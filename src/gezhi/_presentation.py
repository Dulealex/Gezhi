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


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def operations_json_buffer(
    *,
    command: str,
    outcome: CliOutcome,
    result: Mapping[str, object] | None,
    diagnostics: Sequence[Mapping[str, object]],
) -> bytes:
    if type(command) is not str or command not in _COMMANDS:
        raise ValueError("CLI command is not registered")
    if outcome not in {"succeeded", "blocked", "failed", "interrupted"}:
        raise ValueError("CLI outcome is invalid")
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
    payload = (
        _canonical_json_bytes(envelope) + b"\n"
    )
    if len(payload) > _OPERATIONS_OUTPUT_CAP:
        raise ValueError("Operations output exceeds its byte limit")
    return payload


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
    try:
        msvcrt.setmode(1, os.O_BINARY)
    except OSError:
        os._exit(1)

    view = memoryview(buffer)
    offset = 0
    while offset < len(buffer):
        remaining = len(buffer) - offset
        current = view[offset:]
        if current.obj is not buffer or current.nbytes != remaining:
            raise RuntimeError("stdout view invariant failed")
        try:
            count = os.write(1, current)
        except OSError:
            os._exit(1)
        if type(count) is not int or not 1 <= count <= remaining:
            os._exit(1)
        offset += count
