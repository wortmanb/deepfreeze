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
MAX_ROTATE_ATTEMPTS = 12    # 12 × 5 min = 60 min max wait for archive


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
                continue

            sample_classes = {obj.get("StorageClass", "STANDARD") for obj in objects[:5]}
            if sample_classes & archive_classes:
                return True, repo["name"]
        except Exception:
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

    def test_04_rotate_until_archive(self, runner, test_config_file, es_client,
                                      test_prefixes, storage_provider):
        """Rotate periodically until at least one repo has objects in archive storage.

        This is the main waiting loop. Every 5 minutes:
        1. Run deepfreeze rotate (updates date ranges, creates new repo, archives old)
        2. Check if any frozen repo has objects in glacier/archive tier
        3. If yes, proceed to thaw tests

        Timeout: 60 minutes (12 rotations × 5 min)
        """
        start = time.monotonic()

        for attempt in range(1, MAX_ROTATE_ATTEMPTS + 1):
            elapsed = time.monotonic() - start
            logger.info(
                "=== Rotation attempt %d/%d (%.0f min elapsed) ===",
                attempt, MAX_ROTATE_ATTEMPTS, elapsed / 60,
            )

            # Log current state
            repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
            states = {r["name"]: r.get("thaw_state") for r in repos}
            logger.info("Repo states: %s", states)

            # Run rotate
            result = runner.invoke(cli, [
                "--config", test_config_file,
                "--local",
                "rotate", "--keep", "1", "--porcelain",
            ])
            if result.exit_code != 0:
                logger.warning("Rotate failed (attempt %d): %s", attempt, result.output[:200])
            else:
                logger.info("Rotate succeeded")

            # Check if any frozen repo has objects in archive storage
            in_archive, repo_name = _check_archive_storage(es_client, test_prefixes, storage_provider)
            if in_archive:
                elapsed = time.monotonic() - start
                logger.info(
                    "Found repo '%s' with objects in archive storage after %.0f min",
                    repo_name, elapsed / 60,
                )
                return  # Success — proceed to thaw tests

            # Wait before next rotation
            if attempt < MAX_ROTATE_ATTEMPTS:
                logger.info("No archived repos yet — waiting %ds before next rotation...", ROTATE_INTERVAL_SECS)
                time.sleep(ROTATE_INTERVAL_SECS)

        # If we get here, no repos reached archive storage
        elapsed = time.monotonic() - start
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        states = {r["name"]: r.get("thaw_state") for r in repos}
        pytest.fail(
            f"No repo reached archive storage after {MAX_ROTATE_ATTEMPTS} rotations "
            f"({elapsed / 60:.0f} min). Final states: {states}"
        )

    def test_05_verify_archive_storage(self, es_client, test_prefixes, storage_provider):
        """Verify that at least one frozen repo has objects in archive tier."""
        in_archive, repo_name = _check_archive_storage(es_client, test_prefixes, storage_provider)
        assert in_archive, "No frozen repo with archived objects found"
        logger.info("Verified: repo '%s' has objects in archive storage", repo_name)

    def test_06_verify_date_ranges(self, es_client, test_prefixes):
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

    def test_07_status(self, runner, test_config_file):
        """Status should show repos in various states."""
        result = _invoke(runner, test_config_file, "status")
        data = json.loads(result.output)
        logger.info("Status: %d repos, %d thaw requests",
                     len(data.get("repositories", [])), len(data.get("thaw_requests", [])))

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
