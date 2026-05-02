# nsclient_test_base

Base framework for testing new NSClient (Netskope Client) features across Windows, macOS, and Linux.

Each NPLAN gets its own folder under `features/`. Test plans are fetched from Confluence,
converted to Markdown, then scaffolded into pytest suites.

```mermaid
flowchart LR
    A[Fetch test plan] 
    --> B[Convert the plan to MD]
    --> C[Implement tests]
    --> D[Run the tests]
```

---

## Prerequisites

- Python 3.10+, no virtual environment — install globally
- `pip install -r requirements.txt`

---

## ⚠️ First-Time Setup — Secrets (Required)

### Step 1 — Generate the encryption key

```
python tool/manage_secrets.py init
```

For all other secret setup and maintenance details, see [`secrects.md`](secrects.md).

---

## Setup

Edit `data/config.json` directly. Sensitive fields (api_token, password) are ignored here — use
`manage_secrets.py set` for those.

```json
{
    "tenant_hostname": "your-tenant.goskope.com",
    "is_64bit": true,
    "log_dir": "log",
    "confluence": {
        "base_url": "https://netskope.atlassian.net/wiki",
        "username": "you@netskope.com",
        "api_token": ""
    }
}
```

---

## Workflow — NPLAN to Tests

Detailed guide: [`workflow.md`](workflow.md)

### Step 1 — Fetch the test plan from Confluence

```
python tool/fetch_test_plan.py <confluence_url> --nplan NPLAN-XXXX
```

```
python tool/fetch_test_plan.py https://netskope.atlassian.net/wiki/spaces/CDTBA/pages/7875198997 --nplan NPLAN-6711
```

---

### Step 2 — Scaffold pytest from the Markdown

```
python tool/gen_test_suite.py test_plans/nplan-6711.md
```

```
python tool/gen_test_suite.py test_plans/nplan-6711.md --dry-run
```

---

### Step 3 — Implement the tests

```
/gen-test test_plans/nplan-6711.md A01 A02 A03
/gen-test test_plans/nplan-6711.md all
```

---

### Step 4 — Run the tests

```
python -m pytest features/nplan_6711_<slug>/ -v
```

```
python -m pytest features/ -m "windows and automated" -v
```

---

## Implemented Feature Tests

### NPLAN-6711: Auto Re-enable NSClient after Disable

**Location:** `features/nplan_6711_auto_reenable/`

```
features/nplan_6711_auto_reenable/
    conftest.py              # session fixtures, ensure_client_enabled, assert_auto_reenable helper
    test_auto_reenable.py    # A01, A02, A03
```

**Test cases:**

| ID  | Function | Priority | Platform | What it tests |
|-----|----------|----------|----------|---------------|
| A01 | `test_a01_auto_reenable_3min` | P0 | All | Disable → auto re-enable after 3 min timer |
| A02 | `test_a02_auto_reenable_10min_otp` | P0 | Windows | Disable with OTP → auto re-enable after 10 min |
| A03 | `test_a03_ff_off_no_auto_reenable` | P1 | All | FF off → disable stays disabled (negative) |

**Prerequisites — one-time setup only:**

1. Set `tenant_hostname` and `tenant_username` in `data/config.json`
2. Store the tenant admin password:
   `python tool/manage_secrets.py set tenant_password`
3. A02 additionally needs the OTP/uninstall password:
   `python tool/manage_secrets.py set uninstall_password`
4. Ensure feature flag `nplan6711_auto_reenable_ns_client_after_disablement` is
   **enabled** on the tenant for A01/A02 and **disabled** for A03.

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
```

> **Note:** Use `-s` to see real-time polling output. These are long-running integration tests
> that poll `nsdiag -f` every 10 seconds until the client re-enables or times out.

**Architecture:** All three tests share the `assert_auto_reenable()` helper (in conftest.py)
which handles the disable → poll → verify flow. It accepts an `interrupt` callback for
B-series tests (sleep/wake/reboot during the timer).

---

## Power Management
Detailed guide: [`power.md`](power.md)

---

## Running unit tests

Unit tests live in `test/` and run fully mocked — no admin, no services, no NSClient required.

```
python -m pytest -v
```

---

## Secrets commands and details

See [`secrects.md`](secrects.md).

---

## Project structure

```
.claude/
    agents/nsc_test_angel.md      # AI agent for NPLAN test development
    skills/gen-test.md            # /gen-test skill — generate implemented tests from test plan
data/
    config.json                   # Non-sensitive settings (git-tracked)
    secrets.json                  # Encrypted secrets (gitignored)
features/
    nplan_6711_auto_reenable/     # NPLAN-6711: Auto re-enable (A01–A03 implemented)
    nplan_XXXX_<name>/            # One folder per NPLAN
        conftest.py
        test_<feature>.py
test/
    conftest.py                   # Mocked fixtures for unit tests
    ut_backlog.md                 # Pending test coverage
test_plans/                       # Confluence-sourced Markdown
tool/
    fetch_test_plan.py            # Confluence → Markdown
    gen_test_suite.py             # Markdown → pytest scaffold
    manage_secrets.py             # Encrypted secret management
    pwrtest.exe                   # Windows sleep/wake tool (bundled from stress_test)
util_client_status.py             # Client status detection via nsdiag -f (all platforms)
util_webui.py                     # Tenant WebAPI client (pylark-webapi-lib wrapper)
util_config.py                    # Project config loader
util_crash.py                     # Crash dump detection
util_install.py                   # Install / uninstall (all platforms)
util_log.py                       # Logging setup
util_log_validator.py             # NSClient debug log reader and validator
util_nsclient.py                  # NSClient inspection
util_power.py                     # Sleep/wake/reboot (Windows full, macOS partial, Linux stub)
util_process.py                   # Process management
util_registry.py                  # Windows registry helpers
util_secrets.py                   # Encrypted secret store
util_service.py                   # Service control (all platforms)
CLAUDE.md                         # Coding standards + NSClient knowledge
knowledge_gap.md                  # Unresolved platform questions
pytest.ini                        # Markers, test discovery
requirements.txt
```
