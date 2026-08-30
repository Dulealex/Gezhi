from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest
from support.reviewed_handoff_witness_v1 import (
    ACCEPT_CANDIDATES_V1,
    ACCEPT_MANIFEST_V1,
)

if TYPE_CHECKING:
    from gezhi._knowledge_read import KnowledgeReadReportV1


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
) -> KnowledgeReadReportV1:
    from gezhi._knowledge_read import KnowledgeReadReportV1

    record = cast(dict[str, object], json.loads(ACCEPT_CANDIDATES_V1))
    candidate = cast(dict[str, object], record["candidate"])
    if command == "knowledge.search":
        result: dict[str, object] = {
            "candidate_count": 1,
            "items": [
                {
                    "candidate": candidate,
                    "governance": {
                        "intake_status": "active",
                        "promotion_status": "not_promoted",
                        "review_status": "accepted",
                    },
                    "rank": 1,
                }
            ],
            "query": "source term",
            "result_kind": "candidate_backed",
            "schema_version": "gezhi.knowledge_search_result.v1",
        }
    else:
        manifest = cast(dict[str, object], json.loads(ACCEPT_MANIFEST_V1))
        receipt = cast(dict[str, object], record["review_receipt"])
        import_result = {
            "action": "accept",
            "candidates_sha256": hashlib.sha256(ACCEPT_CANDIDATES_V1).hexdigest(),
            "handoff_id": manifest["handoff_id"],
            "manifest_sha256": hashlib.sha256(ACCEPT_MANIFEST_V1).hexdigest(),
            "review_revision": receipt["review_revision"],
        }
        result = {
            "candidate": candidate,
            "citation": record["citation"],
            "content_import": import_result,
            "descriptor_snapshots": record["descriptor_snapshots"],
            "evidence_snapshots": record["evidence_snapshots"],
            "governance": {
                "intake_status": "active",
                "promotion_status": "not_promoted",
                "review_status": "accepted",
            },
            "result_kind": "candidate_backed",
            "schema_version": "gezhi.knowledge_show_result.v1",
            "status_import": dict(import_result),
        }
    return KnowledgeReadReportV1(
        command=command,
        outcome="succeeded",
        result=result,
        reason=None,
    )


@pytest.mark.parametrize("command", ["knowledge.search", "knowledge.show"])
def test_command_specific_result_seal_rejects_an_unclosed_success_result(
    command: Literal["knowledge.search", "knowledge.show"],
) -> None:
    from gezhi._knowledge_commands import (
        build_knowledge_read_human_buffer_v1,
        build_knowledge_read_json_buffer_v1,
    )
    from gezhi._knowledge_read import KnowledgeReadReportV1

    invalid = KnowledgeReadReportV1(
        command=command,
        outcome="succeeded",
        result={"value": "not a Knowledge result"},
        reason=None,
    )
    with pytest.raises((TypeError, ValueError)):
        build_knowledge_read_json_buffer_v1(invalid)
    with pytest.raises((TypeError, ValueError)):
        build_knowledge_read_human_buffer_v1(invalid)


@pytest.mark.parametrize("command", ["knowledge.search", "knowledge.show"])
def test_command_specific_result_seal_rejects_nested_identity_or_state_drift(
    command: Literal["knowledge.search", "knowledge.show"],
) -> None:
    from gezhi._knowledge_commands import build_knowledge_read_json_buffer_v1

    report = _success_report(command)
    assert report.result is not None
    result = deepcopy(report.result)
    if command == "knowledge.search":
        items = cast(list[object], result["items"])
        item = cast(dict[str, object], items[0])
        candidate = cast(dict[str, object], item["candidate"])
        candidate["payload_sha256"] = "0" * 64
    else:
        status_import = cast(dict[str, object], result["status_import"])
        status_import["review_revision"] = 2
    invalid = type(report)(
        command=report.command,
        outcome=report.outcome,
        result=result,
        reason=report.reason,
    )
    with pytest.raises((TypeError, ValueError)):
        build_knowledge_read_json_buffer_v1(invalid)


@pytest.mark.parametrize(
    ("command", "outcome", "reason"),
    [
        ("knowledge.search", "blocked", "registry_corrupt"),
        ("knowledge.search", "failed", "registry_unavailable"),
        ("knowledge.show", "blocked", "candidate_corrupt"),
        ("knowledge.show", "failed", "candidate_not_found"),
    ],
)
def test_report_seal_rejects_reason_outcome_matrix_mismatches(
    command: Literal["knowledge.search", "knowledge.show"],
    outcome: Literal["blocked", "failed"],
    reason: str,
) -> None:
    from gezhi._knowledge_commands import build_knowledge_read_json_buffer_v1
    from gezhi._knowledge_read import KnowledgeReadReportV1

    report = KnowledgeReadReportV1(
        command=command,
        outcome=outcome,
        result=None,
        reason=reason,
    )
    with pytest.raises(ValueError):
        build_knowledge_read_json_buffer_v1(report)


def test_show_result_seal_enforces_the_sqlite_int64_revision_ceiling() -> None:
    from gezhi._knowledge_commands import build_knowledge_read_json_buffer_v1

    report = _success_report("knowledge.show")
    assert report.result is not None
    result = deepcopy(report.result)
    for key in ("content_import", "status_import"):
        import_result = cast(dict[str, object], result[key])
        import_result["review_revision"] = 9_223_372_036_854_775_808
    invalid = type(report)(
        command=report.command,
        outcome=report.outcome,
        result=result,
        reason=report.reason,
    )
    with pytest.raises(ValueError):
        build_knowledge_read_json_buffer_v1(invalid)


def test_knowledge_result_cap_converts_the_shared_writer_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gezhi._knowledge_commands as commands
    from gezhi._presentation import CliJsonOutputTooLargeV1

    real_writer = commands.cli_json_buffer_v1

    def forced_overflow(**arguments: Any) -> bytes:
        if arguments["outcome"] == "succeeded":
            raise CliJsonOutputTooLargeV1("forced Knowledge overflow")
        return real_writer(**arguments)

    monkeypatch.setattr(commands, "cli_json_buffer_v1", forced_overflow)
    report = _success_report("knowledge.show")
    expected = _canonical_json_line(
        {
            "command": "knowledge.show",
            "diagnostics": [
                {
                    "code": "knowledge.show.result_too_large.v1",
                    "context": {},
                }
            ],
            "outcome": "blocked",
            "result": None,
            "schema_version": "gezhi.cli_result.v1",
        }
    )
    assert commands.build_knowledge_read_json_buffer_v1(report) == expected
    assert (
        commands.build_knowledge_read_human_buffer_v1(report)
        == ("结果超过本命令的输出上限；本次结果未截断。\n").encode()
    )


@pytest.mark.parametrize("json_output", [False, True])
def test_presenter_serializes_one_authoritative_would_be_json_buffer(
    monkeypatch: pytest.MonkeyPatch,
    json_output: bool,
) -> None:
    import gezhi._knowledge_commands as commands

    real_writer = commands.cli_json_buffer_v1
    serialization_calls: list[dict[str, Any]] = []
    writes: list[bytes] = []

    def counted_writer(**arguments: Any) -> bytes:
        serialization_calls.append(arguments)
        return real_writer(**arguments)

    def capture_write(
        buffer: bytes,
        *,
        fd: int,
        max_chunk_size: int | None,
    ) -> None:
        assert fd == 1
        assert max_chunk_size == 65_536
        writes.append(buffer)

    monkeypatch.setattr(commands, "cli_json_buffer_v1", counted_writer)
    monkeypatch.setattr(commands, "write_binary_buffer_v1", capture_write)

    report = _success_report("knowledge.search")
    assert commands._present_v1(report, json_output=json_output) == report
    assert len(serialization_calls) == 1
    assert len(writes) == 1
    if json_output:
        assert writes[0] == real_writer(**serialization_calls[0])


def test_binary_writer_retries_short_writes_without_exceeding_the_chunk_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gezhi._presentation as presentation

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

    monkeypatch.setattr(presentation.msvcrt, "setmode", fake_setmode)
    monkeypatch.setattr(presentation.os, "write", fake_write)

    presentation.write_binary_buffer_v1(
        payload,
        fd=17,
        max_chunk_size=65_536,
    )

    assert setmode_calls == [(17, presentation.os.O_BINARY)]
    assert written == payload
    assert requested_sizes
    assert max(requested_sizes) == 65_536
    assert all(1 <= size <= 65_536 for size in requested_sizes)


def test_binary_writer_hard_stops_on_a_zero_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gezhi._presentation as presentation

    class _PresentationExit(RuntimeError):
        pass

    monkeypatch.setattr(presentation.msvcrt, "setmode", lambda _fd, _mode: 0)
    monkeypatch.setattr(presentation.os, "write", lambda _fd, _value: 0)

    def hard_exit(code: int) -> None:
        raise _PresentationExit(code)

    monkeypatch.setattr(presentation.os, "_exit", hard_exit)
    with pytest.raises(_PresentationExit, match="1"):
        presentation.write_binary_buffer_v1(
            b"payload",
            fd=17,
            max_chunk_size=65_536,
        )
