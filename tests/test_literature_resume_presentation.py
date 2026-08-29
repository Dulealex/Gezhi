from __future__ import annotations

import copy
import json

import pytest

from gezhi import _literature_commands as commands
from gezhi._literature_commands import (
    ResumeReceiptV1,
    build_resume_human_buffer_v1,
    build_resume_json_buffer_v1,
)

RESULT = {
    "active_source_id": "src_0123456789abcdef01234567",
    "advanced_stages": ["ocr"],
    "pending_candidate_ids": [],
    "pipeline_complete": False,
    "schema_version": "gezhi.literature_resume_result.v1",
    "start_stage": "ocr",
    "stop_stage": "canonicalize",
    "work_id": "wrk_123e4567-e89b-42d3-a456-426614174000",
}

CANDIDATE_ID = "cand_0123456789abcdef01234567"


def _stage_result(
    stage: str,
    *,
    start_stage: str | None = None,
    advanced_stages: list[str] | None = None,
    pending_candidate_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "active_source_id": RESULT["active_source_id"],
        "advanced_stages": [] if advanced_stages is None else advanced_stages,
        "pending_candidate_ids": (
            [] if pending_candidate_ids is None else pending_candidate_ids
        ),
        "pipeline_complete": False,
        "schema_version": "gezhi.literature_resume_result.v1",
        "start_stage": stage if start_stage is None else start_stage,
        "stop_stage": stage,
        "work_id": RESULT["work_id"],
    }


def test_resume_stage_blocked_has_exact_json_and_human_receipts() -> None:
    receipt = ResumeReceiptV1(
        outcome="blocked",
        result=RESULT,
        diagnostic={
            "code": "literature.resume.stage_blocked.v1",
            "context": {
                "reason": "canonical_prerequisite_unavailable",
                "stage": "canonicalize",
            },
        },
    )

    assert json.loads(build_resume_json_buffer_v1(receipt)) == {
        "command": "literature.resume",
        "diagnostics": [receipt.diagnostic],
        "outcome": "blocked",
        "result": RESULT,
        "schema_version": "gezhi.cli_result.v1",
    }
    assert build_resume_human_buffer_v1(receipt).decode().splitlines() == [
        "Literature resume：已阻塞",
        "Active Source ID：src_0123456789abcdef01234567",
        "本次推进阶段：",
        "  - ocr",
        "待审核 Candidate：[]",
        "管线已完成：否",
        "Schema：gezhi.literature_resume_result.v1",
        "开始阶段：ocr",
        "停止阶段：canonicalize",
        "Work ID：wrk_123e4567-e89b-42d3-a456-426614174000",
        "原因：canonicalize 阶段已阻塞（canonical_prerequisite_unavailable）",
        "下一步：修复该前置条件后重新运行 resume；awaiting_review 时对列出的 Candidate 显式 review",
    ]


def test_resume_null_result_primary_has_only_catalog_reason_and_next_action() -> None:
    receipt = ResumeReceiptV1(
        outcome="blocked",
        result=None,
        diagnostic={
            "code": "literature.resume.work_invalid.v1",
            "context": {},
        },
    )

    assert build_resume_human_buffer_v1(receipt).decode().splitlines() == [
        "Literature resume：已阻塞",
        "原因：Work ID 格式无效",
        "下一步：使用完整规范 Work ID 重试",
    ]


def test_resume_stage_matrix_has_13_blocked_and_25_failed_sealed_witnesses() -> None:
    matrices = (
        (
            "blocked",
            "literature.resume.stage_blocked.v1",
            commands._RESUME_STAGE_BLOCKED,
            13,
        ),
        (
            "failed",
            "literature.resume.stage_failed.v1",
            commands._RESUME_STAGE_FAILED,
            25,
        ),
    )
    for outcome, code, matrix, expected_count in matrices:
        pairs = [
            (stage, reason) for stage, reasons in matrix.items() for reason in reasons
        ]
        assert len(pairs) == expected_count
        for stage, reason in pairs:
            pending = (
                [CANDIDATE_ID]
                if reason == "awaiting_review"
                or stage in {"handoff", "knowledge_import"}
                else []
            )
            result = _stage_result(
                stage,
                start_stage=(
                    "review" if stage in {"handoff", "knowledge_import"} else stage
                ),
                pending_candidate_ids=pending,
            )
            receipt = ResumeReceiptV1(
                outcome=outcome,  # type: ignore[arg-type]
                result=result,
                diagnostic={
                    "code": code,
                    "context": {"reason": reason, "stage": stage},
                },
            )

            document = json.loads(build_resume_json_buffer_v1(receipt))

            assert document["result"]["stop_stage"] == stage
            assert document["diagnostics"][0]["context"] == {
                "reason": reason,
                "stage": stage,
            }
    read_blocked = set(commands._RESUME_STAGE_BLOCKED["read"])
    assert read_blocked == {
        "reader_prerequisite_unavailable",
        "reader_input_too_large",
        "codex_runtime_unavailable",
        "codex_timeout_exhausted",
    }


def test_awaiting_review_can_follow_successful_authorized_backlog() -> None:
    result = _stage_result(
        "review",
        advanced_stages=["handoff", "knowledge_import"],
        pending_candidate_ids=[CANDIDATE_ID],
    )
    receipt = ResumeReceiptV1(
        outcome="blocked",
        result=result,
        diagnostic={
            "code": "literature.resume.stage_blocked.v1",
            "context": {"reason": "awaiting_review", "stage": "review"},
        },
    )

    assert json.loads(build_resume_json_buffer_v1(receipt))["result"] == result


@pytest.mark.parametrize(
    ("result_patch", "diagnostic"),
    [
        (
            {"stop_stage": "canonicalize"},
            {
                "code": "literature.resume.stage_blocked.v1",
                "context": {
                    "reason": "ocr_runtime_unavailable",
                    "stage": "ocr",
                },
            },
        ),
        (
            {"pending_candidate_ids": []},
            {
                "code": "literature.resume.stage_blocked.v1",
                "context": {"reason": "awaiting_review", "stage": "review"},
            },
        ),
        (
            {"pending_candidate_ids": [CANDIDATE_ID]},
            {
                "code": "literature.resume.stage_blocked.v1",
                "context": {
                    "reason": "canonical_prerequisite_unavailable",
                    "stage": "canonicalize",
                },
            },
        ),
        (
            {"advanced_stages": ["ocr"]},
            {
                "code": "literature.resume.stage_failed.v1",
                "context": {"reason": "commit_failed", "stage": "ocr"},
            },
        ),
        (
            {"advanced_stages": ["ocr"]},
            {
                "code": "literature.resume.stage_failed.v1",
                "context": {"reason": "ocr_failed", "stage": "ocr"},
            },
        ),
        (
            {"start_stage": "canonicalize", "stop_stage": "ocr"},
            {
                "code": "literature.resume.stage_blocked.v1",
                "context": {
                    "reason": "ocr_runtime_unavailable",
                    "stage": "ocr",
                },
            },
        ),
        (
            {
                "advanced_stages": ["ocr"],
                "start_stage": "canonicalize",
                "stop_stage": "read",
            },
            {
                "code": "literature.resume.stage_blocked.v1",
                "context": {
                    "reason": "codex_runtime_unavailable",
                    "stage": "read",
                },
            },
        ),
    ],
)
def test_resume_stage_receipt_rejects_cross_field_contradictions(
    result_patch: dict[str, object],
    diagnostic: dict[str, object],
) -> None:
    stage = str(copy.deepcopy(diagnostic)["context"]["stage"])  # type: ignore[index]
    result = _stage_result(stage)
    result.update(result_patch)
    receipt = ResumeReceiptV1(
        outcome=(
            "blocked"
            if diagnostic["code"] == "literature.resume.stage_blocked.v1"
            else "failed"
        ),
        result=result,
        diagnostic=diagnostic,
    )

    with pytest.raises((TypeError, ValueError)):
        build_resume_json_buffer_v1(receipt)


@pytest.mark.parametrize(
    ("stage", "reason"),
    [
        ("handoff", "handoff_blocked"),
        ("knowledge_import", "import_blocked"),
    ],
)
def test_backlog_only_stop_accepts_empty_pending_and_actual_start_stage(
    stage: str,
    reason: str,
) -> None:
    result = _stage_result(
        stage,
        start_stage=stage,
        pending_candidate_ids=[],
    )
    receipt = ResumeReceiptV1(
        outcome="blocked",
        result=result,
        diagnostic={
            "code": "literature.resume.stage_blocked.v1",
            "context": {"reason": reason, "stage": stage},
        },
    )

    assert json.loads(build_resume_json_buffer_v1(receipt))["result"] == result


def test_awaiting_review_can_follow_a_review_repair_and_authorized_backlog() -> None:
    result = _stage_result(
        "review",
        advanced_stages=["review", "handoff", "knowledge_import"],
        pending_candidate_ids=[CANDIDATE_ID],
    )
    receipt = ResumeReceiptV1(
        outcome="blocked",
        result=result,
        diagnostic={
            "code": "literature.resume.stage_blocked.v1",
            "context": {"reason": "awaiting_review", "stage": "review"},
        },
    )

    assert json.loads(build_resume_json_buffer_v1(receipt))["result"] == result


def test_review_failure_can_preserve_other_proven_pending_candidates() -> None:
    result = _stage_result(
        "review",
        pending_candidate_ids=[CANDIDATE_ID],
    )
    receipt = ResumeReceiptV1(
        outcome="failed",
        result=result,
        diagnostic={
            "code": "literature.resume.stage_failed.v1",
            "context": {
                "reason": "review_state_invalid",
                "stage": "review",
            },
        },
    )

    assert json.loads(build_resume_json_buffer_v1(receipt))["result"] == result


@pytest.mark.parametrize(
    ("stage", "reason", "result_patch"),
    [
        (
            "handoff",
            "handoff_blocked",
            {
                "start_stage": "knowledge_import",
                "pending_candidate_ids": [],
            },
        ),
        (
            "knowledge_import",
            "import_blocked",
            {
                "advanced_stages": ["knowledge_import"],
                "pending_candidate_ids": [],
            },
        ),
    ],
)
def test_backlog_stop_rejects_impossible_progress(
    stage: str,
    reason: str,
    result_patch: dict[str, object],
) -> None:
    result = _stage_result(stage)
    result.update(result_patch)
    receipt = ResumeReceiptV1(
        outcome="blocked",
        result=result,
        diagnostic={
            "code": "literature.resume.stage_blocked.v1",
            "context": {"reason": reason, "stage": stage},
        },
    )

    with pytest.raises((TypeError, ValueError)):
        build_resume_json_buffer_v1(receipt)


@pytest.mark.parametrize(
    "result_patch",
    [
        {"stop_stage": "handoff"},
        {"advanced_stages": ["knowledge_import"]},
    ],
)
def test_knowledge_root_receipt_requires_unadvanced_knowledge_import_stop(
    result_patch: dict[str, object],
) -> None:
    result = _stage_result("knowledge_import", start_stage="review")
    result.update(result_patch)
    receipt = ResumeReceiptV1(
        outcome="blocked",
        result=result,
        diagnostic={
            "code": "literature.resume.data_root_unavailable.v1",
            "context": {"data_root": "knowledge"},
        },
    )

    with pytest.raises((TypeError, ValueError)):
        build_resume_json_buffer_v1(receipt)
