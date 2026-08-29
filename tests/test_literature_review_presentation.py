from __future__ import annotations

import copy
import json

import pytest

from gezhi import _literature_commands as commands
from gezhi._literature_commands import (
    ReviewReceiptV1,
    build_review_human_buffer_v1,
    build_review_json_buffer_v1,
)

CANDIDATE_ID = "cand_aaaaaaaaaaaaaaaaaaaaaaaa"
HANDOFF_ID = "hnd_6516df7f17eab620795d28ee"
PAYLOAD_SHA256 = "a" * 64
WORK_ID = "wrk_123e4567-e89b-42d3-a456-426614174000"

SUCCESS_RESULT = {
    "candidate_id": CANDIDATE_ID,
    "decision_disposition": "created",
    "handoff_action": "accept",
    "handoff_id": HANDOFF_ID,
    "handoff_status": "committed",
    "import_status": "applied",
    "intake_status": "active",
    "payload_sha256": PAYLOAD_SHA256,
    "review_revision": 1,
    "review_status": "accepted",
    "schema_version": "gezhi.literature_review_result.v1",
    "work_id": WORK_ID,
}

HANDOFF_PENDING_RESULT = {
    **SUCCESS_RESULT,
    "handoff_status": "pending",
    "import_status": "pending",
    "intake_status": None,
}

IMPORT_PENDING_RESULT = {
    **SUCCESS_RESULT,
    "handoff_status": "committed",
    "import_status": "pending",
    "intake_status": None,
}

NO_ACTION_RESULT = {
    **SUCCESS_RESULT,
    "handoff_action": "none",
    "handoff_id": None,
    "handoff_status": "not_required",
    "import_status": "not_required",
    "intake_status": None,
    "review_status": "rejected",
}

NO_ACTION_PENDING_RESULT = {
    **NO_ACTION_RESULT,
    "handoff_status": "pending",
}

WITHDRAW_RESULT = {
    **SUCCESS_RESULT,
    "candidate_id": "cand_3a421e895f79e2c167e2ef4b",
    "handoff_action": "withdraw",
    "handoff_id": "hnd_39cf03ad1f8fd432e3b83a5b",
    "intake_status": "withdrawn",
    "payload_sha256": (
        "3a421e895f79e2c167e2ef4b4f42ece44839ca487c11e6659870904f268eabf1"
    ),
    "review_revision": 2,
    "review_status": "rejected",
}


class _ForcedProcessExit(RuntimeError):
    pass


def _receipt(
    outcome: str,
    result: dict[str, object] | None,
    code: str | None = None,
    context: dict[str, object] | None = None,
) -> ReviewReceiptV1:
    return ReviewReceiptV1(
        outcome=outcome,  # type: ignore[arg-type]
        result=result,
        diagnostic=(
            None
            if code is None
            else {"code": code, "context": {} if context is None else context}
        ),
    )


def test_review_success_has_frozen_json_and_human_witnesses() -> None:
    receipt = _receipt("succeeded", SUCCESS_RESULT)

    assert (
        build_review_json_buffer_v1(receipt)
        == (
            '{"command":"literature.review","diagnostics":[],"outcome":"succeeded",'
            '"result":{"candidate_id":"cand_aaaaaaaaaaaaaaaaaaaaaaaa",'
            '"decision_disposition":"created","handoff_action":"accept",'
            '"handoff_id":"hnd_6516df7f17eab620795d28ee",'
            '"handoff_status":"committed","import_status":"applied",'
            '"intake_status":"active","payload_sha256":"'
            + PAYLOAD_SHA256
            + '","review_revision":1,"review_status":"accepted",'
            '"schema_version":"gezhi.literature_review_result.v1",'
            '"work_id":"wrk_123e4567-e89b-42d3-a456-426614174000"},'
            '"schema_version":"gezhi.cli_result.v1"}\n'
        ).encode()
    )
    assert (
        build_review_human_buffer_v1(receipt)
        == (
            "Literature review：完成\n"
            "Candidate ID：cand_aaaaaaaaaaaaaaaaaaaaaaaa\n"
            "Decision 处理结果：created\n"
            "Handoff 动作：accept\n"
            "Handoff ID：hnd_6516df7f17eab620795d28ee\n"
            "Handoff 状态：committed\n"
            "Import 状态：applied\n"
            "Intake 状态：active\n"
            f"Payload SHA-256：{PAYLOAD_SHA256}\n"
            "Review revision：1\n"
            "Review 状态：accepted\n"
            "Schema：gezhi.literature_review_result.v1\n"
            "Work ID：wrk_123e4567-e89b-42d3-a456-426614174000\n"
            "下一步：运行 gezhi literature resume "
            "wrk_123e4567-e89b-42d3-a456-426614174000\n"
        ).encode()
    )


def test_review_import_blocked_keeps_non_null_partial_receipt() -> None:
    receipt = _receipt(
        "blocked",
        IMPORT_PENDING_RESULT,
        "literature.review.import_blocked.v1",
    )

    assert json.loads(build_review_json_buffer_v1(receipt)) == {
        "command": "literature.review",
        "diagnostics": [receipt.diagnostic],
        "outcome": "blocked",
        "result": IMPORT_PENDING_RESULT,
        "schema_version": "gezhi.cli_result.v1",
    }
    assert build_review_human_buffer_v1(receipt).decode().splitlines() == [
        "Literature review：已阻塞",
        "Candidate ID：cand_aaaaaaaaaaaaaaaaaaaaaaaa",
        "Decision 处理结果：created",
        "Handoff 动作：accept",
        "Handoff ID：hnd_6516df7f17eab620795d28ee",
        "Handoff 状态：committed",
        "Import 状态：pending",
        "Intake 状态：无",
        f"Payload SHA-256：{PAYLOAD_SHA256}",
        "Review revision：1",
        "Review 状态：accepted",
        "Schema：gezhi.literature_review_result.v1",
        "Work ID：wrk_123e4567-e89b-42d3-a456-426614174000",
        "原因：Review Decision 与 Handoff 已保存，但 Knowledge import 尚未完成",
        "下一步：修复 Knowledge 前置条件后用相同 action 重试或运行 literature resume",
    ]


def test_review_candidate_invalid_has_null_result_and_frozen_human() -> None:
    receipt = _receipt(
        "blocked",
        None,
        "literature.review.candidate_invalid.v1",
    )

    assert build_review_json_buffer_v1(receipt) == (
        b'{"command":"literature.review","diagnostics":['
        b'{"code":"literature.review.candidate_invalid.v1","context":{}}],'
        b'"outcome":"blocked","result":null,'
        b'"schema_version":"gezhi.cli_result.v1"}\n'
    )
    assert (
        build_review_human_buffer_v1(receipt)
        == (
            "Literature review：已阻塞\n"
            "原因：Candidate ID 格式无效\n"
            "下一步：使用完整规范 Candidate ID 重试\n"
        ).encode()
    )


def test_review_partial_result_uses_the_frozen_field_order() -> None:
    receipt = _receipt(
        "blocked",
        IMPORT_PENDING_RESULT,
        "literature.review.import_blocked.v1",
    )

    labels = [
        line.split("：", 1)[0]
        for line in build_review_human_buffer_v1(receipt).decode().splitlines()[1:13]
    ]

    assert labels == [
        "Candidate ID",
        "Decision 处理结果",
        "Handoff 动作",
        "Handoff ID",
        "Handoff 状态",
        "Import 状态",
        "Intake 状态",
        "Payload SHA-256",
        "Review revision",
        "Review 状态",
        "Schema",
        "Work ID",
    ]


@pytest.mark.parametrize(
    "result",
    [SUCCESS_RESULT, NO_ACTION_RESULT, WITHDRAW_RESULT],
    ids=["accept", "none", "withdraw"],
)
def test_review_success_accepts_each_frozen_handoff_action_matrix(
    result: dict[str, object],
) -> None:
    document = json.loads(build_review_json_buffer_v1(_receipt("succeeded", result)))

    assert document["result"] == result


@pytest.mark.parametrize(
    "result_patch",
    [
        {"candidate_id": "cand_AAAAAAAAAAAAAAAAAAAAAAAA"},
        {"payload_sha256": "A" * 64},
        {"work_id": "wrk_not-a-uuid"},
        {"review_revision": True},
        {"review_revision": 0},
        {"review_revision": 9_223_372_036_854_775_808},
        {"decision_disposition": "updated"},
        {"review_status": "pending"},
        {"handoff_id": "hnd_000000000000000000000000"},
        {"handoff_action": "none"},
        {"handoff_status": "pending"},
        {"import_status": "pending", "intake_status": "active"},
        {"intake_status": "withdrawn"},
    ],
)
def test_review_result_rejects_invalid_types_identities_and_state_matrix(
    result_patch: dict[str, object],
) -> None:
    result = copy.deepcopy(SUCCESS_RESULT)
    result.update(result_patch)

    with pytest.raises((TypeError, ValueError)):
        build_review_json_buffer_v1(_receipt("succeeded", result))


def test_review_result_rejects_missing_and_additional_fields() -> None:
    missing = copy.deepcopy(SUCCESS_RESULT)
    del missing["payload_sha256"]
    additional = {**SUCCESS_RESULT, "note": None}

    for result in (missing, additional):
        with pytest.raises((TypeError, ValueError)):
            build_review_json_buffer_v1(_receipt("succeeded", result))


@pytest.mark.parametrize(
    ("outcome", "code", "context", "result"),
    [
        ("blocked", "literature.review.configuration_invalid.v1", {}, None),
        (
            "blocked",
            "literature.review.data_root_unsafe.v1",
            {"data_root": "literature"},
            None,
        ),
        (
            "blocked",
            "literature.review.data_root_unavailable.v1",
            {"data_root": "knowledge"},
            IMPORT_PENDING_RESULT,
        ),
        ("blocked", "literature.review.candidate_invalid.v1", {}, None),
        ("blocked", "literature.review.candidate_not_found.v1", {}, None),
        ("blocked", "literature.review.work_busy.v1", {}, None),
        (
            "blocked",
            "literature.review.handoff_blocked.v1",
            {},
            HANDOFF_PENDING_RESULT,
        ),
        (
            "blocked",
            "literature.review.import_blocked.v1",
            {},
            IMPORT_PENDING_RESULT,
        ),
        (
            "failed",
            "literature.review.data_root_integrity_lost.v1",
            {"data_root": "literature"},
            None,
        ),
        (
            "failed",
            "literature.review.data_root_integrity_lost.v1",
            {"data_root": "knowledge"},
            IMPORT_PENDING_RESULT,
        ),
        (
            "failed",
            "literature.review.candidate_integrity_lost.v1",
            {},
            None,
        ),
        ("failed", "literature.review.review_state_invalid.v1", {}, None),
        ("failed", "literature.review.review_commit_failed.v1", {}, None),
        (
            "failed",
            "literature.review.handoff_failed.v1",
            {},
            HANDOFF_PENDING_RESULT,
        ),
        (
            "failed",
            "literature.review.handoff_failed.v1",
            {},
            NO_ACTION_PENDING_RESULT,
        ),
        (
            "failed",
            "literature.review.import_failed.v1",
            {},
            IMPORT_PENDING_RESULT,
        ),
    ],
)
def test_review_diagnostic_union_accepts_only_its_frozen_result_presence(
    outcome: str,
    code: str,
    context: dict[str, object],
    result: dict[str, object] | None,
) -> None:
    document = json.loads(
        build_review_json_buffer_v1(_receipt(outcome, result, code, context))
    )

    assert document["outcome"] == outcome
    assert document["result"] == result


@pytest.mark.parametrize(
    ("outcome", "code", "context", "result"),
    [
        (
            "failed",
            "literature.review.candidate_invalid.v1",
            {},
            None,
        ),
        (
            "blocked",
            "literature.review.candidate_invalid.v1",
            {},
            IMPORT_PENDING_RESULT,
        ),
        ("blocked", "literature.review.import_blocked.v1", {}, None),
        (
            "blocked",
            "literature.review.handoff_blocked.v1",
            {},
            IMPORT_PENDING_RESULT,
        ),
        (
            "blocked",
            "literature.review.import_blocked.v1",
            {},
            HANDOFF_PENDING_RESULT,
        ),
        (
            "blocked",
            "literature.review.data_root_unavailable.v1",
            {"data_root": "literature"},
            IMPORT_PENDING_RESULT,
        ),
        (
            "blocked",
            "literature.review.data_root_unavailable.v1",
            {"data_root": "knowledge"},
            None,
        ),
        (
            "failed",
            "literature.review.data_root_integrity_lost.v1",
            {"data_root": "knowledge"},
            None,
        ),
        (
            "blocked",
            "literature.review.candidate_not_found.v1",
            {"extra": "forbidden"},
            None,
        ),
        (
            "blocked",
            "literature.review.data_root_unsafe.v1",
            {"data_root": "other"},
            None,
        ),
    ],
)
def test_review_receipt_rejects_outcome_context_and_presence_contradictions(
    outcome: str,
    code: str,
    context: dict[str, object],
    result: dict[str, object] | None,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        build_review_json_buffer_v1(_receipt(outcome, result, code, context))


@pytest.mark.parametrize(
    ("outcome", "code", "context", "result", "reason", "next_action"),
    [
        (
            "blocked",
            "literature.review.configuration_invalid.v1",
            {},
            None,
            "配置无效",
            "修正格致配置后重新运行 review",
        ),
        (
            "blocked",
            "literature.review.data_root_unsafe.v1",
            {"data_root": "literature"},
            None,
            "literature 数据目录不安全",
            "移除不受支持的 namespace 或路径别名后用相同 action 重试",
        ),
        (
            "blocked",
            "literature.review.data_root_unavailable.v1",
            {"data_root": "knowledge"},
            IMPORT_PENDING_RESULT,
            "knowledge 数据目录不可用",
            "修复该 Context 数据目录后用相同 action 重试",
        ),
        (
            "blocked",
            "literature.review.candidate_invalid.v1",
            {},
            None,
            "Candidate ID 格式无效",
            "使用完整规范 Candidate ID 重试",
        ),
        (
            "blocked",
            "literature.review.candidate_not_found.v1",
            {},
            None,
            "指定 Candidate 不存在",
            "核对 Candidate ID 后重试",
        ),
        (
            "blocked",
            "literature.review.work_busy.v1",
            {},
            None,
            "Candidate 所属 Work 正由另一个写流程处理",
            "等待该流程结束后重试",
        ),
        (
            "blocked",
            "literature.review.handoff_blocked.v1",
            {},
            HANDOFF_PENDING_RESULT,
            "Review Decision 已保存，但 Handoff 尚未完成",
            "用相同 action 重试或运行 literature resume",
        ),
        (
            "blocked",
            "literature.review.import_blocked.v1",
            {},
            IMPORT_PENDING_RESULT,
            "Review Decision 与 Handoff 已保存，但 Knowledge import 尚未完成",
            "修复 Knowledge 前置条件后用相同 action 重试或运行 literature resume",
        ),
        (
            "failed",
            "literature.review.data_root_integrity_lost.v1",
            {"data_root": "literature"},
            None,
            "literature 数据目录身份在执行中失去可信性",
            "停止写入并运行 gezhi doctor",
        ),
        (
            "failed",
            "literature.review.candidate_integrity_lost.v1",
            {},
            None,
            "Candidate 资产完整性失效",
            (
                "保留 Candidate 与 Evidence 资产，运行 gezhi status 并检查 "
                "ID、hash、canonical bytes、provenance、Evidence、payload、"
                "collision 与 asset 完整性"
            ),
        ),
        (
            "failed",
            "literature.review.review_state_invalid.v1",
            {},
            None,
            "Candidate Review 历史无效",
            "保留审核资产并检查 revision 与 payload identity",
        ),
        (
            "failed",
            "literature.review.review_commit_failed.v1",
            {},
            None,
            "Review Decision 提交失败",
            "保持相同 Candidate 与 action 重试",
        ),
        (
            "failed",
            "literature.review.handoff_failed.v1",
            {},
            HANDOFF_PENDING_RESULT,
            "Review Decision 已保存，但 Handoff 失败",
            (
                "保留 Decision 与 Handoff 资产，运行 gezhi status 检查 Handoff "
                "完整性、协议、revision 与提交状态；修复确定原因后以同一 "
                "identity 续行"
            ),
        ),
        (
            "failed",
            "literature.review.import_failed.v1",
            {},
            IMPORT_PENDING_RESULT,
            "Review Decision 与 Handoff 已保存，但 Knowledge import 失败",
            (
                "保留 Decision、Handoff 与 Registry 前置事实，运行 gezhi status "
                "检查 KnowledgeIntake/Registry 完整性、协议、revision、commit "
                "与 conflict；修复确定原因后以同一 identity 续行"
            ),
        ),
    ],
)
def test_every_review_primary_has_its_frozen_human_catalog_entry(
    outcome: str,
    code: str,
    context: dict[str, object],
    result: dict[str, object] | None,
    reason: str,
    next_action: str,
) -> None:
    receipt = _receipt(outcome, result, code, context)

    assert build_review_human_buffer_v1(receipt).decode().splitlines()[-2:] == [
        f"原因：{reason}",
        f"下一步：{next_action}",
    ]


def test_review_json_and_human_buffers_enforce_32_kib_inclusive_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _receipt("succeeded", SUCCESS_RESULT)
    json_size = len(build_review_json_buffer_v1(receipt))
    human_size = len(build_review_human_buffer_v1(receipt))

    monkeypatch.setattr(commands, "_LITERATURE_OUTPUT_CAP", json_size)
    assert len(build_review_json_buffer_v1(receipt)) == json_size

    monkeypatch.setattr(commands, "_LITERATURE_OUTPUT_CAP", json_size - 1)
    with pytest.raises(ValueError, match="32 KiB"):
        build_review_json_buffer_v1(receipt)

    monkeypatch.setattr(commands, "_LITERATURE_OUTPUT_CAP", human_size)
    assert len(build_review_human_buffer_v1(receipt)) == human_size

    monkeypatch.setattr(commands, "_LITERATURE_OUTPUT_CAP", human_size - 1)
    with pytest.raises(ValueError, match="32 KiB"):
        build_review_human_buffer_v1(receipt)


@pytest.mark.parametrize("json_output", [False, True])
def test_review_sealing_failure_hard_stops_without_fallback_output(
    monkeypatch: pytest.MonkeyPatch,
    json_output: bool,
) -> None:
    receipt = _receipt("succeeded", SUCCESS_RESULT)
    monkeypatch.setattr(commands, "_LITERATURE_OUTPUT_CAP", 1)
    monkeypatch.setattr(
        commands,
        "write_operations_stdout",
        lambda _buffer: pytest.fail("failed seal must not write stdout"),
    )

    def forced_exit(code: int) -> None:
        raise _ForcedProcessExit(code)

    monkeypatch.setattr(commands.os, "_exit", forced_exit)

    with pytest.raises(_ForcedProcessExit, match="1"):
        commands._present_review(receipt, json_output=json_output)
