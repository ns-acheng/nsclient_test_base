"""
Shared fixtures for feature / integration tests (features/ directory).

Unlike test/conftest.py, these fixtures do NOT block real subprocess calls.
Feature tests may run against a live NSClient installation.

Guardrails here are safety checks (e.g. confirm admin, confirm service exists)
rather than mocks.
"""

import logging
import sys
from pathlib import Path

import pytest

from util_config import ProjectConfig, load_config
from util_nsclient import get_nsconfig_info, NsConfigInfo, detect_install_dir
from util_service import query_service, SVC_CLIENT
from util_webui import WebUIClient

log = logging.getLogger(__name__)


# ── Auto-skip by platform ────────────────────────────────────────────────────

def pytest_collection_modifyitems(config, items):
    """Auto-skip tests marked for a different platform."""
    platform_map = {
        "windows": sys.platform.startswith("win"),
        "macos": sys.platform.startswith("darwin"),
        "linux": not sys.platform.startswith("win") and not sys.platform.startswith("darwin"),
    }

    for item in items:
        for marker_name, is_current in platform_map.items():
            if marker_name in item.keywords and not is_current:
                item.add_marker(pytest.mark.skip(
                    reason=f"Test requires {marker_name}, running on {sys.platform}"
                ))


# ── Project config ───────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def project_config() -> ProjectConfig:
    """Load data/config.json once per session."""
    return load_config()


@pytest.fixture(scope="session")
def tenant_hostname(project_config: ProjectConfig) -> str:
    """Tenant hostname from project config."""
    return project_config.tenant_hostname


@pytest.fixture(scope="session")
def is_64bit(project_config: ProjectConfig) -> bool:
    """64-bit flag from project config."""
    return project_config.is_64bit


@pytest.fixture(scope="session")
def log_dir(project_config: ProjectConfig) -> Path:
    """Ensure log directory exists and return its path."""
    d = Path(project_config.log_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── NSClient state fixtures ──────────────────────────────────────────────────

@pytest.fixture(scope="session")
def nsclient_installed() -> bool:
    """Return True if NSClient is installed on this machine."""
    return detect_install_dir() is not None


@pytest.fixture(scope="session")
def install_dir() -> Path:
    """Return the detected install directory; skip session if not installed."""
    d = detect_install_dir()
    if d is None:
        pytest.skip("NSClient is not installed on this machine")
    return d


@pytest.fixture(scope="session")
def nsconfig(install_dir: Path) -> NsConfigInfo:
    """Read and parse nsconfig.json; skip if unreadable."""
    info = get_nsconfig_info()
    if info is None:
        pytest.skip("nsconfig.json not found or unparseable")
    return info


@pytest.fixture()
def client_service_running() -> bool:
    """Check if the primary client service is currently running."""
    info = query_service(SVC_CLIENT)
    return info.state == "RUNNING"


@pytest.fixture()
def require_client_running():
    """Skip the test if the client service is not running."""
    info = query_service(SVC_CLIENT)
    if info.state != "RUNNING":
        pytest.skip(f"Client service {SVC_CLIENT!r} is not running (state={info.state})")


@pytest.fixture(scope="session")
def webui_client(project_config: ProjectConfig) -> WebUIClient:
    """
    Authenticated WebUIClient for the tenant.

    Skips the session if tenant_hostname or tenant_username is not configured,
    or if tenant_password is not stored in the secrets store.
    Login is attempted once; subsequent calls reuse the session.
    """
    hostname = project_config.tenant_hostname
    username = project_config.tenant_username
    password = project_config.tenant_password

    if not hostname:
        pytest.skip("tenant_hostname not set in data/config.json")
    if not username:
        pytest.skip("tenant_username not set in data/config.json")
    if not password:
        pytest.skip(
            "tenant_password not in secrets store — run: "
            "python tool/manage_secrets.py set tenant_password"
        )

    client = WebUIClient(hostname, username, password)
    if not client.login():
        pytest.skip(f"WebUI login failed for {username}@{hostname}")
    return client


@pytest.fixture()
def require_admin():
    """Skip the test if not running with admin/root privileges."""
    from util_install import is_admin
    if not is_admin():
        pytest.skip("Test requires administrator / root privileges")
