# NPLAN-6711: Auto Re-enable NSClient after Disable

**Location:** `features/nplan_6711_auto_reenable/`

```
features/nplan_6711_auto_reenable/
    conftest.py                # session fixtures, ensure_client_enabled, assert_auto_reenable helper
    test_auto_reenable.py      # A01, A02, A03
    test_auto_reenable_b.py    # B01, B02, B03 (robustness / interrupt scenarios)
```

**Test cases:**

| ID  | Function | Priority | Platform | What it tests |
|-----|----------|----------|----------|---------------|
| A01 | `test_a01_auto_reenable_3min` | P0 | All | Disable → auto re-enable after 3 min timer |
| A02 | `test_a02_auto_reenable_10min_otp` | P0 | Windows | Disable with OTP → auto re-enable after 10 min |
| A03 | `test_a03_ff_off_no_auto_reenable` | P1 | All | FF off → disable stays disabled (negative) |
| B01 | `test_b01_encrypted_config_auto_reenable` | P1 | All | encryptClientConfig=1 + 3 min timer |
| B02a | `test_b02_reboot_before_timer_expires` | P1 | All | Reboot during timer — timer continues after boot |
| B02b | `test_b02_reboot_after_timer_expires` | P1 | All | Wait past timer, then reboot — client already re-enabled |
| B03a | `test_b03_sleep_wake_before_timer_expires` | P1 | All | Sleep 30s during 3 min timer — timer continues after wake |
| B03b | `test_b03_sleep_wake_after_timer_expires` | P1 | All | Sleep 240s through timer — re-enables immediately on wake |

**Prerequisites — one-time setup only:**

1. Set `tenant_hostname` and `tenant_username` in `data/config.json`
2. Store the tenant admin password:
   `python tool/manage_secrets.py set tenant_password`
3. A02 additionally needs the OTP/uninstall password:
   `python tool/manage_secrets.py set uninstall_password`
4. Ensure feature flag `nplan6711_auto_reenable_ns_client_after_disablement` is
   **enabled** on the tenant for A01/A02/B-series and **disabled** for A03.
5. B02/B03 require **admin/elevated privileges** — use the `require_admin` fixture.
6. B02 (reboot) requires the test runner to be configured to resume after reboot
   (e.g. Windows Task Scheduler).
7. B03 (sleep/wake) requires a sleep-capable machine (S1 standby or modern standby).

The tests configure `clientAllDisableAutoReenableDuration` on the tenant automatically
via WebAPI (`util_webui.py` → `pylark-webapi-lib`) and run `nsdiag -u` to sync the
config down to the client — no manual console steps required.

**Run commands:**

```
# Dry-run — verify tests collect without errors
python -m pytest features/nplan_6711_auto_reenable/ --co -q

# Run A01 only (waits ~4 min)
python -m pytest features/nplan_6711_auto_reenable/ -k a01 -v -s

# Run A02 only (waits ~11 min, needs stored OTP password)
python -m pytest features/nplan_6711_auto_reenable/ -k a02 -v -s

# Run A03 only (waits ~2 min, negative test)
python -m pytest features/nplan_6711_auto_reenable/ -k a03 -v -s

# Run all A-series
python -m pytest features/nplan_6711_auto_reenable/ -k "a01 or a02 or a03" -v -s

# Run P0 only (A01 + A02)
python -m pytest features/nplan_6711_auto_reenable/ -m p0 -v -s

# Run B01 only (encrypted config, ~4 min)
python -m pytest features/nplan_6711_auto_reenable/ -k b01 -v -s

# Run B02 (reboot tests — requires admin + Task Scheduler resume config)
python -m pytest features/nplan_6711_auto_reenable/ -k b02 -v -s

# Run B03 (sleep/wake tests — requires admin + sleep-capable machine)
python -m pytest features/nplan_6711_auto_reenable/ -k b03 -v -s

# Run all B-series
python -m pytest features/nplan_6711_auto_reenable/ -k "b01 or b02 or b03" -v -s
```

> **Note:** Use `-s` to see real-time polling output. These are long-running integration tests
> that poll `nsdiag -f` every 10 seconds until the client re-enables or times out.

**Architecture:** All three tests share the `assert_auto_reenable()` helper (in `conftest.py`)
which handles the disable → poll → verify flow. It accepts an `interrupt` callback for
B-series tests (sleep/wake/reboot during the timer).
