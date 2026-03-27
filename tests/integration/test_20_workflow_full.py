"""Full end-to-end workflow test.

Mirrors the real-world deepfreeze usage pattern:

  1. Setup (ILM policies, templates, buckets, repos)
  2. Start continuous data ingestion (es-loader)
  3. Accelerate ILM timings for testing (3m/10m/20m/30m)
  4. Rotate on a schedule (~every 5 min), just like a cron job
     - Each rotation updates date ranges, creates new repos,
       and archives old ones to glacier when keep count is exceeded
  5. Once a repo is archived to glacier, create a thaw request
  6. Continue rotating while waiting for the thaw to complete
  7. Verify thawed indices are mounted and queryable
  8. Rotate again — verify thawed repo survives rotation
  9. Refreeze, cleanup

Expected runtime: 45-120+ minutes depending on ILM timing and
provider restore speed.
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

# Accelerated ILM timings
ILM_ROLLOVER_AGE = "3m"
ILM_COLD_AGE = "10m"
ILM_FROZEN_AGE = "20m"
ILM_DELETE_AGE = "30m"

# Rotation schedule
ROTATE_INTERVAL_SECS = 300   # 5 minutes between rotations
ROTATE_KEEP = 1              # keep 1 repo mounted
MAX_TOTAL_TIME_SECS = 7200   # 2 hour overall timeout

# Fallback if es-loader not available
NUM_TEST_DOCS = 200
DOC_SIZE_APPROX = 512


@pytest.fixture(scope="module")
def runner():
    return CliRunner(mix_stderr=False)


def _run_cli(runner, config, *args):
    """Invoke the CLI with --porcelain and return the result (no assertion)."""
    return runner.invoke(cli, [
        "--config", config,
        "--local",
        *args,
        "--porcelain",
    ])


def _invoke(runner, config, *args):
    """Invoke the CLI with --porcelain and assert success."""
    result = _run_cli(runner, config, *args)
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


def _load_test_data(es, data_stream, num_docs):
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


def _set_accelerated_ilm(es, policy_name, repo_name):
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
            logger.debug("Repo %s: %d objects, storage classes: %s",
                        repo["name"], len(objects), sample_classes)
            if sample_classes & archive_classes:
                return True, repo["name"]
        except Exception as e:
            logger.debug("Error checking repo %s: %s", repo["name"], e)
            continue

    return False, None


def _log_state(es, test_prefixes, label=""):
    """Log the current state of all repos for debugging."""
    repos = get_repos_with_prefix(es, test_prefixes.repo_name_prefix)
    states = {r["name"]: {"state": r.get("thaw_state"), "start": r.get("start"), "end": r.get("end")}
              for r in repos}
    logger.info("%sRepo states: %s", f"[{label}] " if label else "", json.dumps(states, default=str))
    return repos


class TestFullLifecycle:
    """End-to-end lifecycle mirroring real-world deepfreeze usage."""

    # -- Phase 1: Setup --

    def test_01_setup(self, runner, test_config_file, test_prefixes, test_index_template,
                      storage_provider, es_client):
        """Initialize deepfreeze and set ILM poll interval."""
        es_client.cluster.put_settings(
            body={"transient": {"indices.lifecycle.poll_interval": "5s"}}
        )

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
        assert policy["policy"]["phases"]["frozen"]["min_age"] == ILM_FROZEN_AGE

    def test_03_start_data_loader(self, es_loader, es_client, test_prefixes):
        """Start continuous data ingestion."""
        ds_name = test_prefixes.data_stream_name

        if es_loader is None:
            logger.warning("es-loader not available — loading data manually")
            _load_test_data(es_client, ds_name, NUM_TEST_DOCS)
        else:
            logger.info("Waiting for es-loader to create data stream '%s'...", ds_name)
            wait_for(
                lambda: es_client.indices.exists(index=ds_name),
                timeout=30,
                initial_interval=2,
                max_interval=5,
                description=f"data stream '{ds_name}'",
            )

        ds = es_client.indices.get_data_stream(name=ds_name)
        assert len(ds.get("data_streams", [])) == 1
        logger.info("Data stream '%s' active", ds_name)

    # -- Phase 2: Rotate until archived --

    def test_04_rotate_until_archived(self, runner, test_config_file, es_client,
                                       test_prefixes, storage_provider):
        """Rotate on a schedule until at least one repo is archived to glacier.

        Mimics a cron job running deepfreeze rotate every 5 minutes.
        Each rotation:
        - Updates date ranges on mounted repos
        - Creates a new repo
        - Archives old repos (when keep count exceeded) by pushing to glacier

        We keep rotating until _check_archive_storage finds objects in
        archive tier, then proceed to thaw.
        """
        start = time.monotonic()
        rotation_count = 0

        while True:
            elapsed = time.monotonic() - start
            if elapsed > MAX_TOTAL_TIME_SECS:
                _log_state(es_client, test_prefixes, "TIMEOUT")
                pytest.fail(
                    f"No repo reached archive storage after {rotation_count} rotations "
                    f"({elapsed / 60:.0f} min)"
                )

            rotation_count += 1
            logger.info(
                "=== Rotation %d (%.0f min elapsed) ===",
                rotation_count, elapsed / 60,
            )
            _log_state(es_client, test_prefixes, f"pre-rotate-{rotation_count}")

            # Run rotate
            result = _run_cli(runner, test_config_file, "rotate", "--keep", str(ROTATE_KEEP))
            if result.exit_code != 0:
                logger.warning("Rotate %d failed: %s", rotation_count, result.output.strip()[:300])
            else:
                logger.info("Rotate %d succeeded: %s", rotation_count, result.output.strip()[:300])

            _log_state(es_client, test_prefixes, f"post-rotate-{rotation_count}")

            # Check if any frozen repo has objects in archive storage
            in_archive, repo_name = _check_archive_storage(es_client, test_prefixes, storage_provider)
            if in_archive:
                logger.info(
                    "SUCCESS: Repo '%s' has objects in archive storage after %d rotations (%.0f min)",
                    repo_name, rotation_count, elapsed / 60,
                )
                return

            # Wait before next rotation
            logger.info("No archived repos yet — sleeping %ds...", ROTATE_INTERVAL_SECS)
            time.sleep(ROTATE_INTERVAL_SECS)

    # -- Phase 3: Thaw --

    def test_05_thaw_create(self, runner, test_config_file, es_client, test_prefixes):
        """Create a thaw request for the archived repos."""
        # Verify we have frozen repos with date ranges
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        frozen_with_dates = [
            r for r in repos
            if r.get("thaw_state") == THAW_STATE_FROZEN and r.get("start") and r.get("end")
        ]
        logger.info("Frozen repos with dates: %s",
                    [(r["name"], r.get("start"), r.get("end")) for r in frozen_with_dates])
        assert len(frozen_with_dates) >= 1, (
            f"No frozen repos with date ranges. "
            f"All repos: {[(r['name'], r.get('thaw_state'), r.get('start')) for r in repos]}"
        )

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
        assert result.exit_code == 0, f"Thaw failed:\n{result.output}\n{result.exception}"

        # Verify request was created
        from deepfreeze_core.utilities import list_thaw_requests
        es_client.indices.refresh(index=STATUS_INDEX)
        requests = list_thaw_requests(es_client)
        assert len(requests) >= 1, f"No thaw request created. Output: {result.output[:200]}"
        logger.info("Thaw request created (%d total)", len(requests))

    def test_06_wait_for_thaw(self, runner, test_config_file, es_client, test_prefixes):
        """Poll thaw --check-status until restore completes. Continue rotating."""
        start = time.monotonic()
        last_rotate = time.monotonic()

        def _check_and_rotate():
            nonlocal last_rotate

            # Run a rotation if it's time (keep the cron going)
            now = time.monotonic()
            if now - last_rotate >= ROTATE_INTERVAL_SECS:
                logger.info("Running scheduled rotation during thaw wait...")
                result = _run_cli(runner, test_config_file, "rotate", "--keep", str(ROTATE_KEEP))
                if result.exit_code == 0:
                    logger.info("Rotation during thaw succeeded")
                else:
                    logger.debug("Rotation during thaw: %s", result.output.strip()[:200])
                last_rotate = now

            # Check thaw status
            result = _run_cli(runner, test_config_file, "thaw", "--check-status")
            if result.exit_code != 0:
                return False

            # Check repo states
            repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
            thawing = [r for r in repos if r.get("thaw_state") == THAW_STATE_THAWING]
            thawed = [r for r in repos if r.get("thaw_state") == THAW_STATE_THAWED]

            elapsed = time.monotonic() - start
            if thawing:
                logger.info("Thaw in progress (%.0fs): %d thawing, %d thawed",
                            elapsed, len(thawing), len(thawed))
                return False

            return len(thawed) >= 1

        def _diag():
            repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
            return json.dumps({r["name"]: r.get("thaw_state") for r in repos}, indent=2)

        logger.info("Waiting for thaw to complete (timeout: 2h)...")
        wait_for(
            _check_and_rotate,
            timeout=7200,
            initial_interval=30,
            max_interval=60,
            description="thaw completion (glacier restore)",
            on_timeout=_diag,
        )

        elapsed = time.monotonic() - start
        logger.info("Thaw completed in %.1f min", elapsed / 60)

    # -- Phase 4: Verify --

    def test_07_verify_thawed(self, es_client, test_prefixes):
        """Thawed repos should be in thawed state."""
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        states = {r["name"]: r.get("thaw_state") for r in repos}
        logger.info("Post-thaw states: %s", states)

        thawed = [r for r in repos if r.get("thaw_state") == THAW_STATE_THAWED]
        assert len(thawed) >= 1, f"No thawed repos. States: {states}"

    def test_08_verify_queryable(self, es_client, test_prefixes):
        """Thawed indices should be mounted and searchable."""
        pattern = test_prefixes.data_stream_name
        result = es_client.search(
            index=pattern,
            body={"query": {"match_all": {}}, "size": 1},
            ignore_unavailable=True,
        )
        total = result["hits"]["total"]["value"]
        logger.info("Found %d searchable docs in %s", total, pattern)
        assert total > 0, f"No documents found in '{pattern}' after thaw"

    def test_09_rotate_preserves_thawed(self, runner, test_config_file, es_client, test_prefixes):
        """A rotation while repos are thawed should NOT disturb them."""
        # Record thawed repos before rotation
        repos_before = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        thawed_before = {r["name"] for r in repos_before if r.get("thaw_state") == THAW_STATE_THAWED}
        logger.info("Thawed repos before rotate: %s", thawed_before)
        assert len(thawed_before) >= 1

        # Run another rotation
        result = _run_cli(runner, test_config_file, "rotate", "--keep", str(ROTATE_KEEP))
        logger.info("Rotate during thaw: exit=%d, output=%s", result.exit_code, result.output.strip()[:300])

        # Verify thawed repos survived
        repos_after = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        thawed_after = {r["name"] for r in repos_after if r.get("thaw_state") == THAW_STATE_THAWED}
        logger.info("Thawed repos after rotate: %s", thawed_after)

        assert thawed_before.issubset(thawed_after), (
            f"Rotation disturbed thawed repos! "
            f"Before: {thawed_before}, After: {thawed_after}"
        )

    # -- Phase 5: Refreeze and cleanup --

    def test_10_refreeze(self, runner, test_config_file):
        """Refreeze all completed thaw requests."""
        _invoke(runner, test_config_file, "refreeze")
        logger.info("Refreeze complete")

    def test_11_verify_refrozen(self, es_client, test_prefixes):
        """Thawed repos should be frozen again."""
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        states = {r["name"]: r.get("thaw_state") for r in repos}
        logger.info("Post-refreeze states: %s", states)

        frozen = [r for r in repos if r.get("thaw_state") == THAW_STATE_FROZEN]
        assert len(frozen) >= 1, f"No frozen repos after refreeze. States: {states}"

    def test_12_cleanup(self, runner, test_config_file):
        """Cleanup expired artifacts."""
        _invoke(runner, test_config_file, "cleanup")
        logger.info("Cleanup complete")

    def test_13_repair_metadata(self, runner, test_config_file):
        """Repair metadata should complete without error."""
        _invoke(runner, test_config_file, "repair-metadata")
        logger.info("Repair complete")

    def test_14_final_status(self, runner, test_config_file, test_prefixes):
        """Final status should show consistent state."""
        result = _invoke(runner, test_config_file, "status")
        data = json.loads(result.output)
        repos = data.get("repositories", [])
        logger.info("Final: %d repos, %d thaw requests",
                     len(repos), len(data.get("thaw_requests", [])))
        for r in repos:
            logger.info("  %s: %s (dates: %s - %s)",
                        r.get("name"), r.get("thaw_state"), r.get("start"), r.get("end"))

    def test_15_restore_ilm_poll_interval(self, es_client):
        """Restore ILM poll interval to default."""
        es_client.cluster.put_settings(
            body={"transient": {"indices.lifecycle.poll_interval": None}}
        )
        logger.info("Restored ILM poll interval to default")
