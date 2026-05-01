# Knowledge Gap: macOS and Linux NSClient Support

Items marked **[BLOCKED]** cannot be implemented until answered.
Items marked **[ASSUMED]** are inferred from stress_test patterns — verify before use.
Items marked **✅ RESOLVED** are confirmed and already coded.

---

## macOS — Confirmed ✅

| Item | Confirmed Value | Notes |
|------|----------------|-------|
| ✅ M3 | Admin = `os.getuid() == 0` (root) | All service ops use sudo |
| ✅ M7 | Key processes: `nsAuxiliarySvc` (root XPC), `Netskope Client` (user UI), `NetskopeClientMacAppProxy` (sysext) | From `ps aux` |
| ✅ M9 | launchctl label: `com.netskope.client.auxsvc` | plist: `/Library/LaunchDaemons/com.netskope.client.auxsvc.plist` |
| ✅ M9 | Start: `launchctl bootstrap system <plist>` | NOT the old `launchctl start <label>` |
| ✅ M9 | Stop:  `launchctl bootout  system <plist>` | Same |
| ✅ M9 | Check: `launchctl list \| grep netskope` | Or `launchctl list com.netskope.client.auxsvc` |
| ✅ M9 | Install dir: `/Applications/Netskope Client.app` | From ps aux paths |
| ✅ Hosts | `/etc/hosts` | Standard Unix |

---

## macOS — Still Open

| # | Question | Impact | Status |
|---|----------|--------|--------|
| M1 | What is the exact `.pkg` filename? (`STAgent.pkg`? `NetskopeClient.pkg`?) | `util_install.py` | **[BLOCKED]** |
| M2 | How is uninstall done on macOS? (bundled script? `pkgutil --forget`? Uninstaller app?) | `util_install.py` | **[BLOCKED]** |
| M4 | Does macOS need `nsdiag -u` post-install like Windows? Same 30s wait? | `util_nsclient.py` sync_config() | **[BLOCKED]** |
| M5 | Is there a separate arm64 vs x86_64 `.pkg`? Different filename? | `util_install.py` | **[BLOCKED]** |
| M6 | Exact path of `nsdiag` on macOS — currently assumed `/Library/Application Support/Netskope/STAgent/nsdiag` | `util_nsclient.py`, `util_crash.py` | **[ASSUMED]** |
| M12 | Exact path of `nsdebuglog.log` on macOS — currently assumed `/Library/Logs/Netskope/stAgent/nsdebuglog.log` | `util_log_validator.py` | **[ASSUMED]** |
| M8 | Is `nsclient_watchdog_monitor` in nsconfig.json on macOS? (likely Windows-only) | `util_nsclient.py` parse_nsconfig() | **[ASSUMED: Windows-only]** |
| M10 | Is there a driver service on macOS equivalent to `stadrv`? If so, what is its plist label? | `util_service.py` SVC_DRIVER_MAC | **[BLOCKED]** |
| M11 | ✅ Watchdog is Windows-only — no watchdog service exists on macOS | `util_service.py` SVC_WATCHDOG_MAC | **✅ RESOLVED: N/A** |
| V1 | How to read installed version on macOS? (`pkgutil --pkg-info`? `Info.plist`? Binary `--version`?) | `util_nsclient.py` get_installed_version() | **[BLOCKED]** |
| V3 | How to read version from a `.pkg` before installing? | `util_nsclient.py` get_installer_version() | **[BLOCKED]** |

---

## Linux — Confirmed ✅

| Item | Confirmed Value | Notes |
|------|----------------|-------|
| ✅ L1 | `.run` silent install: `./STAgent.run -H <host> -o <orgKey> -m <email>` | Add `-c` for headless (no GUI) |
| ✅ L1 | `.deb` install: `dpkg -i <file>.deb` | Package name: `nsclient` |
| ✅ L1 | `.rpm` install: `rpm -ivh <file>.rpm` | — |
| ✅ L2 | Uninstall: `/opt/netskope/stagent/uninstall.sh` (primary) | For `.run` installs |
| ✅ L2 | Uninstall: `dpkg -r nsclient` | For `.deb` installs |
| ✅ L2 | Uninstall: `rpm -e <pkg>` (discovered via `rpm -qa \| grep nsclient`) | For `.rpm` installs |
| ✅ L3 | DEB package name: `nsclient` | Used in `dpkg -r` |
| ✅ L4 | `nsdiag -u` exists at `/opt/netskope/stagent/nsdiag` | Same sync concept as Windows |
| ✅ L5 | Primary binary: `/opt/netskope/stagent/stAgentSvc` | Confirmed via `ls` |
| ✅ L6 | Second process: `stagentapp` (UI/app service) | Two services, not daemon-only |
| ✅ L7 | Service units: `stagentd` (daemon) + `stagentapp` (UI/app) | `systemctl start/stop stagentd` |
| ✅ Paths | Install dir: `/opt/netskope/stagent/` | nsconfig.json also here |
| ✅ Paths | Crash/core: `/var/crash/*netskope*`, `/opt/netskope/stagent/log/core*`, `/opt/netskope/stagent/logs/core*`, `/tmp/core*` | — |

---

## Linux — Still Open

| # | Question | Impact | Status |
|---|----------|--------|--------|
| L8 | Driver service unit name on Linux (equivalent of `stadrv`)? | `util_service.py` SVC_DRIVER_LIN | **[BLOCKED]** |
| L9 | Watchdog service on Linux? Unit name? | `util_service.py` SVC_WATCHDOG_LIN | **[BLOCKED]** |
| V2 | How to read installed version on Linux? (`dpkg -l`? `rpm -qi`? binary `--version`?) | `util_nsclient.py` get_installed_version() | **[BLOCKED]** |
| V3 | How to read version from `.run` before installing? | `util_nsclient.py` get_installer_version() | **[BLOCKED]** |

---

## What Is Implemented vs. Blocked

### Fully implemented (all platforms)
- Power management — Windows ✅ (pwrtest + ctypes fallback), macOS ✅ (pmset), Linux ✅ (stub/reboot only)
- Service start/stop/query/wait — Windows ✅, macOS ✅, Linux ✅
- Process detect/kill/wait — all platforms ✅
- Registry helpers — Windows only ✅, graceful no-op on macOS/Linux ✅
- nsconfig.json read/parse — all platforms ✅ (same schema)
- sync_config (nsdiag -u) — all platforms ✅ (macOS nsdiag path assumed)
- detect_install_dir / verify_executables — all platforms ✅
- Admin check — Windows (`ctypes`) ✅, macOS/Linux (`os.getuid`) ✅
- Crash dump scan — all platforms ✅ (macOS patterns assumed)
- Log bundle collect — all platforms ✅
- Install — Windows (msiexec) ✅, macOS (installer -pkg) ✅, Linux (.run/.deb/.rpm) ✅
- Uninstall — Windows (msiexec/wmic) ✅, Linux (uninstall.sh/dpkg/rpm) ✅

### Raises NotImplementedError until gaps filled
- `_uninstall_mac()` — M2

### Returns empty string / warning until gaps filled
- `get_installed_version()` on macOS/Linux — V1/V2
- `get_installer_version()` on macOS/Linux — V3
