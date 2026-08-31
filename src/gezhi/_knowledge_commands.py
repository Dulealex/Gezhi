from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Literal, TypeAlias, cast

from gezhi._answer_terminal import (
    TerminalAnswerBytesReadyV1,
    read_committed_answer_v1,
)
from gezhi._knowledge_ask import (
    KnowledgeAskReportV1,
    KnowledgeAsksV1,
    validate_knowledge_ask_report_v1,
)
from gezhi._knowledge_cancellation import (
    CancellationSnapshotV1,
    activate_knowledge_ask_cancellation_v1,
)
from gezhi._knowledge_read import (
    KnowledgeReadReportV1,
    KnowledgeReadsV1,
    validate_knowledge_read_report_v1,
)
from gezhi._presentation import (
    CliJsonOutputTooLargeV1,
    cli_json_buffer_v1,
    write_binary_buffer_v1,
    write_knowledge_ask_human_buffer_v1,
    write_knowledge_ask_json_buffer_v1,
)
from gezhi._windows_data_root import DataRootOpenErrorV1, open_validated_data_root_v1

_OUTPUT_CAP = 1_048_576
_ASK_JSON_OUTPUT_CAP = 65_536
_ASK_HUMAN_OUTPUT_CAP = 532_480
_WRITE_CHUNK = 65_536
_ASK_PRIMARY = {
    "invalid_question": (
        "knowledge.ask.invalid_question.v1",
        "问题为空、语义不足或包含不支持的控制字符",
        "输入一个单轮、自包含且可读的问题后重试",
    ),
    "question_too_large": (
        "knowledge.ask.question_too_large.v1",
        "问题超过 2000 个 Unicode code point 或 8192 个 UTF-8 字节",
        "缩短问题后重试",
    ),
    "question_too_complex": (
        "knowledge.ask.question_too_complex.v1",
        "问题产生的安全检索原子超过上限",
        "减少并列术语或拆成更具体的单轮问题后重试",
    ),
    "configuration_invalid": (
        "knowledge.ask.configuration_invalid.v1",
        "格致配置的格式、版本或字段无效",
        "运行 gezhi doctor 检查配置能力，并在外部修正版本化配置后重试",
    ),
    "configuration_incompatible": (
        "knowledge.ask.configuration_incompatible.v1",
        "格致配置与冻结的运行角色不兼容",
        "恢复与当前版本匹配的冻结配置后重试",
    ),
    "provenance_unavailable": (
        "knowledge.ask.provenance_unavailable.v1",
        "无法形成本次运行所需的仓库 provenance",
        "在外部恢复可验证的 Git provenance 后重试",
    ),
    "data_root_unavailable": (
        "knowledge.ask.data_root_unavailable.v1",
        "Knowledge 数据目录不存在、不可访问或不是普通本机目录",
        "运行 gezhi doctor 检查 Knowledge Data Root 能力，并在外部恢复已配置目录后重试",
    ),
    "data_root_unsafe": (
        "knowledge.ask.data_root_unsafe.v1",
        "Knowledge 数据目录违反本机路径或隔离安全边界",
        "运行 gezhi doctor 检查 Knowledge Data Root 能力，并在外部改用安全且隔离的本机目录",
    ),
    "data_root_identity_unavailable": (
        "knowledge.ask.data_root_identity_unavailable.v1",
        "无法取得 Knowledge 数据目录的稳定物理身份",
        "运行 gezhi doctor 检查 Knowledge Data Root 能力，并改用支持稳定文件身份的本机文件系统",
    ),
    "answer_writer_busy": (
        "knowledge.ask.answer_writer_busy.v1",
        "另一个 knowledge ask 正在写入同一 Knowledge 数据目录",
        "等待另一个回答完成后重试",
    ),
    "answer_writer_coordination_unavailable": (
        "knowledge.ask.answer_writer_coordination_unavailable.v1",
        "无法建立 Knowledge Answer 单写者协调",
        "运行 gezhi status 观察 Knowledge 状态（status 不会修复），在外部恢复 Windows 单写者协调后重试",
    ),
    "retrieval_view_too_large": (
        "knowledge.ask.retrieval_view_too_large.v1",
        "检索视图超过 262144 字节上限",
        "使用更具体的问题重新提问；保留 Answer ID 作为本次超限审计",
    ),
    "codex_runtime_unavailable": (
        "knowledge.ask.codex_runtime_unavailable.v1",
        "冻结的 Codex CLI 运行能力不可用",
        "运行 gezhi doctor 检查项目 Codex CLI 与登录能力，恢复后重新提问",
    ),
    "codex_timeout_exhausted": (
        "knowledge.ask.codex_timeout_exhausted.v1",
        "Codex 回答尝试已耗尽超时预算",
        "稍后重新提问；若持续发生，运行 gezhi doctor 检查 Codex 环境能力",
    ),
    "synthesis_input_invalid": (
        "knowledge.ask.synthesis_input_invalid.v1",
        "Codex 回答输入包未通过本地验证",
        "运行 gezhi status 观察 Knowledge 与 Answer 整体状态（status 不会修复），保留 Answer ID 并检查本地输入形成",
    ),
    "codex_process_failed": (
        "knowledge.ask.codex_process_failed.v1",
        "Codex 子进程或捕获链失败",
        "先运行 gezhi status 观察 Knowledge 与 Answer 整体状态（status 不会修复）；必要时运行 gezhi doctor 检查 Codex 环境能力",
    ),
    "answer_output_invalid": (
        "knowledge.ask.answer_output_invalid.v1",
        "Codex 回答未通过结构、引用或状态校验",
        "重新表述问题后提问；若持续发生，运行 gezhi status 观察 Knowledge 与 Answer 整体状态（status 不会修复）",
    ),
    "citation_link_construction_failed": (
        "knowledge.ask.citation_link_construction_failed.v1",
        "来源标识符无法形成安全引用链接",
        "运行 gezhi status 观察整体 Work 与 Knowledge 状态（status 不会修复），在外部修正 DOI 或 arXiv 身份后重新提问",
    ),
    "answer_rendering_failed": (
        "knowledge.ask.answer_rendering_failed.v1",
        "可读 Answer 未能确定性渲染",
        "运行 gezhi status 观察 Knowledge 与 Answer 整体状态（status 不会修复），保留 Answer ID 并检查确定性渲染",
    ),
    "pre_answer_formation_failed": (
        "knowledge.ask.pre_answer_formation_failed.v1",
        "Answer 身份建立前的本地审计对象形成失败",
        "运行 gezhi status 观察整体状态（status 不会修复），保留现场并检查本地对象形成",
    ),
    "data_root_integrity_lost": (
        "knowledge.ask.data_root_integrity_lost.v1",
        "Knowledge 数据目录身份在执行中失去可信性",
        "停止写入并运行 gezhi status 观察完整性风险（status 不会修复）；必要时运行 gezhi doctor 检查当前 Data Root 能力",
    ),
    "orphan_scan_failed": (
        "knowledge.ask.orphan_scan_failed.v1",
        "历史 Answer staging 无法安全完成扫描",
        "运行 gezhi status 观察 staging 风险（status 不会修复）；不要手动移动、删除或修补 staging",
    ),
    "answer_staging_failed": (
        "knowledge.ask.answer_staging_failed.v1",
        "本次 Answer staging 或非终态资产形成失败",
        "运行 gezhi status 观察 staging 风险（status 不会修复），保留现场后检查存储与权限",
    ),
    "answer_manifest_failed": (
        "knowledge.ask.answer_manifest_failed.v1",
        "本次 Answer terminal manifest 形成或复验失败",
        "保留 staging 并运行 gezhi status 观察 staging 与 Answer 整体状态（status 不会复验或修复 manifest）；不要手动补写 manifest",
    ),
    "answer_target_conflict": (
        "knowledge.ask.answer_target_conflict.v1",
        "本次 Answer 的同身份正式 target 已存在",
        "运行 gezhi status 观察 Knowledge 与 Answer 整体状态（status 不会判定或修复该冲突）；不要覆盖、删除或合并现有 Answer",
    ),
    "answer_commit_failed": (
        "knowledge.ask.answer_commit_failed.v1",
        "本次 Answer 的原子目录提交确定失败",
        "保留 staging 并运行 gezhi status 观察 staging 与 Answer 整体状态（status 不会判定或修复该提交），再在外部检查存储",
    ),
    "user_interrupted": (
        "knowledge.ask.user_interrupted.v1",
        "用户中断了已经建立身份的本次回答",
        "如仍需要答案，请重新运行 knowledge ask",
    ),
    "user_interrupted_before_answer": (
        "knowledge.ask.user_interrupted_before_answer.v1",
        "用户在 Answer 身份建立前中断了本次请求",
        "如仍需要答案，请重新运行 knowledge ask",
    ),
}

_PresentationFailureKindV1: TypeAlias = Literal[
    "diagnostic_projection_unrepresentable",
    "canonical_serialization_failed",
    "stdout_cap_exceeded",
    "human_terminal_answer_bytes_rejected",
    "human_semantic_render_rejected",
    "human_utf8_encode_failed",
    "human_semantic_bytes_rejected",
    "human_semantic_bytes_too_large",
]
_DISCLOSURE = (
    "治理说明：以下结果仅为已审核但尚未晋升的 Candidate Knowledge，"
    "不代表已晋升知识、已验证事实或自动蕴含证明。"
)
_WITHDRAWN_WARNING = (
    "注意：该 Candidate 已撤回，不参与 search 或 ask 检索；以下内容仅供历史审计。"
)

_HUMAN_DIAGNOSTICS = {
    "invalid_query": "搜索内容无效；请提供包含可检索文字的查询。",
    "query_too_large": "搜索内容过长；请缩短查询后重试。",
    "query_too_complex": "搜索内容过于复杂；请减少不同检索词后重试。",
    "invalid_candidate_id": "Candidate ID 格式无效；请提供完整的小写 cand_ 标识。",
    "candidate_not_found": "没有找到该 Candidate。",
    "configuration_invalid": "格致配置无效；请修正项目配置后重试。",
    "configuration_incompatible": "格致配置版本不兼容；请使用项目支持的配置版本。",
    "data_root_unavailable": "Knowledge 数据目录不可用；请确认目录已经存在且可读取。",
    "data_root_unsafe": "Knowledge 数据目录不满足安全边界；请改用本机独立目录。",
    "data_root_identity_unavailable": "无法验证 Knowledge 数据目录身份；请检查磁盘与目录状态。",
    "data_root_integrity_lost": "读取期间 Knowledge 数据目录身份发生异常；本次结果未发布。",
    "registry_unavailable": "Candidate Registry 暂时不可用；请确认 Registry 已初始化且未被占用。",
    "registry_incompatible": "Candidate Registry 版本不兼容；本项目不会自动迁移。",
    "fts5_unavailable": "当前 SQLite 缺少所需的 FTS5 检索能力。",
    "registry_corrupt": "Candidate Registry 已损坏或不满足完整性约束；本次结果未发布。",
    "registry_read_failed": "读取 Candidate Registry 失败；本次结果未发布。",
    "retrieval_query_failed": "Candidate 检索执行失败；本次结果未发布。",
    "retrieval_materialization_failed": "检索结果无法完整验证；本次结果未发布。",
    "candidate_corrupt": "Candidate 内容无法通过身份与哈希验证；本次结果未发布。",
    "evidence_corrupt": "Candidate 的交接证据无法完整验证；本次结果未发布。",
    "result_too_large": "结果超过本命令的输出上限；本次结果未截断。",
}

_LABELS = {
    "action": "动作 [action]",
    "arxiv_id": "arXiv ID [arxiv_id]",
    "author_count": "作者总数 [author_count]",
    "block_id": "Block ID [block_id]",
    "candidate": "Candidate [candidate]",
    "candidate_count": "Candidate 数量 [candidate_count]",
    "candidate_id": "Candidate ID [candidate_id]",
    "candidate_type": "Candidate 类型 [candidate_type]",
    "candidates_sha256": "candidates.jsonl SHA-256 [candidates_sha256]",
    "canonical_content_sha256": ("Canonical 内容 SHA-256 [canonical_content_sha256]"),
    "citation": "引用快照 [citation]",
    "content_import": "内容交接 [content_import]",
    "descriptor_id": "Descriptor ID [descriptor_id]",
    "descriptor_refs": "Descriptor 引用 [descriptor_refs]",
    "descriptor_snapshots": "Descriptor 快照 [descriptor_snapshots]",
    "doi": "DOI [doi]",
    "evidence_pointers": "证据指针 [evidence_pointers]",
    "evidence_snapshots": "证据快照 [evidence_snapshots]",
    "excerpt": "摘录 [excerpt]",
    "governance": "治理 [governance]",
    "handoff_id": "Handoff ID [handoff_id]",
    "intake_status": "接收状态 [intake_status]",
    "items": "候选项 [items]",
    "kind": "类型 [kind]",
    "label": "名称 [label]",
    "manifest_sha256": "manifest.json SHA-256 [manifest_sha256]",
    "page_index": "页索引 [page_index]",
    "payload": "Payload [payload]",
    "payload_sha256": "Payload SHA-256 [payload_sha256]",
    "pointer": "证据指针 [pointer]",
    "primary_authors": "主要作者 [primary_authors]",
    "promotion_status": "晋升状态 [promotion_status]",
    "query": "规范查询 [query]",
    "rank": "排名 [rank]",
    "reference": "Descriptor 引用 [reference]",
    "research_interest_id": "Research Interest ID [research_interest_id]",
    "result_kind": "结果种类 [result_kind]",
    "review_revision": "审核修订 [review_revision]",
    "review_status": "审核状态 [review_status]",
    "risk_flags": "审核风险标记 [risk_flags]",
    "schema_version": "架构版本 [schema_version]",
    "source_id": "Source ID [source_id]",
    "source_sha256": "Source SHA-256 [source_sha256]",
    "source_terms": "来源术语 [source_terms]",
    "statement": "陈述 [statement]",
    "status_import": "当前交接 [status_import]",
    "support_kind": "支持类型 [support_kind]",
    "text": "文本 [text]",
    "title": "标题 [title]",
    "value": "值 [value]",
    "work_id": "Work ID [work_id]",
    "year": "年份 [year]",
}


def _diagnostics_v1(report: KnowledgeReadReportV1) -> list[dict[str, object]]:
    validate_knowledge_read_report_v1(report)
    if report.outcome == "succeeded":
        return []
    if report.reason is None:
        raise ValueError("unsuccessful Knowledge read has no reason")
    return [
        {
            "code": f"{report.command}.{report.reason}.v1",
            "context": {},
        }
    ]


def _json_buffer_v1(report: KnowledgeReadReportV1) -> bytes:
    diagnostics = _diagnostics_v1(report)
    if report.outcome == "succeeded":
        if report.result is None or diagnostics:
            raise ValueError("successful Knowledge read envelope is invalid")
    elif report.result is not None or len(diagnostics) != 1:
        raise ValueError("unsuccessful Knowledge read envelope is invalid")
    return cli_json_buffer_v1(
        command=report.command,
        outcome=report.outcome,
        result=report.result,
        diagnostics=diagnostics,
        output_cap=_OUTPUT_CAP,
    )


@dataclass(frozen=True, slots=True)
class _PreparedKnowledgeReadV1:
    report: KnowledgeReadReportV1
    json_buffer: bytes


def _prepare_knowledge_read_v1(
    report: KnowledgeReadReportV1,
) -> _PreparedKnowledgeReadV1:
    try:
        json_buffer = _json_buffer_v1(report)
    except CliJsonOutputTooLargeV1:
        if report.outcome != "succeeded":
            raise
        prepared = KnowledgeReadReportV1(
            command=report.command,
            outcome="blocked",
            result=None,
            reason="result_too_large",
        )
        return _PreparedKnowledgeReadV1(
            report=prepared,
            json_buffer=_json_buffer_v1(prepared),
        )
    return _PreparedKnowledgeReadV1(report=report, json_buffer=json_buffer)


def build_knowledge_read_json_buffer_v1(report: KnowledgeReadReportV1) -> bytes:
    return _prepare_knowledge_read_v1(report).json_buffer


def _scalar_token_v1(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    raise TypeError("HumanTree scalar is invalid")


def _is_container(value: object) -> bool:
    return type(value) in {dict, list}


def _container_is_empty(value: object) -> bool:
    return _is_container(value) and len(value) == 0  # type: ignore[arg-type]


def _human_container_lines_v1(value: object, *, depth: int) -> list[str]:
    indent = " " * (2 * depth)
    if type(value) is dict:
        lines: list[str] = []
        for key in sorted(value):
            if type(key) is not str or key not in _LABELS:
                raise ValueError("HumanTree key is invalid")
            item = value[key]
            prefix = f"{indent}{_LABELS[key]}:"
            if not _is_container(item):
                lines.append(f"{prefix} {_scalar_token_v1(item)}")
            elif _container_is_empty(item):
                lines.append(f"{prefix} {'{}' if type(item) is dict else '[]'}")
            else:
                lines.append(prefix)
                lines.extend(_human_container_lines_v1(item, depth=depth + 1))
        return lines
    if type(value) is list:
        lines = []
        for item in value:
            prefix = f"{indent}-"
            if not _is_container(item):
                lines.append(f"{prefix} {_scalar_token_v1(item)}")
            elif _container_is_empty(item):
                lines.append(f"{prefix} {'{}' if type(item) is dict else '[]'}")
            else:
                lines.append(prefix)
                lines.extend(_human_container_lines_v1(item, depth=depth + 1))
        return lines
    raise TypeError("HumanTree container is invalid")


def _human_buffer_v1(report: KnowledgeReadReportV1) -> bytes:
    if report.outcome != "succeeded":
        if report.reason is None or report.reason not in _HUMAN_DIAGNOSTICS:
            raise ValueError("Knowledge read Human diagnostic is invalid")
        return (_HUMAN_DIAGNOSTICS[report.reason] + "\n").encode("utf-8")
    result = report.result
    if type(result) is not dict:
        raise TypeError("Knowledge read Human result is invalid")
    heading = (
        "Knowledge 候选搜索"
        if report.command == "knowledge.search"
        else "Knowledge 候选详情"
    )
    lines = [heading, _DISCLOSURE]
    for key in sorted(result):
        item = result[key]
        lines.extend(_human_container_lines_v1({key: item}, depth=0))
        if (
            report.command == "knowledge.show"
            and key == "governance"
            and type(item) is dict
            and item.get("intake_status") == "withdrawn"
        ):
            lines.append(_WITHDRAWN_WARNING)
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_knowledge_read_human_buffer_v1(report: KnowledgeReadReportV1) -> bytes:
    prepared = _prepare_knowledge_read_v1(report)
    return _human_buffer_v1(prepared.report)


@dataclass(frozen=True, slots=True)
class _PreparedKnowledgeReadPresentationV1:
    report: KnowledgeReadReportV1
    buffer: bytes
    json_output: bool


class _KnowledgeReadPresentationSealFailedV1(RuntimeError):
    pass


def _prepare_knowledge_read_presentation_v1(
    report: KnowledgeReadReportV1,
    *,
    json_output: bool,
) -> _PreparedKnowledgeReadPresentationV1:
    prepared = _prepare_knowledge_read_v1(report)
    return _PreparedKnowledgeReadPresentationV1(
        report=prepared.report,
        buffer=(
            prepared.json_buffer if json_output else _human_buffer_v1(prepared.report)
        ),
        json_output=json_output,
    )


def _present_v1(
    report: KnowledgeReadReportV1,
    *,
    json_output: bool,
    prepared_candidate: _PreparedKnowledgeReadPresentationV1 | None = None,
) -> KnowledgeReadReportV1:
    try:
        candidate = (
            _prepare_knowledge_read_presentation_v1(
                report,
                json_output=json_output,
            )
            if prepared_candidate is None
            else prepared_candidate
        )
        if prepared_candidate is not None and (
            candidate.report != report or candidate.json_output is not json_output
        ):
            raise ValueError("Knowledge read presentation candidate differs")
    except Exception:  # noqa: BLE001 - the contract hard-stops seal failures.
        os._exit(1)
    fd = 1 if json_output or candidate.report.outcome == "succeeded" else 2
    write_binary_buffer_v1(
        candidate.buffer,
        fd=fd,
        max_chunk_size=_WRITE_CHUNK,
    )
    return candidate.report


def run_search(
    *,
    query: str,
    json_output: bool,
    cli_patch: tuple[tuple[str, str], ...],
) -> int:
    prepared_candidate: _PreparedKnowledgeReadPresentationV1 | None = None

    def seal_report(report: KnowledgeReadReportV1) -> KnowledgeReadReportV1:
        nonlocal prepared_candidate
        try:
            prepared_candidate = _prepare_knowledge_read_presentation_v1(
                report,
                json_output=json_output,
            )
        except Exception as error:
            raise _KnowledgeReadPresentationSealFailedV1 from error
        return prepared_candidate.report

    try:
        report = KnowledgeReadsV1.search(
            query,
            cli_patch=cli_patch,
            report_sealer=seal_report,
        )
    except _KnowledgeReadPresentationSealFailedV1:
        os._exit(1)
    prepared = _present_v1(
        report,
        json_output=json_output,
        prepared_candidate=prepared_candidate,
    )
    return {"succeeded": 0, "blocked": 2, "failed": 1}[prepared.outcome]


def run_show(
    *,
    candidate_id: str,
    json_output: bool,
    cli_patch: tuple[tuple[str, str], ...],
) -> int:
    prepared_candidate: _PreparedKnowledgeReadPresentationV1 | None = None

    def seal_report(report: KnowledgeReadReportV1) -> KnowledgeReadReportV1:
        nonlocal prepared_candidate
        try:
            prepared_candidate = _prepare_knowledge_read_presentation_v1(
                report,
                json_output=json_output,
            )
        except Exception as error:
            raise _KnowledgeReadPresentationSealFailedV1 from error
        return prepared_candidate.report

    try:
        report = KnowledgeReadsV1.show(
            candidate_id,
            cli_patch=cli_patch,
            report_sealer=seal_report,
        )
    except _KnowledgeReadPresentationSealFailedV1:
        os._exit(1)
    prepared = _present_v1(
        report,
        json_output=json_output,
        prepared_candidate=prepared_candidate,
    )
    return {"succeeded": 0, "blocked": 2, "failed": 1}[prepared.outcome]


def run_ask(
    *,
    question: str,
    json_output: bool,
    cli_patch: tuple[tuple[str, str], ...],
) -> int:
    prepared_candidate: _PreparedKnowledgeAskPresentationV1 | None = None
    candidate_token = 0
    cancellation = activate_knowledge_ask_cancellation_v1()

    def next_candidate_token_v1() -> int:
        nonlocal candidate_token
        if candidate_token >= 0xFFFFFFFF:
            raise RuntimeError("Knowledge ask candidate token space is exhausted")
        candidate_token += 1
        return candidate_token

    def cancellation_adjusted_report_v1(
        report: KnowledgeAskReportV1,
        snapshot: CancellationSnapshotV1,
    ) -> KnowledgeAskReportV1:
        if (
            snapshot.observed_monotonic_ns is not None
            and report.outcome == "blocked"
            and report.result is None
        ):
            return KnowledgeAskReportV1(
                outcome="interrupted",
                result=None,
                reason="user_interrupted_before_answer",
            )
        return report

    def seal_report(
        report: KnowledgeAskReportV1,
    ) -> KnowledgeAskReportV1:
        nonlocal prepared_candidate
        while True:
            snapshot = cancellation.snapshot_v1()
            sealed_report = cancellation_adjusted_report_v1(report, snapshot)
            unbound = _prepare_knowledge_ask_presentation_v1(
                sealed_report,
                json_output=json_output,
                answer_markdown_bytes=sealed_report.answer_markdown_bytes,
            )
            token = next_candidate_token_v1()
            pending = _bind_knowledge_ask_presentation_v1(
                unbound,
                expected_generation=snapshot.generation,
                candidate_token=token,
            )
            if not cancellation.conditional_seal_v1(
                expected_generation=pending.expected_generation,
                candidate_token=pending.candidate_token,
            ):
                continue
            cancellation.release_v1()
            prepared_candidate = pending
            return pending.report

    report = KnowledgeAsksV1.ask(
        question,
        cli_patch=cli_patch,
        cancellation=cancellation,
    )
    report = seal_report(report)
    if prepared_candidate is None:
        raise RuntimeError("Knowledge ask presentation candidate is absent")
    candidate = prepared_candidate
    if (
        candidate.report != report
        or candidate.json_output is not json_output
        or candidate.outcome != report.outcome
        or candidate.result != _freeze_json_value_v1(report.result)
    ):
        raise RuntimeError("Knowledge ask presentation candidate differs")
    if candidate.failure_kind == "diagnostic_projection_unrepresentable":
        if candidate.diagnostics is not None or candidate.envelope is not None:
            raise RuntimeError("Knowledge ask diagnostic projection candidate differs")
    else:
        projected = _build_knowledge_ask_diagnostics_v1(report)
        if type(projected) is not _KnowledgeAskDiagnosticsReadyV1 or (
            candidate.diagnostics != _freeze_json_value_v1(projected.diagnostics)
        ):
            raise RuntimeError("Knowledge ask presentation diagnostics differ")
    if candidate.disposition == "no_output_presentation_failure":
        if (
            candidate.failure_kind
            not in {
                "canonical_serialization_failed",
                "stdout_cap_exceeded",
                "diagnostic_projection_unrepresentable",
                "human_terminal_answer_bytes_rejected",
                "human_semantic_render_rejected",
                "human_utf8_encode_failed",
                "human_semantic_bytes_rejected",
                "human_semantic_bytes_too_large",
            }
            or candidate.buffer is not None
            or candidate.byte_length is not None
            or (
                candidate.failure_kind == "diagnostic_projection_unrepresentable"
                and (
                    candidate.diagnostics is not None or candidate.envelope is not None
                )
            )
            or (
                candidate.failure_kind
                in {"canonical_serialization_failed", "stdout_cap_exceeded"}
                and (
                    not candidate.json_output
                    or candidate.envelope is None
                    or candidate.diagnostics is None
                )
            )
            or (
                candidate.failure_kind
                in {
                    "human_terminal_answer_bytes_rejected",
                    "human_semantic_render_rejected",
                    "human_utf8_encode_failed",
                    "human_semantic_bytes_rejected",
                    "human_semantic_bytes_too_large",
                }
                and (
                    candidate.json_output
                    or candidate.envelope is not None
                    or candidate.diagnostics is None
                )
            )
        ):
            raise RuntimeError("Knowledge ask no-output candidate differs")
        os._exit(1)
        raise RuntimeError("Knowledge ask hard exit returned")
    if (
        candidate.disposition != "ready_bytes"
        or candidate.failure_kind is not None
        or type(candidate.buffer) is not bytes
        or candidate.byte_length != len(candidate.buffer)
    ):
        raise RuntimeError("Knowledge ask presentation buffer proof differs")
    buffer = candidate.buffer
    if candidate.json_output:
        write_knowledge_ask_json_buffer_v1(buffer)
    else:
        write_knowledge_ask_human_buffer_v1(buffer)
    return {"succeeded": 0, "blocked": 2, "failed": 1, "interrupted": 130}[
        report.outcome
    ]


@dataclass(frozen=True, slots=True)
class _FrozenJsonObjectV1:
    items: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class _FrozenJsonArrayV1:
    items: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class _KnowledgeAskDiagnosticsReadyV1:
    diagnostics: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class _DiagnosticProjectionUnrepresentableV1:
    pass


def _freeze_json_value_v1(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is dict:
        object_value = cast(dict[object, object], value)
        if any(type(key) is not str for key in object_value):
            raise TypeError("Knowledge ask JSON object key is invalid")
        keys = tuple(cast(str, key) for key in object_value)
        return _FrozenJsonObjectV1(
            tuple(
                (key, _freeze_json_value_v1(object_value[key])) for key in sorted(keys)
            )
        )
    if type(value) in {list, tuple}:
        sequence_value = cast(list[object] | tuple[object, ...], value)
        return _FrozenJsonArrayV1(
            tuple(_freeze_json_value_v1(item) for item in sequence_value)
        )
    raise TypeError("Knowledge ask JSON value is not immutable")


def _knowledge_ask_diagnostics_v1(
    report: KnowledgeAskReportV1,
) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = (
        []
        if report.reason is None
        else [{"code": _ASK_PRIMARY[report.reason][0], "context": {}}]
    )
    if report.capture_overflow_channels:
        diagnostics.append(
            {
                "code": "knowledge.ask.capture_overflow.v1",
                "context": {"channels": list(report.capture_overflow_channels)},
            }
        )
    orphan_supplementals = (
        (
            "knowledge.ask.orphan_quarantined.v1",
            report.orphan_quarantined_count,
        ),
        ("knowledge.ask.orphan_recovered.v1", report.orphan_recovered_count),
        (
            "knowledge.ask.orphan_recovery_failed.v1",
            report.orphan_recovery_failed_count,
        ),
        (
            "knowledge.ask.orphan_target_conflict.v1",
            report.orphan_target_conflict_count,
        ),
    )
    diagnostics.extend(
        {"code": code, "context": {"count": count}}
        for code, count in orphan_supplementals
        if count
    )
    return diagnostics


def _build_knowledge_ask_diagnostics_v1(
    report: KnowledgeAskReportV1,
) -> _KnowledgeAskDiagnosticsReadyV1 | _DiagnosticProjectionUnrepresentableV1:
    counts = (
        report.orphan_quarantined_count,
        report.orphan_recovered_count,
        report.orphan_recovery_failed_count,
        report.orphan_target_conflict_count,
    )
    if any(count > 9_223_372_036_854_775_807 for count in counts):
        return _DiagnosticProjectionUnrepresentableV1()
    return _KnowledgeAskDiagnosticsReadyV1(
        diagnostics=_knowledge_ask_diagnostics_v1(report)
    )


def _knowledge_ask_envelope_v1(
    report: KnowledgeAskReportV1,
    diagnostics: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": "gezhi.cli_result.v1",
        "command": "knowledge.ask",
        "outcome": report.outcome,
        "result": report.result,
        "diagnostics": diagnostics,
    }


def _capture_overflow_hint_v1(channels: tuple[str, ...]) -> str | None:
    if not channels:
        return None
    if channels == ("events",):
        return "Codex 事件捕获超过 16777216 字节上限，已保留精确上限前缀"
    if channels == ("final_message",):
        return "Codex 最终消息捕获超过 1048576 字节上限，已保留精确上限前缀"
    return "Codex 事件与最终消息捕获均超过各自上限，已保留精确上限前缀"


def _orphan_hints_v1(report: KnowledgeAskReportV1) -> tuple[str, ...]:
    observed: list[str] = []
    if report.orphan_quarantined_count:
        observed.append(
            f"发现 {report.orphan_quarantined_count} 个无法安全恢复的历史 "
            "Answer staging，已原地逻辑隔离"
        )
    if report.orphan_recovered_count:
        observed.append(
            f"已恢复并提交 {report.orphan_recovered_count} 个完整历史 Answer"
        )
    if report.orphan_recovery_failed_count:
        observed.append(
            f"有 {report.orphan_recovery_failed_count} 个历史 Answer 的确定性"
            "恢复提交失败，staging 已原地保留"
        )
    if report.orphan_target_conflict_count:
        observed.append(
            f"有 {report.orphan_target_conflict_count} 个历史 Answer 因同身份 "
            "target 已存在而未恢复"
        )
    return tuple(observed)


@dataclass(frozen=True, slots=True)
class _HumanTerminalAnswerReadyV1:
    answer_markdown_bytes: bytes
    answer_markdown_text: str


@dataclass(frozen=True, slots=True)
class _HumanSemanticTextReadyV1:
    text: str


@dataclass(frozen=True, slots=True)
class _HumanSemanticTextRejectedV1:
    pass


@dataclass(frozen=True, slots=True)
class _HumanSemanticBytesValidV1:
    buffer: bytes


@dataclass(frozen=True, slots=True)
class _HumanSemanticBytesRejectedV1:
    pass


@dataclass(frozen=True, slots=True)
class _HumanSemanticBytesWithinLimitV1:
    buffer: bytes


@dataclass(frozen=True, slots=True)
class _HumanSemanticBytesTooLargeV1:
    pass


def _read_committed_answer_for_human_v1(
    report: KnowledgeAskReportV1,
) -> _HumanTerminalAnswerReadyV1 | None:
    locator = report.committed_answer_locator
    if locator is None or report.result is None:
        raise ValueError("Knowledge ask committed Answer locator is absent")
    try:
        with open_validated_data_root_v1(locator.root_path) as root:
            observed = read_committed_answer_v1(root, locator.answer_id)
    except (DataRootOpenErrorV1, OSError):
        return None
    if (
        type(observed) is not TerminalAnswerBytesReadyV1
        or observed.answer_id != locator.answer_id
        or observed.manifest_sha256 != locator.manifest_sha256
        or observed.status != "succeeded"
        or type(observed.answer_markdown_bytes) is not bytes
        or type(observed.answer_markdown_text) is not str
    ):
        return None
    return _HumanTerminalAnswerReadyV1(
        answer_markdown_bytes=observed.answer_markdown_bytes,
        answer_markdown_text=observed.answer_markdown_text,
    )


def _render_knowledge_ask_human_text_v1(
    report: KnowledgeAskReportV1,
    *,
    terminal_answer: _HumanTerminalAnswerReadyV1 | None,
) -> _HumanSemanticTextReadyV1 | _HumanSemanticTextRejectedV1:
    if report.outcome == "succeeded":
        if (
            type(report.result) is not dict
            or type(terminal_answer) is not _HumanTerminalAnswerReadyV1
            or terminal_answer.answer_markdown_bytes.startswith(b"\xef\xbb\xbf")
            or b"\r" in terminal_answer.answer_markdown_bytes
            or b"\x00" in terminal_answer.answer_markdown_bytes
            or not terminal_answer.answer_markdown_bytes.endswith(b"\n")
        ):
            return _HumanSemanticTextRejectedV1()
        answer_id = report.result["answer_id"]
        if type(answer_id) is not str:
            return _HumanSemanticTextRejectedV1()
        lines = ["Knowledge ask：完成", f"Answer ID：{answer_id}"]
        lines.extend(f"提示：{hint}" for hint in _orphan_hints_v1(report))
        if (
            report.orphan_quarantined_count
            or report.orphan_recovery_failed_count
            or report.orphan_target_conflict_count
        ):
            next_step = (
                "运行 gezhi status 观察历史 Answer 异常；status 不会修复、"
                "移动、删除或恢复 Answer 目录"
            )
        else:
            next_step = "无需操作"
        lines.append(f"下一步：{next_step}")
        return _HumanSemanticTextReadyV1(
            text=("\n".join(lines) + "\n\n" + terminal_answer.answer_markdown_text)
        )

    if terminal_answer is not None or report.reason not in _ASK_PRIMARY:
        return _HumanSemanticTextRejectedV1()
    _code, reason, next_step = _ASK_PRIMARY[report.reason]
    heading = {
        "blocked": "Knowledge ask：已阻塞",
        "failed": "Knowledge ask：失败",
        "interrupted": "Knowledge ask：已中断",
    }[report.outcome]
    lines = [heading]
    if report.result is not None:
        answer_id = report.result["answer_id"]
        if type(answer_id) is not str:
            return _HumanSemanticTextRejectedV1()
        lines.append(f"Answer ID：{answer_id}")
    lines.append(f"原因：{reason}")
    hint = _capture_overflow_hint_v1(report.capture_overflow_channels)
    if hint is not None:
        lines.append(f"提示：{hint}")
    lines.extend(f"提示：{hint}" for hint in _orphan_hints_v1(report))
    lines.append(f"下一步：{next_step}")
    return _HumanSemanticTextReadyV1(text="\n".join(lines) + "\n")


def _validate_knowledge_ask_human_bytes_v1(
    report: KnowledgeAskReportV1,
    rendered: _HumanSemanticTextReadyV1,
    buffer: bytes,
    *,
    terminal_answer: _HumanTerminalAnswerReadyV1 | None,
) -> _HumanSemanticBytesValidV1 | _HumanSemanticBytesRejectedV1:
    if (
        type(buffer) is not bytes
        or buffer.startswith(b"\xef\xbb\xbf")
        or b"\r" in buffer
        or b"\x00" in buffer
        or b"\x1b" in buffer
        or not buffer.endswith(b"\n")
        or buffer.endswith(b"\n\n")
        or any(line.endswith((b" ", b"\t")) for line in buffer[:-1].split(b"\n"))
    ):
        return _HumanSemanticBytesRejectedV1()
    try:
        decoded = buffer.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return _HumanSemanticBytesRejectedV1()
    if decoded != rendered.text:
        return _HumanSemanticBytesRejectedV1()
    if report.outcome == "succeeded":
        if type(
            terminal_answer
        ) is not _HumanTerminalAnswerReadyV1 or not buffer.endswith(
            terminal_answer.answer_markdown_bytes
        ):
            return _HumanSemanticBytesRejectedV1()
        prefix = buffer[: -len(terminal_answer.answer_markdown_bytes)]
        if not prefix.endswith(b"\n\n"):
            return _HumanSemanticBytesRejectedV1()
    elif terminal_answer is not None:
        return _HumanSemanticBytesRejectedV1()
    return _HumanSemanticBytesValidV1(buffer=buffer)


def _check_knowledge_ask_human_cap_v1(
    validated: _HumanSemanticBytesValidV1,
) -> _HumanSemanticBytesWithinLimitV1 | _HumanSemanticBytesTooLargeV1:
    if len(validated.buffer) > _ASK_HUMAN_OUTPUT_CAP:
        return _HumanSemanticBytesTooLargeV1()
    return _HumanSemanticBytesWithinLimitV1(buffer=validated.buffer)


def _knowledge_ask_human_buffer_v1(
    report: KnowledgeAskReportV1,
    *,
    answer_markdown_bytes: bytes | None,
) -> bytes:
    validate_knowledge_ask_report_v1(report)
    terminal_answer: _HumanTerminalAnswerReadyV1 | None = None
    if answer_markdown_bytes is not None:
        terminal_answer = _HumanTerminalAnswerReadyV1(
            answer_markdown_bytes=answer_markdown_bytes,
            answer_markdown_text=answer_markdown_bytes.decode("utf-8", errors="strict"),
        )
    rendered = _render_knowledge_ask_human_text_v1(
        report,
        terminal_answer=terminal_answer,
    )
    if type(rendered) is not _HumanSemanticTextReadyV1:
        raise ValueError("Knowledge ask Human semantic text is invalid")
    try:
        payload = rendered.text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("Knowledge ask Human semantic text is invalid") from error
    validated = _validate_knowledge_ask_human_bytes_v1(
        report,
        rendered,
        payload,
        terminal_answer=terminal_answer,
    )
    if type(validated) is not _HumanSemanticBytesValidV1:
        raise ValueError("Knowledge ask Human semantic bytes are invalid")
    checked = _check_knowledge_ask_human_cap_v1(validated)
    if type(checked) is not _HumanSemanticBytesWithinLimitV1:
        raise ValueError("Knowledge ask Human output exceeds its byte limit")
    return checked.buffer


@dataclass(frozen=True, slots=True)
class _UnboundKnowledgeAskPresentationV1:
    report: KnowledgeAskReportV1
    outcome: str
    result: object
    diagnostics: _FrozenJsonArrayV1 | None
    envelope: _FrozenJsonObjectV1 | None
    disposition: Literal["ready_bytes", "no_output_presentation_failure"]
    failure_kind: _PresentationFailureKindV1 | None
    buffer: bytes | None
    byte_length: int | None
    json_output: bool


@dataclass(frozen=True, slots=True)
class _PreparedKnowledgeAskPresentationV1:
    expected_generation: int
    candidate_token: int
    report: KnowledgeAskReportV1
    outcome: str
    result: object
    diagnostics: _FrozenJsonArrayV1 | None
    envelope: _FrozenJsonObjectV1 | None
    disposition: Literal["ready_bytes", "no_output_presentation_failure"]
    failure_kind: _PresentationFailureKindV1 | None
    buffer: bytes | None
    byte_length: int | None
    json_output: bool


def _prepare_knowledge_ask_presentation_v1(
    report: KnowledgeAskReportV1,
    *,
    json_output: bool,
    answer_markdown_bytes: bytes | None,
) -> _UnboundKnowledgeAskPresentationV1:
    validate_knowledge_ask_report_v1(report)
    if type(json_output) is not bool:
        raise TypeError("Knowledge ask presentation mode is invalid")
    if answer_markdown_bytes is not report.answer_markdown_bytes:
        raise ValueError("Knowledge ask committed Markdown identity differs")
    frozen_result = _freeze_json_value_v1(report.result)
    projected = _build_knowledge_ask_diagnostics_v1(report)
    if type(projected) is _DiagnosticProjectionUnrepresentableV1:
        return _UnboundKnowledgeAskPresentationV1(
            report=report,
            outcome=report.outcome,
            result=frozen_result,
            diagnostics=None,
            envelope=None,
            disposition="no_output_presentation_failure",
            failure_kind="diagnostic_projection_unrepresentable",
            buffer=None,
            byte_length=None,
            json_output=json_output,
        )
    if type(projected) is not _KnowledgeAskDiagnosticsReadyV1:
        raise RuntimeError("Knowledge ask diagnostic projection verdict is invalid")
    diagnostics = projected.diagnostics
    frozen_diagnostics = _freeze_json_value_v1(diagnostics)
    if type(frozen_diagnostics) is not _FrozenJsonArrayV1:
        raise RuntimeError("Knowledge ask diagnostics freeze proof differs")
    envelope: _FrozenJsonObjectV1 | None = None
    buffer: bytes
    if json_output:
        envelope_value = _knowledge_ask_envelope_v1(report, diagnostics)
        frozen_envelope = _freeze_json_value_v1(envelope_value)
        if type(frozen_envelope) is not _FrozenJsonObjectV1:
            raise RuntimeError("Knowledge ask envelope freeze proof differs")
        envelope = frozen_envelope
        try:
            buffer = (
                json.dumps(
                    envelope_value,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8", errors="strict")
                + b"\n"
            )
        except (TypeError, ValueError):
            return _UnboundKnowledgeAskPresentationV1(
                report=report,
                outcome=report.outcome,
                result=frozen_result,
                diagnostics=frozen_diagnostics,
                envelope=envelope,
                disposition="no_output_presentation_failure",
                failure_kind="canonical_serialization_failed",
                buffer=None,
                byte_length=None,
                json_output=True,
            )
        if len(buffer) > _ASK_JSON_OUTPUT_CAP:
            return _UnboundKnowledgeAskPresentationV1(
                report=report,
                outcome=report.outcome,
                result=frozen_result,
                diagnostics=frozen_diagnostics,
                envelope=envelope,
                disposition="no_output_presentation_failure",
                failure_kind="stdout_cap_exceeded",
                buffer=None,
                byte_length=None,
                json_output=True,
            )
    else:
        terminal_answer: _HumanTerminalAnswerReadyV1 | None = None
        if report.outcome == "succeeded":
            terminal_answer = _read_committed_answer_for_human_v1(report)
            if terminal_answer is None:
                return _UnboundKnowledgeAskPresentationV1(
                    report=report,
                    outcome=report.outcome,
                    result=frozen_result,
                    diagnostics=frozen_diagnostics,
                    envelope=None,
                    disposition="no_output_presentation_failure",
                    failure_kind="human_terminal_answer_bytes_rejected",
                    buffer=None,
                    byte_length=None,
                    json_output=False,
                )
        rendered = _render_knowledge_ask_human_text_v1(
            report,
            terminal_answer=terminal_answer,
        )
        if type(rendered) is _HumanSemanticTextRejectedV1:
            return _UnboundKnowledgeAskPresentationV1(
                report=report,
                outcome=report.outcome,
                result=frozen_result,
                diagnostics=frozen_diagnostics,
                envelope=None,
                disposition="no_output_presentation_failure",
                failure_kind="human_semantic_render_rejected",
                buffer=None,
                byte_length=None,
                json_output=False,
            )
        if type(rendered) is not _HumanSemanticTextReadyV1:
            raise RuntimeError("Knowledge ask Human renderer verdict is invalid")
        try:
            buffer = rendered.text.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            return _UnboundKnowledgeAskPresentationV1(
                report=report,
                outcome=report.outcome,
                result=frozen_result,
                diagnostics=frozen_diagnostics,
                envelope=None,
                disposition="no_output_presentation_failure",
                failure_kind="human_utf8_encode_failed",
                buffer=None,
                byte_length=None,
                json_output=False,
            )
        validated = _validate_knowledge_ask_human_bytes_v1(
            report,
            rendered,
            buffer,
            terminal_answer=terminal_answer,
        )
        if type(validated) is _HumanSemanticBytesRejectedV1:
            return _UnboundKnowledgeAskPresentationV1(
                report=report,
                outcome=report.outcome,
                result=frozen_result,
                diagnostics=frozen_diagnostics,
                envelope=None,
                disposition="no_output_presentation_failure",
                failure_kind="human_semantic_bytes_rejected",
                buffer=None,
                byte_length=None,
                json_output=False,
            )
        if type(validated) is not _HumanSemanticBytesValidV1:
            raise RuntimeError("Knowledge ask Human bytes verdict is invalid")
        checked = _check_knowledge_ask_human_cap_v1(validated)
        if type(checked) is _HumanSemanticBytesTooLargeV1:
            return _UnboundKnowledgeAskPresentationV1(
                report=report,
                outcome=report.outcome,
                result=frozen_result,
                diagnostics=frozen_diagnostics,
                envelope=None,
                disposition="no_output_presentation_failure",
                failure_kind="human_semantic_bytes_too_large",
                buffer=None,
                byte_length=None,
                json_output=False,
            )
        if type(checked) is not _HumanSemanticBytesWithinLimitV1:
            raise RuntimeError("Knowledge ask Human capacity verdict is invalid")
        if checked.buffer is not buffer:
            raise RuntimeError("Knowledge ask Human buffer identity changed")
        buffer = checked.buffer
    return _UnboundKnowledgeAskPresentationV1(
        report=report,
        outcome=report.outcome,
        result=frozen_result,
        diagnostics=frozen_diagnostics,
        envelope=envelope,
        disposition="ready_bytes",
        failure_kind=None,
        buffer=buffer,
        byte_length=len(buffer),
        json_output=json_output,
    )


def _bind_knowledge_ask_presentation_v1(
    unbound: _UnboundKnowledgeAskPresentationV1,
    *,
    expected_generation: int,
    candidate_token: int,
) -> _PreparedKnowledgeAskPresentationV1:
    if type(unbound) is not _UnboundKnowledgeAskPresentationV1:
        raise TypeError("Knowledge ask unbound presentation type is invalid")
    if (
        type(expected_generation) is not int
        or not 0 <= expected_generation <= 0x0FFFFFFF
        or type(candidate_token) is not int
        or not 1 <= candidate_token <= 0xFFFFFFFF
    ):
        raise ValueError("Knowledge ask presentation binding is invalid")
    return _PreparedKnowledgeAskPresentationV1(
        expected_generation=expected_generation,
        candidate_token=candidate_token,
        report=unbound.report,
        outcome=unbound.outcome,
        result=unbound.result,
        diagnostics=unbound.diagnostics,
        envelope=unbound.envelope,
        disposition=unbound.disposition,
        failure_kind=unbound.failure_kind,
        buffer=unbound.buffer,
        byte_length=unbound.byte_length,
        json_output=unbound.json_output,
    )


__all__ = [
    "build_knowledge_read_human_buffer_v1",
    "build_knowledge_read_json_buffer_v1",
    "run_ask",
    "run_search",
    "run_show",
]
