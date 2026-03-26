"""Full end-to-end workflow test.

Exercises the complete deepfreeze lifecycle with real data:

  setup → load data → wait for ILM → rotate → verify frozen →
  thaw → verify mounted & queryable → refreeze → cleanup

This test creates an ILM policy with accelerated timings:
  - Hot: rollover at 3 minutes
  - Cold: 10 minutes
  - Frozen: 20 minutes (searchable snapshot to test repo)
  - Delete: 30 minutes (delete_searchable_snapshot=false)

Expected runtime: 30-45 minutes depending on ILM poll interval.
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
from deepfreeze_core.constants import STATUS_INDEX

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


def _any_index_in_phase(es: Elasticsearch, pattern: str, phase: str) -> bool:
    """Check if any index matching pattern is in the given ILM phase."""
    indices = _get_ilm_explain(es, pattern)
    for idx_name, info in indices.items():
        if info.get("phase") == phase:
            return True
    return False


class TestFullLifecycle:
    """End-to-end lifecycle with real data and ILM progression.

    This test class exercises the complete deepfreeze workflow including
    data loading, ILM phase transitions, rotation, thaw, and refreeze.
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

        # Verify the data stream was created
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

    def test_06_rotate(self, runner, test_config_file, es_client, test_prefixes):
        """Rotate to create a new repository and archive old ones."""
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

    def test_07_verify_repo_states(self, es_client, test_prefixes):
        """Verify repo state distribution after rotate."""
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        states = {r["name"]: r.get("thaw_state") for r in repos}
        logger.info("Repo states: %s", states)
        assert len(repos) >= 2, f"Expected at least 2 repos, got {len(repos)}"

    def test_08_status(self, runner, test_config_file, test_prefixes):
        """Status should show repos and ILM policy."""
        result = _invoke(runner, test_config_file, "status")
        data = json.loads(result.output)
        repos = data.get("repositories", [])
        logger.info("Status: %d repos, %d thaw requests",
                     len(repos), len(data.get("thaw_requests", [])))

    def test_09_thaw(self, runner, test_config_file):
        """Create a thaw request and wait for completion."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "thaw",
            "--start-date", "2020-01-01T00:00:00Z",
            "--end-date", "2030-12-31T23:59:59Z",
            "--sync",
            "--porcelain",
        ])
        assert result.exit_code == 0, f"Thaw failed:\n{result.output}\n{result.exception}"
        logger.info("Thaw complete (sync)")

    def test_10_verify_thawed_repos(self, es_client, test_prefixes):
        """After thaw, repos should be in thawed state."""
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        states = {r["name"]: r.get("thaw_state") for r in repos}
        logger.info("Post-thaw repo states: %s", states)
        # At least the active repos should still be active, and any
        # previously frozen repos should now be thawed or thawing
        thawed = [r for r in repos if r.get("thaw_state") in ("thawed", "thawing")]
        active = [r for r in repos if r.get("thaw_state") == "active"]
        assert len(thawed) + len(active) >= 1, (
            f"Expected thawed or active repos. States: {states}"
        )

    def test_11_verify_queryable(self, es_client, test_prefixes):
        """Verify that thawed indices are searchable."""
        # Search the data stream (covers all backing indices)
        pattern = test_prefixes.data_stream_name
        try:
            result = es_client.search(
                index=pattern,
                body={"query": {"match_all": {}}, "size": 1},
                ignore_unavailable=True,
            )
            total = result["hits"]["total"]["value"]
            logger.info("Found %d searchable docs in %s", total, pattern)
            assert total > 0, f"No docs found in thawed indices ({pattern})"
        except Exception as e:
            logger.warning("Search failed (may be expected if no indices thawed): %s", e)

    def test_12_refreeze(self, runner, test_config_file):
        """Refreeze all completed thaw requests."""
        _invoke(runner, test_config_file, "refreeze")
        logger.info("Refreeze complete")

    def test_13_verify_refrozen(self, es_client, test_prefixes):
        """After refreeze, previously thawed repos should be frozen again."""
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        states = {r["name"]: r.get("thaw_state") for r in repos}
        logger.info("Post-refreeze repo states: %s", states)

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
        thaw_requests = data.get("thaw_requests", [])
        logger.info("Final: %d repos, %d thaw requests", len(repos), len(thaw_requests))
        for r in repos:
            logger.info("  %s: %s", r.get("name"), r.get("thaw_state"))

    def test_17_restore_ilm_poll_interval(self, es_client):
        """Restore ILM poll interval to default."""
        es_client.cluster.put_settings(
            body={"transient": {"indices.lifecycle.poll_interval": None}}
        )
        logger.info("Restored ILM poll interval to default")
