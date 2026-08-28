from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, BinaryIO, Literal, NoReturn, TypeAlias, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from gezhi._codex_child_process import (
    LITERATURE_EVENTS_CAPTURE_CAP_V1,
    LITERATURE_FINAL_CAPTURE_CAP_V1,
    AttemptTerminalEvidenceV1,
    NeverCancelledV1,
    PreAttemptRejectedV1,
    run_codex_child_v1,
)
from gezhi._codex_role_plan import (
    freeze_codex_attempt_workspace_v1,
    freeze_codex_role_launch_v1,
    validate_codex_source_environment_v1,
)
from gezhi._codex_runtime import (
    CodexRuntimeResolutionErrorV1,
    FrozenCodexRuntimeV1,
    resolve_codex_runtime_v1,
)
from gezhi._literature_canonical import CurrentCanonicalAssetV1
from gezhi._literature_intake import (
    ActiveSourceAuthorityStoppedV1,
    ActiveSourceAuthorityV1,
    _load_work_identity,
    load_active_source_authority_v1,
)
from gezhi._windows_data_root import (
    DataRootLifecycleErrorV1,
    DataRootOpenErrorV1,
    ValidatedDataRootV1,
    open_validated_data_root_v1,
    open_validated_local_file_v1,
    validate_relative_parts_v1,
)

_PROJECT_ROOT = Path(r"E:\Gezhi")
_INPUT_BYTE_LIMIT = 524_288
_INPUT_BLOCK_LIMIT = 4_096
_MAX_JSON_OR_TEXT_BYTES = 67_108_864
_MAX_AUDIT_INTEGER = 9_223_372_036_854_775_807
_SEMANTIC_RUN_ID = re.compile(
    r"^semrun_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_BLOCK_ID = re.compile(r"^blk_[0-9a-f]{24}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OPTIONAL_ENVIRONMENT_NAMES = (
    "ALL_PROXY",
    "CODEX_ACCESS_TOKEN",
    "CODEX_API_KEY",
    "CODEX_CA_CERTIFICATE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
)
_READER_INSTRUCTIONS = (
    b"You are literature_reader_v1. Consume only the ReaderInputV1 JSONL "
    b"included below. Return exactly one JSON object matching the supplied "
    b"JSON Schema. Write canonical statements in Simplified Chinese while "
    b"preserving source-language technical terms. Every statement and study "
    b"descriptor must cite only block_id values present in the input, and every "
    b"source_term must occur verbatim in one of its cited Evidence Blocks. Do "
    b"not infer Research Interest or emit relevance. Do not use tools, paths, "
    b"the network, prior sessions, or any source outside this input.\n\n"
    b"--- BEGIN READER INPUT JSONL ---\n"
)
_READER_INPUT_SUFFIX = b"--- END READER INPUT JSONL ---\n"

ReaderOutcome: TypeAlias = Literal["blocked", "failed"]
ReaderReason: TypeAlias = Literal[
    "reader_input_invalid",
    "reader_input_too_large",
    "codex_runtime_unavailable",
    "codex_timeout_exhausted",
    "codex_process_failed",
    "reader_output_invalid",
    "candidate_validation_failed",
    "asset_integrity_lost",
    "commit_failed",
]
ReaderAuthorityReason: TypeAlias = Literal[
    "data_root_integrity_lost",
    "active_source_unavailable",
    "active_source_invalid",
    "recovery_failed",
]


def _canonical_payload_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_file_bytes(value: object) -> bytes:
    return _canonical_payload_bytes(value) + b"\n"


def _normalize_text(value: object) -> str:
    if type(value) is not str:
        raise ValueError("Reader text must be a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("Reader text contains an unpaired surrogate") from error
    if "\x00" in value:
        raise ValueError("Reader text contains NUL")
    normalized = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    ).strip()
    if not normalized:
        raise ValueError("Reader text is empty")
    return normalized


def _normalize_reader_input_text(value: object, *, allow_empty: bool) -> str:
    if type(value) is not str:
        raise ValueError("Reader input text must be a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("Reader input text contains an unpaired surrogate") from error
    if "\x00" in value:
        raise ValueError("Reader input text contains NUL")
    normalized = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    )
    if not allow_empty and not normalized:
        raise ValueError("Reader input text is empty")
    return normalized


class _ClosedModelV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


RiskFlagV1 = Literal[
    "numeric_claim",
    "comparative_claim",
    "translation_sensitive",
    "source_ambiguity",
    "evidence_gap",
]
SupportKindV1 = Literal["direct", "synthesized", "interpretive"]


class EvidenceStatementV1(_ClosedModelV1):
    text: Annotated[str, Field(min_length=1, max_length=600)]
    source_terms: Annotated[list[str], Field(max_length=12)]
    evidence_block_ids: Annotated[list[str], Field(min_length=1, max_length=6)]
    support_kind: SupportKindV1
    risk_flags: Annotated[list[RiskFlagV1], Field(max_length=5)]

    @field_validator("text", mode="before")
    @classmethod
    def _normalize_statement(cls, value: object) -> str:
        return _normalize_text(value)

    @field_validator("source_terms", mode="after")
    @classmethod
    def _normalize_terms(cls, value: list[str]) -> list[str]:
        normalized = [_normalize_text(item) for item in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Reader source terms contain duplicates")
        if any(len(item) > 160 for item in normalized):
            raise ValueError("Reader source term is too long")
        return sorted(normalized, key=lambda item: item.encode("utf-8"))

    @field_validator("evidence_block_ids", mode="after")
    @classmethod
    def _validate_block_ids(cls, value: list[str]) -> list[str]:
        if any(_BLOCK_ID.fullmatch(item) is None for item in value):
            raise ValueError("Reader Evidence Block ID is invalid")
        if len(set(value)) != len(value):
            raise ValueError("Reader Evidence Block IDs contain duplicates")
        return sorted(value, key=lambda item: item.encode("utf-8"))

    @field_validator("risk_flags", mode="after")
    @classmethod
    def _sort_risk_flags(cls, value: list[RiskFlagV1]) -> list[RiskFlagV1]:
        if len(set(value)) != len(value):
            raise ValueError("Reader risk flags contain duplicates")
        return sorted(value)


class SynopsisStatementV1(EvidenceStatementV1):
    text: Annotated[str, Field(min_length=1, max_length=1200)]


class StudyDescriptorV1(_ClosedModelV1):
    kind: Literal["object", "dataset", "experiment", "metric"]
    label: Annotated[str, Field(min_length=1, max_length=160)]
    source_terms: Annotated[list[str], Field(max_length=12)]
    evidence_block_ids: Annotated[list[str], Field(min_length=1, max_length=6)]

    @field_validator("label", mode="before")
    @classmethod
    def _normalize_label(cls, value: object) -> str:
        return _normalize_text(value)

    @field_validator("source_terms", mode="after")
    @classmethod
    def _normalize_terms(cls, value: list[str]) -> list[str]:
        normalized = [_normalize_text(item) for item in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Descriptor source terms contain duplicates")
        if any(len(item) > 160 for item in normalized):
            raise ValueError("Descriptor source term is too long")
        return sorted(normalized, key=lambda item: item.encode("utf-8"))

    @field_validator("evidence_block_ids", mode="after")
    @classmethod
    def _validate_block_ids(cls, value: list[str]) -> list[str]:
        if any(_BLOCK_ID.fullmatch(item) is None for item in value):
            raise ValueError("Descriptor Evidence Block ID is invalid")
        if len(set(value)) != len(value):
            raise ValueError("Descriptor Evidence Block IDs contain duplicates")
        return sorted(value, key=lambda item: item.encode("utf-8"))


class StudyDescriptorsV1(_ClosedModelV1):
    objects: Annotated[list[StudyDescriptorV1], Field(max_length=8)]
    datasets: Annotated[list[StudyDescriptorV1], Field(max_length=8)]
    experiments: Annotated[list[StudyDescriptorV1], Field(max_length=8)]
    metrics: Annotated[list[StudyDescriptorV1], Field(max_length=8)]

    @model_validator(mode="after")
    def _validate_descriptor_groups(self) -> StudyDescriptorsV1:
        groups = (
            ("object", self.objects),
            ("dataset", self.datasets),
            ("experiment", self.experiments),
            ("metric", self.metrics),
        )
        if sum(len(values) for _kind, values in groups) > 24:
            raise ValueError("Reader has too many Study Descriptors")
        for expected_kind, values in groups:
            if any(item.kind != expected_kind for item in values):
                raise ValueError("Study Descriptor is in the wrong kind group")
            canonical = [_canonical_payload_bytes(item.model_dump()) for item in values]
            if len(set(canonical)) != len(canonical):
                raise ValueError("Study Descriptor group contains duplicates")
        return self


class DescriptorLocatorV1(_ClosedModelV1):
    kind: Literal["method", "object", "dataset", "experiment", "metric"]
    index: Annotated[int, Field(ge=0)]


class CandidateDraftV1(_ClosedModelV1):
    candidate_type: Literal["method", "claim", "limitation", "open_question"]
    statement: EvidenceStatementV1
    descriptor_refs: Annotated[list[DescriptorLocatorV1], Field(max_length=6)]

    @model_validator(mode="after")
    def _validate_candidate(self) -> CandidateDraftV1:
        if (
            self.candidate_type in {"method", "claim", "limitation"}
            and self.statement.support_kind == "interpretive"
        ):
            raise ValueError("Candidate support kind is not allowed")
        canonical = [
            _canonical_payload_bytes(item.model_dump()) for item in self.descriptor_refs
        ]
        if len(set(canonical)) != len(canonical):
            raise ValueError("Candidate Descriptor Locators contain duplicates")
        return self


class ReadingResultV1(_ClosedModelV1):
    synopsis: SynopsisStatementV1
    research_problems: Annotated[list[EvidenceStatementV1], Field(max_length=3)]
    methods: Annotated[list[EvidenceStatementV1], Field(max_length=6)]
    findings: Annotated[list[EvidenceStatementV1], Field(max_length=8)]
    limitations: Annotated[list[EvidenceStatementV1], Field(max_length=6)]
    relevance: Annotated[list[EvidenceStatementV1], Field(max_length=0)]
    open_questions: Annotated[list[EvidenceStatementV1], Field(max_length=5)]
    study_descriptors: StudyDescriptorsV1

    @model_validator(mode="after")
    def _validate_statement_groups(self) -> ReadingResultV1:
        for values in (
            self.research_problems,
            self.methods,
            self.findings,
            self.limitations,
            self.relevance,
            self.open_questions,
        ):
            canonical = [_canonical_payload_bytes(item.model_dump()) for item in values]
            if len(set(canonical)) != len(canonical):
                raise ValueError("Reading Result group contains duplicates")
        return self


class LiteratureReaderOutputV1(_ClosedModelV1):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        json_schema_extra={
            "$id": (
                "https://gezhi.local/schemas/literature-reader-output-v1.schema.json"
            )
        },
    )

    schema_version: Literal["gezhi.literature_reader_output.v1"]
    reading_result: ReadingResultV1
    candidate_drafts: Annotated[list[CandidateDraftV1], Field(max_length=12)]


def reader_output_schema_bytes_v1() -> bytes:
    return _canonical_file_bytes(
        LiteratureReaderOutputV1.model_json_schema(mode="validation")
    )


@dataclass(frozen=True, slots=True)
class ReaderAttemptRequestV1:
    runtime: FrozenCodexRuntimeV1
    attempt_root: Path
    attempt_ordinal: int
    prompt: bytes
    schema_path: Path
    codex_home: Path
    literature_root: Path
    knowledge_root: Path
    source_environment: Mapping[str, str]
    existing_shared_deadline_monotonic_ns: int | None


@dataclass(frozen=True, slots=True)
class ReaderAdvanceV1:
    advanced: bool
    run_id: str
    manifest_sha256: str
    pending_candidate_ids: tuple[str, ...]


class ReaderStageStoppedV1(RuntimeError):
    def __init__(self, outcome: ReaderOutcome, reason: ReaderReason) -> None:
        super().__init__(f"Reader stage {outcome}: {reason}")
        self.outcome = outcome
        self.reason = reason


class ReaderRecoveryUncertainV1(RuntimeError):
    """A semantic publication result cannot be represented as handled."""


class ReaderAuthorityStoppedV1(RuntimeError):
    def __init__(self, reason: ReaderAuthorityReason) -> None:
        super().__init__(f"Reader authority stopped: {reason}")
        self.reason = reason


def _source_environment(source: Mapping[str, str]) -> dict[str, str]:
    indexed = validate_codex_source_environment_v1(source)
    result = {"SystemRoot": indexed.get("systemroot") or ""}
    if not result["SystemRoot"]:
        raise ReaderStageStoppedV1("blocked", "codex_runtime_unavailable")
    for name in ("CODEX_HOME", "TEMP", *_OPTIONAL_ENVIRONMENT_NAMES):
        value = indexed.get(name.casefold())
        if value:
            result[name] = value
    return result


def _run_role_attempt_v1(
    request: ReaderAttemptRequestV1,
) -> PreAttemptRejectedV1 | AttemptTerminalEvidenceV1:
    try:
        workspace = freeze_codex_attempt_workspace_v1(
            attempt_root=request.attempt_root,
            attempt_ordinal=request.attempt_ordinal,
            literature_authoritative_root=request.literature_root,
            knowledge_authoritative_root=request.knowledge_root,
        )
        plan = freeze_codex_role_launch_v1(
            runtime=request.runtime,
            role="literature_reader_v1",
            prompt=request.prompt,
            attempt_ordinal=request.attempt_ordinal,
            workspace=workspace,
            schema_path=request.schema_path,
            codex_home=request.codex_home,
            source_environment=request.source_environment,
            existing_shared_deadline_monotonic_ns=(
                request.existing_shared_deadline_monotonic_ns
            ),
        )
    except (CodexRuntimeResolutionErrorV1, OSError, ValueError) as error:
        raise ReaderStageStoppedV1("blocked", "codex_runtime_unavailable") from error
    return run_codex_child_v1(plan, NeverCancelledV1())


def _prepare_role_invocation_v1() -> FrozenCodexRuntimeV1:
    try:
        return resolve_codex_runtime_v1(_PROJECT_ROOT)
    except (CodexRuntimeResolutionErrorV1, OSError, ValueError) as error:
        raise ReaderStageStoppedV1(
            "blocked", "codex_runtime_unavailable"
        ) from error


def _reader_metadata(
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
) -> dict[str, object]:
    try:
        aliases, _identity_sha256 = _load_work_identity(
            authority.work_directory, authority.work_id
        )
    except (OSError, ValueError) as error:
        raise ReaderStageStoppedV1("failed", "reader_input_invalid") from error
    dois = sorted(aliases["doi"], key=lambda item: item.encode("utf-8"))
    arxiv_ids = sorted(aliases["arxiv_id"], key=lambda item: item.encode("utf-8"))
    return {
        "arxiv_id": arxiv_ids[0] if arxiv_ids else None,
        "authors": [],
        "canonical_content_sha256": canonical.canonical_content_sha256,
        "canonical_run_id": canonical.run_id,
        "doi": dois[0] if dois else None,
        "record_type": "metadata",
        "schema_version": "gezhi.reader_input.v1",
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "title": None,
        "work_id": authority.work_id,
        "year": None,
    }


def _reader_input(
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
) -> tuple[bytes, dict[str, str]]:
    records = [_reader_metadata(authority, canonical)]
    evidence: dict[str, str] = {}
    try:
        raw_lines = _read_safe_bytes(
            canonical.run_directory / "blocks.jsonl",
            limit=_MAX_JSON_OR_TEXT_BYTES,
        ).splitlines()
        for order, raw in enumerate(raw_lines):
            value = json.loads(raw)
            if type(value) is not dict:
                raise ValueError("Canonical block is not an object")
            block_id = value.get("block_id")
            if (
                type(block_id) is not str
                or _BLOCK_ID.fullmatch(block_id) is None
                or block_id in evidence
                or type(value.get("order")) is not int
                or value["order"] != order
                or value.get("kind")
                not in {
                    "heading",
                    "paragraph",
                    "list_item",
                    "table",
                    "figure_caption",
                    "figure_text",
                    "equation",
                    "other_text",
                }
                or type(value.get("heading_path")) is not list
                or any(type(item) is not str for item in value["heading_path"])
                or (
                    value.get("page_index") is not None
                    and (
                        type(value["page_index"]) is not int
                        or value["page_index"] < 0
                    )
                )
                or type(value.get("text")) is not str
            ):
                raise ValueError("Canonical block cannot form Reader input")
            text = _normalize_reader_input_text(value["text"], allow_empty=False)
            heading_path = [
                _normalize_reader_input_text(item, allow_empty=True)
                for item in value["heading_path"]
            ]
            evidence[block_id] = text
            records.append(
                {
                    "block_id": block_id,
                    "heading_path": heading_path,
                    "kind": value["kind"],
                    "order": order,
                    "page_index": value["page_index"],
                    "record_type": "block",
                    "text": text,
                }
            )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise ReaderStageStoppedV1("failed", "reader_input_invalid") from error
    if not evidence:
        raise ReaderStageStoppedV1("failed", "reader_input_invalid")
    payload = b"".join(_canonical_file_bytes(record) for record in records)
    if len(evidence) > _INPUT_BLOCK_LIMIT or len(payload) > _INPUT_BYTE_LIMIT:
        raise ReaderStageStoppedV1("blocked", "reader_input_too_large")
    return payload, evidence


def _effective_prompt(input_bytes: bytes) -> bytes:
    return _READER_INSTRUCTIONS + input_bytes + _READER_INPUT_SUFFIX


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Reader output contains a duplicate key")
        result[key] = value
    return result


def _reject_float(_value: str) -> NoReturn:
    raise ValueError("Reader output contains a float")


def _parse_reader_output(payload: bytes) -> LiteratureReaderOutputV1:
    try:
        text = payload.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
        if type(value) is not dict:
            raise ValueError("Reader output root is not an object")
        return LiteratureReaderOutputV1.model_validate(value, strict=True)
    except (UnicodeDecodeError, ValueError, RecursionError, ValidationError) as error:
        raise ReaderStageStoppedV1("failed", "reader_output_invalid") from error


def _all_statements(
    output: LiteratureReaderOutputV1,
) -> tuple[EvidenceStatementV1, ...]:
    reading = output.reading_result
    return (
        reading.synopsis,
        *reading.research_problems,
        *reading.methods,
        *reading.findings,
        *reading.limitations,
        *reading.relevance,
        *reading.open_questions,
        *(candidate.statement for candidate in output.candidate_drafts),
    )


def _validate_evidence(
    output: LiteratureReaderOutputV1,
    evidence: Mapping[str, str],
) -> None:
    statements = list(_all_statements(output))
    descriptors = output.reading_result.study_descriptors
    descriptor_values = (
        *descriptors.objects,
        *descriptors.datasets,
        *descriptors.experiments,
        *descriptors.metrics,
    )
    for item in statements:
        if any(block_id not in evidence for block_id in item.evidence_block_ids):
            raise ReaderStageStoppedV1("failed", "reader_output_invalid")
        cited_blocks = [evidence[item_id] for item_id in item.evidence_block_ids]
        if any(
            not any(term in block_text for block_text in cited_blocks)
            for term in item.source_terms
        ):
            raise ReaderStageStoppedV1("failed", "reader_output_invalid")
    for descriptor in descriptor_values:
        if any(
            block_id not in evidence
            for block_id in descriptor.evidence_block_ids
        ):
            raise ReaderStageStoppedV1("failed", "reader_output_invalid")
        cited_blocks = [
            evidence[item_id] for item_id in descriptor.evidence_block_ids
        ]
        if any(
            not any(term in block_text for block_text in cited_blocks)
            for term in descriptor.source_terms
        ):
            raise ReaderStageStoppedV1("failed", "reader_output_invalid")
    groups: dict[str, list[object]] = {
        "method": list(output.reading_result.methods),
        "object": list(descriptors.objects),
        "dataset": list(descriptors.datasets),
        "experiment": list(descriptors.experiments),
        "metric": list(descriptors.metrics),
    }
    for candidate in output.candidate_drafts:
        for locator in candidate.descriptor_refs:
            values = groups[locator.kind]
            if locator.index >= len(values):
                raise ReaderStageStoppedV1("failed", "reader_output_invalid")


def _write_all(destination: BinaryIO, payload: bytes) -> None:
    offset = 0
    view = memoryview(payload)
    while offset < len(payload):
        count = destination.write(view[offset:])
        remaining = len(payload) - offset
        if type(count) is not int or not 1 <= count <= remaining:
            raise OSError("Reader asset write did not complete deterministically")
        offset += count


def _read_safe_bytes(path: Path, *, limit: int) -> bytes:
    try:
        with open_validated_local_file_v1(str(path)) as source:
            return source.read_bytes_v1(limit=limit)
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        ValueError,
    ) as error:
        raise ValueError("Reader asset is unreadable") from error


def _write_new_verified(path: Path, payload: bytes) -> None:
    try:
        with (
            open_validated_data_root_v1(str(path.parent)),
            path.open("xb", buffering=0) as target,
        ):
            _write_all(target, payload)
        if _read_safe_bytes(path, limit=len(payload)) != payload:
            raise OSError("semantic write readback differs")
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        ValueError,
    ) as error:
        raise ReaderStageStoppedV1("failed", "commit_failed") from error


def _ensure_directory(path: Path) -> None:
    try:
        with open_validated_data_root_v1(str(path.parent)):
            try:
                path.mkdir()
            except FileExistsError:
                pass
        with open_validated_data_root_v1(str(path)):
            pass
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
    ) as error:
        raise ReaderStageStoppedV1("failed", "commit_failed") from error


def _entry_names(path: Path) -> tuple[str, ...]:
    try:
        with open_validated_data_root_v1(str(path)) as opened:
            return opened.relative_entry_names_v1()
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
    ) as error:
        raise ValueError("Reader namespace is unreadable") from error


def _name_exists(path: Path, name: str) -> bool:
    return name in _entry_names(path)


def _same_authority(
    first: ActiveSourceAuthorityV1,
    second: ActiveSourceAuthorityV1,
) -> bool:
    return (
        first.work_id,
        first.source_id,
        first.source_sha256,
        first.source_byte_length,
        first.source_manifest_sha256,
    ) == (
        second.work_id,
        second.source_id,
        second.source_sha256,
        second.source_byte_length,
        second.source_manifest_sha256,
    )


def _checkpoint(
    authority: ActiveSourceAuthorityV1,
    root: ValidatedDataRootV1,
) -> None:
    try:
        fresh = load_active_source_authority_v1(authority.work_id, root=root)
    except ActiveSourceAuthorityStoppedV1 as error:
        if error.reason in {
            "data_root_integrity_lost",
            "active_source_unavailable",
            "active_source_invalid",
            "recovery_failed",
        }:
            reason = cast(ReaderAuthorityReason, error.reason)
        else:
            reason = "recovery_failed"
        raise ReaderAuthorityStoppedV1(reason) from error
    if not _same_authority(authority, fresh):
        raise ReaderAuthorityStoppedV1("recovery_failed")


def _media_type(relative_path: str) -> str:
    if relative_path.endswith(".json"):
        return "application/json"
    if relative_path.endswith(".jsonl"):
        return "application/x-ndjson"
    return "text/plain; charset=utf-8"


def _schema_version(relative_path: str) -> str | None:
    return {
        "input.jsonl": "gezhi.reader_input.v1",
        "result/reading_result.json": "gezhi.reading_result.v1",
        "result/candidate_drafts.json": "gezhi.candidate_drafts.v1",
        "result/candidate_knowledge.jsonl": "gezhi.candidate_knowledge.v1",
        "result/review_queue.json": "gezhi.review_queue.v1",
    }.get(relative_path)


def _asset_entries(run_dir: Path) -> list[dict[str, object]]:
    try:
        with open_validated_data_root_v1(str(run_dir)) as run:
            paths = tuple(
                sorted(
                    (
                        path
                        for path in run.relative_file_paths_v1()
                        if path != "manifest.json"
                    ),
                    key=lambda value: value.encode("utf-8"),
                )
            )
            entries: list[dict[str, object]] = []
            for relative in paths:
                parts = validate_relative_parts_v1(tuple(relative.split("/")))
                with run.open_relative_file_v1(parts) as asset:
                    entry: dict[str, object] = {
                        "byte_length": asset.size,
                        "media_type": _media_type(relative),
                        "path": relative,
                        "sha256": asset.sha256_v1(),
                    }
                schema = _schema_version(relative)
                if schema is not None:
                    entry["schema_version"] = schema
                entries.append(entry)
            return entries
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        ValueError,
    ) as error:
        raise ReaderStageStoppedV1("failed", "commit_failed") from error


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _wait_before_retry_v1(seconds: float) -> None:
    time.sleep(seconds)


def _git_revision() -> str:
    git_dir = _PROJECT_ROOT / ".git"
    head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
    if re.fullmatch(r"[0-9a-f]{40}", head):
        return head
    prefix = "ref: "
    if not head.startswith(prefix):
        raise ReaderStageStoppedV1("failed", "commit_failed")
    reference = head[len(prefix) :]
    reference_path = git_dir.joinpath(*reference.split("/"))
    if reference_path.is_file():
        revision = reference_path.read_text(encoding="ascii").strip()
        if re.fullmatch(r"[0-9a-f]{40}", revision):
            return revision
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="ascii").splitlines():
            if line.endswith(" " + reference):
                revision = line.split(" ", 1)[0]
                if re.fullmatch(r"[0-9a-f]{40}", revision):
                    return revision
    raise ReaderStageStoppedV1("failed", "commit_failed")


def _create_attempt_root(temporary_root: Path) -> Path:
    if not temporary_root.is_dir():
        raise ReaderStageStoppedV1("blocked", "codex_runtime_unavailable")
    for _attempt in range(64):
        root = temporary_root / ("g" + uuid.uuid4().hex[:7])
        try:
            root.mkdir()
        except FileExistsError:
            continue
        try:
            for name in ("captures", "sqlite", "temporary", "working"):
                (root / name).mkdir()
        except OSError:
            shutil.rmtree(root, ignore_errors=True)
            raise ReaderStageStoppedV1("blocked", "codex_runtime_unavailable") from None
        return root
    raise ReaderStageStoppedV1("blocked", "codex_runtime_unavailable")


def _copy_attempt(
    evidence: AttemptTerminalEvidenceV1,
    destination: Path,
) -> None:
    try:
        events = _read_safe_bytes(
            evidence.events.path,
            limit=evidence.events.byte_length,
        )
        if (
            len(events) != evidence.events.byte_length
            or hashlib.sha256(events).hexdigest() != evidence.events.sha256
        ):
            raise OSError("events capture copy differs")
        final: bytes | None = None
        if evidence.final_message is not None:
            final = _read_safe_bytes(
                evidence.final_message.path,
                limit=evidence.final_message.byte_length,
            )
            if (
                len(final) != evidence.final_message.byte_length
                or hashlib.sha256(final).hexdigest() != evidence.final_message.sha256
            ):
                raise OSError("final capture copy differs")
        _ensure_directory(destination)
        _write_new_verified(destination / "events.jsonl", events)
        if final is not None:
            _write_new_verified(destination / "final_message.txt", final)
    except (OSError, ValueError) as error:
        raise ReaderStageStoppedV1("failed", "commit_failed") from error


def _usage(
    events: bytes,
) -> tuple[tuple[int | None, int | None, int | None, int | None], bool]:
    usage: dict[str, object] | None = None
    try:
        if events and (not events.endswith(b"\n") or b"\r" in events):
            raise ValueError("Codex events framing is invalid")
        completed_count = 0
        for raw in events.splitlines():
            value = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_float,
            )
            if type(value) is not dict:
                raise ValueError("Codex event is not an object")
            if value.get("type") == "turn.completed":
                completed_count += 1
                if completed_count > 1:
                    raise ValueError("Codex events contain duplicate completion")
                if type(value.get("usage")) is dict:
                    usage = value["usage"]
    except (UnicodeError, ValueError, json.JSONDecodeError):
        return (None, None, None, None), False
    values: list[int | None] = []
    for name in (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    ):
        value = None if usage is None else usage.get(name)
        values.append(
            value
            if type(value) is int and 0 <= value <= _MAX_AUDIT_INTEGER
            else None
        )
    return (values[0], values[1], values[2], values[3]), True


def _attempt_document(
    evidence: AttemptTerminalEvidenceV1,
    *,
    failure_class: Literal["timeout", "process_error"] | None,
) -> tuple[dict[str, object], bool]:
    events = _read_safe_bytes(
        evidence.events.path,
        limit=evidence.events.byte_length,
    )
    usage, events_valid = _usage(events)
    input_tokens, cached_tokens, output_tokens, reasoning_tokens = usage
    effective_failure_class = (
        "process_error"
        if not events_valid and failure_class is None
        else failure_class
    )
    elapsed_ns = (
        None
        if evidence.capture_ready_monotonic_ns is None
        else max(0, evidence.capture_ready_monotonic_ns - evidence.commit_monotonic_ns)
    )
    return {
        "attempt_ordinal": evidence.attempt_ordinal,
        "cached_input_tokens": cached_tokens,
        "elapsed_ms": None if elapsed_ns is None else elapsed_ns // 1_000_000,
        "exit_code": evidence.exit_code,
        "failure_class": effective_failure_class,
        "finished_at": _utc_now(),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_tokens,
        "resource_ledger_count": evidence.resource_ledger_count,
        "schema_version": "gezhi.literature_codex_attempt.v1",
        "started_at": evidence.commit_wall_time,
        "usage_unavailable": any(
            value is None
            for value in (
                input_tokens,
                cached_tokens,
                output_tokens,
                reasoning_tokens,
            )
        ),
    }, events_valid


def _usage_totals(
    attempts: list[dict[str, object]],
) -> dict[str, int | None]:
    totals: dict[str, int | None] = {}
    for name in (
        "cached_input_tokens",
        "input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    ):
        values = [attempt.get(name) for attempt in attempts]
        if any(type(value) is not int for value in values):
            totals[name] = None
            continue
        total = sum(value for value in values if type(value) is int)
        totals[name] = total if total <= _MAX_AUDIT_INTEGER else None
    return totals


def _manifest_document_v1(
    *,
    assets: list[dict[str, object]],
    attempts: list[dict[str, object]],
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    candidate_draft_count: int,
    evidence_count: int,
    input_bytes: bytes,
    prompt_bytes: bytes,
    reason: ReaderReason | Literal["interrupted"] | None,
    run_id: str,
    schema_bytes: bytes,
    status: Literal["succeeded", "blocked", "failed", "interrupted"],
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "assets": assets,
        "attempt_count": len(attempts),
        "attempts": list(attempts),
        "candidate_count": 0,
        "candidate_draft_count": candidate_draft_count,
        "canonical_content_sha256": canonical.canonical_content_sha256,
        "canonical_manifest_sha256": canonical.manifest_sha256,
        "canonical_run_id": canonical.run_id,
        "codex_cli_version": "0.146.0",
        "finished_at": _utc_now(),
        "git_revision": _git_revision(),
        "input_block_count": evidence_count,
        "input_block_limit": _INPUT_BLOCK_LIMIT,
        "input_byte_length": len(input_bytes),
        "input_byte_limit": _INPUT_BYTE_LIMIT,
        "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "model": "gpt-5.6-sol",
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "reasoning_effort": "high",
        "role": "literature_reader_v1",
        "run_id": run_id,
        "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
        "schema_version": "gezhi.literature_semantic_run_manifest.v1",
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "status": status,
        "usage_totals": _usage_totals(attempts),
        "work_id": authority.work_id,
    }
    if status == "succeeded":
        if reason is not None:
            raise ValueError("a succeeded Reader manifest cannot have a reason")
    else:
        if reason is None:
            raise ValueError("a terminal Reader manifest requires a reason")
        manifest["reason"] = reason
    return manifest


def _read_canonical_object_v1(path: Path) -> tuple[dict[str, object], bytes]:
    payload = _read_safe_bytes(path, limit=_MAX_JSON_OR_TEXT_BYTES)
    value = json.loads(
        payload,
        object_pairs_hook=_reject_duplicate_pairs,
        parse_float=_reject_float,
        parse_constant=_reject_float,
    )
    if type(value) is not dict or payload != _canonical_file_bytes(value):
        raise ValueError("Reader JSON asset is not canonical")
    return value, payload


def _attempt_documents_from_run_v1(
    run_dir: Path,
) -> list[dict[str, object]]:
    attempts_dir = run_dir / "attempts"
    entries = _entry_names(attempts_dir)
    if len(entries) > 3:
        raise ValueError("Reader attempt count is invalid")
    documents: list[dict[str, object]] = []
    for expected_ordinal, attempt_name in enumerate(entries, start=1):
        expected_name = f"{expected_ordinal:02d}"
        if attempt_name != expected_name:
            raise ValueError("Reader attempt namespace is invalid")
        attempt_dir = attempts_dir / attempt_name
        children = frozenset(_entry_names(attempt_dir))
        if not children <= {
            "attempt.json",
            "events.jsonl",
            "final_message.txt",
        }:
            raise ValueError("Reader attempt inventory is invalid")
        attempt_path = attempt_dir / "attempt.json"
        if "attempt.json" not in children:
            raise ValueError("Reader attempt document is missing")
        if "events.jsonl" not in children:
            raise ValueError("Reader attempt events are missing")
        events = _read_safe_bytes(
            attempt_dir / "events.jsonl",
            limit=LITERATURE_EVENTS_CAPTURE_CAP_V1,
        )
        if "final_message.txt" in children:
            _read_safe_bytes(
                attempt_dir / "final_message.txt",
                limit=LITERATURE_FINAL_CAPTURE_CAP_V1,
            )
        document, _payload = _read_canonical_object_v1(attempt_path)
        expected_keys = {
            "attempt_ordinal",
            "cached_input_tokens",
            "elapsed_ms",
            "exit_code",
            "failure_class",
            "finished_at",
            "input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "resource_ledger_count",
            "schema_version",
            "started_at",
            "usage_unavailable",
        }
        token_names = (
            "cached_input_tokens",
            "input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        )
        elapsed_ms = document.get("elapsed_ms")
        exit_code = document.get("exit_code")
        usage, events_valid = _usage(events)
        expected_usage = {
            "input_tokens": usage[0],
            "cached_input_tokens": usage[1],
            "output_tokens": usage[2],
            "reasoning_output_tokens": usage[3],
        }
        failure_class = document.get("failure_class")
        if (
            set(document) != expected_keys
            or document.get("attempt_ordinal") != expected_ordinal
            or document.get("schema_version")
            != "gezhi.literature_codex_attempt.v1"
            or document.get("failure_class")
            not in {None, "timeout", "process_error"}
            or type(document.get("resource_ledger_count")) is not int
            or document["resource_ledger_count"] != 0
            or type(document.get("usage_unavailable")) is not bool
            or type(document.get("started_at")) is not str
            or not document["started_at"]
            or type(document.get("finished_at")) is not str
            or not document["finished_at"]
            or (
                elapsed_ms is not None
                and (
                    type(elapsed_ms) is not int
                    or elapsed_ms < 0
                )
            )
            or (
                exit_code is not None
                and type(exit_code) is not int
            )
            or any(
                (value := document.get(name)) is not None
                and (
                    type(value) is not int or value < 0
                )
                for name in token_names
            )
            or any(
                document.get(name) != expected_usage[name]
                for name in token_names
            )
            or document["usage_unavailable"]
            is not any(value is None for value in usage)
            or (
                failure_class is None
                and (
                    exit_code != 0
                    or "final_message.txt" not in children
                    or not events_valid
                )
            )
        ):
            raise ValueError("Reader attempt document is invalid")
        documents.append(document)
    if any(
        document.get("failure_class") != "timeout"
        for document in documents[:-1]
    ):
        raise ValueError("Reader retry sequence is invalid")
    return documents


def _recover_staging_v1(
    staging_dir: Path,
    runs_dir: Path,
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    *,
    root: ValidatedDataRootV1,
) -> None:
    try:
        staged = _entry_names(staging_dir)
    except ValueError as error:
        raise ReaderRecoveryUncertainV1(
            "semantic staging inventory cannot be proven"
        ) from error
    if not staged:
        return
    if len(staged) != 1:
        raise ReaderRecoveryUncertainV1("semantic staging is ambiguous")
    run_id = staged[0]
    stage = staging_dir / run_id
    target = runs_dir / run_id
    try:
        target_exists = _name_exists(runs_dir, run_id)
        stage_entries = frozenset(_entry_names(stage))
    except ValueError as error:
        raise ReaderRecoveryUncertainV1(
            "semantic staging namespace cannot be proven"
        ) from error
    if _SEMANTIC_RUN_ID.fullmatch(run_id) is None or target_exists:
        raise ReaderRecoveryUncertainV1("semantic staging namespace is invalid")
    try:
        if not {"attempts", "input.jsonl", "prompt.txt", "schema.json"}.issubset(
            stage_entries
        ) or not stage_entries <= {
            "attempts",
            "input.jsonl",
            "manifest.json",
            "prompt.txt",
            "result",
            "schema.json",
        }:
            raise ValueError("semantic staging inventory is invalid")
        _entry_names(stage / "attempts")
        input_bytes = _read_safe_bytes(
            stage / "input.jsonl",
            limit=_INPUT_BYTE_LIMIT,
        )
        expected_input, evidence = _reader_input(authority, canonical)
        schema_bytes = _read_safe_bytes(
            stage / "schema.json",
            limit=_MAX_JSON_OR_TEXT_BYTES,
        )
        expected_schema = reader_output_schema_bytes_v1()
        prompt_bytes = _read_safe_bytes(
            stage / "prompt.txt",
            limit=_MAX_JSON_OR_TEXT_BYTES,
        )
        if (
            input_bytes != expected_input
            or schema_bytes != expected_schema
            or prompt_bytes != _effective_prompt(expected_input)
        ):
            raise ValueError("semantic staging input identity differs")
        attempt_documents = _attempt_documents_from_run_v1(stage)
        if "result" in stage_entries or "manifest.json" in stage_entries:
            raise ValueError("terminal semantic staging requires exact recovery")
    except (OSError, ReaderStageStoppedV1, ValueError) as error:
        raise ReaderRecoveryUncertainV1(
            "semantic interrupted staging cannot be proven"
        ) from error
    assets = _asset_entries(stage)
    manifest = _manifest_document_v1(
        assets=assets,
        attempts=attempt_documents,
        authority=authority,
        canonical=canonical,
        candidate_draft_count=0,
        evidence_count=len(evidence),
        input_bytes=input_bytes,
        prompt_bytes=prompt_bytes,
        reason="interrupted",
        run_id=run_id,
        schema_bytes=schema_bytes,
        status="interrupted",
    )
    _write_new_verified(stage / "manifest.json", _canonical_file_bytes(manifest))
    if json.loads(
        _read_safe_bytes(
            stage / "manifest.json",
            limit=_MAX_JSON_OR_TEXT_BYTES,
        )
    )["assets"] != _asset_entries(stage):
        raise ReaderRecoveryUncertainV1(
            "semantic interrupted manifest readback differs"
        )
    _checkpoint(authority, root)
    try:
        if _name_exists(runs_dir, run_id):
            raise ReaderRecoveryUncertainV1(
                "semantic interrupted run target conflicts"
            )
    except ValueError as error:
        raise ReaderRecoveryUncertainV1(
            "semantic interrupted run target cannot be proven"
        ) from error
    try:
        with (
            open_validated_data_root_v1(str(staging_dir)),
            open_validated_data_root_v1(str(runs_dir)),
        ):
            os.rename(stage, target)
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
    ) as error:
        raise ReaderRecoveryUncertainV1(
            "semantic interrupted run rename result is uncertain"
        ) from error


def _validated_success_manifest_sha256(
    run_dir: Path,
    run_id: str,
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    *,
    expected_sha256: str | None,
) -> str | None:
    try:
        manifest, manifest_bytes = _read_canonical_object_v1(
            run_dir / "manifest.json"
        )
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        identity_matches = (
            manifest.get("canonical_content_sha256")
            == canonical.canonical_content_sha256
            and manifest.get("canonical_manifest_sha256")
            == canonical.manifest_sha256
            and manifest.get("canonical_run_id") == canonical.run_id
            and manifest.get("source_id") == authority.source_id
            and manifest.get("source_sha256") == authority.source_sha256
            and manifest.get("work_id") == authority.work_id
        )
        if expected_sha256 is None and (
            manifest.get("status") != "succeeded" or not identity_matches
        ):
            return None
        if (
            expected_sha256 is not None
            and manifest_sha256 != expected_sha256
        ):
            raise ValueError("semantic manifest identity is invalid")
        expected_manifest_keys = {
            "assets",
            "attempt_count",
            "attempts",
            "candidate_count",
            "candidate_draft_count",
            "canonical_content_sha256",
            "canonical_manifest_sha256",
            "canonical_run_id",
            "codex_cli_version",
            "finished_at",
            "git_revision",
            "input_block_count",
            "input_block_limit",
            "input_byte_length",
            "input_byte_limit",
            "input_sha256",
            "model",
            "prompt_sha256",
            "reasoning_effort",
            "role",
            "run_id",
            "schema_sha256",
            "schema_version",
            "source_id",
            "source_sha256",
            "status",
            "usage_totals",
            "work_id",
        }
        input_bytes, evidence = _reader_input(authority, canonical)
        schema_bytes = reader_output_schema_bytes_v1()
        prompt_bytes = _effective_prompt(input_bytes)
        candidate_draft_count = manifest.get("candidate_draft_count")
        git_revision = manifest.get("git_revision")
        if (
            set(manifest) != expected_manifest_keys
            or manifest.get("schema_version")
            != "gezhi.literature_semantic_run_manifest.v1"
            or manifest.get("run_id") != run_id
            or manifest.get("status") != "succeeded"
            or not identity_matches
            or manifest.get("candidate_count") != 0
            or type(candidate_draft_count) is not int
            or not 0 <= candidate_draft_count <= 12
            or manifest.get("codex_cli_version") != "0.146.0"
            or manifest.get("model") != "gpt-5.6-sol"
            or manifest.get("reasoning_effort") != "high"
            or manifest.get("role") != "literature_reader_v1"
            or type(manifest.get("finished_at")) is not str
            or not manifest["finished_at"]
            or type(git_revision) is not str
            or re.fullmatch(r"[0-9a-f]{40}", git_revision) is None
            or manifest.get("input_block_count") != len(evidence)
            or manifest.get("input_block_limit") != _INPUT_BLOCK_LIMIT
            or manifest.get("input_byte_length") != len(input_bytes)
            or manifest.get("input_byte_limit") != _INPUT_BYTE_LIMIT
            or manifest.get("input_sha256")
            != hashlib.sha256(input_bytes).hexdigest()
            or manifest.get("prompt_sha256")
            != hashlib.sha256(prompt_bytes).hexdigest()
            or manifest.get("schema_sha256")
            != hashlib.sha256(schema_bytes).hexdigest()
            or _read_safe_bytes(
                run_dir / "input.jsonl",
                limit=_INPUT_BYTE_LIMIT,
            )
            != input_bytes
            or _read_safe_bytes(
                run_dir / "prompt.txt",
                limit=_MAX_JSON_OR_TEXT_BYTES,
            )
            != prompt_bytes
            or _read_safe_bytes(
                run_dir / "schema.json",
                limit=_MAX_JSON_OR_TEXT_BYTES,
            )
            != schema_bytes
        ):
            raise ValueError("semantic run is invalid")
        attempt_count = manifest.get("attempt_count")
        if type(attempt_count) is not int or not 1 <= attempt_count <= 3:
            raise ValueError("semantic attempt count is invalid")
        attempts = _attempt_documents_from_run_v1(run_dir)
        if (
            len(attempts) != attempt_count
            or manifest.get("attempts") != attempts
            or manifest.get("usage_totals") != _usage_totals(attempts)
            or any(
                attempt.get("failure_class") != "timeout"
                for attempt in attempts[:-1]
            )
            or attempts[-1].get("failure_class") is not None
            or attempts[-1].get("exit_code") != 0
        ):
            raise ValueError("semantic attempt provenance is invalid")
        final_path = run_dir / "attempts" / f"{attempt_count:02d}" / "final_message.txt"
        output = _parse_reader_output(
            _read_safe_bytes(final_path, limit=_MAX_JSON_OR_TEXT_BYTES)
        )
        _validate_evidence(output, evidence)
        reading_document, _reading_bytes = _read_canonical_object_v1(
            run_dir / "result" / "reading_result.json"
        )
        draft_document, _draft_bytes = _read_canonical_object_v1(
            run_dir / "result" / "candidate_drafts.json"
        )
        review_queue, _queue_bytes = _read_canonical_object_v1(
            run_dir / "result" / "review_queue.json"
        )
        common_identity = {
            "canonical_content_sha256": canonical.canonical_content_sha256,
            "source_id": authority.source_id,
            "source_sha256": authority.source_sha256,
            "work_id": authority.work_id,
        }
        expected_reading = {
            **common_identity,
            "reading_result": output.reading_result.model_dump(mode="json"),
            "schema_version": "gezhi.reading_result.v1",
        }
        expected_drafts = {
            **common_identity,
            "candidate_drafts": [
                draft.model_dump(mode="json") for draft in output.candidate_drafts
            ],
            "schema_version": "gezhi.candidate_drafts.v1",
        }
        expected_queue = {
            "candidates": [],
            **common_identity,
            "schema_version": "gezhi.review_queue.v1",
            "semantic_run_id": run_id,
        }
        if (
            reading_document != expected_reading
            or draft_document != expected_drafts
            or review_queue != expected_queue
            or _read_safe_bytes(
                run_dir / "result" / "candidate_knowledge.jsonl",
                limit=_MAX_JSON_OR_TEXT_BYTES,
            )
            != b""
            or manifest.get("candidate_draft_count")
            != len(output.candidate_drafts)
            or frozenset(_entry_names(run_dir / "result"))
            != {
                "candidate_drafts.json",
                "candidate_knowledge.jsonl",
                "reading_result.json",
                "review_queue.json",
            }
        ):
            raise ValueError("semantic result bundle is invalid")
        assets = _asset_entries(run_dir)
        observed_paths = {entry["path"] for entry in assets}
        expected_paths = {
            "input.jsonl",
            "prompt.txt",
            "schema.json",
            "result/reading_result.json",
            "result/candidate_drafts.json",
            "result/candidate_knowledge.jsonl",
            "result/review_queue.json",
        }
        for ordinal in range(1, attempt_count + 1):
            prefix = f"attempts/{ordinal:02d}/"
            expected_paths.update({prefix + "attempt.json", prefix + "events.jsonl"})
            if _name_exists(
                run_dir / "attempts" / f"{ordinal:02d}",
                "final_message.txt",
            ):
                expected_paths.add(prefix + "final_message.txt")
        if (
            observed_paths != expected_paths
            or manifest.get("assets") != assets
        ):
            raise ValueError("semantic asset inventory is invalid")
    except (
        KeyError,
        OSError,
        ReaderStageStoppedV1,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise ReaderStageStoppedV1("failed", "asset_integrity_lost") from error
    return manifest_sha256


def _replace_semantic_current_v1(
    semantic_dir: Path,
    *,
    authority: ActiveSourceAuthorityV1,
    root: ValidatedDataRootV1,
    run_id: str,
    manifest_sha256: str,
) -> None:
    current = {
        "manifest_sha256": manifest_sha256,
        "run_id": run_id,
        "schema_version": "gezhi.literature_semantic_current.v1",
    }
    current_bytes = _canonical_file_bytes(current)
    current_temp = semantic_dir / (".current.json." + uuid.uuid4().hex + ".tmp")
    _write_new_verified(current_temp, current_bytes)
    _checkpoint(authority, root)
    try:
        with open_validated_data_root_v1(str(semantic_dir)):
            os.replace(current_temp, semantic_dir / "current.json")
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
    ) as error:
        raise ReaderRecoveryUncertainV1(
            "semantic current replace result is uncertain"
        ) from error
    if _read_safe_bytes(
        semantic_dir / "current.json",
        limit=len(current_bytes),
    ) != current_bytes:
        raise ReaderRecoveryUncertainV1("semantic current readback differs")


def _load_current(
    semantic_dir: Path,
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
) -> ReaderAdvanceV1 | None:
    current_path = semantic_dir / "current.json"
    try:
        if not _name_exists(semantic_dir, "current.json"):
            return None
        current_bytes = _read_safe_bytes(
            current_path,
            limit=_MAX_JSON_OR_TEXT_BYTES,
        )
        current = json.loads(current_bytes)
        run_id = current["run_id"]
        manifest_sha256 = current["manifest_sha256"]
        if (
            type(run_id) is not str
            or _SEMANTIC_RUN_ID.fullmatch(run_id) is None
            or type(manifest_sha256) is not str
            or _SHA256.fullmatch(manifest_sha256) is None
            or current_bytes != _canonical_file_bytes(current)
            or current
            != {
                "manifest_sha256": manifest_sha256,
                "run_id": run_id,
                "schema_version": "gezhi.literature_semantic_current.v1",
            }
        ):
            raise ValueError("semantic current is invalid")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ReaderStageStoppedV1("failed", "asset_integrity_lost") from error
    _validated_success_manifest_sha256(
        semantic_dir / "runs" / run_id,
        run_id,
        authority,
        canonical,
        expected_sha256=manifest_sha256,
    )
    return ReaderAdvanceV1(
        advanced=False,
        run_id=run_id,
        manifest_sha256=manifest_sha256,
        pending_candidate_ids=(),
    )


def _recover_committed_success_v1(
    semantic_dir: Path,
    runs_dir: Path,
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    *,
    root: ValidatedDataRootV1,
) -> ReaderAdvanceV1 | None:
    matches: list[tuple[str, str]] = []
    try:
        entries = _entry_names(runs_dir)
    except ValueError as error:
        raise ReaderRecoveryUncertainV1(
            "semantic run inventory cannot be proven"
        ) from error
    for run_id in entries:
        run_dir = runs_dir / run_id
        if _SEMANTIC_RUN_ID.fullmatch(run_id) is None:
            raise ReaderRecoveryUncertainV1("semantic run namespace is invalid")
        try:
            _entry_names(run_dir)
        except ValueError as error:
            raise ReaderRecoveryUncertainV1(
                "semantic run namespace cannot be proven"
            ) from error
        manifest_sha256 = _validated_success_manifest_sha256(
            run_dir,
            run_id,
            authority,
            canonical,
            expected_sha256=None,
        )
        if manifest_sha256 is not None:
            matches.append((run_id, manifest_sha256))
    if not matches:
        return None
    if len(matches) != 1:
        raise ReaderRecoveryUncertainV1(
            "semantic current recovery has multiple success candidates"
        )
    run_id, manifest_sha256 = matches[0]
    _replace_semantic_current_v1(
        semantic_dir,
        authority=authority,
        root=root,
        run_id=run_id,
        manifest_sha256=manifest_sha256,
    )
    return ReaderAdvanceV1(
        advanced=False,
        run_id=run_id,
        manifest_sha256=manifest_sha256,
        pending_candidate_ids=(),
    )


def advance_reader_v1(
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    *,
    root: ValidatedDataRootV1,
    knowledge_root: Path,
    source_environment: Mapping[str, str],
) -> ReaderAdvanceV1:
    """Publish or reuse one evidence-bound zero-Candidate semantic result."""

    semantic_dir = authority.source_directory / "semantic"
    runs_dir = semantic_dir / "runs"
    staging_dir = semantic_dir / ".staging"
    _checkpoint(authority, root)
    for path in (semantic_dir, runs_dir, staging_dir):
        _ensure_directory(path)
    _recover_staging_v1(
        staging_dir,
        runs_dir,
        authority,
        canonical,
        root=root,
    )
    existing = _load_current(semantic_dir, authority, canonical)
    if existing is not None:
        return existing
    recovered = _recover_committed_success_v1(
        semantic_dir,
        runs_dir,
        authority,
        canonical,
        root=root,
    )
    if recovered is not None:
        return recovered

    input_bytes, evidence = _reader_input(authority, canonical)
    schema_bytes = reader_output_schema_bytes_v1()
    prompt_bytes = _effective_prompt(input_bytes)
    run_id = "semrun_" + str(uuid.uuid4())
    stage = staging_dir / run_id
    _checkpoint(authority, root)
    try:
        if _name_exists(staging_dir, run_id) or _name_exists(runs_dir, run_id):
            raise ReaderRecoveryUncertainV1("semantic run ID collides")
        with open_validated_data_root_v1(str(staging_dir)):
            stage.mkdir()
        with open_validated_data_root_v1(str(stage)):
            pass
    except ReaderRecoveryUncertainV1:
        raise
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        ValueError,
    ) as error:
        raise ReaderStageStoppedV1("failed", "commit_failed") from error
    _ensure_directory(stage / "attempts")
    _write_new_verified(stage / "input.jsonl", input_bytes)
    _write_new_verified(stage / "prompt.txt", prompt_bytes)
    _write_new_verified(stage / "schema.json", schema_bytes)

    pre_attempt_failure: ReaderStageStoppedV1 | None = None
    try:
        effective_environment = _source_environment(source_environment)
    except (ReaderStageStoppedV1, ValueError):
        effective_environment = {}
        pre_attempt_failure = ReaderStageStoppedV1(
            "blocked", "codex_runtime_unavailable"
        )
    temporary_value = effective_environment.get("TEMP")
    if not temporary_value:
        pre_attempt_failure = ReaderStageStoppedV1(
            "blocked", "codex_runtime_unavailable"
        )
    temporary_root = Path(temporary_value) if temporary_value else None
    codex_home_value = effective_environment.get("CODEX_HOME")
    codex_home = Path(codex_home_value) if codex_home_value else Path.home() / ".codex"
    literature_path = root.inspection.canonical_path
    if literature_path is None:
        raise ReaderStageStoppedV1("failed", "asset_integrity_lost")
    output: LiteratureReaderOutputV1 | None = None
    process_failed = False
    semantic_failure: ReaderStageStoppedV1 | None = None
    attempt_documents: list[dict[str, object]] = []
    runtime: FrozenCodexRuntimeV1 | None = None
    shared_deadline_monotonic_ns: int | None = None
    if pre_attempt_failure is None:
        try:
            runtime = _prepare_role_invocation_v1()
        except ReaderStageStoppedV1 as error:
            pre_attempt_failure = error
    ordinals = range(1, 4) if pre_attempt_failure is None else ()
    for ordinal in ordinals:
        if temporary_root is None or runtime is None:
            raise RuntimeError("Reader attempt root invariant is invalid")
        try:
            attempt_root = _create_attempt_root(temporary_root)
        except ReaderStageStoppedV1 as error:
            if (
                error.outcome == "blocked"
                and error.reason == "codex_runtime_unavailable"
            ):
                pre_attempt_failure = error
                break
            raise
        timed_out = False
        try:
            attempt: AttemptTerminalEvidenceV1 | None = None
            try:
                attempt_result = _run_role_attempt_v1(
                    ReaderAttemptRequestV1(
                        runtime=runtime,
                        attempt_root=attempt_root,
                        attempt_ordinal=ordinal,
                        prompt=prompt_bytes,
                        schema_path=stage / "schema.json",
                        codex_home=codex_home,
                        literature_root=Path(literature_path),
                        knowledge_root=knowledge_root,
                        source_environment=effective_environment,
                        existing_shared_deadline_monotonic_ns=(
                            shared_deadline_monotonic_ns
                        ),
                    )
                )
                if not isinstance(attempt_result, AttemptTerminalEvidenceV1):
                    raise ReaderStageStoppedV1(
                        "blocked", "codex_runtime_unavailable"
                    )
                attempt = attempt_result
                shared_deadline_monotonic_ns = (
                    attempt.shared_deadline_monotonic_ns
                )
            except ReaderStageStoppedV1 as error:
                if (
                    error.outcome == "blocked"
                    and error.reason == "codex_runtime_unavailable"
                ):
                    pre_attempt_failure = error
                else:
                    raise
            if attempt is not None:
                timed_out = attempt.mechanical_outcome == "timeout"
                final_message = attempt.final_message
                process_failed = not timed_out and (
                    attempt.mechanical_outcome != "clean"
                    or attempt.exit_code != 0
                    or final_message is None
                    or attempt.resource_ledger_count != 0
                )
                attempt_destination = stage / "attempts" / f"{ordinal:02d}"
                _copy_attempt(attempt, attempt_destination)
                attempt_document, events_valid = _attempt_document(
                    attempt,
                    failure_class=(
                        "timeout"
                        if timed_out
                        else "process_error" if process_failed else None
                    ),
                )
                if not events_valid and not timed_out:
                    process_failed = True
                attempt_documents.append(attempt_document)
                _write_new_verified(
                    attempt_destination / "attempt.json",
                    _canonical_file_bytes(attempt_document),
                )
                if not timed_out and not process_failed:
                    if final_message is None:
                        raise RuntimeError(
                            "clean Reader attempt final-message invariant is invalid"
                        )
                    try:
                        output = _parse_reader_output(
                            _read_safe_bytes(
                                final_message.path,
                                limit=final_message.byte_length,
                            )
                        )
                        _validate_evidence(output, evidence)
                    except ReaderStageStoppedV1 as error:
                        if error.outcome != "failed" or error.reason not in {
                            "reader_output_invalid",
                            "candidate_validation_failed",
                        }:
                            raise
                        semantic_failure = error
                        output = None
        finally:
            shutil.rmtree(attempt_root, ignore_errors=True)
        if pre_attempt_failure is not None:
            break
        if semantic_failure is not None:
            break
        if process_failed:
            break
        if not timed_out:
            break
        if ordinal < 3:
            _wait_before_retry_v1(10.0 if ordinal == 1 else 30.0)

    if output is None:
        if process_failed:
            terminal_outcome: ReaderOutcome = "failed"
            terminal_reason: ReaderReason = "codex_process_failed"
        elif pre_attempt_failure is not None:
            terminal_outcome = pre_attempt_failure.outcome
            terminal_reason = pre_attempt_failure.reason
        elif semantic_failure is not None:
            terminal_outcome = semantic_failure.outcome
            terminal_reason = semantic_failure.reason
        else:
            terminal_outcome = "blocked"
            terminal_reason = "codex_timeout_exhausted"
        assets = _asset_entries(stage)
        manifest = _manifest_document_v1(
            assets=assets,
            attempts=attempt_documents,
            authority=authority,
            canonical=canonical,
            candidate_draft_count=0,
            evidence_count=len(evidence),
            input_bytes=input_bytes,
            prompt_bytes=prompt_bytes,
            reason=terminal_reason,
            run_id=run_id,
            schema_bytes=schema_bytes,
            status=terminal_outcome,
        )
        manifest_bytes = _canonical_file_bytes(manifest)
        _write_new_verified(stage / "manifest.json", manifest_bytes)
        if json.loads(
            _read_safe_bytes(
                stage / "manifest.json",
                limit=_MAX_JSON_OR_TEXT_BYTES,
            )
        )["assets"] != _asset_entries(stage):
            raise ReaderRecoveryUncertainV1(
                "semantic manifest readback differs"
            )
        target = runs_dir / run_id
        _checkpoint(authority, root)
        try:
            if _name_exists(runs_dir, run_id):
                raise ReaderRecoveryUncertainV1(
                    "semantic run target conflicts"
                )
            with (
                open_validated_data_root_v1(str(staging_dir)),
                open_validated_data_root_v1(str(runs_dir)),
            ):
                os.rename(stage, target)
        except ReaderRecoveryUncertainV1:
            raise
        except (
            DataRootLifecycleErrorV1,
            DataRootOpenErrorV1,
            OSError,
            ValueError,
        ) as error:
            raise ReaderRecoveryUncertainV1(
                "semantic run rename result is uncertain"
            ) from error
        raise ReaderStageStoppedV1(terminal_outcome, terminal_reason)

    _ensure_directory(stage / "result")

    reading_document = {
        "canonical_content_sha256": canonical.canonical_content_sha256,
        "reading_result": output.reading_result.model_dump(mode="json"),
        "schema_version": "gezhi.reading_result.v1",
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "work_id": authority.work_id,
    }
    draft_document = {
        "candidate_drafts": [
            draft.model_dump(mode="json") for draft in output.candidate_drafts
        ],
        "canonical_content_sha256": canonical.canonical_content_sha256,
        "schema_version": "gezhi.candidate_drafts.v1",
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "work_id": authority.work_id,
    }
    review_queue = {
        "candidates": [],
        "canonical_content_sha256": canonical.canonical_content_sha256,
        "schema_version": "gezhi.review_queue.v1",
        "semantic_run_id": run_id,
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "work_id": authority.work_id,
    }
    _write_new_verified(
        stage / "result" / "reading_result.json",
        _canonical_file_bytes(reading_document),
    )
    _write_new_verified(
        stage / "result" / "candidate_drafts.json",
        _canonical_file_bytes(draft_document),
    )
    _write_new_verified(stage / "result" / "candidate_knowledge.jsonl", b"")
    _write_new_verified(
        stage / "result" / "review_queue.json",
        _canonical_file_bytes(review_queue),
    )
    assets = _asset_entries(stage)
    manifest = _manifest_document_v1(
        assets=assets,
        attempts=attempt_documents,
        authority=authority,
        canonical=canonical,
        candidate_draft_count=len(output.candidate_drafts),
        evidence_count=len(evidence),
        input_bytes=input_bytes,
        prompt_bytes=prompt_bytes,
        reason=None,
        run_id=run_id,
        schema_bytes=schema_bytes,
        status="succeeded",
    )
    manifest_bytes = _canonical_file_bytes(manifest)
    _write_new_verified(stage / "manifest.json", manifest_bytes)
    if json.loads(
        _read_safe_bytes(
            stage / "manifest.json",
            limit=_MAX_JSON_OR_TEXT_BYTES,
        )
    )["assets"] != _asset_entries(stage):
        raise ReaderRecoveryUncertainV1("semantic manifest readback differs")
    target = runs_dir / run_id
    _checkpoint(authority, root)
    try:
        if _name_exists(runs_dir, run_id):
            raise ReaderRecoveryUncertainV1(
                "semantic run target conflicts"
            )
        with (
            open_validated_data_root_v1(str(staging_dir)),
            open_validated_data_root_v1(str(runs_dir)),
        ):
            os.rename(stage, target)
    except ReaderRecoveryUncertainV1:
        raise
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        ValueError,
    ) as error:
        raise ReaderRecoveryUncertainV1(
            "semantic run rename result is uncertain"
        ) from error
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    _replace_semantic_current_v1(
        semantic_dir,
        authority=authority,
        root=root,
        run_id=run_id,
        manifest_sha256=manifest_sha256,
    )
    return ReaderAdvanceV1(
        advanced=True,
        run_id=run_id,
        manifest_sha256=manifest_sha256,
        pending_candidate_ids=(),
    )
