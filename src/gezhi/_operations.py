from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, TypeAlias, cast

from gezhi._presentation import (
    CliOutcome,
    present_operations_human,
    present_operations_json,
)
from gezhi._work_id import is_work_id_v1

CheckStatus: TypeAlias = Literal["ready", "blocked", "failed", "not_checked"]
CheckReason: TypeAlias = (
    Literal[
        "configuration_invalid",
        "core_environment_unavailable",
        "data_root_unsafe",
        "data_root_unavailable",
        "ocr_environment_unavailable",
        "codex_environment_unavailable",
        "inspection_failed",
    ]
    | None
)
OverallStatus: TypeAlias = Literal["ready", "blocked", "failed"]
DoctorObservation: TypeAlias = tuple[str, CheckStatus, CheckReason]
Diagnostic: TypeAlias = dict[str, object]

_OUTCOME_BY_STATUS: dict[OverallStatus, CliOutcome] = {
    "ready": "succeeded",
    "blocked": "blocked",
    "failed": "failed",
}

_CHECK_IDS = (
    "configuration",
    "core_python",
    "core_dependencies",
    "literature_data_root",
    "knowledge_data_root",
    "ocr_runtime",
    "codex_runtime",
)
_EXPECTED_BLOCKED_REASON: dict[str, tuple[str, ...]] = {
    "configuration": ("configuration_invalid",),
    "core_python": ("core_environment_unavailable",),
    "core_dependencies": ("core_environment_unavailable",),
    "literature_data_root": ("data_root_unsafe", "data_root_unavailable"),
    "knowledge_data_root": ("data_root_unsafe", "data_root_unavailable"),
    "ocr_runtime": ("ocr_environment_unavailable",),
    "codex_runtime": ("codex_environment_unavailable",),
}
_BLOCKED_PRIORITY = (
    "configuration_invalid",
    "data_root_unsafe",
    "data_root_unavailable",
    "core_environment_unavailable",
    "ocr_environment_unavailable",
    "codex_environment_unavailable",
)
_REASON_TO_CODE = {
    "configuration_invalid": "operations.doctor.configuration_invalid.v1",
    "core_environment_unavailable": (
        "operations.doctor.core_environment_unavailable.v1"
    ),
    "data_root_unsafe": "operations.doctor.data_root_unsafe.v1",
    "data_root_unavailable": "operations.doctor.data_root_unavailable.v1",
    "ocr_environment_unavailable": ("operations.doctor.ocr_environment_unavailable.v1"),
    "codex_environment_unavailable": (
        "operations.doctor.codex_environment_unavailable.v1"
    ),
    "inspection_failed": "operations.doctor.inspection_failed.v1",
}
_CHECK_HUMAN_NAMES = (
    "配置",
    "核心 Python",
    "核心依赖",
    "Literature Data Root",
    "Knowledge Data Root",
    "OCR 运行时",
    "Codex 运行时",
)
_STATUS_HUMAN = {
    "ready": "就绪",
    "blocked": "受阻",
    "failed": "检查失败",
    "not_checked": "未检查",
}
_DIAGNOSTIC_HUMAN = {
    "operations.doctor.configuration_invalid.v1": (
        "问题：格致配置无效。",
        "建议：检查版本化配置后重试；本命令不会修改配置。",
    ),
    "operations.doctor.core_environment_unavailable.v1": (
        "问题：核心 Python 环境或依赖与冻结基线不一致。",
        "建议：使用已批准的冻结环境恢复流程；不要在 doctor 中安装或升级。",
    ),
    "operations.doctor.data_root_unsafe.v1": (
        "问题：一个或多个 Data Root 不满足 Windows 安全边界。",
        "建议：停止写入并在外部修复路径边界；本命令不会移动或创建目录。",
    ),
    "operations.doctor.data_root_unavailable.v1": (
        "问题：一个或多个 Data Root 不可用。",
        "建议：在外部恢复已配置目录及访问权限后重试；本命令不会创建目录。",
    ),
    "operations.doctor.ocr_environment_unavailable.v1": (
        "问题：OCR 运行时与冻结基线不一致或不可用。",
        "建议：使用已批准的 OCR 环境恢复流程；不要切换 CPU、在线模型或其他 OCR。",
    ),
    "operations.doctor.codex_environment_unavailable.v1": (
        "问题：项目锁定的 Codex CLI 不可用。",
        "建议：检查项目锁、原生 CLI 与登录状态；不要切换全局、桌面或其他模型。",
    ),
    "operations.doctor.inspection_failed.v1": (
        "问题：doctor 无法完成只读检查。",
        "建议：保留现场并检查格致实现或运行环境；不要让 doctor 自动修复。",
    ),
    "operations.status.configuration_invalid.v1": (
        "问题：格致配置无效。",
        "建议：检查版本化配置后重试；本命令不会修改配置。",
    ),
    "operations.status.invalid_work_id.v1": (
        "问题：Work ID 无效。",
        "建议：使用完整的小写 wrk_ UUIDv4。",
    ),
    "operations.status.work_not_found.v1": (
        "问题：找不到指定 Work。",
        "建议：核对 Work ID，或运行 gezhi status 查看整体状态。",
    ),
    "operations.status.data_root_unsafe.v1": (
        "问题：一个或多个 Data Root 不满足 Windows 安全边界。",
        "建议：停止写入并在外部修复路径边界；本命令不会移动或创建目录。",
    ),
    "operations.status.data_root_unavailable.v1": (
        "问题：一个或多个 Data Root 不可用。",
        "建议：在外部恢复已配置目录及访问权限后重试；本命令不会创建目录。",
    ),
    "operations.status.integrity_attention.v1": (
        "问题：状态范围内存在恢复或完整性风险。",
        "建议：停止相关写入、保留现场并进行维护检查；不要手工删除或改名。",
    ),
    "operations.status.projection_incomplete.v1": (
        "问题：状态报告只覆盖了可验证的部分 Context。",
        "建议：先恢复不可用的 Context，再运行相同 status 命令。",
    ),
    "operations.status.observation_failed.v1": (
        "问题：无法形成可信的状态报告。",
        "建议：保留现场并检查权威资产、索引与读取环境；status 不会自动修复。",
    ),
}

_MAX_INT64 = 9_223_372_036_854_775_807
_OPERATIONAL_ORDER = (
    "empty",
    "pending",
    "running",
    "succeeded",
    "blocked",
    "failed",
    "interrupted",
    "partial",
    "staging",
    "orphaned",
    "quarantined",
    "inconsistent",
)
_WORK_OPERATIONAL_ORDER = _OPERATIONAL_ORDER[1:]
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
    "empty",
)
_ANSWER_STATUS_ORDER = ("succeeded", "blocked", "failed", "interrupted")
_STAGE_ORDER = (
    "ingest",
    "ocr",
    "canonicalize",
    "read",
    "review",
    "handoff",
    "knowledge_import",
)
_STAGE_STATUSES = frozenset(
    {"pending", "running", "succeeded", "blocked", "failed", "interrupted"}
)
_RECOVERY_KEYS = (
    "staging_count",
    "orphaned_count",
    "quarantined_count",
    "inconsistent_count",
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
    "review_candidate": (
        "使用 Review Queue 中的 Candidate ID 运行 gezhi literature review。"
    ),
    "repair_data_root": "在外部恢复或修复 Data Root 后重试。",
    "inspect_recovery": "停止相关写入、保留现场并进行维护检查。",
}


def _validate_observations(
    observations: Sequence[tuple[str, str, str | None]],
) -> tuple[DoctorObservation, ...]:
    frozen = tuple(observations)
    if len(frozen) != len(_CHECK_IDS):
        raise ValueError("doctor observation count is invalid")
    for expected_id, observation in zip(_CHECK_IDS, frozen, strict=True):
        if type(observation) is not tuple or len(observation) != 3:
            raise TypeError("doctor observation is invalid")
        check_id, status, reason = observation
        if check_id != expected_id:
            raise ValueError("doctor observation order is invalid")
        if status not in {"ready", "blocked", "failed", "not_checked"}:
            raise ValueError("doctor observation status is invalid")
        if status == "ready" and reason is not None:
            raise ValueError("ready doctor observation has a reason")
        if status == "failed" and reason != "inspection_failed":
            raise ValueError("failed doctor observation has an invalid reason")
        if status == "blocked" and reason not in _EXPECTED_BLOCKED_REASON[check_id]:
            raise ValueError("blocked doctor observation has an invalid reason")
        if status == "not_checked" and (
            check_id not in {"literature_data_root", "knowledge_data_root"}
            or reason is not None
        ):
            raise ValueError("doctor observation cannot be not_checked")

    configuration_ready = frozen[0][1] == "ready"
    root_statuses = (frozen[3][1], frozen[4][1])
    if configuration_ready and "not_checked" in root_statuses:
        raise ValueError("ready configuration requires Data Root observations")
    if not configuration_ready and root_statuses != ("not_checked", "not_checked"):
        raise ValueError("unready configuration must skip Data Root observations")
    return cast(tuple[DoctorObservation, ...], frozen)


def _overall_status(observations: tuple[DoctorObservation, ...]) -> OverallStatus:
    statuses = tuple(observation[1] for observation in observations)
    if "failed" in statuses:
        return "failed"
    if "blocked" in statuses or "not_checked" in statuses:
        return "blocked"
    return "ready"


def _diagnostic_item(
    reason: str,
    observations: tuple[DoctorObservation, ...],
) -> Diagnostic:
    context: dict[str, object] = {}
    if reason in {"core_environment_unavailable", "inspection_failed"}:
        context["checks"] = [
            check_id
            for check_id, status, observed_reason in observations
            if status in {"blocked", "failed"} and observed_reason == reason
        ]
    elif reason in {"data_root_unsafe", "data_root_unavailable"}:
        context["contexts"] = [
            "literature" if check_id == "literature_data_root" else "knowledge"
            for check_id, status, observed_reason in observations
            if status == "blocked" and observed_reason == reason
        ]
    return {"code": _REASON_TO_CODE[reason], "context": context}


def _diagnostics(
    observations: tuple[DoctorObservation, ...],
    overall_status: OverallStatus,
) -> list[Diagnostic]:
    if overall_status == "ready":
        return []
    reasons = {
        cast(str, reason)
        for _check_id, status, reason in observations
        if status in {"blocked", "failed"}
    }
    if overall_status == "failed":
        primary_reason = "inspection_failed"
    else:
        primary_reason = next(
            reason for reason in _BLOCKED_PRIORITY if reason in reasons
        )
    primary = _diagnostic_item(primary_reason, observations)
    supplemental = [
        _diagnostic_item(reason, observations)
        for reason in reasons
        if reason != primary_reason
    ]
    supplemental.sort(key=lambda item: cast(str, item["code"]).encode("ascii"))
    return [primary, *supplemental]


def _doctor_envelope(
    observations: tuple[DoctorObservation, ...],
) -> tuple[dict[str, object], OverallStatus, list[Diagnostic]]:
    overall_status = _overall_status(observations)
    diagnostics = _diagnostics(observations, overall_status)
    checks = [
        {"id": check_id, "status": status} for check_id, status, _reason in observations
    ]
    result: dict[str, object] = {
        "schema_version": "gezhi.doctor_result.v1",
        "overall_status": overall_status,
        "checks": checks,
    }
    return result, overall_status, diagnostics


def _doctor_human_text(
    observations: tuple[DoctorObservation, ...],
    overall_status: OverallStatus,
    diagnostics: Sequence[Diagnostic],
) -> str:
    lines = [f"格致 doctor：{_STATUS_HUMAN[overall_status]}"]
    lines.extend(
        f"{name}：{_STATUS_HUMAN[status]}"
        for name, (_check_id, status, _reason) in zip(
            _CHECK_HUMAN_NAMES,
            observations,
            strict=True,
        )
    )
    if overall_status == "ready":
        lines.append("下一步：冻结环境已就绪。")
    else:
        for diagnostic in diagnostics:
            lines.extend(_DIAGNOSTIC_HUMAN[cast(str, diagnostic["code"])])
    return "\n".join(lines) + "\n"


def run_doctor(
    *,
    cli_patch: tuple[tuple[str, str], ...],
    json_output: bool,
) -> int:
    from gezhi._doctor_runtime import observe_doctor

    observations = _validate_observations(observe_doctor(cli_patch=cli_patch))
    result, overall_status, diagnostics = _doctor_envelope(observations)
    if json_output:
        outcome = _OUTCOME_BY_STATUS[overall_status]
        present_operations_json(
            command="doctor",
            outcome=outcome,
            result=result,
            diagnostics=diagnostics,
        )
    else:
        present_operations_human(
            _doctor_human_text(observations, overall_status, diagnostics)
        )
    return {"ready": 0, "blocked": 2, "failed": 1}[overall_status]


def _strict_count(value: object, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if type(value) is not int or not minimum <= value <= _MAX_INT64:
        raise ValueError("status count is invalid")
    return value


def _exact_mapping(value: object, keys: set[str], *, label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise TypeError(f"{label} is invalid")
    return cast(dict[str, object], value)


def _validate_recovery(value: object) -> dict[str, int]:
    raw = _exact_mapping(value, set(_RECOVERY_KEYS), label="status recovery")
    return {key: _strict_count(raw[key]) for key in _RECOVERY_KEYS}


def _checked_add(left: int, right: int) -> int:
    if right > _MAX_INT64 - left:
        raise OverflowError("status count sum exceeds int64")
    return left + right


def _merge_recovery(*values: Mapping[str, int]) -> dict[str, int]:
    merged = {key: 0 for key in _RECOVERY_KEYS}
    for value in values:
        if set(value) != set(_RECOVERY_KEYS):
            raise ValueError("status recovery shape is invalid")
        for key in _RECOVERY_KEYS:
            merged[key] = _checked_add(merged[key], _strict_count(value[key]))
    return merged


def _validate_status_counts(
    value: object,
    *,
    allowed_order: tuple[str, ...],
) -> list[dict[str, object]]:
    if type(value) is not list or len(value) > len(allowed_order):
        raise TypeError("status counts are invalid")
    observed: list[dict[str, object]] = []
    previous_index = -1
    for item in value:
        raw = _exact_mapping(item, {"status", "count"}, label="status count item")
        status = raw["status"]
        if type(status) is not str or status not in allowed_order:
            raise ValueError("status count value is invalid")
        index = allowed_order.index(status)
        if index <= previous_index:
            raise ValueError("status counts are not in contract order")
        previous_index = index
        observed.append(
            {"status": status, "count": _strict_count(raw["count"], positive=True)}
        )
    return observed


def _validate_availability(value: object) -> str:
    if value not in {"ready", "partial", "unavailable", "unsafe"}:
        raise ValueError("status availability is invalid")
    return cast(str, value)


def _validate_overall_literature(
    value: object,
) -> tuple[dict[str, object], dict[str, int]]:
    if type(value) is not dict or "availability" not in value:
        raise TypeError("overall Literature observation is invalid")
    availability = _validate_availability(value["availability"])
    if availability in {"unavailable", "unsafe"}:
        raw = _exact_mapping(
            value,
            {"availability", "recovery"},
            label="unavailable Literature observation",
        )
        recovery = _validate_recovery(raw["recovery"])
        if any(recovery.values()):
            raise ValueError("an unavailable projection cannot prove recovery counts")
        return {"availability": availability}, recovery
    raw = _exact_mapping(
        value,
        {
            "availability",
            "work_count",
            "work_status_counts",
            "pending_review_count",
            "pending_handoff_count",
            "recovery",
        },
        label="overall Literature observation",
    )
    work_count = _strict_count(raw["work_count"])
    counts = _validate_status_counts(
        raw["work_status_counts"],
        allowed_order=_WORK_OPERATIONAL_ORDER,
    )
    total = 0
    for item in counts:
        total = _checked_add(total, cast(int, item["count"]))
    if total != work_count or (work_count == 0) is not (counts == []):
        raise ValueError("Literature Work count projection differs")
    return (
        {
            "availability": availability,
            "work_count": work_count,
            "work_status_counts": counts,
            "pending_review_count": _strict_count(raw["pending_review_count"]),
            "pending_handoff_count": _strict_count(raw["pending_handoff_count"]),
        },
        _validate_recovery(raw["recovery"]),
    )


def _validate_overall_knowledge(
    value: object,
) -> tuple[dict[str, object], dict[str, int]]:
    if type(value) is not dict or "availability" not in value:
        raise TypeError("overall Knowledge observation is invalid")
    availability = _validate_availability(value["availability"])
    if availability in {"unavailable", "unsafe"}:
        raw = _exact_mapping(
            value,
            {"availability", "recovery"},
            label="unavailable Knowledge observation",
        )
        recovery = _validate_recovery(raw["recovery"])
        if any(recovery.values()):
            raise ValueError("an unavailable projection cannot prove recovery counts")
        return {"availability": availability}, recovery
    raw = _exact_mapping(
        value,
        {
            "availability",
            "active_candidate_count",
            "withdrawn_candidate_count",
            "answer_status_counts",
            "recovery",
        },
        label="overall Knowledge observation",
    )
    return (
        {
            "availability": availability,
            "active_candidate_count": _strict_count(raw["active_candidate_count"]),
            "withdrawn_candidate_count": _strict_count(
                raw["withdrawn_candidate_count"]
            ),
            "answer_status_counts": _validate_status_counts(
                raw["answer_status_counts"],
                allowed_order=_ANSWER_STATUS_ORDER,
            ),
        },
        _validate_recovery(raw["recovery"]),
    )


def _validate_stages(value: object) -> list[dict[str, object]]:
    if type(value) is not list or len(value) != len(_STAGE_ORDER):
        raise TypeError("Work stage projection is invalid")
    stages: list[dict[str, object]] = []
    for expected, item in zip(_STAGE_ORDER, value, strict=True):
        raw = _exact_mapping(item, {"stage", "status"}, label="Work stage item")
        status = raw["status"]
        if raw["stage"] != expected or status not in _STAGE_STATUSES:
            raise ValueError("Work stage projection differs")
        stages.append({"stage": expected, "status": status})
    return stages


def _validate_work_literature(
    value: object,
) -> tuple[dict[str, object], dict[str, int]]:
    raw = _exact_mapping(
        value,
        {"availability", "stages", "review_counts", "handoff_status", "recovery"},
        label="Work Literature observation",
    )
    availability = _validate_availability(raw["availability"])
    if availability not in {"ready", "partial"}:
        raise ValueError("a Work report requires Literature projection")
    review_raw = _exact_mapping(
        raw["review_counts"],
        {"pending", "accepted", "rejected", "deferred"},
        label="Work Review counts",
    )
    handoff_status = raw["handoff_status"]
    if handoff_status not in {
        "none",
        "pending",
        "available",
        "blocked",
        "failed",
        "inconsistent",
    }:
        raise ValueError("Work Handoff status is invalid")
    return (
        {
            "availability": availability,
            "stages": _validate_stages(raw["stages"]),
            "review_counts": {
                key: _strict_count(review_raw[key])
                for key in ("pending", "accepted", "rejected", "deferred")
            },
            "handoff_status": handoff_status,
        },
        _validate_recovery(raw["recovery"]),
    )


def _validate_work_knowledge(
    value: object,
) -> tuple[dict[str, object], dict[str, int]]:
    if type(value) is not dict or "availability" not in value:
        raise TypeError("Work Knowledge observation is invalid")
    availability = _validate_availability(value["availability"])
    if availability in {"unavailable", "unsafe"}:
        raw = _exact_mapping(
            value,
            {"availability", "recovery"},
            label="unavailable Work Knowledge observation",
        )
        recovery = _validate_recovery(raw["recovery"])
        if any(recovery.values()):
            raise ValueError("an unavailable projection cannot prove recovery counts")
        return {"availability": availability}, recovery
    raw = _exact_mapping(
        value,
        {
            "availability",
            "candidate_counts",
            "related_answer_status_counts",
            "recovery",
        },
        label="Work Knowledge observation",
    )
    candidate_raw = _exact_mapping(
        raw["candidate_counts"],
        {"active", "withdrawn"},
        label="Work Candidate counts",
    )
    return (
        {
            "availability": availability,
            "candidate_counts": {
                "active": _strict_count(candidate_raw["active"]),
                "withdrawn": _strict_count(candidate_raw["withdrawn"]),
            },
            "related_answer_status_counts": _validate_status_counts(
                raw["related_answer_status_counts"],
                allowed_order=_ANSWER_STATUS_ORDER,
            ),
        },
        _validate_recovery(raw["recovery"]),
    )


def _summary_status(statuses: set[str]) -> str:
    return next(status for status in _SUMMARY_PRIORITY if status in statuses)


def _recovery_status(recovery: Mapping[str, int]) -> str | None:
    for key, status in (
        ("inconsistent_count", "inconsistent"),
        ("quarantined_count", "quarantined"),
        ("orphaned_count", "orphaned"),
        ("staging_count", "staging"),
    ):
        if recovery[key]:
            return status
    return None


def _availability_contexts(
    literature: Mapping[str, object], knowledge: Mapping[str, object]
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (context, cast(str, summary["availability"]))
        for context, summary in (
            ("literature", literature),
            ("knowledge", knowledge),
        )
        if summary["availability"] != "ready"
    )


def _status_diagnostics(
    literature: Mapping[str, object],
    knowledge: Mapping[str, object],
    recovery: Mapping[str, int],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    contexts = _availability_contexts(literature, knowledge)
    for availability, code in (
        ("unsafe", "operations.status.data_root_unsafe.v1"),
        ("unavailable", "operations.status.data_root_unavailable.v1"),
    ):
        affected = [context for context, state in contexts if state == availability]
        if affected:
            diagnostics.append({"code": code, "context": {"contexts": affected}})
    recovery_kinds = [
        kind
        for kind, key in (
            ("staging", "staging_count"),
            ("orphaned", "orphaned_count"),
            ("quarantined", "quarantined_count"),
            ("inconsistent", "inconsistent_count"),
        )
        if recovery[key]
    ]
    if recovery_kinds:
        total = 0
        for key in _RECOVERY_KEYS:
            total = _checked_add(total, recovery[key])
        diagnostics.append(
            {
                "code": "operations.status.integrity_attention.v1",
                "context": {"kinds": recovery_kinds, "count": total},
            }
        )
    incomplete = [context for context, _state in contexts]
    if incomplete:
        diagnostics.append(
            {
                "code": "operations.status.projection_incomplete.v1",
                "context": {"contexts": incomplete},
            }
        )
    diagnostics.sort(key=lambda item: cast(str, item["code"]).encode("ascii"))
    return diagnostics


def _overall_result(
    observation: dict[str, object],
) -> tuple[dict[str, object], list[Diagnostic]]:
    raw = _exact_mapping(
        observation,
        {"kind", "literature", "knowledge"},
        label="overall status observation",
    )
    literature, literature_recovery = _validate_overall_literature(raw["literature"])
    knowledge, knowledge_recovery = _validate_overall_knowledge(raw["knowledge"])
    recovery = _merge_recovery(literature_recovery, knowledge_recovery)
    recovery_status = _recovery_status(recovery)
    contexts = _availability_contexts(literature, knowledge)
    statuses: set[str] = set()
    if recovery_status is not None:
        statuses.add(recovery_status)
    if contexts:
        statuses.add("partial")
    if "work_status_counts" in literature:
        statuses.update(
            cast(str, item["status"])
            for item in cast(list[dict[str, object]], literature["work_status_counts"])
        )
        if literature["pending_review_count"] or literature["pending_handoff_count"]:
            statuses.add("pending")
    if "answer_status_counts" in knowledge:
        statuses.update(
            cast(str, item["status"])
            for item in cast(list[dict[str, object]], knowledge["answer_status_counts"])
        )
    has_governed_fact = bool(
        literature.get("work_count", 0)
        or knowledge.get("active_candidate_count", 0)
        or knowledge.get("withdrawn_candidate_count", 0)
        or knowledge.get("answer_status_counts", [])
        or any(recovery.values())
    )
    if not statuses:
        statuses.add("succeeded" if has_governed_fact else "empty")
    status = _summary_status(statuses)
    if recovery_status is not None:
        next_action = "inspect_recovery"
    elif any(state in {"unavailable", "unsafe"} for _context, state in contexts):
        next_action = "repair_data_root"
    elif status == "running":
        next_action = "none"
    elif literature.get("pending_review_count", 0):
        next_action = "review_candidate"
    elif status == "empty":
        next_action = "add_work"
    elif status == "succeeded":
        next_action = "none"
    else:
        next_action = "inspect_work"
    result: dict[str, object] = {
        "schema_version": "gezhi.status_result.v1",
        "scope": "overall",
        "status": status,
        "literature": literature,
        "knowledge": knowledge,
        "recovery": recovery,
        "next_action": next_action,
    }
    return result, _status_diagnostics(literature, knowledge, recovery)


def _work_result(
    observation: dict[str, object],
) -> tuple[dict[str, object], list[Diagnostic]]:
    raw = _exact_mapping(
        observation,
        {"kind", "work_id", "literature", "knowledge"},
        label="Work status observation",
    )
    work_id = raw["work_id"]
    if not is_work_id_v1(work_id):
        raise ValueError("Work status observation identity is invalid")
    literature, literature_recovery = _validate_work_literature(raw["literature"])
    knowledge, knowledge_recovery = _validate_work_knowledge(raw["knowledge"])
    recovery = _merge_recovery(literature_recovery, knowledge_recovery)
    recovery_status = _recovery_status(recovery)
    contexts = _availability_contexts(literature, knowledge)
    statuses = {
        cast(str, item["status"])
        for item in cast(list[dict[str, object]], literature["stages"])
    }
    if recovery_status is not None:
        statuses.add(recovery_status)
    if contexts:
        statuses.add("partial")
    if "related_answer_status_counts" in knowledge:
        statuses.update(
            cast(str, item["status"])
            for item in cast(
                list[dict[str, object]], knowledge["related_answer_status_counts"]
            )
        )
    status = _summary_status(statuses)
    if recovery_status is not None:
        next_action = "inspect_recovery"
    elif any(state in {"unavailable", "unsafe"} for _context, state in contexts):
        next_action = "repair_data_root"
    elif status == "running":
        next_action = "none"
    elif cast(dict[str, int], literature["review_counts"])["pending"]:
        next_action = "review_candidate"
    elif status == "succeeded":
        next_action = "none"
    else:
        next_action = "resume_work"
    result: dict[str, object] = {
        "schema_version": "gezhi.status_result.v1",
        "scope": "work",
        "work_id": work_id,
        "status": status,
        "literature": literature,
        "knowledge": knowledge,
        "recovery": recovery,
        "next_action": next_action,
    }
    return result, _status_diagnostics(literature, knowledge, recovery)


def _blocked_status_observation(
    observation: dict[str, object],
) -> tuple[list[Diagnostic], int]:
    reason = observation.get("reason")
    if reason in {"configuration_invalid", "invalid_work_id"}:
        _exact_mapping(
            observation, {"kind", "reason"}, label="blocked status observation"
        )
        context: dict[str, object] = {}
    elif reason == "work_not_found":
        raw = _exact_mapping(
            observation,
            {"kind", "reason", "work_id"},
            label="Work-not-found observation",
        )
        work_id = raw["work_id"]
        if not is_work_id_v1(work_id):
            raise ValueError("Work-not-found identity is invalid")
        context = {"work_id": work_id}
    elif reason in {"data_root_unsafe", "data_root_unavailable"}:
        expected_keys = {"kind", "reason", "contexts"}
        if "supplemental" in observation:
            expected_keys.add("supplemental")
        raw = _exact_mapping(
            observation,
            expected_keys,
            label="Data Root blocked observation",
        )
        primary_contexts = _validate_blocked_contexts(raw["contexts"])
        context = {"contexts": primary_contexts}
        diagnostics: list[Diagnostic] = [
            {
                "code": f"operations.status.{reason}.v1",
                "context": context,
            }
        ]
        supplemental = raw.get("supplemental", [])
        if type(supplemental) is not list or len(supplemental) > 1:
            raise ValueError("blocked Data Root supplemental facts are invalid")
        for item in supplemental:
            fact = _exact_mapping(
                item,
                {"reason", "contexts"},
                label="Data Root supplemental observation",
            )
            fact_reason = fact["reason"]
            if (
                fact_reason not in {"data_root_unsafe", "data_root_unavailable"}
                or fact_reason == reason
                or reason != "data_root_unsafe"
            ):
                raise ValueError("blocked Data Root supplemental priority is invalid")
            supplemental_contexts = _validate_blocked_contexts(fact["contexts"])
            if set(primary_contexts) & set(supplemental_contexts):
                raise ValueError("blocked Data Root facts overlap")
            diagnostics.append(
                {
                    "code": f"operations.status.{fact_reason}.v1",
                    "context": {"contexts": supplemental_contexts},
                }
            )
        return diagnostics, 2
    else:
        raise ValueError("blocked status reason is invalid")
    return (
        [
            {
                "code": f"operations.status.{reason}.v1",
                "context": context,
            }
        ],
        2,
    )


def _validate_blocked_contexts(value: object) -> list[str]:
    if (
        type(value) is not list
        or not value
        or value
        != [context for context in ("literature", "knowledge") if context in value]
    ):
        raise ValueError("blocked Data Root contexts are invalid")
    return cast(list[str], value)


def _status_envelope(
    observation: object,
) -> tuple[dict[str, object] | None, CliOutcome, list[Diagnostic], int]:
    if type(observation) is not dict or type(observation.get("kind")) is not str:
        raise TypeError("status observation is invalid")
    kind = observation["kind"]
    if kind == "overall":
        result, diagnostics = _overall_result(observation)
        return result, "succeeded", diagnostics, 0
    if kind == "work":
        result, diagnostics = _work_result(observation)
        return result, "succeeded", diagnostics, 0
    if kind == "blocked":
        diagnostics, exit_code = _blocked_status_observation(observation)
        return None, "blocked", diagnostics, exit_code
    if kind == "failed":
        _exact_mapping(observation, {"kind"}, label="failed status observation")
        return (
            None,
            "failed",
            [{"code": "operations.status.observation_failed.v1", "context": {}}],
            1,
        )
    raise ValueError("status observation kind is invalid")


def _status_count_text(value: object) -> str:
    counts = cast(list[dict[str, object]], value)
    return (
        "["
        + ",".join(
            f"{_OPERATIONAL_HUMAN[cast(str, item['status'])]}={item['count']}"
            for item in counts
        )
        + "]"
    )


def _diagnostic_human_lines(diagnostics: Sequence[Diagnostic]) -> list[str]:
    lines: list[str] = []
    for diagnostic in diagnostics:
        lines.extend(_DIAGNOSTIC_HUMAN[cast(str, diagnostic["code"])])
    return lines


def _status_human_text(
    result: Mapping[str, object] | None,
    outcome: CliOutcome,
    diagnostics: Sequence[Diagnostic],
) -> str:
    if result is None:
        heading = "受阻" if outcome == "blocked" else "读取失败"
        return (
            "\n".join([f"格致状态：{heading}", *_diagnostic_human_lines(diagnostics)])
            + "\n"
        )
    status = cast(str, result["status"])
    literature = cast(dict[str, object], result["literature"])
    knowledge = cast(dict[str, object], result["knowledge"])
    recovery = cast(dict[str, int], result["recovery"])
    lines = [f"格致状态：{_OPERATIONAL_HUMAN[status]}"]
    if result["scope"] == "overall":
        lines.append("范围：全部")
        if literature["availability"] in {"unavailable", "unsafe"}:
            lines.append(
                f"Literature：{_AVAILABILITY_HUMAN[cast(str, literature['availability'])]}"
            )
        else:
            lines.append(
                "Literature："
                f"{_AVAILABILITY_HUMAN[cast(str, literature['availability'])]}；"
                f"Work={literature['work_count']}；"
                f"状态={_status_count_text(literature['work_status_counts'])}；"
                f"待审核={literature['pending_review_count']}；"
                f"待交接={literature['pending_handoff_count']}"
            )
        if knowledge["availability"] in {"unavailable", "unsafe"}:
            lines.append(
                f"Knowledge：{_AVAILABILITY_HUMAN[cast(str, knowledge['availability'])]}"
            )
        else:
            lines.append(
                "Knowledge："
                f"{_AVAILABILITY_HUMAN[cast(str, knowledge['availability'])]}；"
                f"active={knowledge['active_candidate_count']}；"
                f"withdrawn={knowledge['withdrawn_candidate_count']}；"
                f"Answer={_status_count_text(knowledge['answer_status_counts'])}"
            )
    else:
        work_id = cast(str, result["work_id"])
        lines.extend(
            [
                f"范围：Work {work_id}",
                "Literature："
                + _AVAILABILITY_HUMAN[cast(str, literature["availability"])],
                "阶段："
                + "；".join(
                    f"{item['stage']}={_OPERATIONAL_HUMAN[cast(str, item['status'])]}"
                    for item in cast(list[dict[str, object]], literature["stages"])
                ),
            ]
        )
        review = cast(dict[str, int], literature["review_counts"])
        lines.append(
            f"审核：待审核={review['pending']}；已接受={review['accepted']}；"
            f"已拒绝={review['rejected']}；已暂缓={review['deferred']}"
        )
        lines.append("交接：" + _HANDOFF_HUMAN[cast(str, literature["handoff_status"])])
        if knowledge["availability"] in {"unavailable", "unsafe"}:
            lines.append(
                f"Knowledge：{_AVAILABILITY_HUMAN[cast(str, knowledge['availability'])]}"
            )
        else:
            candidate_counts = cast(dict[str, int], knowledge["candidate_counts"])
            lines.append(
                "Knowledge："
                f"{_AVAILABILITY_HUMAN[cast(str, knowledge['availability'])]}；"
                f"active={candidate_counts['active']}；"
                f"withdrawn={candidate_counts['withdrawn']}；"
                "相关 Answer="
                + _status_count_text(knowledge["related_answer_status_counts"])
            )
    lines.append(
        f"恢复风险：暂存={recovery['staging_count']}；"
        f"待恢复={recovery['orphaned_count']}；"
        f"已隔离={recovery['quarantined_count']}；"
        f"不一致={recovery['inconsistent_count']}"
    )
    next_action = cast(str, result["next_action"])
    if next_action == "resume_work":
        recommendation = (
            "前置条件就绪后运行 gezhi literature resume "
            f"{cast(str, result['work_id'])}。"
        )
    else:
        recommendation = _NEXT_ACTION_HUMAN[next_action]
    lines.append("下一步：" + recommendation)
    lines.extend(_diagnostic_human_lines(diagnostics))
    return "\n".join(lines) + "\n"


def run_status(
    *,
    cli_patch: tuple[tuple[str, str], ...],
    work_id: str | None,
    json_output: bool,
) -> int:
    try:
        from gezhi._status_runtime import observe_status

        observation = observe_status(cli_patch=cli_patch, work_id=work_id)
        result, outcome, diagnostics, exit_code = _status_envelope(observation)
    except Exception:  # noqa: BLE001 - internal observation faults fail closed.
        result = None
        outcome = "failed"
        diagnostics = [
            {"code": "operations.status.observation_failed.v1", "context": {}}
        ]
        exit_code = 1
    if json_output:
        present_operations_json(
            command="status",
            outcome=outcome,
            result=result,
            diagnostics=diagnostics,
        )
    else:
        present_operations_human(_status_human_text(result, outcome, diagnostics))
    return exit_code
