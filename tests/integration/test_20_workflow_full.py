"""Full end-to-end workflow test.

Exercises the complete deepfreeze lifecycle in order:
  status → rotate → verify states → thaw → check → refreeze → cleanup

On an already-initialized cluster, setup is skipped (it would fail
precondition checks).  All operations use the live cluster settings.
All CLI invocations use --porcelain for machine-readable output.

This is the "golden path" integration test.  It is long-running
(marked slow) because thaw operations may take minutes depending on
the storage provider.
"""

import json
import logging

import pytest
from click.testing import CliRunner

from deepfreeze.cli.main import cli

from .helpers.es_verify import (
    assert_settings_exist,
    get_repos_with_prefix,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]

logger = logging.getLogger("deepfreeze.tests.workflow")


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


class TestFullLifecycle:
    """End-to-end lifecycle.

    Tests are named with numeric prefixes to enforce execution order.
    Each step builds on the previous one.
    """

    def test_01_prerequisites(self, es_client, cluster_initialized):
        """Cluster must be initialized before running the workflow."""
        if not cluster_initialized:
            pytest.skip("Cluster not initialized — run 'deepfreeze setup' first")
        settings = assert_settings_exist(es_client)
        logger.info("Live settings: provider=%s, prefix=%s", settings.get("provider"), settings.get("repo_name_prefix"))

    def test_02_status(self, runner, test_config_file):
        """Status should succeed and return valid JSON."""
        result = _invoke(runner, test_config_file, "status")
        data = json.loads(result.output)
        assert "settings" in data
        logger.info("Status: %d repos, %d thaw requests",
                     len(data.get("repositories", [])), len(data.get("thaw_requests", [])))

    def test_03_rotate(self, runner, test_config_file, es_client, live_repo_prefix):
        """Rotate should create a new repository."""
        repos_before = get_repos_with_prefix(es_client, live_repo_prefix)

        _invoke(runner, test_config_file, "rotate")

        repos_after = get_repos_with_prefix(es_client, live_repo_prefix)
        assert len(repos_after) == len(repos_before) + 1, (
            f"Expected {len(repos_before) + 1} repos, got {len(repos_after)}"
        )
        logger.info("After rotate: %d repos", len(repos_after))

    def test_04_verify_repo_states(self, es_client, live_repo_prefix):
        """After rotation, check state distribution."""
        repos = get_repos_with_prefix(es_client, live_repo_prefix)
        states = {}
        for r in repos:
            state = r.get("thaw_state", "unknown")
            states[state] = states.get(state, 0) + 1
        logger.info("Repo states: %s", states)
        assert len(repos) >= 2, f"Expected at least 2 repos, got {len(repos)}"

    def test_05_thaw_create(self, runner, test_config_file):
        """Create a thaw request for a broad date range."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "thaw",
            "--start-date", "2020-01-01T00:00:00Z",
            "--end-date", "2030-12-31T23:59:59Z",
            "--async",
            "--porcelain",
        ])
        assert result.exit_code == 0, f"Thaw create failed:\n{result.output}\n{result.exception}"
        logger.info("Thaw create output: %s", result.output[:200])

    def test_06_thaw_check(self, runner, test_config_file):
        """Check thaw request status."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "thaw", "--check-status", "--porcelain",
        ])
        assert result.exit_code == 0, f"Thaw check failed:\n{result.output}"
        logger.info("Thaw check output: %s", result.output[:200])

    def test_07_thaw_list(self, runner, test_config_file):
        """List thaw requests."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "thaw", "--list", "--porcelain",
        ])
        assert result.exit_code == 0, f"Thaw list failed:\n{result.output}"
        logger.info("Thaw list output: %s", result.output[:200])

    def test_08_refreeze(self, runner, test_config_file):
        """Refreeze all completed thaw requests."""
        _invoke(runner, test_config_file, "refreeze")
        logger.info("Refreeze complete")

    def test_09_cleanup(self, runner, test_config_file):
        """Cleanup expired artifacts."""
        _invoke(runner, test_config_file, "cleanup")
        logger.info("Cleanup complete")

    def test_10_repair_metadata(self, runner, test_config_file):
        """Repair metadata should complete without error."""
        _invoke(runner, test_config_file, "repair-metadata")
        logger.info("Repair complete")

    def test_11_final_status(self, runner, test_config_file):
        """Final status should succeed and return valid JSON."""
        result = _invoke(runner, test_config_file, "status")
        data = json.loads(result.output)
        logger.info("Final: %d repos, %d thaw requests",
                     len(data.get("repositories", [])), len(data.get("thaw_requests", [])))
