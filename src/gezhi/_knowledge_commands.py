from __future__ import annotations

import json
import os
from dataclasses import dataclass

from gezhi._knowledge_read import (
    KnowledgeReadReportV1,
    KnowledgeReadsV1,
    validate_knowledge_read_report_v1,
)
from gezhi._presentation import (
    CliJsonOutputTooLargeV1,
    cli_json_buffer_v1,
    write_binary_buffer_v1,
)

_OUTPUT_CAP = 1_048_576
_WRITE_CHUNK = 65_536
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
            prepared.json_buffer
            if json_output
            else _human_buffer_v1(prepared.report)
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
    del question, json_output, cli_patch
    raise RuntimeError("Knowledge ask is not implemented")


__all__ = [
    "build_knowledge_read_human_buffer_v1",
    "build_knowledge_read_json_buffer_v1",
    "run_ask",
    "run_search",
    "run_show",
]
