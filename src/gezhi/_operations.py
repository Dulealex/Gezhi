from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypeAlias, cast

from gezhi._presentation import (
    CliOutcome,
    present_operations_human,
    present_operations_json,
)

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
    "ocr_environment_unavailable": (
        "operations.doctor.ocr_environment_unavailable.v1"
    ),
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
        {"id": check_id, "status": status}
        for check_id, status, _reason in observations
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
