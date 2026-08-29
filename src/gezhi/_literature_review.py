from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, TypeAlias, cast

from gezhi._literature_candidate import (
    CandidateMaterializationAuthorityStoppedV1,
    CandidateMaterializationRecoveryUncertainV1,
    CandidateMaterializationStageStoppedV1,
    CandidateReviewMaterializationV1,
    validate_candidate_materialization_for_review_v1,
)
from gezhi._literature_intake import (
    ActiveSourceAuthorityV1,
    AddStoppedV1,
    _ensure_plain_directory,
    _load_source,
    _load_work_identity,
    _read_canonical_document,
    _read_safe_bytes,
    _root_checkpoint,
    _write_new_verified,
)
from gezhi._windows_data_root import (
    DataRootOpenErrorV1,
    ValidatedDataRootV1,
    open_validated_data_root_v1,
)
from gezhi._windows_ownership import try_acquire_work_writer_v1

_WORK_ID = re.compile(
    r"^wrk_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SOURCE_ID = re.compile(r"^src_[0-9a-f]{24}$")
_CANDIDATE_ID = re.compile(r"^cand_[0-9a-f]{24}$")
_DESCRIPTOR_ID = re.compile(r"^desc_[0-9a-f]{24}$")
_HANDOFF_ID = re.compile(r"^hnd_[0-9a-f]{24}$")
_MATERIALIZATION_RUN_ID = re.compile(
    r"^matrun_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DECIDED_AT = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:"
    r"[0-9]{2}\.[0-9]{3}Z$"
)
_MAX_INT64 = 9_223_372_036_854_775_807
_MAX_ASSET_BYTES = 16 * 1024 * 1024
_MAX_ENUMERATED_ITEMS = 16_384

ReviewActionV1: TypeAlias = Literal["accept", "reject", "defer"]
ReviewStatusV1: TypeAlias = Literal["accepted", "rejected", "deferred"]
HandoffActionV1: TypeAlias = Literal["accept", "withdraw", "none"]
IntakeStatusV1: TypeAlias = Literal["active", "withdrawn"]
ReviewBlockedReasonV1: TypeAlias = Literal[
    "candidate_invalid",
    "candidate_not_found",
    "work_busy",
    "handoff_blocked",
    "import_blocked",
    "data_root_unsafe",
    "data_root_unavailable",
]
ReviewFailedReasonV1: TypeAlias = Literal[
    "data_root_integrity_lost",
    "candidate_integrity_lost",
    "review_state_invalid",
    "review_commit_failed",
    "handoff_failed",
    "import_failed",
]
DataRootKindV1: TypeAlias = Literal["literature", "knowledge"]


@dataclass(frozen=True, slots=True)
class ReviewCandidateCommandV1:
    candidate_id: str
    action: ReviewActionV1


@dataclass(frozen=True, slots=True)
class ReviewProgressV1:
    candidate_id: str
    decision_disposition: Literal["created", "unchanged"]
    handoff_action: HandoffActionV1
    handoff_id: str | None
    handoff_status: Literal["committed", "not_required", "pending"]
    import_status: Literal["applied", "not_required", "pending"]
    intake_status: IntakeStatusV1 | None
    payload_sha256: str
    review_revision: int
    review_status: ReviewStatusV1
    work_id: str

    def as_mapping_v1(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "decision_disposition": self.decision_disposition,
            "handoff_action": self.handoff_action,
            "handoff_id": self.handoff_id,
            "handoff_status": self.handoff_status,
            "import_status": self.import_status,
            "intake_status": self.intake_status,
            "payload_sha256": self.payload_sha256,
            "review_revision": self.review_revision,
            "review_status": self.review_status,
            "schema_version": "gezhi.literature_review_result.v1",
            "work_id": self.work_id,
        }


@dataclass(frozen=True, slots=True)
class ReviewCauseV1:
    reason: ReviewBlockedReasonV1 | ReviewFailedReasonV1
    data_root: DataRootKindV1 | None = None


@dataclass(frozen=True, slots=True)
class ReviewSucceededV1:
    progress: ReviewProgressV1


@dataclass(frozen=True, slots=True)
class ReviewBlockedV1:
    cause: ReviewCauseV1
    progress: ReviewProgressV1 | None


@dataclass(frozen=True, slots=True)
class ReviewFailedV1:
    cause: ReviewCauseV1
    progress: ReviewProgressV1 | None


ReviewVerdictV1: TypeAlias = ReviewSucceededV1 | ReviewBlockedV1 | ReviewFailedV1


class ReviewIndeterminateV1(RuntimeError):
    """A commit or external verdict cannot be represented as handled."""


@dataclass(frozen=True, slots=True)
class ReviewedHandoffBytesV1:
    manifest_bytes: bytes
    candidates_bytes: bytes


@dataclass(frozen=True, slots=True)
class IntakeAppliedV1:
    intake_status: IntakeStatusV1
    disposition: Literal["applied", "unchanged"]


@dataclass(frozen=True, slots=True)
class IntakeBlockedV1:
    reason: str
    data_root: DataRootKindV1 | None = None


@dataclass(frozen=True, slots=True)
class IntakeFailedV1:
    reason: str
    data_root: DataRootKindV1 | None = None


KnowledgeIntakeVerdictV1: TypeAlias = IntakeAppliedV1 | IntakeBlockedV1 | IntakeFailedV1


class KnowledgeIntakeV1(Protocol):
    def apply(self, handoff: ReviewedHandoffBytesV1) -> KnowledgeIntakeVerdictV1: ...


@dataclass(frozen=True, slots=True)
class _CandidateAuthorityV1:
    source: ActiveSourceAuthorityV1
    materialization: CandidateReviewMaterializationV1
    candidate: dict[str, object]
    descriptors: tuple[dict[str, object], ...]
    citation: dict[str, object]
    evidence_blocks: tuple[dict[str, object], ...]
    is_current_materialization: bool

    @property
    def candidate_id(self) -> str:
        return cast(str, self.candidate["candidate_id"])

    @property
    def payload_sha256(self) -> str:
        return cast(str, self.candidate["payload_sha256"])

    @property
    def payload(self) -> dict[str, object]:
        return cast(dict[str, object], self.candidate["payload"])


class _CandidateNotFoundV1(RuntimeError):
    pass


class _CandidateIntegrityLostV1(RuntimeError):
    pass


class _ReviewStateInvalidV1(RuntimeError):
    pass


class _ReviewCommitFailedV1(RuntimeError):
    pass


class _HandoffFailedV1(RuntimeError):
    pass


class _ImportFailedV1(RuntimeError):
    pass


class _DataRootIntegrityLostV1(RuntimeError):
    pass


def _data_root_open_cause(error: BaseException) -> DataRootOpenErrorV1 | None:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, DataRootOpenErrorV1):
            return current
        current = current.__cause__
    return None


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


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("JSON object contains a duplicate key")
        value[key] = item
    return value


def _reject_float(_value: str) -> object:
    raise ValueError("JSON float is forbidden")


def _decode_canonical_object(
    payload: bytes,
    *,
    file_bytes: bool,
) -> dict[str, object]:
    body = payload
    if file_bytes:
        if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
            raise ValueError("Canonical JSON file must have one final LF")
        body = payload[:-1]
    value = json.loads(
        body,
        object_pairs_hook=_reject_duplicate_pairs,
        parse_float=_reject_float,
        parse_constant=_reject_float,
    )
    if type(value) is not dict or _canonical_payload_bytes(value) != body:
        raise ValueError("JSON object is not canonical")
    return value


def _decode_canonical_jsonl(payload: bytes) -> tuple[dict[str, object], ...]:
    if not payload:
        return ()
    if not payload.endswith(b"\n"):
        raise ValueError("Canonical JSONL has no final LF")
    records: list[dict[str, object]] = []
    for line in payload.splitlines():
        if not line:
            raise ValueError("Canonical JSONL contains an empty record")
        records.append(_decode_canonical_object(line, file_bytes=False))
    return tuple(records)


def _entry_names(path: Path) -> tuple[str, ...]:
    try:
        names = tuple(entry.name for entry in path.iterdir())
    except OSError as error:
        raise _CandidateIntegrityLostV1("authority inventory is unreadable") from error
    if len(names) > _MAX_ENUMERATED_ITEMS or len(names) != len(set(names)):
        raise _CandidateIntegrityLostV1("authority inventory is invalid")
    return tuple(sorted(names, key=lambda value: value.encode("utf-8")))


def _work_source_authority(
    work_directory: Path,
    work_id: str,
    source_directory: Path,
    source_id: str,
) -> ActiveSourceAuthorityV1:
    try:
        work, _work_bytes = _read_canonical_document(work_directory / "work.json")
        if work != {
            "schema_version": "gezhi.literature_work.v1",
            "work_id": work_id,
        }:
            raise ValueError("Work descriptor is invalid")
        _aliases, _identity_sha256 = _load_work_identity(work_directory, work_id)
        source = _load_source(
            source_directory,
            work_id=work_id,
            source_id=source_id,
        )
    except (OSError, ValueError) as error:
        open_error = _data_root_open_cause(error)
        if open_error is not None and open_error.status == "unavailable":
            raise ReviewIndeterminateV1(
                "Work or Source authority availability is uncertain"
            ) from error
        raise _CandidateIntegrityLostV1(
            "Work or Source authority is invalid"
        ) from error
    return ActiveSourceAuthorityV1(
        work_id=work_id,
        source_id=source.source_id,
        source_sha256=source.source_sha256,
        source_byte_length=source.byte_length,
        source_manifest_sha256=source.manifest_sha256,
        work_directory=work_directory,
        source_directory=source.directory,
        original_pdf_path=source.directory / "original.pdf",
        ingest_identity_ready=True,
    )


def _reader_citation(
    authority: ActiveSourceAuthorityV1,
    materialization: CandidateReviewMaterializationV1,
) -> dict[str, object]:
    input_path = (
        authority.source_directory
        / "semantic"
        / "runs"
        / materialization.reader.run_id
        / "input.jsonl"
    )
    try:
        records = _decode_canonical_jsonl(
            _read_safe_bytes(input_path, limit=_MAX_ASSET_BYTES)
        )
        if not records:
            raise ValueError("Reader input metadata is missing")
        metadata = records[0]
        expected_keys = {
            "arxiv_id",
            "authors",
            "canonical_content_sha256",
            "canonical_run_id",
            "doi",
            "record_type",
            "schema_version",
            "source_id",
            "source_sha256",
            "title",
            "work_id",
            "year",
        }
        if (
            set(metadata) != expected_keys
            or metadata.get("record_type") != "metadata"
            or metadata.get("schema_version") != "gezhi.reader_input.v1"
            or metadata.get("work_id") != authority.work_id
            or metadata.get("source_id") != authority.source_id
            or metadata.get("source_sha256") != authority.source_sha256
            or metadata.get("canonical_run_id") != materialization.canonical.run_id
            or metadata.get("canonical_content_sha256")
            != materialization.canonical.canonical_content_sha256
        ):
            raise ValueError("Reader metadata provenance is invalid")
        authors = metadata["authors"]
        title = metadata["title"]
        year = metadata["year"]
        if (
            type(authors) is not list
            or any(type(author) is not str for author in authors)
            or (title is not None and type(title) is not str)
            or (
                year is not None and (type(year) is not int or not 1000 <= year <= 9999)
            )
            or (metadata["doi"] is not None and type(metadata["doi"]) is not str)
            or (
                metadata["arxiv_id"] is not None
                and type(metadata["arxiv_id"]) is not str
            )
        ):
            raise ValueError("Reader citation metadata is invalid")
        visible = [*authors]
        if title is not None:
            visible.append(title)
        for item in visible:
            if any(
                unicodedata.category(character) == "Cc"
                and character not in {"\t", "\n"}
                for character in item
            ):
                raise ValueError("Reader citation text is unsafe")
    except (KeyError, OSError, TypeError, ValueError) as error:
        open_error = _data_root_open_cause(error)
        if open_error is not None and open_error.status == "unavailable":
            raise ReviewIndeterminateV1(
                "Reader citation availability is uncertain"
            ) from error
        raise _CandidateIntegrityLostV1("Reader citation is invalid") from error
    return {
        "arxiv_id": metadata["arxiv_id"],
        "author_count": None if not authors else len(authors),
        "doi": metadata["doi"],
        "primary_authors": authors[:3],
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "title": title,
        "work_id": authority.work_id,
        "year": year,
    }


def _canonical_blocks(
    materialization: CandidateReviewMaterializationV1,
) -> tuple[dict[str, object], ...]:
    try:
        records = _decode_canonical_jsonl(
            _read_safe_bytes(
                materialization.canonical.run_directory / "blocks.jsonl",
                limit=_MAX_ASSET_BYTES,
            )
        )
        block_ids: set[str] = set()
        for record in records:
            block_id = record.get("block_id")
            if (
                type(block_id) is not str
                or block_id in block_ids
                or type(record.get("text")) is not str
                or (
                    record.get("page_index") is not None
                    and (
                        type(record.get("page_index")) is not int
                        or cast(int, record["page_index"]) < 0
                    )
                )
            ):
                raise ValueError("Canonical Evidence Block is invalid")
            block_ids.add(block_id)
    except (OSError, TypeError, ValueError) as error:
        open_error = _data_root_open_cause(error)
        if open_error is not None and open_error.status == "unavailable":
            raise ReviewIndeterminateV1(
                "Canonical Evidence availability is uncertain"
            ) from error
        raise _CandidateIntegrityLostV1("Canonical Evidence is invalid") from error
    return records


def _materialization_is_current(
    materializations: Path,
    materialization: CandidateReviewMaterializationV1,
) -> bool:
    current_path = materializations / "current.json"
    if not current_path.exists():
        return False
    try:
        current, _current_bytes = _read_canonical_document(current_path)
    except (OSError, ValueError):
        return False
    return current == {
        "manifest_sha256": materialization.manifest_sha256,
        "run_id": materialization.run_id,
        "schema_version": "gezhi.candidate_materialization_current.v1",
    }


def _authority_from_run(
    authority: ActiveSourceAuthorityV1,
    materializations: Path,
    run_directory: Path,
    run_id: str,
    candidate_id: str,
) -> _CandidateAuthorityV1:
    try:
        materialization = validate_candidate_materialization_for_review_v1(
            authority,
            run_directory,
            run_id,
        )
        candidates = _decode_canonical_jsonl(materialization.candidate_bytes)
        descriptors = _decode_canonical_jsonl(materialization.descriptor_bytes)
        matches = [
            record
            for record in candidates
            if record.get("candidate_id") == candidate_id
        ]
        if len(matches) != 1:
            raise ValueError("Candidate binding is not unique in successor")
        candidate = matches[0]
        payload = candidate.get("payload")
        payload_sha256 = candidate.get("payload_sha256")
        if (
            set(candidate)
            != {"candidate_id", "payload", "payload_sha256", "schema_version"}
            or candidate.get("schema_version") != "gezhi.candidate_knowledge.v1"
            or type(payload) is not dict
            or type(payload_sha256) is not str
            or _SHA256.fullmatch(payload_sha256) is None
            or hashlib.sha256(_canonical_payload_bytes(payload)).hexdigest()
            != payload_sha256
            or candidate_id != "cand_" + payload_sha256[:24]
            or payload.get("work_id") != authority.work_id
            or payload.get("source_id") != authority.source_id
            or payload.get("source_sha256") != authority.source_sha256
            or payload.get("canonical_content_sha256")
            != materialization.canonical.canonical_content_sha256
        ):
            raise ValueError("Candidate identity or provenance is invalid")
        descriptor_ids: set[str] = set()
        for record in descriptors:
            descriptor_id = record.get("descriptor_id")
            descriptor_payload = record.get("payload")
            descriptor_sha256 = record.get("payload_sha256")
            if (
                set(record)
                != {
                    "descriptor_id",
                    "payload",
                    "payload_sha256",
                    "schema_version",
                }
                or record.get("schema_version") != "gezhi.descriptor_payload_record.v1"
                or type(descriptor_id) is not str
                or _DESCRIPTOR_ID.fullmatch(descriptor_id) is None
                or descriptor_id in descriptor_ids
                or type(descriptor_payload) is not dict
                or type(descriptor_sha256) is not str
                or _SHA256.fullmatch(descriptor_sha256) is None
                or hashlib.sha256(
                    _canonical_payload_bytes(descriptor_payload)
                ).hexdigest()
                != descriptor_sha256
                or descriptor_id != "desc_" + descriptor_sha256[:24]
            ):
                raise ValueError("Descriptor identity is invalid")
            descriptor_ids.add(descriptor_id)
    except CandidateMaterializationRecoveryUncertainV1 as error:
        raise ReviewIndeterminateV1(
            "Candidate successor recovery is uncertain"
        ) from error
    except (
        CandidateMaterializationAuthorityStoppedV1,
        CandidateMaterializationStageStoppedV1,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        open_error = _data_root_open_cause(error)
        if open_error is not None and open_error.status == "unavailable":
            raise ReviewIndeterminateV1(
                "Candidate successor availability is uncertain"
            ) from error
        if isinstance(
            error, CandidateMaterializationAuthorityStoppedV1
        ) and error.reason in {
            "active_source_unavailable",
            "recovery_failed",
        }:
            raise ReviewIndeterminateV1(
                "Candidate successor authority is uncertain"
            ) from error
        if (
            isinstance(error, CandidateMaterializationAuthorityStoppedV1)
            and error.reason == "data_root_integrity_lost"
        ):
            raise _DataRootIntegrityLostV1(
                "Literature root identity drifted"
            ) from error
        raise _CandidateIntegrityLostV1(
            "Candidate successor cannot be proven"
        ) from error
    return _CandidateAuthorityV1(
        source=authority,
        materialization=materialization,
        candidate=candidate,
        descriptors=descriptors,
        citation=_reader_citation(authority, materialization),
        evidence_blocks=_canonical_blocks(materialization),
        is_current_materialization=_materialization_is_current(
            materializations,
            materialization,
        ),
    )


def _candidate_scan_directory(
    path: Path,
    *,
    label: str,
    missing_is_empty: bool,
) -> bool:
    presence = _path_presence(path)
    if presence == "missing":
        if missing_is_empty:
            return False
        raise ReviewIndeterminateV1(f"{label} disappeared during discovery")
    if presence == "unknown":
        raise ReviewIndeterminateV1(f"{label} availability is uncertain")
    try:
        with open_validated_data_root_v1(str(path)):
            pass
    except DataRootOpenErrorV1 as error:
        if error.status == "unavailable":
            raise ReviewIndeterminateV1(f"{label} availability is uncertain") from error
        raise _CandidateIntegrityLostV1(f"{label} is unsafe") from error
    return True


def _candidate_scan_entry_names(path: Path, *, label: str) -> tuple[str, ...]:
    try:
        return _entry_names(path)
    except _CandidateIntegrityLostV1 as error:
        if isinstance(error.__cause__, OSError):
            raise ReviewIndeterminateV1(f"{label} availability is uncertain") from error
        raise


def _find_candidate_authority_v1(
    candidate_id: str,
    *,
    root: ValidatedDataRootV1,
) -> _CandidateAuthorityV1:
    root_path_text = root.inspection.canonical_path
    if root_path_text is None:
        raise _DataRootIntegrityLostV1("Literature root path is unavailable")
    works = Path(root_path_text) / "works"
    if not _candidate_scan_directory(
        works,
        label="Work inventory",
        missing_is_empty=True,
    ):
        raise _CandidateNotFoundV1(candidate_id)
    selector = b'"candidate_id":"' + candidate_id.encode("ascii") + b'"'
    matches: list[_CandidateAuthorityV1] = []
    relevant_invalid = False
    work_names = _candidate_scan_entry_names(works, label="Work inventory")
    for work_id in work_names:
        if work_id == ".staging" or _WORK_ID.fullmatch(work_id) is None:
            continue
        work_directory = works / work_id
        sources = work_directory / "sources"
        _candidate_scan_directory(
            work_directory,
            label="Work authority",
            missing_is_empty=False,
        )
        if not _candidate_scan_directory(
            sources,
            label="Source inventory",
            missing_is_empty=True,
        ):
            continue
        source_names = _candidate_scan_entry_names(
            sources,
            label="Source inventory",
        )
        for source_id in source_names:
            if source_id == ".staging" or _SOURCE_ID.fullmatch(source_id) is None:
                continue
            source_directory = sources / source_id
            _candidate_scan_directory(
                source_directory,
                label="Source authority",
                missing_is_empty=False,
            )
            materializations = source_directory / "semantic" / "materializations"
            runs = materializations / "runs"
            if not _candidate_scan_directory(
                runs,
                label="Candidate materialization inventory",
                missing_is_empty=True,
            ):
                continue
            run_names = _candidate_scan_entry_names(
                runs,
                label="Candidate materialization inventory",
            )
            cached_authority: ActiveSourceAuthorityV1 | None = None
            for run_id in run_names:
                if _MATERIALIZATION_RUN_ID.fullmatch(run_id) is None:
                    continue
                run_directory = runs / run_id
                result_directory = run_directory / "result"
                hinted = False
                hint_unknown = False
                for hint_path in (
                    result_directory / "review_queue.json",
                    result_directory / "candidate_knowledge.jsonl",
                ):
                    hint_presence = _path_presence(hint_path)
                    if hint_presence == "missing":
                        continue
                    if hint_presence == "unknown":
                        hint_unknown = True
                        continue
                    try:
                        hinted = selector in _read_safe_bytes(
                            hint_path,
                            limit=_MAX_ASSET_BYTES,
                        )
                    except OSError:
                        hint_unknown = True
                        continue
                    except ValueError as error:
                        open_error = _data_root_open_cause(error)
                        if (
                            open_error is not None
                            and open_error.status == "unavailable"
                        ):
                            hint_unknown = True
                        continue
                    if hinted:
                        break
                if not hinted:
                    if hint_unknown:
                        raise ReviewIndeterminateV1(
                            "Candidate materialization availability is uncertain"
                        )
                    continue
                try:
                    if cached_authority is None:
                        cached_authority = _work_source_authority(
                            work_directory,
                            work_id,
                            source_directory,
                            source_id,
                        )
                    matches.append(
                        _authority_from_run(
                            cached_authority,
                            materializations,
                            run_directory,
                            run_id,
                            candidate_id,
                        )
                    )
                except _CandidateIntegrityLostV1:
                    relevant_invalid = True
    if relevant_invalid:
        raise _CandidateIntegrityLostV1("Candidate has an invalid binding")
    if not matches:
        raise _CandidateNotFoundV1(candidate_id)
    canonical_binding = (
        matches[0].payload_sha256,
        _canonical_payload_bytes(matches[0].payload),
        matches[0].source.work_id,
        matches[0].materialization.canonical.run_id,
        matches[0].materialization.reader.run_id,
        _canonical_payload_bytes(matches[0].citation),
        matches[0].materialization.descriptor_bytes,
        _canonical_payload_bytes(list(matches[0].evidence_blocks)),
    )
    for match in matches[1:]:
        observed = (
            match.payload_sha256,
            _canonical_payload_bytes(match.payload),
            match.source.work_id,
            match.materialization.canonical.run_id,
            match.materialization.reader.run_id,
            _canonical_payload_bytes(match.citation),
            match.materialization.descriptor_bytes,
            _canonical_payload_bytes(list(match.evidence_blocks)),
        )
        if observed != canonical_binding:
            raise _CandidateIntegrityLostV1(
                "Candidate identity or Handoff provenance is ambiguous"
            )
    matches.sort(
        key=lambda item: (
            0 if item.is_current_materialization else 1,
            item.materialization.canonical.run_id.encode("utf-8"),
            item.materialization.reader.run_id.encode("utf-8"),
            item.materialization.run_id.encode("utf-8"),
        )
    )
    return matches[0]


@dataclass(frozen=True, slots=True)
class _DecisionV1:
    document: dict[str, object]
    payload: bytes
    revision: int
    status: ReviewStatusV1


class _DecisionCommittedDataRootLostV1(_DataRootIntegrityLostV1):
    def __init__(
        self,
        decision: _DecisionV1,
        *,
        previously_imported: bool | None = None,
    ) -> None:
        super().__init__("Literature root identity drifted after Decision commit")
        self.decision = decision
        self.previously_imported = previously_imported


@dataclass(frozen=True, slots=True)
class _ImportReceiptV1:
    action: Literal["accept", "withdraw"]
    handoff_id: str
    intake_status: IntakeStatusV1
    revision: int


@dataclass(frozen=True, slots=True)
class _ImportAttemptV1:
    action: Literal["accept", "withdraw"]
    decision: _DecisionV1
    handoff_id: str
    handoff: ReviewedHandoffBytesV1

    @property
    def revision(self) -> int:
        return self.decision.revision


def _utc_now_v1() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _ensure_review_directory(
    path: Path,
    *,
    failure: type[
        _ReviewCommitFailedV1 | _HandoffFailedV1 | _ImportFailedV1
    ] = _ReviewCommitFailedV1,
) -> None:
    try:
        _ensure_plain_directory(path)
    except AddStoppedV1 as error:
        open_error = _data_root_open_cause(error)
        if open_error is not None and open_error.status == "unavailable":
            raise ReviewIndeterminateV1(
                "Review directory availability is uncertain"
            ) from error
        if error.reason == "data_root_integrity_lost":
            raise _DataRootIntegrityLostV1(
                "Literature root identity drifted"
            ) from error
        raise failure("Review directory cannot be created") from error


def _read_review_file(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        payload = _read_safe_bytes(path, limit=_MAX_ASSET_BYTES)
        return _decode_canonical_object(payload, file_bytes=True), payload
    except OSError as error:
        raise ReviewIndeterminateV1(
            "Review authority file availability is uncertain"
        ) from error
    except ValueError as error:
        open_error = _data_root_open_cause(error)
        if open_error is not None and open_error.status == "unavailable":
            raise ReviewIndeterminateV1(
                "Review authority file availability is uncertain"
            ) from error
        raise _ReviewStateInvalidV1("Review authority file is invalid") from error


def _path_presence(path: Path) -> Literal["present", "missing", "unknown"]:
    try:
        path.lstat()
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unknown"
    return "present"


def _optional_authority_directory(
    path: Path,
    *,
    label: str,
) -> bool:
    presence = _path_presence(path)
    if presence == "missing":
        return False
    if presence == "unknown":
        raise ReviewIndeterminateV1(f"{label} availability is uncertain")
    try:
        with open_validated_data_root_v1(str(path)):
            pass
    except DataRootOpenErrorV1 as error:
        if error.status == "unavailable":
            raise ReviewIndeterminateV1(f"{label} availability is uncertain") from error
        raise _ReviewStateInvalidV1(f"{label} is unsafe") from error
    return True


def _review_authority_entry_names(path: Path, *, label: str) -> tuple[str, ...]:
    try:
        return _entry_names(path)
    except _CandidateIntegrityLostV1 as error:
        if isinstance(error.__cause__, OSError):
            raise ReviewIndeterminateV1(f"{label} availability is uncertain") from error
        raise _ReviewStateInvalidV1(f"{label} is invalid") from error


def _inspect_exact_file(
    path: Path,
    payload: bytes,
) -> Literal["exact", "different", "missing", "unknown"]:
    try:
        status = path.lstat()
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unknown"
    if not stat.S_ISREG(status.st_mode):
        return "different"
    try:
        observed = _read_safe_bytes(path, limit=len(payload))
    except ValueError as error:
        open_error = _data_root_open_cause(error)
        if open_error is not None and open_error.status == "unavailable":
            return "unknown"
        return "different"
    except OSError:
        return "unknown"
    return "exact" if observed == payload else "different"


def _decision_from_file(
    path: Path,
    *,
    candidate: _CandidateAuthorityV1,
    expected_revision: int,
) -> _DecisionV1:
    document, payload = _read_review_file(path)
    status = document.get("review_status")
    decided_at = document.get("decided_at")
    if (
        set(document)
        != {
            "candidate_id",
            "decided_at",
            "payload_sha256",
            "review_revision",
            "review_status",
            "reviewer_kind",
            "schema_version",
            "work_id",
        }
        or document.get("schema_version") != "gezhi.review_decision.v1"
        or document.get("candidate_id") != candidate.candidate_id
        or document.get("payload_sha256") != candidate.payload_sha256
        or document.get("work_id") != candidate.source.work_id
        or type(document.get("review_revision")) is not int
        or document.get("review_revision") != expected_revision
        or type(status) is not str
        or status not in {"accepted", "rejected", "deferred"}
        or document.get("reviewer_kind") != "local_human_cli"
        or type(decided_at) is not str
        or _DECIDED_AT.fullmatch(decided_at) is None
    ):
        raise _ReviewStateInvalidV1("Review Decision is invalid")
    try:
        datetime.strptime(decided_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise _ReviewStateInvalidV1("Review Decision timestamp is invalid") from error
    return _DecisionV1(
        document=document,
        payload=payload,
        revision=expected_revision,
        status=cast(ReviewStatusV1, status),
    )


def _current_document(
    candidate: _CandidateAuthorityV1,
    decision: _DecisionV1,
) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "decision_sha256": hashlib.sha256(decision.payload).hexdigest(),
        "payload_sha256": candidate.payload_sha256,
        "review_revision": decision.revision,
        "schema_version": "gezhi.review_decision_current.v1",
        "work_id": candidate.source.work_id,
    }


def _replace_review_current(
    candidate_directory: Path,
    candidate: _CandidateAuthorityV1,
    decision: _DecisionV1,
    *,
    root: ValidatedDataRootV1,
) -> None:
    expected = _current_document(candidate, decision)
    payload = _canonical_file_bytes(expected)
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise _DataRootIntegrityLostV1("Literature root identity drifted") from error
    staging = candidate_directory.parent / ".staging" / ".files"
    try:
        _ensure_review_directory(staging)
    except _ReviewCommitFailedV1 as error:
        raise ReviewIndeterminateV1("Review current staging failed") from error
    temporary = staging / (f"{candidate.candidate_id}.current.{uuid.uuid4().hex}.tmp")
    try:
        _write_new_verified(temporary, payload)
    except AddStoppedV1 as error:
        raise ReviewIndeterminateV1("Review current staging failed") from error
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise _DataRootIntegrityLostV1("Literature root identity drifted") from error
    replace_error: OSError | None = None
    try:
        os.replace(temporary, candidate_directory / "current.json")
    except OSError as error:
        replace_error = error
    target_state = _inspect_exact_file(candidate_directory / "current.json", payload)
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise ReviewIndeterminateV1(
            "Review current was replaced but cannot be sealed"
        ) from error
    if target_state != "exact":
        raise ReviewIndeterminateV1(
            "Review current replacement completion is uncertain"
        ) from replace_error


def _load_decision_history(
    candidate_directory: Path,
    candidate: _CandidateAuthorityV1,
) -> tuple[tuple[_DecisionV1, ...], bool]:
    names = _review_authority_entry_names(
        candidate_directory,
        label="Review Candidate inventory",
    )
    allowed_directories = {"import_attempts", "imports", "no_actions"}
    revision_names: list[tuple[int, str]] = []
    for name in names:
        path = candidate_directory / name
        if name == "current.json":
            continue
        if name in allowed_directories:
            if _optional_authority_directory(
                path,
                label=f"Review {name} directory",
            ):
                continue
            raise ReviewIndeterminateV1(
                f"Review {name} directory disappeared during validation"
            )
        match = re.fullmatch(r"([1-9][0-9]*)\.json", name, re.ASCII)
        if match is None:
            raise _ReviewStateInvalidV1("Review namespace contains a foreign entry")
        revision = int(match.group(1))
        if revision > _MAX_INT64:
            raise _ReviewStateInvalidV1("Review revision exceeds int64")
        revision_names.append((revision, name))
    revision_names.sort()
    expected_revisions = list(range(1, len(revision_names) + 1))
    if [revision for revision, _name in revision_names] != expected_revisions:
        raise _ReviewStateInvalidV1("Review revision history has a gap")
    decisions = tuple(
        _decision_from_file(
            candidate_directory / name,
            candidate=candidate,
            expected_revision=revision,
        )
        for revision, name in revision_names
    )
    current_path = candidate_directory / "current.json"
    current_presence = _path_presence(current_path)
    if current_presence == "unknown":
        raise ReviewIndeterminateV1("Review current availability is uncertain")
    if not decisions:
        if current_presence == "present":
            raise _ReviewStateInvalidV1("Review current exists without a Decision")
        return (), False
    pointed_revision = 0
    if current_presence == "present":
        current, _current_bytes = _read_review_file(current_path)
        pointed_revision_raw = current.get("review_revision")
        if (
            set(current)
            != {
                "candidate_id",
                "decision_sha256",
                "payload_sha256",
                "review_revision",
                "schema_version",
                "work_id",
            }
            or current.get("schema_version") != "gezhi.review_decision_current.v1"
            or current.get("candidate_id") != candidate.candidate_id
            or current.get("payload_sha256") != candidate.payload_sha256
            or current.get("work_id") != candidate.source.work_id
            or type(pointed_revision_raw) is not int
            or not 1 <= pointed_revision_raw <= len(decisions)
        ):
            raise _ReviewStateInvalidV1("Review current pointer is invalid")
        pointed_revision = pointed_revision_raw
        if current != _current_document(candidate, decisions[pointed_revision - 1]):
            raise _ReviewStateInvalidV1("Review current hash binding is invalid")
    unpointed = len(decisions) - pointed_revision
    if unpointed > 1:
        raise _ReviewStateInvalidV1("Multiple unpointed Review leaves are ambiguous")
    return decisions, pointed_revision != len(decisions)


def _publish_decision_leaf(
    reviews: Path,
    candidate_directory: Path,
    candidate: _CandidateAuthorityV1,
    revision: int,
    status: ReviewStatusV1,
    *,
    root: ValidatedDataRootV1,
) -> _DecisionV1:
    document = {
        "candidate_id": candidate.candidate_id,
        "decided_at": _utc_now_v1(),
        "payload_sha256": candidate.payload_sha256,
        "review_revision": revision,
        "review_status": status,
        "reviewer_kind": "local_human_cli",
        "schema_version": "gezhi.review_decision.v1",
        "work_id": candidate.source.work_id,
    }
    payload = _canonical_file_bytes(document)
    staging = reviews / ".staging" / ".files"
    _ensure_review_directory(staging)
    staged_path = staging / (
        f"{candidate.candidate_id}.{revision}.{uuid.uuid4().hex}.json"
    )
    target = candidate_directory / f"{revision}.json"
    try:
        _write_new_verified(staged_path, payload)
    except AddStoppedV1 as error:
        raise _ReviewCommitFailedV1("Review Decision staging failed") from error
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise _DataRootIntegrityLostV1("Literature root identity drifted") from error
    rename_error: OSError | None = None
    try:
        os.rename(staged_path, target)
    except OSError as error:
        rename_error = error
    target_state = _inspect_exact_file(target, payload)
    staged_state = _inspect_exact_file(staged_path, payload)
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise ReviewIndeterminateV1(
            "Review Decision was committed but cannot be sealed"
        ) from error
    if target_state == "different":
        raise _ReviewCommitFailedV1(
            "Review Decision target conflicts"
        ) from rename_error
    if target_state == "missing" and staged_state in {"exact", "different"}:
        raise _ReviewCommitFailedV1("Review Decision publish failed") from rename_error
    if target_state != "exact":
        raise ReviewIndeterminateV1(
            "Review Decision publication completion is uncertain"
        ) from rename_error
    decision = _DecisionV1(
        document=document,
        payload=payload,
        revision=revision,
        status=status,
    )
    try:
        _replace_review_current(
            candidate_directory,
            candidate,
            decision,
            root=root,
        )
    except _DataRootIntegrityLostV1 as error:
        raise _DecisionCommittedDataRootLostV1(decision) from error
    return decision


def _commit_or_reuse_decision(
    candidate: _CandidateAuthorityV1,
    status: ReviewStatusV1,
    *,
    reviews: Path,
    candidate_directory: Path,
    history: tuple[_DecisionV1, ...],
    root: ValidatedDataRootV1,
) -> tuple[_DecisionV1, Literal["created", "unchanged"]]:
    if history and history[-1].status == status:
        return history[-1], "unchanged"
    revision = len(history) + 1
    if revision > _MAX_INT64:
        raise _ReviewStateInvalidV1("Review revision cannot advance")
    decision = _publish_decision_leaf(
        reviews,
        candidate_directory,
        candidate,
        revision,
        status,
        root=root,
    )
    return decision, "created"


def _publish_exact_file(
    path: Path,
    payload: bytes,
    *,
    staging_directory: Path,
    root: ValidatedDataRootV1,
    failure: type[_ReviewCommitFailedV1 | _HandoffFailedV1 | _ImportFailedV1],
) -> None:
    initial = _inspect_exact_file(path, payload)
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise _DataRootIntegrityLostV1("Literature root identity drifted") from error
    if initial == "exact":
        return
    if initial == "different":
        raise failure("Immutable target is invalid or conflicting")
    if initial == "unknown":
        raise ReviewIndeterminateV1("Immutable target availability is uncertain")
    _ensure_review_directory(staging_directory, failure=failure)
    temporary = staging_directory / (
        f"{path.parent.name}.{path.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        _write_new_verified(temporary, payload)
    except AddStoppedV1 as error:
        raise failure("Immutable target staging failed") from error
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise _DataRootIntegrityLostV1("Literature root identity drifted") from error
    rename_error: OSError | None = None
    try:
        os.rename(temporary, path)
    except OSError as error:
        rename_error = error
    target_state = _inspect_exact_file(path, payload)
    staged_state = _inspect_exact_file(temporary, payload)
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise ReviewIndeterminateV1(
            "Immutable target was committed but cannot be sealed"
        ) from error
    if target_state == "different":
        raise failure("Immutable target readback differs") from rename_error
    if target_state == "missing" and staged_state in {"exact", "different"}:
        raise failure("Immutable target publication failed") from rename_error
    if target_state != "exact":
        raise ReviewIndeterminateV1(
            "Immutable target publication completion is uncertain"
        ) from rename_error


def _no_action_document(
    candidate: _CandidateAuthorityV1,
    decision: _DecisionV1,
) -> dict[str, object]:
    if decision.status not in {"rejected", "deferred"}:
        raise _ReviewStateInvalidV1("Accepted Decision cannot be no-action")
    return {
        "candidate_id": candidate.candidate_id,
        "payload_sha256": candidate.payload_sha256,
        "reason": "never_imported",
        "review_revision": decision.revision,
        "review_status": decision.status,
        "schema_version": "gezhi.review_no_action_receipt.v1",
        "work_id": candidate.source.work_id,
    }


def _commit_no_action_receipt(
    candidate_directory: Path,
    candidate: _CandidateAuthorityV1,
    decision: _DecisionV1,
    *,
    root: ValidatedDataRootV1,
) -> None:
    no_actions = candidate_directory / "no_actions"
    _ensure_review_directory(no_actions, failure=_HandoffFailedV1)
    payload = _canonical_file_bytes(_no_action_document(candidate, decision))
    _publish_exact_file(
        no_actions / f"{decision.revision}.json",
        payload,
        staging_directory=candidate_directory.parent / ".staging" / ".files",
        root=root,
        failure=_HandoffFailedV1,
    )


def _descriptor_snapshots(
    candidate: _CandidateAuthorityV1,
) -> tuple[dict[str, object], ...]:
    payload = candidate.payload
    references = payload.get("descriptor_refs")
    if type(references) is not list or len(references) > 6:
        raise _CandidateIntegrityLostV1("Candidate Descriptor references are invalid")
    by_id = {
        cast(str, record["descriptor_id"]): record for record in candidate.descriptors
    }
    snapshots: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_reference in references:
        if type(raw_reference) is not dict:
            raise _CandidateIntegrityLostV1("Descriptor reference is invalid")
        reference = cast(dict[str, object], raw_reference)
        descriptor_id = reference.get("descriptor_id")
        descriptor = by_id.get(cast(str, descriptor_id))
        if (
            set(reference)
            != {"descriptor_id", "kind", "payload_sha256", "schema_version"}
            or reference.get("schema_version") != "gezhi.descriptor_reference.v1"
            or type(descriptor_id) is not str
            or descriptor_id in seen
            or descriptor is None
            or descriptor.get("payload_sha256") != reference.get("payload_sha256")
            or cast(dict[str, object], descriptor["payload"]).get("kind")
            != reference.get("kind")
        ):
            raise _CandidateIntegrityLostV1("Descriptor reference cannot be resolved")
        seen.add(descriptor_id)
        snapshots.append(
            {
                "payload": descriptor["payload"],
                "reference": reference,
            }
        )
    return tuple(snapshots)


def _evidence_pointers(
    candidate: _CandidateAuthorityV1,
    descriptors: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    containers: list[object] = [candidate.payload.get("statement")]
    containers.extend(
        cast(dict[str, object], snapshot["payload"]).get("value")
        for snapshot in descriptors
    )
    unique: dict[bytes, dict[str, object]] = {}
    for container in containers:
        if type(container) is not dict:
            raise _CandidateIntegrityLostV1("Evidence container is invalid")
        raw_pointers = cast(dict[str, object], container).get("evidence_pointers")
        if type(raw_pointers) is not list or len(raw_pointers) > 6:
            raise _CandidateIntegrityLostV1("Evidence Pointer collection is invalid")
        for raw_pointer in raw_pointers:
            if type(raw_pointer) is not dict:
                raise _CandidateIntegrityLostV1("Evidence Pointer is invalid")
            pointer = cast(dict[str, object], raw_pointer)
            if (
                set(pointer)
                != {"block_id", "canonical_content_sha256", "schema_version"}
                or pointer.get("schema_version") != "gezhi.evidence_pointer.v1"
                or type(pointer.get("block_id")) is not str
                or pointer.get("canonical_content_sha256")
                != candidate.materialization.canonical.canonical_content_sha256
            ):
                raise _CandidateIntegrityLostV1("Evidence Pointer binding is invalid")
            unique[_canonical_payload_bytes(pointer)] = pointer
    pointers = tuple(
        sorted(
            unique.values(),
            key=lambda pointer: (
                cast(str, pointer["canonical_content_sha256"]).encode("ascii"),
                cast(str, pointer["block_id"]).encode("utf-8"),
            ),
        )
    )
    if not 1 <= len(pointers) <= 42:
        raise _CandidateIntegrityLostV1("Evidence Pointer union is invalid")
    return pointers


def _evidence_snapshots(
    candidate: _CandidateAuthorityV1,
    pointers: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    blocks = {
        cast(str, block["block_id"]): block for block in candidate.evidence_blocks
    }
    snapshots: list[dict[str, object]] = []
    for pointer in pointers:
        block = blocks.get(cast(str, pointer["block_id"]))
        if block is None:
            raise _CandidateIntegrityLostV1("Evidence Block is missing")
        text = block.get("text")
        if type(text) is not str:
            raise _CandidateIntegrityLostV1("Evidence Block text is invalid")
        normalized = unicodedata.normalize(
            "NFC", text.replace("\r\n", "\n").replace("\r", "\n")
        ).strip()
        if not normalized:
            raise _CandidateIntegrityLostV1("Evidence excerpt is empty")
        snapshots.append(
            {
                "excerpt": normalized[:800],
                "page_index": block.get("page_index"),
                "pointer": pointer,
            }
        )
    return tuple(snapshots)


def _handoff_identity(
    candidate: _CandidateAuthorityV1,
    decision: _DecisionV1,
    action: Literal["accept", "withdraw"],
) -> tuple[str, dict[str, object]]:
    identity = {
        "action": action,
        "candidate_id": candidate.candidate_id,
        "payload_sha256": candidate.payload_sha256,
        "review_revision": decision.revision,
        "schema_version": "gezhi.reviewed_handoff_identity.v1",
    }
    digest = hashlib.sha256(_canonical_payload_bytes(identity)).hexdigest()
    return "hnd_" + digest[:24], identity


def _handoff_bytes(
    candidate: _CandidateAuthorityV1,
    decision: _DecisionV1,
    action: Literal["accept", "withdraw"],
) -> tuple[str, ReviewedHandoffBytesV1]:
    handoff_id, _identity = _handoff_identity(candidate, decision, action)
    review_receipt = {
        "review_revision": decision.revision,
        "review_status": decision.status,
        "reviewer_kind": "local_human_cli",
    }
    if action == "accept":
        if decision.status != "accepted":
            raise _ReviewStateInvalidV1("Accept Handoff lacks accepted Decision")
        descriptors = _descriptor_snapshots(candidate)
        pointers = _evidence_pointers(candidate, descriptors)
        record = {
            "action": "accept",
            "candidate": candidate.candidate,
            "citation": candidate.citation,
            "descriptor_snapshots": list(descriptors),
            "evidence_snapshots": list(_evidence_snapshots(candidate, pointers)),
            "review_receipt": review_receipt,
            "schema_version": "gezhi.reviewed_candidate_action.v1",
        }
    else:
        if decision.status not in {"rejected", "deferred"}:
            raise _ReviewStateInvalidV1("Withdraw Handoff lacks non-accepted Decision")
        record = {
            "action": "withdraw",
            "candidate_id": candidate.candidate_id,
            "payload_sha256": candidate.payload_sha256,
            "review_receipt": review_receipt,
            "schema_version": "gezhi.reviewed_candidate_action.v1",
        }
    candidates_bytes = _canonical_file_bytes(record)
    canonical = candidate.materialization.canonical
    reader = candidate.materialization.reader
    manifest = {
        "candidates_sha256": hashlib.sha256(candidates_bytes).hexdigest(),
        "canonical_content_sha256": canonical.canonical_content_sha256,
        "canonical_run_id": canonical.run_id,
        "handoff_id": handoff_id,
        "provenance": {
            "canonical_run_id": canonical.run_id,
            "semantic_run_id": reader.run_id,
        },
        "record_count": 1,
        "schema_version": "gezhi.reviewed_handoff_manifest.v1",
        "source_id": candidate.source.source_id,
        "source_sha256": candidate.source.source_sha256,
        "work_id": candidate.source.work_id,
    }
    return handoff_id, ReviewedHandoffBytesV1(
        manifest_bytes=_canonical_file_bytes(manifest),
        candidates_bytes=candidates_bytes,
    )


def _validate_handoff_bytes(
    handoff_id: str,
    handoff: ReviewedHandoffBytesV1,
    candidate: _CandidateAuthorityV1,
    decision: _DecisionV1,
    action: Literal["accept", "withdraw"],
) -> None:
    try:
        expected_id, expected = _handoff_bytes(candidate, decision, action)
    except (_CandidateIntegrityLostV1, _ReviewStateInvalidV1) as error:
        raise _HandoffFailedV1(
            "Reviewed Handoff expectation cannot be derived"
        ) from error
    if handoff_id != expected_id or handoff != expected:
        raise _HandoffFailedV1("Reviewed Handoff bytes differ from authority")
    try:
        manifest = _decode_canonical_object(
            handoff.manifest_bytes,
            file_bytes=True,
        )
        records = _decode_canonical_jsonl(handoff.candidates_bytes)
        if len(records) != 1:
            raise ValueError("Reviewed Handoff must contain one record")
        record = records[0]
        expected_manifest_keys = {
            "candidates_sha256",
            "canonical_content_sha256",
            "canonical_run_id",
            "handoff_id",
            "provenance",
            "record_count",
            "schema_version",
            "source_id",
            "source_sha256",
            "work_id",
        }
        if (
            set(manifest) != expected_manifest_keys
            or manifest.get("schema_version") != "gezhi.reviewed_handoff_manifest.v1"
            or manifest.get("handoff_id") != handoff_id
            or manifest.get("record_count") != 1
            or manifest.get("candidates_sha256")
            != hashlib.sha256(handoff.candidates_bytes).hexdigest()
            or manifest.get("work_id") != candidate.source.work_id
            or manifest.get("source_id") != candidate.source.source_id
            or manifest.get("source_sha256") != candidate.source.source_sha256
            or manifest.get("canonical_content_sha256")
            != candidate.materialization.canonical.canonical_content_sha256
            or type(manifest.get("canonical_run_id")) is not str
            or type(manifest.get("provenance")) is not dict
        ):
            raise ValueError("Reviewed Handoff manifest is invalid")
        provenance = cast(dict[str, object], manifest["provenance"])
        if (
            set(provenance) != {"canonical_run_id", "semantic_run_id"}
            or provenance.get("canonical_run_id") != manifest.get("canonical_run_id")
            or type(provenance.get("semantic_run_id")) is not str
        ):
            raise ValueError("Reviewed Handoff provenance is invalid")
        if record.get("action") != action:
            raise ValueError("Reviewed Handoff action differs")
        review_receipt = record.get("review_receipt")
        if review_receipt != {
            "review_revision": decision.revision,
            "review_status": decision.status,
            "reviewer_kind": "local_human_cli",
        }:
            raise ValueError("Reviewed Handoff review receipt differs")
        if action == "accept":
            if (
                set(record)
                != {
                    "action",
                    "candidate",
                    "citation",
                    "descriptor_snapshots",
                    "evidence_snapshots",
                    "review_receipt",
                    "schema_version",
                }
                or record.get("schema_version") != "gezhi.reviewed_candidate_action.v1"
                or record.get("candidate") != candidate.candidate
                or type(record.get("citation")) is not dict
                or type(record.get("descriptor_snapshots")) is not list
                or type(record.get("evidence_snapshots")) is not list
                or not 1 <= len(cast(list[object], record["evidence_snapshots"])) <= 42
            ):
                raise ValueError("Accept Handoff record is invalid")
        elif (
            set(record)
            != {
                "action",
                "candidate_id",
                "payload_sha256",
                "review_receipt",
                "schema_version",
            }
            or record.get("schema_version") != "gezhi.reviewed_candidate_action.v1"
            or record.get("candidate_id") != candidate.candidate_id
            or record.get("payload_sha256") != candidate.payload_sha256
        ):
            raise ValueError("Withdraw Handoff record is invalid")
        observed_id, _identity = _handoff_identity(candidate, decision, action)
        if observed_id != handoff_id or _HANDOFF_ID.fullmatch(handoff_id) is None:
            raise ValueError("Reviewed Handoff identity differs")
    except (KeyError, TypeError, ValueError) as error:
        raise _HandoffFailedV1("Reviewed Handoff bytes are invalid") from error


def _read_formal_handoff(
    formal: Path,
    handoff_id: str,
    candidate: _CandidateAuthorityV1,
    decision: _DecisionV1,
    action: Literal["accept", "withdraw"],
) -> ReviewedHandoffBytesV1:
    _expected_id, expected = _handoff_bytes(candidate, decision, action)
    state = _inspect_handoff_directory(formal, expected)
    if state == "unknown":
        raise ReviewIndeterminateV1("Formal Handoff availability is uncertain")
    if state != "exact":
        raise _HandoffFailedV1("Formal Handoff is invalid")
    _validate_handoff_bytes(
        handoff_id,
        expected,
        candidate,
        decision,
        action,
    )
    return expected


def _inspect_handoff_directory(
    path: Path,
    expected: ReviewedHandoffBytesV1,
) -> Literal["exact", "different", "missing", "unknown"]:
    presence = _path_presence(path)
    if presence != "present":
        return presence
    try:
        with open_validated_data_root_v1(str(path)):
            pass
    except DataRootOpenErrorV1 as error:
        return "different" if error.status == "unsafe" else "unknown"
    try:
        names = set(_entry_names(path))
    except _CandidateIntegrityLostV1 as error:
        return "unknown" if isinstance(error.__cause__, OSError) else "different"
    if names != {"candidates.jsonl", "manifest.json"}:
        return "different"
    manifest_state = _inspect_exact_file(
        path / "manifest.json", expected.manifest_bytes
    )
    candidates_state = _inspect_exact_file(
        path / "candidates.jsonl",
        expected.candidates_bytes,
    )
    if "unknown" in {manifest_state, candidates_state}:
        return "unknown"
    if manifest_state == candidates_state == "exact":
        return "exact"
    return "different"


def _commit_or_reuse_handoff(
    candidate: _CandidateAuthorityV1,
    decision: _DecisionV1,
    action: Literal["accept", "withdraw"],
    *,
    root: ValidatedDataRootV1,
) -> tuple[str, ReviewedHandoffBytesV1]:
    handoff_id, expected = _handoff_bytes(candidate, decision, action)
    _validate_handoff_bytes(
        handoff_id,
        expected,
        candidate,
        decision,
        action,
    )
    handoffs = candidate.source.work_directory / "handoffs"
    _ensure_review_directory(handoffs, failure=_HandoffFailedV1)
    staging = handoffs / ".staging"
    _ensure_review_directory(staging, failure=_HandoffFailedV1)
    formal = handoffs / handoff_id
    formal_state = _inspect_handoff_directory(formal, expected)
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise _DataRootIntegrityLostV1("Literature root identity drifted") from error
    if formal_state == "exact":
        return handoff_id, expected
    if formal_state == "different":
        raise _HandoffFailedV1("Formal Handoff is invalid")
    if formal_state == "unknown":
        raise ReviewIndeterminateV1("Formal Handoff availability is uncertain")
    stage = staging / handoff_id
    stage_presence = _path_presence(stage)
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise _DataRootIntegrityLostV1("Literature root identity drifted") from error
    if stage_presence == "unknown":
        raise ReviewIndeterminateV1("Staged Handoff availability is uncertain")
    _ensure_review_directory(stage, failure=_HandoffFailedV1)
    _publish_exact_file(
        stage / "candidates.jsonl",
        expected.candidates_bytes,
        staging_directory=staging / ".files",
        root=root,
        failure=_HandoffFailedV1,
    )
    _publish_exact_file(
        stage / "manifest.json",
        expected.manifest_bytes,
        staging_directory=staging / ".files",
        root=root,
        failure=_HandoffFailedV1,
    )
    stage_state = _inspect_handoff_directory(stage, expected)
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise _DataRootIntegrityLostV1("Literature root identity drifted") from error
    if stage_state == "unknown":
        raise ReviewIndeterminateV1("Staged Handoff availability is uncertain")
    if stage_state != "exact":
        raise _HandoffFailedV1("Staged Handoff is invalid")
    rename_error: OSError | None = None
    try:
        os.rename(stage, formal)
    except OSError as error:
        rename_error = error
    formal_state = _inspect_handoff_directory(formal, expected)
    stage_state = _inspect_handoff_directory(stage, expected)
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise ReviewIndeterminateV1(
            "Handoff was committed but cannot be sealed"
        ) from error
    if formal_state == "exact":
        return handoff_id, expected
    if formal_state == "different":
        raise _HandoffFailedV1("Formal Handoff conflicts") from rename_error
    if formal_state == "missing" and stage_state in {"exact", "different"}:
        raise _HandoffFailedV1("Handoff directory was not committed") from rename_error
    raise ReviewIndeterminateV1(
        "Handoff directory commit completion is uncertain"
    ) from rename_error


def _validate_no_action_receipts(
    candidate_directory: Path,
    candidate: _CandidateAuthorityV1,
    decisions: tuple[_DecisionV1, ...],
) -> frozenset[int]:
    receipts_dir = candidate_directory / "no_actions"
    if not _optional_authority_directory(
        receipts_dir,
        label="Review no-action directory",
    ):
        return frozenset()
    revisions: set[int] = set()
    names = _review_authority_entry_names(
        receipts_dir,
        label="Review no-action inventory",
    )
    for name in names:
        match = re.fullmatch(r"([1-9][0-9]*)\.json", name, re.ASCII)
        if match is None:
            raise _ReviewStateInvalidV1("Review no-action namespace is invalid")
        revision = int(match.group(1))
        if revision > len(decisions):
            raise _ReviewStateInvalidV1("Review no-action Decision is missing")
        document, payload = _read_review_file(receipts_dir / name)
        expected = _no_action_document(candidate, decisions[revision - 1])
        if document != expected or payload != _canonical_file_bytes(expected):
            raise _ReviewStateInvalidV1("Review no-action receipt is invalid")
        revisions.add(revision)
    return frozenset(revisions)


def _import_binding(
    candidate: _CandidateAuthorityV1,
    decision: _DecisionV1,
) -> _ImportAttemptV1:
    action: Literal["accept", "withdraw"] = (
        "accept" if decision.status == "accepted" else "withdraw"
    )
    handoff_id, _identity = _handoff_identity(candidate, decision, action)
    try:
        handoff = _read_formal_handoff(
            candidate.source.work_directory / "handoffs" / handoff_id,
            handoff_id,
            candidate,
            decision,
            action,
        )
    except _HandoffFailedV1 as error:
        raise _ReviewStateInvalidV1(
            "Review import binding Handoff is invalid"
        ) from error
    return _ImportAttemptV1(
        action=action,
        decision=decision,
        handoff_id=handoff_id,
        handoff=handoff,
    )


def _import_attempt_document(
    candidate: _CandidateAuthorityV1,
    attempt: _ImportAttemptV1,
) -> dict[str, object]:
    return {
        "action": attempt.action,
        "candidate_id": candidate.candidate_id,
        "candidates_sha256": hashlib.sha256(
            attempt.handoff.candidates_bytes
        ).hexdigest(),
        "handoff_id": attempt.handoff_id,
        "manifest_sha256": hashlib.sha256(attempt.handoff.manifest_bytes).hexdigest(),
        "payload_sha256": candidate.payload_sha256,
        "review_revision": attempt.revision,
        "schema_version": "gezhi.review_import_attempt.v1",
        "work_id": candidate.source.work_id,
    }


def _import_receipt_document(
    candidate: _CandidateAuthorityV1,
    attempt: _ImportAttemptV1,
    intake_status: IntakeStatusV1,
) -> dict[str, object]:
    document = _import_attempt_document(candidate, attempt)
    document["intake_status"] = intake_status
    document["schema_version"] = "gezhi.review_import_receipt.v1"
    return document


def _import_attempts(
    candidate_directory: Path,
    candidate: _CandidateAuthorityV1,
    decisions: tuple[_DecisionV1, ...],
) -> tuple[_ImportAttemptV1, ...]:
    attempts_dir = candidate_directory / "import_attempts"
    if not _optional_authority_directory(
        attempts_dir,
        label="Review import attempt directory",
    ):
        return ()
    names = _review_authority_entry_names(
        attempts_dir,
        label="Review import attempt inventory",
    )
    attempts: list[_ImportAttemptV1] = []
    for name in names:
        match = re.fullmatch(r"([1-9][0-9]*)\.json", name, re.ASCII)
        if match is None:
            raise _ReviewStateInvalidV1("Review import attempt namespace is invalid")
        revision = int(match.group(1))
        if revision > _MAX_INT64 or revision > len(decisions):
            raise _ReviewStateInvalidV1("Review import attempt Decision is missing")
        attempt = _import_binding(candidate, decisions[revision - 1])
        document, payload = _read_review_file(attempts_dir / name)
        expected = _import_attempt_document(candidate, attempt)
        if document != expected or payload != _canonical_file_bytes(expected):
            raise _ReviewStateInvalidV1("Review import attempt is invalid")
        attempts.append(attempt)
    attempts.sort(key=lambda attempt: attempt.revision)
    return tuple(attempts)


def _import_receipts(
    candidate_directory: Path,
    candidate: _CandidateAuthorityV1,
    attempts: tuple[_ImportAttemptV1, ...],
) -> tuple[_ImportReceiptV1, ...]:
    receipts_dir = candidate_directory / "imports"
    if not _optional_authority_directory(
        receipts_dir,
        label="Review import receipt directory",
    ):
        return ()
    names = _review_authority_entry_names(
        receipts_dir,
        label="Review import receipt inventory",
    )
    by_revision = {attempt.revision: attempt for attempt in attempts}
    receipts: list[_ImportReceiptV1] = []
    for name in names:
        match = re.fullmatch(r"([1-9][0-9]*)\.json", name, re.ASCII)
        if match is None:
            raise _ReviewStateInvalidV1("Review import receipt namespace is invalid")
        revision = int(match.group(1))
        attempt = by_revision.get(revision)
        if attempt is None:
            raise _ReviewStateInvalidV1("Review import receipt attempt is missing")
        document, payload = _read_review_file(receipts_dir / name)
        intake_status: IntakeStatusV1 = (
            "active" if attempt.action == "accept" else "withdrawn"
        )
        expected = _import_receipt_document(
            candidate,
            attempt,
            intake_status,
        )
        if document != expected or payload != _canonical_file_bytes(expected):
            raise _ReviewStateInvalidV1("Review import receipt is invalid")
        receipts.append(
            _ImportReceiptV1(
                action=attempt.action,
                handoff_id=attempt.handoff_id,
                intake_status=intake_status,
                revision=revision,
            )
        )
    receipts.sort(key=lambda receipt: receipt.revision)
    imported = False
    for receipt in receipts:
        if receipt.action == "accept":
            imported = True
        elif not imported:
            raise _ReviewStateInvalidV1(
                "Withdraw import receipt has no prior accepted import"
            )
    return tuple(receipts)


def _review_authority_snapshot(
    candidate: _CandidateAuthorityV1,
    *,
    root: ValidatedDataRootV1,
) -> tuple[
    Path,
    Path,
    tuple[_DecisionV1, ...],
    tuple[_ImportAttemptV1, ...],
    tuple[_ImportReceiptV1, ...],
]:
    reviews = candidate.source.work_directory / "reviews"
    _ensure_review_directory(reviews)
    _ensure_review_directory(reviews / ".staging")
    candidate_directory = reviews / candidate.candidate_id
    _ensure_review_directory(candidate_directory)
    decisions, repair_current = _load_decision_history(
        candidate_directory,
        candidate,
    )
    no_actions = _validate_no_action_receipts(
        candidate_directory,
        candidate,
        decisions,
    )
    attempts = _import_attempts(candidate_directory, candidate, decisions)
    imports = _import_receipts(candidate_directory, candidate, attempts)
    if no_actions.intersection(attempt.revision for attempt in attempts):
        raise _ReviewStateInvalidV1(
            "Review revision has both no-action and import authority"
        )
    imported_revisions = {receipt.revision for receipt in imports}
    accepted_import_revisions = {
        receipt.revision for receipt in imports if receipt.action == "accept"
    }
    if any(
        accepted_revision < no_action_revision
        for no_action_revision in no_actions
        for accepted_revision in accepted_import_revisions
    ):
        raise _ReviewStateInvalidV1(
            "Review no-action contradicts a prior accepted import"
        )
    for attempt in attempts:
        if attempt.action == "withdraw" and not any(
            revision < attempt.revision for revision in accepted_import_revisions
        ):
            raise _ReviewStateInvalidV1(
                "Withdraw import attempt has no prior accepted import"
            )
    unresolved = [
        attempt for attempt in attempts if attempt.revision not in imported_revisions
    ]
    if len(unresolved) > 1 or (unresolved and unresolved[0].revision != len(decisions)):
        raise _ReviewStateInvalidV1("Review import attempt recovery is ambiguous")
    if repair_current:
        try:
            _replace_review_current(
                candidate_directory,
                candidate,
                decisions[-1],
                root=root,
            )
        except _DataRootIntegrityLostV1 as error:
            raise _DecisionCommittedDataRootLostV1(
                decisions[-1],
                previously_imported=bool(accepted_import_revisions),
            ) from error
    return reviews, candidate_directory, decisions, attempts, imports


def _publish_import_attempt(
    candidate_directory: Path,
    candidate: _CandidateAuthorityV1,
    attempt: _ImportAttemptV1,
    *,
    root: ValidatedDataRootV1,
) -> None:
    attempts = candidate_directory / "import_attempts"
    _ensure_review_directory(attempts, failure=_ImportFailedV1)
    _publish_exact_file(
        attempts / f"{attempt.revision}.json",
        _canonical_file_bytes(_import_attempt_document(candidate, attempt)),
        staging_directory=candidate_directory.parent / ".staging" / ".files",
        root=root,
        failure=_ImportFailedV1,
    )


def _publish_import_receipt(
    candidate_directory: Path,
    candidate: _CandidateAuthorityV1,
    attempt: _ImportAttemptV1,
    intake_status: IntakeStatusV1,
    *,
    root: ValidatedDataRootV1,
) -> None:
    imports = candidate_directory / "imports"
    _ensure_review_directory(imports, failure=_ImportFailedV1)
    _publish_exact_file(
        imports / f"{attempt.revision}.json",
        _canonical_file_bytes(
            _import_receipt_document(candidate, attempt, intake_status)
        ),
        staging_directory=candidate_directory.parent / ".staging" / ".files",
        root=root,
        failure=_ImportFailedV1,
    )


def _progress(
    candidate: _CandidateAuthorityV1,
    decision: _DecisionV1,
    disposition: Literal["created", "unchanged"],
    *,
    handoff_action: HandoffActionV1,
    handoff_id: str | None,
    handoff_status: Literal["committed", "not_required", "pending"],
    import_status: Literal["applied", "not_required", "pending"],
    intake_status: IntakeStatusV1 | None,
) -> ReviewProgressV1:
    return ReviewProgressV1(
        candidate_id=candidate.candidate_id,
        decision_disposition=disposition,
        handoff_action=handoff_action,
        handoff_id=handoff_id,
        handoff_status=handoff_status,
        import_status=import_status,
        intake_status=intake_status,
        payload_sha256=candidate.payload_sha256,
        review_revision=decision.revision,
        review_status=decision.status,
        work_id=candidate.source.work_id,
    )


def _data_root_lost_after_decision(
    candidate: _CandidateAuthorityV1,
    decision: _DecisionV1,
    disposition: Literal["created", "unchanged"],
    *,
    previously_imported: bool,
) -> ReviewFailedV1:
    if decision.status == "accepted":
        handoff_action: HandoffActionV1 = "accept"
    elif previously_imported:
        handoff_action = "withdraw"
    else:
        handoff_action = "none"
    handoff_id = (
        _handoff_identity(candidate, decision, handoff_action)[0]
        if handoff_action in {"accept", "withdraw"}
        else None
    )
    return ReviewFailedV1(
        ReviewCauseV1("data_root_integrity_lost", "literature"),
        _progress(
            candidate,
            decision,
            disposition,
            handoff_action=handoff_action,
            handoff_id=handoff_id,
            handoff_status="pending",
            import_status="not_required" if handoff_action == "none" else "pending",
            intake_status=None,
        ),
    )


def _continue_import_attempt(
    candidate_directory: Path,
    candidate: _CandidateAuthorityV1,
    attempt: _ImportAttemptV1,
    disposition: Literal["created", "unchanged"],
    *,
    root: ValidatedDataRootV1,
    knowledge_intake: KnowledgeIntakeV1 | None,
) -> _ImportReceiptV1 | ReviewBlockedV1 | ReviewFailedV1:
    committed = _progress(
        candidate,
        attempt.decision,
        disposition,
        handoff_action=attempt.action,
        handoff_id=attempt.handoff_id,
        handoff_status="committed",
        import_status="pending",
        intake_status=None,
    )
    if knowledge_intake is None:
        return ReviewBlockedV1(ReviewCauseV1("import_blocked"), committed)
    try:
        intake_verdict = knowledge_intake.apply(attempt.handoff)
    except Exception as error:
        raise ReviewIndeterminateV1(
            "KnowledgeIntake completion is uncertain"
        ) from error
    if type(intake_verdict) is IntakeBlockedV1:
        if intake_verdict.reason in {"data_root_unsafe", "data_root_unavailable"}:
            if intake_verdict.data_root != "knowledge":
                raise ReviewIndeterminateV1(
                    "KnowledgeIntake returned an invalid Data Root block"
                )
            reason = cast(ReviewBlockedReasonV1, intake_verdict.reason)
            return ReviewBlockedV1(
                ReviewCauseV1(reason, "knowledge"),
                committed,
            )
        return ReviewBlockedV1(ReviewCauseV1("import_blocked"), committed)
    if type(intake_verdict) is IntakeFailedV1:
        if intake_verdict.reason == "data_root_integrity_lost":
            if intake_verdict.data_root != "knowledge":
                raise ReviewIndeterminateV1(
                    "KnowledgeIntake returned an invalid Data Root failure"
                )
            return ReviewFailedV1(
                ReviewCauseV1("data_root_integrity_lost", "knowledge"),
                committed,
            )
        return ReviewFailedV1(ReviewCauseV1("import_failed"), committed)
    if type(intake_verdict) is not IntakeAppliedV1:
        raise ReviewIndeterminateV1("KnowledgeIntake returned an unknown verdict")
    expected_status: IntakeStatusV1 = (
        "active" if attempt.action == "accept" else "withdrawn"
    )
    if (
        intake_verdict.intake_status != expected_status
        or intake_verdict.disposition not in {"applied", "unchanged"}
    ):
        raise ReviewIndeterminateV1("KnowledgeIntake returned an invalid receipt")
    try:
        _publish_import_receipt(
            candidate_directory,
            candidate,
            attempt,
            intake_verdict.intake_status,
            root=root,
        )
    except (_ImportFailedV1, _DataRootIntegrityLostV1) as error:
        raise ReviewIndeterminateV1(
            "Knowledge import succeeded but receipt commit is uncertain"
        ) from error
    return _ImportReceiptV1(
        action=attempt.action,
        handoff_id=attempt.handoff_id,
        intake_status=intake_verdict.intake_status,
        revision=attempt.revision,
    )


def review_candidate_v1(
    command: ReviewCandidateCommandV1,
    *,
    root: ValidatedDataRootV1,
    knowledge_intake: KnowledgeIntakeV1 | None,
) -> ReviewVerdictV1:
    if type(command) is not ReviewCandidateCommandV1 or command.action not in {
        "accept",
        "reject",
        "defer",
    }:
        raise TypeError("Review command is invalid")
    if (
        type(command.candidate_id) is not str
        or _CANDIDATE_ID.fullmatch(command.candidate_id) is None
    ):
        return ReviewBlockedV1(
            ReviewCauseV1("candidate_invalid"),
            None,
        )
    try:
        initial = _find_candidate_authority_v1(command.candidate_id, root=root)
    except _CandidateNotFoundV1:
        return ReviewBlockedV1(ReviewCauseV1("candidate_not_found"), None)
    except _CandidateIntegrityLostV1:
        return ReviewFailedV1(ReviewCauseV1("candidate_integrity_lost"), None)
    except _DataRootIntegrityLostV1:
        return ReviewFailedV1(
            ReviewCauseV1("data_root_integrity_lost", "literature"),
            None,
        )
    root_identity = root.inspection.identity
    if root_identity is None:
        return ReviewFailedV1(
            ReviewCauseV1("data_root_integrity_lost", "literature"),
            None,
        )
    owner = try_acquire_work_writer_v1(root_identity, initial.source.work_id)
    if owner is None:
        return ReviewBlockedV1(ReviewCauseV1("work_busy"), None)
    with owner:
        try:
            _root_checkpoint(root)
            candidate = _find_candidate_authority_v1(command.candidate_id, root=root)
            if (
                candidate.source.work_id != initial.source.work_id
                or candidate.payload_sha256 != initial.payload_sha256
                or _canonical_payload_bytes(candidate.payload)
                != _canonical_payload_bytes(initial.payload)
            ):
                raise _CandidateIntegrityLostV1("Candidate changed before ownership")
        except AddStoppedV1:
            return ReviewFailedV1(
                ReviewCauseV1("data_root_integrity_lost", "literature"),
                None,
            )
        except _CandidateNotFoundV1:
            return ReviewFailedV1(
                ReviewCauseV1("candidate_integrity_lost"),
                None,
            )
        except _CandidateIntegrityLostV1:
            return ReviewFailedV1(
                ReviewCauseV1("candidate_integrity_lost"),
                None,
            )
        except _DataRootIntegrityLostV1:
            return ReviewFailedV1(
                ReviewCauseV1("data_root_integrity_lost", "literature"),
                None,
            )
        status = {
            "accept": "accepted",
            "reject": "rejected",
            "defer": "deferred",
        }[command.action]
        try:
            reviews, candidate_directory, history, attempts, prior_imports = (
                _review_authority_snapshot(candidate, root=root)
            )
        except _DecisionCommittedDataRootLostV1 as error:
            if error.previously_imported is None:
                raise ReviewIndeterminateV1(
                    "Recovered Decision import history is unavailable"
                ) from error
            return _data_root_lost_after_decision(
                candidate,
                error.decision,
                "unchanged",
                previously_imported=error.previously_imported,
            )
        except _ReviewStateInvalidV1:
            return ReviewFailedV1(ReviewCauseV1("review_state_invalid"), None)
        except _ReviewCommitFailedV1:
            return ReviewFailedV1(ReviewCauseV1("review_commit_failed"), None)
        except _DataRootIntegrityLostV1:
            return ReviewFailedV1(
                ReviewCauseV1("data_root_integrity_lost", "literature"),
                None,
            )
        imported_revisions = {receipt.revision for receipt in prior_imports}
        unresolved = next(
            (
                attempt
                for attempt in attempts
                if attempt.revision not in imported_revisions
            ),
            None,
        )
        if unresolved is not None:
            continuation = _continue_import_attempt(
                candidate_directory,
                candidate,
                unresolved,
                "unchanged",
                root=root,
                knowledge_intake=knowledge_intake,
            )
            if (
                type(continuation) is ReviewBlockedV1
                or type(continuation) is ReviewFailedV1
            ):
                return continuation
            if type(continuation) is not _ImportReceiptV1:
                raise ReviewIndeterminateV1(
                    "Import continuation returned an invalid verdict"
                )
            prior_imports = (*prior_imports, continuation)
        previously_imported = any(
            receipt.action == "accept" for receipt in prior_imports
        )
        try:
            decision, disposition = _commit_or_reuse_decision(
                candidate,
                cast(ReviewStatusV1, status),
                reviews=reviews,
                candidate_directory=candidate_directory,
                history=history,
                root=root,
            )
        except _DecisionCommittedDataRootLostV1 as error:
            return _data_root_lost_after_decision(
                candidate,
                error.decision,
                "created",
                previously_imported=previously_imported,
            )
        except _ReviewStateInvalidV1:
            return ReviewFailedV1(ReviewCauseV1("review_state_invalid"), None)
        except _ReviewCommitFailedV1:
            return ReviewFailedV1(ReviewCauseV1("review_commit_failed"), None)
        except _DataRootIntegrityLostV1:
            return ReviewFailedV1(
                ReviewCauseV1("data_root_integrity_lost", "literature"),
                None,
            )
        current_import = next(
            (
                receipt
                for receipt in prior_imports
                if receipt.revision == decision.revision
            ),
            None,
        )
        if current_import is not None:
            return ReviewSucceededV1(
                _progress(
                    candidate,
                    decision,
                    disposition,
                    handoff_action=current_import.action,
                    handoff_id=current_import.handoff_id,
                    handoff_status="committed",
                    import_status="applied",
                    intake_status=current_import.intake_status,
                )
            )
        if decision.status != "accepted" and not previously_imported:
            progress = _progress(
                candidate,
                decision,
                disposition,
                handoff_action="none",
                handoff_id=None,
                handoff_status="not_required",
                import_status="not_required",
                intake_status=None,
            )
            pending_no_action = _progress(
                candidate,
                decision,
                disposition,
                handoff_action="none",
                handoff_id=None,
                handoff_status="pending",
                import_status="not_required",
                intake_status=None,
            )
            try:
                _commit_no_action_receipt(
                    candidate_directory,
                    candidate,
                    decision,
                    root=root,
                )
            except _DataRootIntegrityLostV1:
                return ReviewFailedV1(
                    ReviewCauseV1("data_root_integrity_lost", "literature"),
                    pending_no_action,
                )
            except _HandoffFailedV1:
                return ReviewFailedV1(
                    ReviewCauseV1("handoff_failed"),
                    pending_no_action,
                )
            return ReviewSucceededV1(progress)
        action: Literal["accept", "withdraw"] = (
            "accept" if decision.status == "accepted" else "withdraw"
        )
        expected_handoff_id, _identity = _handoff_identity(
            candidate,
            decision,
            action,
        )
        pending = _progress(
            candidate,
            decision,
            disposition,
            handoff_action=action,
            handoff_id=expected_handoff_id,
            handoff_status="pending",
            import_status="pending",
            intake_status=None,
        )
        try:
            handoff_id, handoff = _commit_or_reuse_handoff(
                candidate,
                decision,
                action,
                root=root,
            )
        except _DataRootIntegrityLostV1:
            return ReviewFailedV1(
                ReviewCauseV1("data_root_integrity_lost", "literature"),
                pending,
            )
        except _HandoffFailedV1:
            return ReviewFailedV1(ReviewCauseV1("handoff_failed"), pending)
        committed = _progress(
            candidate,
            decision,
            disposition,
            handoff_action=action,
            handoff_id=handoff_id,
            handoff_status="committed",
            import_status="pending",
            intake_status=None,
        )
        if knowledge_intake is None:
            return ReviewBlockedV1(ReviewCauseV1("import_blocked"), committed)
        attempt = _ImportAttemptV1(
            action=action,
            decision=decision,
            handoff_id=handoff_id,
            handoff=handoff,
        )
        try:
            _publish_import_attempt(
                candidate_directory,
                candidate,
                attempt,
                root=root,
            )
        except _DataRootIntegrityLostV1:
            return ReviewFailedV1(
                ReviewCauseV1("data_root_integrity_lost", "literature"),
                committed,
            )
        except _ImportFailedV1:
            return ReviewFailedV1(ReviewCauseV1("import_failed"), committed)
        continuation = _continue_import_attempt(
            candidate_directory,
            candidate,
            attempt,
            disposition,
            root=root,
            knowledge_intake=knowledge_intake,
        )
        if (
            type(continuation) is ReviewBlockedV1
            or type(continuation) is ReviewFailedV1
        ):
            return continuation
        if type(continuation) is not _ImportReceiptV1:
            raise ReviewIndeterminateV1(
                "Import continuation returned an invalid verdict"
            )
        return ReviewSucceededV1(
            _progress(
                candidate,
                decision,
                disposition,
                handoff_action=action,
                handoff_id=handoff_id,
                handoff_status="committed",
                import_status="applied",
                intake_status=continuation.intake_status,
            )
        )
