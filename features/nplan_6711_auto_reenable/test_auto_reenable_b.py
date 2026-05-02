"""
NPLAN-6711: Auto re-enable NSClient after disable timer.

Test cases B01–B03 (Robustness / Interrupt scenarios).

Prerequisites:
  - Same as A-series: tenant_hostname, tenant_username in data/config.json,
    tenant_password stored in secrets.
  - B02/B03 require admin/root privileges (reboot, sleep/wake).
  - B03 requires a sleep-capable machine (S1 standby or modern standby).
"""

import logging
from functools import partial

import pytest

from util_log_validator import NsClientLogValidator
from util_power import enter_s1_and_wake, reboot

log = logging.getLogger(__name__)


# ── B01: Encrypted config + auto re-enable 3 min ────────────────────────────

@pytest.mark.priority_medium
@pytest.mark.p1
@pytest.mark.automated
def test_b01_encrypted_config_auto_reenable(
    ensure_client_enabled,
    configure_auto_reenable,
    log_validator: NsClientLogValidator,
    run_auto_reenable,
    webui_client,
):
    """
    B01: encryptClientConfig=1 with Auto Re-enable duration 3 minutes.

    Steps:
      1. Enable encryptClientConfig on tenant via WebAPI
      2. Set autoReenableDuration=3 on tenant, sync to client
      3. Disable the client
      4. Observe client auto-re-enables when timer expires
      5. Verify timer works correctly with encrypted config
    """
    # Setup: enable encrypted config
    ok = webui_client._update(encryptClientConfig=1)
    if not ok:
        pytest.fail("WebAPI: failed to set encryptClientConfig=1")

    configure_auto_reenable(minutes=3)
    log_validator.seek_to_end()

    # Execute: same flow as A01 — timer should work with encrypted config
    run_auto_reenable(duration_minutes=3)

    # Verify
    assert log_validator.check_log("autoReenableDuration"), (
        "Expected 'autoReenableDuration' in debug log (encrypted config mode)"
    )


# ── B02: Reboot during timer ────────────────────────────────────────────────

@pytest.mark.priority_medium
@pytest.mark.p1
@pytest.mark.automated
def test_b02_reboot_before_timer_expires(
    ensure_client_enabled,
    configure_auto_reenable,
    log_validator: NsClientLogValidator,
    run_auto_reenable,
    require_admin,
):
    """
    B02a: Trigger timer, reboot, boot BEFORE timer expires.

    Steps:
      1. Set autoReenableDuration=3 on tenant, sync to client
      2. Disable the client (timer starts)
      3. Reboot immediately (boot time < 3 min)
      4. After reboot, timer should continue running
      5. Observe client auto-re-enables when timer expires

    Note: This test triggers a real reboot. The test runner must be
    configured to resume after reboot (e.g. Windows Task Scheduler).
    """
    configure_auto_reenable(minutes=3)
    log_validator.seek_to_end()

    # Execute: disable → reboot → wait for timer to expire
    # reboot() is the interrupt — called after disable is confirmed
    run_auto_reenable(
        duration_minutes=3,
        interrupt=reboot,
        buffer_seconds=120,  # extra buffer for reboot time
    )

    assert log_validator.check_log("autoReenableDuration"), (
        "Expected 'autoReenableDuration' in debug log after reboot + re-enable"
    )


@pytest.mark.priority_medium
@pytest.mark.p1
@pytest.mark.automated
def test_b02_reboot_after_timer_expires(
    ensure_client_enabled,
    configure_auto_reenable,
    run_auto_reenable,
    require_admin,
):
    """
    B02b: Trigger timer, reboot AFTER timer expires.

    Steps:
      1. Set autoReenableDuration=3 on tenant, sync to client
      2. Disable the client (timer starts)
      3. Wait for timer to expire + extra, then reboot
      4. After reboot, client should already be re-enabled

    Note: This test triggers a real reboot. The test runner must be
    configured to resume after reboot.
    """
    import time
    from util_client_status import is_client_enabled

    configure_auto_reenable(minutes=3)

    # Execute: disable → wait past timer → reboot
    # Use a long sleep as the interrupt to ensure timer expires before reboot
    def wait_then_reboot() -> None:
        wait = 3 * 60 + 30  # 3.5 min — past the 3 min timer
        log.info("Waiting %ds for timer to expire before rebooting", wait)
        time.sleep(wait)
        # Client should already be re-enabled by now
        if is_client_enabled():
            log.info("Client already re-enabled before reboot — good")
        reboot()

    run_auto_reenable(
        duration_minutes=3,
        interrupt=wait_then_reboot,
        buffer_seconds=120,
    )


# ── B03: Sleep/wake during timer ────────────────────────────────────────────

@pytest.mark.priority_medium
@pytest.mark.p1
@pytest.mark.automated
def test_b03_sleep_wake_before_timer_expires(
    ensure_client_enabled,
    configure_auto_reenable,
    log_validator: NsClientLogValidator,
    run_auto_reenable,
    require_admin,
):
    """
    B03a: Trigger timer, sleep, wake BEFORE timer expires.

    Steps:
      1. Set autoReenableDuration=3 on tenant, sync to client
      2. Disable the client (timer starts)
      3. Put system to sleep for 30s (wake before 3 min timer)
      4. After wake, timer should continue running
      5. Observe client auto-re-enables when timer expires
    """
    configure_auto_reenable(minutes=3)
    log_validator.seek_to_end()

    # Sleep 30s — well before the 3 min timer expires
    run_auto_reenable(
        duration_minutes=3,
        interrupt=partial(enter_s1_and_wake, duration_seconds=30),
    )

    assert log_validator.check_log("autoReenableDuration"), (
        "Expected 'autoReenableDuration' in debug log after sleep/wake + re-enable"
    )


@pytest.mark.priority_medium
@pytest.mark.p1
@pytest.mark.automated
def test_b03_sleep_wake_after_timer_expires(
    ensure_client_enabled,
    configure_auto_reenable,
    log_validator: NsClientLogValidator,
    run_auto_reenable,
    require_admin,
):
    """
    B03b: Trigger timer, sleep THROUGH timer expiry, then wake.

    Steps:
      1. Set autoReenableDuration=3 on tenant, sync to client
      2. Disable the client (timer starts)
      3. Put system to sleep for 240s (wake after 3 min timer)
      4. After wake, client should re-enable immediately
    """
    configure_auto_reenable(minutes=3)
    log_validator.seek_to_end()

    # Sleep 240s (4 min) — past the 3 min timer
    run_auto_reenable(
        duration_minutes=3,
        interrupt=partial(enter_s1_and_wake, duration_seconds=240),
        buffer_seconds=30,  # should re-enable almost immediately after wake
    )

    assert log_validator.check_log("autoReenableDuration"), (
        "Expected 'autoReenableDuration' in debug log after sleep-through + re-enable"
    )
