"""
Windows service control helpers for NSClient services.
All operations use 'sc.exe' via subprocess — no pywin32 dependency.
"""

import logging
import subprocess
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

# NSClient service names
SVC_CLIENT = "stAgentSvc"
SVC_WATCHDOG = "stwatchdog"
SVC_DRIVER = "stadrv"


@dataclass
class ServiceInfo:
    """Parsed result of an ``sc query`` call."""
    name: str
    exists: bool
    state: str  # e.g. "RUNNING", "STOPPED", "STOP_PENDING", "NOT_FOUND"


def query_service(name: str) -> ServiceInfo:
    """Query the current state of a Windows service."""
    try:
        result = subprocess.run(
            ["sc", "query", name],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        log.exception("sc query failed for service: %s", name)
        return ServiceInfo(name=name, exists=False, state="ERROR")

    stdout = result.stdout.upper()
    if "FAILED 1060" in stdout or result.returncode == 1060:
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


def is_running(name: str) -> bool:
    """Return True if the service is in RUNNING state."""
    return query_service(name).state == "RUNNING"


def start_service(name: str) -> bool:
    """Start a Windows service.  Returns True on success."""
    log.info("Starting service: %s", name)
    try:
        result = subprocess.run(
            ["sc", "start", name],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode not in (0, 1056):  # 1056 = already running
            log.error("sc start %s failed (rc=%d): %s", name, result.returncode, result.stdout.strip())
            return False
        return True
    except Exception:
        log.exception("start_service failed for: %s", name)
        return False


def stop_service(name: str, timeout: int = 30) -> bool:
    """
    Stop a Windows service and wait up to ``timeout`` seconds for it to reach STOPPED.
    Returns True if stopped within timeout.
    """
    log.info("Stopping service: %s", name)
    try:
        subprocess.run(["sc", "stop", name], capture_output=True, text=True, timeout=15)
    except Exception:
        log.exception("sc stop failed for: %s", name)
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = query_service(name)
        if info.state in ("STOPPED", "NOT_FOUND"):
            log.info("Service stopped: %s", name)
            return True
        time.sleep(1)

    log.warning("Service %s did not stop within %ds (state=%s)", name, timeout, query_service(name).state)
    return False


def restart_service(name: str, stop_timeout: int = 30) -> bool:
    """Stop then start a service.  Returns True if both succeed."""
    if not stop_service(name, timeout=stop_timeout):
        return False
    return start_service(name)


def wait_for_running(name: str, timeout: int = 60, interval: float = 2.0) -> bool:
    """Poll until the service is RUNNING or timeout expires.  Returns True if running."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_running(name):
            log.info("Service running: %s", name)
            return True
        time.sleep(interval)
    log.warning("Service %s not running after %ds", name, timeout)
    return False
