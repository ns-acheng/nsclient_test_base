"""
Netskope tenant Web API client for nsclient_test_base.

Wraps pylark-webapi-lib (sibling repo at ../pylark-webapi-lib) to configure
tenant settings programmatically during test setup and teardown.

Usage:
    from util_webui import WebUIClient

    client = WebUIClient("mytenant.goskope.com", "user@netskope.com", password)
    client.login()
    client.set_auto_reenable_duration(minutes=3)
    client.clear_auto_reenable()

The pylark-webapi-lib path is resolved at import time; an ImportError is raised
at construction if the library is not found.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Locate pylark-webapi-lib ──────────────────────────────────────────────────

_current_dir = Path(__file__).resolve().parent
_sibling_path = (_current_dir.parent / "pylark-webapi-lib" / "src").resolve()
_local_path   = (_current_dir / "lib" / "pylark-webapi-lib" / "src").resolve()

for _candidate in (_sibling_path, _local_path):
    if _candidate.exists() and str(_candidate) not in sys.path:
        sys.path.append(str(_candidate))
        break

try:
    from webapi import WebAPI
    from webapi.auth import Authentication
    from webapi.settings.security_cloud_platform.netskope_client.client_configuration import (
        ClientConfiguration,
    )
    _WEBAPI_AVAILABLE = True
except ImportError:
    log.warning("pylark-webapi-lib not found — WebUIClient will raise on construction")
    WebAPI = None  # type: ignore[assignment]
    _WEBAPI_AVAILABLE = False


# ── WebUIClient ───────────────────────────────────────────────────────────────

class WebUIClient:
    """
    Thin wrapper around pylark-webapi-lib for test-setup operations.

    Mirrors the WebUIClient in stress_test/util_webui.py but is scoped to the
    operations needed by nsclient_test_base feature tests.
    """

    DEFAULT_CONFIG = "Default tenant config"

    def __init__(self, hostname: str, username: str, password: str) -> None:
        if not _WEBAPI_AVAILABLE:
            raise ImportError(
                "pylark-webapi-lib not found. "
                "Clone it next to this repo: git clone <url> ../pylark-webapi-lib"
            )
        self.hostname = hostname
        self.username = username
        self.password = password
        self.webapi: Optional[WebAPI] = None
        self.is_logged_in: bool = False
        self.client_config_name: str = self._detect_config_name()

    def _detect_config_name(self) -> str:
        """Read configurationName from local nsconfig.json, fall back to default."""
        try:
            import json
            if sys.platform.startswith("win"):
                path = Path(r"C:\ProgramData\netskope\stagent\nsconfig.json")
            elif sys.platform.startswith("darwin"):
                path = Path("/Library/Application Support/Netskope/STAgent/nsconfig.json")
            else:
                path = Path("/opt/netskope/stagent/nsconfig.json")
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                name = data.get("clientConfig", {}).get("configurationName", "")
                if name:
                    log.debug("Using client config name from nsconfig.json: %r", name)
                    return name
        except Exception:
            log.debug("Could not read config name from nsconfig.json", exc_info=True)
        return self.DEFAULT_CONFIG

    def login(self) -> bool:
        """Authenticate to the tenant. Returns True on success."""
        try:
            log.info("WebUI login: %s as %s", self.hostname, self.username)
            self.webapi = WebAPI(
                hostname=self.hostname,
                username=self.username,
                password=self.password,
            )
            Authentication(self.webapi).login()
            self.is_logged_in = True
            log.info("WebUI login successful")
            return True
        except Exception:
            log.exception("WebUI login failed")
            self.is_logged_in = False
            return False

    def _ensure_logged_in(self) -> bool:
        if not self.is_logged_in:
            return self.login()
        return True

    def _update(self, **kwargs) -> bool:
        """Call update_client_config with the detected config name."""
        if not self._ensure_logged_in():
            return False
        try:
            cc = ClientConfiguration(self.webapi)
            log.info("Updating client config %r: %s", self.client_config_name, kwargs)
            response = cc.update_client_config(search_config=self.client_config_name, **kwargs)
            if response.get("status") == "success":
                log.info("Client config updated successfully")
                return True
            log.error("Client config update failed: %s", response)
            return False
        except Exception:
            log.exception("Client config update error")
            return False

    # ── NPLAN-6711 specific ───────────────────────────────────────────────────

    def set_auto_reenable_duration(self, minutes: int) -> bool:
        """
        Set clientAllDisable.autoReenableDuration on the tenant.

        Also sets allowClientDisabling=1 in the same call — the client cannot
        be disabled (and the timer therefore cannot start) unless this is enabled.

        Args:
            minutes: Duration in minutes (30–1440). The feature flag must already
                     be enabled on the tenant before this has any effect.
        """
        log.info("Setting clientAllDisableAutoReenableDuration=%d, allowClientDisabling=1", minutes)
        return self._update(
            clientAllDisableAutoReenableDuration=minutes,
            allowClientDisabling=1,
        )

    def clear_auto_reenable(self) -> bool:
        """
        Remove the auto-reenable duration (set to 0 / disabled).

        Keeps allowClientDisabling=1 so the client remains manually disable-able
        after the timer is cleared (teardown should not lock the client).
        """
        log.info("Clearing clientAllDisableAutoReenableDuration (allowClientDisabling stays 1)")
        return self._update(
            clientAllDisableAutoReenableDuration=0,
            allowClientDisabling=1,
        )

    def set_allow_client_disabling(self, enable: bool) -> bool:
        """Toggle allowClientDisabling (1=allow, 0=deny)."""
        val = 1 if enable else 0
        log.info("Setting allowClientDisabling = %d", val)
        return self._update(allowClientDisabling=val)
