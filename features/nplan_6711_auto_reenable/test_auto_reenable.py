"""
NPLAN-6711: Auto re-enable NSClient after disable timer.

Test cases A01–A03 (Functional).

Prerequisites:
  - tenant_hostname and tenant_username set in data/config.json
  - tenant_password stored:  python tool/manage_secrets.py set tenant_password
  - A02 additionally needs:  python tool/manage_secrets.py set uninstall_password
  - Feature flag nplan6711_auto_reenable_ns_client_after_disablement must be enabled
    on the tenant for A01/A02, disabled for A03.
"""

import re

import pytest

from util_log_validator import NsClientLogValidator


# ── A01: Auto re-enable after 3 minutes ──────────────────────────────────────

@pytest.mark.priority_high
@pytest.mark.p0
@pytest.mark.automated
def test_a01_auto_reenable_3min(
    ensure_client_enabled,
    configure_auto_reenable,
    log_validator: NsClientLogValidator,
    run_auto_reenable,
):
    """
    A01: Set Auto Re-enable duration to 3 minutes.

    Steps:
      1. Set clientAllDisableAutoReenableDuration=3 on tenant via WebAPI
      2. Sync config to client (nsdiag -u)
      3. Disable the client
      4. Observe client auto-re-enables when timer expires
      5. Verify log shows autoReenableDuration
      6. Verify client status uploaded to tenant
    """
    # Setup: push duration=3 to tenant and sync to client
    configure_auto_reenable(minutes=3)
    log_validator.seek_to_end()

    # Execute: disable → wait for auto re-enable
    run_auto_reenable(duration_minutes=3)

    # Verify: log patterns
    assert log_validator.check_log("autoReenableDuration"), (
        "Expected 'autoReenableDuration' in debug log after auto re-enable"
    )
    assert log_validator.check_log_regex(
        r"Client status posted successfully", re.IGNORECASE
    ), "Expected client status upload confirmation in debug log"


# ── A02: Auto re-enable after 10 minutes with OTP ────────────────────────────

@pytest.mark.priority_high
@pytest.mark.p0
@pytest.mark.windows
@pytest.mark.automated
def test_a02_auto_reenable_10min_otp(
    ensure_client_enabled,
    configure_auto_reenable,
    log_validator: NsClientLogValidator,
    run_auto_reenable,
):
    """
    A02: Set Auto Re-enable duration to 10 minutes with OTP.

    Steps:
      1. Set clientAllDisableAutoReenableDuration=10 on tenant via WebAPI
      2. Sync config to client (nsdiag -u)
      3. Verify OTP hash is present in synced nsconfig.json
      4. Disable the client with OTP password
      5. Observe client auto-re-enables when timer expires
      6. Verify log shows autoReenableDuration
      7. Verify client status uploaded to tenant
    """
    from util_nsclient import read_nsconfig
    from util_secrets import get_secret, SECRET_UNINSTALL_PASSWORD

    # Get OTP password before we touch the tenant config (fail fast if missing)
    pw = get_secret(SECRET_UNINSTALL_PASSWORD)
    if not pw:
        pytest.skip(
            "uninstall_password not in secrets store — run: "
            "python tool/manage_secrets.py set uninstall_password"
        )

    # Setup: push duration=10 to tenant and sync to client
    configure_auto_reenable(minutes=10)

    # Verify OTP hash is present after sync
    nsconfig = read_nsconfig()
    client_all_disable = nsconfig.get("clientConfig", {}).get("clientAllDisable", {})
    assert client_all_disable.get("hash", "") != "", (
        "OTP hash not found in nsconfig after sync — configure OTP password on tenant"
    )

    log_validator.seek_to_end()

    # Execute: disable with OTP → wait for auto re-enable
    run_auto_reenable(duration_minutes=10, password=pw)

    # Verify: log patterns
    assert log_validator.check_log("autoReenableDuration"), (
        "Expected 'autoReenableDuration' in debug log after auto re-enable"
    )
    assert log_validator.check_log_regex(
        r"Client status posted successfully", re.IGNORECASE
    ), "Expected client status upload confirmation in debug log"


# ── A03: Feature flag OFF — no auto re-enable ────────────────────────────────

@pytest.mark.priority_medium
@pytest.mark.p1
@pytest.mark.automated
def test_a03_ff_off_no_auto_reenable(
    ensure_client_enabled,
    configure_auto_reenable,
    log_validator: NsClientLogValidator,
    run_auto_reenable,
):
    """
    A03: Set FF nplan6711_auto_reenable_ns_client_after_disablement = 0.

    Steps:
      1. Set clientAllDisableAutoReenableDuration=0 on tenant via WebAPI (clear)
      2. Sync config to client (nsdiag -u)
      3. Verify autoReenableDuration is absent in nsconfig.json
      4. Disable the client
      5. Wait 120s — client must stay disabled (no timer)
      6. Verify no autoReenableDuration in logs
    """
    from util_nsclient import read_nsconfig

    # Setup: clear duration on tenant and sync to client
    configure_auto_reenable(minutes=0)

    # Verify duration is absent after sync
    nsconfig = read_nsconfig()
    client_all_disable = nsconfig.get("clientConfig", {}).get("clientAllDisable", {})
    assert "autoReenableDuration" not in client_all_disable, (
        f"autoReenableDuration should be absent when cleared, "
        f"got: {client_all_disable.get('autoReenableDuration')}"
    )

    log_validator.seek_to_end()

    # Execute: disable → confirm stays disabled (negative test)
    run_auto_reenable(duration_minutes=0, expect_reenable=False)

    # Verify: no auto-reenable log activity
    new_logs = log_validator.read_new_logs()
    assert "autoReenableDuration" not in new_logs, (
        "autoReenableDuration should NOT appear in logs when FF is off"
    )
