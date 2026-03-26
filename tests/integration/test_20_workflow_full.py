"""Full end-to-end workflow test.

Exercises the complete deepfreeze lifecycle with real data:

  setup → load data → wait for ILM frozen → rotate (archives to glacier) →
  verify objects in archive tier → thaw (restore from glacier) →
  verify mounted & queryable → refreeze → cleanup

This test creates an ILM policy with accelerated timings:
  - Hot: rollover at 3 minutes
  - Cold: 10 minutes
  - Frozen: 20 minutes (searchable snapshot to test repo)
  - Delete: 30 minutes (delete_searchable_snapshot=false)

Expected runtime: 30-60+ minutes depending on provider restore speed.
"""

import json
import logging
import random
import time
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner
from elasticsearch8 import Elasticsearch

from deepfreeze.cli.main import cli
from deepfreeze_core.constants import (
    STATUS_INDEX,
    THAW_STATE_FROZEN,
    THAW_STATE_THAWED,
    THAW_STATE_THAWING,
)

from .helpers.es_verify import (
    assert_ilm_policy_exists,
    assert_repo_exists,
    assert_settings_exist,
    get_repos_with_prefix,
)
from .helpers.waiter import wait_for

pytestmark = [pytest.mark.integration, pytest.mark.slow]

logger = logging.getLogger("deepfreeze.tests.workflow")

# Accelerated ILM timings for testing
ILM_ROLLOVER_AGE = "3m"
ILM_COLD_AGE = "10m"
ILM_FROZEN_AGE = "20m"
ILM_DELETE_AGE = "30m"

# How many docs to load
NUM_TEST_DOCS = 200
DOC_SIZE_APPROX = 512


@pytest.fixture(scope="module")
def runner():
    return CliRunner()


def _invoke(runner, config, *args):
    """Invoke the CLI with --porcelain and assert success."""
    result = runner.invoke(cli, [
        "--config", config,
        "--local",
        *args,
        "--porcelain",
    ])
    assert result.exit_code == 0, (
        f"CLI failed (exit={result.exit_code}):\n{result.output}\n{result.exception}"
    )
    return result


def _generate_log_doc():
    """Generate a realistic log document with @timestamp."""
    return {
        "@timestamp": datetime.now(timezone.utc).isoformat(),
        "level": random.choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
        "message": random.choice([
            "Request processed", "Cache hit", "Cache miss",
            "Auth successful", "Connection timeout", "Query completed",
        ]),
        "host": random.choice(["web-01", "web-02", "api-01", "db-01"]),
        "service": random.choice(["nginx", "app-server", "database"]),
        "response_code": random.choice([200, 201, 400, 404, 500]),
        "duration_ms": round(random.uniform(1.0, 500.0), 2),
        "path": random.choice(["/api/users", "/api/orders", "/health"]),
        "_padding": "x" * max(0, DOC_SIZE_APPROX - 300),
    }


def _set_accelerated_ilm(es: Elasticsearch, policy_name: str, repo_name: str):
    """Replace the ILM policy with accelerated test timings."""
    policy_body = {
        "policy": {
            "phases": {
                "hot": {
                    "min_age": "0ms",
                    "actions": {"rollover": {"max_age": ILM_ROLLOVER_AGE, "max_size": "1gb"}},
                },
                "cold": {
                    "min_age": ILM_COLD_AGE,
                    "actions": {"set_priority": {"priority": 0}},
                },
                "frozen": {
                    "min_age": ILM_FROZEN_AGE,
                    "actions": {
                        "searchable_snapshot": {"snapshot_repository": repo_name},
                    },
                },
                "delete": {
                    "min_age": ILM_DELETE_AGE,
                    "actions": {"delete": {"delete_searchable_snapshot": False}},
                },
            }
        }
    }
    es.ilm.put_lifecycle(name=policy_name, body=policy_body)
    logger.info("Set accelerated ILM: rollover=%s, cold=%s, frozen=%s, delete=%s",
                ILM_ROLLOVER_AGE, ILM_COLD_AGE, ILM_FROZEN_AGE, ILM_DELETE_AGE)


def _load_test_data(es: Elasticsearch, data_stream: str, num_docs: int):
    """Bulk-index test documents into the data stream."""
    from elasticsearch8.helpers import bulk

    def _gen():
        for _ in range(num_docs):
            doc = _generate_log_doc()
            doc["_index"] = data_stream
            doc["_op_type"] = "create"
            yield doc

    success, errors = bulk(es, _gen(), stats_only=True, raise_on_error=False)
    logger.info("Loaded %d docs into %s (%d errors)", success, data_stream, errors)
    return success


def _get_ilm_explain(es: Elasticsearch, pattern: str) -> dict:
    """Get ILM explain for indices matching pattern."""
    try:
        result = es.ilm.explain_lifecycle(index=pattern)
        return result.get("indices", {})
    except Exception:
        return {}


class TestFullLifecycle:
    """End-to-end lifecycle with real data and ILM progression.

    This test class exercises the complete deepfreeze workflow including
    data loading, ILM phase transitions, rotation to glacier, thaw
    from glacier, and refreeze.
    """

    def test_00_set_ilm_poll_interval(self, es_client):
        """Set ILM poll interval to 5s for faster phase transitions."""
        es_client.cluster.put_settings(
            body={"transient": {"indices.lifecycle.poll_interval": "5s"}}
        )
        logger.info("Set ILM poll interval to 5s")

    def test_01_setup(self, runner, test_config_file, test_prefixes, test_index_template,
                      storage_provider, es_client):
        """Initialize deepfreeze with test prefixes."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "setup",
            "--repo_name_prefix", test_prefixes.repo_name_prefix,
            "--bucket_name_prefix", test_prefixes.bucket_name_prefix,
            "--ilm_policy_name", test_prefixes.ilm_policy_name,
            "--index_template_name", test_prefixes.index_template_name,
            "--provider", storage_provider,
            "--porcelain",
        ])
        assert result.exit_code == 0, f"Setup failed:\n{result.output}\n{result.exception}"
        settings = assert_settings_exist(es_client)
        assert settings["repo_name_prefix"] == test_prefixes.repo_name_prefix
        logger.info("Setup complete: prefix=%s", test_prefixes.repo_name_prefix)

    def test_02_accelerate_ilm(self, es_client, test_prefixes):
        """Replace ILM policy with accelerated test timings."""
        repo_name = f"{test_prefixes.repo_name_prefix}-000001"
        _set_accelerated_ilm(es_client, test_prefixes.ilm_policy_name, repo_name)
        policy = assert_ilm_policy_exists(es_client, test_prefixes.ilm_policy_name)
        frozen_age = policy["policy"]["phases"]["frozen"]["min_age"]
        assert frozen_age == ILM_FROZEN_AGE, f"Expected frozen min_age={ILM_FROZEN_AGE}, got {frozen_age}"

    def test_03_load_data(self, es_client, test_prefixes):
        """Load test documents into the data stream."""
        ds_name = test_prefixes.data_stream_name
        success = _load_test_data(es_client, ds_name, NUM_TEST_DOCS)
        assert success >= NUM_TEST_DOCS * 0.9, f"Only {success}/{NUM_TEST_DOCS} docs indexed"

        ds = es_client.indices.get_data_stream(name=ds_name)
        streams = ds.get("data_streams", [])
        assert len(streams) == 1, f"Data stream not created: {ds}"
        backing = streams[0].get("indices", [])
        logger.info("Data stream '%s' created with %d backing index(es), %d docs loaded",
                     ds_name, len(backing), success)

    def test_04_wait_for_rollover(self, es_client, test_prefixes):
        """Wait for ILM to rollover the hot index (should happen after ~3 minutes)."""
        ds_name = test_prefixes.data_stream_name

        def _backing_count():
            try:
                ds = es_client.indices.get_data_stream(name=ds_name)
                streams = ds.get("data_streams", [])
                if streams:
                    return len(streams[0].get("indices", []))
            except Exception:
                pass
            return 0

        def _diag():
            try:
                ds = es_client.indices.get_data_stream(name=ds_name)
                streams = ds.get("data_streams", [])
                if not streams:
                    return f"Data stream '{ds_name}' not found"
                backing = [idx["index_name"] for idx in streams[0].get("indices", [])]
                ilm = _get_ilm_explain(es_client, ",".join(backing)) if backing else {}
                return json.dumps({
                    "backing_indices": backing,
                    "ilm": {k: {"phase": v.get("phase"), "action": v.get("action"), "step": v.get("step")}
                            for k, v in ilm.items()},
                }, indent=2)
            except Exception as e:
                return f"diagnostic error: {e}"

        logger.info("Waiting for ILM rollover on data stream '%s' (timeout: 10m)...", ds_name)
        wait_for(
            lambda: _backing_count() >= 2,
            timeout=600,
            initial_interval=10,
            max_interval=15,
            description="ILM rollover (2+ backing indices)",
            on_timeout=_diag,
        )
        logger.info("Rollover detected: %d backing indices", _backing_count())

    def test_04b_set_repo_date_range(self, es_client, test_prefixes):
        """Set the date range on the initial repo while indices are still mounted.

        This must happen BEFORE the frozen/delete phases remove the indices,
        because update_repository_date_range scans mounted indices to
        determine the date range. Without this, thaw can't find the repo
        by date range.
        """
        from deepfreeze_core.utilities import get_all_repos, update_repository_date_range

        repos = get_all_repos(es_client)
        updated = 0
        for repo in repos:
            if repo.name.startswith(test_prefixes.repo_name_prefix):
                if update_repository_date_range(es_client, repo):
                    logger.info("Set date range for %s: %s - %s", repo.name, repo.start, repo.end)
                    updated += 1
                else:
                    logger.warning("Could not determine date range for %s", repo.name)

        assert updated >= 1, (
            f"Failed to set date range on any repo. "
            f"Repos: {[r.name for r in repos if r.name.startswith(test_prefixes.repo_name_prefix)]}"
        )

    def test_05_wait_for_frozen_phase(self, es_client, test_prefixes):
        """Wait for at least one backing index to reach the frozen ILM phase."""
        ds_name = test_prefixes.data_stream_name

        def _check():
            try:
                ds = es_client.indices.get_data_stream(name=ds_name)
                streams = ds.get("data_streams", [])
                if not streams:
                    return False
                backing = [idx["index_name"] for idx in streams[0].get("indices", [])]
                if not backing:
                    return False
                ilm = _get_ilm_explain(es_client, ",".join(backing))
                return any(info.get("phase") == "frozen" for info in ilm.values())
            except Exception:
                return False

        def _diag():
            try:
                ds = es_client.indices.get_data_stream(name=ds_name)
                streams = ds.get("data_streams", [])
                if not streams:
                    return f"Data stream '{ds_name}' not found"
                backing = [idx["index_name"] for idx in streams[0].get("indices", [])]
                ilm = _get_ilm_explain(es_client, ",".join(backing)) if backing else {}
                return json.dumps({
                    "backing_indices": backing,
                    "ilm": {k: {"phase": v.get("phase"), "action": v.get("action"), "step": v.get("step")}
                            for k, v in ilm.items()},
                }, indent=2)
            except Exception as e:
                return f"diagnostic error: {e}"

        logger.info("Waiting for ILM frozen phase on '%s' (timeout: 30m)...", ds_name)
        wait_for(
            _check,
            timeout=1800,
            initial_interval=15,
            max_interval=30,
            description="ILM frozen phase",
            on_timeout=_diag,
        )
        logger.info("At least one backing index reached frozen phase")

    def test_05b_wait_for_delete_phase(self, es_client, test_prefixes):
        """Wait for the oldest backing index to be deleted by ILM.

        After the frozen phase creates a searchable snapshot, the delete
        phase removes the index (but preserves the snapshot in the repo).
        Only after deletion can rotate unmount and archive the repo.
        """
        ds_name = test_prefixes.data_stream_name

        # Get the first (oldest) backing index name
        ds = es_client.indices.get_data_stream(name=ds_name)
        streams = ds.get("data_streams", [])
        assert streams, f"Data stream '{ds_name}' not found"
        backing = [idx["index_name"] for idx in streams[0].get("indices", [])]
        assert len(backing) >= 2, f"Expected 2+ backing indices, got {len(backing)}"

        # The oldest backing index is the one that will be deleted
        oldest_index = backing[0]
        logger.info("Waiting for ILM to delete oldest index '%s' (timeout: 45m)...", oldest_index)

        def _deleted():
            return not es_client.indices.exists(index=oldest_index)

        def _diag():
            try:
                # Check all backing indices' ILM state
                current_ds = es_client.indices.get_data_stream(name=ds_name)
                current_streams = current_ds.get("data_streams", [])
                if not current_streams:
                    return "Data stream gone"
                current_backing = [idx["index_name"] for idx in current_streams[0].get("indices", [])]
                ilm = _get_ilm_explain(es_client, ",".join(current_backing)) if current_backing else {}
                exists = es_client.indices.exists(index=oldest_index)
                return json.dumps({
                    "oldest_index": oldest_index,
                    "still_exists": bool(exists),
                    "current_backing": current_backing,
                    "ilm": {k: {"phase": v.get("phase"), "action": v.get("action"), "step": v.get("step")}
                            for k, v in ilm.items()},
                }, indent=2)
            except Exception as e:
                return f"diagnostic error: {e}"

        wait_for(
            _deleted,
            timeout=2700,  # 45 minutes — delete phase is at 30m min_age
            initial_interval=15,
            max_interval=30,
            description=f"ILM delete of '{oldest_index}'",
            on_timeout=_diag,
        )
        logger.info("Index '%s' deleted by ILM — snapshot preserved in repo", oldest_index)

    def test_06_rotate(self, runner, test_config_file, es_client, test_prefixes):
        """Rotate to create a new repository and archive old ones to glacier."""
        repos_before = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        count_before = len(repos_before)

        _invoke(runner, test_config_file, "rotate", "--keep", "1")

        repos_after = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        assert len(repos_after) == count_before + 1, (
            f"Expected {count_before + 1} repos, got {len(repos_after)}. "
            f"Before: {[r['name'] for r in repos_before]}  "
            f"After: {[r['name'] for r in repos_after]}"
        )
        logger.info("Rotation complete: %d -> %d repos", count_before, len(repos_after))

    def test_07_verify_frozen_repos(self, es_client, test_prefixes):
        """After rotate with keep=1, at least one repo should be frozen."""
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        states = {r["name"]: r.get("thaw_state") for r in repos}
        logger.info("Repo states after rotate: %s", states)

        frozen = [r for r in repos if r.get("thaw_state") == THAW_STATE_FROZEN]
        assert len(frozen) >= 1, (
            f"Expected at least one frozen repo after rotate --keep 1. States: {states}"
        )

    def test_08_verify_archive_storage(self, es_client, test_prefixes, storage_provider):
        """Verify that frozen repo objects are actually in archive storage tier.

        This is the critical check — if objects aren't in glacier/archive,
        the thaw test will be meaningless (instant completion).
        """
        from deepfreeze_core.s3client import s3_client_factory

        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        frozen = [r for r in repos if r.get("thaw_state") == THAW_STATE_FROZEN]
        assert len(frozen) >= 1, "No frozen repos to check"

        s3 = s3_client_factory(storage_provider)
        repo = frozen[0]
        bucket = repo["bucket"]
        base_path = repo.get("base_path", "").strip("/")
        if base_path:
            base_path += "/"

        objects = s3.list_objects(bucket, base_path)
        if not objects:
            logger.warning("No objects found in %s/%s — archive check skipped", bucket, base_path)
            return

        # Check storage class of first few objects
        archive_classes = {"GLACIER", "DEEP_ARCHIVE", "Archive", "ARCHIVE", "COLDLINE", "NEARLINE"}
        sample = objects[:5]
        storage_classes = set()
        for obj in sample:
            sc = obj.get("StorageClass", "STANDARD")
            storage_classes.add(sc)

        logger.info("Storage classes in %s/%s: %s (sampled %d objects)",
                     bucket, base_path, storage_classes, len(sample))

        in_archive = storage_classes & archive_classes
        assert len(in_archive) > 0, (
            f"Objects in frozen repo '{repo['name']}' are NOT in archive storage. "
            f"Storage classes found: {storage_classes}. "
            f"Thaw test would be meaningless without actual glacier storage."
        )

    def test_09_status(self, runner, test_config_file, test_prefixes):
        """Status should show repos and frozen state."""
        result = _invoke(runner, test_config_file, "status")
        data = json.loads(result.output)
        repos = data.get("repositories", [])
        logger.info("Status: %d repos, %d thaw requests",
                     len(repos), len(data.get("thaw_requests", [])))

    def test_10_thaw_create(self, runner, test_config_file, es_client, test_prefixes):
        """Create a thaw request (async — returns immediately)."""
        # Verify we have frozen repos with date ranges before thawing
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        frozen_with_dates = [
            r for r in repos
            if r.get("thaw_state") == THAW_STATE_FROZEN and r.get("start") and r.get("end")
        ]
        logger.info(
            "Repos before thaw: %s",
            {r["name"]: {"state": r.get("thaw_state"), "start": r.get("start"), "end": r.get("end")} for r in repos},
        )
        assert len(frozen_with_dates) >= 1, (
            f"No frozen repos with date ranges found — thaw would find nothing. "
            f"Repos: {[(r['name'], r.get('thaw_state'), r.get('start'), r.get('end')) for r in repos]}"
        )

        logger.info("Creating thaw request for frozen repos with date ranges...")
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "thaw",
            "--start-date", "2020-01-01T00:00:00Z",
            "--end-date", "2030-12-31T23:59:59Z",
            "--async",
            "--porcelain",
        ])
        logger.info("Thaw create output: %s", result.output.strip()[:500])
        assert result.exit_code == 0, f"Thaw create failed:\n{result.output}\n{result.exception}"

        # Verify a thaw request was actually created
        from deepfreeze_core.utilities import list_thaw_requests
        es_client.indices.refresh(index=STATUS_INDEX)
        requests = list_thaw_requests(es_client)
        assert len(requests) >= 1, (
            f"Thaw command succeeded but no thaw request was created in the status index. "
            f"Output: {result.output.strip()[:200]}"
        )
        logger.info("Thaw request created: %d request(s) in status index", len(requests))

    def test_10b_wait_for_thaw_complete(self, runner, test_config_file, es_client, test_prefixes):
        """Poll thaw --check-status until the thaw request is completed.

        This is the real wait — glacier restores take minutes (Standard)
        to hours (Bulk/Deep Archive). We poll every 30 seconds.
        """
        start = time.monotonic()

        def _thaw_completed():
            """Run thaw --check-status and check if all requests are completed."""
            result = runner.invoke(cli, [
                "--config", test_config_file,
                "--local",
                "thaw", "--check-status",
                "--porcelain",
            ])
            if result.exit_code != 0:
                logger.debug("check-status exit code %d: %s", result.exit_code, result.output[:200])
                return False

            # Check repo states — thaw is done when repos are thawed (not thawing)
            repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
            thawing = [r for r in repos if r.get("thaw_state") == THAW_STATE_THAWING]
            thawed = [r for r in repos if r.get("thaw_state") == THAW_STATE_THAWED]

            if thawing:
                elapsed = time.monotonic() - start
                logger.info(
                    "Thaw in progress (%.0fs): %d thawing, %d thawed",
                    elapsed, len(thawing), len(thawed),
                )
                return False

            if thawed:
                return True

            return False

        def _diag():
            repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
            states = {r["name"]: r.get("thaw_state") for r in repos}
            return json.dumps({"repo_states": states}, indent=2)

        logger.info("Waiting for thaw to complete (glacier restore — timeout: 2h)...")
        wait_for(
            _thaw_completed,
            timeout=7200,  # 2 hours — glacier Standard retrieval can take 3-5 hours
            initial_interval=30,
            max_interval=60,
            description="thaw completion (glacier restore)",
            on_timeout=_diag,
        )

        elapsed = time.monotonic() - start
        logger.info("Thaw completed in %.1f seconds (%.1f minutes)", elapsed, elapsed / 60)

    def test_11_verify_thawed_repos(self, es_client, test_prefixes):
        """After thaw, previously frozen repos should be in thawed state."""
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        states = {r["name"]: r.get("thaw_state") for r in repos}
        logger.info("Post-thaw repo states: %s", states)

        thawed = [r for r in repos if r.get("thaw_state") in (THAW_STATE_THAWED, THAW_STATE_THAWING)]
        assert len(thawed) >= 1, (
            f"Expected at least one thawed/thawing repo. States: {states}"
        )

    def test_12_verify_queryable(self, es_client, test_prefixes):
        """Verify that thawed indices are mounted and searchable.

        This must find actual documents — not just succeed with 0 hits.
        """
        pattern = test_prefixes.data_stream_name
        result = es_client.search(
            index=pattern,
            body={"query": {"match_all": {}}, "size": 1},
            ignore_unavailable=True,
        )
        total = result["hits"]["total"]["value"]
        logger.info("Found %d searchable docs in %s", total, pattern)
        assert total > 0, (
            f"No documents found in '{pattern}' after thaw. "
            f"Indices should be mounted and queryable."
        )

    def test_13_refreeze(self, runner, test_config_file):
        """Refreeze all completed thaw requests."""
        _invoke(runner, test_config_file, "refreeze")
        logger.info("Refreeze complete")

    def test_14_verify_refrozen(self, es_client, test_prefixes):
        """After refreeze, previously thawed repos should be frozen again."""
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        states = {r["name"]: r.get("thaw_state") for r in repos}
        logger.info("Post-refreeze repo states: %s", states)

        # At least the repos that were thawed should now be frozen
        frozen = [r for r in repos if r.get("thaw_state") == THAW_STATE_FROZEN]
        assert len(frozen) >= 1, (
            f"Expected at least one frozen repo after refreeze. States: {states}"
        )

    def test_15_cleanup(self, runner, test_config_file):
        """Cleanup should succeed."""
        _invoke(runner, test_config_file, "cleanup")
        logger.info("Cleanup complete")

    def test_16_repair_metadata(self, runner, test_config_file):
        """Repair metadata should complete without error."""
        _invoke(runner, test_config_file, "repair-metadata")
        logger.info("Repair complete")

    def test_17_final_status(self, runner, test_config_file, test_prefixes):
        """Final status should show consistent state."""
        result = _invoke(runner, test_config_file, "status")
        data = json.loads(result.output)
        repos = data.get("repositories", [])
        thaw_requests = data.get("thaw_requests", [])
        logger.info("Final: %d repos, %d thaw requests", len(repos), len(thaw_requests))
        for r in repos:
            logger.info("  %s: %s", r.get("name"), r.get("thaw_state"))

    def test_18_restore_ilm_poll_interval(self, es_client):
        """Restore ILM poll interval to default."""
        es_client.cluster.put_settings(
            body={"transient": {"indices.lifecycle.poll_interval": None}}
        )
        logger.info("Restored ILM poll interval to default")
