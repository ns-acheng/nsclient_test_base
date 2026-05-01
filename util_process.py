"""
Windows process management helpers.
Uses tasklist / taskkill via subprocess — no psutil dependency.
"""

import csv
import io
import logging
import subprocess
import time
from typing import Optional

log = logging.getLogger(__name__)


def is_process_running(name: str) -> bool:
    """Return True if at least one process with the given image name is running."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        return name.lower() in result.stdout.lower()
    except Exception:
        log.exception("is_process_running failed for: %s", name)
        return False


def get_process_pid(name: str) -> Optional[int]:
    """Return the PID of the first matching process, or None if not found."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        log.exception("get_process_pid failed for: %s", name)
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


def kill_process(name: str) -> bool:
    """Force-kill all processes with the given image name.  Returns True on success."""
    log.info("Killing process: %s", name)
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", name],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode not in (0, 128):  # 128 = no matching process
            log.warning("taskkill %s returned %d: %s", name, result.returncode, result.stdout.strip())
            return False
        return True
    except Exception:
        log.exception("kill_process failed for: %s", name)
        return False


def wait_for_process(
    name: str,
    timeout: int = 60,
    interval: float = 2.0,
    running: bool = True,
) -> bool:
    """
    Poll until the process reaches the desired state within ``timeout`` seconds.

    Args:
        name: Image name (e.g. "stAgentSvc.exe").
        timeout: Maximum seconds to wait.
        interval: Poll interval in seconds.
        running: If True, wait until running; if False, wait until gone.

    Returns:
        True if the desired state was reached within the timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        currently_running = is_process_running(name)
        if currently_running == running:
            return True
        time.sleep(interval)
    return False
