# nsclient_test_base

Base framework for testing new NSClient (Netskope Client) features across Windows, macOS, and Linux.

Each NPLAN gets its own folder under `features/`. Test plans are fetched from Confluence,
converted to Markdown, then scaffolded into pytest suites.

---

## Prerequisites

- Python 3.10+, no virtual environment — install globally
- `pip install -r requirements.txt`

---

## ⚠️ First-Time Setup — Secrets (Required)

API tokens and passwords are **never stored in plaintext**. They are encrypted at rest using a
local key that lives **outside the repository**. You must complete this setup before running any
tool that contacts Confluence or installs NSClient.

### Step 1 — Generate the encryption key

```
python tool/manage_secrets.py init
```

This creates:
```
C:\Users\<you>\.nsclient_test_base\.secret_key
```

The key file lives outside the repo and is never committed. It is the only thing that can decrypt
your stored secrets. **Do not delete it.** If you lose it, all stored secrets must be re-entered.

### Step 2 — Store your secrets

Run each command below and paste the value when prompted. Input is not echoed to the terminal.

```
python tool/manage_secrets.py set confluence_api_token
python tool/manage_secrets.py set install_token
```

Store only the secrets you actually need. Full list of known names:

| Secret name | What it is |
|---|---|
| `confluence_api_token` | Atlassian API token — required for `fetch_test_plan.py` |
| `install_token` | NSClient install token (`msiexec token=...`) |
| `org_key` | Linux `.run` installer org key (`-o` flag) |
| `enroll_auth_token` | IDP install mode `enrollauthtoken=` |
| `enroll_encryption_token` | IDP install mode `enrollencryptiontoken=` |
| `uninstall_password` | NSClient uninstall password (if protection is enabled) |

### Step 3 — Verify

```
python tool/manage_secrets.py list
```

Expected output (example):
```
Stored secrets (2):
  confluence_api_token   — Confluence API token (for fetch_test_plan.py)
  install_token          — NSClient install token (msiexec token=...)
```

### Where things live

```
C:\Users\<you>\.nsclient_test_base\
    .secret_key          ← encryption key — outside repo, never in git

C:\git\nsclient_test_base\
    data\config.json     ← non-sensitive settings — git-tracked
    data\secrets.json    ← encrypted ciphertext — gitignored, never commit
```

`data/secrets.json` is in `.gitignore`. Even if it were accidentally committed, it is useless
without the key file.

---

## Non-sensitive configuration

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

### 1. Fetch the test plan from Confluence

```
python tool/fetch_test_plan.py https://netskope.atlassian.net/.../pages/123456 --nplan NPLAN-6711
```

Produces: `test_plans/nplan_6711_<slug>.md`

The Confluence API token is injected automatically from the secrets store.

### 2. Scaffold pytest from the Markdown

```
python tool/gen_test_suite.py test_plans/nplan_6711_<slug>.md
```

Produces: `features/nplan_6711_<slug>/conftest.py` + `test_<feature>.py`

Preview without writing:
```
python tool/gen_test_suite.py test_plans/<file>.md --dry-run
```

### 3. Implement and run the tests

```
python -m pytest features/nplan_6711_<slug>/ -v
```

Filter by marker:
```
python -m pytest features/ -m priority_high          # P0 only
python -m pytest features/ -m "windows and automated"
python -m pytest features/ -m "not manual"
```

---

## Running unit tests

Unit tests live in `test/` and run fully mocked — no admin, no services, no NSClient required.

```
python -m pytest -v
```

---

## Managing secrets

```
python tool/manage_secrets.py init              # First-time: generate key
python tool/manage_secrets.py set <name>        # Store/update a secret (prompts, no echo)
python tool/manage_secrets.py get <name>        # Print decrypted value
python tool/manage_secrets.py list              # List stored names
python tool/manage_secrets.py delete <name>     # Remove a secret
python tool/manage_secrets.py info              # Show key path, store path, all known names
```

### Rotating a secret

```
python tool/manage_secrets.py set confluence_api_token   # re-enter new value, overwrites old
```

### Moving to a new machine

The secrets store (`data/secrets.json`) is gitignored and not in the repo. On a new machine:

1. `python tool/manage_secrets.py init` — generates a **new** key
2. Re-enter all secrets: `python tool/manage_secrets.py set <name>` for each one

There is no export/import — each machine has its own key and its own local secrets file.

---

## Project structure

```
.claude/agents/nsc_test_angel.md  # AI agent for NPLAN test development
data/
    config.json                   # Non-sensitive settings (git-tracked)
    secrets.json                  # Encrypted secrets (gitignored)
features/
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
util_config.py                    # Project config loader
util_crash.py                     # Crash dump detection
util_install.py                   # Install / uninstall (all platforms)
util_log.py                       # Logging setup
util_nsclient.py                  # NSClient inspection
util_process.py                   # Process management
util_registry.py                  # Windows registry helpers
util_secrets.py                   # Encrypted secret store
util_service.py                   # Service control (all platforms)
CLAUDE.md                         # Coding standards + NSClient knowledge
knowledge_gap.md                  # Unresolved platform questions
pytest.ini                        # Markers, test discovery
requirements.txt
```
