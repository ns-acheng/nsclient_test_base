"""
Power management helpers — Windows, macOS, Linux.

Windows : pwrtest.exe (bundled at tool/pwrtest.exe) + ctypes fallback
macOS   : pmset / caffeinate
Linux   : stub — sleep states not supported; reboot via sudo reboot

Public API:
    enter_s0_and_wake(duration_seconds)   -> bool
    enter_s1_and_wake(duration_seconds)   -> bool
    enter_s4_and_wake(duration_seconds)   -> bool
    is_sleep_state_available(state_name)  -> bool
    enable_wake_timers()                  -> bool
    reboot()                              -> None

Sleep state names for is_sleep_state_available():
    "Standby (S0 Low Power Idle)"   — Modern Standby / AOAC
    "Standby (S1)"                  — Legacy Standby
    "Hibernate"                     — S4 Hibernate
"""

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# pwrtest.exe bundled alongside this file in tool/
_PWRTEST = Path(__file__).parent / "tool" / "pwrtest.exe"


# ── Public API ─────────────────────────────────────────────────────────────────

def enter_s0_and_wake(duration_seconds: int) -> bool:
    """
    Enter S0 / Display Sleep and wake after ``duration_seconds``.

    Windows : pwrtest /cs with ctypes fallback (monitor-off via SendMessageW)
    macOS   : pmset displaysleepnow + caffeinate to wake
    Linux   : not supported — returns False
    """
    if sys.platform.startswith("win"):
        return _win_enter_s0(duration_seconds)
    if sys.platform.startswith("darwin"):
        return _mac_enter_s0(duration_seconds)
    log.warning("enter_s0_and_wake: not supported on Linux")
    return False


def enter_s1_and_wake(duration_seconds: int) -> bool:
    """
    Enter S1 / System Standby and wake after ``duration_seconds``.

    Windows : pwrtest /sleep /s:1 with ctypes SetSuspendState fallback
    macOS   : pmset sleepnow with scheduled wake
    Linux   : not supported — returns False
    """
    if sys.platform.startswith("win"):
        return _win_enter_s1(duration_seconds)
    if sys.platform.startswith("darwin"):
        return _mac_enter_s1(duration_seconds)
    log.warning("enter_s1_and_wake: not supported on Linux")
    return False


def enter_s4_and_wake(duration_seconds: int) -> bool:
    """
    Enter S4 / Hibernate and wake after ``duration_seconds``.

    Windows : skipped on AOAC platforms; pwrtest /sleep /s:s4 with ctypes fallback
    macOS   : mapped to system sleep (macOS has no separate S4)
    Linux   : not supported — returns False
    """
    if sys.platform.startswith("win"):
        return _win_enter_s4(duration_seconds)
    if sys.platform.startswith("darwin"):
        log.info("enter_s4_and_wake: mapping to system sleep on macOS")
        return _mac_enter_s1(duration_seconds)
    log.warning("enter_s4_and_wake: not supported on Linux")
    return False


def is_sleep_state_available(state_name: str) -> bool:
    """
    Check whether a named sleep state is available on this machine.

    Args:
        state_name: One of "Hibernate", "Standby (S1)",
                    "Standby (S0 Low Power Idle)".

    Windows : parses ``powercfg /a`` output (supports EN and ZH-TW locales)
    macOS   : checks ``pmset -g cap`` for "Sleep"
    Linux   : always False
    """
    if sys.platform.startswith("win"):
        return _win_sleep_state_available(state_name)
    if sys.platform.startswith("darwin"):
        return _mac_sleep_state_available(state_name)
    return False


def enable_wake_timers() -> bool:
    """
    Ensure wake timers are enabled in the current power scheme.

    Windows : sets both AC and DC wake-timer powercfg values to 1
    macOS   : no-op, returns True (wake timers not a macOS concept)
    Linux   : returns False
    """
    if sys.platform.startswith("win"):
        return _win_enable_wake_timers()
    if sys.platform.startswith("darwin"):
        return True
    return False


def reboot() -> None:
    """Reboot the system immediately."""
    log.info("Triggering system reboot")
    if sys.platform.startswith("win"):
        subprocess.run(["shutdown", "/r", "/t", "0"], check=False)
    elif sys.platform.startswith("darwin"):
        subprocess.run(["sudo", "shutdown", "-r", "now"], check=False)
    else:
        subprocess.run(["sudo", "reboot"], check=False)


# ── Windows implementation ─────────────────────────────────────────────────────

def _win_powercfg_output() -> str:
    """Run ``powercfg /a`` with UTF-8 codepage and return stdout."""
    try:
        res = subprocess.run(
            ["cmd", "/c", "chcp 65001 && powercfg /a"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if res.returncode != 0:
            log.warning("powercfg /a returned rc=%d", res.returncode)
        return res.stdout
    except Exception:
        log.exception("Failed to run powercfg /a")
        return ""


def _win_is_aoac() -> bool:
    """Return True if this is an AOAC (Modern Standby / S0 Low Power Idle) platform."""
    output = _win_powercfg_output()
    return any(m in output for m in ("Standby (S0 Low Power Idle)", "待命 (S0 低電源閒置)"))


def _win_run_pwrtest(args: list[str]) -> bool:
    """Run the bundled pwrtest.exe with the given arguments."""
    pwrtest = _PWRTEST
    if not pwrtest.is_file():
        log.debug("pwrtest.exe not found at %s", pwrtest)
        return False
    try:
        cmd = [str(pwrtest)] + args
        log.info("Running pwrtest: %s", " ".join(cmd))
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as exc:
        log.error("pwrtest failed rc=%d", exc.returncode)
        return False
    except Exception:
        log.exception("pwrtest execution error")
        return False


def _win_set_wake_timer(duration_seconds: int) -> Optional[int]:
    """
    Create a Windows waitable timer that fires after ``duration_seconds``.

    Returns the timer handle, or None on failure.
    The caller must call CloseHandle on the returned handle.
    """
    import ctypes
    from ctypes import wintypes

    class LARGE_INTEGER(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateWaitableTimerW(None, True, None)
    if not handle:
        log.error("CreateWaitableTimerW failed: %d", kernel32.GetLastError())
        return None

    dt = int(duration_seconds * 10_000_000) * -1   # 100-ns intervals, negative = relative
    li = LARGE_INTEGER(dt & 0xFFFFFFFF, dt >> 32)

    if not kernel32.SetWaitableTimer(handle, ctypes.byref(li), 0, None, None, True):
        log.error("SetWaitableTimer failed: %d", kernel32.GetLastError())
        kernel32.CloseHandle(handle)
        return None

    return handle


def _win_enter_s0(duration_seconds: int) -> bool:
    if _win_run_pwrtest(["/cs", "/c:1", f"/p:{duration_seconds}", "/d:0"]):
        log.info("S0 cycle via pwrtest complete")
        return True

    log.info("S0 fallback: monitor-off via ctypes for %ds", duration_seconds)
    import ctypes
    HWND_BROADCAST = 0xFFFF
    WM_SYSCOMMAND  = 0x0112
    SC_MONITORPOWER = 0xF170
    KEYEVENTF_KEYUP = 0x0002

    kernel32 = ctypes.windll.kernel32
    user32   = ctypes.windll.user32
    handle   = _win_set_wake_timer(duration_seconds)
    if not handle:
        return False
    try:
        user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2)   # OFF
        kernel32.WaitForSingleObject(handle, -1)
        user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, -1)  # ON
        user32.keybd_event(0, 0, 0, 0)
        user32.keybd_event(0, 0, KEYEVENTF_KEYUP, 0)
        log.info("S0 complete (monitor back on)")
        return True
    except Exception:
        log.exception("S0 fallback failed")
        return False
    finally:
        kernel32.CloseHandle(handle)


def _win_enter_s1(duration_seconds: int) -> bool:
    if _win_run_pwrtest(["/sleep", "/s:1", "/c:1", f"/p:{duration_seconds}", "/d:0"]):
        log.info("S1 cycle via pwrtest complete")
        return True

    log.info("S1 fallback: SetSuspendState for %ds", duration_seconds)
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle   = _win_set_wake_timer(duration_seconds)
    if not handle:
        return False
    try:
        ctypes.windll.powrprof.SetSuspendState(0, 0, 0)  # Standby
        kernel32.WaitForSingleObject(handle, -1)
        log.info("S1 complete (woke from standby)")
        return True
    except Exception:
        log.exception("S1 fallback failed")
        return False
    finally:
        kernel32.CloseHandle(handle)


def _win_enter_s4(duration_seconds: int) -> bool:
    if _win_is_aoac():
        log.info("AOAC platform: skipping pwrtest S4, using legacy hibernate")
        return _win_enter_s4_legacy(duration_seconds)

    if _win_run_pwrtest(["/sleep", "/s:s4", "/dt:60", f"/p:{duration_seconds}"]):
        log.info("S4 cycle via pwrtest complete")
        return True

    log.info("S4 fallback: SetSuspendState(hibernate) for %ds", duration_seconds)
    return _win_enter_s4_legacy(duration_seconds)


def _win_enter_s4_legacy(duration_seconds: int) -> bool:
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle   = _win_set_wake_timer(duration_seconds)
    if not handle:
        return False
    try:
        ctypes.windll.powrprof.SetSuspendState(1, 0, 0)  # Hibernate
        kernel32.WaitForSingleObject(handle, -1)
        log.info("S4 complete (woke from hibernate)")
        return True
    except Exception:
        log.exception("S4 legacy failed")
        return False
    finally:
        kernel32.CloseHandle(handle)


def _win_sleep_state_available(state_name: str) -> bool:
    try:
        output = _win_powercfg_output()
        if not output:
            return False

        # Trim everything after the "not available" marker so we only search the available section
        for marker in ("The following sleep states are not available", "此系統缺乏以下幾種睡眠狀態"):
            if marker in output:
                output = output.split(marker)[0]
                break

        # Build search candidates including ZH-TW equivalents
        candidates = [state_name]
        aliases = {
            "Hibernate":                   "休眠",
            "Standby (S1)":               "待命 (S1)",
            "Standby (S0 Low Power Idle)": "待命 (S0 低電源閒置)",
        }
        if state_name in aliases:
            candidates.append(aliases[state_name])

        return any(c in output for c in candidates)
    except Exception:
        log.exception("is_sleep_state_available failed for %s", state_name)
        return False


def _win_enable_wake_timers() -> bool:
    subgroup = "238C9FA8-0AAD-41ED-83F4-97BE242C8F20"
    setting  = "BD3B718A-0680-4D9D-8AB2-E1D2B4EF806D"
    commands = [
        ["powercfg", "/setacvalueindex", "SCHEME_CURRENT", subgroup, setting, "1"],
        ["powercfg", "/setdcvalueindex", "SCHEME_CURRENT", subgroup, setting, "1"],
        ["powercfg", "/setactive", "SCHEME_CURRENT"],
    ]
    try:
        log.info("Enabling wake timers in current power scheme")
        for cmd in commands:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        log.warning("Failed to enable wake timers")
        return False


# ── macOS implementation ────────────────────────────────────────────────────────

def _mac_schedule_wake(duration_seconds: int) -> bool:
    """Schedule a pmset wake event ``duration_seconds`` from now."""
    import datetime
    wake_time = datetime.datetime.now() + datetime.timedelta(seconds=duration_seconds)
    time_str  = wake_time.strftime("%m/%d/%Y %H:%M:%S")
    try:
        subprocess.run(["pmset", "schedule", "wake", time_str], check=True, capture_output=True)
        log.info("Scheduled wake at %s", time_str)
        return True
    except subprocess.CalledProcessError:
        log.exception("pmset schedule wake failed")
        return False


def _mac_enter_s0(duration_seconds: int) -> bool:
    try:
        subprocess.run(["pmset", "displaysleepnow"], check=True)
        time.sleep(duration_seconds)
        subprocess.run(["caffeinate", "-u", "-t", "1"], check=True)
        log.info("Display sleep complete")
        return True
    except Exception:
        log.exception("macOS S0 (display sleep) failed")
        return False


def _mac_enter_s1(duration_seconds: int) -> bool:
    if not _mac_schedule_wake(duration_seconds):
        log.warning("Could not schedule wake — sleep may be indefinite")
        return False
    try:
        subprocess.run(["pmset", "sleepnow"], check=True)
        time.sleep(duration_seconds + 5)   # buffer for wake-up
        log.info("System sleep complete")
        return True
    except Exception:
        log.exception("macOS S1 (system sleep) failed")
        return False


def _mac_sleep_state_available(state_name: str) -> bool:
    try:
        res = subprocess.run(["pmset", "-g", "cap"], capture_output=True, text=True, timeout=10)
        return "Sleep" in res.stdout
    except Exception:
        return False
