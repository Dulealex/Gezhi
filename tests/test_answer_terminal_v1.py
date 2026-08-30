from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from gezhi import _answer_terminal as terminal


def _canonical_json_file(value: object) -> bytes:
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


def _succeeded_request_with_timeout_attempt() -> terminal.AnswerPublishRequestV1:
    retrieval_view_bytes = _canonical_json_file(
        {
            "candidate_count": 1,
            "schema_version": "gezhi.retrieval_view.v1",
        }
    )
    retrieval_audit_bytes = _canonical_json_file(
        {
            "retrieval_view_measurement": {
                "byte_length": len(retrieval_view_bytes),
                "limit_bytes": 262_144,
                "sha256": hashlib.sha256(retrieval_view_bytes).hexdigest(),
                "status": "within_limit",
            },
            "schema_version": "gezhi.retrieval_audit.v1",
        }
    )
    timestamp = "2026-08-31T12:00:00.000Z"
    return terminal.AnswerPublishRequestV1(
        answer_id="ans_00000000-0000-4000-8000-000000000000",
        started_at=timestamp,
        started_monotonic_ns=1,
        provenance={
            "codex_cli_version": "0.146.0",
            "git": {"revision": "0" * 40, "state": "clean"},
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "role_version": "knowledge_answerer_v1",
        },
        effective_config_bytes=_canonical_json_file(
            {
                "attempt_timeout_ms": 1_800_000,
                "attempt_window_limit_ms": 5_700_000,
                "retry_backoff_schedule_ms": [10_000, 30_000],
                "schema_version": "gezhi.knowledge_answerer_effective_config.v1",
            }
        ),
        question_bytes=_canonical_json_file({"schema_version": "gezhi.question.v1"}),
        retrieval_query_bytes=_canonical_json_file(
            {"schema_version": "gezhi.retrieval_query.v1"}
        ),
        retrieval_audit_bytes=retrieval_audit_bytes,
        retrieval_view_bytes=retrieval_view_bytes,
        prompt_bytes=b"prompt\n",
        schema_bytes=_canonical_json_file(
            {"$id": ("https://gezhi.local/schemas/answer-output-v1.schema.json")}
        ),
        attempts=(
            terminal.AnswerAttemptPublishV1(
                record={
                    "cached_input_tokens": None,
                    "elapsed_ms": 1,
                    "exit_code": 0x475A0001,
                    "failure_class": "timeout",
                    "finished_at": timestamp,
                    "input_tokens": None,
                    "output_tokens": None,
                    "reasoning_output_tokens": None,
                    "started_at": timestamp,
                    "usage_unavailable": True,
                },
                events_bytes=b"",
                final_message_bytes=b"",
            ),
        ),
        answer_output_bytes=_canonical_json_file(
            {"schema_version": "gezhi.answer_output.v1"}
        ),
        answer_markdown_bytes=b"answer\n",
    )


def _request_with_terminal_matrix(
    *,
    status: str,
    error: dict[str, object] | None,
    failure_classes: tuple[str | None, ...],
) -> terminal.AnswerPublishRequestV1:
    base = _succeeded_request_with_timeout_attempt()
    prototype = base.attempts[0]
    attempts = []
    for failure_class in failure_classes:
        record = dict(prototype.record)
        record["failure_class"] = failure_class
        record["exit_code"] = 0 if failure_class is None else 0x475A0001
        attempts.append(replace(prototype, record=record))
    succeeded = status == "succeeded"
    return replace(
        base,
        status=status,  # type: ignore[arg-type]
        error=error,
        attempts=tuple(attempts),
        answer_output_bytes=base.answer_output_bytes if succeeded else None,
        answer_markdown_bytes=base.answer_markdown_bytes if succeeded else None,
    )


def test_terminal_writer_rejects_success_with_a_timeout_attempt() -> None:
    request = _succeeded_request_with_timeout_attempt()

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="terminal matrix",
    ):
        terminal._validate_request(request)


@pytest.mark.parametrize(
    ("status", "error", "failure_classes"),
    (
        ("succeeded", None, (None,)),
        ("succeeded", None, ("timeout", None)),
        (
            "blocked",
            {"code": "codex_timeout_exhausted", "stage": "synthesis"},
            ("timeout", "timeout"),
        ),
        (
            "failed",
            {"code": "codex_process_failed", "stage": "synthesis"},
            ("timeout", "process_error"),
        ),
        (
            "failed",
            {"code": "answer_output_invalid", "stage": "validation"},
            ("timeout", None),
        ),
        ("interrupted", None, ("timeout", "interrupted")),
        ("interrupted", None, ("timeout", None)),
    ),
    ids=(
        "success",
        "retry-success",
        "timeout-exhaustion",
        "process-failure",
        "validation-failure",
        "active-interrupt",
        "post-synthesis-interrupt",
    ),
)
def test_terminal_writer_accepts_closed_attempt_matrices(
    status: str,
    error: dict[str, object] | None,
    failure_classes: tuple[str | None, ...],
) -> None:
    request = _request_with_terminal_matrix(
        status=status,
        error=error,
        failure_classes=failure_classes,
    )

    terminal._validate_request(request)


@pytest.mark.parametrize(
    ("status", "error", "failure_classes"),
    (
        (
            "blocked",
            {"code": "codex_timeout_exhausted", "stage": "synthesis"},
            ("timeout", None),
        ),
        (
            "failed",
            {"code": "codex_process_failed", "stage": "synthesis"},
            ("timeout",),
        ),
        (
            "failed",
            {"code": "answer_output_invalid", "stage": "validation"},
            ("process_error",),
        ),
        ("interrupted", None, ("process_error",)),
        ("succeeded", None, (None, "timeout")),
        (
            "blocked",
            {"code": "codex_timeout_exhausted", "stage": "synthesis"},
            (),
        ),
        (
            "blocked",
            {"code": "codex_network_exhausted", "stage": "synthesis"},
            ("network",),
        ),
    ),
    ids=(
        "exhaustion-with-success",
        "process-failure-with-timeout",
        "validation-with-process-error",
        "interrupt-with-process-error",
        "failure-after-success",
        "exhaustion-without-attempt",
        "legacy-writer-class",
    ),
)
def test_terminal_writer_rejects_cross_field_attempt_mismatches(
    status: str,
    error: dict[str, object] | None,
    failure_classes: tuple[str | None, ...],
) -> None:
    request = _request_with_terminal_matrix(
        status=status,
        error=error,
        failure_classes=failure_classes,
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="terminal matrix",
    ):
        terminal._validate_request(request)
