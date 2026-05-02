---
name: gen-test
description: Generate fully implemented pytest test cases from a test plan Markdown file
disable-model-invocation: true
argument-hint: <test_plan.md> [TC-IDs...]
---

Given a test plan Markdown file and specific test case IDs, generate **fully implemented** pytest
test functions (not just scaffolds). This goes beyond `gen_test_suite.py` by producing real test
logic using the project's `util_*` toolkit.

## Arguments

$ARGUMENTS — one of:
- `<test_plan.md> <TC-IDs>` — e.g. `test_plans/nplan-6711.md A01 A02 A03`
- `<test_plan.md> all` — generate all test cases in the plan
- `<test_plan.md>` — (no IDs) list available test cases and ask which to generate

## Workflow

### 1. Read the test plan

Read the Markdown file from `test_plans/`. Extract:
- NPLAN ID and feature title
- Each test case: ID, title, priority, platform, steps, expected result

### 2. Determine feature folder

Target: `features/nplan_XXXX_<slug>/`
- If the folder already exists, read its `conftest.py` and existing test file to understand
  what fixtures and helpers are already defined. Generate only the NEW test cases.
- If the folder doesn't exist, create it with a new `conftest.py` and test file.

### 3. Analyse test cases for shared patterns

Before generating individual tests, look across the requested test cases:
- Do multiple tests follow the same flow with different parameters? → Create a **reusable helper
  function** in conftest.py (like `assert_auto_reenable` in NPLAN-6711).
- What nsconfig fields do the tests need? → Create session fixtures to read them.
- What preconditions are shared? → Create setup/teardown fixtures.
- Do any tests need secrets (passwords, tokens)? → Use `util_secrets.get_secret()`.

### 4. Generate conftest.py

Create feature-specific `conftest.py` with:
- Module docstring: `"""NPLAN-XXXX: Feature title.\n\nFeature-specific fixtures."""`
- Session fixtures for nsconfig fields the tests need
- Per-test fixtures for setup/teardown (e.g. `ensure_client_enabled`)
- If a reusable helper was identified in step 3:
  - Define it as a plain function (NOT a fixture)
  - Add a `@pytest.fixture()` that returns the callable (for injection into tests)
- Imports from `util_*` modules only — never shell out directly

### 5. Generate test file

`test_<feature_slug>.py` with:
- Module docstring with NPLAN, test case IDs, and prerequisites
- Each test function:
  - `@pytest.mark` decorators: `p0`/`p1`/`p2` + `priority_high`/`priority_medium`/`priority_low`,
    platform, `automated`/`manual`. Always apply BOTH the short alias (`p0`) and the long form
    (`priority_high`) so users can filter by either.
  - Function name: `test_<id>_<slug>` (e.g. `test_a01_auto_reenable_3min`)
  - Parameters: fixtures the test needs (injected by pytest)
  - Docstring: test case title + numbered steps
  - **Real implementation**: setup asserts, execute actions, verify results
  - Use log_validator for log checks when the test plan mentions observing logs
  - Use `get_client_status()` / `is_client_enabled()` / `is_client_disabled()` for status checks
  - Use `pytest.fail()` with descriptive messages for timeout failures
  - Use `pytest.skip()` with setup instructions when preconditions aren't met

### 6. Verify

Run `python -m pytest features/nplan_XXXX_<slug>/ --co -q` to confirm tests collect cleanly.

## Reference Implementation

The NPLAN-6711 auto-reenable tests are the gold standard. Study these files:
- `features/nplan_6711_auto_reenable/conftest.py` — session fixtures, per-test fixture, reusable helper
- `features/nplan_6711_auto_reenable/test_auto_reenable.py` — A01/A02/A03 implementations

Key patterns from that implementation:
- `run_auto_reenable` fixture returns `assert_auto_reenable` callable
- `configure_auto_reenable` factory fixture calls WebAPI then `sync_config()` — teardown clears state
- `log_validator.seek_to_end()` before the action, then `check_log()` / `check_log_regex()` after
- OTP tests get password from `util_secrets.get_secret()`, skip if not stored
- Negative tests (FF off) wait a fixed period and assert state HASN'T changed

## Toolkit APIs Available

Use ONLY these — never subprocess directly:

```python
# Client status
from util_client_status import get_client_status, is_client_enabled, is_client_disabled

# NSClient operations
from util_nsclient import (
    read_nsconfig, parse_nsconfig, get_nsconfig_info, sync_config,
    disable_client, enable_client,
    detect_install_dir, get_install_dir, get_installed_version,
    verify_executables,
)

# Log validation
from util_log_validator import NsClientLogValidator, init_validator

# Tenant WebAPI (configure tenant settings programmatically)
from util_webui import WebUIClient   # webui_client session fixture in features/conftest.py

# Service control
from util_service import query_service, is_running, start_service, stop_service, SVC_CLIENT

# Process management
from util_process import is_process_running, get_process_pid, kill_process, wait_for_process

# Power management (sleep/wake/reboot scenarios)
from util_power import enter_s0_and_wake, enter_s1_and_wake, enter_s4_and_wake, reboot

# Registry (Windows)
from util_registry import check_uninstall_entry, get_reg_dword, set_reg_dword

# Install/uninstall
from util_install import install, uninstall, is_admin

# Secrets
from util_secrets import get_secret, SECRET_UNINSTALL_PASSWORD, SECRET_INSTALL_TOKEN

# Crash dumps
from util_crash import check_crash_dumps, collect_log_bundle
```

## Code Standards

- 110 char line length, CRLF line endings
- snake_case functions/variables, PascalCase classes, UPPER_SNAKE_CASE constants
- Type hints on all function parameters and return types
- `log = logging.getLogger(__name__)` at module level
- Three-group imports: stdlib, third-party, local
- Docstrings on test functions with steps from the test plan

## GOLDEN RULE

After generating, add any new coverage gaps to `test/ut_backlog.md`. Never create or run
unit tests in `test/` unless the user explicitly asks.
