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
    """Status command via CliRunner — all assertions use --porcelain."""

    def test_status_exits_zero(self, runner, test_config_file, cluster_initialized):
        """Status command should succeed on an initialized cluster."""
        if not cluster_initialized:
            pytest.skip("Cluster not initialized — status requires setup")

        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "status", "--porcelain",
        ])
        assert result.exit_code == 0, f"Status failed:\n{result.output}"

    def test_status_porcelain_parseable(self, runner, test_config_file, cluster_initialized):
        """Porcelain output should be valid JSON with expected keys."""
        if not cluster_initialized:
            pytest.skip("Cluster not initialized — status requires setup")

        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "status", "--porcelain",
        ])
        assert result.exit_code == 0, f"Status --porcelain failed:\n{result.output}"
        data = json.loads(result.output.strip())
        assert "settings" in data
        assert "repositories" in data
        assert "thaw_requests" in data

    def test_status_on_fresh_cluster(self, runner, test_config_file, cluster_initialized):
        """On a fresh cluster, status should return a clear error in JSON."""
        if cluster_initialized:
            pytest.skip("Cluster already initialized")

        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "status", "--porcelain",
        ])
        # Status should exit non-zero with a helpful error
        assert result.exit_code != 0
        data = json.loads(result.output.strip())
        assert "error" in data
        assert "status_index_missing" in data["error"]

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
