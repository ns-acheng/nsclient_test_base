"""
NPLAN-6711: Auto re-enable NSClient after disable timer.

Feature-specific fixtures and the shared assert_auto_reenable() helper.
"""

import logging
import re
import time
from typing import Callable, Optional

import pytest

from util_client_status import is_client_enabled, is_client_disabled, get_client_status
from util_log_validator import NsClientLogValidator, init_validator
from util_nsclient import (
    disable_client,
    enable_client,
    read_nsconfig,
    sync_config,
)
from util_webui import WebUIClient

log = logging.getLogger(__name__)


# ── Session fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def log_validator() -> NsClientLogValidator:
    """Init log validator singleton for the session."""
    return init_validator()


@pytest.fixture(scope="session")
def raw_nsconfig() -> dict:
    """Read the full nsconfig.json dict. Skip session if unreadable."""
    try:
        return read_nsconfig()
    except Exception:
        pytest.skip("nsconfig.json not readable")


@pytest.fixture(scope="session")
def client_all_disable(raw_nsconfig: dict) -> dict:
    """Return the clientConfig.clientAllDisable section."""
    return raw_nsconfig.get("clientConfig", {}).get("clientAllDisable", {})


@pytest.fixture(scope="session")
def auto_reenable_duration(client_all_disable: dict) -> int:
    """Extract autoReenableDuration (minutes). Skip if absent (FF off)."""
    dur = client_all_disable.get("autoReenableDuration")
    if dur is None:
        pytest.skip("autoReenableDuration not set — configure tenant or enable FF first")
    return int(dur)


@pytest.fixture(scope="session")
def feature_flag_enabled(raw_nsconfig: dict) -> bool:
    """Return True if nplan6711 feature flag is enabled."""
    cc = raw_nsconfig.get("clientConfig", {})
    return str(cc.get(
        "nplan6711_auto_reenable_ns_client_after_disablement", "false"
    )).lower() == "true"


# ── Tenant configuration fixtures ────────────────────────────────────────────

@pytest.fixture()
def configure_auto_reenable(webui_client: WebUIClient):
    """
    Factory fixture: set autoReenableDuration on the tenant via WebAPI, then
    sync config to the client (nsdiag -u).

    Usage in tests:
        configure_auto_reenable(minutes=3)    # set duration and sync
        configure_auto_reenable(minutes=0)    # clear (FF off scenario)

    The fixture is a callable so each test controls its own duration.
    Teardown: always clears the duration (set to 0) after the test completes.
    """
    _set_minutes: list[int] = []

    def _configure(minutes: int) -> None:
        if minutes > 0:
            ok = webui_client.set_auto_reenable_duration(minutes)
        else:
            ok = webui_client.clear_auto_reenable()
        if not ok:
            pytest.fail(f"WebAPI: failed to set clientAllDisableAutoReenableDuration={minutes}")
        _set_minutes.append(minutes)
        log.info("Syncing config to client (nsdiag -u)…")
        if not sync_config():
            pytest.fail("nsdiag -u failed after setting autoReenableDuration on tenant")

    yield _configure

    # Teardown: restore to 0 so subsequent tests start from a clean state
    if _set_minutes and _set_minutes[-1] != 0:
        log.info("Teardown: clearing clientAllDisableAutoReenableDuration on tenant")
        webui_client.clear_auto_reenable()
        sync_config()


# ── Per-test fixtures ─────────────────────────────────────────────────────────

@pytest.fixture()
def ensure_client_enabled():
    """Ensure client is Enabled before the test. Re-enable in teardown if needed."""
    if not is_client_enabled():
        enable_client()
        time.sleep(5)
    yield
    if not is_client_enabled():
        enable_client()
        time.sleep(5)


# ── Reusable test helper ─────────────────────────────────────────────────────

@pytest.fixture()
def run_auto_reenable():
    """Expose assert_auto_reenable as a fixture-injected callable."""
    return assert_auto_reenable


def assert_auto_reenable(
    duration_minutes: int,
    password: Optional[str] = None,
    expect_reenable: bool = True,
    buffer_seconds: int = 60,
    poll_interval: float = 10.0,
    interrupt: Optional[Callable] = None,
) -> None:
    """
    Core test logic for NPLAN-6711 auto-reenable scenarios.

    1. Disable the client (optional OTP password).
    2. Assert the client is disabled.
    3. If ``interrupt`` is provided, call it (e.g. enter_s1_and_wake, reboot).
    4. If ``expect_reenable``:
         poll is_client_enabled() until True or timeout.
         Assert client re-enabled.
    5. If NOT ``expect_reenable``:
         wait 120s, assert client is STILL disabled.

    Args:
        duration_minutes: Expected auto-reenable duration from nsconfig.
        password: OTP password (None for no-password disable).
        expect_reenable: True if the client should auto-reenable.
        buffer_seconds: Extra seconds beyond duration_minutes to wait.
        poll_interval: Seconds between is_client_enabled() polls.
        interrupt: Optional callback to execute while the timer is running
                   (e.g. sleep/wake, reboot). Called after disable is confirmed.
    """
    # ── Disable ──────────────────────────────────────────────────────────
    ok = disable_client(password=password)
    assert ok, "nsdiag -t disable failed"
    time.sleep(3)  # brief settle

    status = get_client_status()
    assert is_client_disabled(), (
        f"Client should be Disabled after nsdiag -t disable, got: {status.internet_security}"
    )
    log.info("Client disabled — status: %s (source: %s)", status.internet_security, status.source)

    # ── Interrupt (sleep/wake/reboot) ────────────────────────────────────
    if interrupt is not None:
        log.info("Executing interrupt callback")
        interrupt()

    # ── Wait for re-enable (or confirm still disabled) ───────────────────
    if expect_reenable:
        timeout = duration_minutes * 60 + buffer_seconds
        deadline = time.monotonic() + timeout
        log.info("Waiting up to %ds for auto re-enable (%d min + %ds buffer)",
                 timeout, duration_minutes, buffer_seconds)

        while time.monotonic() < deadline:
            if is_client_enabled():
                log.info("Client auto-re-enabled after ~%.0fs",
                         timeout - (deadline - time.monotonic()))
                return  # success
            time.sleep(poll_interval)

        # Timeout — fail
        final = get_client_status()
        pytest.fail(
            f"Client did not auto-re-enable within {timeout}s. "
            f"Final status: {final.internet_security} (source: {final.source})"
        )
    else:
        # Negative case: wait 120s, confirm STILL disabled
        wait = 120
        log.info("Negative test — waiting %ds to confirm client stays disabled", wait)
        time.sleep(wait)
        status = get_client_status()
        assert is_client_disabled(), (
            f"Client should STILL be Disabled (FF off), got: {status.internet_security}"
        )
        log.info("Confirmed: client stayed disabled for %ds", wait)
