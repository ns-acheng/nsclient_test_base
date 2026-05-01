# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

# Project Overview

Base framework for testing new NSClient (Netskope Client) features. Each feature/NPLAN is tested
in its own `features/nplan_XXXX/` folder. Test plans are sourced from Confluence and converted to
actionable Markdown in `test_plans/`. No `pylark-nsclient-lib` — all operations use direct
subprocess/registry/filesystem access.

## Python Requirements

- **Minimum Version**: Python 3.10+
- **No virtual environment** — install/run directly in the current global Python environment
- **Install dependencies**: `pip install -r requirements.txt`

## Code Style & Rules

### General

- **Line length**: Limit each line to 110 characters
- **Line endings**: Use Windows CRLF (`\r\n`) line breaks for all files
- **Naming**:
  - snake_case for files, functions, and variables
  - PascalCase for class names
  - UPPER_SNAKE_CASE for constants
  - Prefix interfaces with `I` (e.g., `IPowerManager`)
  - Prefix utility files with `util_` (e.g., `util_log.py`)
- **Type hints**: Use type hints for all function parameters and return types

### Import Organization

Organize imports in three groups with blank lines between:

```python
# 1. Standard library
import sys
import os

# 2. Third-party packages
import requests

# 3. Local modules
from util_config import ProjectConfig
```

### Documentation

- Add docstrings for public classes and non-trivial methods
- Use comments only where logic isn't self-evident
- Keep comments concise and relevant

## Architecture Principles

- **CLI entry point**: Use `argparse` for command-line argument parsing
- **Utility modules**: Separate concerns into `util_<name>.py` files
- **Configuration**: JSON config files stored in `data/`
- **Feature tests**: One folder per NPLAN under `features/`
- **Test plans**: Confluence-sourced Markdown stored in `test_plans/`

### File and Directory Organization

```
data/                # Configuration and data files (JSON)
features/            # Feature test suites (one folder per NPLAN)
  nplan_XXXX/        # Per-feature test folder
test/                # Unit tests for util_* modules
test_plans/          # Converted Confluence test plans (.md)
tool/                # Helper scripts (fetch_test_plan.py, gen_test_suite.py)
log/                 # Log output (generated at runtime)
```

## Logging

- Use Python's `logging` module exclusively
- Logger name: `log = logging.getLogger(__name__)` at module level
- **Levels**: INFO for normal ops, WARNING for non-blocking issues, ERROR for failures
- **Security**: Never log passwords, tokens, credentials, or sensitive data
- Set verbose third-party loggers to WARNING level

## Testing

- **Framework**: pytest
- **Test files**: `test/test_<module_name>.py`
- **Mock all I/O**: file system, network, and OS calls
- **No admin privileges** required to run tests
- Run: `python -m pytest test/ -v`

> ⚠️ **GOLDEN RULE — NO TEST ACTIVITY WITHOUT EXPLICIT INSTRUCTION**
> Never run, write, or update tests unless the user explicitly asks.
> This means: no `pytest`, no editing `test/` files, no creating new test
> files — under any circumstances, even for regression checks.
> Instead, when code changes create UT gaps, update `test/ut_backlog.md`
> with what needs to be covered. UT work is batched and done separately
> only after the user confirms the code works.

## Error Handling

- Wrap I/O and external calls in try-except blocks
- Use `logger.exception()` for full stack traces
- Clean up resources in `finally` blocks

## Security

- Never log or commit passwords, tokens, or credentials
- Validate all user inputs and configuration values
- Avoid shell command injection

## NSClient Knowledge

> Items marked **[ASSUMED]** need verification — see `knowledge_gap.md`.

### Key Paths

#### Windows
| Item | Path |
|------|------|
| nsconfig.json | `C:\ProgramData\netskope\stagent\nsconfig.json` |
| Install dir (64-bit) | `C:\Program Files\Netskope\STAgent` |
| Install dir (32-bit) | `C:\Program Files (x86)\Netskope\STAgent` |
| nsdiag.exe (64-bit) | `C:\Program Files\Netskope\STAgent\nsdiag.exe` |
| nsdiag.exe (32-bit) | `C:\Program Files (x86)\Netskope\STAgent\nsdiag.exe` |
| Install log | `C:\ProgramData\netskope\stagent\logs\nsInstallation.log` |
| MSI download cache | `C:\ProgramData\netskope\stagent\download\STAgent.msi` |
| Crash dumps | `C:\dump\stAgentSvc.exe\*.dmp`, `C:\ProgramData\netskope\stagent\logs\*.dmp` |
| Hosts file | `C:\Windows\System32\drivers\etc\hosts` |

#### macOS (✅ confirmed unless marked [ASSUMED])
| Item | Path |
|------|------|
| nsconfig.json | `/Library/Application Support/Netskope/STAgent/nsconfig.json` [ASSUMED] |
| Install dir | `/Applications/Netskope Client.app` |
| nsdiag | `/Library/Application Support/Netskope/STAgent/nsdiag` [ASSUMED M6] |
| Crash dumps | `~/Library/Logs/DiagnosticReports/Netskope Client*.ips` [ASSUMED] |
| Logs | `/Library/Logs/Netskope/stAgent/nsdebuglog.log` [ASSUMED] |
| Hosts file | `/etc/hosts` |

#### Linux (✅ confirmed)
| Item | Path |
|------|------|
| Install dir | `/opt/netskope/stagent/` |
| nsconfig.json | `/opt/netskope/stagent/nsconfig.json` |
| Config data | `/opt/netskope/stagent/data/` |
| Service logs | `/opt/netskope/stagent/log/` or `/opt/netskope/stagent/logs/` |
| User / CLI logs | `~/.netskope/stagent/` |
| nsdiag | `/opt/netskope/stagent/nsdiag` |
| Uninstall script | `/opt/netskope/stagent/uninstall.sh` |
| Crash dumps | `/var/crash/*netskope*`, `/opt/netskope/stagent/log/core*` |
| Hosts file | `/etc/hosts` |

### Services

#### Windows
| Constant | Service Name | Description |
|----------|-------------|-------------|
| `SVC_CLIENT_WIN` | `stAgentSvc` | Main client service |
| `SVC_WATCHDOG_WIN` | `stwatchdog` | Watchdog monitor |
| `SVC_DRIVER_WIN` | `stadrv` | Driver service |

#### macOS (✅ confirmed)
| Constant | Label / plist | Description |
|----------|--------------|-------------|
| `SVC_CLIENT_MAC` | `com.netskope.client.auxsvc` | Main service — `/Library/LaunchDaemons/com.netskope.client.auxsvc.plist` |
| `SVC_DRIVER_MAC` | unknown | See knowledge_gap.md M10 |
| `SVC_WATCHDOG_MAC` | unknown | See knowledge_gap.md M11 |

**macOS service control:**
```bash
# Stop
sudo launchctl bootout  system /Library/LaunchDaemons/com.netskope.client.auxsvc.plist
# Start
sudo launchctl bootstrap system /Library/LaunchDaemons/com.netskope.client.auxsvc.plist
# Check
sudo launchctl list | grep netskope
```

#### Linux (✅ confirmed)
| Constant | Unit Name | Description |
|----------|----------|-------------|
| `SVC_CLIENT_LIN` | `stagentd` | Main daemon service |
| `SVC_APP_LIN` | `stagentapp` | UI / app service |
| `SVC_DRIVER_LIN` | unknown | See knowledge_gap.md L8 |
| `SVC_WATCHDOG_LIN` | unknown | See knowledge_gap.md L9 |

**Linux service control:**
```bash
sudo systemctl start stagentd.service
sudo systemctl stop stagentd.service
sudo systemctl restart stagentd.service
systemctl status stagentd   # active (running)
systemctl status stagentapp # active (running)
```

**Linux install formats:**
```bash
# .run file
sudo chmod 755 STAgent.run && sudo ./STAgent.run
# .run silent with email
sudo ./STAgent.run -H <tenant> -o <orgKey> -m <email>
# .run headless (no GUI)
sudo ./STAgent.run -H <tenant> -o <orgKey> -m <email> -c
# DEB
sudo dpkg -i STAgent_amd64.deb
# RPM
sudo rpm -ivh STAgent_x86_64.rpm
```

**Linux uninstall:**
```bash
# .run installs
cd /opt/netskope/stagent/ && sudo ./uninstall.sh
# DEB
sudo dpkg -r nsclient
# RPM (find version first: rpm -qa | grep -i nsclient)
sudo rpm -e nsclient-99.0.0-3060.x86_64
```

**Linux CLI tools:**
```bash
nsclient show-status   # "Internet Security Enabled"
nsclient show-config   # gateway, org, user, tunnel, steering
nsdiag -s              # tunnel status
```

### Key Processes

#### Windows
- `stAgentSvc.exe` — Main service
- `stAgentUI.exe` — UI process
- `stAgentSvcMon.exe` — Watchdog monitor (watchdog mode only)
- `nsdiag.exe` — Diagnostic/sync tool

#### macOS (✅ confirmed from ps aux)
- `nsAuxiliarySvc` — Root XPC aux service (primary health indicator)
- `Netskope Client` — User-space UI app (`/Applications/Netskope Client.app/...`)
- `NetskopeClientMacAppProxy` — System extension (in `/Library/SystemExtensions/`)

#### Linux (✅ confirmed)
- `stAgentSvc` — Main daemon binary at `/opt/netskope/stagent/stAgentSvc`
- `stagentd` / `stagentapp` — systemd service processes
- `nsclient` — CLI tool (`nsclient show-status`, `nsclient show-config`)
- `nsdiag` — Diagnostic tool (`nsdiag -s` for tunnel status)

### nsconfig.json

- **`nsgw.host`** — Gateway hostname. Strip `gateway-` prefix to get tenant hostname.
- **`clientConfig.configurationName`** — Client config name assigned to this device.
- **`clientConfig.nsclient_watchdog_monitor`** — Watchdog flag. String `"true"` or `"false"` (not JSON
  boolean). Read as: `config["clientConfig"].get("nsclient_watchdog_monitor") == "true"`
- **`clientConfig.clientUpdate.allowAutoUpdate`** — Auto-update flag (boolean).

### Config Sync (nsdiag -u)

After fresh install, run `nsdiag.exe -u` to pull full config from tenant. Wait ~30 seconds after
the command for the config to be written to nsconfig.json, then re-read it.

### Registry

- `HKLM\SOFTWARE\Netskope\UpgradeInProgress` — DWORD, non-zero during upgrade
- `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall` — Add/Remove Programs entries
- `HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall` — 32-bit entries

### Installation Modes (msiexec)

All Windows installs use `msiexec /I "<msi>" [params] /qn`. Key parameters:

| Mode | Parameters |
|------|-----------|
| Token + Host | `token=<T> host=addon-<tenant>.<env>` |
| IDP | `installmode=idp host=addon-<tenant>.<env>` |
| IDP + tokens | `installmode=idp enrollauthtoken=<A> enrollencryptiontoken=<B> tenant=<T> domain=<D>` |
| Per-user | `mode=peruserconfig token=<T> enrollauthtoken=<A> enrollencryptiontoken=<B> host=...` |

## Git Workflow

- Main branch: `master`
- Create feature branches for new work
- Clear, descriptive commit messages
