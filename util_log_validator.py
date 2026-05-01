"""
NSClient debug log reader and validator — Windows, macOS, Linux.

Reads nsdebuglog.log (and rotated copies) with position tracking so callers
only see new content since the last call.  Handles log rotation transparently
via inode tracking on Unix and file-size rollback detection on Windows.

Platform default log paths:
  Windows : C:\\ProgramData\\netskope\\stagent\\logs\\nsdebuglog.log
  macOS   : /Library/Logs/Netskope/stAgent/nsdebuglog.log  [ASSUMED — M6]
  Linux   : /opt/netskope/stagent/log/nsdebuglog.log

Usage:
    from util_log_validator import NsClientLogValidator

    v = NsClientLogValidator()
    v.seek_to_end()                          # mark start point before action under test

    # ... trigger the feature ...

    found = v.check_log("autoReenableDuration")          # literal search
    found = v.check_log_regex(r"timer.*expired", re.I)   # regex search
    new_text = v.read_new_logs()                         # raw new content since last read
"""

import logging
import re
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Platform default log paths ────────────────────────────────────────────────

if sys.platform.startswith("win"):
    _DEFAULT_LOG = Path(r"C:\ProgramData\netskope\stagent\logs\nsdebuglog.log")
elif sys.platform.startswith("darwin"):
    # [ASSUMED M6 — verify actual path]
    _DEFAULT_LOG = Path("/Library/Logs/Netskope/stAgent/nsdebuglog.log")
else:
    _DEFAULT_LOG = Path("/opt/netskope/stagent/log/nsdebuglog.log")

# Maximum number of rotated log files to search (nsdebuglog.1.log … nsdebuglog.10.log)
_MAX_ROTATED = 10

# How far back (bytes) to scan when seeking by timestamp
_MAX_SCAN_BYTES = 50 * 1024 * 1024  # 50 MB


# ── Validator class ───────────────────────────────────────────────────────────

class NsClientLogValidator:
    """
    Stateful reader for the NSClient debug log.

    Thread-safe.  A single instance should be created per test session and
    reused; call ``seek_to_end()`` before each test action to reset the
    read position.
    """

    def __init__(self, log_path: Optional[Path] = None) -> None:
        """
        Args:
            log_path: Override the default platform log path.
                      Useful for unit tests or non-standard installs.
        """
        self.log_path: Path = log_path or _DEFAULT_LOG
        self._lock = threading.Lock()
        self._last_pos: int = 0
        self._last_inode: int = 0           # Unix only; 0 on Windows
        self._pending_reads: list[tuple[int, int]] = []   # [(inode, start_pos), ...]

    # ── Position management ───────────────────────────────────────────────────

    def seek_to_end(self) -> None:
        """
        Move the read position to the current end of the log file.

        Call this immediately before triggering the action under test so that
        subsequent ``check_log`` / ``read_new_logs`` calls only see new output.
        """
        with self._lock:
            self._pending_reads = []
            if self.log_path.exists():
                try:
                    self._last_pos = self.log_path.stat().st_size
                    self._last_inode = self.log_path.stat().st_ino
                except OSError:
                    self._last_pos = 0
                    self._last_inode = 0
            log.debug("seek_to_end: position=%d path=%s", self._last_pos, self.log_path)

    def seek_by_time(self, seconds: int = 100) -> None:
        """
        Seek backwards through the log to find content older than ``seconds`` ago.

        Useful when you need to validate log lines that were written before the
        test started (e.g. checking the state at install time).

        Searches the current log file first, then rotated copies
        (nsdebuglog.1.log … nsdebuglog.10.log) in reverse chronological order.
        """
        with self._lock:
            self._pending_reads = []
            target_time = datetime.now() - timedelta(seconds=seconds)

            found, pos, inode = self._scan_for_time(self.log_path, target_time)
            if found:
                self._last_pos = pos
                self._last_inode = inode
                log.info("seek_by_time: found in current log at pos=%d", pos)
                return

            # Search rotated files oldest-first so we queue them in order
            rotated = self._rotated_paths()
            found_idx = -1
            found_pos = 0

            for idx, rpath in enumerate(rotated):
                found, pos, _ = self._scan_for_time(rpath, target_time)
                if found:
                    found_idx = idx
                    found_pos = pos
                    break

            if found_idx != -1:
                queue = [(rotated[found_idx], found_pos)]
                for i in range(found_idx - 1, -1, -1):
                    queue.append((rotated[i], 0))
            else:
                queue = [(p, 0) for p in reversed(rotated)]

            for fpath, start in queue:
                try:
                    self._pending_reads.append((fpath.stat().st_ino, start))
                except OSError:
                    pass

            # Reset to start of current log
            try:
                st = self.log_path.stat()
                self._last_inode = st.st_ino
                self._last_pos = 0
            except OSError:
                self._last_inode = 0
                self._last_pos = 0

            log.info("seek_by_time: queued %d pending files", len(self._pending_reads))

    # ── Search ────────────────────────────────────────────────────────────────

    def check_log(self, pattern: str) -> bool:
        """
        Return True if ``pattern`` (literal string) appears in new log content
        since the last read position.

        Advances the read position to the current end of the log.
        """
        return self._search(pattern, is_regex=False)

    def check_log_regex(self, pattern: str, flags: int = 0) -> bool:
        """
        Return True if regex ``pattern`` matches anywhere in new log content
        since the last read position.

        Advances the read position to the current end of the log.
        """
        return self._search(pattern, is_regex=True, flags=flags)

    def read_new_logs(self) -> str:
        """
        Return all new log content since the last read position as a string.

        Handles:
        - Normal growth of the current log file
        - Log rotation (detected via inode change on Unix, size rollback on Windows)
        - Pending rotated files queued by ``seek_by_time``

        Advances the read position to the current end of the log.
        """
        with self._lock:
            content = ""

            # Drain any pending rotated files first
            if self._pending_reads:
                for inode, start_pos in self._pending_reads:
                    fpath = self._find_by_inode(inode)
                    if fpath:
                        content += self._read_chunk(fpath, start_pos)
                self._pending_reads = []

            # Stat the current log
            try:
                st = self.log_path.stat()
                current_inode = st.st_ino
                current_size = st.st_size
            except OSError:
                return content

            # Rotation detected: inode changed (Unix) or file shrank (Windows)
            if self._last_inode and current_inode != self._last_inode:
                old_path = self._find_by_inode(self._last_inode)
                if old_path:
                    content += self._read_chunk(old_path, self._last_pos)
                self._last_pos = 0
                self._last_inode = current_inode
            elif current_size < self._last_pos:
                # File was truncated / recreated without inode change (Windows)
                self._last_pos = 0

            content += self._read_chunk(self.log_path, self._last_pos)

            # Advance position
            try:
                st = self.log_path.stat()
                self._last_pos = st.st_size
                self._last_inode = st.st_ino
            except OSError:
                pass

            if content:
                log.debug(
                    "read_new_logs: %d bytes  start=%r  end=%r",
                    len(content),
                    content[:80].replace("\n", "\\n"),
                    content[-80:].replace("\n", "\\n"),
                )

            return content

    # ── Private helpers ───────────────────────────────────────────────────────

    def _search(self, pattern: str, is_regex: bool, flags: int = 0) -> bool:
        """Read new content and search it.  Handles rotation like read_new_logs."""
        with self._lock:
            found = False

            # Rotation: size rolled back → read tail of rotated file first
            try:
                current_size = self.log_path.stat().st_size if self.log_path.exists() else 0
            except OSError:
                current_size = 0

            if current_size < self._last_pos:
                rotated = self.log_path.with_suffix(".1.log")
                tail = self._read_chunk(rotated, self._last_pos)
                found = self._match(pattern, tail, is_regex, flags)
                self._last_pos = 0

            new_content = self._read_chunk(self.log_path, self._last_pos)
            if not found:
                found = self._match(pattern, new_content, is_regex, flags)

            try:
                self._last_pos = self.log_path.stat().st_size if self.log_path.exists() else 0
            except OSError:
                self._last_pos = 0

            return found

    @staticmethod
    def _match(pattern: str, text: str, is_regex: bool, flags: int) -> bool:
        if not text:
            return False
        if is_regex:
            return bool(re.search(pattern, text, flags=flags))
        return pattern in text

    def _read_chunk(self, path: Path, start_pos: int) -> str:
        if not path.exists():
            return ""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(start_pos)
                return fh.read()
        except Exception:
            log.exception("Failed to read log chunk: %s", path)
            return ""

    def _rotated_paths(self) -> list[Path]:
        """Return existing rotated log paths in order: [.1.log, .2.log, ...]."""
        paths = []
        for i in range(1, _MAX_ROTATED + 1):
            p = self.log_path.with_suffix(f".{i}.log")
            if p.exists():
                paths.append(p)
            else:
                break
        return paths

    def _find_by_inode(self, target_inode: int) -> Optional[Path]:
        """Find the log file (current or rotated) that has the given inode."""
        candidates = [self.log_path] + self._rotated_paths()
        for p in candidates:
            try:
                if p.stat().st_ino == target_inode:
                    return p
            except OSError:
                pass
        return None

    def _scan_for_time(
        self, path: Path, target_time: datetime
    ) -> tuple[bool, int, int]:
        """
        Scan ``path`` backwards for a log line older than ``target_time``.

        Returns (found: bool, byte_position: int, inode: int).
        ``found=True`` means we found a position where logs are older than target_time.
        ``found=None`` means the file could not be read.
        """
        if not path.exists():
            return False, 0, 0

        try:
            st = path.stat()
            fsize = st.st_size
            inode = st.st_ino
        except OSError:
            return False, 0, 0

        if fsize == 0:
            return False, 0, inode

        chunk_size = 1024 * 1024
        min_pos = max(0, fsize - _MAX_SCAN_BYTES)
        pos = fsize

        while pos > min_pos:
            read_len = min(chunk_size, pos - min_pos)
            pos -= read_len
            try:
                with open(path, "rb") as fh:
                    fh.seek(pos)
                    raw = fh.read(read_len)
                    text = raw.decode("utf-8", errors="ignore")
                    m = re.search(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})", text)
                    if m:
                        try:
                            ts = datetime.strptime(m.group(1), "%Y/%m/%d %H:%M:%S")
                            if ts < target_time:
                                return True, pos, inode
                        except ValueError:
                            pass
            except Exception:
                break

        return False, pos, inode


# ── Module-level singleton ────────────────────────────────────────────────────
# Tests can use the singleton via module functions, or instantiate their own
# NsClientLogValidator directly for isolation.

_instance: Optional[NsClientLogValidator] = None
_instance_lock = threading.Lock()


def init_validator(log_path: Optional[Path] = None) -> NsClientLogValidator:
    """
    Initialise (or replace) the module-level singleton.

    Call once per test session, typically in a session-scoped fixture.
    """
    global _instance
    with _instance_lock:
        _instance = NsClientLogValidator(log_path)
        log.info("Log validator initialised: %s", _instance.log_path)
        return _instance


def get_validator() -> NsClientLogValidator:
    """Return the module-level singleton.  Raises if not initialised."""
    if _instance is None:
        raise RuntimeError(
            "Log validator not initialised. "
            "Call init_validator() or create NsClientLogValidator() directly."
        )
    return _instance


# ── Convenience wrappers ──────────────────────────────────────────────────────

def check_log(pattern: str) -> bool:
    """Literal string search in new log content since last read."""
    return get_validator().check_log(pattern)


def check_log_regex(pattern: str, flags: int = 0) -> bool:
    """Regex search in new log content since last read."""
    return get_validator().check_log_regex(pattern, flags)


def read_new_logs() -> str:
    """Return raw new log content since last read."""
    return get_validator().read_new_logs()


def seek_to_end() -> None:
    """Advance read position to current end of log (call before each test action)."""
    get_validator().seek_to_end()
