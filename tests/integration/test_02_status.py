"""Status verification tests — confirm status output after setup."""

import json

import pytest
from click.testing import CliRunner

from deepfreeze.cli.main import cli

pytestmark = [pytest.mark.integration, pytest.mark.cli]


@pytest.fixture
def runner():
    return CliRunner()


class TestStatusCLI:
    """Status command via CliRunner."""

    def test_status_exits_zero(self, runner, test_config_file):
        """Status command should succeed after setup."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "status",
        ])
        assert result.exit_code == 0, f"Status failed:\n{result.output}"

    def test_status_porcelain(self, runner, test_config_file, test_prefixes):
        """Porcelain output should be parseable JSON."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "status", "--porcelain",
        ])
        assert result.exit_code == 0, f"Status --porcelain failed:\n{result.output}"
        # Porcelain status outputs JSON to stdout
        output = result.output.strip()
        if output:
            data = json.loads(output)
            assert "settings" in data or "repositories" in data

    def test_status_shows_repos(self, runner, test_config_file, test_prefixes):
        """Status should show the repository created by setup."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "status", "--repos",
        ])
        assert result.exit_code == 0
        assert test_prefixes.repo_name_prefix in result.output, (
            f"Expected repo prefix '{test_prefixes.repo_name_prefix}' in status output"
        )
