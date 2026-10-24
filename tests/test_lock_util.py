"""Unit tests for lock_util.py verifying file lock, timeouts, and stale lock recovery."""

import json
import os
import time
from pathlib import Path

import pytest

from lock_util import FileLock, LockAcquisitionError, _is_pid_alive


def test_lock_acquire_and_release(tmp_path: Path):
    lock_file = tmp_path / "test.lock"
    lock = FileLock(lock_file=lock_file, timeout=1.0)

    assert not lock.is_acquired
    assert not lock_file.exists()

    lock.acquire()
    assert lock.is_acquired
    assert lock_file.exists()

    meta = json.loads(lock_file.read_text(encoding="utf-8"))
    assert meta["pid"] == os.getpid()
    assert "timestamp" in meta

    lock.release()
    assert not lock.is_acquired
    assert not lock_file.exists()


def test_lock_context_manager(tmp_path: Path):
    lock_file = tmp_path / "test_ctx.lock"

    with FileLock(lock_file=lock_file, timeout=1.0) as lock:
        assert lock.is_acquired
        assert lock_file.exists()

    assert not lock.is_acquired
    assert not lock_file.exists()


def test_lock_timeout_when_held(tmp_path: Path):
    lock_file = tmp_path / "held.lock"
    # Create an artificial lock file held by current PID with current timestamp
    lock_file.write_text(
        json.dumps({"pid": os.getpid(), "timestamp": time.time()}),
        encoding="utf-8",
    )

    # Attempt to acquire with very short timeout
    lock2 = FileLock(lock_file=lock_file, timeout=0.4, poll_interval=0.1)
    with pytest.raises(LockAcquisitionError) as exc_info:
        lock2.acquire()

    assert "Timed out" in str(exc_info.value)


def test_stale_lock_recovery_dead_pid(tmp_path: Path):
    lock_file = tmp_path / "dead_pid.lock"
    # Use a PID that does not exist (e.g. 9999999)
    dead_pid = 9999999
    lock_file.write_text(
        json.dumps({"pid": dead_pid, "timestamp": time.time() - 10}),
        encoding="utf-8",
    )

    # The lock should detect dead PID, break it, and acquire successfully
    lock = FileLock(lock_file=lock_file, timeout=2.0, stale_timeout=5.0)
    lock.acquire()

    assert lock.is_acquired
    meta = json.loads(lock_file.read_text(encoding="utf-8"))
    assert meta["pid"] == os.getpid()

    lock.release()


def test_stale_lock_recovery_expired_timestamp(tmp_path: Path):
    lock_file = tmp_path / "expired.lock"
    # Old timestamp older than stale_timeout
    old_time = time.time() - 300
    lock_file.write_text(
        json.dumps({"pid": os.getpid(), "timestamp": old_time}),
        encoding="utf-8",
    )
    # Also set file mtime back
    os.utime(lock_file, (old_time, old_time))

    lock = FileLock(lock_file=lock_file, timeout=2.0, stale_timeout=10.0)
    lock.acquire()

    assert lock.is_acquired
    lock.release()


def test_is_pid_alive_current():
    assert _is_pid_alive(os.getpid()) is True
    assert _is_pid_alive(-1) is False
    assert _is_pid_alive(99999999) is False
