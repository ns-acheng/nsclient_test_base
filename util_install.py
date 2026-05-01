"""
NSClient install / uninstall helpers — Windows, macOS, Linux.

Windows : msiexec / wmic
macOS   : sudo installer -pkg  [M1/M2 in knowledge_gap.md — pkg filename and uninstall TBD]
Linux   : STAgent.run          [L1/L2/L3 in knowledge_gap.md — run flags and uninstall TBD]
"""

import ctypes
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_SUBPROCESS_TIMEOUT = 300
_UNINSTALL_RETRY_WAIT = 10


class InstallError(RuntimeError):
    """Raised when installation fails."""


class UninstallError(RuntimeError):
    """Raised when uninstall fails."""


class UninstallCriticalError(UninstallError):
    """Raised when Windows uninstall fails with exit code 1603."""


# ── Privilege check ────────────────────────────────────────────────────────────

def is_admin() -> bool:
    """Return True if the current process has administrator / root privileges."""
    if sys.platform.startswith("win"):
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    else:
        # macOS / Linux — check for root (uid 0)
        # [ASSUMED: verify A1 in knowledge_gap.md — passwordless sudo also acceptable]
        import os
        return os.getuid() == 0


# ── Install ────────────────────────────────────────────────────────────────────

def install(
    installer_path: str | Path,
    extra_args: Optional[list[str]] = None,
    log_dir: Optional[Path] = None,
) -> None:
    """
    Install NSClient silently.  Dispatcher selects the platform-specific method.

    Args:
        installer_path: Path to .msi (Windows), .pkg (macOS), or .run (Linux).
        extra_args: Platform-specific extra parameters:
                    Windows — msiexec property=value pairs (e.g. ["token=xxx", "host=yyy"])
                    macOS/Linux — additional CLI flags (if any)
        log_dir: Directory to write install logs into (Windows only currently).

    Raises:
        InstallError: On failure.
    """
    if sys.platform.startswith("win"):
        _install_msi(installer_path, extra_args, log_dir)
    elif sys.platform.startswith("darwin"):
        _install_pkg_mac(installer_path, extra_args)
    else:
        _install_run_linux(installer_path, extra_args)


# ── Uninstall ──────────────────────────────────────────────────────────────────

def uninstall(
    product_code: Optional[str] = None,
    log_dir: Optional[Path] = None,
) -> None:
    """
    Uninstall NSClient.  Dispatcher selects the platform-specific method.

    Args:
        product_code: Windows product GUID (required on Windows).
                      Ignored on macOS/Linux.
        log_dir: Directory to write uninstall logs into (Windows only).

    Raises:
        UninstallError / UninstallCriticalError: On failure.
    """
    if sys.platform.startswith("win"):
        if not product_code:
            raise UninstallError("product_code is required for Windows uninstall")
        _uninstall_msi(product_code, log_dir)
    elif sys.platform.startswith("darwin"):
        _uninstall_mac()
    else:
        _uninstall_linux()


# ── Windows ────────────────────────────────────────────────────────────────────

def _install_msi(
    msi_path: str | Path,
    extra_args: Optional[list[str]],
    log_dir: Optional[Path],
) -> None:
    if not is_admin():
        raise InstallError("msiexec /qn requires administrator privileges")

    cmd = ["msiexec", "/I", str(msi_path), "/qn"]
    if extra_args:
        cmd.extend(extra_args)
    if log_dir is not None:
        cmd.extend(["/l*v", str(log_dir / "msiexec_install.log")])

    log.info("Installing MSI: %s", msi_path)
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=_SUBPROCESS_TIMEOUT,
            encoding="utf-8", errors="replace",
        )
    except Exception as exc:
        raise InstallError(f"msiexec subprocess error: {exc}") from exc

    if result.returncode != 0:
        raise InstallError(
            f"msiexec /I failed (rc={result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    log.info("MSI installed successfully")


def _uninstall_msi(product_code: str, log_dir: Optional[Path], retries: int = 2) -> None:
    if not is_admin():
        raise UninstallError("msiexec /x requires administrator privileges")

    last_rc = 0
    for attempt in range(1, retries + 1):
        cmd = ["msiexec", "/x", product_code, "/qn"]
        if log_dir is not None:
            cmd.extend(["/l*v", str(log_dir / f"msiexec_uninstall_{attempt}.log")])

        log.info("Uninstalling MSI (attempt %d/%d): %s", attempt, retries, product_code)
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=_SUBPROCESS_TIMEOUT,
                encoding="utf-8", errors="replace",
            )
        except Exception as exc:
            raise UninstallError(f"msiexec subprocess error: {exc}") from exc

        last_rc = result.returncode
        if last_rc == 0:
            log.info("MSI uninstalled successfully")
            return
        if last_rc == 1603:
            raise UninstallCriticalError(f"msiexec /x critical failure (1603) for {product_code}")

        log.warning("msiexec /x returned %d on attempt %d", last_rc, attempt)
        if attempt < retries:
            _kill_msiexec()
            time.sleep(_UNINSTALL_RETRY_WAIT)

    raise UninstallError(f"msiexec /x failed after {retries} attempts (last rc={last_rc})")


def uninstall_by_wmic() -> bool:
    """
    Windows only: uninstall via WMIC when the product code is unknown.
    Returns True on success.
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
    try:
        subprocess.run(["taskkill", "/F", "/IM", "msiexec.exe"], capture_output=True, timeout=10)
    except Exception:
        pass


# ── macOS ──────────────────────────────────────────────────────────────────────

def _install_pkg_mac(pkg_path: str | Path, extra_args: Optional[list[str]]) -> None:
    """
    Install NSClient PKG on macOS via ``sudo installer``.
    [ASSUMED: verify M1 (pkg filename), M3 (sudo vs root)]
    """
    if not is_admin():
        raise InstallError("PKG installation requires root privileges on macOS")

    cmd = ["installer", "-allowUntrusted", "-pkg", str(pkg_path), "-target", "/"]
    if extra_args:
        cmd.extend(extra_args)

    log.info("Installing PKG: %s", pkg_path)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
    except Exception as exc:
        raise InstallError(f"installer subprocess error: {exc}") from exc

    if result.returncode != 0:
        raise InstallError(
            f"installer failed (rc={result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
        )
    log.info("PKG installed successfully")


def _uninstall_mac() -> None:
    """
    Uninstall NSClient on macOS.
    [BLOCKED: unknown method — see knowledge_gap.md M2]
    """
    raise NotImplementedError(
        "macOS uninstall method unknown — see knowledge_gap.md M2. "
        "Likely a bundled uninstall script or pkgutil --forget."
    )


# ── Linux ──────────────────────────────────────────────────────────────────────

# Linux package formats
LINUX_PKG_DEB = "deb"
LINUX_PKG_RPM = "rpm"
LINUX_PKG_RUN = "run"

_LINUX_DEB_PACKAGE_NAME = "nsclient"
_LINUX_UNINSTALL_SCRIPT = Path("/opt/netskope/stagent/uninstall.sh")


def _install_run_linux(installer_path: str | Path, extra_args: Optional[list[str]]) -> None:
    """
    Install NSClient on Linux.

    Detects package format from extension and dispatches:
      .run → ``chmod 755; ./STAgent.run [args]``
      .deb → ``dpkg -i <file>``
      .rpm → ``rpm -ivh <file>``

    For .run silent install via email, pass extra_args like:
      ["-H", "tenant.goskope.com", "-o", "<orgKey>", "-m", "user@example.com"]
    Add "-c" for headless (no GUI) mode.
    """
    if not is_admin():
        raise InstallError("NSClient installation requires root privileges on Linux")

    installer_path = Path(installer_path)
    suffix = installer_path.suffix.lower()

    if suffix == ".deb":
        cmd = ["dpkg", "-i", str(installer_path)]
    elif suffix == ".rpm":
        cmd = ["rpm", "-ivh", str(installer_path)]
    else:
        # .run file — make executable first
        try:
            installer_path.chmod(0o755)
        except Exception:
            log.warning("Could not chmod 755: %s", installer_path)
        cmd = [str(installer_path)]

    if extra_args:
        cmd.extend(extra_args)

    log.info("Installing (%s): %s", suffix or ".run", installer_path)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
    except Exception as exc:
        raise InstallError(f"Linux install subprocess error: {exc}") from exc

    if result.returncode != 0:
        raise InstallError(
            f"Linux install failed (rc={result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    log.info("Linux install completed successfully")


def _uninstall_linux(method: str = "auto") -> None:
    """
    Uninstall NSClient on Linux.

    Methods:
      "auto"   — tries uninstall.sh first, then dpkg, then rpm
      "script" — /opt/netskope/stagent/uninstall.sh
      "deb"    — dpkg -r nsclient
      "rpm"    — rpm -e <package-name>  (discovered via rpm -qa)

    Note: if password protection is enabled, uninstall.sh will prompt
    for the uninstall password.
    """
    if not is_admin():
        raise UninstallError("Uninstall requires root privileges on Linux")

    if method in ("auto", "script"):
        if _LINUX_UNINSTALL_SCRIPT.is_file():
            log.info("Uninstalling via uninstall.sh")
            result = subprocess.run(
                [str(_LINUX_UNINSTALL_SCRIPT)],
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode == 0:
                log.info("uninstall.sh succeeded")
                return
            log.warning("uninstall.sh failed (rc=%d): %s", result.returncode, result.stderr.strip())
            if method == "script":
                raise UninstallError(f"uninstall.sh failed (rc={result.returncode})")

    if method in ("auto", "deb"):
        # Try dpkg -r nsclient
        log.info("Attempting dpkg -r %s", _LINUX_DEB_PACKAGE_NAME)
        result = subprocess.run(
            ["dpkg", "-r", _LINUX_DEB_PACKAGE_NAME],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode == 0:
            log.info("dpkg -r succeeded")
            return
        if method == "deb":
            raise UninstallError(f"dpkg -r failed (rc={result.returncode}): {result.stderr.strip()}")

    if method in ("auto", "rpm"):
        # Discover rpm package name first
        rpm_name = _find_rpm_package()
        if rpm_name:
            log.info("Attempting rpm -e %s", rpm_name)
            result = subprocess.run(
                ["rpm", "-e", rpm_name],
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode == 0:
                log.info("rpm -e succeeded")
                return
            if method == "rpm":
                raise UninstallError(f"rpm -e failed (rc={result.returncode}): {result.stderr.strip()}")
        elif method == "rpm":
            raise UninstallError("No nsclient RPM package found via rpm -qa")

    raise UninstallError("All Linux uninstall methods failed — tried uninstall.sh, dpkg, rpm")


def _find_rpm_package() -> str:
    """Query ``rpm -qa`` for the nsclient package name (e.g. nsclient-99.0.0-3060.x86_64)."""
    try:
        result = subprocess.run(
            ["rpm", "-qa"],
            capture_output=True, text=True, timeout=30,
        )
        for line in result.stdout.splitlines():
            if "nsclient" in line.lower():
                return line.strip()
    except Exception:
        log.exception("rpm -qa failed")
    return ""
