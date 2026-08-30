from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeAlias, cast

from gezhi._windows_data_root import (
    DataRootOpenErrorV1,
    ValidatedDataRootV1,
    open_validated_data_root_v1,
    open_validated_local_file_v1,
)
from gezhi._windows_ownership import (
    WriterOwnershipLifecycleErrorV1,
    WriterOwnershipV1,
)

_ANSWER_ID = re.compile(
    r"^ans_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_UTC_MILLISECONDS = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:"
    r"[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
)
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")
_INT64_MAX = 9_223_372_036_854_775_807

ANSWER_MANIFEST_MAX_BYTES = 65_536
ANSWER_TERMINAL_MAX_BYTES = 56_623_104

_ROOT_ASSET_SPECS = (
    (
        "effective_config.json",
        "schema_id",
        "gezhi.knowledge_answerer_effective_config.v1",
        4_096,
    ),
    ("question.json", "schema_id", "gezhi.question.v1", 16_384),
    (
        "retrieval_query.json",
        "schema_id",
        "gezhi.retrieval_query.v1",
        262_144,
    ),
    (
        "retrieval_audit.json",
        "schema_id",
        "gezhi.retrieval_audit.v1",
        2_097_152,
    ),
    (
        "retrieval_view.json",
        "schema_id",
        "gezhi.retrieval_view.v1",
        262_144,
    ),
    (
        "prompt.txt",
        "media_type",
        "text/plain; charset=utf-8",
        262_144,
    ),
    (
        "schema.json",
        "media_type",
        "application/schema+json",
        262_144,
    ),
    (
        "answer_output.json",
        "schema_id",
        "gezhi.answer_output.v1",
        32_768,
    ),
    (
        "answer.md",
        "media_type",
        "text/markdown; charset=utf-8",
        524_288,
    ),
)

_ATTEMPT_EVENTS_CAP = 16_777_216
_ATTEMPT_FINAL_CAP = 1_048_576
_ERROR_MATRIX = {
    "fts5_unavailable": ("blocked", "retrieval"),
    "retrieval_view_too_large": ("blocked", "retrieval"),
    "retrieval_query_failed": ("failed", "retrieval"),
    "retrieval_materialization_failed": ("failed", "retrieval"),
    "codex_runtime_unavailable": ("blocked", "synthesis"),
    "codex_timeout_exhausted": ("blocked", "synthesis"),
    "codex_network_exhausted": ("blocked", "synthesis"),
    "codex_rate_limit_exhausted": ("blocked", "synthesis"),
    "codex_server_error_exhausted": ("blocked", "synthesis"),
    "codex_transient_exhausted": ("blocked", "synthesis"),
    "synthesis_input_invalid": ("failed", "synthesis"),
    "codex_process_failed": ("failed", "synthesis"),
    "answer_output_invalid": ("failed", "validation"),
    "citation_link_construction_failed": ("failed", "rendering"),
    "answer_rendering_failed": ("failed", "rendering"),
}

_EXPECTED_EFFECTIVE_CONFIG = {
    "attempt_timeout_ms": 1_800_000,
    "attempt_window_limit_ms": 5_700_000,
    "retry_backoff_schedule_ms": [10_000, 30_000],
    "schema_version": "gezhi.knowledge_answerer_effective_config.v1",
}

StagingScanStatusV1: TypeAlias = Literal["empty", "recovery_unsupported"]


class AnswerTerminalErrorV1(RuntimeError):
    """Base class for a classified Answer Terminal failure."""


class AnswerTerminalRequestInvalidV1(AnswerTerminalErrorV1):
    """The declarative terminal request violates the frozen v1 shape."""


class AnswerWriterOwnershipInvalidV1(AnswerTerminalErrorV1):
    """The caller does not hold the live Answer writer on this thread."""


class AnswerRootIntegrityLostV1(AnswerTerminalErrorV1):
    """The held Knowledge root can no longer be re-proved."""


class AnswerOrphanScanFailedV1(AnswerTerminalErrorV1):
    """The pre-ID staging namespace could not be safely enumerated."""


class AnswerStagingFailedV1(AnswerTerminalErrorV1):
    """The current Answer staging tree could not be formed and closed."""


class AnswerManifestFailedV1(AnswerTerminalErrorV1):
    """The terminal manifest or its complete readback was rejected."""


class AnswerTargetConflictV1(AnswerTerminalErrorV1):
    """The expected immutable Answer target already exists."""


class AnswerCommitFailedV1(AnswerTerminalErrorV1):
    """The rename definitely did not commit this Answer."""


class AnswerCommitIndeterminateV1(AnswerTerminalErrorV1):
    """The final namespace does not prove a commit or a safe no-commit."""


@dataclass(frozen=True, slots=True)
class AnswerStagingScanV1:
    status: StagingScanStatusV1
    entry_count: int


@dataclass(frozen=True, slots=True)
class AnswerAttemptPublishV1:
    record: Mapping[str, object]
    events_bytes: bytes
    final_message_bytes: bytes


@dataclass(frozen=True, slots=True)
class AnswerPublishRequestV1:
    """Caller-owned values; it intentionally contains no paths or proof."""

    answer_id: str
    started_at: str
    started_monotonic_ns: int
    provenance: Mapping[str, object]
    effective_config_bytes: bytes
    question_bytes: bytes | None
    retrieval_query_bytes: bytes | None
    retrieval_audit_bytes: bytes | None
    retrieval_view_bytes: bytes | None
    status: Literal["succeeded", "blocked", "failed", "interrupted"] = "succeeded"
    error: Mapping[str, object] | None = None
    prompt_bytes: bytes | None = None
    schema_bytes: bytes | None = None
    attempts: tuple[AnswerAttemptPublishV1, ...] = ()
    answer_output_bytes: bytes | None = None
    answer_markdown_bytes: bytes | None = None


@dataclass(frozen=True, slots=True)
class CommittedAnswerProofV1:
    """Invocation-local proof returned only after an explicit rename success."""

    answer_id: str
    manifest_sha256: str
    status: Literal["succeeded", "blocked", "failed", "interrupted"]
    error: dict[str, object] | None
    answer_output_bytes: bytes | None
    answer_markdown_bytes: bytes | None


@dataclass(frozen=True, slots=True)
class _VerifiedAssetV1:
    path: str
    byte_length: int
    sha256: str
    identity_key: Literal["schema_id", "media_type"]
    identity_value: str

    def manifest_item(self) -> dict[str, object]:
        return {
            "path": self.path,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            self.identity_key: self.identity_value,
        }


def _root_facts(root: ValidatedDataRootV1) -> tuple[str, tuple[int, int]]:
    if type(root) is not ValidatedDataRootV1:
        raise TypeError("Knowledge root capability type is invalid")
    path = root.inspection.canonical_path
    identity = root.inspection.identity
    if path is None or identity is None:
        raise AnswerRootIntegrityLostV1("Knowledge root proof is incomplete")
    return path, identity


def _root_checkpoint(root: ValidatedDataRootV1) -> None:
    expected_path, expected_identity = _root_facts(root)
    try:
        with open_validated_data_root_v1(expected_path) as observed_root:
            observed = observed_root.inspection
    except (DataRootOpenErrorV1, OSError) as error:
        raise AnswerRootIntegrityLostV1("Knowledge root proof was lost") from error
    if (
        observed.identity != expected_identity
        or observed.ancestor_identities != root.inspection.ancestor_identities
        or observed.canonical_path is None
        or os.path.normcase(observed.canonical_path) != os.path.normcase(expected_path)
    ):
        raise AnswerRootIntegrityLostV1("Knowledge root identity changed")


def _assert_writer_ownership(
    root: ValidatedDataRootV1,
    ownership: WriterOwnershipV1,
) -> None:
    _, identity = _root_facts(root)
    if type(ownership) is not WriterOwnershipV1:
        raise TypeError("Knowledge Answer writer ownership type is invalid")
    try:
        ownership.assert_knowledge_answer_ownership_v1(identity)
    except (WriterOwnershipLifecycleErrorV1, ValueError) as error:
        raise AnswerWriterOwnershipInvalidV1(
            "Knowledge Answer writer ownership proof is invalid"
        ) from error


def _case_insensitive_name_present(names: tuple[str, ...], expected: str) -> bool:
    expected_ascii = expected.lower()
    return any(name.lower() == expected_ascii for name in names)


def _open_existing_child(
    parent: ValidatedDataRootV1,
    child: str,
) -> ValidatedDataRootV1 | None:
    names = parent.relative_entry_names_v1()
    aliases = tuple(name for name in names if name.lower() == child.lower())
    if not aliases:
        return None
    if aliases != (child,):
        raise DataRootOpenErrorV1("unsafe")
    return parent.open_relative_data_root_v1((child,))


def scan_answer_staging_v1(
    root: ValidatedDataRootV1,
    ownership: WriterOwnershipV1,
) -> AnswerStagingScanV1:
    """Read-only pre-ID scan; recovery itself is deliberately deferred to T23."""

    _assert_writer_ownership(root, ownership)
    _root_checkpoint(root)
    try:
        answers = _open_existing_child(root, "answers")
        if answers is None:
            _root_checkpoint(root)
            return AnswerStagingScanV1(status="empty", entry_count=0)
        with answers:
            staging = _open_existing_child(answers, ".staging")
            if staging is None:
                _root_checkpoint(root)
                return AnswerStagingScanV1(status="empty", entry_count=0)
            with staging:
                names = staging.relative_entry_names_v1()
    except AnswerRootIntegrityLostV1:
        raise
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        _root_checkpoint(root)
        raise AnswerOrphanScanFailedV1(
            "Answer staging could not be safely enumerated"
        ) from error
    _root_checkpoint(root)
    if names:
        return AnswerStagingScanV1(
            status="recovery_unsupported",
            entry_count=len(names),
        )
    return AnswerStagingScanV1(status="empty", entry_count=0)


def _validate_timestamp(value: object) -> str:
    if (
        type(value) is not str
        or len(value.encode("ascii", errors="ignore")) != 24
        or _UTC_MILLISECONDS.fullmatch(value) is None
    ):
        raise AnswerTerminalRequestInvalidV1("Answer timestamp is invalid")
    try:
        datetime.fromisoformat(value)
    except ValueError as error:
        raise AnswerTerminalRequestInvalidV1("Answer timestamp is invalid") from error
    return value


def _utc_now_milliseconds_v1() -> str:
    now = datetime.now(UTC)
    return (
        f"{now.year:04d}-{now.month:02d}-{now.day:02d}T"
        f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}."
        f"{now.microsecond // 1_000:03d}Z"
    )


def _reject_json_float(_: str) -> object:
    raise ValueError("floating-point JSON values are not permitted")


def _reject_json_constant(_: str) -> object:
    raise ValueError("non-standard JSON constants are not permitted")


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _canonical_json_file(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _decode_canonical_json_asset(payload: bytes) -> dict[str, object]:
    if (
        payload.startswith(b"\xef\xbb\xbf")
        or not payload.endswith(b"\n")
        or b"\r" in payload
        or b"\n" in payload[:-1]
    ):
        raise AnswerTerminalRequestInvalidV1("Answer JSON asset framing is invalid")
    try:
        decoded = json.loads(
            payload[:-1].decode("utf-8"),
            object_pairs_hook=_closed_object,
            parse_float=_reject_json_float,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise AnswerTerminalRequestInvalidV1("Answer JSON asset is invalid") from error
    if type(decoded) is not dict or _canonical_json_file(decoded) != payload:
        raise AnswerTerminalRequestInvalidV1("Answer JSON asset is not canonical")
    return cast(dict[str, object], decoded)


def _validate_provenance(value: Mapping[str, object]) -> dict[str, object]:
    if type(value) is not dict or set(value) != {
        "codex_cli_version",
        "git",
        "model",
        "reasoning_effort",
        "role_version",
    }:
        raise AnswerTerminalRequestInvalidV1("Answer provenance is invalid")
    git = value.get("git")
    if type(git) is not dict or set(git) != {"revision", "state"}:
        raise AnswerTerminalRequestInvalidV1("Answer Git provenance is invalid")
    state = git.get("state")
    revision = git.get("revision")
    if state == "unborn":
        valid_git = revision is None
    else:
        valid_git = (
            state in {"clean", "dirty"}
            and type(revision) is str
            and _GIT_REVISION.fullmatch(revision) is not None
        )
    if (
        value.get("codex_cli_version") != "0.146.0"
        or value.get("model") != "gpt-5.6-sol"
        or value.get("reasoning_effort") != "high"
        or value.get("role_version") != "knowledge_answerer_v1"
        or not valid_git
    ):
        raise AnswerTerminalRequestInvalidV1("Answer provenance is invalid")
    return {
        "codex_cli_version": "0.146.0",
        "git": {"revision": revision, "state": state},
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "role_version": "knowledge_answerer_v1",
    }


def _validate_attempt_record_v1(record: Mapping[str, object]) -> dict[str, object]:
    if type(record) is not dict or set(record) != {
        "cached_input_tokens",
        "elapsed_ms",
        "exit_code",
        "failure_class",
        "finished_at",
        "input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "started_at",
        "usage_unavailable",
    }:
        raise AnswerTerminalRequestInvalidV1("Answer attempt record is not closed")
    _validate_timestamp(record["started_at"])
    _validate_timestamp(record["finished_at"])
    elapsed_ms = record["elapsed_ms"]
    exit_code = record["exit_code"]
    failure_class = record["failure_class"]
    usage_unavailable = record["usage_unavailable"]
    if (
        type(elapsed_ms) is not int
        or not 0 <= elapsed_ms <= _INT64_MAX
        or exit_code is not None
        and (type(exit_code) is not int or not 0 <= exit_code <= 4_294_967_295)
        or failure_class
        not in {
            None,
            "timeout",
            "network",
            "rate_limit",
            "server_error",
            "runtime_unavailable",
            "process_error",
            "interrupted",
        }
        or type(usage_unavailable) is not bool
    ):
        raise AnswerTerminalRequestInvalidV1("Answer attempt scalar is invalid")
    tokens = []
    for name in (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    ):
        value = record[name]
        if value is not None and (
            type(value) is not int or not 0 <= value <= _INT64_MAX
        ):
            raise AnswerTerminalRequestInvalidV1("Answer attempt usage is invalid")
        tokens.append(value)
    if usage_unavailable is not any(value is None for value in tokens):
        raise AnswerTerminalRequestInvalidV1(
            "Answer attempt usage availability differs"
        )
    if failure_class is None and exit_code != 0:
        raise AnswerTerminalRequestInvalidV1("Successful Answer attempt exit differs")
    return dict(record)


def _validate_attempt_terminal_matrix_v1(
    *,
    status: str,
    error: dict[str, object] | None,
    candidate_count: int | None,
    attempts: list[dict[str, object]],
) -> None:
    error_code = None if error is None else error.get("code")
    if not attempts:
        legacy_transient_error = error_code in {
            "codex_network_exhausted",
            "codex_rate_limit_exhausted",
            "codex_server_error_exhausted",
            "codex_transient_exhausted",
        }
        attempt_required = error_code in {
            "codex_timeout_exhausted",
            "codex_process_failed",
        } or (
            candidate_count != 0
            and error_code
            in {
                "answer_output_invalid",
                "citation_link_construction_failed",
                "answer_rendering_failed",
            }
        )
        if legacy_transient_error or attempt_required:
            raise AnswerTerminalRequestInvalidV1(
                "Answer terminal matrix rejects the no-attempt cause"
            )
        return
    if candidate_count is None or candidate_count <= 0:
        raise AnswerTerminalRequestInvalidV1("Answer terminal matrix has no Candidate")
    failure_classes = tuple(attempt["failure_class"] for attempt in attempts)
    if any(
        failure_class not in {None, "timeout", "process_error", "interrupted"}
        for failure_class in failure_classes
    ) or any(failure_class != "timeout" for failure_class in failure_classes[:-1]):
        raise AnswerTerminalRequestInvalidV1(
            "Answer terminal matrix has an invalid attempt sequence"
        )
    last_failure = failure_classes[-1]
    valid = False
    if status == "succeeded":
        valid = last_failure is None
    elif status == "interrupted":
        valid = last_failure in {None, "interrupted"} or (
            last_failure == "timeout" and len(failure_classes) < 3
        )
    elif error_code == "codex_timeout_exhausted":
        valid = last_failure == "timeout"
    elif error_code == "codex_process_failed":
        valid = last_failure == "process_error"
    elif error_code in {
        "answer_output_invalid",
        "citation_link_construction_failed",
        "answer_rendering_failed",
    }:
        valid = last_failure is None
    if not valid:
        raise AnswerTerminalRequestInvalidV1(
            "Answer terminal matrix differs from its attempts"
        )


def _validate_utf8_text_asset_v1(payload: bytes, *, label: str) -> None:
    if payload.startswith(b"\xef\xbb\xbf") or not payload.endswith(b"\n"):
        raise AnswerTerminalRequestInvalidV1(f"{label} framing is invalid")
    try:
        if payload.decode("utf-8").encode("utf-8") != payload:
            raise UnicodeError(f"{label} changed on round-trip")
    except UnicodeError as error:
        raise AnswerTerminalRequestInvalidV1(f"{label} is not strict UTF-8") from error


def _request_assets(
    request: AnswerPublishRequestV1,
) -> tuple[
    tuple[tuple[str, bytes, str, str, int], ...],
    tuple[dict[str, object], ...],
]:
    if (request.prompt_bytes is None) is not (request.schema_bytes is None):
        raise AnswerTerminalRequestInvalidV1("Answer prompt/Schema pair is partial")
    if (request.answer_output_bytes is None) is not (
        request.answer_markdown_bytes is None
    ):
        raise AnswerTerminalRequestInvalidV1("Answer result pair is partial")
    stage_prefix = (
        request.effective_config_bytes,
        request.question_bytes,
        request.retrieval_query_bytes,
        request.retrieval_audit_bytes,
        request.retrieval_view_bytes,
    )
    if type(stage_prefix[0]) is not bytes:
        raise AnswerTerminalRequestInvalidV1(
            "Answer effective configuration is absent"
        )
    missing_seen = False
    for payload in stage_prefix:
        if payload is None:
            missing_seen = True
        elif missing_seen:
            raise AnswerTerminalRequestInvalidV1(
                "Answer root asset stage prefix is discontinuous"
            )
    payload_by_path: dict[str, bytes | None] = {
        "effective_config.json": request.effective_config_bytes,
        "question.json": request.question_bytes,
        "retrieval_query.json": request.retrieval_query_bytes,
        "retrieval_audit.json": request.retrieval_audit_bytes,
        "retrieval_view.json": request.retrieval_view_bytes,
        "prompt.txt": request.prompt_bytes,
        "schema.json": request.schema_bytes,
        "answer_output.json": request.answer_output_bytes,
        "answer.md": request.answer_markdown_bytes,
    }
    assets: list[tuple[str, bytes, str, str, int]] = []
    decoded: dict[str, dict[str, object]] = {}
    for path, identity_key, identity_value, cap in _ROOT_ASSET_SPECS:
        payload = payload_by_path[path]
        if payload is None:
            continue
        if type(payload) is not bytes or len(payload) > cap:
            raise AnswerTerminalRequestInvalidV1(
                "Answer asset type or capacity is invalid"
            )
        if path.endswith(".json"):
            document = _decode_canonical_json_asset(payload)
            decoded[path] = document
            if path == "schema.json":
                if document.get("$id") != (
                    "https://gezhi.local/schemas/answer-output-v1.schema.json"
                ):
                    raise AnswerTerminalRequestInvalidV1(
                        "Answer Schema snapshot identity is invalid"
                    )
            elif document.get("schema_version") != identity_value:
                raise AnswerTerminalRequestInvalidV1(
                    "Answer asset schema identity is invalid"
                )
            if (
                path == "effective_config.json"
                and document != _EXPECTED_EFFECTIVE_CONFIG
            ):
                raise AnswerTerminalRequestInvalidV1(
                    "Answer effective configuration is invalid"
                )
        else:
            _validate_utf8_text_asset_v1(payload, label=path)
        assets.append((path, payload, identity_key, identity_value, cap))

    audit = decoded.get("retrieval_audit.json")
    measurement: dict[str, object] | None
    if audit is None:
        measurement = None
    else:
        raw_measurement = audit.get("retrieval_view_measurement")
        if type(raw_measurement) is not dict:
            raise AnswerTerminalRequestInvalidV1(
                "Answer Retrieval View measurement is invalid"
            )
        measurement = raw_measurement
    view = decoded.get("retrieval_view.json")
    candidate_count: int | None = None
    if request.retrieval_view_bytes is not None:
        if view is None or type(view.get("candidate_count")) is not int:
            raise AnswerTerminalRequestInvalidV1("Answer Retrieval View is invalid")
        candidate_count = cast(int, view["candidate_count"])
        if measurement != {
            "byte_length": len(request.retrieval_view_bytes),
            "limit_bytes": 262_144,
            "sha256": hashlib.sha256(request.retrieval_view_bytes).hexdigest(),
            "status": "within_limit",
        }:
            raise AnswerTerminalRequestInvalidV1(
                "Answer Retrieval View measurement differs"
            )
    elif measurement is not None and (
        request.status != "interrupted" and measurement.get("status") != "too_large"
    ):
        raise AnswerTerminalRequestInvalidV1(
            "Missing Retrieval View is not an over-limit branch"
        )

    if request.status == "succeeded":
        if (
            request.error is not None
            or request.answer_output_bytes is None
            or candidate_count is None
        ):
            raise AnswerTerminalRequestInvalidV1(
                "Succeeded Answer terminal presence is invalid"
            )
        error: dict[str, object] | None = None
    elif request.status in {"blocked", "failed"}:
        if (
            type(request.error) is not dict
            or set(request.error) != {"code", "stage"}
            or request.answer_output_bytes is not None
        ):
            raise AnswerTerminalRequestInvalidV1(
                "Stopped Answer terminal presence is invalid"
            )
        code = request.error.get("code")
        stage = request.error.get("stage")
        if (
            type(code) is not str
            or type(stage) is not str
            or _ERROR_MATRIX.get(code) != (request.status, stage)
        ):
            raise AnswerTerminalRequestInvalidV1("Answer terminal error is invalid")
        error = dict(request.error)
    elif request.status == "interrupted":
        if request.error is not None or request.answer_output_bytes is not None:
            raise AnswerTerminalRequestInvalidV1(
                "Interrupted Answer terminal presence is invalid"
            )
        error = None
    else:
        raise AnswerTerminalRequestInvalidV1("Answer terminal status is invalid")

    has_call_pair = request.prompt_bytes is not None
    if has_call_pair and (candidate_count is None or not 1 <= candidate_count <= 12):
        raise AnswerTerminalRequestInvalidV1(
            "Answer synthesis pair has no non-zero Retrieval View"
        )
    if request.attempts and not has_call_pair:
        raise AnswerTerminalRequestInvalidV1("Answer attempts have no synthesis pair")
    if not 0 <= len(request.attempts) <= 3:
        raise AnswerTerminalRequestInvalidV1("Answer attempt count is invalid")
    if request.status == "succeeded" and (
        candidate_count == 0
        and (has_call_pair or request.attempts)
        or candidate_count is not None
        and candidate_count > 0
        and (not has_call_pair or not request.attempts)
    ):
        raise AnswerTerminalRequestInvalidV1(
            "Succeeded Answer synthesis presence is invalid"
        )
    if (
        error is not None
        and error.get("code") == "retrieval_view_too_large"
        and (
            request.retrieval_view_bytes is not None
            or has_call_pair
            or request.attempts
            or type(measurement) is not dict
            or measurement.get("status") != "too_large"
        )
    ):
        raise AnswerTerminalRequestInvalidV1(
            "Over-limit Retrieval View terminal presence is invalid"
        )

    attempt_records: list[dict[str, object]] = []
    for ordinal, attempt in enumerate(request.attempts, start=1):
        if type(attempt) is not AnswerAttemptPublishV1:
            raise AnswerTerminalRequestInvalidV1("Answer attempt type is invalid")
        record = _validate_attempt_record_v1(attempt.record)
        if (
            type(attempt.events_bytes) is not bytes
            or len(attempt.events_bytes) > _ATTEMPT_EVENTS_CAP
            or type(attempt.final_message_bytes) is not bytes
            or len(attempt.final_message_bytes) > _ATTEMPT_FINAL_CAP
        ):
            raise AnswerTerminalRequestInvalidV1(
                "Answer attempt capture capacity is invalid"
            )
        prefix = f"attempts/{ordinal:02d}"
        assets.extend(
            (
                (
                    prefix + "/events.jsonl",
                    attempt.events_bytes,
                    "media_type",
                    "application/octet-stream",
                    _ATTEMPT_EVENTS_CAP,
                ),
                (
                    prefix + "/final_message.txt",
                    attempt.final_message_bytes,
                    "media_type",
                    "application/octet-stream",
                    _ATTEMPT_FINAL_CAP,
                ),
            )
        )
        attempt_records.append(record)
    _validate_attempt_terminal_matrix_v1(
        status=request.status,
        error=error,
        candidate_count=candidate_count,
        attempts=attempt_records,
    )
    return tuple(assets), tuple(attempt_records)


def _validate_request(
    request: AnswerPublishRequestV1,
) -> tuple[
    dict[str, object],
    tuple[tuple[str, bytes, str, str, int], ...],
    tuple[dict[str, object], ...],
]:
    if type(request) is not AnswerPublishRequestV1:
        raise TypeError("Answer publish request type is invalid")
    if (
        type(request.answer_id) is not str
        or len(request.answer_id.encode("ascii", errors="ignore")) != 40
        or _ANSWER_ID.fullmatch(request.answer_id) is None
    ):
        raise AnswerTerminalRequestInvalidV1("Answer ID is invalid")
    _validate_timestamp(request.started_at)
    if (
        type(request.started_monotonic_ns) is not int
        or request.started_monotonic_ns < 0
    ):
        raise AnswerTerminalRequestInvalidV1("Answer monotonic start is invalid")
    provenance = _validate_provenance(request.provenance)
    assets, attempts = _request_assets(request)
    return provenance, assets, attempts


def _ensure_child_directory(
    parent: ValidatedDataRootV1,
    parent_path: Path,
    child: str,
) -> ValidatedDataRootV1:
    try:
        existing = _open_existing_child(parent, child)
        if existing is not None:
            return existing
        (parent_path / child).mkdir()
        return parent.open_relative_data_root_v1((child,))
    except (DataRootOpenErrorV1, FileExistsError, OSError, ValueError) as error:
        raise AnswerStagingFailedV1(
            "Answer staging directory could not be established"
        ) from error


def _read_safe_file(path: Path, *, cap: int) -> bytes:
    try:
        with open_validated_local_file_v1(str(path)) as source:
            if source.size > cap:
                raise ValueError("Answer asset exceeds its capacity")
            payload = b"".join(source.iter_verified_chunks_v1())
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        raise AnswerStagingFailedV1("Answer asset readback failed") from error
    if len(payload) > cap:
        raise AnswerStagingFailedV1("Answer asset exceeds its capacity")
    return payload


def _write_new_file(path: Path, payload: bytes) -> None:
    try:
        with (
            open_validated_data_root_v1(str(path.parent)),
            path.open("xb", buffering=0) as destination,
        ):
            view = memoryview(payload)
            offset = 0
            while offset < len(view):
                count = destination.write(view[offset:])
                if type(count) is not int or not 1 <= count <= len(view) - offset:
                    raise OSError("Answer write did not complete")
                offset += count
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        raise AnswerStagingFailedV1("Answer asset write failed") from error


def _install_assets(
    root: ValidatedDataRootV1,
    stage_path: Path,
    assets: tuple[tuple[str, bytes, str, str, int], ...],
) -> tuple[_VerifiedAssetV1, ...]:
    installed: list[_VerifiedAssetV1] = []
    attempt_ordinals = tuple(
        dict.fromkeys(
            path.split("/")[1]
            for path, _payload, _key, _value, _cap in assets
            if path.startswith("attempts/")
        )
    )
    if attempt_ordinals:
        try:
            (stage_path / "attempts").mkdir()
            for ordinal in attempt_ordinals:
                (stage_path / "attempts" / ordinal).mkdir()
        except OSError as error:
            raise AnswerStagingFailedV1(
                "Answer attempt directories could not be formed"
            ) from error
    for path, payload, identity_key, identity_value, cap in assets:
        _root_checkpoint(root)
        target = stage_path / path
        _write_new_file(target, payload)
        observed = _read_safe_file(target, cap=cap)
        if observed != payload or len(observed) != len(payload):
            raise AnswerStagingFailedV1("Answer asset readback differs")
        installed.append(
            _VerifiedAssetV1(
                path=path,
                byte_length=len(observed),
                sha256=hashlib.sha256(observed).hexdigest(),
                identity_key=cast(Literal["schema_id", "media_type"], identity_key),
                identity_value=identity_value,
            )
        )
    try:
        with open_validated_data_root_v1(str(stage_path)) as stage:
            names = stage.relative_entry_names_v1()
        root_names = tuple(
            sorted(
                {"attempts" if "/" in item.path else item.path for item in installed}
            )
        )
        if names != root_names:
            raise ValueError("Answer root asset set is not closed")
        if attempt_ordinals:
            with open_validated_data_root_v1(str(stage_path / "attempts")) as nested:
                if nested.relative_entry_names_v1() != tuple(sorted(attempt_ordinals)):
                    raise ValueError("Answer attempt ordinal set is not closed")
            for ordinal in attempt_ordinals:
                with open_validated_data_root_v1(
                    str(stage_path / "attempts" / ordinal)
                ) as attempt_root:
                    if attempt_root.relative_entry_names_v1() != (
                        "events.jsonl",
                        "final_message.txt",
                    ):
                        raise ValueError("Answer attempt asset pair is not closed")
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        raise AnswerStagingFailedV1(
            "Answer staging closure could not be proved"
        ) from error
    return tuple(installed)


def _manifest_bytes(
    request: AnswerPublishRequestV1,
    provenance: dict[str, object],
    assets: tuple[_VerifiedAssetV1, ...],
    attempts: tuple[dict[str, object], ...],
) -> bytes:
    try:
        finished_at = _utc_now_milliseconds_v1()
        _validate_timestamp(finished_at)
        finished_monotonic_ns = time.monotonic_ns()
    except (AnswerTerminalRequestInvalidV1, OSError, RuntimeError) as error:
        raise AnswerManifestFailedV1(
            "Answer finish boundary could not be formed"
        ) from error
    elapsed_ns = finished_monotonic_ns - request.started_monotonic_ns
    if elapsed_ns < 0:
        raise AnswerManifestFailedV1("Answer elapsed time is invalid")
    elapsed_ms = elapsed_ns // 1_000_000
    if elapsed_ms > _INT64_MAX:
        raise AnswerManifestFailedV1("Answer elapsed time is invalid")
    asset_items = sorted(
        (asset.manifest_item() for asset in assets),
        key=lambda item: cast(str, item["path"]).encode("utf-8"),
    )
    usage_totals: dict[str, int | None] = {}
    for name in (
        "cached_input_tokens",
        "input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    ):
        values = [attempt[name] for attempt in attempts]
        if any(type(value) is not int for value in values):
            usage_totals[name] = None
            continue
        total = sum(cast(int, value) for value in values)
        usage_totals[name] = total if total <= _INT64_MAX else None
    manifest = {
        "schema_version": "gezhi.answer_manifest.v1",
        "answer_id": request.answer_id,
        "status": request.status,
        "error": None if request.error is None else dict(request.error),
        "started_at": request.started_at,
        "finished_at": finished_at,
        "elapsed_ms": elapsed_ms,
        "provenance": provenance,
        "attempts": list(attempts),
        "usage_totals": usage_totals,
        "assets": asset_items,
    }
    try:
        payload = _canonical_json_file(manifest)
    except (TypeError, ValueError, UnicodeError) as error:
        raise AnswerManifestFailedV1(
            "Answer manifest could not be serialized"
        ) from error
    if len(payload) > ANSWER_MANIFEST_MAX_BYTES:
        raise AnswerManifestFailedV1("Answer manifest exceeds its capacity")
    aggregate = len(payload)
    for asset in assets:
        aggregate += asset.byte_length
        if aggregate > _INT64_MAX or aggregate > ANSWER_TERMINAL_MAX_BYTES:
            raise AnswerManifestFailedV1("Answer terminal tree exceeds its capacity")
    return payload


def _install_and_validate_manifest(
    root: ValidatedDataRootV1,
    stage_path: Path,
    manifest_bytes: bytes,
    assets: tuple[_VerifiedAssetV1, ...],
) -> None:
    manifest_path = stage_path / "manifest.json"
    try:
        _write_new_file(manifest_path, manifest_bytes)
        observed = _read_safe_file(
            manifest_path,
            cap=ANSWER_MANIFEST_MAX_BYTES,
        )
    except AnswerStagingFailedV1 as error:
        raise AnswerManifestFailedV1(
            "Answer manifest write or readback failed"
        ) from error
    if observed != manifest_bytes:
        raise AnswerManifestFailedV1("Answer manifest readback differs")
    try:
        decoded = _decode_canonical_json_asset(observed)
    except AnswerTerminalRequestInvalidV1 as error:
        raise AnswerManifestFailedV1("Answer manifest is invalid") from error
    if decoded.get("schema_version") != "gezhi.answer_manifest.v1":
        raise AnswerManifestFailedV1("Answer manifest identity is invalid")
    try:
        with open_validated_data_root_v1(str(stage_path)) as stage:
            names = stage.relative_entry_names_v1()
    except (DataRootOpenErrorV1, OSError) as error:
        raise AnswerManifestFailedV1(
            "Answer terminal tree closure could not be proved"
        ) from error
    expected_names = tuple(
        sorted(
            {"attempts" if "/" in asset.path else asset.path for asset in assets}
            | {"manifest.json"}
        )
    )
    if names != expected_names:
        raise AnswerManifestFailedV1(
            "Answer terminal tree contains an unexpected entry"
        )
    _root_checkpoint(root)


def _namespace_state(
    root: ValidatedDataRootV1,
    answer_id: str,
) -> tuple[bool, bool]:
    try:
        answers = root.open_relative_data_root_v1(("answers",))
        with answers:
            target_present = _case_insensitive_name_present(
                answers.relative_entry_names_v1(), answer_id
            )
            staging = answers.open_relative_data_root_v1((".staging",))
            with staging:
                staging_present = _case_insensitive_name_present(
                    staging.relative_entry_names_v1(), answer_id
                )
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        _root_checkpoint(root)
        raise AnswerCommitIndeterminateV1(
            "Answer namespace state is indeterminate"
        ) from error
    return staging_present, target_present


def publish_answer_v1(
    root: ValidatedDataRootV1,
    ownership: WriterOwnershipV1,
    request: AnswerPublishRequestV1,
) -> CommittedAnswerProofV1:
    """Create, validate, and non-replacingly publish one terminal Answer."""

    _assert_writer_ownership(root, ownership)
    provenance, request_assets, attempt_records = _validate_request(request)
    root_path_text, root_identity = _root_facts(root)
    root_path = Path(root_path_text)
    _root_checkpoint(root)

    try:
        answers = _ensure_child_directory(root, root_path, "answers")
    except AnswerStagingFailedV1:
        _root_checkpoint(root)
        raise
    with answers:
        try:
            staging = _ensure_child_directory(
                answers,
                root_path / "answers",
                ".staging",
            )
        except AnswerStagingFailedV1:
            _root_checkpoint(root)
            raise
        with staging:
            answer_names = answers.relative_entry_names_v1()
            if _case_insensitive_name_present(answer_names, request.answer_id):
                raise AnswerTargetConflictV1("Answer target already exists")
            staging_names = staging.relative_entry_names_v1()
            if _case_insensitive_name_present(staging_names, request.answer_id):
                raise AnswerStagingFailedV1("Answer staging already exists")
            stage_path = root_path / "answers" / ".staging" / request.answer_id
            try:
                stage_path.mkdir()
                stage = staging.open_relative_data_root_v1((request.answer_id,))
            except (DataRootOpenErrorV1, FileExistsError, OSError) as error:
                raise AnswerStagingFailedV1(
                    "Answer staging could not be created"
                ) from error
            with stage:
                stage_identity = stage.inspection.identity
                if stage_identity is None or stage_identity[0] != root_identity[0]:
                    raise AnswerStagingFailedV1("Answer staging identity is invalid")

    try:
        installed = _install_assets(root, stage_path, request_assets)
    except AnswerStagingFailedV1:
        _root_checkpoint(root)
        raise
    try:
        manifest_bytes = _manifest_bytes(
            request,
            provenance,
            installed,
            attempt_records,
        )
        _install_and_validate_manifest(root, stage_path, manifest_bytes, installed)
    except AnswerManifestFailedV1:
        _root_checkpoint(root)
        raise

    _root_checkpoint(root)
    try:
        with root.open_relative_data_root_v1(
            ("answers", ".staging", request.answer_id)
        ) as final_stage:
            if final_stage.inspection.identity != stage_identity:
                raise AnswerRootIntegrityLostV1("Answer staging identity changed")
        with root.open_relative_data_root_v1(("answers",)) as final_answers:
            if _case_insensitive_name_present(
                final_answers.relative_entry_names_v1(), request.answer_id
            ):
                raise AnswerTargetConflictV1("Answer target already exists")
    except AnswerTerminalErrorV1:
        raise
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        _root_checkpoint(root)
        raise AnswerRootIntegrityLostV1(
            "Answer final checkpoint could not be proved"
        ) from error

    target_path = root_path / "answers" / request.answer_id
    try:
        os.rename(stage_path, target_path)
    except OSError as error:
        _root_checkpoint(root)
        staging_present, target_present = _namespace_state(root, request.answer_id)
        if staging_present and target_present and isinstance(error, FileExistsError):
            raise AnswerTargetConflictV1("Answer target already exists") from error
        if staging_present and not target_present:
            raise AnswerCommitFailedV1("Answer rename did not commit") from error
        raise AnswerCommitIndeterminateV1(
            "Answer rename outcome is indeterminate"
        ) from error

    _root_checkpoint(root)
    return CommittedAnswerProofV1(
        answer_id=request.answer_id,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        status=request.status,
        error=None if request.error is None else dict(request.error),
        answer_output_bytes=request.answer_output_bytes,
        answer_markdown_bytes=request.answer_markdown_bytes,
    )


__all__ = [
    "ANSWER_MANIFEST_MAX_BYTES",
    "ANSWER_TERMINAL_MAX_BYTES",
    "AnswerAttemptPublishV1",
    "AnswerCommitFailedV1",
    "AnswerCommitIndeterminateV1",
    "AnswerManifestFailedV1",
    "AnswerOrphanScanFailedV1",
    "AnswerPublishRequestV1",
    "AnswerRootIntegrityLostV1",
    "AnswerStagingFailedV1",
    "AnswerStagingScanV1",
    "AnswerTargetConflictV1",
    "AnswerTerminalErrorV1",
    "AnswerTerminalRequestInvalidV1",
    "AnswerWriterOwnershipInvalidV1",
    "CommittedAnswerProofV1",
    "publish_answer_v1",
    "scan_answer_staging_v1",
]
