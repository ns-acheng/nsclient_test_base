"""
NSClient service control — Windows, macOS, Linux.

Windows : sc.exe          (service name, e.g. "stAgentSvc")
macOS   : launchctl       (plist path — bootstrap/bootout system <plist>)
Linux   : systemctl       (unit name — still assumed, see knowledge_gap.md L7)

macOS notes (confirmed):
  - Start : sudo launchctl bootstrap system /Library/LaunchDaemons/<label>.plist
  - Stop  : sudo launchctl bootout  system /Library/LaunchDaemons/<label>.plist
  - Check : launchctl list | grep netskope
  - Tool must run as root on macOS for service operations.
"""

import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# ── macOS plist directory ──────────────────────────────────────────────────────
_MAC_LAUNCHDAEMON_DIR = Path("/Library/LaunchDaemons")

# ── Service name / label constants ────────────────────────────────────────────

# Windows — sc.exe service names
SVC_CLIENT_WIN    = "stAgentSvc"
SVC_WATCHDOG_WIN  = "stwatchdog"
SVC_DRIVER_WIN    = "stadrv"

# macOS — launchctl labels (plist basename without .plist)
# Confirmed: com.netskope.client.auxsvc.plist in /Library/LaunchDaemons/
SVC_CLIENT_MAC    = "com.netskope.client.auxsvc"
SVC_WATCHDOG_MAC  = ""   # N/A — watchdog is Windows-only (confirmed)
SVC_DRIVER_MAC    = ""   # unknown — see knowledge_gap.md M10

# Linux — systemctl unit names (confirmed)
# Two services: stagentd (daemon) and stagentapp (UI/app)
SVC_CLIENT_LIN    = "stagentd"       # primary daemon service
SVC_APP_LIN       = "stagentapp"     # UI / app service
SVC_WATCHDOG_LIN  = ""   # unknown — see knowledge_gap.md L9
SVC_DRIVER_LIN    = ""   # unknown — see knowledge_gap.md L8

# Convenience: canonical names for the running platform
if sys.platform.startswith("win"):
    SVC_CLIENT   = SVC_CLIENT_WIN
    SVC_WATCHDOG = SVC_WATCHDOG_WIN
    SVC_DRIVER   = SVC_DRIVER_WIN
elif sys.platform.startswith("darwin"):
    SVC_CLIENT   = SVC_CLIENT_MAC
    SVC_WATCHDOG = SVC_WATCHDOG_MAC
    SVC_DRIVER   = SVC_DRIVER_MAC
else:
    SVC_CLIENT   = SVC_CLIENT_LIN
    SVC_WATCHDOG = SVC_WATCHDOG_LIN
    SVC_DRIVER   = SVC_DRIVER_LIN


@dataclass
class ServiceInfo:
    """Normalised service query result — same structure on all platforms."""
    name: str
    exists: bool
    state: str  # "RUNNING" | "STOPPED" | "NOT_FOUND" | "UNKNOWN" | "ERROR"


# ── Public API ─────────────────────────────────────────────────────────────────

def query_service(name: str) -> ServiceInfo:
    """Query the current state of an NSClient service."""
    if sys.platform.startswith("win"):
        return _query_win(name)
    if sys.platform.startswith("darwin"):
        return _query_mac(name)
    return _query_linux(name)


def is_running(name: str) -> bool:
    """Return True if the service is in RUNNING state."""
    return query_service(name).state == "RUNNING"


def start_service(name: str) -> bool:
    """Start the named service.  Returns True on success."""
    log.info("Starting service: %s", name)
    if sys.platform.startswith("win"):
        return _sc(["start", name], ok_codes={0, 1056})  # 1056 = already running
    if sys.platform.startswith("darwin"):
        return _launchctl_plist("bootstrap", name)
    return _systemctl(["start", name])


def stop_service(name: str, timeout: int = 30) -> bool:
    """Stop the named service and wait up to ``timeout`` seconds for STOPPED."""
    log.info("Stopping service: %s", name)
    if sys.platform.startswith("win"):
        ok = _sc(["stop", name], ok_codes={0, 1062})  # 1062 = not started
    elif sys.platform.startswith("darwin"):
        ok = _launchctl_plist("bootout", name)
    else:
        ok = _systemctl(["stop", name])

    if not ok:
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = query_service(name)
        if info.state in ("STOPPED", "NOT_FOUND"):
            log.info("Service stopped: %s", name)
            return True
        time.sleep(1)

    log.warning("Service %s did not stop within %ds", name, timeout)
    return False


def restart_service(name: str, stop_timeout: int = 30) -> bool:
    """Stop then start a service.  Returns True if both succeed."""
    if not stop_service(name, timeout=stop_timeout):
        return False
    return start_service(name)


def wait_for_running(name: str, timeout: int = 60, interval: float = 2.0) -> bool:
    """Poll until the service is RUNNING or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_running(name):
            log.info("Service running: %s", name)
            return True
        time.sleep(interval)
    log.warning("Service %s not running after %ds", name, timeout)
    return False


# ── Windows ────────────────────────────────────────────────────────────────────

def _query_win(name: str) -> ServiceInfo:
    try:
        result = subprocess.run(
            ["sc", "query", name],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        log.exception("sc query failed: %s", name)
        return ServiceInfo(name=name, exists=False, state="ERROR")

    if "FAILED 1060" in result.stdout.upper() or result.returncode == 1060:
        return ServiceInfo(name=name, exists=False, state="NOT_FOUND")

    state = "UNKNOWN"
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("STATE"):
            parts = stripped.split()
            if len(parts) >= 4:
                state = parts[3]
            break

    return ServiceInfo(name=name, exists=True, state=state)


def _sc(args: list[str], ok_codes: set[int]) -> bool:
    try:
        result = subprocess.run(
            ["sc"] + args,
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode not in ok_codes:
            log.error("sc %s failed (rc=%d): %s", args, result.returncode, result.stdout.strip())
            return False
        return True
    except Exception:
        log.exception("sc command failed: %s", args)
        return False


# ── macOS ──────────────────────────────────────────────────────────────────────

def _plist_path_mac(label: str) -> str:
    """Resolve the plist path from a launchd label."""
    return str(_MAC_LAUNCHDAEMON_DIR / f"{label}.plist")


def _query_mac(label: str) -> ServiceInfo:
    """
    Query via ``launchctl list <label>``.

    The output is plist-format when the service is known to launchd.
    If "PID" appears in the output the service is running.
    Requires root on macOS for system-level services.
    """
    try:
        result = subprocess.run(
            ["launchctl", "list", label],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        log.exception("launchctl list failed: %s", label)
        return ServiceInfo(name=label, exists=False, state="ERROR")

    if result.returncode != 0:
        return ServiceInfo(name=label, exists=False, state="NOT_FOUND")

    # When running, output contains:  "PID" = <number>;
    state = "RUNNING" if '"PID"' in result.stdout else "STOPPED"
    return ServiceInfo(name=label, exists=True, state=state)


def _launchctl_plist(action: str, label: str) -> bool:
    """
    Run ``launchctl <action> system <plist_path>``.

    ``action`` must be "bootstrap" or "bootout".
    Requires root.
    """
    plist = _plist_path_mac(label)
    log.debug("launchctl %s system %s", action, plist)
    try:
        result = subprocess.run(
            ["launchctl", action, "system", plist],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            log.error(
                "launchctl %s system %s failed (rc=%d): %s",
                action, plist, result.returncode, result.stderr.strip() or result.stdout.strip(),
            )
            return False
        return True
    except Exception:
        log.exception("launchctl %s failed: %s", action, plist)
        return False


# ── Linux ──────────────────────────────────────────────────────────────────────

def _query_linux(name: str) -> ServiceInfo:
    """Use ``systemctl is-active`` to check service state."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        log.exception("systemctl is-active failed: %s", name)
        return ServiceInfo(name=name, exists=False, state="ERROR")

    # systemctl exit codes: 0=active, 3=inactive/failed, 4=not found
    if result.returncode == 4:
        return ServiceInfo(name=name, exists=False, state="NOT_FOUND")

    state_map = {
        "active":       "RUNNING",
        "inactive":     "STOPPED",
        "failed":       "STOPPED",
        "activating":   "START_PENDING",
        "deactivating": "STOP_PENDING",
    }
    state = state_map.get(result.stdout.strip().lower(), "UNKNOWN")
    return ServiceInfo(name=name, exists=True, state=state)


def _systemctl(args: list[str]) -> bool:
    try:
        result = subprocess.run(
            ["systemctl"] + args,
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            log.error("systemctl %s failed (rc=%d): %s", args, result.returncode, result.stderr.strip())
            return False
        return True
    except Exception:
        log.exception("systemctl command failed: %s", args)
        return False
