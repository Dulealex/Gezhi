from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeAlias, cast

from gezhi._knowledge_answerer import (
    KnowledgeAnswererInputInvalidV1,
    validate_terminal_answer_content_v1,
)
from gezhi._knowledge_attempt_events import (
    KNOWLEDGE_ATTEMPT_EVENTS_CAP_V1,
    parse_knowledge_attempt_events_v1,
    project_knowledge_attempt_usage_v1,
)
from gezhi._knowledge_retrieval import (
    RetrievalMaterializationFailedV1,
    validate_terminal_retrieval_assets_v1,
)
from gezhi._windows_data_root import (
    DataRootLifecycleErrorV1,
    DataRootOpenErrorV1,
    ValidatedDataRootV1,
    create_exclusive_file_bytes_v1,
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
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_JSON_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
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

_ATTEMPT_EVENTS_CAP = KNOWLEDGE_ATTEMPT_EVENTS_CAP_V1
_ATTEMPT_FINAL_CAP = 1_048_576
_ASSET_READ_ORDER = (
    "effective_config.json",
    "question.json",
    "retrieval_query.json",
    "retrieval_audit.json",
    "retrieval_view.json",
    "prompt.txt",
    "schema.json",
    "attempts/01/events.jsonl",
    "attempts/01/final_message.txt",
    "attempts/02/events.jsonl",
    "attempts/02/final_message.txt",
    "attempts/03/events.jsonl",
    "attempts/03/final_message.txt",
    "answer_output.json",
    "answer.md",
)
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

StagingScanStatusV1: TypeAlias = Literal["empty", "complete"]


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
    quarantined_count: int = 0
    recovered_count: int = 0
    recovery_failed_count: int = 0
    target_conflict_count: int = 0


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
class TerminalAnswerBytesReadyV1:
    """One fully revalidated committed Answer and its Human projection."""

    answer_id: str
    manifest_sha256: str
    status: Literal["succeeded", "blocked", "failed", "interrupted"]
    error: dict[str, object] | None
    answer_output_bytes: bytes | None
    answer_markdown_bytes: bytes | None
    answer_markdown_text: str | None
    retrieval_view_bytes: bytes | None = None


@dataclass(frozen=True, slots=True)
class TerminalAnswerBytesRejectedV1:
    """The requested formal target failed closed as one indivisible Answer."""

    answer_id: str


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


class _TerminalCandidateRejectedV1(ValueError):
    """Internal whole-candidate rejection; no partial facts may escape."""


@dataclass(frozen=True, slots=True)
class _InspectedAnswerOrphanV1:
    answer_id: str
    candidate_identity: tuple[int, int]
    terminal: TerminalAnswerBytesReadyV1


@dataclass(frozen=True, slots=True)
class _ManifestTerminalFactsV1:
    status: Literal["succeeded", "blocked", "failed", "interrupted"]
    error: dict[str, object] | None
    provenance: dict[str, object]
    attempts: tuple[dict[str, object], ...]


@dataclass(slots=True)
class _JsonContainerFrameV1:
    kind: Literal["object", "array"]
    state: str
    item_count: int = 0


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


def _case_insensitive_entry_present(
    parent: ValidatedDataRootV1,
    expected: str,
) -> bool:
    return _case_insensitive_name_present(
        tuple(entry.name for entry in parent.relative_entries_v1()),
        expected,
    )


def _open_existing_child(
    parent: ValidatedDataRootV1,
    child: str,
) -> ValidatedDataRootV1 | None:
    aliases = tuple(
        entry
        for entry in parent.relative_entries_v1()
        if entry.name.lower() == child.lower()
    )
    if not aliases:
        return None
    if (
        len(aliases) != 1
        or aliases[0].name != child
        or not aliases[0].is_directory
        or aliases[0].is_reparse
        or aliases[0].short_name is not None
    ):
        raise DataRootOpenErrorV1("unsafe")
    return parent.open_relative_data_root_v1((child,))


def scan_answer_staging_v1(
    root: ValidatedDataRootV1,
    ownership: WriterOwnershipV1,
) -> AnswerStagingScanV1:
    """Inspect and, when fully proved, complete historical terminal commits."""

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
                entries = staging.relative_entries_v1()
    except AnswerRootIntegrityLostV1:
        raise
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        _root_checkpoint(root)
        raise AnswerOrphanScanFailedV1(
            "Answer staging could not be safely enumerated"
        ) from error
    _root_checkpoint(root)
    if not entries:
        return AnswerStagingScanV1(status="empty", entry_count=0)

    quarantined_count = 0
    recovered_count = 0
    recovery_failed_count = 0
    target_conflict_count = 0
    for entry in entries:
        name = entry.name
        if (
            _ANSWER_ID.fullmatch(name) is None
            or entry.is_reparse
            or not entry.is_directory
            or entry.short_name is not None
        ):
            quarantined_count += 1
            continue
        try:
            inspected = _inspect_answer_orphan_v1(root, ownership, name)
        except _TerminalCandidateRejectedV1:
            quarantined_count += 1
            continue
        outcome = _complete_answer_orphan_v1(root, ownership, inspected)
        if outcome == "recovered":
            recovered_count += 1
        elif outcome == "target_conflict":
            target_conflict_count += 1
        elif outcome == "recovery_failed":
            recovery_failed_count += 1
        else:
            raise RuntimeError("Answer orphan completion outcome is invalid")
    _root_checkpoint(root)
    return AnswerStagingScanV1(
        status="complete",
        entry_count=len(entries),
        quarantined_count=quarantined_count,
        recovered_count=recovered_count,
        recovery_failed_count=recovery_failed_count,
        target_conflict_count=target_conflict_count,
    )


def _consume_current_publish_v1(
    root: ValidatedDataRootV1,
    ownership: WriterOwnershipV1,
) -> None:
    _, identity = _root_facts(root)
    if type(ownership) is not WriterOwnershipV1:
        raise TypeError("Knowledge Answer writer ownership type is invalid")
    try:
        ownership.consume_knowledge_answer_publish_v1(identity)
    except (WriterOwnershipLifecycleErrorV1, ValueError) as error:
        raise AnswerWriterOwnershipInvalidV1(
            "Knowledge Answer current publication is unavailable"
        ) from error


def _bind_current_staging_v1(
    root: ValidatedDataRootV1,
    ownership: WriterOwnershipV1,
    answer_id: str,
) -> None:
    _, identity = _root_facts(root)
    try:
        ownership.bind_knowledge_answer_active_staging_v1(identity, answer_id)
    except (WriterOwnershipLifecycleErrorV1, ValueError) as error:
        raise AnswerWriterOwnershipInvalidV1(
            "Knowledge Answer current staging could not be bound"
        ) from error


def _inspect_answer_orphan_v1(
    root: ValidatedDataRootV1,
    ownership: WriterOwnershipV1,
    answer_id: str,
) -> _InspectedAnswerOrphanV1:
    _assert_writer_ownership(root, ownership)
    if _ANSWER_ID.fullmatch(answer_id) is None:
        raise _TerminalCandidateRejectedV1("Answer orphan basename is invalid")
    _, identity = _root_facts(root)
    try:
        ownership.assert_knowledge_answer_orphan_ownership_v1(identity, answer_id)
    except (WriterOwnershipLifecycleErrorV1, ValueError) as error:
        raise AnswerWriterOwnershipInvalidV1(
            "current Answer staging cannot enter orphan recovery"
        ) from error
    terminal = _validate_terminal_candidate_v1(
        root,
        ("answers", ".staging", answer_id),
        answer_id,
    )
    try:
        with root.open_relative_data_root_v1(
            ("answers", ".staging", answer_id)
        ) as candidate:
            candidate_identity = candidate.inspection.identity
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        raise _TerminalCandidateRejectedV1(
            "Answer orphan identity could not be proved"
        ) from error
    if candidate_identity is None:
        raise _TerminalCandidateRejectedV1("Answer orphan identity could not be proved")
    return _InspectedAnswerOrphanV1(
        answer_id=answer_id,
        candidate_identity=candidate_identity,
        terminal=terminal,
    )


def _classify_existing_answer_target_v1(
    root: ValidatedDataRootV1,
    answer_id: str,
) -> Literal["committed", "quarantined"]:
    try:
        _validate_terminal_candidate_v1(
            root,
            ("answers", answer_id),
            answer_id,
        )
    except _TerminalCandidateRejectedV1:
        return "quarantined"
    return "committed"


def _complete_answer_orphan_v1(
    root: ValidatedDataRootV1,
    ownership: WriterOwnershipV1,
    inspected: _InspectedAnswerOrphanV1,
) -> Literal["recovered", "target_conflict", "recovery_failed"]:
    _assert_writer_ownership(root, ownership)
    if type(inspected) is not _InspectedAnswerOrphanV1:
        raise TypeError("Inspected Answer orphan type is invalid")
    answer_id = inspected.answer_id
    root_path_text, root_identity = _root_facts(root)
    _root_checkpoint(root)
    try:
        with root.open_relative_data_root_v1(
            ("answers", ".staging", answer_id)
        ) as candidate:
            if (
                candidate.inspection.identity != inspected.candidate_identity
                or candidate.inspection.identity is None
                or candidate.inspection.identity[0] != root_identity[0]
            ):
                raise AnswerRootIntegrityLostV1("Answer orphan identity changed")
        with root.open_relative_data_root_v1(("answers",)) as answers:
            target_present = _case_insensitive_entry_present(answers, answer_id)
        if target_present:
            target_state = _classify_existing_answer_target_v1(root, answer_id)
            if target_state not in {"committed", "quarantined"}:
                raise RuntimeError("Answer target classification is invalid")
            return "target_conflict"
    except AnswerRootIntegrityLostV1:
        raise
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        _root_checkpoint(root)
        raise AnswerRootIntegrityLostV1(
            "Answer orphan final checkpoint could not be proved"
        ) from error

    _root_checkpoint(root)
    root_path = Path(root_path_text)
    stage_path = root_path / "answers" / ".staging" / answer_id
    target_path = root_path / "answers" / answer_id
    try:
        os.rename(stage_path, target_path)
    except OSError as error:
        _root_checkpoint(root)
        staging_present, target_present = _namespace_state(root, answer_id)
        if staging_present and target_present and isinstance(error, FileExistsError):
            target_state = _classify_existing_answer_target_v1(root, answer_id)
            if target_state not in {"committed", "quarantined"}:
                raise RuntimeError("Answer target classification is invalid")
            return "target_conflict"
        if staging_present and not target_present:
            return "recovery_failed"
        raise AnswerCommitIndeterminateV1(
            "Answer orphan rename outcome is indeterminate"
        ) from error
    _root_checkpoint(root)
    return "recovered"


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
    if type(decoded) is not dict:
        raise AnswerTerminalRequestInvalidV1("Answer JSON asset is not canonical")
    try:
        canonical = _canonical_json_file(decoded)
    except (TypeError, ValueError, UnicodeError) as error:
        raise AnswerTerminalRequestInvalidV1(
            "Answer JSON asset is not canonical"
        ) from error
    if canonical != payload:
        raise AnswerTerminalRequestInvalidV1("Answer JSON asset is not canonical")
    return cast(dict[str, object], decoded)


def _skip_json_string_v1(value: str, offset: int) -> int:
    if offset >= len(value) or value[offset] != '"':
        raise ValueError("JSON string is absent")
    index = offset + 1
    while index < len(value):
        character = value[index]
        if character == '"':
            return index + 1
        if ord(character) < 0x20:
            raise ValueError("JSON string contains a control character")
        if character != "\\":
            index += 1
            continue
        index += 1
        if index >= len(value) or value[index] not in '"\\/bfnrtu':
            raise ValueError("JSON string escape is invalid")
        if value[index] == "u":
            digits = value[index + 1 : index + 5]
            if len(digits) != 4 or any(
                digit not in "0123456789abcdefABCDEF" for digit in digits
            ):
                raise ValueError("JSON Unicode escape is invalid")
            index += 5
        else:
            index += 1
    raise ValueError("JSON string is unterminated")


def _manifest_structural_preflight_v1(value: str) -> None:
    stack: list[_JsonContainerFrameV1] = []
    root_state = "value"
    total_pairs = 0
    total_array_items = 0
    total_containers = 0
    total_nodes = 0
    index = 0

    def skip_space(offset: int) -> int:
        while offset < len(value) and value[offset] in " \t\r\n":
            offset += 1
        return offset

    def begin_value(offset: int) -> int:
        nonlocal total_containers, total_nodes
        offset = skip_space(offset)
        if offset >= len(value):
            raise ValueError("JSON value is absent")
        total_nodes += 1
        if total_nodes > 256:
            raise ValueError("JSON node limit is exceeded")
        character = value[offset]
        if character in "{[":
            total_containers += 1
            if total_containers > 32 or len(stack) + 1 > 8:
                raise ValueError("JSON container limit is exceeded")
            stack.append(
                _JsonContainerFrameV1(
                    kind="object" if character == "{" else "array",
                    state="key_or_end" if character == "{" else "value_or_end",
                )
            )
            return offset + 1
        if character == '"':
            return _skip_json_string_v1(value, offset)
        for literal in ("true", "false", "null"):
            if value.startswith(literal, offset):
                return offset + len(literal)
        match = _JSON_NUMBER.match(value, offset)
        if match is None:
            raise ValueError("JSON scalar is invalid")
        return match.end()

    while True:
        index = skip_space(index)
        if not stack:
            if root_state == "value":
                root_state = "done"
                index = begin_value(index)
                continue
            if index != len(value):
                raise ValueError("JSON has trailing content")
            return

        frame = stack[-1]
        if frame.kind == "object":
            if frame.state in {"key_or_end", "key"}:
                if (
                    frame.state == "key_or_end"
                    and index < len(value)
                    and value[index] == "}"
                ):
                    stack.pop()
                    index += 1
                    continue
                if index >= len(value) or value[index] != '"':
                    raise ValueError("JSON object key is invalid")
                index = _skip_json_string_v1(value, index)
                frame.item_count += 1
                total_pairs += 1
                if frame.item_count > 16 or total_pairs > 128:
                    raise ValueError("JSON object pair limit is exceeded")
                frame.state = "colon"
                continue
            if frame.state == "colon":
                if index >= len(value) or value[index] != ":":
                    raise ValueError("JSON object colon is absent")
                frame.state = "value"
                index += 1
                continue
            if frame.state == "value":
                frame.state = "comma_or_end"
                index = begin_value(index)
                continue
            if index < len(value) and value[index] == ",":
                frame.state = "key"
                index += 1
                continue
            if index < len(value) and value[index] == "}":
                stack.pop()
                index += 1
                continue
            raise ValueError("JSON object terminator is invalid")

        if frame.state in {"value_or_end", "value"}:
            if (
                frame.state == "value_or_end"
                and index < len(value)
                and value[index] == "]"
            ):
                stack.pop()
                index += 1
                continue
            frame.item_count += 1
            total_array_items += 1
            if frame.item_count > 16 or total_array_items > 32:
                raise ValueError("JSON array item limit is exceeded")
            frame.state = "comma_or_end"
            index = begin_value(index)
            continue
        if index < len(value) and value[index] == ",":
            frame.state = "value"
            index += 1
            continue
        if index < len(value) and value[index] == "]":
            stack.pop()
            index += 1
            continue
        raise ValueError("JSON array terminator is invalid")


def _parse_manifest_int_v1(value: str) -> int:
    digits = value.removeprefix("-")
    if len(digits) > 19 or not digits or not digits.isascii():
        raise ValueError("JSON integer digit limit is exceeded")
    return int(value)


def _decode_terminal_manifest_v1(payload: bytes) -> dict[str, object]:
    if (
        len(payload) > ANSWER_MANIFEST_MAX_BYTES
        or payload.startswith(b"\xef\xbb\xbf")
        or not payload.endswith(b"\n")
        or b"\r" in payload
        or b"\n" in payload[:-1]
    ):
        raise AnswerTerminalRequestInvalidV1(
            "Answer terminal manifest framing is invalid"
        )
    try:
        decoded_text = payload[:-1].decode("utf-8", errors="strict")
        _manifest_structural_preflight_v1(decoded_text)
        decoded = json.loads(
            decoded_text,
            strict=True,
            object_pairs_hook=_closed_object,
            parse_int=_parse_manifest_int_v1,
            parse_float=_reject_json_float,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise AnswerTerminalRequestInvalidV1(
            "Answer terminal manifest parser rejected the input"
        ) from error
    if type(decoded) is not dict:
        raise AnswerTerminalRequestInvalidV1(
            "Answer terminal manifest is not canonical"
        )
    try:
        canonical = _canonical_json_file(decoded)
    except (TypeError, ValueError, UnicodeError) as error:
        raise AnswerTerminalRequestInvalidV1(
            "Answer terminal manifest is not canonical"
        ) from error
    if canonical != payload:
        raise AnswerTerminalRequestInvalidV1(
            "Answer terminal manifest is not canonical"
        )
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


def _validate_retrieval_view_measurement_v1(
    value: object,
) -> dict[str, object]:
    if type(value) is not dict or set(value) != {
        "byte_length",
        "limit_bytes",
        "sha256",
        "status",
    }:
        raise AnswerTerminalRequestInvalidV1(
            "Answer Retrieval View measurement is invalid"
        )
    byte_length = value["byte_length"]
    status = value["status"]
    if (
        type(byte_length) is not int
        or not 0 <= byte_length <= _INT64_MAX
        or type(value["limit_bytes"]) is not int
        or value["limit_bytes"] != 262_144
        or type(value["sha256"]) is not str
        or _SHA256.fullmatch(value["sha256"]) is None
        or type(status) is not str
        or status not in {"within_limit", "too_large"}
        or status == "within_limit"
        and byte_length > 262_144
        or status == "too_large"
        and byte_length <= 262_144
    ):
        raise AnswerTerminalRequestInvalidV1(
            "Answer Retrieval View measurement is invalid"
        )
    return dict(value)


def _validate_attempt_evidence_v1(
    record: Mapping[str, object],
    events: bytes,
) -> None:
    if (
        len(events) == _ATTEMPT_EVENTS_CAP
        and record["failure_class"] == "process_error"
    ):
        records: tuple[dict[str, object], ...] = ()
        events_valid = True
    else:
        records, events_valid = parse_knowledge_attempt_events_v1(events)
    projected = project_knowledge_attempt_usage_v1(
        events,
        records,
        events_valid=events_valid,
    )
    if not events_valid and record["failure_class"] != "process_error":
        raise AnswerTerminalRequestInvalidV1(
            "Answer attempt events differ from failure class"
        )
    has_completed = any(record.get("type") == "turn.completed" for record in records)
    has_provider_failure = any(
        record.get("type") in {"turn.failed", "error"} for record in records
    )
    if record["failure_class"] is None and (
        not events_valid or not has_completed or has_provider_failure
    ):
        raise AnswerTerminalRequestInvalidV1(
            "Answer attempt events differ from failure class"
        )
    recorded = tuple(
        record[name]
        for name in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        )
    )
    if recorded != projected:
        raise AnswerTerminalRequestInvalidV1("Answer attempt usage differs from events")


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


def _validate_root_terminal_matrix_v1(
    *,
    status: str,
    error: dict[str, object] | None,
    prefix_level: int,
    has_call_pair: bool,
    candidate_count: int | None,
    attempt_count: int,
) -> None:
    error_code = None if error is None else error.get("code")
    no_synthesis = not has_call_pair and candidate_count is None and attempt_count == 0
    zero_candidate = (
        prefix_level == 4
        and not has_call_pair
        and candidate_count == 0
        and attempt_count == 0
    )
    nonzero_without_call = (
        prefix_level == 4
        and not has_call_pair
        and candidate_count is not None
        and 1 <= candidate_count <= 12
        and attempt_count == 0
    )
    nonzero_with_call = (
        prefix_level == 4
        and has_call_pair
        and candidate_count is not None
        and 1 <= candidate_count <= 12
    )

    valid = False
    if status == "succeeded":
        valid = zero_candidate or (nonzero_with_call and 1 <= attempt_count <= 3)
    elif status == "interrupted":
        valid = (
            0 <= prefix_level <= 3
            and no_synthesis
            or zero_candidate
            or nonzero_without_call
            or nonzero_with_call
            and 0 <= attempt_count <= 3
        )
    elif error_code in {"fts5_unavailable", "retrieval_query_failed"}:
        valid = prefix_level == 2 and no_synthesis
    elif error_code == "retrieval_view_too_large":
        valid = prefix_level == 3 and no_synthesis
    elif error_code == "retrieval_materialization_failed":
        valid = 0 <= prefix_level <= 3 and no_synthesis
    elif error_code == "synthesis_input_invalid":
        valid = nonzero_without_call
    elif error_code == "codex_runtime_unavailable":
        valid = nonzero_with_call and attempt_count == 0
    elif error_code in {"codex_timeout_exhausted", "codex_process_failed"}:
        valid = nonzero_with_call and 1 <= attempt_count <= 3
    elif error_code in {
        "answer_output_invalid",
        "citation_link_construction_failed",
        "answer_rendering_failed",
    }:
        valid = zero_candidate or (nonzero_with_call and 1 <= attempt_count <= 3)
    if not valid:
        raise AnswerTerminalRequestInvalidV1("Answer root terminal matrix differs")


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
        raise AnswerTerminalRequestInvalidV1("Answer effective configuration is absent")
    missing_seen = False
    for payload in stage_prefix:
        if payload is None:
            missing_seen = True
        elif missing_seen:
            raise AnswerTerminalRequestInvalidV1(
                "Answer root asset stage prefix is discontinuous"
            )
    prefix_level = sum(payload is not None for payload in stage_prefix) - 1
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
        measurement = _validate_retrieval_view_measurement_v1(raw_measurement)
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
    elif measurement is not None:
        materialization_failed = (
            request.status == "failed"
            and type(request.error) is dict
            and request.error.get("code") == "retrieval_materialization_failed"
        )
        if not (
            request.status == "interrupted"
            or materialization_failed
            and measurement.get("status") == "within_limit"
            or not materialization_failed
            and measurement.get("status") == "too_large"
        ):
            raise AnswerTerminalRequestInvalidV1(
                "Missing Retrieval View has an invalid measurement cause"
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
        _validate_attempt_evidence_v1(record, attempt.events_bytes)
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
    _validate_root_terminal_matrix_v1(
        status=request.status,
        error=error,
        prefix_level=prefix_level,
        has_call_pair=has_call_pair,
        candidate_count=candidate_count,
        attempt_count=len(attempt_records),
    )
    _validate_attempt_terminal_matrix_v1(
        status=request.status,
        error=error,
        candidate_count=candidate_count,
        attempts=attempt_records,
    )
    if request.question_bytes is not None:
        try:
            validate_terminal_retrieval_assets_v1(
                question_bytes=request.question_bytes,
                retrieval_query_bytes=request.retrieval_query_bytes,
                retrieval_audit_bytes=request.retrieval_audit_bytes,
                retrieval_view_bytes=request.retrieval_view_bytes,
            )
        except RetrievalMaterializationFailedV1 as error:
            raise AnswerTerminalRequestInvalidV1(
                "Answer retrieval assets are invalid"
            ) from error
    if request.question_bytes is not None and request.retrieval_view_bytes is not None:
        try:
            validate_terminal_answer_content_v1(
                question_bytes=request.question_bytes,
                retrieval_view_bytes=request.retrieval_view_bytes,
                prompt_bytes=request.prompt_bytes,
                schema_bytes=request.schema_bytes,
                answer_output_bytes=request.answer_output_bytes,
                answer_markdown_bytes=request.answer_markdown_bytes,
            )
        except KnowledgeAnswererInputInvalidV1 as error:
            raise AnswerTerminalRequestInvalidV1(
                "Answer synthesis assets are invalid"
            ) from error
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
            payload = source.read_bytes_v1(limit=cap)
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        raise AnswerStagingFailedV1("Answer asset readback failed") from error
    if len(payload) > cap:
        raise AnswerStagingFailedV1("Answer asset exceeds its capacity")
    return payload


def _asset_contract_v1(
    path: str,
) -> tuple[Literal["schema_id", "media_type"], str, int]:
    for expected_path, identity_key, identity_value, cap in _ROOT_ASSET_SPECS:
        if path == expected_path:
            return (
                cast(Literal["schema_id", "media_type"], identity_key),
                identity_value,
                cap,
            )
    match = re.fullmatch(
        r"attempts/(0[1-3])/(events\.jsonl|final_message\.txt)",
        path,
    )
    if match is None:
        raise _TerminalCandidateRejectedV1("Answer asset path is not recognized")
    if match.group(2) == "events.jsonl":
        return "media_type", "application/octet-stream", _ATTEMPT_EVENTS_CAP
    return "media_type", "application/octet-stream", _ATTEMPT_FINAL_CAP


def _manifest_assets_v1(value: object) -> tuple[_VerifiedAssetV1, ...]:
    if type(value) is not list or not 1 <= len(value) <= 15:
        raise _TerminalCandidateRejectedV1("Answer asset inventory is invalid")
    observed: list[_VerifiedAssetV1] = []
    previous_path_bytes: bytes | None = None
    for raw_item in value:
        if type(raw_item) is not dict:
            raise _TerminalCandidateRejectedV1("Answer asset item is invalid")
        item = cast(dict[str, object], raw_item)
        path = item.get("path")
        byte_length = item.get("byte_length")
        digest = item.get("sha256")
        if type(path) is not str:
            raise _TerminalCandidateRejectedV1("Answer asset path is invalid")
        identity_key, identity_value, cap = _asset_contract_v1(path)
        if set(item) != {"path", "byte_length", "sha256", identity_key}:
            raise _TerminalCandidateRejectedV1("Answer asset identity is invalid")
        if item.get(identity_key) != identity_value:
            raise _TerminalCandidateRejectedV1("Answer asset identity is invalid")
        if (
            type(byte_length) is not int
            or not 0 <= byte_length <= _INT64_MAX
            or byte_length > cap
            or type(digest) is not str
            or _SHA256.fullmatch(digest) is None
        ):
            raise _TerminalCandidateRejectedV1("Answer asset metadata is invalid")
        path_bytes = path.encode("utf-8")
        if previous_path_bytes is not None and path_bytes <= previous_path_bytes:
            raise _TerminalCandidateRejectedV1("Answer assets are not ordered")
        previous_path_bytes = path_bytes
        observed.append(
            _VerifiedAssetV1(
                path=path,
                byte_length=byte_length,
                sha256=digest,
                identity_key=identity_key,
                identity_value=identity_value,
            )
        )
    return tuple(observed)


def _read_candidate_file_v1(
    candidate: ValidatedDataRootV1,
    path: str,
    *,
    cap: int,
) -> bytes:
    try:
        with candidate.open_relative_file_v1(tuple(path.split("/"))) as source:
            source.validate_streams_v1()
            payload = source.read_bytes_v1(limit=cap)
    except _TerminalCandidateRejectedV1:
        raise
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        raise _TerminalCandidateRejectedV1(
            "Answer asset could not be read safely"
        ) from error
    if len(payload) > cap:
        raise _TerminalCandidateRejectedV1("Answer asset exceeds its capacity")
    return payload


def _expected_usage_totals_v1(
    attempts: tuple[dict[str, object], ...],
) -> dict[str, int | None]:
    totals: dict[str, int | None] = {}
    for name in (
        "cached_input_tokens",
        "input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    ):
        values = [attempt[name] for attempt in attempts]
        if any(type(value) is not int for value in values):
            totals[name] = None
            continue
        total = sum(cast(int, value) for value in values)
        totals[name] = total if total <= _INT64_MAX else None
    return totals


def _candidate_has_exact_answer_basename_v1(
    candidate: ValidatedDataRootV1,
    answer_id: str,
) -> bool:
    canonical_path = candidate.inspection.canonical_path
    return canonical_path is not None and ntpath.basename(canonical_path) == answer_id


def _validate_manifest_terminal_facts_v1(
    manifest: dict[str, object],
    assets: tuple[_VerifiedAssetV1, ...],
    answer_id: str,
) -> _ManifestTerminalFactsV1:
    if set(manifest) != {
        "schema_version",
        "answer_id",
        "status",
        "error",
        "started_at",
        "finished_at",
        "elapsed_ms",
        "provenance",
        "attempts",
        "usage_totals",
        "assets",
    }:
        raise AnswerTerminalRequestInvalidV1("Answer terminal manifest is not closed")
    if (
        manifest.get("schema_version") != "gezhi.answer_manifest.v1"
        or manifest.get("answer_id") != answer_id
    ):
        raise AnswerTerminalRequestInvalidV1(
            "Answer terminal manifest identity differs"
        )
    elapsed_ms = manifest.get("elapsed_ms")
    if type(elapsed_ms) is not int or not 0 <= elapsed_ms <= _INT64_MAX:
        raise AnswerTerminalRequestInvalidV1("Answer elapsed time is invalid")
    _validate_timestamp(manifest.get("started_at"))
    _validate_timestamp(manifest.get("finished_at"))

    raw_status = manifest.get("status")
    raw_error = manifest.get("error")
    if raw_status not in {"succeeded", "blocked", "failed", "interrupted"}:
        raise AnswerTerminalRequestInvalidV1("Answer terminal status is invalid")
    status = cast(
        Literal["succeeded", "blocked", "failed", "interrupted"],
        raw_status,
    )
    error: dict[str, object] | None
    if status in {"succeeded", "interrupted"}:
        if raw_error is not None:
            raise AnswerTerminalRequestInvalidV1(
                "Answer terminal error presence is invalid"
            )
        error = None
    else:
        if type(raw_error) is not dict or set(raw_error) != {"code", "stage"}:
            raise AnswerTerminalRequestInvalidV1(
                "Answer terminal error presence is invalid"
            )
        code = raw_error.get("code")
        stage = raw_error.get("stage")
        if (
            type(code) is not str
            or type(stage) is not str
            or _ERROR_MATRIX.get(code) != (status, stage)
        ):
            raise AnswerTerminalRequestInvalidV1("Answer terminal error is invalid")
        error = dict(raw_error)

    raw_provenance = manifest.get("provenance")
    if type(raw_provenance) is not dict:
        raise AnswerTerminalRequestInvalidV1("Answer provenance is invalid")
    provenance = _validate_provenance(raw_provenance)
    raw_attempts = manifest.get("attempts")
    if type(raw_attempts) is not list or not 0 <= len(raw_attempts) <= 3:
        raise AnswerTerminalRequestInvalidV1("Answer attempts are invalid")
    attempt_items: list[dict[str, object]] = []
    for raw_record in raw_attempts:
        if type(raw_record) is not dict:
            raise AnswerTerminalRequestInvalidV1("Answer attempt record is invalid")
        attempt_items.append(_validate_attempt_record_v1(raw_record))
    attempts = tuple(attempt_items)
    if manifest.get("usage_totals") != _expected_usage_totals_v1(attempts):
        raise AnswerTerminalRequestInvalidV1("Answer usage totals differ")

    asset_paths = {asset.path for asset in assets}
    stage_paths = tuple(spec[0] for spec in _ROOT_ASSET_SPECS[:5])
    stage_presence = tuple(path in asset_paths for path in stage_paths)
    if not stage_presence[0] or any(
        stage_presence[index] and not stage_presence[index - 1]
        for index in range(1, len(stage_presence))
    ):
        raise AnswerTerminalRequestInvalidV1("Answer root asset prefix differs")
    prefix_level = sum(stage_presence) - 1
    has_prompt = "prompt.txt" in asset_paths
    has_schema = "schema.json" in asset_paths
    if has_prompt is not has_schema or has_prompt and prefix_level != 4:
        raise AnswerTerminalRequestInvalidV1("Answer synthesis pair differs")
    has_output = "answer_output.json" in asset_paths
    has_markdown = "answer.md" in asset_paths
    if has_output is not has_markdown or has_output is not (status == "succeeded"):
        raise AnswerTerminalRequestInvalidV1("Answer result pair differs")
    expected_attempt_paths = {
        f"attempts/{ordinal:02d}/{leaf}"
        for ordinal in range(1, len(attempts) + 1)
        for leaf in ("events.jsonl", "final_message.txt")
    }
    observed_attempt_paths = {
        path for path in asset_paths if path.startswith("attempts/")
    }
    if observed_attempt_paths != expected_attempt_paths or attempts and not has_prompt:
        raise AnswerTerminalRequestInvalidV1("Answer attempt asset pair differs")

    error_code = None if error is None else error.get("code")
    if has_prompt or prefix_level == 4 and error_code == "synthesis_input_invalid":
        candidate_count = 1
    elif prefix_level == 4:
        candidate_count = 0
    else:
        candidate_count = None
    _validate_root_terminal_matrix_v1(
        status=status,
        error=error,
        prefix_level=prefix_level,
        has_call_pair=has_prompt,
        candidate_count=candidate_count,
        attempt_count=len(attempts),
    )
    _validate_attempt_terminal_matrix_v1(
        status=status,
        error=error,
        candidate_count=candidate_count,
        attempts=list(attempts),
    )
    return _ManifestTerminalFactsV1(
        status=status,
        error=error,
        provenance=provenance,
        attempts=attempts,
    )


def _validate_candidate_namespace_v1(
    candidate: ValidatedDataRootV1,
    assets: tuple[_VerifiedAssetV1, ...],
) -> None:
    asset_paths = tuple(asset.path for asset in assets)
    try:
        root_profile = {
            name: name == "attempts"
            for name in {"attempts" if "/" in path else path for path in asset_paths}
        }
        root_profile["manifest.json"] = False
        candidate.validate_relative_entry_profile_v1(root_profile)
        ordinals = tuple(
            dict.fromkeys(
                path.split("/")[1]
                for path in asset_paths
                if path.startswith("attempts/")
            )
        )
        if ordinals:
            with candidate.open_relative_data_root_v1(("attempts",)) as attempts:
                attempts.validate_streams_v1()
                attempts.validate_relative_entry_profile_v1(
                    {ordinal: True for ordinal in ordinals}
                )
            for ordinal in ordinals:
                with candidate.open_relative_data_root_v1(
                    ("attempts", ordinal)
                ) as attempt:
                    attempt.validate_streams_v1()
                    attempt.validate_relative_entry_profile_v1(
                        {"events.jsonl": False, "final_message.txt": False}
                    )
    except _TerminalCandidateRejectedV1:
        raise
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        raise _TerminalCandidateRejectedV1(
            "Answer terminal namespace could not be proved"
        ) from error


def _validate_terminal_candidate_v1(
    root: ValidatedDataRootV1,
    parts: tuple[str, ...],
    answer_id: str,
) -> TerminalAnswerBytesReadyV1:
    try:
        candidate = root.open_relative_data_root_v1(parts)
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        raise _TerminalCandidateRejectedV1(
            "Answer terminal candidate is unavailable"
        ) from error
    with candidate:
        if not _candidate_has_exact_answer_basename_v1(candidate, answer_id):
            raise _TerminalCandidateRejectedV1(
                "Answer terminal basename differs from its identity"
            )
        candidate_identity = candidate.inspection.identity
        if candidate_identity is None:
            raise _TerminalCandidateRejectedV1(
                "Answer terminal identity is unavailable"
            )
        try:
            candidate.validate_streams_v1()
        except (DataRootOpenErrorV1, OSError, ValueError) as error:
            raise _TerminalCandidateRejectedV1(
                "Answer terminal root streams are invalid"
            ) from error
        manifest_bytes = _read_candidate_file_v1(
            candidate,
            "manifest.json",
            cap=ANSWER_MANIFEST_MAX_BYTES,
        )
        try:
            manifest = _decode_terminal_manifest_v1(manifest_bytes)
        except AnswerTerminalRequestInvalidV1 as error:
            raise _TerminalCandidateRejectedV1(
                "Answer terminal manifest is invalid"
            ) from error
        try:
            assets = _manifest_assets_v1(manifest.get("assets"))
            terminal_facts = _validate_manifest_terminal_facts_v1(
                manifest,
                assets,
                answer_id,
            )
        except AnswerTerminalRequestInvalidV1 as error:
            raise _TerminalCandidateRejectedV1(
                "Answer terminal manifest facts are invalid"
            ) from error
        declared_aggregate = len(manifest_bytes)
        for asset in assets:
            declared_aggregate += asset.byte_length
            if (
                declared_aggregate > _INT64_MAX
                or declared_aggregate > ANSWER_TERMINAL_MAX_BYTES
            ):
                raise _TerminalCandidateRejectedV1(
                    "Answer terminal aggregate exceeds its capacity"
                )
        _validate_candidate_namespace_v1(candidate, assets)

        asset_by_path = {asset.path: asset for asset in assets}
        payload_by_path: dict[str, bytes] = {}
        actual_aggregate = len(manifest_bytes)
        for path in _ASSET_READ_ORDER:
            current_asset = asset_by_path.get(path)
            if current_asset is None:
                continue
            _identity_key, _identity_value, cap = _asset_contract_v1(path)
            remaining = ANSWER_TERMINAL_MAX_BYTES - actual_aggregate
            payload = _read_candidate_file_v1(
                candidate,
                path,
                cap=min(cap, current_asset.byte_length, remaining),
            )
            if (
                len(payload) != current_asset.byte_length
                or hashlib.sha256(payload).hexdigest() != current_asset.sha256
            ):
                raise _TerminalCandidateRejectedV1(
                    "Answer asset bytes differ from the manifest"
                )
            actual_aggregate += len(payload)
            if actual_aggregate > ANSWER_TERMINAL_MAX_BYTES:
                raise _TerminalCandidateRejectedV1(
                    "Answer terminal aggregate exceeds its capacity"
                )
            payload_by_path[path] = payload
        if set(payload_by_path) != set(asset_by_path):
            raise _TerminalCandidateRejectedV1(
                "Answer asset dependency order is incomplete"
            )

        attempts: list[AnswerAttemptPublishV1] = []
        for ordinal, raw_record in enumerate(terminal_facts.attempts, start=1):
            prefix = f"attempts/{ordinal:02d}"
            try:
                events_bytes = payload_by_path[prefix + "/events.jsonl"]
                final_message_bytes = payload_by_path[prefix + "/final_message.txt"]
            except KeyError as error:
                raise _TerminalCandidateRejectedV1(
                    "Answer attempt evidence is incomplete"
                ) from error
            attempts.append(
                AnswerAttemptPublishV1(
                    record=raw_record,
                    events_bytes=events_bytes,
                    final_message_bytes=final_message_bytes,
                )
            )
        raw_provenance = terminal_facts.provenance
        raw_error = terminal_facts.error
        raw_status = terminal_facts.status
        effective_config_bytes = payload_by_path.get("effective_config.json")
        if type(effective_config_bytes) is not bytes:
            raise _TerminalCandidateRejectedV1(
                "Answer effective configuration is absent"
            )
        request = AnswerPublishRequestV1(
            answer_id=answer_id,
            started_at=cast(str, manifest["started_at"]),
            started_monotonic_ns=0,
            provenance=raw_provenance,
            effective_config_bytes=effective_config_bytes,
            question_bytes=payload_by_path.get("question.json"),
            retrieval_query_bytes=payload_by_path.get("retrieval_query.json"),
            retrieval_audit_bytes=payload_by_path.get("retrieval_audit.json"),
            retrieval_view_bytes=payload_by_path.get("retrieval_view.json"),
            status=raw_status,
            error=raw_error,
            prompt_bytes=payload_by_path.get("prompt.txt"),
            schema_bytes=payload_by_path.get("schema.json"),
            attempts=tuple(attempts),
            answer_output_bytes=payload_by_path.get("answer_output.json"),
            answer_markdown_bytes=payload_by_path.get("answer.md"),
        )
        try:
            provenance, request_assets, attempt_records = _validate_request(request)
        except AnswerTerminalRequestInvalidV1 as error:
            raise _TerminalCandidateRejectedV1(
                "Answer terminal cross-asset validation failed"
            ) from error
        expected_items = sorted(
            (
                {
                    "path": path,
                    "byte_length": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    identity_key: identity_value,
                }
                for path, payload, identity_key, identity_value, _cap in request_assets
            ),
            key=lambda item: cast(str, item["path"]).encode("utf-8"),
        )
        if expected_items != manifest["assets"]:
            raise _TerminalCandidateRejectedV1(
                "Answer manifest asset inventory differs"
            )
        if (
            provenance != manifest["provenance"]
            or list(attempt_records) != manifest["attempts"]
            or _expected_usage_totals_v1(attempt_records) != manifest["usage_totals"]
        ):
            raise _TerminalCandidateRejectedV1("Answer manifest terminal facts differ")
        answer_markdown_bytes = payload_by_path.get("answer.md")
        answer_markdown_text = (
            None
            if answer_markdown_bytes is None
            else answer_markdown_bytes.decode("utf-8", errors="strict")
        )

    _root_checkpoint(root)
    try:
        with root.open_relative_data_root_v1(parts) as observed_candidate:
            if (
                observed_candidate.inspection.identity != candidate_identity
                or not _candidate_has_exact_answer_basename_v1(
                    observed_candidate,
                    answer_id,
                )
            ):
                raise _TerminalCandidateRejectedV1("Answer terminal identity changed")
    except _TerminalCandidateRejectedV1:
        raise
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        raise _TerminalCandidateRejectedV1(
            "Answer terminal post-validation failed"
        ) from error
    return TerminalAnswerBytesReadyV1(
        answer_id=answer_id,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        status=cast(
            Literal["succeeded", "blocked", "failed", "interrupted"],
            raw_status,
        ),
        error=None if raw_error is None else dict(raw_error),
        answer_output_bytes=payload_by_path.get("answer_output.json"),
        answer_markdown_bytes=answer_markdown_bytes,
        answer_markdown_text=answer_markdown_text,
        retrieval_view_bytes=payload_by_path.get("retrieval_view.json"),
    )


def read_committed_answer_v1(
    root: ValidatedDataRootV1,
    answer_id: str,
) -> TerminalAnswerBytesReadyV1 | TerminalAnswerBytesRejectedV1:
    """Read one exact formal target or reject it without returning partial facts."""

    if type(answer_id) is not str:
        raise TypeError("Answer ID type is invalid")
    if _ANSWER_ID.fullmatch(answer_id) is None:
        return TerminalAnswerBytesRejectedV1(answer_id=answer_id)
    try:
        return _validate_terminal_candidate_v1(
            root,
            ("answers", answer_id),
            answer_id,
        )
    except (
        _TerminalCandidateRejectedV1,
        AnswerRootIntegrityLostV1,
    ):
        return TerminalAnswerBytesRejectedV1(answer_id=answer_id)


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
    usage_totals = _expected_usage_totals_v1(attempts)
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
        if (
            type(asset.byte_length) is not int
            or not 0 <= asset.byte_length <= _INT64_MAX
        ):
            raise AnswerManifestFailedV1("Answer terminal tree exceeds its capacity")
        aggregate += asset.byte_length
        if aggregate > _INT64_MAX or aggregate > ANSWER_TERMINAL_MAX_BYTES:
            raise AnswerManifestFailedV1("Answer terminal tree exceeds its capacity")
    return payload


def _install_and_validate_manifest(
    root: ValidatedDataRootV1,
    stage_path: Path,
    manifest_bytes: bytes,
    answer_id: str,
) -> None:
    manifest_path = stage_path / "manifest.json"
    try:
        with open_validated_data_root_v1(str(stage_path)) as stage:
            create_exclusive_file_bytes_v1(
                stage,
                "manifest.json",
                manifest_bytes,
            )
        observed = _read_safe_file(
            manifest_path,
            cap=ANSWER_MANIFEST_MAX_BYTES,
        )
    except (
        AnswerStagingFailedV1,
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        ValueError,
    ) as error:
        raise AnswerManifestFailedV1(
            "Answer manifest write or readback failed"
        ) from error
    if observed != manifest_bytes:
        raise AnswerManifestFailedV1("Answer manifest readback differs")
    try:
        validated = _validate_terminal_candidate_v1(
            root,
            ("answers", ".staging", answer_id),
            answer_id,
        )
    except _TerminalCandidateRejectedV1 as error:
        raise AnswerManifestFailedV1(
            "Answer terminal tree failed complete readback"
        ) from error
    if validated.manifest_sha256 != hashlib.sha256(manifest_bytes).hexdigest():
        raise AnswerManifestFailedV1(
            "Answer terminal manifest readback identity differs"
        )
    _root_checkpoint(root)


def _namespace_state(
    root: ValidatedDataRootV1,
    answer_id: str,
) -> tuple[bool, bool]:
    try:
        answers = root.open_relative_data_root_v1(("answers",))
        with answers:
            target_present = _case_insensitive_entry_present(answers, answer_id)
            staging = answers.open_relative_data_root_v1((".staging",))
            with staging:
                staging_present = _case_insensitive_entry_present(staging, answer_id)
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

    _consume_current_publish_v1(root, ownership)
    provenance, request_assets, attempt_records = _validate_request(request)
    _bind_current_staging_v1(root, ownership, request.answer_id)
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
            if _case_insensitive_entry_present(answers, request.answer_id):
                raise AnswerTargetConflictV1("Answer target already exists")
            if _case_insensitive_entry_present(staging, request.answer_id):
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
        _install_and_validate_manifest(
            root,
            stage_path,
            manifest_bytes,
            request.answer_id,
        )
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
            if _case_insensitive_entry_present(final_answers, request.answer_id):
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
    "TerminalAnswerBytesReadyV1",
    "TerminalAnswerBytesRejectedV1",
    "publish_answer_v1",
    "read_committed_answer_v1",
    "scan_answer_staging_v1",
]
