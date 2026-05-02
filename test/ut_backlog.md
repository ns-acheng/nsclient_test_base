# Unit Test Backlog

Tests are written in separate sessions only after the user confirms the code works.
Add entries here when code changes create coverage gaps.

## Pending Coverage

### util_client_status.py  (platform-gated)
- `_parse_nsdiag_field` — finds key::value line; case-insensitive; trailing dot stripped; missing field → None
- `_map_client_status` — enable → Enabled; disable → Disabled; enroll → Unenrolled; fail close → Fail-closed; error → Disabled (error); unknown raw → Unknown
- `_run_nsdiag_f` — nsdiag not found → None; empty output → None; happy path parses client+tunnel fields
- `_mainframe_title_win` — "enroll" in title → Unenrolled; no window → None
- `_service_state_win` — STOPPED → Disabled; RUNNING → Unknown
- `_status_mac` — nsdiag success; service STOPPED fallback
- `_status_linux` — nsdiag success; service STOPPED fallback
- `is_client_enabled` / `is_client_disabled` — state membership checks

### util_log.py
- `setup_logging` — console handler level, file handler creation, duplicate-handler guard

### util_config.py
- `load_config` — missing file returns defaults; JSON parse error; sensitive field stripping
- `load_config` + `_inject_secrets` — token injected when secrets store has it; skipped when blank; silently skipped when key missing
- `save_config` — api_token/password fields zeroed out even when in-memory token was injected from secrets

### util_service.py  (platform-gated)
- `query_service` / `_query_win` — parses STATE line from sc output; FAILED 1060 path
- `query_service` / `_query_mac` — PID vs "-" in launchctl output
- `query_service` / `_query_linux` — systemctl returncode mapping
- `stop_service` — polls until STOPPED; timeout path
- `start_service` — already-running rc codes ignored

### util_process.py  (platform-gated)
- `_pid_win` — CSV parsing; "No tasks" path
- `_pid_unix` — pgrep rc != 0 returns None
- `kill_process` / `_kill_unix` — ProcessLookupError handled gracefully
- `wait_for_process` — running=True and running=False paths

### util_registry.py  (Windows-only)
- `check_uninstall_entry` — found path; not-found path; non-Windows returns found=False
- `get_reg_dword` — returns None on non-Windows and on missing key
- `set_reg_dword` — returns False on non-Windows
- `check_upgrade_in_progress` — True/False from DWORD value

### util_install.py  (platform-gated)
- `is_admin` — Windows ctypes path; Unix os.getuid() path
- `_install_msi` — success path; non-zero rc raises InstallError
- `_uninstall_msi` — 1603 raises UninstallCriticalError; retry logic; _kill_msiexec called
- `_install_pkg_mac` — success path; non-zero rc raises InstallError
- `_uninstall_mac` — raises NotImplementedError
- `_install_run_linux` — .run chmod+exec; .deb dpkg -i; .rpm rpm -ivh; non-zero rc raises InstallError
- `_uninstall_linux` — cascading fallback: uninstall.sh → dpkg -r → rpm -e; method param routing

### util_nsclient.py  (platform-gated)
- `parse_nsconfig` — gateway- prefix stripping; watchdog string boolean; missing fields
- `get_nsconfig_info` — FileNotFoundError returns None; JSON error returns None
- `sync_config` — nsdiag not found returns False; remaining_wait logic
- `detect_install_dir` — 64-bit found first; neither found returns None
- `verify_executables` — missing exe; version mismatch; watchdog mode adds extra exe
- `_get_file_version_unix` — token extraction from --version output

### util_crash.py  (platform-gated)
- `check_crash_dumps` — zero-byte file removed; real dump detected; custom_dump_path appended
- `collect_log_bundle` — nsdiag not found; output file exists vs missing

### tool/fetch_test_plan.py
- `extract_page_id` — /pages/123456 format; ?pageId= format; bare numeric; invalid URL raises ValueError
- `parse_test_plan_html` — table with row-per-tc; table with no matching headers → empty; list fallback
- `_map_columns` — synonym matching; returns empty dict when no title/steps found
- `_normalise_priority` — P0/P1/P2 + synonyms (critical, major, minor)
- `_normalise_automatable` — Yes/No/Partial + synonyms
- `generate_markdown` — sections, test cases, raw fallback when no TCs found
- `slugify` — special chars removed; length capped

### util_log_validator.py
- `NsClientLogValidator.seek_to_end` — position set to file size; pending_reads cleared
- `NsClientLogValidator.check_log` — literal match in new content; advances position
- `NsClientLogValidator.check_log_regex` — regex match with flags; advances position
- `NsClientLogValidator.read_new_logs` — rotation via inode change; size rollback (Windows); pending drain
- `NsClientLogValidator._scan_for_time` — finds byte position older than target_time; returns False when file empty
- `NsClientLogValidator._find_by_inode` — finds rotated file by inode; returns None if not found
- `init_validator` / `get_validator` — singleton init; RuntimeError when uninitialised
- `check_log` / `check_log_regex` / `read_new_logs` module wrappers — delegate to singleton

### util_power.py  (platform-gated)
- `enter_s0_and_wake` — dispatches to win/mac/linux; Linux returns False
- `enter_s1_and_wake` — dispatches correctly per platform
- `enter_s4_and_wake` — Windows AOAC check skips pwrtest; macOS maps to s1
- `is_sleep_state_available` — Windows: parses powercfg available section only; ZH-TW aliases
- `enable_wake_timers` — Windows: 3 powercfg commands; macOS: True; Linux: False
- `reboot` — correct command per platform
- `_win_run_pwrtest` — returns False when pwrtest.exe missing
- `_win_set_wake_timer` — returns None on CreateWaitableTimerW failure

### util_secrets.py
- `init_key` — creates key file at correct path; chmod 600 on Unix; force=True overwrites
- `store_secret` — auto-inits key on first call; ciphertext written to store; metadata updated
- `get_secret` — round-trip decrypt matches original; missing key returns None; missing name returns None
- `list_secrets` — excludes _meta keys; empty store returns []
- `delete_secret` — removes entry; missing name returns False

### tool/manage_secrets.py
- `cmd_init` — creates key, prints paths
- `cmd_list` — shows known-secret descriptions; empty store message
- `cmd_info` — reports exists/missing for key and store

### tool/gen_test_suite.py
- `parse_test_plan_md` — H1 NPLAN extraction; TC heading parsing; field lines; numbered steps
- `_build_markers` — priority → marker; platform → marker; automatable → marker
- `generate_test_file` — markers applied; docstring has steps/expected; manual → pytest.skip
- `generate_conftest` — placeholder content with correct NPLAN in docstring
- `write_feature_folder` — creates folder, conftest.py, test file; respects --output override
