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
        events_bytes = (
            _canonical_json_file({"type": "turn.completed"})
            if failure_class is None
            else prototype.events_bytes
        )
        attempts.append(replace(prototype, record=record, events_bytes=events_bytes))
    succeeded = status == "succeeded"
    return replace(
        base,
        status=status,  # type: ignore[arg-type]
        error=error,
        attempts=tuple(attempts),
        answer_output_bytes=base.answer_output_bytes if succeeded else None,
        answer_markdown_bytes=base.answer_markdown_bytes if succeeded else None,
    )


def _zero_candidate_request(
    *,
    error: dict[str, object],
) -> terminal.AnswerPublishRequestV1:
    base = _request_with_terminal_matrix(
        status="failed",
        error=error,
        failure_classes=(),
    )
    retrieval_view_bytes = _canonical_json_file(
        {
            "candidate_count": 0,
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
    return replace(
        base,
        retrieval_audit_bytes=retrieval_audit_bytes,
        retrieval_view_bytes=retrieval_view_bytes,
        prompt_bytes=None,
        schema_bytes=None,
    )


def _request_at_root_prefix(
    request: terminal.AnswerPublishRequestV1,
    prefix: int,
) -> terminal.AnswerPublishRequestV1:
    field_names = (
        "effective_config_bytes",
        "question_bytes",
        "retrieval_query_bytes",
        "retrieval_audit_bytes",
        "retrieval_view_bytes",
    )
    changes = {name: None for name in field_names[prefix + 1 :]}
    if prefix < 4:
        changes.update(prompt_bytes=None, schema_bytes=None)
    return replace(request, **changes)


def _request_with_candidate_count(
    request: terminal.AnswerPublishRequestV1,
    candidate_count: int,
) -> terminal.AnswerPublishRequestV1:
    retrieval_view_bytes = _canonical_json_file(
        {
            "candidate_count": candidate_count,
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
    return replace(
        request,
        retrieval_audit_bytes=retrieval_audit_bytes,
        retrieval_view_bytes=retrieval_view_bytes,
    )


def _too_large_retrieval_audit_bytes() -> bytes:
    return _canonical_json_file(
        {
            "retrieval_view_measurement": {
                "byte_length": 262_145,
                "limit_bytes": 262_144,
                "sha256": "0" * 64,
                "status": "too_large",
            },
            "schema_version": "gezhi.retrieval_audit.v1",
        }
    )


def test_terminal_writer_rejects_success_with_a_timeout_attempt() -> None:
    request = _succeeded_request_with_timeout_attempt()

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_runtime_unavailable_before_synthesis_package() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="blocked",
            error={"code": "codex_runtime_unavailable", "stage": "synthesis"},
            failure_classes=(),
        ),
        0,
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_retrieval_query_failure_before_query_asset() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="failed",
            error={"code": "retrieval_query_failed", "stage": "retrieval"},
            failure_classes=(),
        ),
        1,
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_fts_failure_after_retrieval_view() -> None:
    request = _request_with_terminal_matrix(
        status="blocked",
        error={"code": "fts5_unavailable", "stage": "retrieval"},
        failure_classes=(),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_synthesis_input_failure_before_view() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="failed",
            error={"code": "synthesis_input_invalid", "stage": "synthesis"},
            failure_classes=(),
        ),
        0,
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_materialization_failure_after_view() -> None:
    request = _request_with_terminal_matrix(
        status="failed",
        error={
            "code": "retrieval_materialization_failed",
            "stage": "retrieval",
        },
        failure_classes=(),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_accepts_materialization_failure_after_audit() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="failed",
            error={
                "code": "retrieval_materialization_failed",
                "stage": "retrieval",
            },
            failure_classes=(),
        ),
        3,
    )

    terminal._validate_request(request)


@pytest.mark.parametrize(
    "measurement",
    (
        {
            "byte_length": 109,
            "limit_bytes": 262_144,
            "status": "within_limit",
        },
        {
            "byte_length": 109,
            "extra": None,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "within_limit",
        },
        {
            "byte_length": True,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "within_limit",
        },
        {
            "byte_length": -1,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "within_limit",
        },
        {
            "byte_length": 9_223_372_036_854_775_808,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "too_large",
        },
        {
            "byte_length": 109,
            "limit_bytes": True,
            "sha256": "0" * 64,
            "status": "within_limit",
        },
        {
            "byte_length": 109,
            "limit_bytes": 262_144,
            "sha256": "A" * 64,
            "status": "within_limit",
        },
        {
            "byte_length": 109,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "unknown",
        },
        {
            "byte_length": 109,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": [],
        },
        {
            "byte_length": 262_145,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "within_limit",
        },
        {
            "byte_length": 262_144,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "too_large",
        },
    ),
    ids=(
        "missing-field",
        "extra-field",
        "boolean-length",
        "negative-length",
        "length-over-int64",
        "boolean-limit",
        "non-lowercase-hash",
        "unknown-status",
        "non-scalar-status",
        "within-limit-over-cap",
        "too-large-at-cap",
    ),
)
def test_terminal_writer_rejects_invalid_interrupted_p3_measurement(
    measurement: dict[str, object],
) -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="interrupted",
            error=None,
            failure_classes=(),
        ),
        3,
    )
    request = replace(
        request,
        retrieval_audit_bytes=_canonical_json_file(
            {
                "retrieval_view_measurement": measurement,
                "schema_version": "gezhi.retrieval_audit.v1",
            }
        ),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="Retrieval View measurement",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_float_measurement_as_noncanonical_json() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="interrupted",
            error=None,
            failure_classes=(),
        ),
        3,
    )
    request = replace(
        request,
        retrieval_audit_bytes=_canonical_json_file(
            {
                "retrieval_view_measurement": {
                    "byte_length": 109,
                    "limit_bytes": 262_144.0,
                    "sha256": "0" * 64,
                    "status": "within_limit",
                },
                "schema_version": "gezhi.retrieval_audit.v1",
            }
        ),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="Answer JSON asset is invalid",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_materialization_failure_for_over_limit_view() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="failed",
            error={
                "code": "retrieval_materialization_failed",
                "stage": "retrieval",
            },
            failure_classes=(),
        ),
        3,
    )
    request = replace(
        request,
        retrieval_audit_bytes=_too_large_retrieval_audit_bytes(),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="Missing Retrieval View",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_success_with_negative_candidate_count() -> None:
    request = _request_with_candidate_count(
        replace(
            _request_with_terminal_matrix(
                status="succeeded",
                error=None,
                failure_classes=(),
            ),
            prompt_bytes=None,
            schema_bytes=None,
        ),
        -1,
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_interrupt_with_out_of_range_candidates() -> None:
    request = _request_with_candidate_count(
        replace(
            _request_with_terminal_matrix(
                status="interrupted",
                error=None,
                failure_classes=(),
            ),
            prompt_bytes=None,
            schema_bytes=None,
        ),
        13,
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


@pytest.mark.parametrize(
    ("error", "prefix"),
    (
        ({"code": "fts5_unavailable", "stage": "retrieval"}, 2),
        ({"code": "retrieval_query_failed", "stage": "retrieval"}, 2),
        (
            {"code": "retrieval_materialization_failed", "stage": "retrieval"},
            0,
        ),
        (
            {"code": "retrieval_materialization_failed", "stage": "retrieval"},
            1,
        ),
        (
            {"code": "retrieval_materialization_failed", "stage": "retrieval"},
            2,
        ),
        (
            {"code": "retrieval_materialization_failed", "stage": "retrieval"},
            3,
        ),
    ),
    ids=("fts-p2", "query-p2", "materialization-p0", "p1", "p2", "p3"),
)
def test_terminal_writer_accepts_retrieval_terminal_prefixes(
    error: dict[str, object],
    prefix: int,
) -> None:
    status = "blocked" if error["code"] == "fts5_unavailable" else "failed"
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status=status,
            error=error,
            failure_classes=(),
        ),
        prefix,
    )

    terminal._validate_request(request)


def test_terminal_writer_accepts_synthesis_input_failure_without_call_pair() -> None:
    request = replace(
        _request_with_terminal_matrix(
            status="failed",
            error={"code": "synthesis_input_invalid", "stage": "synthesis"},
            failure_classes=(),
        ),
        prompt_bytes=None,
        schema_bytes=None,
    )

    terminal._validate_request(request)


def test_terminal_writer_accepts_runtime_failure_before_first_commitment() -> None:
    request = _request_with_terminal_matrix(
        status="blocked",
        error={"code": "codex_runtime_unavailable", "stage": "synthesis"},
        failure_classes=(),
    )

    terminal._validate_request(request)


def test_terminal_writer_accepts_over_limit_view_at_audit_prefix() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="blocked",
            error={"code": "retrieval_view_too_large", "stage": "retrieval"},
            failure_classes=(),
        ),
        3,
    )
    request = replace(
        request,
        retrieval_audit_bytes=_too_large_retrieval_audit_bytes(),
    )

    terminal._validate_request(request)


def test_terminal_writer_rejects_usage_not_derived_from_attempt_events() -> None:
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    attempt = request.attempts[0]
    record = dict(attempt.record)
    record["input_tokens"] = 7
    request = replace(
        request,
        attempts=(replace(attempt, record=record),),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="attempt usage differs",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_invalid_events_as_retryable_timeout() -> None:
    request = _request_with_terminal_matrix(
        status="blocked",
        error={"code": "codex_timeout_exhausted", "stage": "synthesis"},
        failure_classes=("timeout",),
    )
    attempt = request.attempts[0]
    request = replace(
        request,
        attempts=(replace(attempt, events_bytes=b"not-json\n"),),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="attempt events differ",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_clean_exit_without_completed_event() -> None:
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    attempt = request.attempts[0]
    request = replace(
        request,
        attempts=(replace(attempt, events_bytes=b""),),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="attempt events differ",
    ):
        terminal._validate_request(request)


def test_terminal_writer_accepts_usage_recomputed_from_completed_event() -> None:
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    attempt = request.attempts[0]
    record = dict(attempt.record)
    record.update(
        input_tokens=11,
        cached_input_tokens=7,
        output_tokens=5,
        reasoning_output_tokens=3,
        usage_unavailable=False,
    )
    events_bytes = _canonical_json_file(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 11,
                "cached_input_tokens": 7,
                "output_tokens": 5,
                "reasoning_output_tokens": 3,
            },
        }
    )
    request = replace(
        request,
        attempts=(replace(attempt, record=record, events_bytes=events_bytes),),
    )

    terminal._validate_request(request)


def test_terminal_writer_accepts_invalid_events_as_process_error() -> None:
    request = _request_with_terminal_matrix(
        status="failed",
        error={"code": "codex_process_failed", "stage": "synthesis"},
        failure_classes=("process_error",),
    )
    attempt = request.attempts[0]
    request = replace(
        request,
        attempts=(replace(attempt, events_bytes=b"not-json\n"),),
    )

    terminal._validate_request(request)


def test_terminal_writer_rejects_invalid_exact_cap_events_as_timeout() -> None:
    request = _request_with_terminal_matrix(
        status="blocked",
        error={"code": "codex_timeout_exhausted", "stage": "synthesis"},
        failure_classes=("timeout",),
    )
    attempt = request.attempts[0]
    invalid_prefix = b"not-json\n"
    events_bytes = invalid_prefix + b" " * (16_777_216 - len(invalid_prefix))
    request = replace(
        request,
        attempts=(replace(attempt, events_bytes=events_bytes),),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="attempt events differ",
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
        ("interrupted", None, ("timeout", "timeout", "timeout")),
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
        (
            "blocked",
            {"code": "codex_network_exhausted", "stage": "synthesis"},
            (),
        ),
        (
            "blocked",
            {"code": "codex_rate_limit_exhausted", "stage": "synthesis"},
            (),
        ),
        (
            "blocked",
            {"code": "codex_server_error_exhausted", "stage": "synthesis"},
            (),
        ),
        (
            "blocked",
            {"code": "codex_transient_exhausted", "stage": "synthesis"},
            (),
        ),
    ),
    ids=(
        "exhaustion-with-success",
        "process-failure-with-timeout",
        "validation-with-process-error",
        "interrupt-with-process-error",
        "interrupt-after-three-timeouts",
        "failure-after-success",
        "exhaustion-without-attempt",
        "legacy-writer-class",
        "legacy-network-without-attempt",
        "legacy-rate-limit-without-attempt",
        "legacy-server-error-without-attempt",
        "legacy-transient-without-attempt",
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


@pytest.mark.parametrize(
    "error",
    (
        {"code": "answer_output_invalid", "stage": "validation"},
        {"code": "citation_link_construction_failed", "stage": "rendering"},
        {"code": "answer_rendering_failed", "stage": "rendering"},
    ),
    ids=("validation", "citation-link", "rendering"),
)
def test_terminal_writer_accepts_zero_candidate_post_synthesis_failure(
    error: dict[str, object],
) -> None:
    terminal._validate_request(_zero_candidate_request(error=error))
