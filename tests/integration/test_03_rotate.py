"""Rotate workflow tests — verify repository creation and archival.

Rotate operates on the settings already stored in the deepfreeze-status
index, not on test prefixes.  Tests verify state changes relative to
the cluster's current state before and after rotation.
"""

import pytest
from click.testing import CliRunner

from deepfreeze.cli.main import cli

from .helpers.es_verify import get_repos_with_prefix

pytestmark = [pytest.mark.integration, pytest.mark.cli]


@pytest.fixture
def runner():
    return CliRunner()


class TestRotateCLI:
    """Rotate command via CliRunner."""

    def test_rotate_dry_run(self, runner, test_config_file, es_client, live_repo_prefix, cluster_initialized):
        """--dry-run should not create a new repository."""
        if not cluster_initialized:
            pytest.skip("Cluster not initialized")

        repos_before = get_repos_with_prefix(es_client, live_repo_prefix)

        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local", "--dry-run",
            "rotate",
        ])
        assert result.exit_code == 0, f"Rotate dry-run failed:\n{result.output}\n{result.exception}"

        repos_after = get_repos_with_prefix(es_client, live_repo_prefix)
        assert len(repos_after) == len(repos_before), "Dry run should not create a repo"

    def test_rotate_creates_new_repo(self, runner, test_config_file, es_client, live_repo_prefix, cluster_initialized):
        """Rotate should create one additional repository."""
        if not cluster_initialized:
            pytest.skip("Cluster not initialized")

        repos_before = get_repos_with_prefix(es_client, live_repo_prefix)
        count_before = len(repos_before)

        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "rotate",
        ])
        assert result.exit_code == 0, f"Rotate failed:\n{result.output}\n{result.exception}"

        repos_after = get_repos_with_prefix(es_client, live_repo_prefix)
        assert len(repos_after) == count_before + 1, (
            f"Expected {count_before + 1} repos after rotate, got {len(repos_after)}. "
            f"Before: {[r['name'] for r in repos_before]}  "
            f"After: {[r['name'] for r in repos_after]}"
        )

    def test_repo_states_after_rotate(self, runner, test_config_file, es_client, live_repo_prefix, cluster_initialized):
        """After rotation, verify repo state distribution."""
        if not cluster_initialized:
            pytest.skip("Cluster not initialized")

        repos = get_repos_with_prefix(es_client, live_repo_prefix)
        states = [(r["name"], r.get("thaw_state", "unknown")) for r in repos]

        # At minimum the newest repo should be active
        active = [r for r in repos if r.get("thaw_state") == "active"]
        assert len(active) >= 1, f"Expected at least one active repo. States: {states}"
