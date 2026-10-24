"""File-based mutex utility for process synchronization.

Provides a robust context manager with timeout and stale lock detection,
primarily used to serialize Microsoft Word COM and conversion operations.
"""

from __future__ import annotations

import os
import sys
import time
import logging
import json
from pathlib import Path
from typing import Optional

logger = logging.getLogger("recruitment_automation.lock_util")


class LockAcquisitionError(TimeoutError):
    """Raised when acquiring a file lock exceeds the configured timeout."""
    pass


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is currently running."""
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000, SYNCHRONIZE = 0x00100000
            STILL_ACTIVE = 259
            process = kernel32.OpenProcess(0x1000, False, pid)
            if not process:
                return False
            exit_code = ctypes.c_ulong()
            success = kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code))
            kernel32.CloseHandle(process)
            return bool(success and exit_code.value == STILL_ACTIVE)
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ValueError):
        return False


class FileLock:
    """A re-entrant-safe, process-level file lock with timeout and stale detection."""

    def __init__(
        self,
        lock_file: str | Path,
        timeout: float = 30.0,
        stale_timeout: float = 120.0,
        poll_interval: float = 0.2,
    ) -> None:
        """Initialize the FileLock.

        Args:
            lock_file: Path to lock file.
            timeout: Maximum seconds to wait before raising LockAcquisitionError.
            stale_timeout: Seconds after which an untouched lock is deemed abandoned.
            poll_interval: Delay between acquisition attempts.
        """
        self.lock_file = Path(lock_file).resolve()
        self.timeout = timeout
        self.stale_timeout = stale_timeout
        self.poll_interval = poll_interval
        self._fd: Optional[int] = None
        self._is_acquired = False

    @property
    def is_acquired(self) -> bool:
        """Return True if the current instance holds the lock."""
        return self._is_acquired

    def _read_lock_metadata(self) -> Optional[dict]:
        """Read metadata (pid, timestamp) from existing lock file."""
        try:
            if not self.lock_file.exists():
                return None
            content = self.lock_file.read_text(encoding="utf-8")
            if not content.strip():
                return None
            return json.loads(content)
        except Exception:
            return None

    def _is_stale(self, metadata: Optional[dict]) -> bool:
        """Determine if lock file is stale due to elapsed time or dead process."""
        if not self.lock_file.exists():
            return False

        now = time.time()
        file_mtime = self.lock_file.stat().st_mtime
        if (now - file_mtime) > self.stale_timeout:
            return True

        if metadata:
            pid = metadata.get("pid")
            created_at = metadata.get("timestamp", 0)
            if (now - created_at) > self.stale_timeout:
                return True
            if pid and not _is_pid_alive(pid):
                return True

        return False

    def _force_break_lock(self) -> None:
        """Remove a stale lock file."""
        try:
            if self.lock_file.exists():
                self.lock_file.unlink(missing_ok=True)
                logger.warning("Broken stale lock file: %s", self.lock_file)
        except OSError as e:
            logger.warning("Could not unlink stale lock %s: %s", self.lock_file, e)

    def acquire(self) -> None:
        """Attempt to acquire the file lock until timeout is reached."""
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        start_time = time.time()

        while True:
            # Check for stale lock
            if self.lock_file.exists():
                meta = self._read_lock_metadata()
                if self._is_stale(meta):
                    logger.warning("Detected stale lock on %s. Breaking lock.", self.lock_file)
                    self._force_break_lock()

            # Attempt atomic creation
            try:
                # O_EXCL | O_CREAT guarantees atomic file creation
                fd = os.open(
                    str(self.lock_file),
                    os.O_CREAT | os.O_EXCL | os.O_RDWR,
                )
                self._fd = fd
                metadata = {
                    "pid": os.getpid(),
                    "timestamp": time.time(),
                }
                os.write(fd, json.dumps(metadata).encode("utf-8"))
                self._is_acquired = True
                return
            except FileExistsError:
                pass
            except OSError as e:
                logger.error("OS error while attempting lock acquisition: %s", e)

            if (time.time() - start_time) >= self.timeout:
                raise LockAcquisitionError(
                    f"Timed out after {self.timeout:.1f}s waiting for lock: {self.lock_file}"
                )

            time.sleep(self.poll_interval)

    def release(self) -> None:
        """Release the file lock."""
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

        if self._is_acquired:
            try:
                # Verify we own it before unlinking
                meta = self._read_lock_metadata()
                if meta and meta.get("pid") == os.getpid():
                    self.lock_file.unlink(missing_ok=True)
                elif not meta:
                    self.lock_file.unlink(missing_ok=True)
            except OSError as e:
                logger.warning("Failed to unlink lock file %s: %s", self.lock_file, e)
            finally:
                self._is_acquired = False

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
