"""Cleanup workflow tests."""

import pytest
from click.testing import CliRunner

from deepfreeze.cli.main import cli

pytestmark = [pytest.mark.integration, pytest.mark.cli]


@pytest.fixture
def runner():
    return CliRunner()


class TestCleanupCLI:
    """Cleanup command via CliRunner — uses --porcelain for output."""

    def test_cleanup_dry_run(self, runner, test_config_file, cluster_initialized):
        """Cleanup --dry-run should exit 0."""
        if not cluster_initialized:
            pytest.skip("Cluster not initialized — cleanup requires setup")

        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local", "--dry-run",
            "cleanup", "--porcelain",
        ])
        assert result.exit_code == 0, f"Cleanup dry-run failed:\n{result.output}\n{result.exception}"

    def test_cleanup_runs(self, runner, test_config_file, cluster_initialized):
        """Cleanup should complete without error."""
        if not cluster_initialized:
            pytest.skip("Cluster not initialized — cleanup requires setup")

        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "cleanup", "--porcelain",
        ])
        assert result.exit_code == 0, f"Cleanup failed:\n{result.output}\n{result.exception}"
