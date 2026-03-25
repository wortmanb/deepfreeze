"""Integration test fixtures.

Session-scoped fixtures that provide:
- Real ES client from config
- Unique test-run prefix for artifact isolation
- Temporary config file with test prefixes
- Server process management
- Automatic cleanup of test artifacts
"""

import logging
import os
import signal
import socket
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from deepfreeze_core.esclient import create_es_client

from deepfreeze_core.constants import STATUS_INDEX

from .helpers.diagnostics import write_failure_diagnostics
from .helpers.waiter import wait_for_server_ready

logger = logging.getLogger("deepfreeze.tests")


# ---------------------------------------------------------------------------
# Dataclass for test-run prefixes
# ---------------------------------------------------------------------------

@dataclass
class TestPrefixes:
    """All artifact names used by a single test run."""
    run_id: str
    repo_name_prefix: str
    bucket_name_prefix: str
    ilm_policy_name: str
    index_template_name: str


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_run_id():
    """Unique 6-char hex prefix for this test run."""
    return uuid.uuid4().hex[:6]


@pytest.fixture(scope="session")
def integration_config():
    """Load ES config from env var or default location.

    Priority:
    1. DEEPFREEZE_TEST_CONFIG env var → path to YAML file
    2. ~/.deepfreeze/config.yml
    """
    config_path = os.environ.get("DEEPFREEZE_TEST_CONFIG")
    if not config_path:
        default = Path.home() / ".deepfreeze" / "config.yml"
        if default.is_file():
            config_path = str(default)

    if not config_path or not Path(config_path).is_file():
        pytest.skip("No ES config available (set DEEPFREEZE_TEST_CONFIG or create ~/.deepfreeze/config.yml)")

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    if "elasticsearch" not in config:
        pytest.skip("Config file missing 'elasticsearch' section")

    return config


@pytest.fixture(scope="session")
def es_client(integration_config):
    """Real Elasticsearch client, validated on creation."""
    from deepfreeze.config import get_elasticsearch_config

    es_config = get_elasticsearch_config(integration_config)
    client = create_es_client(**es_config)

    # Validate connectivity
    health = client.cluster.health(timeout="10s")
    assert health["status"] in ("green", "yellow"), (
        f"Cluster health is '{health['status']}' — expected green or yellow"
    )
    logger.info("Connected to ES cluster: %s (status: %s)", health.get("cluster_name"), health["status"])

    yield client
    client.close()


@pytest.fixture(scope="session")
def storage_provider(integration_config):
    """The cloud storage provider from config (aws/azure/gcp)."""
    # Check if there's a storage section to infer provider,
    # otherwise default to aws
    storage = integration_config.get("storage", {})
    for provider in ("gcp", "azure", "aws"):
        if provider in storage:
            return provider
    return "aws"


@pytest.fixture(scope="session")
def test_prefixes(test_run_id):
    """Artifact names keyed by this test run's unique prefix."""
    prefix = f"dftest-{test_run_id}"
    return TestPrefixes(
        run_id=test_run_id,
        repo_name_prefix=prefix,
        bucket_name_prefix=prefix,
        ilm_policy_name=f"{prefix}-ilm",
        index_template_name=f"{prefix}-tmpl",
    )


@pytest.fixture(scope="session")
def test_config_file(integration_config, test_prefixes):
    """Temporary config YAML that merges real ES creds with test prefixes.

    This is the file passed to ``--config`` for all CLI invocations.
    """
    config = dict(integration_config)
    # Ensure logging is set
    config.setdefault("logging", {})["loglevel"] = "DEBUG"

    fd, path = tempfile.mkstemp(suffix=".yml", prefix="dftest-config-")
    with os.fdopen(fd, "w") as f:
        yaml.safe_dump(config, f)

    logger.info("Test config written to %s (run_id=%s)", path, test_prefixes.run_id)
    yield path

    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Index template fixture — creates a minimal template for setup to reference
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def cluster_initialized(es_client):
    """Whether deepfreeze is already initialized on this cluster."""
    return es_client.indices.exists(index=STATUS_INDEX)


@pytest.fixture(scope="session")
def live_settings(es_client, cluster_initialized):
    """The actual deepfreeze settings from the cluster, or None."""
    if not cluster_initialized:
        return None
    try:
        from deepfreeze_core.constants import SETTINGS_ID
        doc = es_client.get(index=STATUS_INDEX, id=SETTINGS_ID)
        return doc["_source"]
    except Exception:
        return None


@pytest.fixture(scope="session")
def live_repo_prefix(live_settings):
    """The repo_name_prefix from the live cluster settings."""
    if live_settings:
        return live_settings.get("repo_name_prefix", "deepfreeze")
    return None


@pytest.fixture(scope="session")
def test_index_template(es_client, test_prefixes):
    """Create a minimal index template for the test run.

    Setup requires an existing index template to attach the ILM policy to.
    This creates one with a pattern that won't match real data.
    """
    template_name = test_prefixes.index_template_name
    pattern = f"{test_prefixes.repo_name_prefix}-data-*"

    es_client.indices.put_index_template(
        name=template_name,
        body={
            "index_patterns": [pattern],
            "template": {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            },
        },
    )
    logger.info("Created test index template '%s' (pattern: %s)", template_name, pattern)
    yield template_name

    # Cleanup handled by auto_cleanup
    pass


# ---------------------------------------------------------------------------
# Server process fixture (for API and WebUI tests)
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_url(test_config_file):
    """Start deepfreeze-server on an ephemeral port. Yields the base URL."""
    port = _find_free_port()
    proc = subprocess.Popen(
        [
            "deepfreeze-server",
            "--config", test_config_file,
            "--port", str(port),
            "--no-tls",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base_url = f"http://localhost:{port}"
    try:
        wait_for_server_ready(base_url, timeout=30)
        logger.info("Test server running at %s (pid=%d)", base_url, proc.pid)
        yield base_url
    except TimeoutError:
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        proc.kill()
        pytest.fail(f"Server failed to start within 30s. stderr:\n{stderr}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@pytest.fixture(scope="session")
def http_client(server_url):
    """httpx client pointed at the test server."""
    import httpx

    with httpx.Client(base_url=f"{server_url}/api", timeout=30) as client:
        yield client


# ---------------------------------------------------------------------------
# Automatic cleanup
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def auto_cleanup(es_client, test_prefixes, storage_provider):
    """Yield, then clean up all test artifacts on session teardown."""
    yield

    prefix = test_prefixes.repo_name_prefix
    logger.info("Cleaning up test artifacts with prefix '%s'", prefix)

    # 1. Snapshot repositories
    try:
        repos = es_client.snapshot.get_repository(name=f"{prefix}*")
        for repo_name in repos:
            try:
                es_client.snapshot.delete_repository(name=repo_name)
                logger.info("Deleted repo: %s", repo_name)
            except Exception as exc:
                logger.warning("Failed to delete repo '%s': %s", repo_name, exc)
    except Exception:
        pass

    # 2. ILM policies
    try:
        all_policies = es_client.ilm.get_lifecycle()
        for name in all_policies:
            if name.startswith(prefix):
                try:
                    es_client.ilm.delete_lifecycle(name=name)
                    logger.info("Deleted ILM policy: %s", name)
                except Exception as exc:
                    logger.warning("Failed to delete ILM policy '%s': %s", name, exc)
    except Exception:
        pass

    # 3. Index templates
    try:
        es_client.indices.delete_index_template(name=test_prefixes.index_template_name)
        logger.info("Deleted index template: %s", test_prefixes.index_template_name)
    except Exception:
        pass

    # 4. Indices matching prefix
    try:
        es_client.indices.delete(index=f"{prefix}*", ignore_unavailable=True)
        logger.info("Deleted indices matching '%s*'", prefix)
    except Exception:
        pass

    # 5. Status index docs matching prefix
    from deepfreeze_core.constants import STATUS_INDEX
    try:
        if es_client.indices.exists(index=STATUS_INDEX):
            es_client.delete_by_query(
                index=STATUS_INDEX,
                body={"query": {"prefix": {"name": prefix}}},
                conflicts="proceed",
            )
            logger.info("Cleaned status docs with prefix '%s'", prefix)
    except Exception as exc:
        logger.warning("Failed to clean status docs: %s", exc)

    # 6. S3 buckets (best-effort)
    try:
        from deepfreeze_core.s3client import s3_client_factory

        s3 = s3_client_factory(storage_provider)
        buckets = s3.list_buckets(prefix=prefix)
        for bucket_name in buckets:
            try:
                s3.delete_bucket(bucket_name)
                logger.info("Deleted bucket: %s", bucket_name)
            except Exception as exc:
                logger.warning("Failed to delete bucket '%s': %s", bucket_name, exc)
    except Exception as exc:
        logger.warning("Failed to clean S3 buckets: %s", exc)


# ---------------------------------------------------------------------------
# Failure diagnostics hook
# ---------------------------------------------------------------------------

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        es = item.funcargs.get("es_client")
        prefixes = item.funcargs.get("test_prefixes")
        if es and prefixes:
            write_failure_diagnostics(
                test_name=item.nodeid,
                es_client=es,
                prefix=prefixes.repo_name_prefix,
            )
