"""Setup workflow tests — verify deepfreeze initialization via CLI.

On an already-initialized cluster, setup will fail with a precondition
error (status index already exists).  The tests adapt: if the cluster
is initialized we verify that existing artifacts are correct; if not,
we run a fresh setup.
"""

import subprocess

import pytest
from click.testing import CliRunner

from deepfreeze.cli.main import cli

from .helpers.es_verify import (
    assert_ilm_policy_exists,
    assert_index_exists,
    assert_repo_exists,
    assert_settings_exist,
)

pytestmark = [pytest.mark.integration, pytest.mark.cli]


@pytest.fixture
def runner():
    return CliRunner()


class TestSetupOnFreshCluster:
    """Setup tests that only run on an uninitialized cluster."""

    def test_setup_dry_run(self, runner, test_config_file, test_prefixes, test_index_template,
                           storage_provider, es_client, cluster_initialized):
        """--dry-run should exit 0 without creating artifacts."""
        if cluster_initialized:
            pytest.skip("Cluster already initialized — setup would fail precondition check")

        result = runner.invoke(cli, [
            "--config", test_config_file,
            "--local", "--dry-run",
            "setup",
            "--repo_name_prefix", test_prefixes.repo_name_prefix,
            "--bucket_name_prefix", test_prefixes.bucket_name_prefix,
            "--ilm_policy_name", test_prefixes.ilm_policy_name,
            "--index_template_name", test_prefixes.index_template_name,
            "--provider", storage_provider,
            "--porcelain",
        ])
        assert result.exit_code == 0, f"Setup dry-run failed:\n{result.output}\n{result.exception}"

    def test_setup_creates_artifacts(self, runner, test_config_file, test_prefixes, test_index_template,
                                     storage_provider, es_client, cluster_initialized):
        """Real setup should create status index, repo, and ILM policy."""
        if cluster_initialized:
            pytest.skip("Cluster already initialized — cannot run fresh setup")

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

        assert_index_exists(es_client, "deepfreeze-status")
        settings = assert_settings_exist(es_client)
        assert settings["repo_name_prefix"] == test_prefixes.repo_name_prefix


class TestSetupOnInitializedCluster:
    """Verify existing setup artifacts on an already-initialized cluster."""

    def test_status_index_exists(self, es_client, cluster_initialized):
        """Status index should exist."""
        if not cluster_initialized:
            pytest.skip("Cluster not initialized — run setup first")
        assert_index_exists(es_client, "deepfreeze-status")

    def test_settings_doc_exists(self, es_client, cluster_initialized):
        """Settings document should be present."""
        if not cluster_initialized:
            pytest.skip("Cluster not initialized")
        settings = assert_settings_exist(es_client)
        assert "repo_name_prefix" in settings
        assert "provider" in settings

    def test_at_least_one_repo_exists(self, es_client, live_settings, cluster_initialized):
        """At least one snapshot repository should exist."""
        if not cluster_initialized or not live_settings:
            pytest.skip("Cluster not initialized")
        prefix = live_settings["repo_name_prefix"]
        repos = es_client.snapshot.get_repository(name=f"{prefix}*")
        assert len(repos) > 0, f"No repos found with prefix '{prefix}'"


class TestSetupSubprocess:
    """Setup via subprocess — validates the installed entry point."""

    def test_setup_help(self):
        """deepfreeze setup --help exits 0."""
        result = subprocess.run(
            ["deepfreeze", "setup", "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "Set up a cluster" in result.stdout or "setup" in result.stdout.lower()
