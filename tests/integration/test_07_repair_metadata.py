"""Repair metadata tests."""

import pytest
from click.testing import CliRunner

from deepfreeze.cli.main import cli

pytestmark = [pytest.mark.integration, pytest.mark.cli]


@pytest.fixture
def runner():
    return CliRunner()


class TestRepairMetadataCLI:
    """repair-metadata command via CliRunner."""

    def test_repair_dry_run(self, runner, test_config_file):
        """Repair --dry-run should scan and report without changes."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local", "--dry-run",
            "repair-metadata",
        ])
        assert result.exit_code == 0, f"Repair dry-run failed:\n{result.output}\n{result.exception}"

    def test_repair_runs(self, runner, test_config_file):
        """Repair should complete without error."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "repair-metadata",
        ])
        assert result.exit_code == 0, f"Repair failed:\n{result.output}\n{result.exception}"
