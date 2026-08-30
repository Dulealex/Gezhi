from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

import pytest

if TYPE_CHECKING:
    from gezhi._knowledge_read import KnowledgeReadReportV1

_OUTPUT_CAP = 1_048_576


def _canonical_json_line(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _success_report(
    command: Literal["knowledge.search", "knowledge.show"],
    value: str,
) -> KnowledgeReadReportV1:
    from gezhi._knowledge_read import KnowledgeReadReportV1

    return KnowledgeReadReportV1(
        command=command,
        outcome="succeeded",
        result={"value": value},
        reason=None,
    )


@pytest.mark.parametrize("command", ["knowledge.search", "knowledge.show"])
def test_json_result_cap_accepts_the_boundary_and_replaces_one_extra_byte(
    command: Literal["knowledge.search", "knowledge.show"],
) -> None:
    from gezhi._knowledge_commands import build_knowledge_read_json_buffer_v1

    empty = _canonical_json_line(
        {
            "command": command,
            "diagnostics": [],
            "outcome": "succeeded",
            "result": {"value": ""},
            "schema_version": "gezhi.cli_result.v1",
        }
    )
    padding = _OUTPUT_CAP - len(empty)
    assert padding > 0

    boundary = build_knowledge_read_json_buffer_v1(
        _success_report(command, "x" * padding)
    )
    assert len(boundary) == _OUTPUT_CAP
    assert json.loads(boundary)["outcome"] == "succeeded"

    overflow = build_knowledge_read_json_buffer_v1(
        _success_report(command, "x" * (padding + 1))
    )
    assert overflow == _canonical_json_line(
        {
            "command": command,
            "diagnostics": [{"code": f"{command}.result_too_large.v1", "context": {}}],
            "outcome": "blocked",
            "result": None,
            "schema_version": "gezhi.cli_result.v1",
        }
    )


def test_human_mode_uses_the_would_be_json_size_cap() -> None:
    from gezhi._knowledge_commands import build_knowledge_read_human_buffer_v1

    report = _success_report("knowledge.show", "x" * _OUTPUT_CAP)
    assert (
        build_knowledge_read_human_buffer_v1(report)
        == ("结果超过本命令的输出上限；本次结果未截断。\n").encode()
    )


def test_binary_writer_retries_short_writes_without_exceeding_the_chunk_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gezhi._knowledge_commands as commands

    payload = bytes(range(251)) * 600
    written = bytearray()
    requested_sizes: list[int] = []
    setmode_calls: list[tuple[int, int]] = []

    def fake_setmode(fd: int, mode: int) -> int:
        setmode_calls.append((fd, mode))
        return 0

    def fake_write(fd: int, value: memoryview) -> int:
        assert fd == 17
        current = bytes(value)
        requested_sizes.append(len(current))
        count = max(1, len(current) // 2)
        written.extend(current[:count])
        return count

    monkeypatch.setattr(commands.msvcrt, "setmode", fake_setmode)
    monkeypatch.setattr(commands.os, "write", fake_write)

    commands._write_buffer_v1(payload, fd=17)

    assert setmode_calls == [(17, commands.os.O_BINARY)]
    assert written == payload
    assert requested_sizes
    assert max(requested_sizes) == 65_536
    assert all(1 <= size <= 65_536 for size in requested_sizes)


def test_binary_writer_hard_stops_on_a_zero_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gezhi._knowledge_commands as commands

    class _PresentationExit(RuntimeError):
        pass

    monkeypatch.setattr(commands.msvcrt, "setmode", lambda _fd, _mode: 0)
    monkeypatch.setattr(commands.os, "write", lambda _fd, _value: 0)

    def hard_exit(code: int) -> None:
        raise _PresentationExit(code)

    monkeypatch.setattr(commands.os, "_exit", hard_exit)
    with pytest.raises(_PresentationExit, match="1"):
        commands._write_buffer_v1(b"payload", fd=17)
