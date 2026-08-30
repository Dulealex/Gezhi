from __future__ import annotations

import json
import msvcrt
import os

from gezhi._knowledge_read import KnowledgeReadReportV1, KnowledgeReadsV1
from gezhi._knowledge_registry import canonical_json_bytes_v1

_OUTPUT_CAP = 1_048_576
_WRITE_CHUNK = 65_536
_DISCLOSURE = (
    "治理说明：以下结果仅为已审核但尚未晋升的 Candidate Knowledge，"
    "不代表已晋升知识、已验证事实或自动蕴含证明。"
)
_WITHDRAWN_WARNING = (
    "注意：该 Candidate 已撤回，不参与 search 或 ask 检索；以下内容仅供历史审计。"
)

_REASONS = {
    "knowledge.search": frozenset(
        {
            "invalid_query",
            "query_too_large",
            "query_too_complex",
            "configuration_invalid",
            "configuration_incompatible",
            "data_root_unavailable",
            "data_root_unsafe",
            "data_root_identity_unavailable",
            "registry_unavailable",
            "registry_incompatible",
            "fts5_unavailable",
            "result_too_large",
            "data_root_integrity_lost",
            "registry_corrupt",
            "retrieval_query_failed",
            "retrieval_materialization_failed",
        }
    ),
    "knowledge.show": frozenset(
        {
            "invalid_candidate_id",
            "configuration_invalid",
            "configuration_incompatible",
            "data_root_unavailable",
            "data_root_unsafe",
            "data_root_identity_unavailable",
            "registry_unavailable",
            "registry_incompatible",
            "candidate_not_found",
            "result_too_large",
            "data_root_integrity_lost",
            "registry_corrupt",
            "registry_read_failed",
            "candidate_corrupt",
            "evidence_corrupt",
        }
    ),
}

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
    if report.outcome == "succeeded":
        if report.reason is not None:
            raise ValueError("successful Knowledge read has a reason")
        return []
    if report.reason is None or report.reason not in _REASONS[report.command]:
        raise ValueError("unsuccessful Knowledge read has an invalid reason")
    return [
        {
            "code": f"{report.command}.{report.reason}.v1",
            "context": {},
        }
    ]


def _envelope_v1(report: KnowledgeReadReportV1) -> dict[str, object]:
    diagnostics = _diagnostics_v1(report)
    if report.outcome == "succeeded":
        if report.result is None or diagnostics:
            raise ValueError("successful Knowledge read envelope is invalid")
    elif report.result is not None or len(diagnostics) != 1:
        raise ValueError("unsuccessful Knowledge read envelope is invalid")
    return {
        "command": report.command,
        "diagnostics": diagnostics,
        "outcome": report.outcome,
        "result": report.result,
        "schema_version": "gezhi.cli_result.v1",
    }


def _json_buffer_without_cap_v1(report: KnowledgeReadReportV1) -> bytes:
    return canonical_json_bytes_v1(_envelope_v1(report)) + b"\n"


def _apply_result_cap_v1(report: KnowledgeReadReportV1) -> KnowledgeReadReportV1:
    if report.outcome != "succeeded":
        return report
    if len(_json_buffer_without_cap_v1(report)) <= _OUTPUT_CAP:
        return report
    return KnowledgeReadReportV1(
        command=report.command,
        outcome="blocked",
        result=None,
        reason="result_too_large",
    )


def build_knowledge_read_json_buffer_v1(report: KnowledgeReadReportV1) -> bytes:
    prepared = _apply_result_cap_v1(report)
    buffer = _json_buffer_without_cap_v1(prepared)
    if len(buffer) > _OUTPUT_CAP:
        raise ValueError("Knowledge read diagnostic exceeds the output cap")
    return buffer


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


def build_knowledge_read_human_buffer_v1(report: KnowledgeReadReportV1) -> bytes:
    prepared = _apply_result_cap_v1(report)
    if prepared.outcome != "succeeded":
        if prepared.reason is None or prepared.reason not in _HUMAN_DIAGNOSTICS:
            raise ValueError("Knowledge read Human diagnostic is invalid")
        return (_HUMAN_DIAGNOSTICS[prepared.reason] + "\n").encode("utf-8")
    result = prepared.result
    if type(result) is not dict:
        raise TypeError("Knowledge read Human result is invalid")
    heading = (
        "Knowledge 候选搜索"
        if prepared.command == "knowledge.search"
        else "Knowledge 候选详情"
    )
    lines = [heading, _DISCLOSURE]
    for key in sorted(result):
        item = result[key]
        lines.extend(_human_container_lines_v1({key: item}, depth=0))
        if (
            prepared.command == "knowledge.show"
            and key == "governance"
            and type(item) is dict
            and item.get("intake_status") == "withdrawn"
        ):
            lines.append(_WITHDRAWN_WARNING)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_buffer_v1(buffer: bytes, *, fd: int) -> None:
    try:
        msvcrt.setmode(fd, os.O_BINARY)
    except OSError:
        os._exit(1)
    view = memoryview(buffer)
    offset = 0
    while offset < len(buffer):
        requested = min(_WRITE_CHUNK, len(buffer) - offset)
        current = view[offset : offset + requested]
        if (
            current.obj is not buffer
            or current.nbytes != requested
            or not 1 <= requested <= _WRITE_CHUNK
        ):
            raise RuntimeError("Knowledge read write view invariant failed")
        try:
            count = os.write(fd, current)
        except OSError:
            os._exit(1)
        if type(count) is not int or not 1 <= count <= requested:
            os._exit(1)
        offset += count


def _present_v1(
    report: KnowledgeReadReportV1,
    *,
    json_output: bool,
) -> KnowledgeReadReportV1:
    try:
        prepared = _apply_result_cap_v1(report)
        buffer = (
            build_knowledge_read_json_buffer_v1(prepared)
            if json_output
            else build_knowledge_read_human_buffer_v1(prepared)
        )
    except Exception:  # noqa: BLE001 - the contract hard-stops seal failures.
        os._exit(1)
    fd = 1 if json_output or prepared.outcome == "succeeded" else 2
    _write_buffer_v1(buffer, fd=fd)
    return prepared


def run_search(
    *,
    query: str,
    json_output: bool,
    cli_patch: tuple[tuple[str, str], ...],
) -> int:
    report = KnowledgeReadsV1.search(query, cli_patch=cli_patch)
    prepared = _present_v1(report, json_output=json_output)
    return {"succeeded": 0, "blocked": 2, "failed": 1}[prepared.outcome]


def run_show(
    *,
    candidate_id: str,
    json_output: bool,
    cli_patch: tuple[tuple[str, str], ...],
) -> int:
    report = KnowledgeReadsV1.show(candidate_id, cli_patch=cli_patch)
    prepared = _present_v1(report, json_output=json_output)
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
