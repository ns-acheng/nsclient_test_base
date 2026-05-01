# Unit Test Backlog

Tests are written in separate sessions only after the user confirms the code works.
Add entries here when code changes create coverage gaps.

## Pending Coverage

| Module | Function/Class | Notes |
|--------|---------------|-------|
| util_log.py | `setup_logging` | Console handler level, file handler creation |
| util_config.py | `load_config` | Missing file returns defaults; JSON parse error |
| util_config.py | `save_config` | Sensitive fields stripped |
| util_service.py | `query_service` | Parses STATE line from sc output |
| util_service.py | `stop_service` | Polls until STOPPED; timeout path |
| util_process.py | `get_process_pid` | CSV parsing; no process found path |
| util_registry.py | `check_uninstall_entry` | Found and not-found paths |
| util_registry.py | `get_reg_dword` / `set_reg_dword` | Read/write DWORD |
| util_install.py | `install_msi` | Success path; non-zero rc raises InstallError |
| util_install.py | `uninstall_msi` | 1603 raises UninstallCriticalError; retry logic |
| util_nsclient.py | `parse_nsconfig` | gateway- prefix stripping; watchdog string bool |
| util_nsclient.py | `get_nsconfig_info` | File not found returns None |
| util_nsclient.py | `verify_executables` | Missing exe; version mismatch; watchdog mode |
| util_crash.py | `check_crash_dumps` | Zero-byte cleanup; real dump detection |
