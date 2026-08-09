from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias, cast

from gezhi._configuration import ConfigurationError, resolve_configuration_v1
from gezhi._literature_intake import (
    AddInputInvalidV1,
    AddLocalPdfRequestV1,
    AddStoppedV1,
    add_local_pdf,
)
from gezhi._presentation import operations_json_buffer, write_operations_stdout
from gezhi._windows_data_root import (
    DataRootOpenErrorV1,
    open_validated_data_root_v1,
)

_LITERATURE_OUTPUT_CAP = 32_768
_WORK_ID = re.compile(
    r"^wrk_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SOURCE_ID = re.compile(r"^src_[0-9a-f]{24}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_INPUT_FIELDS = frozenset(
    {"pdf_path", "work_id", "doi", "arxiv_id", "citation", "pdf_content"}
)

AddOutcome: TypeAlias = Literal["succeeded", "blocked", "failed"]

_BLOCKED_CODES = frozenset(
    {
        "literature.add.configuration_invalid.v1",
        "literature.add.data_root_unsafe.v1",
        "literature.add.data_root_unavailable.v1",
        "literature.add.input_invalid.v1",
        "literature.add.identity_intake_busy.v1",
        "literature.add.pdf_unavailable.v1",
        "literature.add.work_not_found.v1",
        "literature.add.identity_review_required.v1",
        "literature.add.identity_conflict.v1",
        "literature.add.work_busy.v1",
    }
)
_FAILED_CODES = frozenset(
    {
        "literature.add.data_root_integrity_lost.v1",
        "literature.add.source_changed.v1",
        "literature.add.content_identity_collision.v1",
        "literature.add.commit_failed.v1",
        "literature.add.catalog_projection_failed.v1",
    }
)
_HUMAN_CATALOG = {
    "literature.add.configuration_invalid.v1": (
        "配置无效",
        "修正格致配置后重新运行 add",
    ),
    "literature.add.data_root_unsafe.v1": (
        "Literature 数据目录不安全",
        "运行 gezhi doctor 并移除不受支持的 namespace 或路径别名",
    ),
    "literature.add.data_root_unavailable.v1": (
        "Literature 数据目录不可用",
        "运行 gezhi doctor 并修复 Literature 数据目录",
    ),
    "literature.add.input_invalid.v1": (
        "输入字段无效（<field>）",
        "修正该输入字段后重新运行 add",
    ),
    "literature.add.identity_intake_busy.v1": (
        "Literature 身份接收正由另一个写流程处理",
        "等待该 root-level 身份接收流程结束后重试",
    ),
    "literature.add.pdf_unavailable.v1": (
        "PDF 当前不可稳定读取",
        "确认文件存在、可读且未被修改后重试",
    ),
    "literature.add.work_not_found.v1": (
        "指定 Work 不存在",
        "核对 Work ID 后重试",
    ),
    "literature.add.identity_review_required.v1": (
        "Work 身份需要人工确认",
        "核对 DOI、arXiv ID 与目标 Work 后显式重试",
    ),
    "literature.add.identity_conflict.v1": (
        "Work、Source 或身份别名互相冲突",
        "修正冲突的身份输入，不要覆盖既有资产",
    ),
    "literature.add.work_busy.v1": (
        "该 Work 正由另一个写流程处理",
        "等待该流程结束后重试",
    ),
    "literature.add.data_root_integrity_lost.v1": (
        "Literature 数据目录身份在执行中失去可信性",
        "停止写入并运行 gezhi doctor",
    ),
    "literature.add.source_changed.v1": (
        "PDF 在读取过程中发生变化",
        "固定文件内容后重新运行 add",
    ),
    "literature.add.content_identity_collision.v1": (
        "Source 内容身份发生冲突",
        "保留现有资产并报告冲突，不要覆盖",
    ),
    "literature.add.commit_failed.v1": (
        "Source 或 Active Source 提交失败",
        "保持相同输入重新运行 add 以恢复",
    ),
    "literature.add.catalog_projection_failed.v1": (
        "Literature 索引投影未完成",
        "保持相同输入重新运行 add 以重建投影",
    ),
}


@dataclass(frozen=True, slots=True)
class AddReceiptV1:
    outcome: AddOutcome
    result: dict[str, object] | None
    diagnostic: dict[str, object] | None


def _validate_result(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != {
        "active_source_changed",
        "disposition",
        "schema_version",
        "source_id",
        "source_sha256",
        "work_id",
    }:
        raise TypeError("Literature add result is invalid")
    result = cast(dict[str, object], value)
    source_id = result["source_id"]
    source_sha256 = result["source_sha256"]
    if (
        type(result["active_source_changed"]) is not bool
        or result["disposition"]
        not in {"created_work", "added_source", "reused_source"}
        or result["schema_version"] != "gezhi.literature_add_result.v1"
        or type(source_id) is not str
        or _SOURCE_ID.fullmatch(source_id) is None
        or type(source_sha256) is not str
        or _SHA256.fullmatch(source_sha256) is None
        or source_id != "src_" + source_sha256[:24]
        or type(result["work_id"]) is not str
        or _WORK_ID.fullmatch(cast(str, result["work_id"])) is None
    ):
        raise ValueError("Literature add result is invalid")
    return result


def _validate_diagnostic(
    outcome: AddOutcome,
    value: object,
) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != {"code", "context"}
        or type(value["code"]) is not str
        or type(value["context"]) is not dict
    ):
        raise TypeError("Literature add diagnostic is invalid")
    diagnostic = cast(dict[str, object], value)
    code = cast(str, diagnostic["code"])
    context = cast(dict[str, object], diagnostic["context"])
    allowed = _BLOCKED_CODES if outcome == "blocked" else _FAILED_CODES
    if code not in allowed:
        raise ValueError("Literature add diagnostic is invalid")
    if code == "literature.add.input_invalid.v1":
        if set(context) != {"field"} or context["field"] not in _INPUT_FIELDS:
            raise ValueError("Literature add diagnostic context is invalid")
    elif context:
        raise ValueError("Literature add diagnostic context is invalid")
    return diagnostic


def _validate_receipt(
    receipt: AddReceiptV1,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    if type(receipt) is not AddReceiptV1 or receipt.outcome not in {
        "succeeded",
        "blocked",
        "failed",
    }:
        raise TypeError("Literature add receipt is invalid")
    if receipt.outcome == "succeeded":
        if receipt.diagnostic is not None:
            raise ValueError("successful Literature add has a diagnostic")
        return _validate_result(receipt.result), None
    if receipt.result is not None or receipt.diagnostic is None:
        raise ValueError("stopped Literature add receipt is invalid")
    return None, _validate_diagnostic(receipt.outcome, receipt.diagnostic)


def build_add_json_buffer_v1(receipt: AddReceiptV1) -> bytes:
    result, diagnostic = _validate_receipt(receipt)
    buffer = operations_json_buffer(
        command="literature.add",
        outcome=receipt.outcome,
        result=result,
        diagnostics=[] if diagnostic is None else [diagnostic],
    )
    if len(buffer) > _LITERATURE_OUTPUT_CAP:
        raise ValueError("Literature add output exceeds 32 KiB")
    return buffer


def _human_value(value: object) -> str:
    if type(value) is bool:
        return "是" if value else "否"
    if value is None:
        return "无"
    if type(value) is str:
        return value
    if type(value) is int:
        return str(value)
    raise TypeError("Literature add Human value is invalid")


def build_add_human_buffer_v1(receipt: AddReceiptV1) -> bytes:
    result, diagnostic = _validate_receipt(receipt)
    first_line = {
        "succeeded": "Literature add：完成",
        "blocked": "Literature add：已阻塞",
        "failed": "Literature add：失败",
    }[receipt.outcome]
    lines = [first_line]
    if result is not None:
        for key, label in (
            ("active_source_changed", "Active Source 已切换"),
            ("disposition", "处理结果"),
            ("schema_version", "Schema"),
            ("source_id", "Source ID"),
            ("source_sha256", "Source SHA-256"),
            ("work_id", "Work ID"),
        ):
            lines.append(f"{label}：{_human_value(result[key])}")
        lines.append(f"下一步：运行 gezhi literature resume {result['work_id']}")
    else:
        if diagnostic is None:
            raise RuntimeError("Literature add diagnostic is unavailable")
        code = cast(str, diagnostic["code"])
        reason, next_action = _HUMAN_CATALOG[code]
        if code == "literature.add.input_invalid.v1":
            context = cast(dict[str, object], diagnostic["context"])
            reason = reason.replace("<field>", cast(str, context["field"]))
        lines.extend((f"原因：{reason}", f"下一步：{next_action}"))
    buffer = ("\n".join(lines) + "\n").encode("utf-8")
    if len(buffer) > _LITERATURE_OUTPUT_CAP:
        raise ValueError("Literature add output exceeds 32 KiB")
    return buffer


def _stopped_receipt(
    outcome: Literal["blocked", "failed"],
    reason: str,
    context: dict[str, object] | None = None,
) -> AddReceiptV1:
    return AddReceiptV1(
        outcome=outcome,
        result=None,
        diagnostic={
            "code": f"literature.add.{reason}.v1",
            "context": {} if context is None else context,
        },
    )


def _present_add(receipt: AddReceiptV1, *, json_output: bool) -> None:
    try:
        buffer = (
            build_add_json_buffer_v1(receipt)
            if json_output
            else build_add_human_buffer_v1(receipt)
        )
    except Exception:  # noqa: BLE001 - contract hard-stops seal failures.
        os._exit(1)
    write_operations_stdout(buffer)


def run_add(
    *,
    pdf_path: str,
    work_id: str | None,
    doi: str | None,
    arxiv_id: str | None,
    citation: str | None,
    json_output: bool,
    cli_patch: tuple[tuple[str, str], ...],
) -> int:
    try:
        configuration = resolve_configuration_v1(
            trusted_project_root=Path(r"E:\Gezhi"),
            cli_patch=cli_patch,
            environ=os.environ.copy(),
        )
    except ConfigurationError:
        receipt = _stopped_receipt("blocked", "configuration_invalid")
    else:
        try:
            root = open_validated_data_root_v1(
                configuration.literature_data_root
            )
        except DataRootOpenErrorV1 as error:
            receipt = _stopped_receipt(
                "blocked",
                "data_root_unsafe"
                if error.status == "unsafe"
                else "data_root_unavailable",
            )
        else:
            with root:
                try:
                    result = add_local_pdf(
                        AddLocalPdfRequestV1(
                            pdf_path=pdf_path,
                            work_id=work_id,
                            doi=doi,
                            arxiv_id=arxiv_id,
                            citation=citation,
                        ),
                        root=root,
                    )
                except AddInputInvalidV1 as error:
                    receipt = _stopped_receipt(
                        "blocked",
                        "input_invalid",
                        {"field": error.field},
                    )
                except AddStoppedV1 as error:
                    receipt = _stopped_receipt(
                        error.outcome,
                        error.reason,
                        error.context,
                    )
                else:
                    receipt = AddReceiptV1(
                        outcome="succeeded",
                        result=result.as_mapping_v1(),
                        diagnostic=None,
                    )
    _present_add(receipt, json_output=json_output)
    return {"succeeded": 0, "blocked": 2, "failed": 1}[receipt.outcome]


def run_resume(**_values: object) -> int:
    raise NotImplementedError("literature resume is delivered by a later ticket")


def run_review(**_values: object) -> int:
    raise NotImplementedError("literature review is delivered by a later ticket")
