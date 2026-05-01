"""
Windows registry helpers for NSClient state checks.
winreg is a stdlib module — only available on Windows.
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# Paths searched for Add/Remove Programs entry
UNINSTALL_REG_PATHS = [
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
]
UNINSTALL_DISPLAY_NAME = "Netskope Client"

# Upgrade-in-progress flag
UPGRADE_REG_KEY = r"SOFTWARE\Netskope"
UPGRADE_IN_PROGRESS_VALUE = "UpgradeInProgress"


class UninstallEntryResult:
    """Result of checking the Windows Add/Remove Programs registry entry."""

    def __init__(
        self,
        found: bool,
        display_name: str = "",
        display_version: str = "",
        install_location: str = "",
        product_code: str = "",
    ) -> None:
        self.found = found
        self.display_name = display_name
        self.display_version = display_version
        self.install_location = install_location
        self.product_code = product_code

    def __repr__(self) -> str:
        if not self.found:
            return "UninstallEntryResult(found=False)"
        return (
            f"UninstallEntryResult(found=True, version={self.display_version!r}, "
            f"product_code={self.product_code!r})"
        )


def check_uninstall_entry() -> UninstallEntryResult:
    """
    Search HKLM uninstall registry paths for the Netskope Client entry.
    Returns an UninstallEntryResult with details if found.
    """
    try:
        import winreg
    except ImportError:
        log.error("winreg not available — not running on Windows")
        return UninstallEntryResult(found=False)

    for reg_path in UNINSTALL_REG_PATHS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as parent:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(parent, index)
                        index += 1
                    except OSError:
                        break

                    try:
                        with winreg.OpenKey(parent, subkey_name) as subkey:
                            display_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                            if UNINSTALL_DISPLAY_NAME.lower() not in display_name.lower():
                                continue

                            def _read(value_name: str) -> str:
                                try:
                                    val, _ = winreg.QueryValueEx(subkey, value_name)
                                    return str(val)
                                except OSError:
                                    return ""

                            return UninstallEntryResult(
                                found=True,
                                display_name=display_name,
                                display_version=_read("DisplayVersion"),
                                install_location=_read("InstallLocation"),
                                product_code=subkey_name,
                            )
                    except OSError:
                        continue
        except OSError:
            continue

    return UninstallEntryResult(found=False)


def get_reg_dword(key_path: str, value_name: str) -> Optional[int]:
    """
    Read a DWORD value from HKLM.
    Returns the integer value, or None if the key/value does not exist.
    """
    try:
        import winreg
    except ImportError:
        log.error("winreg not available")
        return None

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            raw, reg_type = winreg.QueryValueEx(key, value_name)
            return int(raw)
    except OSError:
        return None
    except Exception:
        log.exception("get_reg_dword failed: %s\\%s", key_path, value_name)
        return None


def set_reg_dword(key_path: str, value_name: str, value: int) -> bool:
    """
    Write a DWORD value to HKLM.  Creates the key if it does not exist.
    Returns True on success.
    """
    try:
        import winreg
    except ImportError:
        log.error("winreg not available")
        return False

    try:
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_DWORD, int(value))
        return True
    except Exception:
        log.exception("set_reg_dword failed: %s\\%s = %d", key_path, value_name, value)
        return False


def check_upgrade_in_progress() -> bool:
    """Return True if the UpgradeInProgress DWORD is set (non-zero)."""
    val = get_reg_dword(UPGRADE_REG_KEY, UPGRADE_IN_PROGRESS_VALUE)
    return val is not None and val != 0


def set_upgrade_in_progress(value: int = 1) -> bool:
    """Set the UpgradeInProgress DWORD.  Pass 0 to clear."""
    return set_reg_dword(UPGRADE_REG_KEY, UPGRADE_IN_PROGRESS_VALUE, value)
