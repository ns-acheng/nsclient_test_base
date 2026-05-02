# Secrets setup and management

## First-Time Setup — Secrets (Required)

API tokens and passwords are **never stored in plaintext**. They are encrypted at rest using a
local key that lives **outside the repository**. You must complete this setup before running any
tool that contacts Confluence or installs NSClient.

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
| `tenant_password` | Tenant admin console login password (for WebAPI test setup) |

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
