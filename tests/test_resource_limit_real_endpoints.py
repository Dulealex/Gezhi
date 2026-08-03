from __future__ import annotations

import subprocess
from queue import Queue
from threading import Thread

import pytest
from launcher_support import run_python_script, start_python_script

CLOSED_FD2_SCRIPT = r"""
import os
import sys

from gezhi.bootstrap import main


os.close(2)
sys.argv = ["gezhi", "x" * 8193]
raise SystemExit(main())
"""

BROKEN_PIPE_SCRIPT = r"""
import os
import sys

from gezhi.bootstrap import main


read_fd, write_fd = os.pipe()
os.dup2(write_fd, 2)
os.close(write_fd)
os.close(read_fd)
sys.argv = ["gezhi", "x" * 8193]
raise SystemExit(main())
"""

BLOCKING_WRITE_ENTERED = b"BLOCKING_WRITE_ENTERED\n"
BLOCKING_PIPE_SCRIPT = r"""
import ctypes
from ctypes import wintypes
import msvcrt
import os
import sys

from gezhi import bootstrap


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
set_pipe_state = kernel32.SetNamedPipeHandleState
set_pipe_state.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
    ctypes.c_void_p,
]
set_pipe_state.restype = wintypes.BOOL

read_fd, write_fd = os.pipe()
write_handle = wintypes.HANDLE(msvcrt.get_osfhandle(write_fd))
nowait_mode = wintypes.DWORD(1)
if not set_pipe_state(write_handle, ctypes.byref(nowait_mode), None, None):
    raise ctypes.WinError(ctypes.get_last_error())

real_write = os.write
try:
    while True:
        real_write(write_fd, b"x" * 4096)
except OSError:
    pass

wait_mode = wintypes.DWORD(0)
if not set_pipe_state(write_handle, ctypes.byref(wait_mode), None, None):
    raise ctypes.WinError(ctypes.get_last_error())

os.dup2(write_fd, 2)
os.close(write_fd)


def observed_blocking_write(fd, remaining):
    if fd == 2:
        real_write(1, b"BLOCKING_WRITE_ENTERED\n")
    return real_write(fd, remaining)


bootstrap.os.write = observed_blocking_write
sys.argv = ["gezhi", "x" * 8193]
raise SystemExit(bootstrap.main())
"""


@pytest.mark.parametrize("source", [CLOSED_FD2_SCRIPT, BROKEN_PIPE_SCRIPT])
def test_real_failed_fd2_endpoints_return_two_without_stdout(source: str) -> None:
    result = run_python_script(source)

    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b""


def test_external_termination_is_distinct_from_completed_blocking_write() -> None:
    process = start_python_script(BLOCKING_PIPE_SCRIPT)
    stdout = process.stdout
    stderr = process.stderr
    assert stdout is not None
    assert stderr is not None
    marker_queue: Queue[bytes] = Queue()
    reader = Thread(
        target=lambda: marker_queue.put(stdout.readline()),
        daemon=True,
    )
    reader.start()

    try:
        assert marker_queue.get(timeout=3.0) == BLOCKING_WRITE_ENTERED
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.25)
        process.terminate()
        process.wait(timeout=3.0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3.0)

    assert process.returncode != 2
    assert stdout.read() == b""
    assert stderr.read() == b""
