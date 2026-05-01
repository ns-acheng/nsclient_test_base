"""
Local NSClient (Netskope Client) inspection helpers — Windows, macOS, Linux.

Reads nsconfig.json, runs nsdiag, validates install state.
No external library dependencies beyond Python stdlib.

macOS paths/executables marked [ASSUMED] still need verification per knowledge_gap.md.
"""

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ── Platform paths and executable lists ───────────────────────────────────────

if sys.platform.startswith("win"):
    # Confirmed Windows paths
    NSCONFIG_PATH        = Path(r"C:\ProgramData\netskope\stagent\nsconfig.json")
    INSTALL_DIR_64       = Path(r"C:\Program Files\Netskope\STAgent")
    INSTALL_DIR_32       = Path(r"C:\Program Files (x86)\Netskope\STAgent")
    NSDIAG_PATH_64       = INSTALL_DIR_64 / "nsdiag.exe"
    NSDIAG_PATH_32       = INSTALL_DIR_32 / "nsdiag.exe"
    REQUIRED_EXECUTABLES = ["stAgentSvc.exe", "stAgentUI.exe"]
    WATCHDOG_EXECUTABLE  = "stAgentSvcMon.exe"

elif sys.platform.startswith("darwin"):
    # macOS — install location confirmed from ps aux output
    # nsconfig.json path and nsdiag path still [ASSUMED] — see knowledge_gap.md M6
    NSCONFIG_PATH        = Path("/Library/Application Support/Netskope/STAgent/nsconfig.json")
    INSTALL_DIR_64       = Path("/Applications/Netskope Client.app")   # confirmed from ps aux
    INSTALL_DIR_32       = INSTALL_DIR_64  # no 32-bit on macOS
    NSDIAG_PATH_64       = Path("/Library/Application Support/Netskope/STAgent/nsdiag")  # [ASSUMED M6]
    NSDIAG_PATH_32       = NSDIAG_PATH_64
    # Key binaries within the app bundle (relative to INSTALL_DIR_64)
    # Confirmed from ps aux: nsAuxiliarySvc and "Netskope Client" binary
    REQUIRED_EXECUTABLES = [
        "Contents/MacOS/Netskope Client",
        "Contents/XPCServices/nsAuxiliarySvc",
    ]
    WATCHDOG_EXECUTABLE  = ""  # watchdog mode appears to be Windows-only [ASSUMED M8]

else:
    # Linux — confirmed paths and executables
    NSCONFIG_PATH        = Path("/opt/netskope/stagent/nsconfig.json")
    INSTALL_DIR_64       = Path("/opt/netskope/stagent")
    INSTALL_DIR_32       = INSTALL_DIR_64  # no 32-bit distinction on Linux
    NSDIAG_PATH_64       = INSTALL_DIR_64 / "nsdiag"
    NSDIAG_PATH_32       = NSDIAG_PATH_64
    REQUIRED_EXECUTABLES = ["stAgentSvc"]  # confirmed: ls /opt/netskope/stagent/stAgentSvc
    WATCHDOG_EXECUTABLE  = ""              # unknown — see knowledge_gap.md L9
    # Uninstall script lives at /opt/netskope/stagent/uninstall.sh (for .run installs)
    UNINSTALL_SCRIPT     = INSTALL_DIR_64 / "uninstall.sh"


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class NsConfigInfo:
    """Information extracted from nsconfig.json (same schema on all platforms)."""
    tenant_hostname: str
    config_name: str
    allow_auto_update: bool = False
    watchdog_mode: bool = False


@dataclass
class ExeValidationResult:
    """Result of verifying executables / processes in the install directory."""
    valid: bool
    install_dir: str
    present: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    version_mismatches: list[str] = field(default_factory=list)
    watchdog_mode: bool = False
    processes_running: list[str] = field(default_factory=list)
    processes_not_running: list[str] = field(default_factory=list)


# ── nsconfig.json ──────────────────────────────────────────────────────────────

def read_nsconfig(path: Optional[Path] = None) -> dict:
    """Read and return the raw nsconfig.json as a dict."""
    config_path = path or NSCONFIG_PATH
    with open(config_path, encoding="utf-8") as fh:
        return json.load(fh)


def parse_nsconfig(data: dict) -> NsConfigInfo:
    """
    Extract key fields from a parsed nsconfig.json dict.

    Schema is the same on all platforms:
    - nsgw.host — strips "gateway-" prefix to get tenant hostname
    - clientConfig.configurationName
    - clientConfig.clientUpdate.allowAutoUpdate
    - clientConfig.nsclient_watchdog_monitor (string "true"/"false", Windows concept)
    """
    nsgw_host = data.get("nsgw", {}).get("host", "")
    tenant_hostname = nsgw_host[len("gateway-"):] if nsgw_host.startswith("gateway-") else nsgw_host

    client_config = data.get("clientConfig", {})
    config_name = client_config.get("configurationName", "")
    allow_auto_update = bool(client_config.get("clientUpdate", {}).get("allowAutoUpdate", False))
    watchdog_raw = client_config.get("nsclient_watchdog_monitor", "false")
    watchdog_mode = str(watchdog_raw).lower() == "true"

    return NsConfigInfo(
        tenant_hostname=tenant_hostname,
        config_name=config_name,
        allow_auto_update=allow_auto_update,
        watchdog_mode=watchdog_mode,
    )


def get_nsconfig_info(path: Optional[Path] = None) -> Optional[NsConfigInfo]:
    """Read nsconfig.json and return parsed info.  Returns None on any error."""
    config_path = path or NSCONFIG_PATH
    try:
        data = read_nsconfig(config_path)
        return parse_nsconfig(data)
    except FileNotFoundError:
        log.warning("nsconfig.json not found: %s", config_path)
        return None
    except Exception:
        log.exception("Failed to parse nsconfig.json: %s", config_path)
        return None


# ── Config sync ────────────────────────────────────────────────────────────────

def sync_config(is_64bit: bool = True, wait_sec: float = 30) -> bool:
    """
    Run ``nsdiag -u`` to pull the latest config from the tenant.

    ``is_64bit`` is only meaningful on Windows.
    macOS/Linux use a single nsdiag path.

    Note: whether nsdiag -u is needed on macOS post-install is still unconfirmed
    — see knowledge_gap.md M4.
    """
    if sys.platform.startswith("win"):
        nsdiag = NSDIAG_PATH_64 if is_64bit else NSDIAG_PATH_32
    else:
        nsdiag = NSDIAG_PATH_64

    if not nsdiag.exists():
        log.error("nsdiag not found: %s", nsdiag)
        return False

    log.info("Running nsdiag -u")
    start = time.monotonic()
    try:
        result = subprocess.run(
            [str(nsdiag), "-u"],
            capture_output=True, text=True, timeout=90,
        )
    except Exception:
        log.exception("nsdiag -u failed")
        return False

    elapsed = time.monotonic() - start
    if result.returncode != 0:
        log.warning("nsdiag -u returned %d: %s", result.returncode, result.stdout.strip())

    remaining_wait = max(0.0, wait_sec - elapsed)
    if remaining_wait > 0:
        log.debug("Waiting %.1fs for config write to complete", remaining_wait)
        time.sleep(remaining_wait)

    return result.returncode == 0


# ── Install directory ──────────────────────────────────────────────────────────

def detect_install_dir() -> Optional[Path]:
    """
    Return the NSClient install directory by checking for the primary executable.

    Windows : checks 64-bit then 32-bit flat directory
    macOS   : checks for /Applications/Netskope Client.app bundle
    Linux   : checks for /opt/netskope/stagent directory
    """
    if sys.platform.startswith("win"):
        for install_dir in (INSTALL_DIR_64, INSTALL_DIR_32):
            if (install_dir / "stAgentSvc.exe").is_file():
                return install_dir
        return None

    if sys.platform.startswith("darwin"):
        # App bundle presence indicates installation
        main_binary = INSTALL_DIR_64 / "Contents" / "MacOS" / "Netskope Client"
        if main_binary.is_file():
            return INSTALL_DIR_64
        return None

    # Linux
    if (INSTALL_DIR_64 / "stAgentSvc").is_file():
        return INSTALL_DIR_64
    return None


def get_install_dir(is_64bit: bool = True) -> Path:
    """
    Return the expected install directory.
    ``is_64bit`` is only relevant on Windows — macOS/Linux always return the single install dir.
    """
    if sys.platform.startswith("win"):
        return INSTALL_DIR_64 if is_64bit else INSTALL_DIR_32
    return INSTALL_DIR_64


# ── Version detection ──────────────────────────────────────────────────────────

def get_installed_version(install_dir: Optional[Path] = None) -> str:
    """
    Read the installed NSClient version.

    Windows : PowerShell VersionInfo on stAgentSvc.exe
    macOS   : [UNKNOWN — see knowledge_gap.md V1]
    Linux   : [UNKNOWN — see knowledge_gap.md V2]
    """
    if install_dir is None:
        install_dir = detect_install_dir()
    if install_dir is None:
        return ""

    if sys.platform.startswith("win"):
        exe_path = install_dir / "stAgentSvc.exe"
        return _get_file_version_win(exe_path) if exe_path.is_file() else ""

    # macOS / Linux version detection method unknown — V1/V2 in knowledge_gap.md
    log.warning("get_installed_version not yet implemented on %s — see knowledge_gap.md V1/V2", sys.platform)
    return ""


def get_installer_version(installer_path: Path) -> str:
    """
    Read the version embedded in an installer file before installation.

    Windows : PowerShell COM (WindowsInstaller.Installer) on .msi
    macOS   : [UNKNOWN — see knowledge_gap.md V3]
    Linux   : [UNKNOWN — see knowledge_gap.md V3]
    """
    if sys.platform.startswith("win"):
        return _get_msi_version_win(installer_path)
    log.warning("get_installer_version not implemented on %s — see knowledge_gap.md V3", sys.platform)
    return ""


# ── Executable validation ──────────────────────────────────────────────────────

def verify_executables(
    is_64bit: bool = True,
    expected_version: Optional[str] = None,
    nsconfig_path: Optional[Path] = None,
) -> ExeValidationResult:
    """
    Validate that required executables/binaries exist and their processes are running.

    On Windows: checks flat INSTALL_DIR for .exe files.
    On macOS:   checks paths relative to the app bundle (INSTALL_DIR_64).
    On Linux:   checks flat INSTALL_DIR for binaries.
    """
    install_dir = get_install_dir(is_64bit)
    result = ExeValidationResult(valid=False, install_dir=str(install_dir))

    info = get_nsconfig_info(nsconfig_path)
    result.watchdog_mode = info.watchdog_mode if info else False

    executables = list(REQUIRED_EXECUTABLES)
    if result.watchdog_mode and WATCHDOG_EXECUTABLE:
        executables.append(WATCHDOG_EXECUTABLE)

    for rel_path in executables:
        exe_path = install_dir / rel_path
        if not exe_path.is_file():
            result.missing.append(rel_path)
            continue

        result.present.append(rel_path)

        if expected_version and sys.platform.startswith("win"):
            actual = _get_file_version_win(exe_path)
            if actual and actual != expected_version:
                result.version_mismatches.append(
                    f"{rel_path}: expected {expected_version}, got {actual}"
                )

        # Use the final component of the path as the process name to check
        proc_name = Path(rel_path).name
        if _is_process_running(proc_name):
            result.processes_running.append(rel_path)
        else:
            result.processes_not_running.append(rel_path)

    result.valid = (
        not result.missing
        and not result.version_mismatches
        and not result.processes_not_running
    )
    return result


# ── Private helpers ────────────────────────────────────────────────────────────

def _get_file_version_win(file_path: Path) -> str:
    ps_cmd = f"(Get-Item '{file_path}').VersionInfo.ProductVersion"
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        log.exception("_get_file_version_win failed: %s", file_path)
        return ""


def _get_msi_version_win(msi_path: Path) -> str:
    ps_script = (
        "$i = New-Object -ComObject WindowsInstaller.Installer; "
        f"$db = $i.GetType().InvokeMember('OpenDatabase','InvokeMethod',$null,$i,@('{msi_path}',0)); "
        "$view = $db.GetType().InvokeMember('OpenView','InvokeMethod',$null,$db,"
        "@(\"SELECT Value FROM Property WHERE Property='ProductVersion'\")); "
        "$view.GetType().InvokeMember('Execute','InvokeMethod',$null,$view,$null); "
        "$rec = $view.GetType().InvokeMember('Fetch','InvokeMethod',$null,$view,$null); "
        "Write-Output ($rec.GetType().InvokeMember('StringData','GetProperty',$null,$rec,@(1)))"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=20,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        log.exception("_get_msi_version_win failed: %s", msi_path)
        return ""


def _is_process_running(name: str) -> bool:
    """Check if a named process is running — platform-appropriate."""
    if sys.platform.startswith("win"):
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            return name.lower() in result.stdout.lower()
        except Exception:
            return False
    else:
        try:
            result = subprocess.run(
                ["pgrep", "-f", name],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False
