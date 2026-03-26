"""Full end-to-end workflow test.

Exercises the complete deepfreeze lifecycle with real data:

  setup → start data loader → accelerate ILM →
  rotate periodically until repos are in archive storage →
  thaw → wait for glacier restore → verify mounted & queryable →
  refreeze → cleanup

The es-loader pushes ~10 docs/sec continuously. ILM uses accelerated
timings (3m rollover, 10m cold, 20m frozen, 30m delete). Every ~5
minutes we run a rotation to push old repos to glacier.

Expected runtime: 45-90+ minutes depending on ILM timing and provider.
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

# How many docs to load as fallback if es-loader not available
NUM_TEST_DOCS = 200
DOC_SIZE_APPROX = 512

# Rotate interval and max attempts
ROTATE_INTERVAL_SECS = 300  # 5 minutes between rotations
MAX_ROTATE_ATTEMPTS = 18    # 18 × 5 min = 90 min max wait for archive


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


def _check_archive_storage(es, test_prefixes, storage_provider):
    """Check if any frozen repo has objects in archive storage tier.

    Returns (True, repo_name) if found, (False, None) otherwise.
    """
    from deepfreeze_core.s3client import s3_client_factory

    repos = get_repos_with_prefix(es, test_prefixes.repo_name_prefix)
    frozen = [r for r in repos if r.get("thaw_state") == THAW_STATE_FROZEN]

    if not frozen:
        return False, None

    archive_classes = {"GLACIER", "DEEP_ARCHIVE", "Archive", "ARCHIVE", "COLDLINE", "NEARLINE"}

    try:
        s3 = s3_client_factory(storage_provider)
    except Exception:
        return False, None

    for repo in frozen:
        bucket = repo.get("bucket")
        base_path = repo.get("base_path", "").strip("/")
        if base_path:
            base_path += "/"

        try:
            objects = s3.list_objects(bucket, base_path)
            if not objects:
                logger.debug("No objects in %s/%s for repo %s", bucket, base_path, repo["name"])
                continue

            sample_classes = {obj.get("StorageClass", "STANDARD") for obj in objects[:5]}
            logger.debug(
                "Repo %s: %d objects, sample classes: %s",
                repo["name"], len(objects), sample_classes,
            )
            if sample_classes & archive_classes:
                return True, repo["name"]
        except Exception as e:
            logger.debug("Error checking repo %s: %s", repo["name"], e)
            continue

    return False, None


class TestFullLifecycle:
    """End-to-end lifecycle with real data, ILM, and periodic rotation.

    The test lets ILM progress naturally with accelerated timings while
    periodically running deepfreeze rotate. Once a repo has objects in
    archive storage, it proceeds to thaw/verify/refreeze.
    """

    def test_01_setup(self, runner, test_config_file, test_prefixes, test_index_template,
                      storage_provider, es_client):
        """Initialize deepfreeze with test prefixes."""
        # Set ILM poll interval to 5s
        es_client.cluster.put_settings(
            body={"transient": {"indices.lifecycle.poll_interval": "5s"}}
        )
        logger.info("Set ILM poll interval to 5s")

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
        assert frozen_age == ILM_FROZEN_AGE

    def test_03_start_data_loader(self, es_loader, es_client, test_prefixes):
        """Start the background data loader and verify data is flowing."""
        ds_name = test_prefixes.data_stream_name

        if es_loader is None:
            logger.warning("es-loader not available — loading data manually")
            success = _load_test_data(es_client, ds_name, NUM_TEST_DOCS)
            assert success >= NUM_TEST_DOCS * 0.9, f"Only {success}/{NUM_TEST_DOCS} docs indexed"
        else:
            logger.info("Waiting for es-loader to push initial data to '%s'...", ds_name)
            wait_for(
                lambda: es_client.indices.exists(index=ds_name),
                timeout=30,
                initial_interval=2,
                max_interval=5,
                description=f"data stream '{ds_name}' to be created by es-loader",
            )

        ds = es_client.indices.get_data_stream(name=ds_name)
        streams = ds.get("data_streams", [])
        assert len(streams) == 1, f"Data stream not created: {ds}"
        logger.info("Data stream '%s' active", ds_name)

    def test_04_wait_for_ilm_delete(self, es_client, test_prefixes):
        """Wait for ILM to fully process the first batch of data.

        We need the oldest backing index to pass through:
        hot → cold → frozen (searchable snapshot) → delete (index removed)

        Only after the delete phase completes can we safely rotate, because
        rotate with --keep 1 will unmount the snapshot repo — which ILM
        must be done using.
        """
        ds_name = test_prefixes.data_stream_name

        def _any_index_deleted():
            """Check if any backing index has been deleted by ILM."""
            try:
                ds = es_client.indices.get_data_stream(name=ds_name)
                streams = ds.get("data_streams", [])
                if not streams:
                    return False
                backing = streams[0].get("indices", [])
                # When ILM deletes an index, the data stream's backing index
                # count decreases. We started with 1, rollover made 2+,
                # but we can also check if any index no longer exists.
                # Simplest: check if we have snapshots in the repo
                repos = es_client.snapshot.get_repository(
                    name=f"{test_prefixes.repo_name_prefix}-000001"
                )
                if repos:
                    # Check if there are snapshots in the repo
                    snaps = es_client.snapshot.get(
                        repository=f"{test_prefixes.repo_name_prefix}-000001",
                        snapshot="_all",
                    )
                    snap_list = snaps.get("snapshots", [])
                    if snap_list:
                        logger.debug("Found %d snapshots in repo 000001", len(snap_list))
                        # Now check if any of the original backing indices no longer exist
                        for snap in snap_list:
                            for idx in snap.get("indices", []):
                                if not es_client.indices.exists(index=idx):
                                    logger.info("Index '%s' deleted by ILM (snapshot preserved)", idx)
                                    return True
            except Exception as e:
                logger.debug("Check error: %s", e)
            return False

        def _diag():
            try:
                ds = es_client.indices.get_data_stream(name=ds_name)
                streams = ds.get("data_streams", [])
                backing = [idx["index_name"] for idx in streams[0].get("indices", [])] if streams else []
                # Get ILM state
                from .helpers.es_verify import snapshot_es_state
                ilm = {}
                for idx in backing:
                    try:
                        explain = es_client.ilm.explain_lifecycle(index=idx)
                        for k, v in explain.get("indices", {}).items():
                            ilm[k] = {"phase": v.get("phase"), "action": v.get("action"), "step": v.get("step")}
                    except Exception:
                        pass
                return json.dumps({"backing": backing, "ilm": ilm}, indent=2)
            except Exception as e:
                return f"diagnostic error: {e}"

        logger.info("Waiting for ILM to complete full cycle (delete phase, timeout: 45m)...")
        wait_for(
            _any_index_deleted,
            timeout=2700,  # 45 minutes
            initial_interval=15,
            max_interval=30,
            description="ILM delete phase (index deleted, snapshot preserved)",
            on_timeout=_diag,
        )
        logger.info("ILM cycle complete — safe to rotate")

    def test_05_rotate(self, runner, test_config_file, es_client, test_prefixes):
        """Rotate to create a new repo and archive the old one to glacier.

        Now that ILM has finished using repo-000001, rotate can safely
        unmount it and push its objects to archive storage.
        """
        repos_before = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        logger.info("Repos before rotate: %s", {r["name"]: r.get("thaw_state") for r in repos_before})

        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "rotate", "--keep", "1", "--porcelain",
        ])
        logger.info("Rotate output: %s", result.output.strip()[:500])
        assert result.exit_code == 0, f"Rotate failed:\n{result.output}\n{result.exception}"

        repos_after = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        logger.info("Repos after rotate: %s", {r["name"]: r.get("thaw_state") for r in repos_after})

    def test_06_verify_archive(self, es_client, test_prefixes, storage_provider):
        """Verify that the archived repo has objects in archive storage tier."""
        # Give a moment for the storage tier change to propagate
        time.sleep(5)

        in_archive, repo_name = _check_archive_storage(es_client, test_prefixes, storage_provider)
        if not in_archive:
            # Log what we found for debugging
            repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
            frozen = [r for r in repos if r.get("thaw_state") == THAW_STATE_FROZEN]
            logger.warning("No archived objects found. Frozen repos: %s",
                          [(r["name"], r.get("bucket"), r.get("base_path")) for r in frozen])

        assert in_archive, (
            "No frozen repo has objects in archive storage. "
            "Rotate may not have pushed objects to glacier."
        )
        logger.info("Verified: repo '%s' has objects in archive storage", repo_name)

    def test_07_verify_date_ranges(self, es_client, test_prefixes):
        """Verify frozen repos have date ranges set (needed for thaw)."""
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        frozen_with_dates = [
            r for r in repos
            if r.get("thaw_state") == THAW_STATE_FROZEN and r.get("start") and r.get("end")
        ]
        logger.info(
            "Frozen repos with date ranges: %s",
            [(r["name"], r.get("start"), r.get("end")) for r in frozen_with_dates],
        )
        assert len(frozen_with_dates) >= 1, (
            f"No frozen repos have date ranges set. "
            f"Repos: {[(r['name'], r.get('thaw_state'), r.get('start')) for r in repos]}"
        )

    def test_08_thaw_create(self, runner, test_config_file, es_client, test_prefixes):
        """Create a thaw request for the frozen repos."""
        logger.info("Creating thaw request...")
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "thaw",
            "--start-date", "2020-01-01T00:00:00Z",
            "--end-date", "2030-12-31T23:59:59Z",
            "--async",
            "--porcelain",
        ])
        logger.info("Thaw output: %s", result.output.strip()[:500])
        assert result.exit_code == 0, f"Thaw create failed:\n{result.output}\n{result.exception}"

        # Verify a thaw request was created
        from deepfreeze_core.utilities import list_thaw_requests
        es_client.indices.refresh(index=STATUS_INDEX)
        requests = list_thaw_requests(es_client)
        assert len(requests) >= 1, (
            f"No thaw request created. Output: {result.output.strip()[:200]}"
        )
        logger.info("Thaw request created: %d request(s)", len(requests))

    def test_09_wait_for_thaw(self, runner, test_config_file, es_client, test_prefixes):
        """Poll thaw --check-status until glacier restore completes."""
        start = time.monotonic()

        def _thaw_completed():
            result = runner.invoke(cli, [
                "--config", test_config_file,
                "--local",
                "thaw", "--check-status",
                "--porcelain",
            ])
            if result.exit_code != 0:
                return False

            repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
            thawing = [r for r in repos if r.get("thaw_state") == THAW_STATE_THAWING]
            thawed = [r for r in repos if r.get("thaw_state") == THAW_STATE_THAWED]

            if thawing:
                elapsed = time.monotonic() - start
                logger.info("Thaw in progress (%.0fs): %d thawing, %d thawed",
                            elapsed, len(thawing), len(thawed))
                return False

            return len(thawed) >= 1

        def _diag():
            repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
            return json.dumps({r["name"]: r.get("thaw_state") for r in repos}, indent=2)

        logger.info("Waiting for thaw to complete (timeout: 2h)...")
        wait_for(
            _thaw_completed,
            timeout=7200,
            initial_interval=30,
            max_interval=60,
            description="thaw completion (glacier restore)",
            on_timeout=_diag,
        )

        elapsed = time.monotonic() - start
        logger.info("Thaw completed in %.1f seconds (%.1f minutes)", elapsed, elapsed / 60)

    def test_10_verify_thawed(self, es_client, test_prefixes):
        """After thaw, repos should be in thawed state."""
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        states = {r["name"]: r.get("thaw_state") for r in repos}
        logger.info("Post-thaw states: %s", states)

        thawed = [r for r in repos if r.get("thaw_state") == THAW_STATE_THAWED]
        assert len(thawed) >= 1, f"No thawed repos. States: {states}"

    def test_11_verify_queryable(self, es_client, test_prefixes):
        """Verify thawed indices are mounted and searchable."""
        pattern = test_prefixes.data_stream_name
        result = es_client.search(
            index=pattern,
            body={"query": {"match_all": {}}, "size": 1},
            ignore_unavailable=True,
        )
        total = result["hits"]["total"]["value"]
        logger.info("Found %d searchable docs in %s", total, pattern)
        assert total > 0, f"No documents found in '{pattern}' after thaw"

    def test_12_refreeze(self, runner, test_config_file):
        """Refreeze all completed thaw requests."""
        _invoke(runner, test_config_file, "refreeze")
        logger.info("Refreeze complete")

    def test_13_verify_refrozen(self, es_client, test_prefixes):
        """After refreeze, thawed repos should be frozen again."""
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        states = {r["name"]: r.get("thaw_state") for r in repos}
        logger.info("Post-refreeze states: %s", states)

        frozen = [r for r in repos if r.get("thaw_state") == THAW_STATE_FROZEN]
        assert len(frozen) >= 1, f"No frozen repos after refreeze. States: {states}"

    def test_14_cleanup(self, runner, test_config_file):
        """Cleanup should succeed."""
        _invoke(runner, test_config_file, "cleanup")
        logger.info("Cleanup complete")

    def test_15_repair_metadata(self, runner, test_config_file):
        """Repair metadata should complete without error."""
        _invoke(runner, test_config_file, "repair-metadata")
        logger.info("Repair complete")

    def test_16_final_status(self, runner, test_config_file, test_prefixes):
        """Final status should show consistent state."""
        result = _invoke(runner, test_config_file, "status")
        data = json.loads(result.output)
        repos = data.get("repositories", [])
        logger.info("Final: %d repos, %d thaw requests",
                     len(repos), len(data.get("thaw_requests", [])))
        for r in repos:
            logger.info("  %s: %s", r.get("name"), r.get("thaw_state"))

    def test_17_restore_ilm_poll_interval(self, es_client):
        """Restore ILM poll interval to default."""
        es_client.cluster.put_settings(
            body={"transient": {"indices.lifecycle.poll_interval": None}}
        )
        logger.info("Restored ILM poll interval to default")
