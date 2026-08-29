from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import cast

import pytest

import gezhi._literature_candidate as candidate
from gezhi._literature_canonical import CurrentCanonicalAssetV1
from gezhi._literature_intake import ActiveSourceAuthorityV1
from gezhi._literature_reader import (
    CandidateDraftV1,
    DescriptorLocatorV1,
    EvidenceStatementV1,
    ReaderAdvanceV1,
    ReadingResultV1,
    StudyDescriptorsV1,
    StudyDescriptorV1,
    SynopsisStatementV1,
)
from gezhi._windows_data_root import ValidatedDataRootV1

_BLOCK_ID = "blk_111111111111111111111111"
_CANONICAL_SHA256 = "c" * 64
_SOURCE_SHA256 = "b" * 64
_READER_MANIFEST_SHA256 = "d" * 64
_WORK_ID = "wrk_123e4567-e89b-42d3-a456-426614174000"
_SOURCE_ID = "src_" + _SOURCE_SHA256[:24]
_READER_RUN_ID = "semrun_123e4567-e89b-42d3-a456-426614174000"
_MATERIALIZATION_RUN_ID = "matrun_123e4567-e89b-42d3-a456-426614174000"


def _statement(text: str) -> EvidenceStatementV1:
    return EvidenceStatementV1(
        evidence_block_ids=[_BLOCK_ID],
        risk_flags=[],
        source_terms=["source term"],
        support_kind="direct",
        text=text,
    )


def _reading_result(*, with_descriptors: bool) -> ReadingResultV1:
    methods = [_statement("这是一个可复验的方法描述。")]
    objects = (
        [
            StudyDescriptorV1(
                evidence_block_ids=[_BLOCK_ID],
                kind="object",
                label="研究对象",
                source_terms=["source term"],
            )
        ]
        if with_descriptors
        else []
    )
    return ReadingResultV1(
        findings=[],
        limitations=[],
        methods=methods if with_descriptors else [],
        open_questions=[],
        relevance=[],
        research_problems=[],
        study_descriptors=StudyDescriptorsV1(
            datasets=[],
            experiments=[],
            metrics=[],
            objects=objects,
        ),
        synopsis=SynopsisStatementV1(
            **_statement("这是用于测试候选物化的阅读摘要。").model_dump()
        ),
    )


def _authority(
    source_directory: Path = Path("source"),
) -> ActiveSourceAuthorityV1:
    return ActiveSourceAuthorityV1(
        work_id=_WORK_ID,
        source_id=_SOURCE_ID,
        source_sha256=_SOURCE_SHA256,
        source_byte_length=123,
        source_manifest_sha256="a" * 64,
        work_directory=source_directory.parent / "work",
        source_directory=source_directory,
        original_pdf_path=source_directory / "source.pdf",
        ingest_identity_ready=True,
    )


def _canonical() -> CurrentCanonicalAssetV1:
    return CurrentCanonicalAssetV1(
        run_id="canonical_fixture",
        run_directory=Path("canonical"),
        input_fingerprint_sha256="e" * 64,
        manifest_sha256="f" * 64,
        canonical_content_sha256=_CANONICAL_SHA256,
    )


def _reader(
    *,
    run_id: str = _READER_RUN_ID,
    manifest_sha256: str = _READER_MANIFEST_SHA256,
) -> ReaderAdvanceV1:
    return ReaderAdvanceV1(
        advanced=True,
        run_id=run_id,
        manifest_sha256=manifest_sha256,
        pending_candidate_ids=(),
    )


def _bundle(
    reading: ReadingResultV1,
    drafts: list[CandidateDraftV1],
) -> candidate._ReaderBundleV1:
    return candidate._ReaderBundleV1(
        reading_result=reading,
        candidate_drafts=tuple(drafts),
        reading_result_sha256="1" * 64,
        candidate_drafts_sha256="2" * 64,
    )


def _materialize(
    reading: ReadingResultV1,
    drafts: list[CandidateDraftV1],
    *,
    run_id: str = _MATERIALIZATION_RUN_ID,
) -> candidate._MaterializedBytesV1:
    return candidate._materialized_documents(
        _authority(),
        _canonical(),
        _reader(),
        _bundle(reading, drafts),
        run_id,
    )


def _write_committed_materialization(
    runs_dir: Path,
    authority: ActiveSourceAuthorityV1,
    reader: ReaderAdvanceV1,
    bundle: candidate._ReaderBundleV1,
    run_id: str,
) -> tuple[candidate._MaterializedBytesV1, str]:
    materialized = candidate._materialized_documents(
        authority,
        _canonical(),
        reader,
        bundle,
        run_id,
    )
    run_dir = runs_dir / run_id
    result_dir = run_dir / "result"
    result_dir.mkdir(parents=True)
    (run_dir / "input.json").write_bytes(materialized.input_bytes)
    (result_dir / "descriptor_payloads.jsonl").write_bytes(
        materialized.descriptor_bytes
    )
    (result_dir / "candidate_knowledge.jsonl").write_bytes(
        materialized.candidate_bytes
    )
    (result_dir / "review_queue.json").write_bytes(materialized.queue_bytes)
    manifest_bytes = candidate._manifest_bytes(
        authority,
        _canonical(),
        reader,
        materialized,
        run_id,
    )
    (run_dir / "manifest.json").write_bytes(manifest_bytes)
    return materialized, hashlib.sha256(manifest_bytes).hexdigest()


def _allow_plain_test_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    def read_safe(path: Path, *, limit: int) -> bytes:
        payload = path.read_bytes()
        if len(payload) > limit:
            raise ValueError("test asset is too large")
        return payload

    def read_canonical(path: Path) -> tuple[dict[str, object], bytes]:
        payload = read_safe(path, limit=candidate._MAX_ASSET_BYTES)
        value = json.loads(payload)
        if type(value) is not dict or payload != candidate._canonical_file_bytes(value):
            raise ValueError("test JSON is not canonical")
        return value, payload

    monkeypatch.setattr(candidate, "_materialization_checkpoint", lambda *_: None)
    monkeypatch.setattr(
        candidate,
        "open_validated_data_root_v1",
        lambda _path: nullcontext(),
    )
    monkeypatch.setattr(candidate, "_read_safe_bytes", read_safe)
    monkeypatch.setattr(candidate, "_read_canonical_object_v1", read_canonical)
    monkeypatch.setattr(
        candidate,
        "_write_new_verified",
        lambda path, payload: path.write_bytes(payload),
    )
    monkeypatch.setattr(
        candidate,
        "_entry_names",
        lambda path: tuple(sorted(child.name for child in path.iterdir())),
    )
    monkeypatch.setattr(
        candidate,
        "_name_exists",
        lambda parent, name: (parent / name).exists(),
    )


def test_duplicate_drafts_collapse_after_descriptor_identity_is_resolved() -> None:
    reading = _reading_result(with_descriptors=True)
    draft = CandidateDraftV1(
        candidate_type="claim",
        descriptor_refs=[
            DescriptorLocatorV1(kind="object", index=0),
            DescriptorLocatorV1(kind="method", index=0),
        ],
        statement=_statement("这是一个具有两个正式描述符引用的结论。"),
    )

    first = _materialize(reading, [draft, draft])
    second = _materialize(
        reading,
        [draft, draft],
        run_id="matrun_223e4567-e89b-42d3-a456-426614174000",
    )

    assert first.candidate_draft_count == 2
    assert first.candidate_count == 1
    assert first.descriptor_count == 2
    assert first.candidate_bytes == second.candidate_bytes
    assert first.descriptor_bytes == second.descriptor_bytes
    assert first.input_bytes == second.input_bytes
    assert first.queue_bytes != second.queue_bytes

    candidates = [json.loads(line) for line in first.candidate_bytes.splitlines()]
    descriptors = [json.loads(line) for line in first.descriptor_bytes.splitlines()]
    assert len(candidates) == 1
    assert [
        reference["kind"]
        for reference in candidates[0]["payload"]["descriptor_refs"]
    ] == ["method", "object"]
    assert [descriptor["payload"]["kind"] for descriptor in descriptors] == [
        "method",
        "object",
    ]
    for descriptor in descriptors:
        payload_bytes = candidate._canonical_payload_bytes(descriptor["payload"])
        payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
        assert descriptor["payload_sha256"] == payload_sha256
        assert descriptor["descriptor_id"] == "desc_" + payload_sha256[:24]
    payload_bytes = candidate._canonical_payload_bytes(candidates[0]["payload"])
    payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    assert candidates[0]["payload_sha256"] == payload_sha256
    assert candidates[0]["candidate_id"] == "cand_" + payload_sha256[:24]


def test_candidate_type_budget_is_applied_after_exact_deduplication() -> None:
    reading = _reading_result(with_descriptors=False)
    duplicate = CandidateDraftV1(
        candidate_type="claim",
        descriptor_refs=[],
        statement=_statement("重复结论。"),
    )
    assert _materialize(reading, [duplicate] * 12).candidate_count == 1

    unique = [
        CandidateDraftV1(
            candidate_type="claim",
            descriptor_refs=[],
            statement=_statement(f"唯一结论 {index}。"),
        )
        for index in range(5)
    ]
    with pytest.raises(
        candidate.CandidateMaterializationStageStoppedV1
    ) as stopped:
        _materialize(reading, unique)
    assert stopped.value.outcome == "failed"
    assert stopped.value.reason == "candidate_validation_failed"


def _same_full_hash(_payload: bytes) -> str:
    return "a" * 64


def _same_short_id(payload: bytes) -> str:
    suffix = "1" * 40 if "第一".encode() in payload else "2" * 40
    return "a" * 24 + suffix


@pytest.mark.parametrize("identity", [_same_full_hash, _same_short_id])
def test_candidate_identity_conflicts_fail_the_whole_materialization(
    monkeypatch: pytest.MonkeyPatch,
    identity: Callable[[bytes], str],
) -> None:
    reading = _reading_result(with_descriptors=False)
    drafts = [
        CandidateDraftV1(
            candidate_type="claim",
            descriptor_refs=[],
            statement=_statement("第一条不同的结论。"),
        ),
        CandidateDraftV1(
            candidate_type="claim",
            descriptor_refs=[],
            statement=_statement("第二条不同的结论。"),
        ),
    ]
    monkeypatch.setattr(candidate, "_content_sha256", identity)

    with pytest.raises(
        candidate.CandidateMaterializationStageStoppedV1
    ) as stopped:
        _materialize(reading, drafts)
    assert stopped.value.outcome == "failed"
    assert stopped.value.reason == "candidate_validation_failed"


def test_current_replace_requires_matching_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materializations = tmp_path / "materializations"
    materializations.mkdir()
    authority = _authority(tmp_path / "source")
    _allow_plain_test_filesystem(monkeypatch)
    original_read = candidate._read_safe_bytes

    def mismatched_current(path: Path, *, limit: int) -> bytes:
        if path == materializations / "current.json":
            return b"{}\n"
        return original_read(path, limit=limit)

    monkeypatch.setattr(candidate, "_read_safe_bytes", mismatched_current)
    with pytest.raises(candidate.CandidateMaterializationRecoveryUncertainV1):
        candidate._replace_current(
            materializations,
            authority,
            cast(ValidatedDataRootV1, object()),
            _MATERIALIZATION_RUN_ID,
            "a" * 64,
        )


def test_valid_historical_current_repairs_the_current_reader_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "source"
    authority = _authority(source_dir)
    materializations = source_dir / "semantic" / "materializations"
    runs_dir = materializations / "runs"
    runs_dir.mkdir(parents=True)
    reading = _reading_result(with_descriptors=False)
    drafts = [
        CandidateDraftV1(
            candidate_type="claim",
            descriptor_refs=[],
            statement=_statement("这是一个跨 Reader successor 的稳定结论。"),
        )
    ]
    historical_reader = _reader()
    current_reader = _reader(
        run_id="semrun_223e4567-e89b-42d3-a456-426614174000",
        manifest_sha256="e" * 64,
    )
    historical_bundle = _bundle(reading, drafts)
    current_bundle = _bundle(reading, drafts)
    historical_run_id = _MATERIALIZATION_RUN_ID
    current_run_id = "matrun_223e4567-e89b-42d3-a456-426614174000"
    _, historical_manifest_sha256 = _write_committed_materialization(
        runs_dir,
        authority,
        historical_reader,
        historical_bundle,
        historical_run_id,
    )
    current_materialized, current_manifest_sha256 = (
        _write_committed_materialization(
            runs_dir,
            authority,
            current_reader,
            current_bundle,
            current_run_id,
        )
    )
    (materializations / "current.json").write_bytes(
        candidate._canonical_file_bytes(
            {
                "manifest_sha256": historical_manifest_sha256,
                "run_id": historical_run_id,
                "schema_version": "gezhi.candidate_materialization_current.v1",
            }
        )
    )
    _allow_plain_test_filesystem(monkeypatch)

    def load_historical_bundle(
        supplied_authority: ActiveSourceAuthorityV1,
        supplied_canonical: CurrentCanonicalAssetV1,
        supplied_reader: ReaderAdvanceV1,
        *,
        require_current: bool,
    ) -> candidate._ReaderBundleV1:
        assert supplied_authority == authority
        assert supplied_canonical == _canonical()
        assert not require_current
        assert supplied_reader.run_id == historical_reader.run_id
        return historical_bundle

    monkeypatch.setattr(
        candidate,
        "_reader_bundle_for_run",
        load_historical_bundle,
    )
    recovered = candidate._load_or_recover_current(
        materializations,
        runs_dir,
        authority,
        _canonical(),
        current_reader,
        current_bundle,
        cast(ValidatedDataRootV1, object()),
    )

    assert recovered == candidate.CandidateMaterializationAdvanceV1(
        advanced=True,
        run_id=current_run_id,
        manifest_sha256=current_manifest_sha256,
        pending_candidate_ids=current_materialized.pending_candidate_ids,
    )
    assert json.loads((materializations / "current.json").read_bytes())[
        "run_id"
    ] == current_run_id


@pytest.mark.parametrize("identity", [_same_full_hash, _same_short_id])
def test_cross_successor_candidate_collision_fails_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    identity: Callable[[bytes], str],
) -> None:
    source_dir = tmp_path / "source"
    authority = _authority(source_dir)
    runs_dir = source_dir / "semantic" / "materializations" / "runs"
    runs_dir.mkdir(parents=True)
    reading = _reading_result(with_descriptors=False)
    historical_draft = CandidateDraftV1(
        candidate_type="claim",
        descriptor_refs=[],
        statement=_statement("第一条不同的结论。"),
    )
    current_draft = CandidateDraftV1(
        candidate_type="claim",
        descriptor_refs=[],
        statement=_statement("第二条不同的结论。"),
    )
    _allow_plain_test_filesystem(monkeypatch)
    monkeypatch.setattr(candidate, "_content_sha256", identity)
    _write_committed_materialization(
        runs_dir,
        authority,
        _reader(),
        _bundle(reading, [historical_draft]),
        _MATERIALIZATION_RUN_ID,
    )
    current = candidate._materialized_documents(
        authority,
        _canonical(),
        _reader(),
        _bundle(reading, [current_draft]),
        "matrun_223e4567-e89b-42d3-a456-426614174000",
    )

    with pytest.raises(
        candidate.CandidateMaterializationStageStoppedV1
    ) as stopped:
        candidate._ensure_no_historical_identity_conflicts(
            runs_dir,
            authority,
            current,
        )
    assert stopped.value.outcome == "failed"
    assert stopped.value.reason == "candidate_validation_failed"
