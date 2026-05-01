"""
Crash dump detection and log collection — Windows, macOS, Linux.

Windows : .dmp files in well-known paths; nsdiag.exe -o for log bundles
macOS   : .ips files in ~/Library/Logs/DiagnosticReports/  [ASSUMED — verify M6]
Linux   : core files in /var/crash/, /var/log/netskope/    [ASSUMED]
"""

import glob
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Crash dump patterns by platform ───────────────────────────────────────────

if sys.platform.startswith("win"):
    _DUMP_PATTERNS_STATIC = [
        r"C:\dump\stAgentSvc.exe\*.dmp",
        r"C:\ProgramData\netskope\stagent\logs\*.dmp",
    ]
    _DUMP_PATTERNS_DYNAMIC = [r"%APPDATA%\Netskope\stagent\Logs\*.dmp"]  # expanded at runtime
    _NSDIAG_64 = Path(r"C:\Program Files\Netskope\STAgent\nsdiag.exe")
    _NSDIAG_32 = Path(r"C:\Program Files (x86)\Netskope\STAgent\nsdiag.exe")

elif sys.platform.startswith("darwin"):
    # [ASSUMED: verify M6 in knowledge_gap.md]
    _DUMP_PATTERNS_STATIC = []
    _DUMP_PATTERNS_DYNAMIC = [
        str(Path.home() / "Library/Logs/DiagnosticReports/Netskope Client*.ips"),
        str(Path.home() / "Library/Logs/DiagnosticReports/nsdiag*.ips"),
    ]
    _NSDIAG_64 = Path.home() / "Library/Application Support/Netskope/STAgent/nsdiag"
    _NSDIAG_32 = _NSDIAG_64

else:  # Linux — confirmed paths
    _DUMP_PATTERNS_STATIC = [
        "/var/crash/*netskope*",
        "/var/crash/*stagent*",
        "/opt/netskope/stagent/log/core*",
        "/opt/netskope/stagent/logs/core*",
        "/tmp/core*",
    ]
    _DUMP_PATTERNS_DYNAMIC = []
    _NSDIAG_64 = Path("/opt/netskope/stagent/nsdiag")
    _NSDIAG_32 = _NSDIAG_64

_NSDIAG_TIMEOUT = 120


# ── Public API ─────────────────────────────────────────────────────────────────

def check_crash_dumps(custom_dump_path: Optional[str] = None) -> tuple[bool, int]:
    """
    Scan known crash dump/core directories for crash artifacts.

    Zero-byte files are removed automatically (incomplete artifacts).

    Args:
        custom_dump_path: Additional glob pattern to scan.

    Returns:
        (crash_found: bool, zero_byte_count: int)
    """
    import os

    patterns = list(_DUMP_PATTERNS_STATIC)
    for p in _DUMP_PATTERNS_DYNAMIC:
        patterns.append(os.path.expandvars(p))
    if custom_dump_path:
        patterns.append(custom_dump_path)

    crash_found = False
    zero_count = 0

    for pattern in patterns:
        try:
            matches = glob.glob(pattern)
        except Exception:
            continue

        for path in matches:
            try:
                size = Path(path).stat().st_size
            except OSError:
                continue

            if size == 0:
                try:
                    Path(path).unlink()
                    zero_count += 1
                    log.debug("Removed zero-byte artifact: %s", path)
                except OSError:
                    pass
            else:
                log.error("CRASH ARTIFACT DETECTED: %s (size=%d bytes)", path, size)
                crash_found = True

    return crash_found, zero_count


def collect_log_bundle(
    is_64bit: bool = True,
    output_dir: Path = Path("log"),
    label: Optional[str] = None,
) -> Optional[Path]:
    """
    Run ``nsdiag -o <output_file>`` to produce a compressed log bundle.

    Works on all platforms — bundle format differs:
    - Windows : .zip
    - macOS   : .zip  [ASSUMED]
    - Linux   : .tar.gz  [ASSUMED]

    Args:
        is_64bit: Which nsdiag to use (only meaningful on Windows).
        output_dir: Directory to write the bundle.
        label: Filename label (defaults to timestamp).

    Returns:
        Path to the created bundle, or None on failure.
    """
    if sys.platform.startswith("win"):
        nsdiag = _NSDIAG_64 if is_64bit else _NSDIAG_32
        ext = ".zip"
    else:
        nsdiag = _NSDIAG_64
        ext = ".tar.gz" if not sys.platform.startswith("darwin") else ".zip"

    if not nsdiag.exists():
        log.error("nsdiag not found: %s", nsdiag)
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = label or time.strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"{timestamp}_log_bundle{ext}"

    log.info("Collecting log bundle → %s", output_file)
    try:
        result = subprocess.run(
            [str(nsdiag), "-o", str(output_file)],
            capture_output=True, text=True, timeout=_NSDIAG_TIMEOUT,
        )
        if result.returncode != 0:
            log.warning("nsdiag -o returned %d: %s", result.returncode, result.stdout.strip())
    except Exception:
        log.exception("collect_log_bundle failed")
        return None

    if output_file.exists():
        log.info("Log bundle saved: %s (%.1f KB)", output_file, output_file.stat().st_size / 1024)
        return output_file

    log.warning("nsdiag ran but output file not found: %s", output_file)
    return None
