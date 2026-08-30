from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def _write_all(fd: int, payload: bytes, *, chunk: int = 65_536) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset : offset + chunk])
        if written <= 0:
            raise RuntimeError("double made no write progress")
        offset += written


def _prompt_receipt(prompt: bytes) -> bytes:
    value = {
        "type": "double.prompt",
        "length": len(prompt),
        "sha256": hashlib.sha256(prompt).hexdigest(),
    }
    return json.dumps(value, separators=(",", ":")).encode("ascii") + b"\n"


def _success(final_path: Path, *, exit_code: int = 0) -> None:
    prompt = sys.stdin.buffer.read()
    _write_all(1, _prompt_receipt(prompt), chunk=7)
    final_path.write_bytes(b'{"answer":"double-success"}\n')
    os._exit(exit_code)


def _final_from_file(final_path: Path, payload_path: Path) -> None:
    prompt = sys.stdin.buffer.read()
    _write_all(1, _prompt_receipt(prompt), chunk=7)
    completed = {
        "type": "turn.completed",
        "usage": {
            "cached_input_tokens": 0,
            "input_tokens": 10,
            "output_tokens": 20,
            "reasoning_output_tokens": 5,
        },
    }
    _write_all(
        1,
        json.dumps(completed, separators=(",", ":")).encode("ascii") + b"\n",
        chunk=7,
    )
    final_path.write_bytes(payload_path.read_bytes())


def _message_failure(message_path: Path, *, exit_code: int) -> None:
    prompt = sys.stdin.buffer.read()
    _write_all(1, _prompt_receipt(prompt), chunk=7)
    failed = {
        "type": "turn.failed",
        "error": {"message": message_path.read_text(encoding="utf-8")},
    }
    _write_all(
        1,
        json.dumps(failed, separators=(",", ":")).encode("utf-8") + b"\n",
        chunk=7,
    )
    os._exit(exit_code)


def _hang(*, read_prompt: bool) -> None:
    if read_prompt:
        sys.stdin.buffer.read()
    threading.Event().wait()


def _descendant_hang() -> None:
    prompt = sys.stdin.buffer.read()
    child = "import threading;threading.Event().wait()"
    subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", child],
        stdin=subprocess.DEVNULL,
        stdout=sys.stdout,
        stderr=sys.stderr,
        close_fds=False,
    )
    _write_all(1, _prompt_receipt(prompt))


def _events_bytes(length: int, final_path: Path) -> None:
    sys.stdin.buffer.read()
    remaining = length
    block = b"e" * 65_536
    while remaining:
        current = block[: min(len(block), remaining)]
        _write_all(1, current)
        remaining -= len(current)
    final_path.write_bytes(b"{}")


def _events_then_hang() -> None:
    sys.stdin.buffer.read()
    _write_all(1, b"events-before-hang")
    threading.Event().wait()


def _mark_and_hang(marker_path: Path) -> None:
    sys.stdin.buffer.read()
    _write_all(1, b'{"type":"double.started"}\n')
    marker_staging = marker_path.with_name(marker_path.name + ".tmp")
    marker_staging.write_text(str(os.getpid()), encoding="ascii")
    os.replace(marker_staging, marker_path)
    threading.Event().wait()


def _events_bytes_then_hang(length: int) -> None:
    sys.stdin.buffer.read()
    remaining = length
    block = b"e" * 65_536
    while remaining:
        current = block[: min(len(block), remaining)]
        _write_all(1, current)
        remaining -= len(current)
    threading.Event().wait()


def _final_bytes(length: int, final_path: Path) -> None:
    sys.stdin.buffer.read()
    _write_all(1, b'{"type":"turn.completed"}\n')
    with final_path.open("wb", buffering=0) as target:
        remaining = length
        block = b"f" * 65_536
        while remaining:
            current = block[: min(len(block), remaining)]
            target.write(current)
            remaining -= len(current)


def _final_bytes_then_hang(length: int, final_path: Path) -> None:
    _final_bytes(length, final_path)
    threading.Event().wait()


def _stderr_flood(final_path: Path) -> None:
    prompt = sys.stdin.buffer.read()
    _write_all(2, b"s" * 1_048_576)
    _write_all(1, _prompt_receipt(prompt))
    final_path.write_bytes(b"{}")


def _chunk_boundaries(final_path: Path) -> None:
    sys.stdin.buffer.read()
    for marker, length in (
        (b"a", 1),
        (b"b", 65_535),
        (b"c", 65_536),
        (b"d", 65_537),
    ):
        _write_all(1, marker * length, chunk=length)
    final_path.write_bytes(b"{}")


def _zero_stdout_write(final_path: Path) -> None:
    sys.stdin.buffer.read()
    assert os.write(1, b"") == 0
    _write_all(1, b"after-zero")
    final_path.write_bytes(b"{}")


def _finite_descendant(final_path: Path) -> None:
    sys.stdin.buffer.read()
    descendant = "import os,time;time.sleep(0.15);os.write(1,b'descendant')"
    subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", descendant],
        stdin=subprocess.DEVNULL,
        stdout=sys.stdout,
        stderr=sys.stderr,
        close_fds=False,
    )
    _write_all(1, b"root-")
    final_path.write_bytes(b"{}")


def _delayed_exit(final_path: Path, milliseconds: int) -> None:
    sys.stdin.buffer.read()
    _write_all(1, b"before-delay")
    time.sleep(milliseconds / 1_000)
    final_path.write_bytes(b"{}")


def _no_final() -> None:
    sys.stdin.buffer.read()
    _write_all(1, b"events-without-final")


def _malformed(final_path: Path) -> None:
    sys.stdin.buffer.read()
    _write_all(1, b"\xff{not-json\n")
    final_path.write_bytes(b"\xffnot-json")


def _inspect_handles(final_path: Path, sentinels: tuple[int, ...]) -> None:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_console_window = kernel32.GetConsoleWindow
    get_console_window.restype = ctypes.c_void_p
    get_std_handle = kernel32.GetStdHandle
    get_std_handle.argtypes = [ctypes.c_ulong]
    get_std_handle.restype = ctypes.c_void_p
    get_file_type = kernel32.GetFileType
    get_file_type.argtypes = [ctypes.c_void_p]
    get_file_type.restype = ctypes.c_ulong
    get_handle_information = kernel32.GetHandleInformation
    get_handle_information.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    get_handle_information.restype = ctypes.c_int
    set_event = kernel32.SetEvent
    set_event.argtypes = [ctypes.c_void_p]
    set_event.restype = ctypes.c_int
    prompt = sys.stdin.buffer.read()
    sentinel_results: list[dict[str, int | bool]] = []
    for sentinel in sentinels:
        flags = ctypes.c_ulong()
        ctypes.set_last_error(0)
        accessible = bool(get_handle_information(sentinel, ctypes.byref(flags)))
        ctypes.set_last_error(0)
        set_succeeded = bool(set_event(sentinel))
        sentinel_results.append(
            {
                "accessible": accessible,
                "set_succeeded": set_succeeded,
                "set_error": int(ctypes.get_last_error()),
            }
        )
    payload = {
        "console": bool(get_console_window()),
        "stdin_type": int(get_file_type(get_std_handle(-10 & 0xFFFFFFFF))),
        "stdout_type": int(get_file_type(get_std_handle(-11 & 0xFFFFFFFF))),
        "stderr_type": int(get_file_type(get_std_handle(-12 & 0xFFFFFFFF))),
        "sentinels": sentinel_results,
        "prompt_length": len(prompt),
        "prompt_sha256": hashlib.sha256(prompt).hexdigest(),
    }
    _write_all(1, json.dumps(payload, separators=(",", ":")).encode("ascii"))
    final_path.write_bytes(b"{}")


def _dual_backpressure(
    final_path: Path,
    *,
    stdout_bytes: int,
    stdout_started_event: str,
    stdout_returned_event: str,
    stdin_read_gate_event: str,
) -> None:
    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_event = kernel32.OpenEventW
    open_event.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_wchar_p]
    open_event.restype = ctypes.c_void_p
    set_event = kernel32.SetEvent
    set_event.argtypes = [ctypes.c_void_p]
    set_event.restype = ctypes.c_int
    wait = kernel32.WaitForSingleObject
    wait.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    wait.restype = ctypes.c_ulong
    write_file = kernel32.WriteFile
    write_file.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.c_void_p,
    ]
    write_file.restype = ctypes.c_int
    close = kernel32.CloseHandle
    close.argtypes = [ctypes.c_void_p]
    close.restype = ctypes.c_int
    access = 0x0002 | 0x00100000
    started = int(open_event(access, False, stdout_started_event))
    returned = int(open_event(access, False, stdout_returned_event))
    stdin_gate = int(open_event(access, False, stdin_read_gate_event))
    if not all((started, returned, stdin_gate)):
        raise RuntimeError("double could not open a named barrier")
    try:
        payload = b"o" * stdout_bytes
        buffer = ctypes.create_string_buffer(payload, len(payload))
        written = ctypes.c_ulong()
        stdout_handle = int(msvcrt.get_osfhandle(1))
        if stdout_handle == -1:
            raise RuntimeError("double stdout handle is invalid")
        if not set_event(started):
            raise RuntimeError("double could not signal stdout start")
        succeeded = bool(
            write_file(
                stdout_handle,
                buffer,
                len(payload),
                ctypes.byref(written),
                None,
            )
        )
        write_error = ctypes.get_last_error()
        if not set_event(returned):
            raise RuntimeError("double could not signal stdout return")
        count = int(written.value)
        if not succeeded or not 1 <= count <= len(payload):
            raise RuntimeError(f"double stdout WriteFile failed: {write_error}:{count}")
        _write_all(1, payload[count:])
        if wait(stdin_gate, 0xFFFFFFFF) != 0:
            raise RuntimeError("double stdin gate failed")
        prompt = sys.stdin.buffer.read()
        final_path.write_bytes(_prompt_receipt(prompt))
    finally:
        for handle in (stdin_gate, returned, started):
            if not close(handle):
                raise RuntimeError("double barrier close failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "scenario",
        choices=(
            "success",
            "final-from-file",
            "message-failure",
            "exit",
            "hang",
            "no-read-hang",
            "descendant-hang",
            "events-bytes",
            "events-overflow-hang",
            "events-then-hang",
            "mark-and-hang",
            "final-bytes",
            "final-overflow-hang",
            "stderr-flood",
            "chunk-boundaries",
            "zero-stdout-write",
            "finite-descendant",
            "delayed-exit",
            "no-final",
            "malformed",
            "inspect-handles",
            "dual-backpressure",
        ),
    )
    parser.add_argument("--final", type=Path, required=True)
    parser.add_argument("--payload-file", type=Path)
    parser.add_argument("--value", type=int, default=0)
    parser.add_argument("--sentinel", action="append", type=int, default=[])
    parser.add_argument("--stdout-bytes", type=int, default=0)
    parser.add_argument("--stdout-started-event", default="")
    parser.add_argument("--stdout-returned-event", default="")
    parser.add_argument("--stdin-read-gate-event", default="")
    args = parser.parse_args()
    if args.scenario == "success":
        _success(args.final)
    if args.scenario == "final-from-file":
        if args.payload_file is None:
            parser.error("final-from-file requires --payload-file")
        _final_from_file(args.final, args.payload_file)
    if args.scenario == "message-failure":
        if args.payload_file is None:
            parser.error("message-failure requires --payload-file")
        _message_failure(args.payload_file, exit_code=args.value)
    if args.scenario == "exit":
        _success(args.final, exit_code=args.value)
    if args.scenario == "hang":
        _hang(read_prompt=True)
    if args.scenario == "no-read-hang":
        _hang(read_prompt=False)
    if args.scenario == "descendant-hang":
        _descendant_hang()
    if args.scenario == "events-bytes":
        _events_bytes(args.value, args.final)
    if args.scenario == "events-overflow-hang":
        _events_bytes_then_hang(args.value)
    if args.scenario == "events-then-hang":
        _events_then_hang()
    if args.scenario == "mark-and-hang":
        if args.payload_file is None:
            parser.error("mark-and-hang requires --payload-file")
        _mark_and_hang(args.payload_file)
    if args.scenario == "final-bytes":
        _final_bytes(args.value, args.final)
    if args.scenario == "final-overflow-hang":
        _final_bytes_then_hang(args.value, args.final)
    if args.scenario == "stderr-flood":
        _stderr_flood(args.final)
    if args.scenario == "chunk-boundaries":
        _chunk_boundaries(args.final)
    if args.scenario == "zero-stdout-write":
        _zero_stdout_write(args.final)
    if args.scenario == "finite-descendant":
        _finite_descendant(args.final)
    if args.scenario == "delayed-exit":
        _delayed_exit(args.final, args.value)
    if args.scenario == "no-final":
        _no_final()
    if args.scenario == "malformed":
        _malformed(args.final)
    if args.scenario == "inspect-handles":
        _inspect_handles(args.final, tuple(args.sentinel))
    if args.scenario == "dual-backpressure":
        _dual_backpressure(
            args.final,
            stdout_bytes=args.stdout_bytes,
            stdout_started_event=args.stdout_started_event,
            stdout_returned_event=args.stdout_returned_event,
            stdin_read_gate_event=args.stdin_read_gate_event,
        )


if __name__ == "__main__":
    main()
