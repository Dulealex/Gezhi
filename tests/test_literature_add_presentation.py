from __future__ import annotations

import json

import pytest

from gezhi import _literature_commands as commands
from gezhi._literature_commands import (
    AddReceiptV1,
    build_add_human_buffer_v1,
    build_add_json_buffer_v1,
)

SUCCESS_RESULT = {
    "active_source_changed": True,
    "disposition": "created_work",
    "schema_version": "gezhi.literature_add_result.v1",
    "source_id": "src_0123456789abcdef01234567",
    "source_sha256": (
        "0123456789abcdef0123456789abcdef"
        "0123456789abcdef0123456789abcdef"
    ),
    "work_id": "wrk_123e4567-e89b-42d3-a456-426614174000",
}


class _ForcedProcessExit(RuntimeError):
    pass


def test_add_success_has_exact_json_and_human_receipts() -> None:
    receipt = AddReceiptV1(
        outcome="succeeded",
        result=SUCCESS_RESULT,
        diagnostic=None,
    )

    assert json.loads(build_add_json_buffer_v1(receipt)) == {
        "command": "literature.add",
        "diagnostics": [],
        "outcome": "succeeded",
        "result": SUCCESS_RESULT,
        "schema_version": "gezhi.cli_result.v1",
    }
    assert build_add_json_buffer_v1(receipt).endswith(b"\n")
    assert build_add_human_buffer_v1(receipt) == (
        "Literature add：完成\n"
        "Active Source 已切换：是\n"
        "处理结果：created_work\n"
        "Schema：gezhi.literature_add_result.v1\n"
        "Source ID：src_0123456789abcdef01234567\n"
        "Source SHA-256："
        "0123456789abcdef0123456789abcdef"
        "0123456789abcdef0123456789abcdef\n"
        "Work ID：wrk_123e4567-e89b-42d3-a456-426614174000\n"
        "下一步：运行 gezhi literature resume "
        "wrk_123e4567-e89b-42d3-a456-426614174000\n"
    ).encode()


@pytest.mark.parametrize(
    ("outcome", "code", "context", "expected"),
    [
        (
            "blocked",
            "literature.add.input_invalid.v1",
            {"field": "doi"},
            (
                "Literature add：已阻塞\n"
                "原因：输入字段无效（doi）\n"
                "下一步：修正该输入字段后重新运行 add\n"
            ),
        ),
        (
            "blocked",
            "literature.add.work_busy.v1",
            {},
            (
                "Literature add：已阻塞\n"
                "原因：该 Work 正由另一个写流程处理\n"
                "下一步：等待该流程结束后重试\n"
            ),
        ),
        (
            "failed",
            "literature.add.source_changed.v1",
            {},
            (
                "Literature add：失败\n"
                "原因：PDF 在读取过程中发生变化\n"
                "下一步：固定文件内容后重新运行 add\n"
            ),
        ),
        (
            "failed",
            "literature.add.catalog_projection_failed.v1",
            {},
            (
                "Literature add：失败\n"
                "原因：Literature 索引投影未完成\n"
                "下一步：保持相同输入重新运行 add 以重建投影\n"
            ),
        ),
    ],
)
def test_add_problem_has_one_exact_primary_and_no_result(
    outcome: str,
    code: str,
    context: dict[str, object],
    expected: str,
) -> None:
    receipt = AddReceiptV1(
        outcome=outcome,  # type: ignore[arg-type]
        result=None,
        diagnostic={"code": code, "context": context},
    )

    document = json.loads(build_add_json_buffer_v1(receipt))
    assert document["result"] is None
    assert document["diagnostics"] == [{"code": code, "context": context}]
    assert build_add_human_buffer_v1(receipt) == expected.encode("utf-8")


@pytest.mark.parametrize(
    "field",
    ["pdf_path", "work_id", "doi", "arxiv_id", "citation", "pdf_content"],
)
def test_add_input_invalid_accepts_only_frozen_context_fields(field: str) -> None:
    receipt = AddReceiptV1(
        outcome="blocked",
        result=None,
        diagnostic={
            "code": "literature.add.input_invalid.v1",
            "context": {"field": field},
        },
    )

    assert f"（{field}）".encode() in build_add_human_buffer_v1(receipt)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda: AddReceiptV1("succeeded", None, None),
        lambda: AddReceiptV1("blocked", SUCCESS_RESULT, None),
        lambda: AddReceiptV1("failed", None, None),
        lambda: AddReceiptV1(
            "blocked",
            None,
            {"code": "literature.add.unknown.v1", "context": {}},
        ),
        lambda: AddReceiptV1(
            "blocked",
            None,
            {
                "code": "literature.add.input_invalid.v1",
                "context": {"field": "unknown"},
            },
        ),
    ],
)
def test_add_receipt_rejects_impossible_shapes(mutator: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        build_add_json_buffer_v1(mutator())  # type: ignore[operator]


def test_add_json_and_human_buffers_enforce_32_kib_inclusive_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = AddReceiptV1(
        outcome="succeeded",
        result=SUCCESS_RESULT,
        diagnostic=None,
    )
    json_size = len(build_add_json_buffer_v1(receipt))
    human_size = len(build_add_human_buffer_v1(receipt))

    monkeypatch.setattr(commands, "_LITERATURE_OUTPUT_CAP", json_size)
    assert len(build_add_json_buffer_v1(receipt)) == json_size

    monkeypatch.setattr(commands, "_LITERATURE_OUTPUT_CAP", json_size - 1)
    with pytest.raises(ValueError, match="32 KiB"):
        build_add_json_buffer_v1(receipt)

    monkeypatch.setattr(commands, "_LITERATURE_OUTPUT_CAP", human_size)
    assert len(build_add_human_buffer_v1(receipt)) == human_size

    monkeypatch.setattr(commands, "_LITERATURE_OUTPUT_CAP", human_size - 1)
    with pytest.raises(ValueError, match="32 KiB"):
        build_add_human_buffer_v1(receipt)


@pytest.mark.parametrize(
    ("outcome", "code", "context", "reason", "next_action"),
    [
        (
            "blocked",
            "literature.add.configuration_invalid.v1",
            {},
            "配置无效",
            "修正格致配置后重新运行 add",
        ),
        (
            "blocked",
            "literature.add.data_root_unsafe.v1",
            {},
            "Literature 数据目录不安全",
            "运行 gezhi doctor 并移除不受支持的 namespace 或路径别名",
        ),
        (
            "blocked",
            "literature.add.data_root_unavailable.v1",
            {},
            "Literature 数据目录不可用",
            "运行 gezhi doctor 并修复 Literature 数据目录",
        ),
        (
            "blocked",
            "literature.add.input_invalid.v1",
            {"field": "pdf_content"},
            "输入字段无效（pdf_content）",
            "修正该输入字段后重新运行 add",
        ),
        (
            "blocked",
            "literature.add.identity_intake_busy.v1",
            {},
            "Literature 身份接收正由另一个写流程处理",
            "等待该 root-level 身份接收流程结束后重试",
        ),
        (
            "blocked",
            "literature.add.pdf_unavailable.v1",
            {},
            "PDF 当前不可稳定读取",
            "确认文件存在、可读且未被修改后重试",
        ),
        (
            "blocked",
            "literature.add.work_not_found.v1",
            {},
            "指定 Work 不存在",
            "核对 Work ID 后重试",
        ),
        (
            "blocked",
            "literature.add.identity_review_required.v1",
            {},
            "Work 身份需要人工确认",
            "核对 DOI、arXiv ID 与目标 Work 后显式重试",
        ),
        (
            "blocked",
            "literature.add.identity_conflict.v1",
            {},
            "Work、Source 或身份别名互相冲突",
            "修正冲突的身份输入，不要覆盖既有资产",
        ),
        (
            "blocked",
            "literature.add.work_busy.v1",
            {},
            "该 Work 正由另一个写流程处理",
            "等待该流程结束后重试",
        ),
        (
            "failed",
            "literature.add.data_root_integrity_lost.v1",
            {},
            "Literature 数据目录身份在执行中失去可信性",
            "停止写入并运行 gezhi doctor",
        ),
        (
            "failed",
            "literature.add.source_changed.v1",
            {},
            "PDF 在读取过程中发生变化",
            "固定文件内容后重新运行 add",
        ),
        (
            "failed",
            "literature.add.content_identity_collision.v1",
            {},
            "Source 内容身份发生冲突",
            "保留现有资产并报告冲突，不要覆盖",
        ),
        (
            "failed",
            "literature.add.commit_failed.v1",
            {},
            "Source 或 Active Source 提交失败",
            "保持相同输入重新运行 add 以恢复",
        ),
        (
            "failed",
            "literature.add.catalog_projection_failed.v1",
            {},
            "Literature 索引投影未完成",
            "保持相同输入重新运行 add 以重建投影",
        ),
    ],
)
def test_every_add_primary_has_its_frozen_human_catalog_entry(
    outcome: str,
    code: str,
    context: dict[str, object],
    reason: str,
    next_action: str,
) -> None:
    receipt = AddReceiptV1(
        outcome=outcome,  # type: ignore[arg-type]
        result=None,
        diagnostic={"code": code, "context": context},
    )

    assert build_add_human_buffer_v1(receipt).decode().splitlines()[-2:] == [
        f"原因：{reason}",
        f"下一步：{next_action}",
    ]


@pytest.mark.parametrize("json_output", [False, True])
def test_add_sealing_failure_hard_stops_without_fallback_output(
    monkeypatch: pytest.MonkeyPatch,
    json_output: bool,
) -> None:
    receipt = AddReceiptV1("succeeded", SUCCESS_RESULT, None)
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
        commands._present_add(receipt, json_output=json_output)
