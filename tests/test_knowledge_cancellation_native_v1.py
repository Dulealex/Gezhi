from __future__ import annotations

import ctypes
import json
import subprocess
from pathlib import Path

from launcher_support import (
    REPOSITORY_ROOT,
    SOURCE_ROOT,
    launcher_commands,
    subprocess_environment,
)


def _bind_native_test_dll(path: Path) -> ctypes.WinDLL:
    dll = ctypes.WinDLL(str(path), use_last_error=True)
    dll.gezhi_cancel_v1_arm.argtypes = []
    dll.gezhi_cancel_v1_arm.restype = ctypes.c_int
    dll.gezhi_cancel_v1_activate.argtypes = []
    dll.gezhi_cancel_v1_activate.restype = ctypes.c_int
    dll.gezhi_cancel_v1_try_begin_work.argtypes = []
    dll.gezhi_cancel_v1_try_begin_work.restype = ctypes.c_int
    dll.gezhi_cancel_v1_snapshot.argtypes = [
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int64),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    dll.gezhi_cancel_v1_snapshot.restype = ctypes.c_int
    dll.gezhi_cancel_v1_conditional_seal.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    dll.gezhi_cancel_v1_conditional_seal.restype = ctypes.c_int
    dll.gezhi_cancel_v1_release.argtypes = []
    dll.gezhi_cancel_v1_release.restype = ctypes.c_int
    dll.gezhi_cancel_v1_test_dispatch.argtypes = [ctypes.c_uint32]
    dll.gezhi_cancel_v1_test_dispatch.restype = ctypes.c_int
    return dll


def _snapshot(dll: ctypes.WinDLL) -> tuple[int, int, int, int, int, int, int]:
    phase = ctypes.c_uint32()
    generation = ctypes.c_uint32()
    latched = ctypes.c_int()
    observed_ns = ctypes.c_int64()
    in_flight = ctypes.c_uint32()
    publication_ready = ctypes.c_int()
    sealed_token = ctypes.c_uint32()
    assert dll.gezhi_cancel_v1_snapshot(
        ctypes.byref(phase),
        ctypes.byref(generation),
        ctypes.byref(latched),
        ctypes.byref(observed_ns),
        ctypes.byref(in_flight),
        ctypes.byref(publication_ready),
        ctypes.byref(sealed_token),
    ) == 1
    return (
        phase.value,
        generation.value,
        latched.value,
        observed_ns.value,
        in_flight.value,
        publication_ready.value,
        sealed_token.value,
    )


def test_native_handler_and_conditional_seal_share_one_admission_gate(
    tmp_path: Path,
) -> None:
    dll_path = tmp_path / "gezhi_cancel_test_v1.dll"
    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(REPOSITORY_ROOT / "tools" / "build-knowledge-cancellation.ps1"),
            "-OutputPath",
            str(dll_path),
            "-TestHooks",
        ],
        check=True,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        timeout=30,
    )
    receipt = json.loads(completed.stdout.splitlines()[-1].decode("ascii"))
    assert receipt["test_hooks"] is True
    assert receipt["toolset"] == "14.44.35207"
    assert receipt["windows_sdk"] == "10.0.26100.0"
    dll = _bind_native_test_dll(dll_path)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_console_ctrl_handler = kernel32.SetConsoleCtrlHandler
    set_console_ctrl_handler.argtypes = [ctypes.c_void_p, ctypes.c_int]
    set_console_ctrl_handler.restype = ctypes.c_int

    assert dll.gezhi_cancel_v1_arm() == 1
    assert set_console_ctrl_handler(None, False) != 0
    assert dll.gezhi_cancel_v1_activate() == 1
    assert _snapshot(dll) == (2, 0, 0, 0, 0, 0, 0)
    assert dll.gezhi_cancel_v1_try_begin_work() == 1
    assert dll.gezhi_cancel_v1_test_dispatch(1) == 0
    assert dll.gezhi_cancel_v1_test_dispatch(0) == 1
    phase, generation, latched, observed_ns, in_flight, ready, token = _snapshot(
        dll
    )
    assert (phase, generation, latched, in_flight, ready, token) == (
        2,
        1,
        1,
        0,
        1,
        0,
    )
    assert observed_ns > 0
    assert dll.gezhi_cancel_v1_try_begin_work() == 0
    assert dll.gezhi_cancel_v1_conditional_seal(0, 8) == 0
    assert dll.gezhi_cancel_v1_conditional_seal(1, 9) == 1
    assert dll.gezhi_cancel_v1_test_dispatch(0) == 0
    assert dll.gezhi_cancel_v1_release() == 1
    assert _snapshot(dll) == (4, 1, 1, observed_ns, 0, 1, 9)


def test_public_ask_uses_no_source_profile_without_a_console() -> None:
    arguments = ("knowledge", "ask", " ", "--json")

    for command in launcher_commands(arguments):
        result = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=subprocess_environment(pythonpath_roots=(SOURCE_ROOT,)),
            capture_output=True,
            check=False,
            timeout=15,
            creationflags=0x08000000,
        )
        assert result.returncode == 2, (result.stdout + result.stderr).decode(
            errors="replace"
        )
        assert result.stderr == b""
        assert json.loads(result.stdout) == {
            "command": "knowledge.ask",
            "diagnostics": [
                {"code": "knowledge.ask.invalid_question.v1", "context": {}}
            ],
            "outcome": "blocked",
            "result": None,
            "schema_version": "gezhi.cli_result.v1",
        }
