"""
Crash dump detection and log collection for NSClient.
Uses nsdiag.exe -o to collect log bundles; scans known dump paths for .dmp files.
"""

import glob
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Known crash dump search patterns
CRASH_DUMP_PATTERNS = [
    r"C:\dump\stAgentSvc.exe\*.dmp",
    r"C:\ProgramData\netskope\stagent\logs\*.dmp",
]

# Constructed at runtime because %APPDATA% is user-specific
_APPDATA_PATTERN = r"%APPDATA%\Netskope\stagent\Logs\*.dmp"

_NSDIAG_64 = Path(r"C:\Program Files\Netskope\STAgent\nsdiag.exe")
_NSDIAG_32 = Path(r"C:\Program Files (x86)\Netskope\STAgent\nsdiag.exe")

_NSDIAG_TIMEOUT = 120


def check_crash_dumps(custom_dump_path: Optional[str] = None) -> tuple[bool, int]:
    """
    Scan known crash dump directories for .dmp files.

    Zero-byte dumps are cleaned up automatically (they are incomplete artifacts).

    Args:
        custom_dump_path: Additional glob pattern to scan.

    Returns:
        Tuple of (crash_found: bool, zero_byte_count: int).
        crash_found is True if any non-zero-byte dump is detected.
    """
    import os

    patterns = list(CRASH_DUMP_PATTERNS)
    patterns.append(os.path.expandvars(_APPDATA_PATTERN))
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
                    log.debug("Removed zero-byte dump: %s", path)
                except OSError:
                    pass
            else:
                log.error("CRASH DUMP DETECTED: %s (size=%d bytes)", path, size)
                crash_found = True

    return crash_found, zero_count


def collect_log_bundle(
    is_64bit: bool,
    output_dir: Path,
    label: Optional[str] = None,
) -> Optional[Path]:
    """
    Run ``nsdiag.exe -o <output_file>`` to produce a zipped log bundle.

    Args:
        is_64bit: Which nsdiag.exe to run.
        output_dir: Directory where the bundle will be saved.
        label: Optional filename label (defaults to a timestamp).

    Returns:
        Path to the created zip file, or None on failure.
    """
    nsdiag = _NSDIAG_64 if is_64bit else _NSDIAG_32
    if not nsdiag.exists():
        log.error("nsdiag.exe not found: %s", nsdiag)
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = label or time.strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"{timestamp}_log_bundle.zip"

    log.info("Collecting log bundle → %s", output_file)
    try:
        result = subprocess.run(
            [str(nsdiag), "-o", str(output_file)],
            capture_output=True, text=True, timeout=_NSDIAG_TIMEOUT,
        )
        if result.returncode != 0:
            log.warning(
                "nsdiag -o returned %d: %s",
                result.returncode, result.stdout.strip()
            )
    except Exception:
        log.exception("collect_log_bundle failed")
        return None

    if output_file.exists():
        log.info("Log bundle saved: %s (%.1f KB)", output_file, output_file.stat().st_size / 1024)
        return output_file

    log.warning("nsdiag ran but output file not found: %s", output_file)
    return None
