from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from gezhi._codex_child_process import (
    AttemptTerminalEvidenceV1,
    CancellationObservationV1,
    CaptureEvidenceV1,
)
from gezhi._knowledge_answerer import (
    _attempt_from_evidence_v1 as _project_attempt_raw_v1,
)

_EVENTS_CAP = 16_777_216


@dataclass(frozen=True, slots=True)
class _FixedCancellationV1:
    observed_ns: int | None

    def observed_at_monotonic_ns(self) -> int | None:
        return self.observed_ns


def _evidence(
    tmp_path: Path,
    *,
    events: bytes,
    final: bytes = b"{}\n",
    mechanical_outcome: str = "clean",
    exit_code: int | None = 0,
    events_overflow: bool = False,
    final_overflow: bool = False,
) -> AttemptTerminalEvidenceV1:
    events_path = tmp_path / "events.jsonl"
    final_path = tmp_path / "final_message.txt"
    events_path.write_bytes(events)
    final_path.write_bytes(final)
    return AttemptTerminalEvidenceV1(
        role="knowledge_answerer_v1",
        attempt_ordinal=1,
        commit_wall_time="2026-08-30T20:00:00.000Z",
        commit_monotonic_ns=1_000_000_000,
        provider_started_monotonic_ns=1_010_000_000,
        attempt_deadline_monotonic_ns=1_810_000_000,
        shared_deadline_monotonic_ns=6_710_000_000,
        capture_ready_monotonic_ns=1_125_999_999,
        exit_code=exit_code,
        mechanical_outcome=mechanical_outcome,  # type: ignore[arg-type]
        events=CaptureEvidenceV1(
            path=events_path,
            byte_length=len(events),
            sha256=hashlib.sha256(events).hexdigest(),
            overflow=events_overflow,
        ),
        final_message=CaptureEvidenceV1(
            path=final_path,
            byte_length=len(final),
            sha256=hashlib.sha256(final).hexdigest(),
            overflow=final_overflow,
        ),
        create_process_calls=1,
        stop_calls=int(
            mechanical_outcome in {"timeout", "interrupted"}
            or events_overflow
            or final_overflow
        ),
        resource_ledger_count=0,
        lifecycle_facts=(),
    )


def _json_line(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n"


def _project_attempt_v1(
    evidence: AttemptTerminalEvidenceV1,
    *,
    classification_ready_monotonic_ns: int | None = None,
    cancellation: CancellationObservationV1 | None = None,
) -> tuple[object, str | None, tuple[str, ...]]:
    ready = (
        evidence.capture_ready_monotonic_ns
        if classification_ready_monotonic_ns is None
        else classification_ready_monotonic_ns
    )
    assert ready is not None
    return _project_attempt_raw_v1(
        evidence,
        cancellation=cancellation,
        classification_ready_monotonic_ns=ready,
    )


def test_attempt_projects_the_one_completed_usage_object(tmp_path: Path) -> None:
    events = b"".join(
        (
            _json_line({"type": "turn.started"}),
            _json_line(
                {
                    "type": "turn.completed",
                    "usage": {
                        "cached_input_tokens": 7,
                        "input_tokens": 11,
                        "output_tokens": 13,
                        "reasoning_output_tokens": 17,
                        "ignored": 19,
                    },
                }
            ),
        )
    )

    attempt, failure_class, overflow_channels = _project_attempt_v1(
        _evidence(tmp_path, events=events)
    )

    assert failure_class is None
    assert overflow_channels == ()
    assert attempt.record == {
        "cached_input_tokens": 7,
        "elapsed_ms": 125,
        "exit_code": 0,
        "failure_class": None,
        "finished_at": attempt.record["finished_at"],
        "input_tokens": 11,
        "output_tokens": 13,
        "reasoning_output_tokens": 17,
        "started_at": "2026-08-30T20:00:00.000Z",
        "usage_unavailable": False,
    }
    assert attempt.events_bytes == events


def test_attempt_projects_usage_fields_independently(tmp_path: Path) -> None:
    events = _json_line(
        {
            "type": "turn.completed",
            "usage": {
                "cached_input_tokens": True,
                "input_tokens": 0,
                "output_tokens": -1,
                "reasoning_output_tokens": 9_223_372_036_854_775_808,
            },
        }
    )

    attempt, failure_class, _overflow_channels = _project_attempt_v1(
        _evidence(tmp_path, events=events)
    )

    assert failure_class is None
    assert attempt.record["input_tokens"] == 0
    assert attempt.record["cached_input_tokens"] is None
    assert attempt.record["output_tokens"] is None
    assert attempt.record["reasoning_output_tokens"] is None
    assert attempt.record["usage_unavailable"] is True


@pytest.mark.parametrize(
    "events",
    (
        b"\xef\xbb\xbf{}\n",
        b"\xff\n",
        b"\n",
        b"{}\n\n",
        b'{"outer":{"same":1,"same":2}}\n',
        b"[]\n",
        b"NaN\n",
        b"{} {}\n",
        b'{"type":"turn.completed"}\n{"type":"turn.completed"}\n',
    ),
    ids=(
        "leading-bom",
        "invalid-utf8",
        "empty-first-record",
        "empty-middle-record",
        "nested-duplicate-key",
        "array-root",
        "nonstandard-number",
        "multiple-values",
        "duplicate-completion",
    ),
)
def test_attempt_event_structure_failure_is_unretryable_process_error(
    tmp_path: Path,
    events: bytes,
) -> None:
    attempt, failure_class, overflow_channels = _project_attempt_v1(
        _evidence(tmp_path, events=events)
    )

    assert failure_class == "process_error"
    assert overflow_channels == ()
    assert attempt.record["failure_class"] == "process_error"
    assert attempt.record["usage_unavailable"] is True
    assert all(
        attempt.record[name] is None
        for name in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        )
    )
    assert attempt.events_bytes == events


def test_timeout_with_zero_records_remains_a_timeout(tmp_path: Path) -> None:
    attempt, failure_class, _overflow_channels = _project_attempt_v1(
        _evidence(
            tmp_path,
            events=b"",
            mechanical_outcome="timeout",
            exit_code=0x475A0001,
        )
    )

    assert failure_class == "timeout"
    assert attempt.record["failure_class"] == "timeout"
    assert attempt.record["usage_unavailable"] is True


def test_human_provider_error_text_never_creates_a_transient_class(
    tmp_path: Path,
) -> None:
    events = _json_line(
        {
            "type": "turn.failed",
            "error": {"message": "HTTP 429 rate limit; retry this request"},
        }
    )

    attempt, failure_class, _overflow_channels = _project_attempt_v1(
        _evidence(
            tmp_path,
            events=events,
            mechanical_outcome="provider_or_process_exit",
            exit_code=1,
        )
    )

    assert failure_class == "process_error"
    assert attempt.record["failure_class"] == "process_error"


def test_exact_cap_skips_usage_projection_without_decoding(tmp_path: Path) -> None:
    completed = (
        b'{"type":"turn.completed","usage":'
        b'{"input_tokens":1,"cached_input_tokens":2,'
        b'"output_tokens":3,"reasoning_output_tokens":4}}'
    )
    events = completed + (b" " * (_EVENTS_CAP - len(completed) - 1)) + b"\n"
    attempt, failure_class, overflow_channels = _project_attempt_v1(
        _evidence(
            tmp_path,
            events=events,
        )
    )

    assert failure_class is None
    assert overflow_channels == ()
    assert attempt.record["usage_unavailable"] is True
    assert attempt.events_bytes == events


@pytest.mark.parametrize(
    ("events_overflow", "final_overflow", "expected_channels"),
    (
        (True, False, ("events",)),
        (False, True, ("final_message",)),
        (True, True, ("events", "final_message")),
    ),
)
def test_capture_overflow_retains_prefix_and_has_highest_priority(
    tmp_path: Path,
    events_overflow: bool,
    final_overflow: bool,
    expected_channels: tuple[str, ...],
) -> None:
    events = b"events-prefix"
    final = b"final-prefix"
    attempt, failure_class, overflow_channels = _project_attempt_v1(
        _evidence(
            tmp_path,
            events=events,
            final=final,
            mechanical_outcome="interrupted",
            exit_code=0x475A0001,
            events_overflow=events_overflow,
            final_overflow=final_overflow,
        )
    )

    assert failure_class == "process_error"
    assert overflow_channels == expected_channels
    assert attempt.events_bytes == events
    assert attempt.final_message_bytes == final


@pytest.mark.parametrize(
    (
        "classification_ready_ns",
        "cancel_observed_ns",
        "expected_failure_class",
        "expected_elapsed_ms",
    ),
    (
        (1_700_000_000, None, None, 700),
        (1_800_000_000, 1_700_000_000, "interrupted", 800),
        (1_810_000_000, None, "timeout", 810),
        (1_900_000_000, 1_820_000_000, "timeout", 900),
    ),
)
def test_attempt_classification_includes_local_event_and_usage_projection_time(
    tmp_path: Path,
    classification_ready_ns: int,
    cancel_observed_ns: int | None,
    expected_failure_class: str | None,
    expected_elapsed_ms: int,
) -> None:
    evidence = _evidence(
        tmp_path,
        events=_json_line({"type": "turn.completed", "usage": {}}),
    )

    attempt, failure_class, _overflow_channels = _project_attempt_v1(
        evidence,
        classification_ready_monotonic_ns=classification_ready_ns,
        cancellation=_FixedCancellationV1(cancel_observed_ns),
    )

    assert failure_class == expected_failure_class
    assert attempt.record["failure_class"] == expected_failure_class
    assert attempt.record["elapsed_ms"] == expected_elapsed_ms
