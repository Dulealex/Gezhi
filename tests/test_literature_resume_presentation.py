from __future__ import annotations

import json

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
