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
        """Status command should succeed."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "status",
        ])
        assert result.exit_code == 0, f"Status failed:\n{result.output}"

    def test_status_porcelain(self, runner, test_config_file):
        """Porcelain output should be parseable JSON."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "status", "--porcelain",
        ])
        assert result.exit_code == 0, f"Status --porcelain failed:\n{result.output}"
        output = result.output.strip()
        if output:
            data = json.loads(output)
            assert "settings" in data or "repositories" in data

    def test_status_shows_repos(self, runner, test_config_file, live_repo_prefix, cluster_initialized):
        """Status should show repositories matching the configured prefix."""
        if not cluster_initialized:
            pytest.skip("Cluster not initialized")

        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "status", "--porcelain",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        repos = data.get("repositories", [])
        matching = [r for r in repos if r.get("name", "").startswith(live_repo_prefix)]
        assert len(matching) > 0, (
            f"Expected at least one repo with prefix '{live_repo_prefix}' in porcelain output. "
            f"Got {len(repos)} repos: {[r.get('name') for r in repos[:5]]}"
        )
