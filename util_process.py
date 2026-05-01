"""
NSClient process management — Windows, macOS, Linux.

Windows : tasklist / taskkill
macOS   : pgrep / kill  (confirmed process names from ps aux)
Linux   : pgrep / kill  [ASSUMED process names — verify L5 in knowledge_gap.md]

macOS confirmed processes (from ps aux):
  nsAuxiliarySvc       — root, XPC aux service  ← primary service process
  Netskope Client      — user, main UI app
  NetskopeClientMacAppProxy — system extension (long path, pgrep by partial name)
"""

import csv
import io
import logging
import subprocess
import sys
import time
from typing import Optional

log = logging.getLogger(__name__)

# ── Process name constants ─────────────────────────────────────────────────────

# Windows
PROC_CLIENT_WIN  = "stAgentSvc.exe"
PROC_UI_WIN      = "stAgentUI.exe"

# macOS (confirmed from ps aux output)
PROC_CLIENT_MAC  = "nsAuxiliarySvc"          # root XPC service — primary health indicator
PROC_UI_MAC      = "Netskope Client"          # user-space UI app
PROC_SYSEXT_MAC  = "NetskopeClientMacAppProxy"  # system extension

# Linux (confirmed: binary at /opt/netskope/stagent/stAgentSvc; services stagentd + stagentapp)
PROC_CLIENT_LIN  = "stAgentSvc"      # confirmed: ls /opt/netskope/stagent/stAgentSvc
PROC_APP_LIN     = "stagentapp"      # UI/app service process

# Convenience: primary client process for the running platform
if sys.platform.startswith("win"):
    PROC_CLIENT = PROC_CLIENT_WIN
elif sys.platform.startswith("darwin"):
    PROC_CLIENT = PROC_CLIENT_MAC
else:
    PROC_CLIENT = PROC_CLIENT_LIN


# ── Public API ─────────────────────────────────────────────────────────────────

def is_process_running(name: str) -> bool:
    """Return True if at least one process matching ``name`` is running."""
    if sys.platform.startswith("win"):
        return _is_running_win(name)
    return _is_running_unix(name)


def get_process_pid(name: str) -> Optional[int]:
    """Return the PID of the first matching process, or None if not found."""
    if sys.platform.startswith("win"):
        return _pid_win(name)
    return _pid_unix(name)


def kill_process(name: str) -> bool:
    """Force-kill all processes matching ``name``.  Returns True on success."""
    log.info("Killing process: %s", name)
    if sys.platform.startswith("win"):
        return _kill_win(name)
    return _kill_unix(name)


def wait_for_process(
    name: str,
    timeout: int = 60,
    interval: float = 2.0,
    running: bool = True,
) -> bool:
    """
    Poll until the process reaches the desired state within ``timeout`` seconds.

    Args:
        name: Process name (platform-appropriate).
        timeout: Maximum seconds to wait.
        interval: Poll interval in seconds.
        running: If True, wait until running; if False, wait until gone.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_process_running(name) == running:
            return True
        time.sleep(interval)
    return False


# ── Windows ────────────────────────────────────────────────────────────────────

def _is_running_win(name: str) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        return name.lower() in result.stdout.lower()
    except Exception:
        log.exception("tasklist failed for: %s", name)
        return False


def _pid_win(name: str) -> Optional[int]:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        log.exception("tasklist /FO CSV failed for: %s", name)
        return None

    stdout = result.stdout.strip()
    if not stdout or "No tasks" in stdout:
        return None

    try:
        reader = csv.reader(io.StringIO(stdout))
        for row in reader:
            if len(row) >= 2:
                return int(row[1])
    except (ValueError, StopIteration):
        pass
    return None


def _kill_win(name: str) -> bool:
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", name],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode not in (0, 128):  # 128 = no matching process
            log.warning("taskkill %s rc=%d: %s", name, result.returncode, result.stdout.strip())
            return False
        return True
    except Exception:
        log.exception("taskkill failed for: %s", name)
        return False


# ── macOS / Linux (pgrep / kill) ───────────────────────────────────────────────

def _is_running_unix(name: str) -> bool:
    """
    Use ``pgrep -f <name>`` for broad substring match.
    Works for both short names ("nsAuxiliarySvc") and partial paths.
    """
    try:
        result = subprocess.run(
            ["pgrep", "-f", name],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        log.exception("pgrep failed for: %s", name)
        return False


def _pid_unix(name: str) -> Optional[int]:
    try:
        result = subprocess.run(
            ["pgrep", "-f", name],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        lines = result.stdout.strip().splitlines()
        if not lines:
            return None
        return int(lines[0])
    except (ValueError, IndexError):
        return None
    except Exception:
        log.exception("pgrep failed for: %s", name)
        return None


def _kill_unix(name: str) -> bool:
    import os
    import signal

    pid = _pid_unix(name)
    if pid is None:
        return True  # already gone

    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return True  # gone between pgrep and kill
    except Exception:
        log.exception("kill failed for pid %d (%s)", pid, name)
        return False
