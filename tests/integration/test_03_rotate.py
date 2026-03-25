"""Rotate workflow tests — verify repository creation and archival."""

import pytest
from click.testing import CliRunner

from deepfreeze.cli.main import cli

from .helpers.es_verify import assert_repo_exists, get_repos_with_prefix

pytestmark = [pytest.mark.integration, pytest.mark.cli]


@pytest.fixture
def runner():
    return CliRunner()


class TestRotateCLI:
    """Rotate command via CliRunner."""

    def test_rotate_dry_run(self, runner, test_config_file, es_client, test_prefixes):
        """--dry-run should not create a new repository."""
        repos_before = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)

        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local", "--dry-run",
            "rotate",
        ])
        assert result.exit_code == 0, f"Rotate dry-run failed:\n{result.output}\n{result.exception}"

        repos_after = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        assert len(repos_after) == len(repos_before), "Dry run created a repo"

    def test_rotate_creates_new_repo(self, runner, test_config_file, es_client, test_prefixes):
        """Rotate should create a second repository with incremented suffix."""
        repos_before = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)

        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "rotate",
        ])
        assert result.exit_code == 0, f"Rotate failed:\n{result.output}\n{result.exception}"

        repos_after = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        assert len(repos_after) == len(repos_before) + 1, (
            f"Expected {len(repos_before) + 1} repos, got {len(repos_after)}"
        )

        # The new repo should exist in ES as a snapshot repository
        expected = f"{test_prefixes.repo_name_prefix}-000002"
        assert_repo_exists(es_client, expected)

    def test_rotate_second_time(self, runner, test_config_file, es_client, test_prefixes):
        """A second rotation should create a third repository."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "rotate",
        ])
        assert result.exit_code == 0, f"Second rotate failed:\n{result.output}\n{result.exception}"

        expected = f"{test_prefixes.repo_name_prefix}-000003"
        assert_repo_exists(es_client, expected)

    def test_rotate_archives_old_repos(self, runner, test_config_file, es_client, test_prefixes):
        """With keep=1, old repos should be archived (frozen state)."""
        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local",
            "rotate", "--keep", "1",
        ])
        assert result.exit_code == 0, f"Rotate with keep=1 failed:\n{result.output}\n{result.exception}"

        # Check that some repos are in frozen state
        repos = get_repos_with_prefix(es_client, test_prefixes.repo_name_prefix)
        frozen = [r for r in repos if r.get("thaw_state") == "frozen"]
        assert len(frozen) > 0, (
            f"Expected at least one frozen repo. States: {[(r['name'], r.get('thaw_state')) for r in repos]}"
        )
