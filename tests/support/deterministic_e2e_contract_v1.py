from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping

_WORK_ID = re.compile(
    r"^wrk_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SOURCE_ID = re.compile(r"^src_[0-9a-f]{24}$")
_CANDIDATE_ID = re.compile(r"^cand_[0-9a-f]{24}$")
_HANDOFF_ID = re.compile(r"^hnd_[0-9a-f]{24}$")
_ANSWER_ID = re.compile(
    r"^ans_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STAGES = (
    "ingest",
    "ocr",
    "canonicalize",
    "read",
    "review",
    "handoff",
    "knowledge_import",
)
_STAGE_STATUSES = {
    "pending",
    "running",
    "succeeded",
    "blocked",
    "failed",
    "interrupted",
}
_MAX_INT64 = 9_223_372_036_854_775_807
_ANSWER_STATUS_ORDER = ("succeeded", "blocked", "failed", "interrupted")
_SUMMARY_PRIORITY = (
    "inconsistent",
    "quarantined",
    "orphaned",
    "staging",
    "partial",
    "failed",
    "blocked",
    "interrupted",
    "running",
    "pending",
    "succeeded",
)
_OPERATIONAL_HUMAN = {
    "empty": "空",
    "pending": "待处理",
    "running": "运行中",
    "succeeded": "完成",
    "blocked": "受阻",
    "failed": "失败",
    "interrupted": "已中断",
    "partial": "部分可用",
    "staging": "存在暂存结果",
    "orphaned": "存在待恢复结果",
    "quarantined": "存在隔离结果",
    "inconsistent": "状态不一致",
}
_AVAILABILITY_HUMAN = {
    "ready": "就绪",
    "partial": "部分可用",
    "unavailable": "不可用",
    "unsafe": "不安全",
}
_HANDOFF_HUMAN = {
    "none": "无",
    "pending": "待处理",
    "available": "可用",
    "blocked": "受阻",
    "failed": "失败",
    "inconsistent": "不一致",
}
_NEXT_ACTION_HUMAN = {
    "none": "当前无需操作。",
    "add_work": "运行 gezhi literature add <pdf_path> 添加 Work。",
    "inspect_work": "运行 gezhi status <work_id> 查看需要处理的 Work。",
    "review_candidate": "使用 Review Queue 中的 Candidate ID 运行 gezhi literature review。",
    "repair_data_root": "在外部恢复或修复 Data Root 后重试。",
    "inspect_recovery": "停止相关写入、保留现场并进行维护检查。",
}
_KNOWLEDGE_LABELS = {
    "action": "动作 [action]",
    "arxiv_id": "arXiv ID [arxiv_id]",
    "author_count": "作者总数 [author_count]",
    "block_id": "Block ID [block_id]",
    "candidate": "Candidate [candidate]",
    "candidate_count": "Candidate 数量 [candidate_count]",
    "candidate_id": "Candidate ID [candidate_id]",
    "candidate_type": "Candidate 类型 [candidate_type]",
    "candidates_sha256": "candidates.jsonl SHA-256 [candidates_sha256]",
    "canonical_content_sha256": "Canonical 内容 SHA-256 [canonical_content_sha256]",
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


def _exact(value: object, keys: set[str]) -> dict[str, object]:
    assert type(value) is dict
    assert set(value) == keys
    return value


def _canonical_object_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _assert_sha256(value: object) -> str:
    assert type(value) is str
    assert _SHA256.fullmatch(value) is not None
    return value


def _assert_work_id(value: object) -> str:
    assert type(value) is str
    assert _WORK_ID.fullmatch(value) is not None
    return value


def _assert_count(value: object, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    assert type(value) is int
    assert minimum <= value <= _MAX_INT64
    return value


def _assert_source_id(value: object, source_sha256: str | None = None) -> str:
    assert type(value) is str
    assert _SOURCE_ID.fullmatch(value) is not None
    if source_sha256 is not None:
        assert value == "src_" + source_sha256[:24]
    return value


def _assert_candidate_v1(value: object) -> dict[str, object]:
    candidate = _exact(
        value,
        {"candidate_id", "payload", "payload_sha256", "schema_version"},
    )
    assert candidate["schema_version"] == "gezhi.candidate_knowledge.v1"
    payload = _exact(
        candidate["payload"],
        {
            "candidate_type",
            "canonical_content_sha256",
            "descriptor_refs",
            "schema_version",
            "source_id",
            "source_sha256",
            "statement",
            "work_id",
        },
    )
    assert payload["candidate_type"] in {
        "method",
        "claim",
        "limitation",
        "open_question",
    }
    assert payload["schema_version"] == "gezhi.candidate_payload.v1"
    source_sha256 = _assert_sha256(payload["source_sha256"])
    _assert_source_id(payload["source_id"], source_sha256)
    canonical_sha256 = _assert_sha256(payload["canonical_content_sha256"])
    _assert_work_id(payload["work_id"])
    assert payload["descriptor_refs"] == []
    statement = _exact(
        payload["statement"],
        {
            "evidence_pointers",
            "risk_flags",
            "source_terms",
            "support_kind",
            "text",
        },
    )
    assert statement["support_kind"] in {"direct", "synthesized", "interpretive"}
    assert type(statement["text"]) is str and statement["text"]
    assert type(statement["risk_flags"]) is list
    assert type(statement["source_terms"]) is list
    pointers = statement["evidence_pointers"]
    assert type(pointers) is list and pointers
    for pointer_value in pointers:
        pointer = _exact(
            pointer_value,
            {"block_id", "canonical_content_sha256", "schema_version"},
        )
        assert pointer["schema_version"] == "gezhi.evidence_pointer.v1"
        assert type(pointer["block_id"]) is str and pointer["block_id"]
        assert pointer["canonical_content_sha256"] == canonical_sha256
    payload_sha256 = hashlib.sha256(_canonical_object_bytes(payload)).hexdigest()
    assert candidate["payload_sha256"] == payload_sha256
    candidate_id = candidate["candidate_id"]
    assert type(candidate_id) is str
    assert _CANDIDATE_ID.fullmatch(candidate_id) is not None
    assert candidate_id == "cand_" + payload_sha256[:24]
    return candidate


def _assert_governance_v1(value: object) -> dict[str, object]:
    governance = _exact(
        value,
        {"intake_status", "promotion_status", "review_status"},
    )
    assert governance["intake_status"] in {"active", "withdrawn"}
    assert governance["promotion_status"] == "not_promoted"
    assert governance["review_status"] in {"accepted", "rejected", "deferred"}
    return governance


def _assert_import_v1(value: object) -> dict[str, object]:
    imported = _exact(
        value,
        {
            "action",
            "candidates_sha256",
            "handoff_id",
            "manifest_sha256",
            "review_revision",
        },
    )
    assert imported["action"] in {"accept", "withdraw"}
    _assert_sha256(imported["candidates_sha256"])
    _assert_sha256(imported["manifest_sha256"])
    assert type(imported["handoff_id"]) is str
    assert _HANDOFF_ID.fullmatch(imported["handoff_id"]) is not None
    assert type(imported["review_revision"]) is int
    assert imported["review_revision"] >= 1
    return imported


def _assert_evidence_v1(value: object, canonical_sha256: str) -> None:
    assert type(value) is list and value
    for snapshot_value in value:
        snapshot = _exact(snapshot_value, {"excerpt", "page_index", "pointer"})
        assert type(snapshot["excerpt"]) is str and snapshot["excerpt"]
        assert snapshot["page_index"] is None or type(snapshot["page_index"]) is int
        pointer = _exact(
            snapshot["pointer"],
            {"block_id", "canonical_content_sha256", "schema_version"},
        )
        assert pointer["schema_version"] == "gezhi.evidence_pointer.v1"
        assert type(pointer["block_id"]) is str and pointer["block_id"]
        assert pointer["canonical_content_sha256"] == canonical_sha256


def _assert_search_v1(result: dict[str, object]) -> None:
    _exact(
        result,
        {"candidate_count", "items", "query", "result_kind", "schema_version"},
    )
    assert result["schema_version"] == "gezhi.knowledge_search_result.v1"
    assert result["result_kind"] == "candidate_backed"
    assert type(result["query"]) is str and result["query"]
    items = result["items"]
    assert type(items) is list
    assert type(result["candidate_count"]) is int
    assert result["candidate_count"] == len(items)
    for rank, item_value in enumerate(items, start=1):
        item = _exact(item_value, {"candidate", "governance", "rank"})
        assert item["rank"] == rank
        _assert_candidate_v1(item["candidate"])
        assert _assert_governance_v1(item["governance"]) == {
            "intake_status": "active",
            "promotion_status": "not_promoted",
            "review_status": "accepted",
        }


def _assert_show_v1(result: dict[str, object]) -> None:
    _exact(
        result,
        {
            "candidate",
            "citation",
            "content_import",
            "descriptor_snapshots",
            "evidence_snapshots",
            "governance",
            "result_kind",
            "schema_version",
            "status_import",
        },
    )
    assert result["schema_version"] == "gezhi.knowledge_show_result.v1"
    assert result["result_kind"] == "candidate_backed"
    candidate = _assert_candidate_v1(result["candidate"])
    payload = candidate["payload"]
    assert type(payload) is dict
    citation = _exact(
        result["citation"],
        {
            "arxiv_id",
            "author_count",
            "doi",
            "primary_authors",
            "source_id",
            "source_sha256",
            "title",
            "work_id",
            "year",
        },
    )
    assert citation["work_id"] == payload["work_id"]
    assert citation["source_id"] == payload["source_id"]
    assert citation["source_sha256"] == payload["source_sha256"]
    assert type(citation["primary_authors"]) is list
    assert result["descriptor_snapshots"] == []
    _assert_evidence_v1(
        result["evidence_snapshots"], str(payload["canonical_content_sha256"])
    )
    governance = _assert_governance_v1(result["governance"])
    content_import = _assert_import_v1(result["content_import"])
    status_import = _assert_import_v1(result["status_import"])
    assert content_import["action"] == "accept"
    if governance["intake_status"] == "active":
        assert governance["review_status"] == "accepted"
        assert status_import == content_import
    else:
        assert status_import["action"] == "withdraw"
        assert status_import["review_revision"] > content_import["review_revision"]


def _assert_answer_output_v1(value: object) -> None:
    output = _exact(
        value,
        {
            "answer_status",
            "answer_units",
            "insufficiency_reason",
            "qualification_units",
            "schema_version",
        },
    )
    assert output["schema_version"] == "gezhi.answer_output.v1"
    assert output["answer_status"] in {"answered", "insufficient_evidence"}
    for collection, limit in (("answer_units", 12), ("qualification_units", 4)):
        units = output[collection]
        assert type(units) is list and len(units) <= limit
        candidate_ids: list[str] = []
        for unit_value in units:
            unit = _exact(unit_value, {"candidate_id", "text"})
            assert type(unit["candidate_id"]) is str
            assert _CANDIDATE_ID.fullmatch(unit["candidate_id"]) is not None
            assert type(unit["text"]) is str and unit["text"]
            candidate_ids.append(unit["candidate_id"])
        assert len(candidate_ids) == len(set(candidate_ids))
    if output["answer_status"] == "answered":
        assert output["answer_units"]
        assert output["insufficiency_reason"] is None
    else:
        assert output["answer_units"] == []
        assert output["qualification_units"] == []
        assert output["insufficiency_reason"] in {
            "no_matching_candidates",
            "retrieved_candidates_not_responsive",
            "unresolved_evidence_conflict",
            "evidence_support_too_weak",
        }


def _assert_status_v1(result: dict[str, object]) -> None:
    _exact(
        result,
        {
            "knowledge",
            "literature",
            "next_action",
            "recovery",
            "schema_version",
            "scope",
            "status",
            "work_id",
        },
    )
    assert result["schema_version"] == "gezhi.status_result.v1"
    assert result["scope"] == "work"
    _assert_work_id(result["work_id"])
    assert result["status"] in _OPERATIONAL_HUMAN
    assert result["next_action"] in {*_NEXT_ACTION_HUMAN, "resume_work"}
    literature = _exact(
        result["literature"],
        {"availability", "handoff_status", "review_counts", "stages"},
    )
    assert literature["availability"] in {"ready", "partial"}
    assert literature["handoff_status"] in _HANDOFF_HUMAN
    stages = literature["stages"]
    assert type(stages) is list and len(stages) == len(_STAGES)
    for expected_stage, stage_value in zip(_STAGES, stages, strict=True):
        stage = _exact(stage_value, {"stage", "status"})
        assert stage["stage"] == expected_stage
        assert stage["status"] in _STAGE_STATUSES
    review = _exact(
        literature["review_counts"],
        {"accepted", "deferred", "pending", "rejected"},
    )
    assert all(_assert_count(review[key]) >= 0 for key in review)
    knowledge = _exact(
        result["knowledge"],
        {"availability", "candidate_counts", "related_answer_status_counts"},
    )
    assert knowledge["availability"] in {"ready", "partial"}
    counts = _exact(knowledge["candidate_counts"], {"active", "withdrawn"})
    assert all(_assert_count(counts[key]) >= 0 for key in counts)
    answer_counts = knowledge["related_answer_status_counts"]
    assert type(answer_counts) is list
    observed_statuses: list[str] = []
    for count_value in answer_counts:
        count = _exact(count_value, {"count", "status"})
        assert count["status"] in _ANSWER_STATUS_ORDER
        _assert_count(count["count"], positive=True)
        observed_statuses.append(str(count["status"]))
    assert len(observed_statuses) == len(set(observed_statuses))
    assert observed_statuses == [
        status for status in _ANSWER_STATUS_ORDER if status in observed_statuses
    ]
    recovery = _exact(
        result["recovery"],
        {
            "inconsistent_count",
            "orphaned_count",
            "quarantined_count",
            "staging_count",
        },
    )
    assert all(_assert_count(recovery[key]) >= 0 for key in recovery)

    statuses = {str(stage["status"]) for stage in stages}
    statuses.update(observed_statuses)
    recovery_status = next(
        (
            status
            for status, key in (
                ("inconsistent", "inconsistent_count"),
                ("quarantined", "quarantined_count"),
                ("orphaned", "orphaned_count"),
                ("staging", "staging_count"),
            )
            if recovery[key]
        ),
        None,
    )
    if recovery_status is not None:
        statuses.add(recovery_status)
    if literature["availability"] != "ready" or knowledge["availability"] != "ready":
        statuses.add("partial")
    expected_status = next(status for status in _SUMMARY_PRIORITY if status in statuses)
    assert result["status"] == expected_status

    if recovery_status is not None:
        expected_action = "inspect_recovery"
    elif literature["availability"] in {"unavailable", "unsafe"} or knowledge[
        "availability"
    ] in {"unavailable", "unsafe"}:
        expected_action = "repair_data_root"
    elif expected_status == "running":
        expected_action = "none"
    elif review["pending"]:
        expected_action = "review_candidate"
    elif expected_status == "succeeded":
        expected_action = "none"
    else:
        expected_action = "resume_work"
    assert result["next_action"] == expected_action


def _assert_doctor_v1(result: dict[str, object]) -> None:
    _exact(result, {"checks", "overall_status", "schema_version"})
    assert result["schema_version"] == "gezhi.doctor_result.v1"
    assert result["overall_status"] == "ready"
    assert result["checks"] == [
        {"id": check_id, "status": "ready"}
        for check_id in (
            "configuration",
            "core_python",
            "core_dependencies",
            "literature_data_root",
            "knowledge_data_root",
            "ocr_runtime",
            "codex_runtime",
        )
    ]


def assert_command_result_v1(command: str, result: object) -> None:
    assert type(result) is dict
    if command == "literature.add":
        value = _exact(
            result,
            {
                "active_source_changed",
                "disposition",
                "schema_version",
                "source_id",
                "source_sha256",
                "work_id",
            },
        )
        assert type(value["active_source_changed"]) is bool
        assert value["disposition"] in {"created_work", "added_source", "reused_source"}
        assert value["schema_version"] == "gezhi.literature_add_result.v1"
        source_sha256 = _assert_sha256(value["source_sha256"])
        _assert_source_id(value["source_id"], source_sha256)
        _assert_work_id(value["work_id"])
    elif command == "literature.resume":
        value = _exact(
            result,
            {
                "active_source_id",
                "advanced_stages",
                "pending_candidate_ids",
                "pipeline_complete",
                "schema_version",
                "start_stage",
                "stop_stage",
                "work_id",
            },
        )
        _assert_source_id(value["active_source_id"])
        _assert_work_id(value["work_id"])
        assert value["schema_version"] == "gezhi.literature_resume_result.v1"
        assert type(value["advanced_stages"]) is list
        assert list(dict.fromkeys(value["advanced_stages"])) == value["advanced_stages"]
        assert all(stage in _STAGES[1:] for stage in value["advanced_stages"])
        assert type(value["pending_candidate_ids"]) is list
        assert all(
            type(candidate_id) is str
            and _CANDIDATE_ID.fullmatch(candidate_id) is not None
            for candidate_id in value["pending_candidate_ids"]
        )
        assert type(value["pipeline_complete"]) is bool
        assert value["start_stage"] in {*_STAGES[1:], "complete"}
        assert value["stop_stage"] in {*_STAGES[1:], "complete"}
        assert value["pipeline_complete"] == (
            value["stop_stage"] == "complete" and value["pending_candidate_ids"] == []
        )
    elif command == "literature.review":
        value = _exact(
            result,
            {
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
            },
        )
        assert type(value["candidate_id"]) is str
        payload_sha256 = _assert_sha256(value["payload_sha256"])
        assert value["candidate_id"] == "cand_" + payload_sha256[:24]
        assert value["decision_disposition"] in {"created", "unchanged"}
        assert value["handoff_action"] in {"accept", "withdraw", "none"}
        assert value["handoff_status"] in {"committed", "not_required", "pending"}
        assert value["import_status"] in {"applied", "not_required", "pending"}
        assert value["intake_status"] in {"active", "withdrawn", None}
        assert type(value["review_revision"]) is int and value["review_revision"] >= 1
        assert value["review_status"] in {"accepted", "rejected", "deferred"}
        assert value["schema_version"] == "gezhi.literature_review_result.v1"
        _assert_work_id(value["work_id"])
        if value["handoff_action"] == "none":
            assert value["handoff_id"] is None
            assert value["import_status"] == "not_required"
            assert value["intake_status"] is None
        else:
            assert type(value["handoff_id"]) is str
            assert _HANDOFF_ID.fullmatch(value["handoff_id"]) is not None
            expected_intake = (
                "active" if value["handoff_action"] == "accept" else "withdrawn"
            )
            assert (
                value["handoff_status"],
                value["import_status"],
                value["intake_status"],
            ) in {
                ("pending", "pending", None),
                ("committed", "pending", None),
                ("committed", "applied", expected_intake),
            }
    elif command == "knowledge.search":
        _assert_search_v1(result)
    elif command == "knowledge.show":
        _assert_show_v1(result)
    elif command == "knowledge.ask":
        value = _exact(result, {"answer_id", "answer_output"})
        assert type(value["answer_id"]) is str
        assert _ANSWER_ID.fullmatch(value["answer_id"]) is not None
        _assert_answer_output_v1(value["answer_output"])
    elif command == "status":
        _assert_status_v1(result)
    elif command == "doctor":
        _assert_doctor_v1(result)
    else:
        raise AssertionError(f"unexpected command: {command}")


def assert_diagnostic_matrix_v1(
    *,
    command: str,
    outcome: str,
    result: object,
    diagnostics: list[object],
) -> None:
    if outcome == "succeeded":
        assert result is not None
        assert diagnostics == []
        return
    if command == "literature.resume":
        assert type(result) is dict
        assert len(diagnostics) == 1
        diagnostic = _exact(diagnostics[0], {"code", "context"})
        context = _exact(diagnostic["context"], {"reason", "stage"})
        expected_code = (
            "literature.resume.stage_blocked.v1"
            if outcome == "blocked"
            else "literature.resume.stage_failed.v1"
        )
        assert diagnostic["code"] == expected_code
        assert context["stage"] == result["stop_stage"]
        assert context == (
            {"reason": "awaiting_review", "stage": "review"}
            if outcome == "blocked"
            else {"reason": "ocr_failed", "stage": "ocr"}
        )
        return
    if command == "knowledge.ask" and outcome == "blocked":
        assert result is None
        assert diagnostics == [
            {"code": "knowledge.ask.invalid_question.v1", "context": {}}
        ]
        return
    raise AssertionError((command, outcome, diagnostics))


def _human_value(value: object) -> str:
    if type(value) is bool:
        return "是" if value else "否"
    if value is None:
        return "无"
    assert type(value) in {str, int}
    return str(value)


def _literature_human(envelope: Mapping[str, object]) -> bytes:
    command = str(envelope["command"])
    outcome = str(envelope["outcome"])
    result = envelope["result"]
    assert type(result) is dict and outcome == "succeeded"
    noun = command.removeprefix("literature.")
    lines = [f"Literature {noun}：完成"]
    if command == "literature.add":
        fields = (
            ("active_source_changed", "Active Source 已切换"),
            ("disposition", "处理结果"),
            ("schema_version", "Schema"),
            ("source_id", "Source ID"),
            ("source_sha256", "Source SHA-256"),
            ("work_id", "Work ID"),
        )
        lines.extend(f"{label}：{_human_value(result[key])}" for key, label in fields)
        lines.append(f"下一步：运行 gezhi literature resume {result['work_id']}")
    elif command == "literature.resume":
        lines.append(f"Active Source ID：{result['active_source_id']}")
        for key, label in (
            ("advanced_stages", "本次推进阶段"),
            ("pending_candidate_ids", "待审核 Candidate"),
        ):
            values = result[key]
            assert type(values) is list
            if values:
                lines.append(f"{label}：")
                lines.extend(f"  - {_human_value(item)}" for item in values)
            else:
                lines.append(f"{label}：[]")
        for key, label in (
            ("pipeline_complete", "管线已完成"),
            ("schema_version", "Schema"),
            ("start_stage", "开始阶段"),
            ("stop_stage", "停止阶段"),
            ("work_id", "Work ID"),
        ):
            lines.append(f"{label}：{_human_value(result[key])}")
        lines.append("下一步：无需操作")
    else:
        fields = (
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
        )
        lines.extend(f"{label}：{_human_value(result[key])}" for key, label in fields)
        lines.append(f"下一步：运行 gezhi literature resume {result['work_id']}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _scalar_token(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    assert type(value) is str
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _knowledge_tree_lines(value: object, *, depth: int) -> list[str]:
    indent = " " * (2 * depth)
    if type(value) is dict:
        lines: list[str] = []
        for key in sorted(value):
            assert key in _KNOWLEDGE_LABELS
            item = value[key]
            prefix = f"{indent}{_KNOWLEDGE_LABELS[key]}:"
            if type(item) not in {dict, list}:
                lines.append(f"{prefix} {_scalar_token(item)}")
            elif not item:
                lines.append(f"{prefix} {'{}' if type(item) is dict else '[]'}")
            else:
                lines.append(prefix)
                lines.extend(_knowledge_tree_lines(item, depth=depth + 1))
        return lines
    assert type(value) is list
    lines = []
    for item in value:
        prefix = f"{indent}-"
        if type(item) not in {dict, list}:
            lines.append(f"{prefix} {_scalar_token(item)}")
        elif not item:
            lines.append(f"{prefix} {'{}' if type(item) is dict else '[]'}")
        else:
            lines.append(prefix)
            lines.extend(_knowledge_tree_lines(item, depth=depth + 1))
    return lines


def _knowledge_read_human(envelope: Mapping[str, object]) -> bytes:
    command = str(envelope["command"])
    result = envelope["result"]
    assert type(result) is dict and envelope["outcome"] == "succeeded"
    heading = (
        "Knowledge 候选搜索" if command == "knowledge.search" else "Knowledge 候选详情"
    )
    lines = [
        heading,
        "治理说明：以下结果仅为已审核但尚未晋升的 Candidate Knowledge，不代表已晋升知识、已验证事实或自动蕴含证明。",
    ]
    for key in sorted(result):
        lines.extend(_knowledge_tree_lines({key: result[key]}, depth=0))
        if (
            command == "knowledge.show"
            and key == "governance"
            and type(result[key]) is dict
            and result[key].get("intake_status") == "withdrawn"
        ):
            lines.append(
                "注意：该 Candidate 已撤回，不参与 search 或 ask 检索；以下内容仅供历史审计。"
            )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _status_count_text(value: object) -> str:
    assert type(value) is list
    return (
        "["
        + ",".join(
            f"{_OPERATIONAL_HUMAN[str(item['status'])]}={item['count']}"
            for item in value
        )
        + "]"
    )


def _status_human(envelope: Mapping[str, object]) -> bytes:
    result = envelope["result"]
    assert type(result) is dict and result["scope"] == "work"
    literature = result["literature"]
    knowledge = result["knowledge"]
    recovery = result["recovery"]
    assert type(literature) is dict and type(knowledge) is dict
    assert type(recovery) is dict
    lines = [
        f"格致状态：{_OPERATIONAL_HUMAN[str(result['status'])]}",
        f"范围：Work {result['work_id']}",
        f"Literature：{_AVAILABILITY_HUMAN[str(literature['availability'])]}",
        "阶段："
        + "；".join(
            f"{item['stage']}={_OPERATIONAL_HUMAN[str(item['status'])]}"
            for item in literature["stages"]
        ),
    ]
    review = literature["review_counts"]
    assert type(review) is dict
    lines.append(
        f"审核：待审核={review['pending']}；已接受={review['accepted']}；"
        f"已拒绝={review['rejected']}；已暂缓={review['deferred']}"
    )
    lines.append(f"交接：{_HANDOFF_HUMAN[str(literature['handoff_status'])]}")
    if knowledge["availability"] in {"unavailable", "unsafe"}:
        lines.append(
            f"Knowledge：{_AVAILABILITY_HUMAN[str(knowledge['availability'])]}"
        )
    else:
        candidate_counts = knowledge["candidate_counts"]
        assert type(candidate_counts) is dict
        lines.append(
            f"Knowledge：{_AVAILABILITY_HUMAN[str(knowledge['availability'])]}；"
            f"active={candidate_counts['active']}；"
            f"withdrawn={candidate_counts['withdrawn']}；相关 Answer="
            + _status_count_text(knowledge["related_answer_status_counts"])
        )
    lines.append(
        f"恢复风险：暂存={recovery['staging_count']}；"
        f"待恢复={recovery['orphaned_count']}；"
        f"已隔离={recovery['quarantined_count']}；"
        f"不一致={recovery['inconsistent_count']}"
    )
    next_action = str(result["next_action"])
    recommendation = (
        f"前置条件就绪后运行 gezhi literature resume {result['work_id']}。"
        if next_action == "resume_work"
        else _NEXT_ACTION_HUMAN[next_action]
    )
    lines.append("下一步：" + recommendation)
    return ("\n".join(lines) + "\n").encode("utf-8")


def expected_human_bytes_v1(envelope: Mapping[str, object]) -> bytes:
    command = str(envelope["command"])
    if command.startswith("literature."):
        return _literature_human(envelope)
    if command in {"knowledge.search", "knowledge.show"}:
        return _knowledge_read_human(envelope)
    if command == "knowledge.ask":
        assert envelope["outcome"] == "blocked"
        assert envelope["result"] is None
        return (
            "Knowledge ask：已阻塞\n"
            "原因：问题为空、语义不足或包含不支持的控制字符\n"
            "下一步：输入一个单轮、自包含且可读的问题后重试\n"
        ).encode()
    if command == "status":
        return _status_human(envelope)
    if command == "doctor":
        assert envelope["result"] == {
            "checks": [
                {"id": check_id, "status": "ready"}
                for check_id in (
                    "configuration",
                    "core_python",
                    "core_dependencies",
                    "literature_data_root",
                    "knowledge_data_root",
                    "ocr_runtime",
                    "codex_runtime",
                )
            ],
            "overall_status": "ready",
            "schema_version": "gezhi.doctor_result.v1",
        }
        return (
            "格致 doctor：就绪\n"
            "配置：就绪\n"
            "核心 Python：就绪\n"
            "核心依赖：就绪\n"
            "Literature Data Root：就绪\n"
            "Knowledge Data Root：就绪\n"
            "OCR 运行时：就绪\n"
            "Codex 运行时：就绪\n"
            "下一步：冻结环境已就绪。\n"
        ).encode()
    raise AssertionError(command)
