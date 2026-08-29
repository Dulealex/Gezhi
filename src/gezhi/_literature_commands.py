from __future__ import annotations

import hashlib
import json
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
_CANDIDATE_ID = re.compile(r"^cand_[0-9a-f]{24}$")
_HANDOFF_ID = re.compile(r"^hnd_[0-9a-f]{24}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_INPUT_FIELDS = frozenset(
    {"pdf_path", "work_id", "doi", "arxiv_id", "citation", "pdf_content"}
)

AddOutcome: TypeAlias = Literal["succeeded", "blocked", "failed"]
ResumeOutcome: TypeAlias = Literal["succeeded", "blocked", "failed"]
ReviewOutcome: TypeAlias = Literal["succeeded", "blocked", "failed"]

_RESUME_STAGES = (
    "ingest",
    "ocr",
    "canonicalize",
    "read",
    "review",
    "handoff",
    "knowledge_import",
)
_RESUME_STAGE_BLOCKED = {
    "ingest": ("identity_review_required",),
    "ocr": ("ocr_runtime_unavailable", "ocr_transient_exhausted"),
    "canonicalize": ("canonical_prerequisite_unavailable",),
    "read": (
        "reader_prerequisite_unavailable",
        "reader_input_too_large",
        "codex_runtime_unavailable",
        "codex_timeout_exhausted",
    ),
    "review": ("awaiting_review",),
    "handoff": ("handoff_blocked",),
    "knowledge_import": (
        "registry_unavailable",
        "registry_busy",
        "import_blocked",
    ),
}
_RESUME_STAGE_FAILED = {
    "ingest": ("identity_conflict", "commit_failed"),
    "ocr": ("ocr_failed", "asset_integrity_lost", "commit_failed"),
    "canonicalize": (
        "canonicalization_failed",
        "asset_integrity_lost",
        "commit_failed",
    ),
    "read": (
        "reader_input_invalid",
        "codex_process_failed",
        "reader_output_invalid",
        "candidate_validation_failed",
        "asset_integrity_lost",
        "commit_failed",
    ),
    "review": ("review_state_invalid", "asset_integrity_lost", "commit_failed"),
    "handoff": (
        "revision_conflict",
        "asset_integrity_lost",
        "commit_failed",
        "handoff_failed",
    ),
    "knowledge_import": (
        "revision_conflict",
        "registry_conflict",
        "commit_failed",
        "import_failed",
    ),
}

_REVIEW_BLOCKED_CODES = frozenset(
    {
        "literature.review.configuration_invalid.v1",
        "literature.review.data_root_unsafe.v1",
        "literature.review.data_root_unavailable.v1",
        "literature.review.candidate_invalid.v1",
        "literature.review.candidate_not_found.v1",
        "literature.review.work_busy.v1",
        "literature.review.handoff_blocked.v1",
        "literature.review.import_blocked.v1",
    }
)
_REVIEW_FAILED_CODES = frozenset(
    {
        "literature.review.data_root_integrity_lost.v1",
        "literature.review.candidate_integrity_lost.v1",
        "literature.review.review_state_invalid.v1",
        "literature.review.review_commit_failed.v1",
        "literature.review.handoff_failed.v1",
        "literature.review.import_failed.v1",
    }
)
_REVIEW_DATA_ROOT_CODES = frozenset(
    {
        "literature.review.data_root_unsafe.v1",
        "literature.review.data_root_unavailable.v1",
        "literature.review.data_root_integrity_lost.v1",
    }
)

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


@dataclass(frozen=True, slots=True)
class ResumeReceiptV1:
    outcome: ResumeOutcome
    result: dict[str, object] | None
    diagnostic: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class ReviewReceiptV1:
    outcome: ReviewOutcome
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
            root = open_validated_data_root_v1(configuration.literature_data_root)
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


def _validate_resume_result(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != {
        "active_source_id",
        "advanced_stages",
        "pending_candidate_ids",
        "pipeline_complete",
        "schema_version",
        "start_stage",
        "stop_stage",
        "work_id",
    }:
        raise TypeError("Literature resume result is invalid")
    result = cast(dict[str, object], value)
    active_source_id = result["active_source_id"]
    advanced = result["advanced_stages"]
    pending = result["pending_candidate_ids"]
    start = result["start_stage"]
    stop = result["stop_stage"]
    if (
        type(active_source_id) is not str
        or _SOURCE_ID.fullmatch(active_source_id) is None
        or type(advanced) is not list
        or any(item not in _RESUME_STAGES for item in advanced)
        or len(advanced) != len(set(advanced))
        or sorted(advanced, key=_RESUME_STAGES.index) != advanced
        or type(pending) is not list
        or len(pending) > 12
        or any(
            type(item) is not str or _CANDIDATE_ID.fullmatch(item) is None
            for item in pending
        )
        or len(pending) != len(set(pending))
        or type(result["pipeline_complete"]) is not bool
        or result["schema_version"] != "gezhi.literature_resume_result.v1"
        or start not in {*_RESUME_STAGES, "complete"}
        or stop not in {*_RESUME_STAGES, "complete"}
        or type(result["work_id"]) is not str
        or _WORK_ID.fullmatch(cast(str, result["work_id"])) is None
    ):
        raise ValueError("Literature resume result is invalid")
    complete = cast(bool, result["pipeline_complete"])
    if complete != (stop == "complete" and pending == []):
        raise ValueError("Literature resume completion result is invalid")
    if start == "complete":
        if stop != "complete" or advanced:
            raise ValueError("Literature resume complete continuation is invalid")
    else:
        start_index = _RESUME_STAGES.index(cast(str, start))
        stop_index = (
            len(_RESUME_STAGES)
            if stop == "complete"
            else _RESUME_STAGES.index(cast(str, stop))
        )
        returned_from_review_backlog = (
            start == "review"
            and stop == "review"
            and bool(advanced)
            and all(
                stage in {"review", "handoff", "knowledge_import"} for stage in advanced
            )
        )
        if not returned_from_review_backlog and (
            start_index > stop_index
            or any(
                not start_index <= _RESUME_STAGES.index(cast(str, stage)) <= stop_index
                for stage in advanced
            )
        ):
            raise ValueError("Literature resume progress ordering is invalid")
    return result


def _validate_resume_diagnostic(
    outcome: Literal["blocked", "failed"],
    value: object,
) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != {"code", "context"}
        or type(value["code"]) is not str
        or type(value["context"]) is not dict
    ):
        raise TypeError("Literature resume diagnostic is invalid")
    diagnostic = cast(dict[str, object], value)
    code = cast(str, diagnostic["code"])
    context = cast(dict[str, object], diagnostic["context"])
    blocked = {
        "literature.resume.configuration_invalid.v1",
        "literature.resume.data_root_unsafe.v1",
        "literature.resume.data_root_unavailable.v1",
        "literature.resume.work_invalid.v1",
        "literature.resume.work_not_found.v1",
        "literature.resume.work_busy.v1",
        "literature.resume.active_source_unavailable.v1",
        "literature.resume.stage_blocked.v1",
    }
    failed = {
        "literature.resume.data_root_integrity_lost.v1",
        "literature.resume.active_source_invalid.v1",
        "literature.resume.stage_failed.v1",
        "literature.resume.recovery_failed.v1",
    }
    if code not in (blocked if outcome == "blocked" else failed):
        raise ValueError("Literature resume diagnostic is invalid")
    if code in {
        "literature.resume.data_root_unsafe.v1",
        "literature.resume.data_root_unavailable.v1",
        "literature.resume.data_root_integrity_lost.v1",
    }:
        if context not in ({"data_root": "literature"}, {"data_root": "knowledge"}):
            raise ValueError("Literature resume Data Root context is invalid")
    elif code in {
        "literature.resume.stage_blocked.v1",
        "literature.resume.stage_failed.v1",
    }:
        if set(context) != {"reason", "stage"}:
            raise ValueError("Literature resume stage context is invalid")
        stage = context["stage"]
        reason = context["reason"]
        matrix = (
            _RESUME_STAGE_BLOCKED
            if code == "literature.resume.stage_blocked.v1"
            else _RESUME_STAGE_FAILED
        )
        if (
            type(stage) is not str
            or stage not in matrix
            or type(reason) is not str
            or reason not in matrix[stage]
        ):
            raise ValueError("Literature resume stage context is invalid")
    elif context:
        raise ValueError("Literature resume diagnostic context is invalid")
    return diagnostic


def _resume_result_is_required(
    diagnostic: dict[str, object],
) -> bool:
    code = cast(str, diagnostic["code"])
    context = cast(dict[str, object], diagnostic["context"])
    if code in {
        "literature.resume.stage_blocked.v1",
        "literature.resume.stage_failed.v1",
    }:
        return True
    if code in {
        "literature.resume.data_root_unsafe.v1",
        "literature.resume.data_root_unavailable.v1",
        "literature.resume.data_root_integrity_lost.v1",
    }:
        return context.get("data_root") == "knowledge"
    return False


def _validate_resume_result_diagnostic_binding(
    result: dict[str, object],
    diagnostic: dict[str, object],
) -> None:
    code = cast(str, diagnostic["code"])
    context = cast(dict[str, object], diagnostic["context"])
    advanced = cast(list[str], result["advanced_stages"])
    pending = cast(list[str], result["pending_candidate_ids"])
    if code in {
        "literature.resume.stage_blocked.v1",
        "literature.resume.stage_failed.v1",
    }:
        stage = cast(str, context["stage"])
        reason = cast(str, context["reason"])
        if result["pipeline_complete"] is not False or result["stop_stage"] != stage:
            raise ValueError("Literature resume stage result binding is invalid")
        if reason == "awaiting_review":
            if stage != "review" or not pending:
                raise ValueError("Literature resume review backlog is invalid")
        elif pending and stage not in {"review", "handoff", "knowledge_import"}:
            raise ValueError("Literature resume pending backlog is invalid")
        if stage in advanced and not (
            stage == "review" and reason == "awaiting_review"
        ):
            raise ValueError("Literature resume stopped stage was advanced")
        return
    if (
        code
        in {
            "literature.resume.data_root_unsafe.v1",
            "literature.resume.data_root_unavailable.v1",
            "literature.resume.data_root_integrity_lost.v1",
        }
        and context == {"data_root": "knowledge"}
        and (
            result["pipeline_complete"] is not False
            or result["stop_stage"] != "knowledge_import"
            or "knowledge_import" in advanced
        )
    ):
        raise ValueError("Literature resume Knowledge root result is invalid")


def _validate_resume_receipt(
    receipt: ResumeReceiptV1,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    if type(receipt) is not ResumeReceiptV1 or receipt.outcome not in {
        "succeeded",
        "blocked",
        "failed",
    }:
        raise TypeError("Literature resume receipt is invalid")
    if receipt.outcome == "succeeded":
        if receipt.diagnostic is not None:
            raise ValueError("successful Literature resume has a diagnostic")
        result = _validate_resume_result(receipt.result)
        if result["pipeline_complete"] is not True:
            raise ValueError("successful Literature resume is not complete")
        return result, None
    if receipt.diagnostic is None:
        raise ValueError("stopped Literature resume diagnostic is unavailable")
    diagnostic = _validate_resume_diagnostic(receipt.outcome, receipt.diagnostic)
    required = _resume_result_is_required(diagnostic)
    if required:
        result = _validate_resume_result(receipt.result)
        _validate_resume_result_diagnostic_binding(result, diagnostic)
        return result, diagnostic
    if receipt.result is not None:
        raise ValueError("Literature resume result presence is invalid")
    return None, diagnostic


def build_resume_json_buffer_v1(receipt: ResumeReceiptV1) -> bytes:
    result, diagnostic = _validate_resume_receipt(receipt)
    buffer = operations_json_buffer(
        command="literature.resume",
        outcome=receipt.outcome,
        result=result,
        diagnostics=[] if diagnostic is None else [diagnostic],
    )
    if len(buffer) > _LITERATURE_OUTPUT_CAP:
        raise ValueError("Literature resume output exceeds 32 KiB")
    return buffer


_RESUME_HUMAN_CATALOG = {
    "literature.resume.configuration_invalid.v1": (
        "配置无效",
        "修正格致配置后重新运行 resume",
    ),
    "literature.resume.data_root_unsafe.v1": (
        "<data_root> 数据目录不安全",
        "运行 gezhi doctor 并移除 <data_root> 数据目录不受支持的 namespace 或路径别名",
    ),
    "literature.resume.data_root_unavailable.v1": (
        "<data_root> 数据目录不可用",
        "运行 gezhi doctor 并修复 <data_root> 数据目录",
    ),
    "literature.resume.work_invalid.v1": (
        "Work ID 格式无效",
        "使用完整规范 Work ID 重试",
    ),
    "literature.resume.work_not_found.v1": (
        "指定 Work 不存在",
        "核对 Work ID 后重试",
    ),
    "literature.resume.work_busy.v1": (
        "该 Work 正由另一个写流程处理",
        "等待该流程结束后重试",
    ),
    "literature.resume.active_source_unavailable.v1": (
        "Active Source 不可用",
        "先用 literature add 明确选择可用 Source",
    ),
    "literature.resume.stage_blocked.v1": (
        "<stage> 阶段已阻塞（<reason>）",
        "修复该前置条件后重新运行 resume；awaiting_review 时对列出的 Candidate 显式 review",
    ),
    "literature.resume.data_root_integrity_lost.v1": (
        "<data_root> 数据目录身份在执行中失去可信性",
        "停止写入并运行 gezhi doctor 检查 <data_root> 数据目录身份",
    ),
    "literature.resume.active_source_invalid.v1": (
        "Active Source 资产无效",
        "保留现有资产并检查 Source manifest、ID、hash 与 bytes",
    ),
    "literature.resume.stage_failed.v1": (
        "<stage> 阶段失败（<reason>）",
        "保留现有资产，修复该阶段后重新运行 resume",
    ),
    "literature.resume.recovery_failed.v1": (
        "Literature 恢复检查失败",
        "停止相关写入并保留 staging 与恢复证据；运行 gezhi status，按 Operations 的 inspect_recovery 指引进行维护检查；不要手工删除或改名",
    ),
}


def _append_resume_result_lines(
    lines: list[str],
    result: dict[str, object],
) -> None:
    lines.append(f"Active Source ID：{_human_value(result['active_source_id'])}")
    advanced = cast(list[object], result["advanced_stages"])
    if advanced:
        lines.append("本次推进阶段：")
        lines.extend(f"  - {_human_value(item)}" for item in advanced)
    else:
        lines.append("本次推进阶段：[]")
    pending = cast(list[object], result["pending_candidate_ids"])
    if pending:
        lines.append("待审核 Candidate：")
        lines.extend(f"  - {_human_value(item)}" for item in pending)
    else:
        lines.append("待审核 Candidate：[]")
    for key, label in (
        ("pipeline_complete", "管线已完成"),
        ("schema_version", "Schema"),
        ("start_stage", "开始阶段"),
        ("stop_stage", "停止阶段"),
        ("work_id", "Work ID"),
    ):
        lines.append(f"{label}：{_human_value(result[key])}")


def build_resume_human_buffer_v1(receipt: ResumeReceiptV1) -> bytes:
    result, diagnostic = _validate_resume_receipt(receipt)
    lines = [
        {
            "succeeded": "Literature resume：完成",
            "blocked": "Literature resume：已阻塞",
            "failed": "Literature resume：失败",
        }[receipt.outcome]
    ]
    if result is not None:
        _append_resume_result_lines(lines, result)
    if diagnostic is None:
        lines.append("下一步：无需操作")
    else:
        code = cast(str, diagnostic["code"])
        context = cast(dict[str, object], diagnostic["context"])
        if (
            code == "literature.resume.stage_blocked.v1"
            and context == {"stage": "review", "reason": "awaiting_review"}
            and result is not None
        ):
            for candidate_id in cast(list[str], result["pending_candidate_ids"]):
                for action in ("accept", "reject", "defer"):
                    lines.append(
                        f"审核命令：gezhi literature review {candidate_id} --{action}"
                    )
        reason, next_action = _RESUME_HUMAN_CATALOG[code]
        if "data_root" in context:
            data_root = cast(str, context["data_root"])
            reason = reason.replace("<data_root>", data_root)
            next_action = next_action.replace("<data_root>", data_root)
        if "stage" in context:
            reason = reason.replace("<stage>", cast(str, context["stage"]))
            reason = reason.replace("<reason>", cast(str, context["reason"]))
        lines.extend((f"原因：{reason}", f"下一步：{next_action}"))
    buffer = ("\n".join(lines) + "\n").encode("utf-8")
    if len(buffer) > _LITERATURE_OUTPUT_CAP:
        raise ValueError("Literature resume output exceeds 32 KiB")
    return buffer


def _present_resume(receipt: ResumeReceiptV1, *, json_output: bool) -> None:
    try:
        buffer = (
            build_resume_json_buffer_v1(receipt)
            if json_output
            else build_resume_human_buffer_v1(receipt)
        )
    except Exception:  # noqa: BLE001 - contract hard-stops seal failures.
        os._exit(1)
    write_operations_stdout(buffer)


def _resume_stopped_receipt(
    outcome: Literal["blocked", "failed"],
    reason: str,
    *,
    result: dict[str, object] | None = None,
    stage: str | None = None,
    data_root: str | None = None,
) -> ResumeReceiptV1:
    if stage is not None:
        code = "stage_blocked" if outcome == "blocked" else "stage_failed"
        context: dict[str, object] = {"reason": reason, "stage": stage}
    else:
        code = reason
        context = {} if data_root is None else {"data_root": data_root}
    return ResumeReceiptV1(
        outcome=outcome,
        result=result,
        diagnostic={
            "code": f"literature.resume.{code}.v1",
            "context": context,
        },
    )


def run_resume(
    *,
    work_id: str,
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
        receipt = _resume_stopped_receipt("blocked", "configuration_invalid")
    else:
        try:
            root = open_validated_data_root_v1(configuration.literature_data_root)
        except DataRootOpenErrorV1 as error:
            receipt = _resume_stopped_receipt(
                "blocked",
                "data_root_unsafe"
                if error.status == "unsafe"
                else "data_root_unavailable",
                data_root="literature",
            )
        else:
            from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
            from gezhi._literature_resume import ResumeStoppedV1, resume_work

            with root:
                try:
                    result = resume_work(
                        work_id,
                        root=root,
                        source_environment=os.environ.copy(),
                        knowledge_intake=KnowledgeIntakeAdapterV1(
                            configuration.knowledge_data_root
                        ),
                    )
                except ResumeStoppedV1 as error:
                    receipt = _resume_stopped_receipt(
                        error.outcome,
                        error.reason,
                        result=(
                            None
                            if error.result is None
                            else error.result.as_mapping_v1()
                        ),
                        stage=error.stage,
                        data_root=error.data_root,
                    )
                else:
                    receipt = ResumeReceiptV1(
                        outcome="succeeded",
                        result=result.as_mapping_v1(),
                        diagnostic=None,
                    )
    _present_resume(receipt, json_output=json_output)
    return {"succeeded": 0, "blocked": 2, "failed": 1}[receipt.outcome]


def _review_handoff_id(
    *,
    action: str,
    candidate_id: str,
    payload_sha256: str,
    review_revision: int,
) -> str:
    identity = {
        "action": action,
        "candidate_id": candidate_id,
        "payload_sha256": payload_sha256,
        "review_revision": review_revision,
        "schema_version": "gezhi.reviewed_handoff_identity.v1",
    }
    payload = json.dumps(
        identity,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "hnd_" + hashlib.sha256(payload).hexdigest()[:24]


def _validate_review_result(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != {
        "candidate_id",
        "decision_disposition",
        "handoff_action",
        "handoff_id",
        "handoff_status",
        "import_status",
        "intake_status",
        "payload_sha256",
        "review_revision",
        "review_status",
        "schema_version",
        "work_id",
    }:
        raise TypeError("Literature review result is invalid")
    result = cast(dict[str, object], value)
    candidate_id = result["candidate_id"]
    payload_sha256 = result["payload_sha256"]
    review_revision = result["review_revision"]
    action = result["handoff_action"]
    handoff_id = result["handoff_id"]
    handoff_status = result["handoff_status"]
    import_status = result["import_status"]
    intake_status = result["intake_status"]
    review_status = result["review_status"]
    if (
        type(candidate_id) is not str
        or _CANDIDATE_ID.fullmatch(candidate_id) is None
        or type(payload_sha256) is not str
        or _SHA256.fullmatch(payload_sha256) is None
        or candidate_id != "cand_" + payload_sha256[:24]
        or type(review_revision) is not int
        or not 1 <= review_revision <= 9_223_372_036_854_775_807
        or result["decision_disposition"] not in {"created", "unchanged"}
        or action not in {"accept", "withdraw", "none"}
        or handoff_status not in {"committed", "not_required", "pending"}
        or import_status not in {"applied", "not_required", "pending"}
        or intake_status not in {"active", "withdrawn", None}
        or review_status not in {"accepted", "rejected", "deferred"}
        or result["schema_version"] != "gezhi.literature_review_result.v1"
        or type(result["work_id"]) is not str
        or _WORK_ID.fullmatch(cast(str, result["work_id"])) is None
    ):
        raise ValueError("Literature review result is invalid")

    if review_status == "accepted":
        if action != "accept":
            raise ValueError("Literature review action is invalid")
    elif action not in {"withdraw", "none"}:
        raise ValueError("Literature review action is invalid")

    if action == "none":
        if (
            handoff_id is not None
            or handoff_status not in {"not_required", "pending"}
            or import_status != "not_required"
            or intake_status is not None
        ):
            raise ValueError("Literature review no-action result is invalid")
        return result

    if (
        type(handoff_id) is not str
        or _HANDOFF_ID.fullmatch(handoff_id) is None
        or handoff_id
        != _review_handoff_id(
            action=cast(str, action),
            candidate_id=candidate_id,
            payload_sha256=payload_sha256,
            review_revision=review_revision,
        )
    ):
        raise ValueError("Literature review Handoff identity is invalid")
    expected_intake = "active" if action == "accept" else "withdrawn"
    if (handoff_status, import_status, intake_status) not in {
        ("pending", "pending", None),
        ("committed", "pending", None),
        ("committed", "applied", expected_intake),
    }:
        raise ValueError("Literature review continuation result is invalid")
    return result


def _validate_review_diagnostic(
    outcome: Literal["blocked", "failed"],
    value: object,
) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != {"code", "context"}
        or type(value["code"]) is not str
        or type(value["context"]) is not dict
    ):
        raise TypeError("Literature review diagnostic is invalid")
    diagnostic = cast(dict[str, object], value)
    code = cast(str, diagnostic["code"])
    context = cast(dict[str, object], diagnostic["context"])
    allowed = _REVIEW_BLOCKED_CODES if outcome == "blocked" else _REVIEW_FAILED_CODES
    if code not in allowed:
        raise ValueError("Literature review diagnostic is invalid")
    if code in _REVIEW_DATA_ROOT_CODES:
        if context not in (
            {"data_root": "literature"},
            {"data_root": "knowledge"},
        ):
            raise ValueError("Literature review Data Root context is invalid")
    elif context:
        raise ValueError("Literature review diagnostic context is invalid")
    return diagnostic


def _review_result_presence(
    diagnostic: dict[str, object],
) -> Literal["forbidden", "optional", "required"]:
    code = cast(str, diagnostic["code"])
    context = cast(dict[str, object], diagnostic["context"])
    if code in {
        "literature.review.handoff_blocked.v1",
        "literature.review.import_blocked.v1",
        "literature.review.handoff_failed.v1",
        "literature.review.import_failed.v1",
    }:
        return "required"
    if code in _REVIEW_DATA_ROOT_CODES:
        if context == {"data_root": "knowledge"}:
            return "required"
        if code == "literature.review.data_root_integrity_lost.v1":
            return "optional"
    return "forbidden"


def _review_result_phase(
    result: dict[str, object],
) -> Literal["complete", "handoff", "import"]:
    if result["import_status"] == "applied" or (
        result["handoff_action"] == "none"
        and result["handoff_status"] == "not_required"
    ):
        return "complete"
    if result["handoff_status"] == "pending":
        return "handoff"
    return "import"


def _validate_review_result_diagnostic_binding(
    result: dict[str, object],
    diagnostic: dict[str, object],
) -> None:
    code = cast(str, diagnostic["code"])
    context = cast(dict[str, object], diagnostic["context"])
    phase = _review_result_phase(result)
    if phase == "complete":
        raise ValueError("stopped Literature review result is complete")
    if code in {
        "literature.review.handoff_blocked.v1",
        "literature.review.handoff_failed.v1",
    }:
        if phase != "handoff":
            raise ValueError("Literature review Handoff result is invalid")
        return
    if (
        code
        in {
            "literature.review.import_blocked.v1",
            "literature.review.import_failed.v1",
        }
        or (code in _REVIEW_DATA_ROOT_CODES and context == {"data_root": "knowledge"})
    ) and phase != "import":
        raise ValueError("Literature review import result is invalid")


def _validate_review_receipt(
    receipt: ReviewReceiptV1,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    if type(receipt) is not ReviewReceiptV1 or receipt.outcome not in {
        "succeeded",
        "blocked",
        "failed",
    }:
        raise TypeError("Literature review receipt is invalid")
    if receipt.outcome == "succeeded":
        if receipt.diagnostic is not None:
            raise ValueError("successful Literature review has a diagnostic")
        result = _validate_review_result(receipt.result)
        if _review_result_phase(result) != "complete":
            raise ValueError("successful Literature review is incomplete")
        return result, None
    if receipt.diagnostic is None:
        raise ValueError("stopped Literature review diagnostic is unavailable")
    diagnostic = _validate_review_diagnostic(receipt.outcome, receipt.diagnostic)
    presence = _review_result_presence(diagnostic)
    if receipt.result is None:
        if presence == "required":
            raise ValueError("Literature review result is required")
        return None, diagnostic
    if presence == "forbidden":
        raise ValueError("Literature review result is forbidden")
    result = _validate_review_result(receipt.result)
    _validate_review_result_diagnostic_binding(result, diagnostic)
    return result, diagnostic


def build_review_json_buffer_v1(receipt: ReviewReceiptV1) -> bytes:
    result, diagnostic = _validate_review_receipt(receipt)
    buffer = operations_json_buffer(
        command="literature.review",
        outcome=receipt.outcome,
        result=result,
        diagnostics=[] if diagnostic is None else [diagnostic],
    )
    if len(buffer) > _LITERATURE_OUTPUT_CAP:
        raise ValueError("Literature review output exceeds 32 KiB")
    return buffer


_REVIEW_HUMAN_CATALOG = {
    "literature.review.configuration_invalid.v1": (
        "配置无效",
        "修正格致配置后重新运行 review",
    ),
    "literature.review.data_root_unsafe.v1": (
        "<data_root> 数据目录不安全",
        "移除不受支持的 namespace 或路径别名后用相同 action 重试",
    ),
    "literature.review.data_root_unavailable.v1": (
        "<data_root> 数据目录不可用",
        "修复该 Context 数据目录后用相同 action 重试",
    ),
    "literature.review.candidate_invalid.v1": (
        "Candidate ID 格式无效",
        "使用完整规范 Candidate ID 重试",
    ),
    "literature.review.candidate_not_found.v1": (
        "指定 Candidate 不存在",
        "核对 Candidate ID 后重试",
    ),
    "literature.review.work_busy.v1": (
        "Candidate 所属 Work 正由另一个写流程处理",
        "等待该流程结束后重试",
    ),
    "literature.review.handoff_blocked.v1": (
        "Review Decision 已保存，但 Handoff 尚未完成",
        "用相同 action 重试或运行 literature resume",
    ),
    "literature.review.import_blocked.v1": (
        "Review Decision 与 Handoff 已保存，但 Knowledge import 尚未完成",
        "修复 Knowledge 前置条件后用相同 action 重试或运行 literature resume",
    ),
    "literature.review.data_root_integrity_lost.v1": (
        "<data_root> 数据目录身份在执行中失去可信性",
        "停止写入并运行 gezhi doctor",
    ),
    "literature.review.candidate_integrity_lost.v1": (
        "Candidate 资产完整性失效",
        (
            "保留 Candidate 与 Evidence 资产，运行 gezhi status 并检查 ID、hash、"
            "canonical bytes、provenance、Evidence、payload、collision 与 asset 完整性"
        ),
    ),
    "literature.review.review_state_invalid.v1": (
        "Candidate Review 历史无效",
        "保留审核资产并检查 revision 与 payload identity",
    ),
    "literature.review.review_commit_failed.v1": (
        "Review Decision 提交失败",
        "保持相同 Candidate 与 action 重试",
    ),
    "literature.review.handoff_failed.v1": (
        "Review Decision 已保存，但 Handoff 失败",
        (
            "保留 Decision 与 Handoff 资产，运行 gezhi status 检查 Handoff 完整性、"
            "协议、revision 与提交状态；修复确定原因后以同一 identity 续行"
        ),
    ),
    "literature.review.import_failed.v1": (
        "Review Decision 与 Handoff 已保存，但 Knowledge import 失败",
        (
            "保留 Decision、Handoff 与 Registry 前置事实，运行 gezhi status 检查 "
            "KnowledgeIntake/Registry 完整性、协议、revision、commit 与 conflict；"
            "修复确定原因后以同一 identity 续行"
        ),
    ),
}


def _append_review_result_lines(
    lines: list[str],
    result: dict[str, object],
) -> None:
    for key, label in (
        ("candidate_id", "Candidate ID"),
        ("decision_disposition", "Decision 处理结果"),
        ("handoff_action", "Handoff 动作"),
        ("handoff_id", "Handoff ID"),
        ("handoff_status", "Handoff 状态"),
        ("import_status", "Import 状态"),
        ("intake_status", "Intake 状态"),
        ("payload_sha256", "Payload SHA-256"),
        ("review_revision", "Review revision"),
        ("review_status", "Review 状态"),
        ("schema_version", "Schema"),
        ("work_id", "Work ID"),
    ):
        lines.append(f"{label}：{_human_value(result[key])}")


def build_review_human_buffer_v1(receipt: ReviewReceiptV1) -> bytes:
    result, diagnostic = _validate_review_receipt(receipt)
    lines = [
        {
            "succeeded": "Literature review：完成",
            "blocked": "Literature review：已阻塞",
            "failed": "Literature review：失败",
        }[receipt.outcome]
    ]
    if result is not None:
        _append_review_result_lines(lines, result)
    if diagnostic is None:
        if result is None:
            raise RuntimeError("Literature review result is unavailable")
        lines.append(f"下一步：运行 gezhi literature resume {result['work_id']}")
    else:
        code = cast(str, diagnostic["code"])
        context = cast(dict[str, object], diagnostic["context"])
        reason, next_action = _REVIEW_HUMAN_CATALOG[code]
        if "data_root" in context:
            reason = reason.replace(
                "<data_root>",
                cast(str, context["data_root"]),
            )
        lines.extend((f"原因：{reason}", f"下一步：{next_action}"))
    buffer = ("\n".join(lines) + "\n").encode("utf-8")
    if len(buffer) > _LITERATURE_OUTPUT_CAP:
        raise ValueError("Literature review output exceeds 32 KiB")
    return buffer


def _present_review(receipt: ReviewReceiptV1, *, json_output: bool) -> None:
    try:
        buffer = (
            build_review_json_buffer_v1(receipt)
            if json_output
            else build_review_human_buffer_v1(receipt)
        )
    except Exception:  # noqa: BLE001 - contract hard-stops seal failures.
        os._exit(1)
    write_operations_stdout(buffer)


def run_review(
    *,
    candidate_id: str,
    action: str,
    note: None,
    json_output: bool,
    cli_patch: tuple[tuple[str, str], ...],
) -> int:
    if action not in {"accept", "reject", "defer"} or note is not None:
        raise TypeError("validated Literature review command is invalid")
    try:
        configuration = resolve_configuration_v1(
            trusted_project_root=Path(r"E:\Gezhi"),
            cli_patch=cli_patch,
            environ=os.environ.copy(),
        )
    except ConfigurationError:
        receipt = ReviewReceiptV1(
            outcome="blocked",
            result=None,
            diagnostic={
                "code": "literature.review.configuration_invalid.v1",
                "context": {},
            },
        )
    else:
        try:
            root = open_validated_data_root_v1(configuration.literature_data_root)
        except DataRootOpenErrorV1 as error:
            reason = (
                "data_root_unsafe"
                if error.status == "unsafe"
                else "data_root_unavailable"
            )
            receipt = ReviewReceiptV1(
                outcome="blocked",
                result=None,
                diagnostic={
                    "code": f"literature.review.{reason}.v1",
                    "context": {"data_root": "literature"},
                },
            )
        else:
            from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
            from gezhi._literature_review import (
                ReviewBlockedV1,
                ReviewCandidateCommandV1,
                ReviewFailedV1,
                ReviewSucceededV1,
                review_candidate_v1,
            )

            with root:
                verdict = review_candidate_v1(
                    ReviewCandidateCommandV1(
                        candidate_id=candidate_id,
                        action=cast(
                            Literal["accept", "reject", "defer"],
                            action,
                        ),
                    ),
                    root=root,
                    knowledge_intake=KnowledgeIntakeAdapterV1(
                        configuration.knowledge_data_root
                    ),
                )
            if type(verdict) is ReviewSucceededV1:
                receipt = ReviewReceiptV1(
                    outcome="succeeded",
                    result=verdict.progress.as_mapping_v1(),
                    diagnostic=None,
                )
            elif type(verdict) is ReviewBlockedV1:
                receipt = ReviewReceiptV1(
                    outcome="blocked",
                    result=(
                        None
                        if verdict.progress is None
                        else verdict.progress.as_mapping_v1()
                    ),
                    diagnostic={
                        "code": f"literature.review.{verdict.cause.reason}.v1",
                        "context": (
                            {}
                            if verdict.cause.data_root is None
                            else {"data_root": verdict.cause.data_root}
                        ),
                    },
                )
            elif type(verdict) is ReviewFailedV1:
                receipt = ReviewReceiptV1(
                    outcome="failed",
                    result=(
                        None
                        if verdict.progress is None
                        else verdict.progress.as_mapping_v1()
                    ),
                    diagnostic={
                        "code": f"literature.review.{verdict.cause.reason}.v1",
                        "context": (
                            {}
                            if verdict.cause.data_root is None
                            else {"data_root": verdict.cause.data_root}
                        ),
                    },
                )
            else:
                raise TypeError("Literature review returned an invalid verdict")
    _present_review(receipt, json_output=json_output)
    return {"succeeded": 0, "blocked": 2, "failed": 1}[receipt.outcome]
