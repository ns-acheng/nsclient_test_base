"""
Shared fixtures for unit tests (test/ directory).

All I/O is mocked — tests run without admin, services, or NSClient installed.
subprocess, winreg, ctypes, and filesystem operations are blocked by default
via the autouse guardrail.  Individual tests opt-in to specific mocks.
"""

import json
import sys
import threading
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ── Autouse guardrail ────────────────────────────────────────────────────────
# Blocks real subprocess/winreg/ctypes calls so a broken test can never
# touch the live system.  Individual fixtures (mock_subprocess, etc.) replace
# these blocks with controlled stubs.

@pytest.fixture(autouse=True)
def _block_real_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent accidental real subprocess, winreg, and ctypes calls."""
    def _blocked_subprocess(*args: Any, **kwargs: Any) -> None:
        raise AssertionError(
            "Real subprocess.run() called in a unit test — "
            "use the mock_subprocess fixture instead"
        )

    monkeypatch.setattr("subprocess.run", _blocked_subprocess)

    # Block winreg on Windows — stub a fake module on other platforms
    if sys.platform.startswith("win"):
        try:
            import winreg
            monkeypatch.setattr(winreg, "OpenKey", lambda *a, **kw: (_ for _ in ()).throw(
                AssertionError("Real winreg.OpenKey() called — use mock_winreg fixture")))
            monkeypatch.setattr(winreg, "CreateKeyEx", lambda *a, **kw: (_ for _ in ()).throw(
                AssertionError("Real winreg.CreateKeyEx() called — use mock_winreg fixture")))
        except ImportError:
            pass

    # Block ctypes.windll on Windows
    if sys.platform.startswith("win"):
        try:
            import ctypes
            if hasattr(ctypes, "windll"):
                monkeypatch.setattr(
                    ctypes.windll.shell32, "IsUserAnAdmin",
                    lambda: (_ for _ in ()).throw(
                        AssertionError("Real IsUserAnAdmin() called — mock it explicitly")),
                )
        except Exception:
            pass


# ── subprocess mock ──────────────────────────────────────────────────────────

@pytest.fixture()
def mock_subprocess(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """
    Replace subprocess.run with a MagicMock.

    The mock returns CompletedProcess(returncode=0, stdout="", stderr="") by
    default.  Override per-test:

        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="error output", stderr=""
        )
    """
    import subprocess as sp

    default_result = sp.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    mock = MagicMock(return_value=default_result)
    monkeypatch.setattr("subprocess.run", mock)
    return mock


# ── winreg mock (Windows-only in production, mockable everywhere) ────────────

@pytest.fixture()
def mock_winreg(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """
    Provide a mock winreg module.

    On Windows, patches the real winreg.  On other platforms, injects a fake
    winreg into sys.modules so ``import winreg`` works in the code under test.
    """
    mock = MagicMock()
    mock.HKEY_LOCAL_MACHINE = 0x80000002
    mock.REG_DWORD = 4
    mock.REG_SZ = 1

    if sys.platform.startswith("win"):
        import winreg
        monkeypatch.setattr(winreg, "OpenKey", mock.OpenKey)
        monkeypatch.setattr(winreg, "CreateKeyEx", mock.CreateKeyEx)
        monkeypatch.setattr(winreg, "QueryValueEx", mock.QueryValueEx)
        monkeypatch.setattr(winreg, "SetValueEx", mock.SetValueEx)
        monkeypatch.setattr(winreg, "EnumKey", mock.EnumKey)
    else:
        monkeypatch.setitem(sys.modules, "winreg", mock)

    return mock


# ── ctypes / admin mock ─────────────────────────────────────────────────────

@pytest.fixture()
def mock_admin(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """
    Mock is_admin() to return True.  Works on all platforms.

    To test the non-admin path, set: ``mock_admin.return_value = False``
    """
    mock = MagicMock(return_value=True)
    monkeypatch.setattr("util_install.is_admin", mock)
    return mock


# ── nsconfig.json fixtures ───────────────────────────────────────────────────

@pytest.fixture()
def sample_nsconfig() -> dict:
    """Minimal nsconfig.json payload with known test values."""
    return {
        "nsgw": {"host": "gateway-test-tenant.goskope.com"},
        "clientConfig": {
            "configurationName": "TestConfig",
            "clientUpdate": {"allowAutoUpdate": True},
            "nsclient_watchdog_monitor": "false",
        },
    }


@pytest.fixture()
def nsconfig_file(tmp_path: Path, sample_nsconfig: dict) -> Path:
    """Write sample_nsconfig to a temp file and return its path."""
    config_path = tmp_path / "nsconfig.json"
    config_path.write_text(json.dumps(sample_nsconfig), encoding="utf-8")
    return config_path


# ── ProjectConfig fixtures ───────────────────────────────────────────────────

@pytest.fixture()
def sample_project_config() -> dict:
    """Raw dict matching data/config.json schema."""
    return {
        "tenant_hostname": "test-tenant.goskope.com",
        "is_64bit": True,
        "log_dir": "log",
        "confluence": {
            "base_url": "https://netskope.atlassian.net/wiki",
            "username": "tester@netskope.com",
            "api_token": "",
        },
    }


@pytest.fixture()
def config_file(tmp_path: Path, sample_project_config: dict) -> Path:
    """Write sample_project_config to a temp file and return its path."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(sample_project_config), encoding="utf-8")
    return config_path


# ── Temp directories ─────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_log_dir(tmp_path: Path) -> Path:
    """Provide a temporary log directory."""
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    return log_dir


@pytest.fixture()
def tmp_install_dir(tmp_path: Path) -> Path:
    """Provide a temporary install directory with a fake stAgentSvc."""
    install_dir = tmp_path / "STAgent"
    install_dir.mkdir()
    (install_dir / "stAgentSvc.exe").write_bytes(b"fake")
    return install_dir


# ── Platform helpers ─────────────────────────────────────────────────────────

@pytest.fixture()
def current_platform() -> str:
    """Return normalised platform name: 'windows', 'macos', 'linux'."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("darwin"):
        return "macos"
    return "linux"


@pytest.fixture()
def force_platform(monkeypatch: pytest.MonkeyPatch):
    """
    Factory fixture to fake sys.platform for cross-platform unit tests.

    Usage:
        def test_mac_service(force_platform):
            force_platform("darwin")
            # code under test now sees sys.platform == "darwin"
    """
    def _force(platform_str: str) -> None:
        monkeypatch.setattr(sys, "platform", platform_str)
    return _force


# ── Service / process mock data ──────────────────────────────────────────────

@pytest.fixture()
def mock_service_info():
    """Factory for util_service.ServiceInfo objects."""
    from util_service import ServiceInfo

    def _make(name: str = "stAgentSvc", exists: bool = True, state: str = "RUNNING"):
        return ServiceInfo(name=name, exists=exists, state=state)
    return _make


@pytest.fixture()
def stop_event() -> threading.Event:
    """Threading event — useful for timeout/polling tests."""
    return threading.Event()
