"""
Netskope Client status detection — Windows, macOS, Linux.

Primary source: `nsdiag -f` (all platforms)
  Parses key::value lines from nsdiag output, e.g.:
    Client status:: enable
    Tunnel status:: NSTUNNEL_CONNECTED

  nsdiag path:
    Windows : C:\\Program Files\\Netskope\\STAgent\\nsdiag.exe   (64-bit)
              C:\\Program Files (x86)\\Netskope\\STAgent\\nsdiag.exe  (32-bit fallback)
    macOS   : /Library/Application Support/Netskope/STAgent/nsdiag  [ASSUMED M6]
    Linux   : /opt/netskope/stagent/nsdiag

Fallback: sc / launchctl / systemctl service state
  STOPPED → Disabled  (unambiguous)
  RUNNING → Unknown   (daemon alive but nsdiag unavailable)

Windows bonus: Netskope_MainFrame window title (pywin32, optional)
  Used only to detect Unenrolled when nsdiag is unavailable.

ClientStatus fields:
  internet_security  "Enabled" | "Disabled" | "Unenrolled" |
                     "Disabled (error)" | "Disabled (fail-closed)" |
                     "Enabled (warning)" | "Enabled (error)" | "Unknown"
  tunnel_up          True if Tunnel status is NSTUNNEL_CONNECTED
  source             "nsdiag" | "tray_tooltip" | "service"
  raw                raw "Client status::" value from nsdiag (for debugging)
"""

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# ── Optional pywin32 import (Windows unenrolled detection) ────────────────────

_HAS_PYWIN32 = False
if sys.platform.startswith("win"):
    try:
        import win32gui   # type: ignore
        _HAS_PYWIN32 = True
    except ImportError:
        pass


# ── nsdiag paths ──────────────────────────────────────────────────────────────

if sys.platform.startswith("win"):
    _NSDIAG_PATHS = [
        Path(r"C:\Program Files\Netskope\STAgent\nsdiag.exe"),
        Path(r"C:\Program Files (x86)\Netskope\STAgent\nsdiag.exe"),
    ]
elif sys.platform.startswith("darwin"):
    _NSDIAG_PATHS = [
        Path("/Library/Application Support/Netskope/STAgent/nsdiag"),  # [ASSUMED M6]
    ]
else:
    _NSDIAG_PATHS = [
        Path("/opt/netskope/stagent/nsdiag"),
    ]


# ── Public types ───────────────────────────────────────────────────────────────

STATUS_ENABLED          = "Enabled"
STATUS_DISABLED         = "Disabled"
STATUS_UNENROLLED       = "Unenrolled"
STATUS_ENABLED_WARNING  = "Enabled (warning)"
STATUS_ENABLED_ERROR    = "Enabled (error)"
STATUS_DISABLED_WARNING = "Disabled (warning)"
STATUS_DISABLED_ERROR   = "Disabled (error)"
STATUS_FAIL_CLOSED      = "Disabled (fail-closed)"
STATUS_UNKNOWN          = "Unknown"


@dataclass
class ClientStatus:
    """Normalised Netskope Client status — same structure on all platforms."""
    internet_security: str   # one of the STATUS_* constants above
    tunnel_up: bool          # True if tunnel is NSTUNNEL_CONNECTED
    source: str              # "nsdiag" | "tray_tooltip" | "service"
    raw: str                 # raw value from the winning source (for debugging)


# ── Public API ─────────────────────────────────────────────────────────────────

def get_client_status() -> ClientStatus:
    """
    Return the current Netskope Client status.

    Primary: nsdiag -f (all platforms).
    Fallback: service state (STOPPED=Disabled) or tray title (Unenrolled).
    Never raises.
    """
    try:
        if sys.platform.startswith("win"):
            return _status_win()
        if sys.platform.startswith("darwin"):
            return _status_mac()
        return _status_linux()
    except Exception:
        log.exception("get_client_status: unexpected error")
        return ClientStatus(STATUS_UNKNOWN, tunnel_up=False, source="service", raw="")


def is_client_enabled() -> bool:
    """Return True if internet security is in any Enabled state."""
    return get_client_status().internet_security in (
        STATUS_ENABLED, STATUS_ENABLED_WARNING, STATUS_ENABLED_ERROR,
    )


def is_client_disabled() -> bool:
    """Return True if internet security is in any Disabled state."""
    return get_client_status().internet_security in (
        STATUS_DISABLED, STATUS_DISABLED_WARNING, STATUS_DISABLED_ERROR, STATUS_FAIL_CLOSED,
    )


# ── nsdiag -f parser (all platforms) ──────────────────────────────────────────

def _find_nsdiag() -> "Path | None":
    """Return the first nsdiag executable that exists."""
    for p in _NSDIAG_PATHS:
        if p.exists():
            return p
    return None


def _run_nsdiag_f() -> "ClientStatus | None":
    """
    Run `nsdiag -f` and parse the output into a ClientStatus.

    Key lines (case-insensitive):
      Client status:: enable | disable | unenrolled | error | fail close
      Tunnel status:: NSTUNNEL_CONNECTED | NSTUNNEL_DISCONNECTED | ...

    Returns None if nsdiag is not found or the output is unparseable.
    """
    nsdiag = _find_nsdiag()
    if nsdiag is None:
        log.debug("nsdiag not found")
        return None

    try:
        result = subprocess.run(
            [str(nsdiag), "-f"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        log.debug("nsdiag -f failed", exc_info=True)
        return None

    output = result.stdout + result.stderr
    if not output.strip():
        log.debug("nsdiag -f produced no output")
        return None

    log.debug("nsdiag -f output:\n%s", output)

    client_raw = _parse_nsdiag_field(output, "client status")
    tunnel_raw = _parse_nsdiag_field(output, "tunnel status")

    if client_raw is None:
        log.debug("nsdiag -f: 'Client status' field not found")
        return None

    state = _map_client_status(client_raw)
    tunnel_up = (
        tunnel_raw is not None
        and "connected" in tunnel_raw.lower()
        and state in (STATUS_ENABLED, STATUS_ENABLED_WARNING, STATUS_ENABLED_ERROR)
    )

    return ClientStatus(
        internet_security=state,
        tunnel_up=tunnel_up,
        source="nsdiag",
        raw=client_raw,
    )


def _parse_nsdiag_field(output: str, field: str) -> "str | None":
    """
    Extract value from a `field:: value` line in nsdiag -f output.
    Field matching is case-insensitive; trailing dot stripped.
    """
    field_lower = field.lower()
    for line in output.splitlines():
        if "::" not in line:
            continue
        key, _, value = line.partition("::")
        if key.strip().lower() == field_lower:
            return value.strip().rstrip(".")
    return None


def _map_client_status(raw: str) -> str:
    """Map the raw 'Client status' value to a STATUS_* constant."""
    r = raw.lower().strip()
    if r in ("enable", "enabled"):
        return STATUS_ENABLED
    if r in ("disable", "disabled"):
        return STATUS_DISABLED
    if "unenroll" in r or "enroll" in r:
        return STATUS_UNENROLLED
    if "fail" in r and ("close" in r or "closed" in r):
        return STATUS_FAIL_CLOSED
    if "error" in r:
        return STATUS_DISABLED_ERROR
    if "warn" in r:
        return STATUS_ENABLED_WARNING
    log.debug("nsdiag: unrecognised client status: %r", raw)
    return STATUS_UNKNOWN


# ── Windows ────────────────────────────────────────────────────────────────────

def _status_win() -> ClientStatus:
    status = _run_nsdiag_f()
    if status is not None:
        return status

    # nsdiag unavailable — check for unenrolled state via window title
    if _HAS_PYWIN32:
        win_status = _mainframe_title_win()
        if win_status is not None:
            return win_status

    return _service_state_win()


def _mainframe_title_win() -> "ClientStatus | None":
    """
    Read Netskope_MainFrame window title — only reliable for Unenrolled detection.
    Returns None if stAgentUI is not running or title doesn't indicate unenrolled.
    """
    try:
        hwnd = win32gui.FindWindow("Netskope_MainFrame", None)
        if not hwnd:
            return None
        title = win32gui.GetWindowText(hwnd)
        log.debug("Netskope_MainFrame title: %r", title)
        if "enroll" in title.lower():
            return ClientStatus(STATUS_UNENROLLED, tunnel_up=False, source="tray_tooltip", raw=title)
    except Exception:
        log.debug("_mainframe_title_win failed", exc_info=True)
    return None


def _service_state_win() -> ClientStatus:
    """Last-resort: sc query stAgentSvc. Only STOPPED is unambiguous."""
    from util_service import query_service, SVC_CLIENT_WIN
    info = query_service(SVC_CLIENT_WIN)
    if info.state == "STOPPED":
        return ClientStatus(STATUS_DISABLED, tunnel_up=False, source="service", raw=info.state)
    log.warning("stAgentSvc is %s but nsdiag is unavailable — status unknown.", info.state)
    return ClientStatus(STATUS_UNKNOWN, tunnel_up=False, source="service", raw=info.state)


# ── macOS ──────────────────────────────────────────────────────────────────────

def _status_mac() -> ClientStatus:
    status = _run_nsdiag_f()
    if status is not None:
        return status

    from util_service import query_service, SVC_CLIENT_MAC
    from util_process import is_process_running, PROC_CLIENT_MAC
    svc = query_service(SVC_CLIENT_MAC)
    if svc.state in ("STOPPED", "NOT_FOUND") or not is_process_running(PROC_CLIENT_MAC):
        return ClientStatus(STATUS_DISABLED, tunnel_up=False, source="service", raw=svc.state)
    return ClientStatus(STATUS_UNKNOWN, tunnel_up=False, source="service", raw=svc.state)


# ── Linux ──────────────────────────────────────────────────────────────────────

def _status_linux() -> ClientStatus:
    status = _run_nsdiag_f()
    if status is not None:
        return status

    from util_service import query_service, SVC_CLIENT_LIN
    info = query_service(SVC_CLIENT_LIN)
    if info.state == "STOPPED":
        return ClientStatus(STATUS_DISABLED, tunnel_up=False, source="service", raw=info.state)
    return ClientStatus(STATUS_UNKNOWN, tunnel_up=False, source="service", raw=info.state)
