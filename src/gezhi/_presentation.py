from __future__ import annotations

import json
import msvcrt
import os
from collections.abc import Mapping, Sequence
from typing import Literal, TypeAlias

_OPERATIONS_OUTPUT_CAP = 65_536
_DIAGNOSTICS_OUTPUT_CAP = 16_384
_COMMANDS = frozenset(
    {
        "doctor",
        "status",
        "knowledge.ask",
        "knowledge.search",
        "knowledge.show",
        "literature.add",
        "literature.resume",
        "literature.review",
    }
)
CliOutcome: TypeAlias = Literal[
    "succeeded",
    "blocked",
    "failed",
    "interrupted",
]


class CliJsonOutputTooLargeV1(ValueError):
    pass


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def cli_json_buffer_v1(
    *,
    command: str,
    outcome: CliOutcome,
    result: Mapping[str, object] | None,
    diagnostics: Sequence[Mapping[str, object]],
    output_cap: int,
) -> bytes:
    if type(command) is not str or command not in _COMMANDS:
        raise ValueError("CLI command is not registered")
    if outcome not in {"succeeded", "blocked", "failed", "interrupted"}:
        raise ValueError("CLI outcome is invalid")
    if type(output_cap) is not int or output_cap < 1:
        raise ValueError("CLI output cap is invalid")
    if result is not None and type(result) is not dict:
        raise TypeError("CLI result must be an object or null")
    if type(diagnostics) not in {list, tuple} or len(diagnostics) > 16:
        raise TypeError("CLI diagnostics must be a bounded array")
    for diagnostic in diagnostics:
        if (
            type(diagnostic) is not dict
            or set(diagnostic) != {"code", "context"}
            or type(diagnostic["code"]) is not str
            or type(diagnostic["context"]) is not dict
        ):
            raise TypeError("CLI diagnostic item is invalid")
    if len(_canonical_json_bytes(diagnostics)) > _DIAGNOSTICS_OUTPUT_CAP:
        raise ValueError("CLI diagnostics exceed their byte limit")

    envelope = {
        "schema_version": "gezhi.cli_result.v1",
        "command": command,
        "outcome": outcome,
        "result": result,
        "diagnostics": diagnostics,
    }
    payload = _canonical_json_bytes(envelope) + b"\n"
    if len(payload) > output_cap:
        raise CliJsonOutputTooLargeV1("CLI output exceeds its byte limit")
    return payload


def operations_json_buffer(
    *,
    command: str,
    outcome: CliOutcome,
    result: Mapping[str, object] | None,
    diagnostics: Sequence[Mapping[str, object]],
) -> bytes:
    try:
        return cli_json_buffer_v1(
            command=command,
            outcome=outcome,
            result=result,
            diagnostics=diagnostics,
            output_cap=_OPERATIONS_OUTPUT_CAP,
        )
    except CliJsonOutputTooLargeV1 as error:
        raise ValueError("Operations output exceeds its byte limit") from error


def operations_human_buffer(value: str) -> bytes:
    payload = value.encode("utf-8")
    if len(payload) > _OPERATIONS_OUTPUT_CAP:
        raise ValueError("Operations output exceeds its byte limit")
    return payload


def present_operations_json(
    *,
    command: str,
    outcome: CliOutcome,
    result: Mapping[str, object] | None,
    diagnostics: Sequence[Mapping[str, object]],
) -> None:
    try:
        buffer = operations_json_buffer(
            command=command,
            outcome=outcome,
            result=result,
            diagnostics=diagnostics,
        )
    except Exception:  # noqa: BLE001 - the contract controls sealing failures.
        os._exit(1)
    write_operations_stdout(buffer)


def present_operations_human(value: str) -> None:
    try:
        buffer = operations_human_buffer(value)
    except Exception:  # noqa: BLE001 - the contract controls sealing failures.
        os._exit(1)
    write_operations_stdout(buffer)


def write_operations_stdout(buffer: bytes) -> None:
    write_binary_buffer_v1(buffer, fd=1, max_chunk_size=None)


def write_binary_buffer_v1(
    buffer: bytes,
    *,
    fd: int,
    max_chunk_size: int | None,
) -> None:
    if type(buffer) is not bytes:
        raise TypeError("CLI write buffer must be immutable bytes")
    if type(fd) is not int or fd < 0:
        raise ValueError("CLI write descriptor is invalid")
    if max_chunk_size is not None and (
        type(max_chunk_size) is not int or max_chunk_size < 1
    ):
        raise ValueError("CLI write chunk limit is invalid")
    try:
        msvcrt.setmode(fd, os.O_BINARY)
    except OSError:
        os._exit(1)

    view = memoryview(buffer)
    offset = 0
    while offset < len(buffer):
        remaining = len(buffer) - offset
        requested = (
            remaining if max_chunk_size is None else min(max_chunk_size, remaining)
        )
        current = view[offset : offset + requested]
        if (
            current.obj is not buffer
            or current.nbytes != requested
            or not 1 <= requested <= remaining
        ):
            raise RuntimeError("CLI write view invariant failed")
        try:
            count = os.write(fd, current)
        except OSError:
            os._exit(1)
        if type(count) is not int or not 1 <= count <= requested:
            os._exit(1)
        offset += count
