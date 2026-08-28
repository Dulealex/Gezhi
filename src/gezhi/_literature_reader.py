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
from typing import Annotated, Literal, NoReturn, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from gezhi._codex_child_process import (
    AttemptTerminalEvidenceV1,
    NeverCancelledV1,
    PreAttemptRejectedV1,
    run_codex_child_v1,
)
from gezhi._codex_role_plan import (
    freeze_codex_attempt_workspace_v1,
    freeze_codex_role_launch_v1,
)
from gezhi._codex_runtime import (
    CodexRuntimeResolutionErrorV1,
    resolve_codex_runtime_v1,
)
from gezhi._literature_canonical import CurrentCanonicalAssetV1
from gezhi._literature_intake import (
    ActiveSourceAuthorityV1,
    _load_work_identity,
)
from gezhi._windows_data_root import ValidatedDataRootV1

_PROJECT_ROOT = Path(r"E:\Gezhi")
_INPUT_BYTE_LIMIT = 524_288
_INPUT_BLOCK_LIMIT = 4_096
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
        non_interpretive = (
            self.synopsis,
            *self.research_problems,
            *self.methods,
            *self.findings,
            *self.limitations,
        )
        if any(item.support_kind == "interpretive" for item in non_interpretive):
            raise ValueError("Interpretive support is not allowed in this group")
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
    attempt_root: Path
    attempt_ordinal: int
    prompt: bytes
    schema_path: Path
    codex_home: Path
    literature_root: Path
    knowledge_root: Path
    source_environment: Mapping[str, str]


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


def _environment_value(source: Mapping[str, str], name: str) -> str | None:
    direct = source.get(name)
    if direct:
        return direct
    folded_name = name.casefold()
    for candidate_name, value in source.items():
        if candidate_name.casefold() == folded_name and value:
            return value
    return None


def _source_environment(source: Mapping[str, str]) -> dict[str, str]:
    result = {"SystemRoot": _environment_value(source, "SystemRoot") or ""}
    if not result["SystemRoot"]:
        raise ReaderStageStoppedV1("blocked", "codex_runtime_unavailable")
    for name in _OPTIONAL_ENVIRONMENT_NAMES:
        value = _environment_value(source, name)
        if value:
            result[name] = value
    return result


def _run_role_attempt_v1(
    request: ReaderAttemptRequestV1,
) -> PreAttemptRejectedV1 | AttemptTerminalEvidenceV1:
    try:
        runtime = resolve_codex_runtime_v1(_PROJECT_ROOT)
        workspace = freeze_codex_attempt_workspace_v1(
            attempt_root=request.attempt_root,
            attempt_ordinal=request.attempt_ordinal,
            literature_authoritative_root=request.literature_root,
            knowledge_authoritative_root=request.knowledge_root,
        )
        plan = freeze_codex_role_launch_v1(
            runtime=runtime,
            role="literature_reader_v1",
            prompt=request.prompt,
            attempt_ordinal=request.attempt_ordinal,
            workspace=workspace,
            schema_path=request.schema_path,
            codex_home=request.codex_home,
            source_environment=request.source_environment,
        )
    except (CodexRuntimeResolutionErrorV1, OSError, ValueError) as error:
        raise ReaderStageStoppedV1("blocked", "codex_runtime_unavailable") from error
    return run_codex_child_v1(plan, NeverCancelledV1())


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
        raw_lines = (canonical.run_directory / "blocks.jsonl").read_bytes().splitlines()
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
        cited_text = "\n".join(evidence[item_id] for item_id in item.evidence_block_ids)
        if any(term not in cited_text for term in item.source_terms):
            raise ReaderStageStoppedV1("failed", "reader_output_invalid")
    for descriptor in descriptor_values:
        if any(
            block_id not in evidence
            for block_id in descriptor.evidence_block_ids
        ):
            raise ReaderStageStoppedV1("failed", "reader_output_invalid")
        cited_text = "\n".join(
            evidence[item_id] for item_id in descriptor.evidence_block_ids
        )
        if any(term not in cited_text for term in descriptor.source_terms):
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


def _write_new_verified(path: Path, payload: bytes) -> None:
    try:
        with path.open("xb", buffering=0) as target:
            offset = 0
            while offset < len(payload):
                written = target.write(payload[offset:])
                if written is None or written <= 0:
                    raise OSError("semantic write made no progress")
                offset += written
        if path.read_bytes() != payload:
            raise OSError("semantic write readback differs")
    except OSError as error:
        raise ReaderStageStoppedV1("failed", "commit_failed") from error


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
    entries: list[dict[str, object]] = []
    for path in sorted(
        (item for item in run_dir.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(run_dir).as_posix().encode("utf-8"),
    ):
        relative = path.relative_to(run_dir).as_posix()
        if relative == "manifest.json":
            continue
        payload = path.read_bytes()
        entry: dict[str, object] = {
            "byte_length": len(payload),
            "media_type": _media_type(relative),
            "path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        schema = _schema_version(relative)
        if schema is not None:
            entry["schema_version"] = schema
        entries.append(entry)
    return entries


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
        shutil.copytree(evidence.events.path.parent, destination)
        events = (destination / "events.jsonl").read_bytes()
        if (
            len(events) != evidence.events.byte_length
            or hashlib.sha256(events).hexdigest() != evidence.events.sha256
        ):
            raise OSError("events capture copy differs")
        if evidence.final_message is not None:
            final = (destination / "final_message.txt").read_bytes()
            if (
                len(final) != evidence.final_message.byte_length
                or hashlib.sha256(final).hexdigest() != evidence.final_message.sha256
            ):
                raise OSError("final capture copy differs")
    except OSError as error:
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
    events = evidence.events.path.read_bytes()
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


def _recover_zero_attempt_staging_v1(
    staging_dir: Path,
    runs_dir: Path,
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
) -> None:
    try:
        staged = sorted(
            staging_dir.iterdir(), key=lambda path: path.name.encode("utf-8")
        )
    except OSError as error:
        raise ReaderRecoveryUncertainV1(
            "semantic staging inventory cannot be proven"
        ) from error
    if not staged:
        return
    if len(staged) != 1:
        raise ReaderRecoveryUncertainV1("semantic staging is ambiguous")
    stage = staged[0]
    run_id = stage.name
    target = runs_dir / run_id
    if (
        not stage.is_dir()
        or _SEMANTIC_RUN_ID.fullmatch(run_id) is None
        or target.exists()
    ):
        raise ReaderRecoveryUncertainV1("semantic staging namespace is invalid")
    try:
        entries = {path.name: path for path in stage.iterdir()}
        if set(entries) != {"attempts", "input.jsonl", "prompt.txt", "schema.json"}:
            raise ValueError("semantic staging inventory is not zero-attempt")
        attempts_dir = entries["attempts"]
        if not attempts_dir.is_dir() or any(attempts_dir.iterdir()):
            raise ValueError("semantic staging contains attempt evidence")
        input_bytes = entries["input.jsonl"].read_bytes()
        expected_input, evidence = _reader_input(authority, canonical)
        schema_bytes = entries["schema.json"].read_bytes()
        expected_schema = reader_output_schema_bytes_v1()
        prompt_bytes = entries["prompt.txt"].read_bytes()
        if (
            input_bytes != expected_input
            or schema_bytes != expected_schema
            or prompt_bytes != _effective_prompt(expected_input)
        ):
            raise ValueError("semantic staging input identity differs")
    except (OSError, ValueError) as error:
        raise ReaderRecoveryUncertainV1(
            "semantic zero-attempt staging cannot be proven"
        ) from error
    assets = _asset_entries(stage)
    manifest = {
        "assets": assets,
        "attempt_count": 0,
        "attempts": [],
        "candidate_count": 0,
        "canonical_content_sha256": canonical.canonical_content_sha256,
        "canonical_manifest_sha256": canonical.manifest_sha256,
        "canonical_run_id": canonical.run_id,
        "codex_cli_version": "0.146.0",
        "finished_at": _utc_now(),
        "git_revision": _git_revision(),
        "input_block_count": len(evidence),
        "input_block_limit": _INPUT_BLOCK_LIMIT,
        "input_byte_length": len(input_bytes),
        "input_byte_limit": _INPUT_BYTE_LIMIT,
        "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "model": "gpt-5.6-sol",
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "reason": "interrupted",
        "reasoning_effort": "high",
        "role": "literature_reader_v1",
        "run_id": run_id,
        "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
        "schema_version": "gezhi.literature_semantic_run_manifest.v1",
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "status": "interrupted",
        "usage_totals": _usage_totals([]),
        "work_id": authority.work_id,
    }
    _write_new_verified(stage / "manifest.json", _canonical_file_bytes(manifest))
    if json.loads((stage / "manifest.json").read_bytes())["assets"] != _asset_entries(
        stage
    ):
        raise ReaderRecoveryUncertainV1(
            "semantic interrupted manifest readback differs"
        )
    try:
        os.rename(stage, target)
    except OSError as error:
        if stage.exists() or target.exists():
            raise ReaderRecoveryUncertainV1(
                "semantic interrupted run rename result is uncertain"
            ) from error
        raise


def _validated_success_manifest_sha256(
    run_dir: Path,
    run_id: str,
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    *,
    expected_sha256: str | None,
) -> str | None:
    try:
        manifest_bytes = (run_dir / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        if type(manifest) is not dict or manifest_bytes != _canonical_file_bytes(
            manifest
        ):
            raise ValueError("semantic manifest encoding is invalid")
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
        if (
            manifest.get("schema_version")
            != "gezhi.literature_semantic_run_manifest.v1"
            or manifest.get("run_id") != run_id
            or manifest.get("status") != "succeeded"
            or not identity_matches
            or manifest_bytes != _canonical_file_bytes(manifest)
            or "reason" in manifest
            or manifest.get("candidate_count") != 0
            or manifest.get("assets") != _asset_entries(run_dir)
        ):
            raise ValueError("semantic run is invalid")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ReaderStageStoppedV1("failed", "asset_integrity_lost") from error
    return manifest_sha256


def _replace_semantic_current_v1(
    semantic_dir: Path,
    *,
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
    try:
        os.replace(current_temp, semantic_dir / "current.json")
    except OSError as error:
        raise ReaderRecoveryUncertainV1(
            "semantic current replace result is uncertain"
        ) from error
    if (semantic_dir / "current.json").read_bytes() != current_bytes:
        raise ReaderRecoveryUncertainV1("semantic current readback differs")


def _load_current(
    semantic_dir: Path,
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
) -> ReaderAdvanceV1 | None:
    current_path = semantic_dir / "current.json"
    if not current_path.exists():
        return None
    try:
        current_bytes = current_path.read_bytes()
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
) -> ReaderAdvanceV1 | None:
    matches: list[tuple[str, str]] = []
    try:
        entries = sorted(runs_dir.iterdir(), key=lambda path: path.name.encode("utf-8"))
    except OSError as error:
        raise ReaderRecoveryUncertainV1(
            "semantic run inventory cannot be proven"
        ) from error
    for run_dir in entries:
        run_id = run_dir.name
        if not run_dir.is_dir() or _SEMANTIC_RUN_ID.fullmatch(run_id) is None:
            raise ReaderRecoveryUncertainV1("semantic run namespace is invalid")
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
    try:
        for path in (semantic_dir, runs_dir, staging_dir):
            path.mkdir(exist_ok=True)
    except OSError as error:
        raise ReaderStageStoppedV1("failed", "commit_failed") from error
    _recover_zero_attempt_staging_v1(
        staging_dir,
        runs_dir,
        authority,
        canonical,
    )
    existing = _load_current(semantic_dir, authority, canonical)
    if existing is not None:
        return existing
    recovered = _recover_committed_success_v1(
        semantic_dir,
        runs_dir,
        authority,
        canonical,
    )
    if recovered is not None:
        return recovered

    input_bytes, evidence = _reader_input(authority, canonical)
    schema_bytes = reader_output_schema_bytes_v1()
    prompt_bytes = _effective_prompt(input_bytes)
    run_id = "semrun_" + str(uuid.uuid4())
    stage = staging_dir / run_id
    try:
        stage.mkdir()
        (stage / "attempts").mkdir()
    except OSError as error:
        raise ReaderStageStoppedV1("failed", "commit_failed") from error
    _write_new_verified(stage / "input.jsonl", input_bytes)
    _write_new_verified(stage / "prompt.txt", prompt_bytes)
    _write_new_verified(stage / "schema.json", schema_bytes)

    temporary_value = _environment_value(source_environment, "TEMP")
    pre_attempt_failure: ReaderStageStoppedV1 | None = None
    if not temporary_value:
        pre_attempt_failure = ReaderStageStoppedV1(
            "blocked", "codex_runtime_unavailable"
        )
    temporary_root = Path(temporary_value) if temporary_value else None
    codex_home_value = _environment_value(source_environment, "CODEX_HOME")
    codex_home = Path(codex_home_value) if codex_home_value else Path.home() / ".codex"
    literature_path = root.inspection.canonical_path
    if literature_path is None:
        raise ReaderStageStoppedV1("failed", "asset_integrity_lost")
    output: LiteratureReaderOutputV1 | None = None
    process_failed = False
    semantic_failure: ReaderStageStoppedV1 | None = None
    attempt_documents: list[dict[str, object]] = []
    ordinals = range(1, 4) if pre_attempt_failure is None else ()
    for ordinal in ordinals:
        if temporary_root is None:
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
                        attempt_root=attempt_root,
                        attempt_ordinal=ordinal,
                        prompt=prompt_bytes,
                        schema_path=stage / "schema.json",
                        codex_home=codex_home,
                        literature_root=Path(literature_path),
                        knowledge_root=knowledge_root,
                        source_environment=_source_environment(source_environment),
                    )
                )
                if not isinstance(attempt_result, AttemptTerminalEvidenceV1):
                    raise ReaderStageStoppedV1(
                        "blocked", "codex_runtime_unavailable"
                    )
                attempt = attempt_result
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
                            final_message.path.read_bytes()
                        )
                        _validate_evidence(output, evidence)
                        if output.candidate_drafts:
                            raise ReaderStageStoppedV1(
                                "failed", "candidate_validation_failed"
                            )
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
            terminal_attempt_count = 1
        elif pre_attempt_failure is not None:
            terminal_outcome = pre_attempt_failure.outcome
            terminal_reason = pre_attempt_failure.reason
            terminal_attempt_count = 0
        elif semantic_failure is not None:
            terminal_outcome = semantic_failure.outcome
            terminal_reason = semantic_failure.reason
            terminal_attempt_count = 1
        else:
            terminal_outcome = "blocked"
            terminal_reason = "codex_timeout_exhausted"
            terminal_attempt_count = 3
        assets = _asset_entries(stage)
        manifest = {
            "assets": assets,
            "attempt_count": terminal_attempt_count,
            "attempts": attempt_documents,
            "candidate_count": 0,
            "canonical_content_sha256": canonical.canonical_content_sha256,
            "canonical_manifest_sha256": canonical.manifest_sha256,
            "canonical_run_id": canonical.run_id,
            "codex_cli_version": "0.146.0",
            "finished_at": _utc_now(),
            "git_revision": _git_revision(),
            "input_block_count": len(evidence),
            "input_block_limit": _INPUT_BLOCK_LIMIT,
            "input_byte_length": len(input_bytes),
            "input_byte_limit": _INPUT_BYTE_LIMIT,
            "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
            "model": "gpt-5.6-sol",
            "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "reason": terminal_reason,
            "reasoning_effort": "high",
            "role": "literature_reader_v1",
            "run_id": run_id,
            "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
            "schema_version": "gezhi.literature_semantic_run_manifest.v1",
            "source_id": authority.source_id,
            "source_sha256": authority.source_sha256,
            "status": terminal_outcome,
            "usage_totals": _usage_totals(attempt_documents),
            "work_id": authority.work_id,
        }
        manifest_bytes = _canonical_file_bytes(manifest)
        _write_new_verified(stage / "manifest.json", manifest_bytes)
        if json.loads((stage / "manifest.json").read_bytes())[
            "assets"
        ] != _asset_entries(stage):
            raise ReaderRecoveryUncertainV1(
                "semantic manifest readback differs"
            )
        target = runs_dir / run_id
        if target.exists():
            raise ReaderRecoveryUncertainV1("semantic run target conflicts")
        try:
            os.rename(stage, target)
        except OSError as error:
            if stage.exists() or target.exists():
                raise ReaderRecoveryUncertainV1(
                    "semantic run rename result is uncertain"
                ) from error
            raise
        raise ReaderStageStoppedV1(terminal_outcome, terminal_reason)

    try:
        (stage / "result").mkdir()
    except OSError as error:
        raise ReaderStageStoppedV1("failed", "commit_failed") from error

    reading_document = {
        "canonical_content_sha256": canonical.canonical_content_sha256,
        "reading_result": output.reading_result.model_dump(mode="json"),
        "schema_version": "gezhi.reading_result.v1",
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "work_id": authority.work_id,
    }
    draft_document = {
        "candidate_drafts": [],
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
    manifest = {
        "assets": assets,
        "attempt_count": 1,
        "attempts": attempt_documents,
        "candidate_count": 0,
        "canonical_content_sha256": canonical.canonical_content_sha256,
        "canonical_manifest_sha256": canonical.manifest_sha256,
        "canonical_run_id": canonical.run_id,
        "codex_cli_version": "0.146.0",
        "finished_at": _utc_now(),
        "git_revision": _git_revision(),
        "input_block_count": len(evidence),
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
        "status": "succeeded",
        "usage_totals": _usage_totals(attempt_documents),
        "work_id": authority.work_id,
    }
    manifest_bytes = _canonical_file_bytes(manifest)
    _write_new_verified(stage / "manifest.json", manifest_bytes)
    if json.loads((stage / "manifest.json").read_bytes())["assets"] != _asset_entries(
        stage
    ):
        raise ReaderRecoveryUncertainV1("semantic manifest readback differs")
    target = runs_dir / run_id
    if target.exists():
        raise ReaderRecoveryUncertainV1("semantic run target conflicts")
    try:
        os.rename(stage, target)
    except OSError as error:
        if stage.exists() or target.exists():
            raise ReaderRecoveryUncertainV1(
                "semantic run rename result is uncertain"
            ) from error
        raise
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    _replace_semantic_current_v1(
        semantic_dir,
        run_id=run_id,
        manifest_sha256=manifest_sha256,
    )
    return ReaderAdvanceV1(
        advanced=True,
        run_id=run_id,
        manifest_sha256=manifest_sha256,
        pending_candidate_ids=(),
    )
