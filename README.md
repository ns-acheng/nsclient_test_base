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

- Python 3.10+
- `pip install -r requirements.txt`

---

## ⚠️ First-Time Setup — Secrets (Required)

### Step 1 — Generate the encryption key

```
python tool/manage_secrets.py init
```

For all other secret setup and maintenance details, see [`doc/secrets.md`](doc/secrets.md).

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

Detailed guide: [`doc/workflow.md`](doc/workflow.md)

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

### NPLAN-6711 details

See [`doc/nplan-6711-feature.md`](doc/nplan-6711-feature.md).

---

## Power Management
Detailed guide: [`doc/power.md`](doc/power.md)

---

## Running unit tests

Unit tests live in `test/` and run fully mocked — no admin, no services, no NSClient required.

```
python -m pytest -v
```

---

## Secrets commands and details

See [`doc/secrets.md`](doc/secrets.md).

---

## Project structure

```
.claude/
    agents/nsc_test_angel.md      # AI agent for NPLAN test development
    skills/gen-test/SKILL.md      # /gen-test skill — generate implemented tests from test plan
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
