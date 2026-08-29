from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias, cast

from pydantic import ValidationError

from gezhi._literature_canonical import CurrentCanonicalAssetV1
from gezhi._literature_intake import ActiveSourceAuthorityV1
from gezhi._literature_reader import (
    CandidateDraftV1,
    EvidenceStatementV1,
    ReaderAdvanceV1,
    ReaderAuthorityStoppedV1,
    ReaderStageStoppedV1,
    ReadingResultV1,
    StudyDescriptorV1,
    _canonical_file_bytes,
    _canonical_payload_bytes,
    _checkpoint,
    _ensure_directory,
    _entry_names,
    _git_revision,
    _name_exists,
    _read_canonical_object_v1,
    _read_safe_bytes,
    _utc_now,
    _validated_success_manifest_sha256,
    _write_new_verified,
)
from gezhi._windows_data_root import (
    DataRootLifecycleErrorV1,
    DataRootOpenErrorV1,
    ValidatedDataRootV1,
    open_validated_data_root_v1,
)

CandidateMaterializationOutcome: TypeAlias = Literal["blocked", "failed"]
CandidateMaterializationReason: TypeAlias = Literal[
    "reader_prerequisite_unavailable",
    "candidate_validation_failed",
    "asset_integrity_lost",
    "commit_failed",
]
CandidateMaterializationAuthorityReason: TypeAlias = Literal[
    "data_root_integrity_lost",
    "active_source_unavailable",
    "active_source_invalid",
    "recovery_failed",
]

_MAX_ASSET_BYTES = 67_108_864
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MATERIALIZATION_RUN_ID = re.compile(
    r"^matrun_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_KIND_ORDER = {
    "method": 0,
    "object": 1,
    "dataset": 2,
    "experiment": 3,
    "metric": 4,
}
_CANDIDATE_BUDGETS = {
    "method": 2,
    "claim": 4,
    "limitation": 3,
    "relevance": 0,
    "open_question": 2,
}
_PROFILE_DOCUMENT = {
    "candidate_budgets": {
        "claim": 4,
        "limitation": 3,
        "method": 2,
        "open_question": 2,
        "relevance": 0,
    },
    "candidate_contract": "gezhi.candidate_knowledge.v1",
    "descriptor_record": "gezhi.descriptor_payload_record.v1",
    "materializer": "candidate_materializer_v1",
    "queue_contract": "gezhi.review_queue.v2",
    "schema_version": "gezhi.candidate_materializer_profile.v1",
}
_PROFILE_SHA256 = hashlib.sha256(
    _canonical_payload_bytes(_PROFILE_DOCUMENT)
).hexdigest()


def _content_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class CandidateMaterializationAdvanceV1:
    advanced: bool
    run_id: str
    manifest_sha256: str
    pending_candidate_ids: tuple[str, ...]


class CandidateMaterializationStageStoppedV1(RuntimeError):
    def __init__(
        self,
        outcome: CandidateMaterializationOutcome,
        reason: CandidateMaterializationReason,
    ) -> None:
        super().__init__(f"Candidate materialization {outcome}: {reason}")
        self.outcome = outcome
        self.reason = reason


class CandidateMaterializationAuthorityStoppedV1(RuntimeError):
    def __init__(self, reason: CandidateMaterializationAuthorityReason) -> None:
        super().__init__(f"Candidate materialization authority stopped: {reason}")
        self.reason = reason


class CandidateMaterializationRecoveryUncertainV1(RuntimeError):
    """A materialization publication result cannot be represented as handled."""


@dataclass(frozen=True, slots=True)
class _ReaderBundleV1:
    reading_result: ReadingResultV1
    candidate_drafts: tuple[CandidateDraftV1, ...]
    reading_result_sha256: str
    candidate_drafts_sha256: str


@dataclass(frozen=True, slots=True)
class _MaterializedBytesV1:
    input_bytes: bytes
    descriptor_bytes: bytes
    candidate_bytes: bytes
    queue_bytes: bytes
    candidate_count: int
    candidate_draft_count: int
    descriptor_count: int
    pending_candidate_ids: tuple[str, ...]


def _raise_authority(error: ReaderAuthorityStoppedV1) -> None:
    reason = error.reason
    if reason not in {
        "data_root_integrity_lost",
        "active_source_unavailable",
        "active_source_invalid",
        "recovery_failed",
    }:
        reason = "recovery_failed"
    raise CandidateMaterializationAuthorityStoppedV1(
        cast(CandidateMaterializationAuthorityReason, reason)
    ) from error


def _materialization_checkpoint(
    authority: ActiveSourceAuthorityV1,
    root: ValidatedDataRootV1,
) -> None:
    try:
        _checkpoint(authority, root)
    except ReaderAuthorityStoppedV1 as error:
        _raise_authority(error)


def _reader_bundle(
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    reader: ReaderAdvanceV1,
) -> _ReaderBundleV1:
    semantic_dir = authority.source_directory / "semantic"
    try:
        current, _current_bytes = _read_canonical_object_v1(
            semantic_dir / "current.json"
        )
        if current != {
            "manifest_sha256": reader.manifest_sha256,
            "run_id": reader.run_id,
            "schema_version": "gezhi.literature_semantic_current.v1",
        }:
            raise ValueError("Reader current does not match the supplied authority")
        observed_manifest_sha256 = _validated_success_manifest_sha256(
            semantic_dir / "runs" / reader.run_id,
            reader.run_id,
            authority,
            canonical,
            expected_sha256=reader.manifest_sha256,
        )
        if observed_manifest_sha256 != reader.manifest_sha256:
            raise ValueError("Reader success manifest cannot be proven")
        result_dir = semantic_dir / "runs" / reader.run_id / "result"
        reading_document, reading_bytes = _read_canonical_object_v1(
            result_dir / "reading_result.json"
        )
        draft_document, draft_bytes = _read_canonical_object_v1(
            result_dir / "candidate_drafts.json"
        )
        common = {
            "canonical_content_sha256": canonical.canonical_content_sha256,
            "source_id": authority.source_id,
            "source_sha256": authority.source_sha256,
            "work_id": authority.work_id,
        }
        if set(reading_document) != {
            *common,
            "reading_result",
            "schema_version",
        } or any(reading_document.get(key) != value for key, value in common.items()):
            raise ValueError("Reading Result wrapper identity is invalid")
        if reading_document.get("schema_version") != "gezhi.reading_result.v1":
            raise ValueError("Reading Result wrapper Schema is invalid")
        if set(draft_document) != {
            *common,
            "candidate_drafts",
            "schema_version",
        } or any(draft_document.get(key) != value for key, value in common.items()):
            raise ValueError("Candidate Draft wrapper identity is invalid")
        if draft_document.get("schema_version") != "gezhi.candidate_drafts.v1":
            raise ValueError("Candidate Draft wrapper Schema is invalid")
        reading = ReadingResultV1.model_validate(
            reading_document["reading_result"],
            strict=True,
        )
        raw_drafts = draft_document["candidate_drafts"]
        if type(raw_drafts) is not list or len(raw_drafts) > 12:
            raise ValueError("Candidate Draft collection is invalid")
        drafts = tuple(
            CandidateDraftV1.model_validate(value, strict=True)
            for value in raw_drafts
        )
    except ReaderAuthorityStoppedV1 as error:
        _raise_authority(error)
    except (KeyError, ReaderStageStoppedV1, TypeError, ValueError, ValidationError) as error:
        raise CandidateMaterializationStageStoppedV1(
            "failed", "asset_integrity_lost"
        ) from error
    return _ReaderBundleV1(
        reading_result=reading,
        candidate_drafts=drafts,
        reading_result_sha256=hashlib.sha256(reading_bytes).hexdigest(),
        candidate_drafts_sha256=hashlib.sha256(draft_bytes).hexdigest(),
    )


def _evidence_pointers(
    block_ids: list[str],
    canonical_content_sha256: str,
) -> list[dict[str, str]]:
    pointers = [
        {
            "block_id": block_id,
            "canonical_content_sha256": canonical_content_sha256,
            "schema_version": "gezhi.evidence_pointer.v1",
        }
        for block_id in block_ids
    ]
    return sorted(
        pointers,
        key=lambda value: (
            value["canonical_content_sha256"],
            value["block_id"].encode("utf-8"),
        ),
    )


def _statement_payload(
    statement: EvidenceStatementV1,
    canonical_content_sha256: str,
) -> dict[str, object]:
    value = cast(dict[str, object], statement.model_dump(mode="json"))
    block_ids = cast(list[str], value.pop("evidence_block_ids"))
    return {
        "evidence_pointers": _evidence_pointers(
            block_ids, canonical_content_sha256
        ),
        "risk_flags": value["risk_flags"],
        "source_terms": value["source_terms"],
        "support_kind": value["support_kind"],
        "text": value["text"],
    }


def _descriptor_payload(
    draft: CandidateDraftV1,
    locator_index: int,
    reading: ReadingResultV1,
    canonical_content_sha256: str,
) -> tuple[dict[str, object], bytes]:
    locator = draft.descriptor_refs[locator_index]
    if locator.kind == "method":
        try:
            method_descriptor = reading.methods[locator.index]
        except IndexError as error:
            raise ValueError("Descriptor locator is out of range") from error
        descriptor_value = _statement_payload(
            method_descriptor, canonical_content_sha256
        )
    else:
        study_groups: dict[str, list[StudyDescriptorV1]] = {
            "object": reading.study_descriptors.objects,
            "dataset": reading.study_descriptors.datasets,
            "experiment": reading.study_descriptors.experiments,
            "metric": reading.study_descriptors.metrics,
        }
        try:
            study_descriptor = study_groups[locator.kind][locator.index]
        except IndexError as error:
            raise ValueError("Descriptor locator is out of range") from error
        raw = study_descriptor.model_dump(mode="json")
        if raw["kind"] != locator.kind:
            raise ValueError("Descriptor locator kind is invalid")
        descriptor_value = {
            "evidence_pointers": _evidence_pointers(
                raw["evidence_block_ids"], canonical_content_sha256
            ),
            "label": raw["label"],
            "source_terms": raw["source_terms"],
        }
    payload: dict[str, object] = {
        "kind": locator.kind,
        "schema_version": "gezhi.descriptor_payload.v1",
        "value": descriptor_value,
    }
    return payload, _canonical_payload_bytes(payload)


def _materialized_documents(
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    reader: ReaderAdvanceV1,
    bundle: _ReaderBundleV1,
    run_id: str,
) -> _MaterializedBytesV1:
    descriptor_records: dict[str, tuple[str, bytes, dict[str, object]]] = {}
    candidate_records: dict[str, tuple[str, bytes, dict[str, object]]] = {}
    try:
        for draft in bundle.candidate_drafts:
            references: list[dict[str, str]] = []
            for index in range(len(draft.descriptor_refs)):
                payload, payload_bytes = _descriptor_payload(
                    draft,
                    index,
                    bundle.reading_result,
                    canonical.canonical_content_sha256,
                )
                payload_sha256 = _content_sha256(payload_bytes)
                descriptor_id = "desc_" + payload_sha256[:24]
                previous = descriptor_records.get(descriptor_id)
                if previous is not None and (
                    previous[0] != payload_sha256 or previous[1] != payload_bytes
                ):
                    raise ValueError("Descriptor identity collision")
                descriptor_record: dict[str, object] = {
                    "descriptor_id": descriptor_id,
                    "payload": payload,
                    "payload_sha256": payload_sha256,
                    "schema_version": "gezhi.descriptor_payload_record.v1",
                }
                descriptor_records[descriptor_id] = (
                    payload_sha256,
                    payload_bytes,
                    descriptor_record,
                )
                references.append(
                    {
                        "descriptor_id": descriptor_id,
                        "kind": cast(str, payload["kind"]),
                        "payload_sha256": payload_sha256,
                        "schema_version": "gezhi.descriptor_reference.v1",
                    }
                )
            references.sort(
                key=lambda value: (
                    _KIND_ORDER[value["kind"]],
                    value["payload_sha256"],
                )
            )
            candidate_payload: dict[str, object] = {
                "candidate_type": draft.candidate_type,
                "canonical_content_sha256": canonical.canonical_content_sha256,
                "descriptor_refs": references,
                "schema_version": "gezhi.candidate_payload.v1",
                "source_id": authority.source_id,
                "source_sha256": authority.source_sha256,
                "statement": _statement_payload(
                    draft.statement, canonical.canonical_content_sha256
                ),
                "work_id": authority.work_id,
            }
            payload_bytes = _canonical_payload_bytes(candidate_payload)
            payload_sha256 = _content_sha256(payload_bytes)
            candidate_id = "cand_" + payload_sha256[:24]
            previous = candidate_records.get(candidate_id)
            if previous is not None and (
                previous[0] != payload_sha256 or previous[1] != payload_bytes
            ):
                raise ValueError("Candidate identity collision")
            candidate_record: dict[str, object] = {
                "candidate_id": candidate_id,
                "payload": candidate_payload,
                "payload_sha256": payload_sha256,
                "schema_version": "gezhi.candidate_knowledge.v1",
            }
            candidate_records[candidate_id] = (
                payload_sha256,
                payload_bytes,
                candidate_record,
            )
        counts = {candidate_type: 0 for candidate_type in _CANDIDATE_BUDGETS}
        for _payload_hash, _payload_bytes, record in candidate_records.values():
            candidate_type = cast(
                str, cast(dict[str, object], record["payload"])["candidate_type"]
            )
            counts[candidate_type] += 1
        if any(
            counts[candidate_type] > budget
            for candidate_type, budget in _CANDIDATE_BUDGETS.items()
        ):
            raise ValueError("Candidate type budget is exceeded")
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateMaterializationStageStoppedV1(
            "failed", "candidate_validation_failed"
        ) from error

    candidates = sorted(
        (value[2] for value in candidate_records.values()),
        key=lambda value: (value["candidate_id"], value["payload_sha256"]),
    )
    referenced_descriptor_ids = {
        reference["descriptor_id"]
        for candidate in candidates
        for reference in cast(
            list[dict[str, str]],
            cast(dict[str, object], candidate["payload"])["descriptor_refs"],
        )
    }
    descriptors = sorted(
        (
            descriptor_records[descriptor_id][2]
            for descriptor_id in referenced_descriptor_ids
        ),
        key=lambda value: (
            _KIND_ORDER[
                cast(str, cast(dict[str, object], value["payload"])["kind"])
            ],
            value["payload_sha256"],
        ),
    )
    candidate_bytes = b"".join(_canonical_file_bytes(value) for value in candidates)
    descriptor_bytes = b"".join(_canonical_file_bytes(value) for value in descriptors)
    queue_candidates = [
        {
            "candidate_id": candidate["candidate_id"],
            "payload_sha256": candidate["payload_sha256"],
            "review_status": "pending",
            "schema_version": "gezhi.review_queue_candidate.v1",
        }
        for candidate in candidates
    ]
    queue = {
        "candidates": queue_candidates,
        "canonical_content_sha256": canonical.canonical_content_sha256,
        "materialization_run_id": run_id,
        "reader_manifest_sha256": reader.manifest_sha256,
        "reader_run_id": reader.run_id,
        "schema_version": "gezhi.review_queue.v2",
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "work_id": authority.work_id,
    }
    input_document = {
        "candidate_drafts_sha256": bundle.candidate_drafts_sha256,
        "canonical_content_sha256": canonical.canonical_content_sha256,
        "materializer_profile_sha256": _PROFILE_SHA256,
        "reader_manifest_sha256": reader.manifest_sha256,
        "reader_run_id": reader.run_id,
        "reading_result_sha256": bundle.reading_result_sha256,
        "schema_version": "gezhi.candidate_materialization_input.v1",
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "work_id": authority.work_id,
    }
    return _MaterializedBytesV1(
        input_bytes=_canonical_file_bytes(input_document),
        descriptor_bytes=descriptor_bytes,
        candidate_bytes=candidate_bytes,
        queue_bytes=_canonical_file_bytes(queue),
        candidate_count=len(candidates),
        candidate_draft_count=len(bundle.candidate_drafts),
        descriptor_count=len(descriptors),
        pending_candidate_ids=tuple(
            cast(str, candidate["candidate_id"]) for candidate in candidates
        ),
    )


def _asset_entries(materialized: _MaterializedBytesV1) -> list[dict[str, object]]:
    assets = (
        (
            "input.json",
            materialized.input_bytes,
            "application/json",
            "gezhi.candidate_materialization_input.v1",
        ),
        (
            "result/candidate_knowledge.jsonl",
            materialized.candidate_bytes,
            "application/x-ndjson",
            "gezhi.candidate_knowledge.v1",
        ),
        (
            "result/descriptor_payloads.jsonl",
            materialized.descriptor_bytes,
            "application/x-ndjson",
            "gezhi.descriptor_payload_record.v1",
        ),
        (
            "result/review_queue.json",
            materialized.queue_bytes,
            "application/json",
            "gezhi.review_queue.v2",
        ),
    )
    return [
        {
            "byte_length": len(payload),
            "media_type": media_type,
            "path": path,
            "schema_version": schema_version,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for path, payload, media_type, schema_version in assets
    ]


def _manifest_bytes(
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    reader: ReaderAdvanceV1,
    materialized: _MaterializedBytesV1,
    run_id: str,
) -> bytes:
    return _canonical_file_bytes(
        {
            "assets": _asset_entries(materialized),
            "candidate_count": materialized.candidate_count,
            "candidate_draft_count": materialized.candidate_draft_count,
            "canonical_content_sha256": canonical.canonical_content_sha256,
            "descriptor_count": materialized.descriptor_count,
            "finished_at": _utc_now(),
            "git_revision": _git_revision(),
            "input_sha256": hashlib.sha256(materialized.input_bytes).hexdigest(),
            "materializer_profile_sha256": _PROFILE_SHA256,
            "reader_manifest_sha256": reader.manifest_sha256,
            "reader_run_id": reader.run_id,
            "run_id": run_id,
            "schema_version": "gezhi.candidate_materialization_run_manifest.v1",
            "source_id": authority.source_id,
            "source_sha256": authority.source_sha256,
            "status": "succeeded",
            "work_id": authority.work_id,
        }
    )


def _read_exact(path: Path, expected: bytes) -> None:
    if _read_safe_bytes(path, limit=_MAX_ASSET_BYTES) != expected:
        raise ValueError(f"Materialization asset differs: {path.name}")


def _validate_success(
    run_dir: Path,
    run_id: str,
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    reader: ReaderAdvanceV1,
    materialized: _MaterializedBytesV1,
    *,
    expected_manifest_sha256: str | None,
) -> str:
    manifest, manifest_bytes = _read_canonical_object_v1(run_dir / "manifest.json")
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if expected_manifest_sha256 is not None and manifest_sha256 != expected_manifest_sha256:
        raise ValueError("Materialization manifest hash differs")
    expected_keys = {
        "assets",
        "candidate_count",
        "candidate_draft_count",
        "canonical_content_sha256",
        "descriptor_count",
        "finished_at",
        "git_revision",
        "input_sha256",
        "materializer_profile_sha256",
        "reader_manifest_sha256",
        "reader_run_id",
        "run_id",
        "schema_version",
        "source_id",
        "source_sha256",
        "status",
        "work_id",
    }
    if (
        set(manifest) != expected_keys
        or manifest.get("run_id") != run_id
        or manifest.get("schema_version")
        != "gezhi.candidate_materialization_run_manifest.v1"
        or manifest.get("status") != "succeeded"
        or manifest.get("reader_run_id") != reader.run_id
        or manifest.get("reader_manifest_sha256") != reader.manifest_sha256
        or manifest.get("canonical_content_sha256")
        != canonical.canonical_content_sha256
        or manifest.get("source_id") != authority.source_id
        or manifest.get("source_sha256") != authority.source_sha256
        or manifest.get("work_id") != authority.work_id
        or manifest.get("materializer_profile_sha256") != _PROFILE_SHA256
        or manifest.get("candidate_count") != materialized.candidate_count
        or manifest.get("candidate_draft_count")
        != materialized.candidate_draft_count
        or manifest.get("descriptor_count") != materialized.descriptor_count
        or manifest.get("input_sha256")
        != hashlib.sha256(materialized.input_bytes).hexdigest()
        or manifest.get("assets") != _asset_entries(materialized)
        or type(manifest.get("finished_at")) is not str
        or not manifest["finished_at"]
        or type(manifest.get("git_revision")) is not str
        or re.fullmatch(
            r"[0-9a-f]{40}", cast(str, manifest["git_revision"])
        )
        is None
    ):
        raise ValueError("Materialization manifest is invalid")
    if frozenset(_entry_names(run_dir)) != {"input.json", "manifest.json", "result"}:
        raise ValueError("Materialization run namespace is invalid")
    result_dir = run_dir / "result"
    if frozenset(_entry_names(result_dir)) != {
        "candidate_knowledge.jsonl",
        "descriptor_payloads.jsonl",
        "review_queue.json",
    }:
        raise ValueError("Materialization result namespace is invalid")
    _read_exact(run_dir / "input.json", materialized.input_bytes)
    _read_exact(result_dir / "descriptor_payloads.jsonl", materialized.descriptor_bytes)
    _read_exact(result_dir / "candidate_knowledge.jsonl", materialized.candidate_bytes)
    _read_exact(result_dir / "review_queue.json", materialized.queue_bytes)
    return manifest_sha256


def _replace_current(
    materializations: Path,
    authority: ActiveSourceAuthorityV1,
    root: ValidatedDataRootV1,
    run_id: str,
    manifest_sha256: str,
) -> None:
    pointer = _canonical_file_bytes(
        {
            "manifest_sha256": manifest_sha256,
            "run_id": run_id,
            "schema_version": "gezhi.candidate_materialization_current.v1",
        }
    )
    next_path = materializations / ".current.next.json"
    try:
        _write_new_verified(next_path, pointer)
    except ReaderStageStoppedV1 as error:
        raise CandidateMaterializationStageStoppedV1(
            "failed", "commit_failed"
        ) from error
    _materialization_checkpoint(authority, root)
    try:
        with open_validated_data_root_v1(str(materializations)):
            os.replace(next_path, materializations / "current.json")
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        ValueError,
    ) as error:
        raise CandidateMaterializationRecoveryUncertainV1(
            "Materialization current replacement is uncertain"
        ) from error


def _load_or_recover_current(
    materializations: Path,
    runs_dir: Path,
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    reader: ReaderAdvanceV1,
    bundle: _ReaderBundleV1,
    root: ValidatedDataRootV1,
) -> CandidateMaterializationAdvanceV1 | None:
    if _name_exists(materializations, ".current.next.json"):
        try:
            next_pointer, next_bytes = _read_canonical_object_v1(
                materializations / ".current.next.json"
            )
            if set(next_pointer) != {
                "manifest_sha256",
                "run_id",
                "schema_version",
            }:
                raise ValueError("Materialization next pointer shape is invalid")
            next_run_id = next_pointer["run_id"]
            next_manifest_sha256 = next_pointer["manifest_sha256"]
            if (
                type(next_run_id) is not str
                or _MATERIALIZATION_RUN_ID.fullmatch(next_run_id) is None
                or type(next_manifest_sha256) is not str
                or _SHA256.fullmatch(next_manifest_sha256) is None
                or next_pointer["schema_version"]
                != "gezhi.candidate_materialization_current.v1"
            ):
                raise ValueError("Materialization next pointer identity is invalid")
            next_materialized = _materialized_documents(
                authority, canonical, reader, bundle, next_run_id
            )
            observed = _validate_success(
                runs_dir / next_run_id,
                next_run_id,
                authority,
                canonical,
                reader,
                next_materialized,
                expected_manifest_sha256=next_manifest_sha256,
            )
            if _name_exists(materializations, "current.json"):
                current_bytes = _read_safe_bytes(
                    materializations / "current.json",
                    limit=_MAX_ASSET_BYTES,
                )
                if current_bytes != next_bytes:
                    raise ValueError(
                        "Materialization current and next pointer conflict"
                    )
            _materialization_checkpoint(authority, root)
            with open_validated_data_root_v1(str(materializations)):
                os.replace(
                    materializations / ".current.next.json",
                    materializations / "current.json",
                )
        except CandidateMaterializationStageStoppedV1:
            raise
        except CandidateMaterializationAuthorityStoppedV1:
            raise
        except (
            DataRootLifecycleErrorV1,
            DataRootOpenErrorV1,
            KeyError,
            OSError,
            ReaderStageStoppedV1,
            TypeError,
            ValueError,
        ) as error:
            raise CandidateMaterializationRecoveryUncertainV1(
                "Materialization next pointer cannot be recovered"
            ) from error
        return CandidateMaterializationAdvanceV1(
            advanced=True,
            run_id=next_run_id,
            manifest_sha256=observed,
            pending_candidate_ids=next_materialized.pending_candidate_ids,
        )
    if _name_exists(materializations, "current.json"):
        try:
            current, _current_bytes = _read_canonical_object_v1(
                materializations / "current.json"
            )
            if set(current) != {"manifest_sha256", "run_id", "schema_version"}:
                raise ValueError("Materialization current shape is invalid")
            run_id = current["run_id"]
            manifest_sha256 = current["manifest_sha256"]
            if (
                type(run_id) is not str
                or _MATERIALIZATION_RUN_ID.fullmatch(run_id) is None
                or type(manifest_sha256) is not str
                or _SHA256.fullmatch(manifest_sha256) is None
                or current["schema_version"]
                != "gezhi.candidate_materialization_current.v1"
            ):
                raise ValueError("Materialization current identity is invalid")
            materialized = _materialized_documents(
                authority, canonical, reader, bundle, run_id
            )
            observed = _validate_success(
                runs_dir / run_id,
                run_id,
                authority,
                canonical,
                reader,
                materialized,
                expected_manifest_sha256=manifest_sha256,
            )
            return CandidateMaterializationAdvanceV1(
                advanced=False,
                run_id=run_id,
                manifest_sha256=observed,
                pending_candidate_ids=materialized.pending_candidate_ids,
            )
        except CandidateMaterializationStageStoppedV1:
            raise
        except (KeyError, ReaderStageStoppedV1, TypeError, ValueError) as error:
            raise CandidateMaterializationStageStoppedV1(
                "failed", "asset_integrity_lost"
            ) from error

    matches: list[tuple[str, str, _MaterializedBytesV1]] = []
    try:
        names = _entry_names(runs_dir)
        for run_id in names:
            if _MATERIALIZATION_RUN_ID.fullmatch(run_id) is None:
                raise ValueError("Materialization run namespace is invalid")
            manifest, _manifest_bytes_value = _read_canonical_object_v1(
                runs_dir / run_id / "manifest.json"
            )
            if (
                manifest.get("reader_run_id") != reader.run_id
                or manifest.get("reader_manifest_sha256") != reader.manifest_sha256
            ):
                continue
            materialized = _materialized_documents(
                authority, canonical, reader, bundle, run_id
            )
            observed = _validate_success(
                runs_dir / run_id,
                run_id,
                authority,
                canonical,
                reader,
                materialized,
                expected_manifest_sha256=None,
            )
            matches.append((run_id, observed, materialized))
    except CandidateMaterializationStageStoppedV1:
        raise
    except (ReaderStageStoppedV1, TypeError, ValueError) as error:
        raise CandidateMaterializationRecoveryUncertainV1(
            "Materialization committed namespace cannot be proven"
        ) from error
    if len(matches) > 1:
        raise CandidateMaterializationRecoveryUncertainV1(
            "Multiple matching materialization successes exist"
        )
    if not matches:
        return None
    run_id, manifest_sha256, materialized = matches[0]
    _replace_current(
        materializations,
        authority,
        root,
        run_id,
        manifest_sha256,
    )
    return CandidateMaterializationAdvanceV1(
        advanced=True,
        run_id=run_id,
        manifest_sha256=manifest_sha256,
        pending_candidate_ids=materialized.pending_candidate_ids,
    )


def _recover_staging(
    staging_dir: Path,
    runs_dir: Path,
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    reader: ReaderAdvanceV1,
    bundle: _ReaderBundleV1,
    root: ValidatedDataRootV1,
) -> None:
    try:
        names = _entry_names(staging_dir)
        if not names:
            return
        if len(names) != 1:
            raise ValueError("Materialization staging is ambiguous")
        run_id = names[0]
        if _MATERIALIZATION_RUN_ID.fullmatch(run_id) is None:
            raise ValueError("Materialization staging run ID is invalid")
        if _name_exists(runs_dir, run_id):
            raise ValueError("Materialization staging target conflicts")
        materialized = _materialized_documents(
            authority, canonical, reader, bundle, run_id
        )
        _validate_success(
            staging_dir / run_id,
            run_id,
            authority,
            canonical,
            reader,
            materialized,
            expected_manifest_sha256=None,
        )
        _materialization_checkpoint(authority, root)
        with (
            open_validated_data_root_v1(str(staging_dir)),
            open_validated_data_root_v1(str(runs_dir)),
        ):
            os.rename(staging_dir / run_id, runs_dir / run_id)
    except CandidateMaterializationAuthorityStoppedV1:
        raise
    except (
        CandidateMaterializationStageStoppedV1,
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        ReaderStageStoppedV1,
        TypeError,
        ValueError,
    ) as error:
        raise CandidateMaterializationRecoveryUncertainV1(
            "Materialization staging cannot be recovered"
        ) from error


def advance_candidate_materialization_v1(
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    reader: ReaderAdvanceV1,
    *,
    root: ValidatedDataRootV1,
) -> CandidateMaterializationAdvanceV1:
    """Publish or reuse one deterministic Candidate materialization successor."""

    bundle = _reader_bundle(authority, canonical, reader)
    materializations = authority.source_directory / "semantic" / "materializations"
    staging_dir = materializations / ".staging"
    runs_dir = materializations / "runs"
    _materialization_checkpoint(authority, root)
    try:
        for path in (materializations, staging_dir, runs_dir):
            _ensure_directory(path)
    except ReaderStageStoppedV1 as error:
        raise CandidateMaterializationStageStoppedV1(
            "failed", "commit_failed"
        ) from error
    try:
        allowed = {".current.next.json", ".staging", "current.json", "runs"}
        if any(name not in allowed for name in _entry_names(materializations)):
            raise CandidateMaterializationRecoveryUncertainV1(
                "Materialization namespace contains a foreign entry"
            )
    except ValueError as error:
        raise CandidateMaterializationRecoveryUncertainV1(
            "Materialization namespace cannot be proven"
        ) from error

    _recover_staging(
        staging_dir,
        runs_dir,
        authority,
        canonical,
        reader,
        bundle,
        root,
    )

    existing = _load_or_recover_current(
        materializations,
        runs_dir,
        authority,
        canonical,
        reader,
        bundle,
        root,
    )
    if existing is not None:
        return existing

    run_id = "matrun_" + str(uuid.uuid4())
    materialized = _materialized_documents(
        authority, canonical, reader, bundle, run_id
    )
    stage = staging_dir / run_id
    try:
        if _name_exists(staging_dir, run_id) or _name_exists(runs_dir, run_id):
            raise CandidateMaterializationRecoveryUncertainV1(
                "Materialization run ID collides"
            )
        with open_validated_data_root_v1(str(staging_dir)):
            stage.mkdir()
        _ensure_directory(stage / "result")
        _write_new_verified(stage / "input.json", materialized.input_bytes)
        _write_new_verified(
            stage / "result" / "descriptor_payloads.jsonl",
            materialized.descriptor_bytes,
        )
        _write_new_verified(
            stage / "result" / "candidate_knowledge.jsonl",
            materialized.candidate_bytes,
        )
        _write_new_verified(
            stage / "result" / "review_queue.json",
            materialized.queue_bytes,
        )
        manifest_bytes = _manifest_bytes(
            authority, canonical, reader, materialized, run_id
        )
        _write_new_verified(stage / "manifest.json", manifest_bytes)
        manifest_sha256 = _validate_success(
            stage,
            run_id,
            authority,
            canonical,
            reader,
            materialized,
            expected_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        )
    except CandidateMaterializationRecoveryUncertainV1:
        raise
    except ReaderAuthorityStoppedV1 as error:
        _raise_authority(error)
    except ReaderStageStoppedV1 as error:
        raise CandidateMaterializationStageStoppedV1(
            "failed", "commit_failed"
        ) from error
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        raise CandidateMaterializationStageStoppedV1(
            "failed", "commit_failed"
        ) from error

    target = runs_dir / run_id
    _materialization_checkpoint(authority, root)
    try:
        if _name_exists(runs_dir, run_id):
            raise CandidateMaterializationRecoveryUncertainV1(
                "Materialization target conflicts"
            )
        with (
            open_validated_data_root_v1(str(staging_dir)),
            open_validated_data_root_v1(str(runs_dir)),
        ):
            os.rename(stage, target)
    except CandidateMaterializationRecoveryUncertainV1:
        raise
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        ValueError,
    ) as error:
        raise CandidateMaterializationRecoveryUncertainV1(
            "Materialization run rename is uncertain"
        ) from error
    _replace_current(
        materializations,
        authority,
        root,
        run_id,
        manifest_sha256,
    )
    return CandidateMaterializationAdvanceV1(
        advanced=True,
        run_id=run_id,
        manifest_sha256=manifest_sha256,
        pending_candidate_ids=materialized.pending_candidate_ids,
    )
