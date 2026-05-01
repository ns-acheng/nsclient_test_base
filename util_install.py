"""
NSClient MSI install / uninstall helpers.
All operations use msiexec / wmic via subprocess.  Admin privilege required at runtime.
"""

import ctypes
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Retry settings for uninstall
_UNINSTALL_RETRY_WAIT = 10
_SUBPROCESS_TIMEOUT = 300


class InstallError(RuntimeError):
    """Raised when msiexec /i fails."""


class UninstallError(RuntimeError):
    """Raised when msiexec /x fails."""


class UninstallCriticalError(UninstallError):
    """Raised when uninstall fails with exit code 1603 (critical failure)."""


def is_admin() -> bool:
    """Return True if the current process has administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def install_msi(
    msi_path: str | Path,
    extra_args: Optional[list[str]] = None,
    log_dir: Optional[Path] = None,
) -> None:
    """
    Install an MSI silently via ``msiexec /I <path> /qn``.

    Args:
        msi_path: Path to the .msi file.
        extra_args: Additional msiexec parameters (e.g. ["token=xxx", "host=yyy"]).
        log_dir: If provided, writes msiexec verbose log to this directory.

    Raises:
        InstallError: On non-zero return code.
    """
    if not is_admin():
        raise InstallError("msiexec /qn requires administrator privileges")

    cmd = ["msiexec", "/I", str(msi_path), "/qn"]
    if extra_args:
        cmd.extend(extra_args)
    if log_dir is not None:
        msi_log = log_dir / "msiexec_install.log"
        cmd.extend(["/l*v", str(msi_log)])

    log.info("Installing MSI: %s", msi_path)
    log.debug("msiexec command: %s", cmd)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, timeout=_SUBPROCESS_TIMEOUT,
            encoding="utf-8", errors="replace",
        )
    except Exception as exc:
        raise InstallError(f"msiexec subprocess error: {exc}") from exc

    if result.returncode != 0:
        raise InstallError(
            f"msiexec /I failed (rc={result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
        )

    log.info("MSI installed successfully: %s", msi_path)


def uninstall_msi(
    product_code: str,
    log_dir: Optional[Path] = None,
    retries: int = 2,
) -> None:
    """
    Uninstall by product code via ``msiexec /x <code> /qn``.

    Retries once after killing any stale msiexec process.

    Args:
        product_code: Windows product code GUID (e.g. "{XXXXXXXX-...}").
        log_dir: If provided, writes verbose log to this directory.
        retries: Number of attempts before giving up.

    Raises:
        UninstallCriticalError: On exit code 1603.
        UninstallError: On other non-zero exit codes after all retries.
    """
    if not is_admin():
        raise UninstallError("msiexec /x requires administrator privileges")

    last_rc = 0
    for attempt in range(1, retries + 1):
        cmd = ["msiexec", "/x", product_code, "/qn"]
        if log_dir is not None:
            msi_log = log_dir / f"msiexec_uninstall_{attempt}.log"
            cmd.extend(["/l*v", str(msi_log)])

        log.info("Uninstalling MSI (attempt %d/%d): %s", attempt, retries, product_code)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True, timeout=_SUBPROCESS_TIMEOUT,
                encoding="utf-8", errors="replace",
            )
        except Exception as exc:
            raise UninstallError(f"msiexec subprocess error: {exc}") from exc

        last_rc = result.returncode
        if last_rc == 0:
            log.info("MSI uninstalled successfully: %s", product_code)
            return

        if last_rc == 1603:
            raise UninstallCriticalError(
                f"msiexec /x critical failure (1603) for {product_code}"
            )

        log.warning("msiexec /x returned %d on attempt %d", last_rc, attempt)
        if attempt < retries:
            _kill_msiexec()
            time.sleep(_UNINSTALL_RETRY_WAIT)

    raise UninstallError(f"msiexec /x failed after {retries} attempts (last rc={last_rc})")


def uninstall_by_wmic() -> bool:
    """
    Uninstall the Netskope Client via WMIC.
    Useful when the product code is unknown.

    Returns:
        True if the command succeeded (rc=0).
    """
    log.info("Uninstalling via WMIC")
    cmd = 'wmic product where name="Netskope client" call uninstall /nointeractive'
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode != 0:
            log.error("WMIC uninstall failed (rc=%d): %s", result.returncode, result.stdout.strip())
            return False
        log.info("WMIC uninstall succeeded")
        return True
    except Exception:
        log.exception("uninstall_by_wmic error")
        return False


def _kill_msiexec() -> None:
    """Kill any stale msiexec.exe process before a retry."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "msiexec.exe"],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass
