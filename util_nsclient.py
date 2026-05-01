"""
Local NSClient (Netskope Client) inspection helpers.
Reads nsconfig.json, runs nsdiag.exe, validates install state.
No external library dependencies beyond Python stdlib.
"""

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
NSCONFIG_PATH = Path(r"C:\ProgramData\netskope\stagent\nsconfig.json")
NSCONFIG_ENC_PATH = Path(r"C:\ProgramData\netskope\stagent\nsconfig.enc")
INSTALL_DIR_64 = Path(r"C:\Program Files\Netskope\STAgent")
INSTALL_DIR_32 = Path(r"C:\Program Files (x86)\Netskope\STAgent")
NSDIAG_PATH_64 = INSTALL_DIR_64 / "nsdiag.exe"
NSDIAG_PATH_32 = INSTALL_DIR_32 / "nsdiag.exe"

# ── Required executables ───────────────────────────────────────────────────────
REQUIRED_EXECUTABLES = ["stAgentSvc.exe", "stAgentUI.exe"]
WATCHDOG_EXECUTABLE = "stAgentSvcMon.exe"


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class NsConfigInfo:
    """Information extracted from nsconfig.json."""
    tenant_hostname: str
    config_name: str
    allow_auto_update: bool = False
    watchdog_mode: bool = False


@dataclass
class ExeValidationResult:
    """Result of verifying executables in the install directory."""
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
    """
    Read and return the raw nsconfig.json as a dict.
    Raises FileNotFoundError if the file does not exist.
    """
    config_path = path or NSCONFIG_PATH
    with open(config_path, encoding="utf-8") as fh:
        return json.load(fh)


def parse_nsconfig(data: dict) -> NsConfigInfo:
    """
    Extract key fields from a parsed nsconfig.json dict.

    Fields used:
    - nsgw.host — strips the "gateway-" prefix to obtain the tenant hostname
    - clientConfig.configurationName
    - clientConfig.clientUpdate.allowAutoUpdate
    - clientConfig.nsclient_watchdog_monitor  (string "true"/"false")
    """
    # Tenant hostname
    nsgw_host = data.get("nsgw", {}).get("host", "")
    if nsgw_host.startswith("gateway-"):
        tenant_hostname = nsgw_host[len("gateway-"):]
    else:
        tenant_hostname = nsgw_host

    client_config = data.get("clientConfig", {})
    config_name = client_config.get("configurationName", "")

    allow_auto_update = bool(
        client_config.get("clientUpdate", {}).get("allowAutoUpdate", False)
    )

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
    Run ``nsdiag.exe -u`` to pull the latest config from the tenant.

    After the command finishes, waits up to ``wait_sec`` seconds for the config
    write to complete.  If nsdiag itself took >10 s the caller can assume
    the write happened during execution and no extra wait is needed.

    Returns True if nsdiag ran without error.
    """
    nsdiag = NSDIAG_PATH_64 if is_64bit else NSDIAG_PATH_32
    if not nsdiag.exists():
        log.error("nsdiag.exe not found: %s", nsdiag)
        return False

    log.info("Running nsdiag -u (is_64bit=%s)", is_64bit)
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

    # If nsdiag completed quickly, give the agent time to write nsconfig.json
    remaining_wait = max(0.0, wait_sec - elapsed)
    if remaining_wait > 0:
        log.debug("Waiting %.1fs for config write to complete", remaining_wait)
        time.sleep(remaining_wait)

    return result.returncode == 0


# ── Install directory ──────────────────────────────────────────────────────────

def detect_install_dir() -> Optional[Path]:
    """Return the NSClient install directory (64-bit checked first)."""
    for install_dir in (INSTALL_DIR_64, INSTALL_DIR_32):
        exe = install_dir / "stAgentSvc.exe"
        if exe.is_file():
            return install_dir
    return None


def get_install_dir(is_64bit: bool) -> Path:
    """Return the expected install directory for the given architecture."""
    return INSTALL_DIR_64 if is_64bit else INSTALL_DIR_32


# ── Version detection ──────────────────────────────────────────────────────────

def get_installed_version(install_dir: Optional[Path] = None) -> str:
    """
    Read the ProductVersion from stAgentSvc.exe using PowerShell VersionInfo.
    Returns an empty string if the executable is not found or PowerShell fails.
    """
    if install_dir is None:
        install_dir = detect_install_dir()
    if install_dir is None:
        return ""

    exe_path = install_dir / "stAgentSvc.exe"
    if not exe_path.is_file():
        return ""

    return _get_file_version(exe_path)


def get_msi_version(msi_path: Path) -> str:
    """
    Read the version from an MSI file via PowerShell COM (WindowsInstaller.Installer).
    Returns an empty string on failure.
    """
    ps_script = (
        "$i = New-Object -ComObject WindowsInstaller.Installer; "
        f"$db = $i.GetType().InvokeMember('OpenDatabase', 'InvokeMethod', $null, $i, @('{msi_path}', 0)); "
        "$view = $db.GetType().InvokeMember('OpenView', 'InvokeMethod', $null, $db, "
        "@(\"SELECT Value FROM Property WHERE Property='ProductVersion'\")); "
        "$view.GetType().InvokeMember('Execute', 'InvokeMethod', $null, $view, $null); "
        "$rec = $view.GetType().InvokeMember('Fetch', 'InvokeMethod', $null, $view, $null); "
        "Write-Output ($rec.GetType().InvokeMember('StringData', 'GetProperty', $null, $rec, @(1)))"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=20,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        log.exception("get_msi_version failed for: %s", msi_path)
        return ""


# ── Executable validation ──────────────────────────────────────────────────────

def verify_executables(
    is_64bit: bool,
    expected_version: Optional[str] = None,
    nsconfig_path: Optional[Path] = None,
) -> ExeValidationResult:
    """
    Validate that required executables exist, have the expected version,
    and their processes are running.

    Args:
        is_64bit: Whether to check the 64-bit install directory.
        expected_version: If provided, compare file versions against this value.
        nsconfig_path: Override for nsconfig.json location.

    Returns:
        ExeValidationResult with a summary.
    """
    install_dir = get_install_dir(is_64bit)
    result = ExeValidationResult(valid=False, install_dir=str(install_dir))

    # Determine watchdog mode
    info = get_nsconfig_info(nsconfig_path)
    result.watchdog_mode = info.watchdog_mode if info else False

    executables = list(REQUIRED_EXECUTABLES)
    if result.watchdog_mode:
        executables.append(WATCHDOG_EXECUTABLE)

    for exe_name in executables:
        exe_path = install_dir / exe_name
        if not exe_path.is_file():
            result.missing.append(exe_name)
            continue

        result.present.append(exe_name)

        if expected_version:
            actual = _get_file_version(exe_path)
            if actual and actual != expected_version:
                result.version_mismatches.append(
                    f"{exe_name}: expected {expected_version}, got {actual}"
                )

        if _is_exe_running(exe_name):
            result.processes_running.append(exe_name)
        else:
            result.processes_not_running.append(exe_name)

    result.valid = (
        not result.missing
        and not result.version_mismatches
        and not result.processes_not_running
    )

    return result


# ── Private helpers ────────────────────────────────────────────────────────────

def _get_file_version(file_path: Path) -> str:
    """Use PowerShell to read ProductVersion from a PE file."""
    ps_cmd = f"(Get-Item '{file_path}').VersionInfo.ProductVersion"
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        log.exception("_get_file_version failed for: %s", file_path)
        return ""


def _is_exe_running(exe_name: str) -> bool:
    """Return True if at least one process with this image name is running."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        return exe_name.lower() in result.stdout.lower()
    except Exception:
        return False
