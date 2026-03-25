"""Full end-to-end workflow test.

Exercises the complete deepfreeze lifecycle in order:
  setup → status → rotate × 2 → verify states → thaw → check → refreeze → cleanup

All artifacts use the dftest-{run_id} prefix for isolation.
All CLI invocations use --porcelain for machine-readable output.

This is the "golden path" integration test.
"""

import json
import logging

import pytest
from click.testing import CliRunner

from deepfreeze.cli.main import cli

from .helpers.es_verify import (
    assert_ilm_policy_exists,
    assert_repo_exists,
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
    """End-to-end lifecycle with test-prefixed artifacts.

    Tests are named with numeric prefixes to enforce execution order.
    """

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
        logger.info("Setup complete: prefix=%s, provider=%s", test_prefixes.repo_name_prefix, storage_provider)

    def test_02_status(self, runner, test_config_file, test_prefixes):
        """Status should return valid JSON with our repo."""
        result = _invoke(runner, test_config_file, "status")
        data = json.loads(result.output)
        assert "settings" in data
        repos = data.get("repositories", [])
        matching = [r for r in repos if r.get("name", "").startswith(test_prefixes.repo_name_prefix)]
        assert len(matching) >= 1, f"No repos with prefix '{test_prefixes.repo_name_prefix}'"
        logger.info("Status: %d repos", len(repos))

    def test_03_rotate_first(self, runner, test_config_file, es_client, test_prefixes):
        """First rotation creates repo -000002."""
        _invoke(runner, test_config_file, "rotate")
        assert_repo_exists(es_client, f"{test_prefixes.repo_name_prefix}-000002")
        logger.info("First rotate complete")

    def test_04_rotate_second(self, runner, test_config_file, es_client, test_prefixes):
        """Second rotation creates repo -000003."""
        _invoke(runner, test_config_file, "rotate")
        assert_repo_exists(es_client, f"{test_prefixes.repo_name_prefix}-000003")
        logger.info("Second rotate complete")

    def test_05_verify_repo_states(self, es_client, test_prefixes):
        """After rotations, check state distribution."""
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        states = {}
        for r in repos:
            state = r.get("thaw_state", "unknown")
            states[state] = states.get(state, 0) + 1
        logger.info("Repo states: %s", states)
        assert len(repos) >= 3, f"Expected at least 3 repos, got {len(repos)}"
        active = [r for r in repos if r.get("thaw_state") == "active"]
        assert len(active) >= 1, f"No active repos. States: {states}"

    def test_06_thaw_create(self, runner, test_config_file):
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
        logger.info("Thaw created")

    def test_07_thaw_check(self, runner, test_config_file):
        """Check thaw request status."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "thaw", "--check-status", "--porcelain",
        ])
        assert result.exit_code == 0, f"Thaw check failed:\n{result.output}"

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

    def test_11_final_status(self, runner, test_config_file, test_prefixes):
        """Final status should show repos with test prefix."""
        result = _invoke(runner, test_config_file, "status")
        data = json.loads(result.output)
        repos = data.get("repositories", [])
        logger.info("Final: %d repos, %d thaw requests",
                     len(repos), len(data.get("thaw_requests", [])))
