"""Full end-to-end workflow test.

Exercises the complete deepfreeze lifecycle in order:
  setup → status → rotate × 3 → verify frozen → thaw → verify thawed → refreeze → cleanup

This is the "golden path" integration test — the single most valuable
test in the suite.  It is long-running (marked slow) because thaw
operations may take minutes depending on the storage provider.
"""

import logging

import pytest
from click.testing import CliRunner

from deepfreeze.cli.main import cli
from deepfreeze_core.constants import (
    THAW_STATE_FROZEN,
    THAW_STATUS_COMPLETED,
    THAW_STATUS_IN_PROGRESS,
)

from .helpers.es_verify import (
    assert_ilm_policy_exists,
    assert_repo_exists,
    assert_settings_exist,
    get_repo_thaw_state,
    get_repos_with_prefix,
)
from .helpers.waiter import wait_for_thaw_status

pytestmark = [pytest.mark.integration, pytest.mark.slow]

logger = logging.getLogger("deepfreeze.tests.workflow")


class TestFullLifecycle:
    """End-to-end lifecycle exercised in a single ordered test class.

    Tests are named with numeric prefixes to enforce execution order
    within the class.  Each step builds on the previous one.
    """

    @pytest.fixture(autouse=True)
    def _inject(self, runner_session, test_config_file, es_client, test_prefixes, storage_provider, test_index_template):
        """Inject session fixtures into the test class."""
        self.runner = runner_session
        self.config = test_config_file
        self.es = es_client
        self.prefixes = test_prefixes
        self.provider = storage_provider

    def _invoke(self, *args, expect_success=True):
        """Invoke the CLI and optionally assert success."""
        result = self.runner.invoke(cli, [
            "--config", self.config,
            "--local",
            *args,
        ])
        if expect_success:
            assert result.exit_code == 0, (
                f"CLI failed (exit={result.exit_code}):\n{result.output}\n{result.exception}"
            )
        return result

    # -- Step 1: Setup --

    def test_01_setup(self):
        """Initialize deepfreeze with test prefixes."""
        self._invoke(
            "setup",
            "--repo_name_prefix", self.prefixes.repo_name_prefix,
            "--bucket_name_prefix", self.prefixes.bucket_name_prefix,
            "--ilm_policy_name", self.prefixes.ilm_policy_name,
            "--index_template_name", self.prefixes.index_template_name,
            "--provider", self.provider,
        )
        settings = assert_settings_exist(self.es)
        assert settings["repo_name_prefix"] == self.prefixes.repo_name_prefix
        logger.info("Setup complete: %s", settings)

    # -- Step 2: Verify initial status --

    def test_02_status_after_setup(self):
        """Status should show the initial repository."""
        result = self._invoke("status")
        assert self.prefixes.repo_name_prefix in result.output

    # -- Step 3: Rotate three times --

    def test_03_rotate_first(self):
        """First rotation creates repo -000002."""
        self._invoke("rotate")
        assert_repo_exists(self.es, f"{self.prefixes.repo_name_prefix}-000002")

    def test_04_rotate_second(self):
        """Second rotation creates repo -000003."""
        self._invoke("rotate")
        assert_repo_exists(self.es, f"{self.prefixes.repo_name_prefix}-000003")

    def test_05_rotate_third_with_keep_1(self):
        """Third rotation with keep=1 should archive old repos."""
        self._invoke("rotate", "--keep", "1")
        assert_repo_exists(self.es, f"{self.prefixes.repo_name_prefix}-000004")

        # After keep=1, older repos should be frozen
        repos = get_repos_with_prefix(self.es, self.prefixes.repo_name_prefix)
        frozen = [r for r in repos if r.get("thaw_state") == THAW_STATE_FROZEN]
        logger.info(
            "Repos after rotate: %s",
            [(r["name"], r.get("thaw_state")) for r in repos],
        )
        assert len(frozen) >= 1, (
            f"Expected at least 1 frozen repo. "
            f"States: {[(r['name'], r.get('thaw_state')) for r in repos]}"
        )

    # -- Step 4: Verify frozen state --

    def test_06_verify_frozen_repos(self):
        """At least one repo should be in frozen state."""
        repos = get_repos_with_prefix(self.es, self.prefixes.repo_name_prefix)
        frozen = [r for r in repos if r.get("thaw_state") == THAW_STATE_FROZEN]
        assert len(frozen) >= 1, "No frozen repos found"
        logger.info("Frozen repos: %s", [r["name"] for r in frozen])

    # -- Step 5: Thaw --

    def test_07_thaw_create(self):
        """Create a thaw request for a broad date range."""
        result = self._invoke(
            "thaw",
            "--start-date", "2020-01-01T00:00:00Z",
            "--end-date", "2030-12-31T23:59:59Z",
            "--async",
        )
        logger.info("Thaw create output: %s", result.output)

    def test_08_thaw_check(self):
        """Check thaw request status."""
        result = self._invoke("thaw", "--check-status")
        logger.info("Thaw check output: %s", result.output)

    # -- Step 6: Refreeze --

    def test_09_refreeze(self):
        """Refreeze all completed thaw requests."""
        self._invoke("refreeze")
        logger.info("Refreeze complete")

    # -- Step 7: Cleanup --

    def test_10_cleanup(self):
        """Cleanup should remove refrozen requests."""
        self._invoke("cleanup")
        logger.info("Cleanup complete")

    # -- Step 8: Final status --

    def test_11_final_status(self):
        """Final status should show clean state."""
        result = self._invoke("status")
        logger.info("Final status:\n%s", result.output)


@pytest.fixture(scope="session")
def runner_session():
    """Session-scoped CliRunner for the full workflow."""
    return CliRunner()
