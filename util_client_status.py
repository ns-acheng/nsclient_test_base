"""
Netskope Client status detection — Windows, macOS, Linux.

Two-layer approach:
  Layer C (service/daemon):  always available, no GUI required
  Layer A (UI/tray/CLI):     richer state; platform-specific

Windows:
  Layer C — sc query stAgentSvc  →  RUNNING / STOPPED
  Layer A — Win32 system tray tooltip via pywin32 (optional dep)
            falls back silently to Layer C if pywin32 not installed

macOS:
  Layer C — launchctl list com.netskope.client.auxsvc  →  RUNNING / STOPPED
            (AppleScript menu bar query omitted — too fragile across macOS versions)

Linux:
  Layer C — systemctl is-active stagentd  →  RUNNING / STOPPED
  Layer A — `nsclient show-status` CLI  →  "Internet Security Enabled/Disabled"
            `nsdiag -s` for tunnel detail

ClientStatus fields:
  internet_security  "Enabled" | "Disabled" | "Disabled (error)" |
                     "Disabled (fail-closed)" | "Enabled (warning)" |
                     "Enabled (error)" | "Unknown"
  tunnel_up          True  if the tunnel is active
  source             "tray_tooltip" | "cli" | "service"  — which layer answered
  raw                raw text from the winning source (for logging/debugging)
"""

import logging
import subprocess
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ── Optional pywin32 import (Windows tray tooltip) ────────────────────────────

_HAS_PYWIN32 = False
if sys.platform.startswith("win"):
    try:
        import win32gui   # type: ignore
        import win32api   # type: ignore
        import win32con   # type: ignore
        _HAS_PYWIN32 = True
    except ImportError:
        log.debug("pywin32 not installed — tray tooltip unavailable, using service layer only")


# ── Public types ───────────────────────────────────────────────────────────────

# Canonical status strings — same values used on all platforms
STATUS_ENABLED          = "Enabled"
STATUS_DISABLED         = "Disabled"
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
    tunnel_up: bool          # True if the tunnel is established
    source: str              # "tray_tooltip" | "cli" | "service"
    raw: str                 # raw text from the winning source


# ── Public API ─────────────────────────────────────────────────────────────────

def get_client_status() -> ClientStatus:
    """
    Return the current Netskope Client status using the best available method
    for the running platform.

    Never raises — returns STATUS_UNKNOWN on any unexpected failure.
    """
    try:
        if sys.platform.startswith("win"):
            return _status_win()
        if sys.platform.startswith("darwin"):
            return _status_mac()
        return _status_linux()
    except Exception:
        log.exception("get_client_status: unexpected error")
        return ClientStatus(
            internet_security=STATUS_UNKNOWN,
            tunnel_up=False,
            source="service",
            raw="",
        )


def is_client_enabled() -> bool:
    """Return True if internet security is in an Enabled state (with or without warnings)."""
    status = get_client_status()
    return status.internet_security in (STATUS_ENABLED, STATUS_ENABLED_WARNING, STATUS_ENABLED_ERROR)


def is_client_disabled() -> bool:
    """Return True if all services are disabled."""
    status = get_client_status()
    return status.internet_security in (
        STATUS_DISABLED,
        STATUS_DISABLED_WARNING,
        STATUS_DISABLED_ERROR,
        STATUS_FAIL_CLOSED,
    )


# ── Windows ────────────────────────────────────────────────────────────────────

def _status_win() -> ClientStatus:
    """
    Windows: try tray tooltip first (Layer A), fall back to service state (Layer C).

    The tray tooltip is the most faithful reflection of what the user sees.
    Tooltip text examples (from Netskope docs):
      "Netskope Internet Security: Enabled"
      "Netskope Internet Security disabled for X minutes"
      "Netskope Internet Security: Disabled due to error"
      "Netskope Internet Security: Fail Closed"
    """
    if _HAS_PYWIN32:
        status = _tray_tooltip_win()
        if status is not None:
            return status
        log.debug("_status_win: tray tooltip not found, falling back to service state")

    return _service_state_win()


def _tray_tooltip_win() -> "ClientStatus | None":
    """
    Walk the Shell_TrayWnd → ToolbarWindow32 hierarchy looking for a button
    whose tooltip contains "Netskope".  Returns None if not found.

    This requires the stAgentUI.exe tray icon to be visible.
    """
    try:
        tooltip = _find_tray_tooltip("Netskope")
        if not tooltip:
            return None
        log.debug("Tray tooltip found: %r", tooltip)
        return _parse_win_tooltip(tooltip)
    except Exception:
        log.debug("_tray_tooltip_win: failed", exc_info=True)
        return None


def _find_tray_tooltip(keyword: str) -> str:
    """
    Enumerate all buttons in the system tray toolbars and return the tooltip
    of the first button whose text contains ``keyword`` (case-insensitive).

    Searches both the visible tray (Shell_TrayWnd) and the overflow tray
    (NotifyIconOverflowWindow).
    """
    kw = keyword.lower()
    results: list[str] = []

    def _enum_toolbar(hwnd: int) -> None:
        count = win32api.SendMessage(hwnd, win32con.TB_BUTTONCOUNT, 0, 0)
        for i in range(count):
            try:
                # TB_GETBUTTONTEXTW returns the button tooltip text
                buf_len = 256
                buf = win32gui.PyMakeBuffer(buf_len * 2)
                length = win32api.SendMessage(hwnd, win32con.TB_GETBUTTONTEXTW, i, buf)
                if length > 0:
                    text = buf[:length * 2].tobytes().decode("utf-16-le", errors="ignore")
                    if kw in text.lower():
                        results.append(text)
            except Exception:
                pass

    def _enum_children(hwnd: int, _lparam: int) -> bool:
        cls = win32gui.GetClassName(hwnd)
        if cls == "ToolbarWindow32":
            _enum_toolbar(hwnd)
        return True  # continue enumeration

    for root_cls in ("Shell_TrayWnd", "NotifyIconOverflowWindow"):
        root = win32gui.FindWindow(root_cls, None)
        if root:
            win32gui.EnumChildWindows(root, _enum_children, None)

    return results[0] if results else ""


def _parse_win_tooltip(tooltip: str) -> ClientStatus:
    """Map a tray tooltip string to a ClientStatus."""
    t = tooltip.lower()

    if "fail" in t and "close" in t:
        state = STATUS_FAIL_CLOSED
    elif "error" in t and "enabl" in t:
        state = STATUS_ENABLED_ERROR
    elif "warning" in t and "enabl" in t:
        state = STATUS_ENABLED_WARNING
    elif "error" in t:
        state = STATUS_DISABLED_ERROR
    elif "warning" in t:
        state = STATUS_DISABLED_WARNING
    elif "disab" in t:
        state = STATUS_DISABLED
    elif "enabl" in t:
        state = STATUS_ENABLED
    else:
        state = STATUS_UNKNOWN

    tunnel_up = state in (STATUS_ENABLED, STATUS_ENABLED_WARNING, STATUS_ENABLED_ERROR)
    return ClientStatus(
        internet_security=state,
        tunnel_up=tunnel_up,
        source="tray_tooltip",
        raw=tooltip,
    )


def _service_state_win() -> ClientStatus:
    """Layer C fallback: infer status from sc query stAgentSvc."""
    from util_service import query_service, SVC_CLIENT_WIN
    info = query_service(SVC_CLIENT_WIN)
    if info.state == "RUNNING":
        return ClientStatus(STATUS_ENABLED, tunnel_up=True, source="service", raw=info.state)
    if info.state == "STOPPED":
        return ClientStatus(STATUS_DISABLED, tunnel_up=False, source="service", raw=info.state)
    return ClientStatus(STATUS_UNKNOWN, tunnel_up=False, source="service", raw=info.state)


# ── macOS ──────────────────────────────────────────────────────────────────────

def _status_mac() -> ClientStatus:
    """
    macOS: Layer C only — launchctl + nsAuxiliarySvc process check.

    The menu bar icon state is not queried (AppleScript is fragile across
    macOS versions and requires specific accessibility permissions).
    """
    from util_service import query_service, SVC_CLIENT_MAC
    from util_process import is_process_running, PROC_CLIENT_MAC

    svc = query_service(SVC_CLIENT_MAC)
    proc_running = is_process_running(PROC_CLIENT_MAC)

    if svc.state == "RUNNING" and proc_running:
        return ClientStatus(STATUS_ENABLED, tunnel_up=True, source="service", raw=svc.state)
    if svc.state in ("STOPPED", "NOT_FOUND") or not proc_running:
        return ClientStatus(STATUS_DISABLED, tunnel_up=False, source="service", raw=svc.state)
    return ClientStatus(STATUS_UNKNOWN, tunnel_up=False, source="service", raw=svc.state)


# ── Linux ──────────────────────────────────────────────────────────────────────

def _status_linux() -> ClientStatus:
    """
    Linux: Layer A first — `nsclient show-status` CLI, fall back to systemctl (Layer C).

    `nsclient show-status` output examples:
      "Internet Security Enabled"
      "Internet Security Disabled"
    """
    cli_status = _nsclient_cli_linux()
    if cli_status is not None:
        return cli_status

    log.debug("_status_linux: nsclient CLI unavailable, falling back to systemctl")
    return _service_state_linux()


def _nsclient_cli_linux() -> "ClientStatus | None":
    """
    Run `nsclient show-status` and parse the output.
    Returns None if the command is not found or fails.
    """
    try:
        result = subprocess.run(
            ["nsclient", "show-status"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        log.debug("nsclient binary not found in PATH")
        return None
    except Exception:
        log.debug("nsclient show-status failed", exc_info=True)
        return None

    output = result.stdout.strip()
    if not output:
        return None

    low = output.lower()
    if "enabled" in low:
        state = STATUS_ENABLED
        tunnel_up = True
    elif "disabled" in low:
        state = STATUS_DISABLED
        tunnel_up = False
    else:
        log.debug("nsclient show-status: unrecognised output: %r", output)
        return None

    # Optionally refine tunnel_up via nsdiag -s
    tunnel_up = _nsdiag_tunnel_linux() if state == STATUS_ENABLED else False

    return ClientStatus(
        internet_security=state,
        tunnel_up=tunnel_up,
        source="cli",
        raw=output,
    )


def _nsdiag_tunnel_linux() -> bool:
    """
    Run `nsdiag -s` and check if tunnel is up.
    Returns True if output indicates tunnel is active, False on any failure.
    """
    try:
        result = subprocess.run(
            ["nsdiag", "-s"],
            capture_output=True, text=True, timeout=10,
        )
        low = result.stdout.lower()
        # nsdiag -s typically outputs "Tunnel: Up" or "Tunnel: Down"
        if "tunnel" in low:
            return "up" in low and "down" not in low
    except Exception:
        pass
    return False


def _service_state_linux() -> ClientStatus:
    """Layer C fallback: systemctl is-active stagentd."""
    from util_service import query_service, SVC_CLIENT_LIN
    info = query_service(SVC_CLIENT_LIN)
    if info.state == "RUNNING":
        return ClientStatus(STATUS_ENABLED, tunnel_up=True, source="service", raw=info.state)
    if info.state == "STOPPED":
        return ClientStatus(STATUS_DISABLED, tunnel_up=False, source="service", raw=info.state)
    return ClientStatus(STATUS_UNKNOWN, tunnel_up=False, source="service", raw=info.state)
