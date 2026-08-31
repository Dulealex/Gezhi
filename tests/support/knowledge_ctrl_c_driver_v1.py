from __future__ import annotations

import base64
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path


def _ignore_ctrl_c_in_driver_v1() -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    setter = kernel32.SetConsoleCtrlHandler
    setter.argtypes = [ctypes.c_void_p, ctypes.c_int]
    setter.restype = ctypes.c_int
    if setter(None, True) == 0:
        raise ctypes.WinError(ctypes.get_last_error())


def _send_ctrl_c_to_console_v1() -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    generate = kernel32.GenerateConsoleCtrlEvent
    generate.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    generate.restype = ctypes.c_int
    if generate(0, 0) == 0:
        raise ctypes.WinError(ctypes.get_last_error())


def _wait_for_child_marker_v1(process: subprocess.Popen[bytes], marker: Path) -> int:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if marker.is_file():
            return int(marker.read_text(encoding="ascii"))
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                "Gezhi exited before its Codex child became active: "
                + (stdout + stderr).decode(errors="replace")
            )
        time.sleep(0.01)
    raise TimeoutError("Codex child did not become active before Ctrl+C")


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit("usage: driver MARKER COMMAND [ARG ...]")
    marker = Path(sys.argv[1])
    command = sys.argv[2:]
    _ignore_ctrl_c_in_driver_v1()
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        child_pid = _wait_for_child_marker_v1(process, marker)
        _send_ctrl_c_to_console_v1()
        stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    receipt = {
        "child_pid": child_pid,
        "returncode": process.returncode,
        "stderr_base64": base64.b64encode(stderr).decode("ascii"),
        "stdout_base64": base64.b64encode(stdout).decode("ascii"),
    }
    sys.stdout.write(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
