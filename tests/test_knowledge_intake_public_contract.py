from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest
from support.reviewed_handoff_witness_v1 import (
    ACCEPT_CANDIDATES_V1,
    ACCEPT_MANIFEST_V1,
    CANDIDATE_ID_V1,
    HANDOFF_ID_ACCEPT_V1,
    HANDOFF_ID_WITHDRAW_V1,
    PAYLOAD_SHA256_V1,
    WITHDRAW_CANDIDATES_V1,
    WITHDRAW_MANIFEST_V1,
)


def _canonical_file_bytes(value: object) -> bytes:
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


def _manifest_for_candidates(template: bytes, candidates_bytes: bytes) -> bytes:
    manifest = json.loads(template)
    manifest["candidates_sha256"] = hashlib.sha256(candidates_bytes).hexdigest()
    return _canonical_file_bytes(manifest)


def _rebind_accept_handoff(
    record: dict[str, object],
    *,
    manifest_template: bytes = ACCEPT_MANIFEST_V1,
) -> tuple[bytes, bytes]:
    candidate = record["candidate"]
    assert type(candidate) is dict
    payload = candidate["payload"]
    payload_sha256 = hashlib.sha256(_canonical_file_bytes(payload)[:-1]).hexdigest()
    candidate_id = "cand_" + payload_sha256[:24]
    candidate["candidate_id"] = candidate_id
    candidate["payload_sha256"] = payload_sha256
    receipt = record["review_receipt"]
    assert type(receipt) is dict
    identity = {
        "action": "accept",
        "candidate_id": candidate_id,
        "payload_sha256": payload_sha256,
        "review_revision": receipt["review_revision"],
        "schema_version": "gezhi.reviewed_handoff_identity.v1",
    }
    candidates_bytes = _canonical_file_bytes(record)
    manifest = json.loads(manifest_template)
    manifest["candidates_sha256"] = hashlib.sha256(candidates_bytes).hexdigest()
    manifest["handoff_id"] = "hnd_" + hashlib.sha256(
        _canonical_file_bytes(identity)[:-1]
    ).hexdigest()[:24]
    return _canonical_file_bytes(manifest), candidates_bytes


def _rebind_withdraw_handoff(
    record: dict[str, object],
    *,
    manifest_template: bytes,
) -> tuple[bytes, bytes]:
    receipt = record["review_receipt"]
    assert type(receipt) is dict
    identity = {
        "action": "withdraw",
        "candidate_id": record["candidate_id"],
        "payload_sha256": record["payload_sha256"],
        "review_revision": receipt["review_revision"],
        "schema_version": "gezhi.reviewed_handoff_identity.v1",
    }
    candidates_bytes = _canonical_file_bytes(record)
    manifest = json.loads(manifest_template)
    manifest["candidates_sha256"] = hashlib.sha256(candidates_bytes).hexdigest()
    manifest["handoff_id"] = "hnd_" + hashlib.sha256(
        _canonical_file_bytes(identity)[:-1]
    ).hexdigest()[:24]
    return _canonical_file_bytes(manifest), candidates_bytes


def _valid_review_sequence_v1() -> tuple[
    tuple[bytes, bytes],
    tuple[bytes, bytes],
    tuple[bytes, bytes],
]:
    accept_record = json.loads(ACCEPT_CANDIDATES_V1)
    statement_pointer = accept_record["candidate"]["payload"]["statement"][
        "evidence_pointers"
    ][0]
    evidence_pointer = accept_record["evidence_snapshots"][0]["pointer"]
    statement_pointer["block_id"] = "blk_111111111111111111111111"
    evidence_pointer["block_id"] = "blk_111111111111111111111111"

    manifest = json.loads(ACCEPT_MANIFEST_V1)
    canonical_run_id = "canrun_123e4567-e89b-42d3-a456-426614174000"
    semantic_run_id = "semrun_123e4567-e89b-42d3-a456-426614174001"
    manifest["canonical_run_id"] = canonical_run_id
    manifest["provenance"] = {
        "canonical_run_id": canonical_run_id,
        "semantic_run_id": semantic_run_id,
    }
    manifest_template = _canonical_file_bytes(manifest)
    accepted = _rebind_accept_handoff(
        accept_record,
        manifest_template=manifest_template,
    )

    accepted_record = json.loads(accepted[1])
    candidate = accepted_record["candidate"]
    withdraw_record = json.loads(WITHDRAW_CANDIDATES_V1)
    withdraw_record["candidate_id"] = candidate["candidate_id"]
    withdraw_record["payload_sha256"] = candidate["payload_sha256"]
    withdrawn = _rebind_withdraw_handoff(
        withdraw_record,
        manifest_template=accepted[0],
    )

    reaccept_record = json.loads(accepted[1])
    reaccept_record["review_receipt"]["review_revision"] = 3
    reaccepted = _rebind_accept_handoff(
        reaccept_record,
        manifest_template=accepted[0],
    )
    return accepted, withdrawn, reaccepted


VALID_ACCEPT_V1, VALID_WITHDRAW_V1, VALID_REACCEPT_V1 = _valid_review_sequence_v1()


@pytest.fixture
def empty_knowledge_root() -> Iterator[Path]:
    container = Path(r"E:\Gezhi\data")
    container.mkdir(parents=True, exist_ok=True)
    base = container / ("t18-" + uuid.uuid4().hex[:12])
    knowledge_root = base / "knowledge"
    knowledge_root.mkdir(parents=True)
    try:
        yield knowledge_root
    finally:
        resolved = base.resolve(strict=True)
        assert resolved.parent == container.resolve(strict=True)
        assert resolved.name.startswith("t18-")
        shutil.rmtree(resolved)


def test_accept_witness_is_applied_to_an_empty_candidate_registry(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    knowledge_root = empty_knowledge_root
    intake = KnowledgeIntakeAdapterV1(str(knowledge_root))

    verdict = intake.apply(
        ReviewedHandoffBytesV1(
            manifest_bytes=ACCEPT_MANIFEST_V1,
            candidates_bytes=ACCEPT_CANDIDATES_V1,
        )
    )

    assert verdict == IntakeAppliedV1(
        intake_status="active",
        disposition="applied",
    )
    import_root = knowledge_root / "imports" / HANDOFF_ID_ACCEPT_V1
    assert (import_root / "manifest.json").read_bytes() == ACCEPT_MANIFEST_V1
    assert (import_root / "candidates.jsonl").read_bytes() == ACCEPT_CANDIDATES_V1

    registry_path = knowledge_root / "registry.sqlite3"
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute("PRAGMA application_id").fetchone() == (0x475A4831,)
        assert registry.execute("PRAGMA user_version").fetchone() == (1,)
        assert registry.execute(
            "SELECT schema_version, generation FROM registry_meta"
        ).fetchone() == ("gezhi.candidate_registry.v1", 1)
        assert registry.execute(
            "SELECT candidate_id, payload_sha256, promotion_status "
            "FROM candidate_content"
        ).fetchone() == (
            CANDIDATE_ID_V1,
            PAYLOAD_SHA256_V1,
            "not_promoted",
        )
        assert registry.execute(
            "SELECT review_revision, review_status, intake_status, "
            "status_handoff_id FROM candidate_current"
        ).fetchone() == (1, "accepted", "active", HANDOFF_ID_ACCEPT_V1)
        physical_tables = {
            row[0]
            for row in registry.execute(
                "SELECT name FROM sqlite_schema "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert {
            name
            for name in physical_tables
            if not name.startswith("candidate_search_")
            and name != "registry_search_meta"
        } == {
            "candidate_content",
            "candidate_current",
            "handoff_revisions",
            "registry_meta",
        }
        assert {
            "candidate_search_unicode",
            "candidate_search_trigram",
            "registry_search_meta",
        } <= physical_tables
        assert registry.execute(
            "SELECT schema_version, registry_generation "
            "FROM registry_search_meta"
        ).fetchone() == ("gezhi.candidate_search_projection.v1", 1)


def test_exact_accept_replay_is_unchanged_without_duplicate_candidate(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    handoff = ReviewedHandoffBytesV1(
        manifest_bytes=ACCEPT_MANIFEST_V1,
        candidates_bytes=ACCEPT_CANDIDATES_V1,
    )

    assert intake.apply(handoff) == IntakeAppliedV1("active", "applied")
    assert intake.apply(handoff) == IntakeAppliedV1("active", "unchanged")

    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute(
            "SELECT generation FROM registry_meta"
        ).fetchone() == (1,)
        assert registry.execute("SELECT count(*) FROM candidate_content").fetchone() == (
            1,
        )
        assert registry.execute("SELECT count(*) FROM handoff_revisions").fetchone() == (
            1,
        )


def test_withdraw_preserves_candidate_history_but_removes_active_status(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    accepted = ReviewedHandoffBytesV1(
        manifest_bytes=ACCEPT_MANIFEST_V1,
        candidates_bytes=ACCEPT_CANDIDATES_V1,
    )
    withdrawn = ReviewedHandoffBytesV1(
        manifest_bytes=WITHDRAW_MANIFEST_V1,
        candidates_bytes=WITHDRAW_CANDIDATES_V1,
    )

    assert intake.apply(accepted) == IntakeAppliedV1("active", "applied")
    assert intake.apply(withdrawn) == IntakeAppliedV1("withdrawn", "applied")

    import_root = empty_knowledge_root / "imports" / HANDOFF_ID_WITHDRAW_V1
    assert (import_root / "manifest.json").read_bytes() == WITHDRAW_MANIFEST_V1
    assert (import_root / "candidates.jsonl").read_bytes() == WITHDRAW_CANDIDATES_V1
    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute(
            "SELECT review_revision, review_status, intake_status, "
            "status_handoff_id FROM candidate_current"
        ).fetchone() == (2, "rejected", "withdrawn", HANDOFF_ID_WITHDRAW_V1)
        assert registry.execute("SELECT count(*) FROM candidate_content").fetchone() == (
            1,
        )
        assert registry.execute("SELECT count(*) FROM handoff_revisions").fetchone() == (
            2,
        )
        assert registry.execute(
            "SELECT generation FROM registry_meta"
        ).fetchone() == (2,)


def test_higher_accept_revision_reactivates_the_same_candidate(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    for manifest_bytes, candidates_bytes, expected_status in (
        (*VALID_ACCEPT_V1, "active"),
        (*VALID_WITHDRAW_V1, "withdrawn"),
        (*VALID_REACCEPT_V1, "active"),
    ):
        assert intake.apply(
            ReviewedHandoffBytesV1(
                manifest_bytes=manifest_bytes,
                candidates_bytes=candidates_bytes,
            )
        ) == IntakeAppliedV1(expected_status, "applied")

    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        reaccept_handoff_id = json.loads(VALID_REACCEPT_V1[0])["handoff_id"]
        assert registry.execute(
            "SELECT review_revision, review_status, intake_status, "
            "status_handoff_id FROM candidate_current"
        ).fetchone() == (3, "accepted", "active", reaccept_handoff_id)
        assert registry.execute("SELECT count(*) FROM candidate_content").fetchone() == (
            1,
        )
        assert registry.execute("SELECT count(*) FROM handoff_revisions").fetchone() == (
            3,
        )
        assert registry.execute(
            "SELECT generation FROM registry_meta"
        ).fetchone() == (3,)


def test_declared_v1_registry_with_schema_drift_is_not_repaired(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(sqlite3.connect(registry_path)) as registry:
        registry.execute("PRAGMA application_id = 0x475A4831")
        registry.execute("PRAGMA user_version = 1")
        registry.execute("CREATE TABLE wrong_schema(value TEXT)")
        registry.commit()

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(
            manifest_bytes=ACCEPT_MANIFEST_V1,
            candidates_bytes=ACCEPT_CANDIDATES_V1,
        )
    )

    assert verdict == IntakeFailedV1("registry_conflict")
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table'"
        ).fetchall() == [("wrong_schema",)]
    import_root = empty_knowledge_root / "imports" / HANDOFF_ID_ACCEPT_V1
    assert (import_root / "manifest.json").read_bytes() == ACCEPT_MANIFEST_V1
    assert (import_root / "candidates.jsonl").read_bytes() == ACCEPT_CANDIDATES_V1


def test_empty_v0_registry_is_the_supported_migration_baseline(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(sqlite3.connect(registry_path)) as registry:
        registry.commit()

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1)
    )

    assert verdict == IntakeAppliedV1("active", "applied")
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute("PRAGMA application_id").fetchone() == (0x475A4831,)
        assert registry.execute("PRAGMA user_version").fetchone() == (1,)


def test_future_registry_version_is_not_downgraded_or_repaired(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(sqlite3.connect(registry_path)) as registry:
        registry.execute("PRAGMA application_id = 0x475A4831")
        registry.execute("PRAGMA user_version = 2")
        registry.commit()

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1)
    )

    assert verdict == IntakeFailedV1("registry_conflict")
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute("PRAGMA application_id").fetchone() == (0x475A4831,)
        assert registry.execute("PRAGMA user_version").fetchone() == (2,)
        assert registry.execute(
            "SELECT name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall() == []


def test_replaying_historical_accept_does_not_roll_back_withdrawn_current(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    accepted = ReviewedHandoffBytesV1(
        manifest_bytes=ACCEPT_MANIFEST_V1,
        candidates_bytes=ACCEPT_CANDIDATES_V1,
    )
    withdrawn = ReviewedHandoffBytesV1(
        manifest_bytes=WITHDRAW_MANIFEST_V1,
        candidates_bytes=WITHDRAW_CANDIDATES_V1,
    )
    assert intake.apply(accepted) == IntakeAppliedV1("active", "applied")
    assert intake.apply(withdrawn) == IntakeAppliedV1("withdrawn", "applied")

    assert intake.apply(accepted) == IntakeAppliedV1("active", "unchanged")

    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute(
            "SELECT review_revision, review_status, intake_status, "
            "status_handoff_id FROM candidate_current"
        ).fetchone() == (2, "rejected", "withdrawn", HANDOFF_ID_WITHDRAW_V1)
        assert registry.execute(
            "SELECT generation FROM registry_meta"
        ).fetchone() == (2,)


def test_exact_replay_rebuilds_missing_current_projection_from_history(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    accepted = ReviewedHandoffBytesV1(
        manifest_bytes=ACCEPT_MANIFEST_V1,
        candidates_bytes=ACCEPT_CANDIDATES_V1,
    )
    withdrawn = ReviewedHandoffBytesV1(
        manifest_bytes=WITHDRAW_MANIFEST_V1,
        candidates_bytes=WITHDRAW_CANDIDATES_V1,
    )
    assert intake.apply(accepted) == IntakeAppliedV1("active", "applied")
    assert intake.apply(withdrawn) == IntakeAppliedV1("withdrawn", "applied")
    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(sqlite3.connect(registry_path)) as registry:
        registry.execute("PRAGMA foreign_keys = ON")
        registry.execute("DELETE FROM candidate_current")
        registry.commit()

    assert intake.apply(withdrawn) == IntakeAppliedV1("withdrawn", "unchanged")

    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute(
            "SELECT review_revision, review_status, intake_status, "
            "status_handoff_id FROM candidate_current"
        ).fetchone() == (2, "rejected", "withdrawn", HANDOFF_ID_WITHDRAW_V1)
        assert registry.execute(
            "SELECT generation FROM registry_meta"
        ).fetchone() == (2,)


def test_registry_writer_contention_blocks_before_publishing_evidence(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeBlockedV1, ReviewedHandoffBytesV1
    from gezhi._windows_data_root import open_validated_data_root_v1
    from gezhi._windows_ownership import try_acquire_knowledge_registry_writer_v1

    with open_validated_data_root_v1(str(empty_knowledge_root)) as root:
        root_identity = root.inspection.identity
        assert root_identity is not None
        owner = try_acquire_knowledge_registry_writer_v1(root_identity)
        assert owner is not None
        with owner:
            verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
                ReviewedHandoffBytesV1(
                    manifest_bytes=ACCEPT_MANIFEST_V1,
                    candidates_bytes=ACCEPT_CANDIDATES_V1,
                )
            )

    assert verdict == IntakeBlockedV1("registry_busy")
    assert not (empty_knowledge_root / "imports").exists()
    assert not (empty_knowledge_root / "registry.sqlite3").exists()


def test_external_sqlite_writer_is_classified_as_registry_busy(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import (
        IntakeAppliedV1,
        IntakeBlockedV1,
        ReviewedHandoffBytesV1,
    )

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    accepted = ReviewedHandoffBytesV1(
        manifest_bytes=ACCEPT_MANIFEST_V1,
        candidates_bytes=ACCEPT_CANDIDATES_V1,
    )
    withdrawn = ReviewedHandoffBytesV1(
        manifest_bytes=WITHDRAW_MANIFEST_V1,
        candidates_bytes=WITHDRAW_CANDIDATES_V1,
    )
    assert intake.apply(accepted) == IntakeAppliedV1("active", "applied")
    registry_path = empty_knowledge_root / "registry.sqlite3"
    blocker = sqlite3.connect(registry_path, isolation_level=None)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        verdict = intake.apply(withdrawn)
    finally:
        blocker.rollback()
        blocker.close()

    assert verdict == IntakeBlockedV1("registry_busy")
    import_root = empty_knowledge_root / "imports" / HANDOFF_ID_WITHDRAW_V1
    assert (import_root / "manifest.json").read_bytes() == WITHDRAW_MANIFEST_V1
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute(
            "SELECT review_revision, intake_status FROM candidate_current"
        ).fetchone() == (1, "active")
        assert registry.execute("SELECT count(*) FROM handoff_revisions").fetchone() == (
            1,
        )


def test_complete_staged_evidence_is_recovered_before_registry_apply(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    stage = (
        empty_knowledge_root
        / "imports"
        / ".staging"
        / HANDOFF_ID_ACCEPT_V1
    )
    stage.mkdir(parents=True)
    (stage / "candidates.jsonl").write_bytes(ACCEPT_CANDIDATES_V1)
    (stage / "manifest.json").write_bytes(ACCEPT_MANIFEST_V1)

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(
            manifest_bytes=ACCEPT_MANIFEST_V1,
            candidates_bytes=ACCEPT_CANDIDATES_V1,
        )
    )

    assert verdict == IntakeAppliedV1("active", "applied")
    assert not stage.exists()
    formal = empty_knowledge_root / "imports" / HANDOFF_ID_ACCEPT_V1
    assert (formal / "manifest.json").read_bytes() == ACCEPT_MANIFEST_V1
    assert (formal / "candidates.jsonl").read_bytes() == ACCEPT_CANDIDATES_V1


def test_tampered_historical_import_evidence_blocks_later_revision(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import (
        IntakeAppliedV1,
        IntakeFailedV1,
        ReviewedHandoffBytesV1,
    )

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    accepted = ReviewedHandoffBytesV1(
        manifest_bytes=ACCEPT_MANIFEST_V1,
        candidates_bytes=ACCEPT_CANDIDATES_V1,
    )
    withdrawn = ReviewedHandoffBytesV1(
        manifest_bytes=WITHDRAW_MANIFEST_V1,
        candidates_bytes=WITHDRAW_CANDIDATES_V1,
    )
    assert intake.apply(accepted) == IntakeAppliedV1("active", "applied")
    accept_evidence = empty_knowledge_root / "imports" / HANDOFF_ID_ACCEPT_V1
    (accept_evidence / "manifest.json").write_bytes(b"tampered\n")

    assert intake.apply(withdrawn) == IntakeFailedV1("registry_conflict")

    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute(
            "SELECT review_revision, intake_status FROM candidate_current"
        ).fetchone() == (1, "active")
        assert registry.execute("SELECT count(*) FROM handoff_revisions").fetchone() == (
            1,
        )


def test_lost_knowledge_root_proof_uses_the_specific_typed_failure(
    empty_knowledge_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gezhi._knowledge_intake as knowledge_intake
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    def lose_root_proof(_root: object) -> None:
        raise knowledge_intake._DataRootIntegrityLostV1(  # type: ignore[attr-defined]
            "injected Knowledge root drift"
        )

    monkeypatch.setattr(knowledge_intake, "_root_checkpoint", lose_root_proof)

    verdict = knowledge_intake.KnowledgeIntakeAdapterV1(
        str(empty_knowledge_root)
    ).apply(
        ReviewedHandoffBytesV1(
            manifest_bytes=ACCEPT_MANIFEST_V1,
            candidates_bytes=ACCEPT_CANDIDATES_V1,
        )
    )

    assert verdict == IntakeFailedV1(
        "data_root_integrity_lost",
        "knowledge",
    )
    assert not (empty_knowledge_root / "imports").exists()
    assert not (empty_knowledge_root / "registry.sqlite3").exists()


def test_withdraw_before_accept_is_rejected_without_guessing_candidate_content(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(
            manifest_bytes=WITHDRAW_MANIFEST_V1,
            candidates_bytes=WITHDRAW_CANDIDATES_V1,
        )
    )

    assert verdict == IntakeFailedV1("revision_conflict")
    evidence = empty_knowledge_root / "imports" / HANDOFF_ID_WITHDRAW_V1
    assert (evidence / "manifest.json").read_bytes() == WITHDRAW_MANIFEST_V1
    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute(
            "SELECT generation FROM registry_meta"
        ).fetchone() == (0,)
        assert registry.execute("SELECT count(*) FROM candidate_content").fetchone() == (
            0,
        )
        assert registry.execute("SELECT count(*) FROM handoff_revisions").fetchone() == (
            0,
        )


def test_older_revision_after_newer_accept_is_rejected_without_rollback(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import (
        IntakeAppliedV1,
        IntakeFailedV1,
        ReviewedHandoffBytesV1,
    )

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    accepted = ReviewedHandoffBytesV1(*VALID_ACCEPT_V1)
    reaccepted = ReviewedHandoffBytesV1(
        *VALID_REACCEPT_V1,
    )
    older_withdraw = ReviewedHandoffBytesV1(
        *VALID_WITHDRAW_V1,
    )
    assert intake.apply(accepted) == IntakeAppliedV1("active", "applied")
    assert intake.apply(reaccepted) == IntakeAppliedV1("active", "applied")

    assert intake.apply(older_withdraw) == IntakeFailedV1("revision_conflict")

    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute(
            "SELECT review_revision, intake_status FROM candidate_current"
        ).fetchone() == (3, "active")
        assert registry.execute("SELECT count(*) FROM handoff_revisions").fetchone() == (
            2,
        )
        assert registry.execute(
            "SELECT generation FROM registry_meta"
        ).fetchone() == (2,)


def test_same_handoff_identity_with_different_bytes_is_revision_conflict(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import (
        IntakeAppliedV1,
        IntakeFailedV1,
        ReviewedHandoffBytesV1,
    )

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    accepted = ReviewedHandoffBytesV1(*VALID_ACCEPT_V1)
    withdrawn = ReviewedHandoffBytesV1(*VALID_WITHDRAW_V1)
    assert intake.apply(accepted) == IntakeAppliedV1("active", "applied")
    assert intake.apply(withdrawn) == IntakeAppliedV1("withdrawn", "applied")

    deferred_record = json.loads(VALID_WITHDRAW_V1[1])
    deferred_record["review_receipt"]["review_status"] = "deferred"
    deferred_candidates = _canonical_file_bytes(deferred_record)
    deferred_manifest = _manifest_for_candidates(
        VALID_WITHDRAW_V1[0],
        deferred_candidates,
    )

    assert intake.apply(
        ReviewedHandoffBytesV1(deferred_manifest, deferred_candidates)
    ) == IntakeFailedV1("revision_conflict")
    valid_withdraw_manifest = json.loads(VALID_WITHDRAW_V1[0])
    evidence = (
        empty_knowledge_root
        / "imports"
        / valid_withdraw_manifest["handoff_id"]
    )
    assert (evidence / "manifest.json").read_bytes() == VALID_WITHDRAW_V1[0]
    assert (evidence / "candidates.jsonl").read_bytes() == VALID_WITHDRAW_V1[1]


def test_closed_schema_handoff_is_rejected_before_any_side_effect(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    record = json.loads(ACCEPT_CANDIDATES_V1)
    record["unexpected"] = True
    candidates_bytes = _canonical_file_bytes(record)
    manifest_bytes = _manifest_for_candidates(ACCEPT_MANIFEST_V1, candidates_bytes)

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(manifest_bytes, candidates_bytes)
    )

    assert verdict == IntakeFailedV1("import_failed")
    assert not (empty_knowledge_root / "imports").exists()
    assert not (empty_knowledge_root / "registry.sqlite3").exists()


def test_partial_staging_is_preserved_and_not_guessed(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    stage = empty_knowledge_root / "imports" / ".staging" / HANDOFF_ID_ACCEPT_V1
    stage.mkdir(parents=True)
    partial = ACCEPT_MANIFEST_V1
    (stage / "manifest.json").write_bytes(partial)

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1)
    )

    assert verdict == IntakeFailedV1("import_failed")
    assert (stage / "manifest.json").read_bytes() == partial
    assert not (stage / "candidates.jsonl").exists()
    assert not (empty_knowledge_root / "imports" / HANDOFF_ID_ACCEPT_V1).exists()
    assert not (empty_knowledge_root / "registry.sqlite3").exists()


def test_existing_reparse_import_target_is_a_deterministic_import_failure(
    empty_knowledge_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gezhi._knowledge_intake as knowledge_intake
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    formal = empty_knowledge_root / "imports" / HANDOFF_ID_ACCEPT_V1
    formal.mkdir(parents=True)
    real_open = knowledge_intake.open_validated_data_root_v1

    def reject_formal_as_reparse(value: str):
        if Path(value) == formal:
            raise knowledge_intake.DataRootOpenErrorV1("unsafe")
        return real_open(value)

    monkeypatch.setattr(
        knowledge_intake,
        "open_validated_data_root_v1",
        reject_formal_as_reparse,
    )

    verdict = knowledge_intake.KnowledgeIntakeAdapterV1(
        str(empty_knowledge_root)
    ).apply(ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1))

    assert verdict == IntakeFailedV1("import_failed")
    assert formal.is_dir()
    assert list(formal.iterdir()) == []
    assert not (empty_knowledge_root / "registry.sqlite3").exists()


def test_lost_directory_rename_ack_is_resolved_by_observing_exact_evidence(
    empty_knowledge_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gezhi._knowledge_intake as knowledge_intake
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    real_rename = os.rename

    def rename_then_lose_ack(source: object, target: object) -> None:
        real_rename(source, target)
        if (
            Path(source).name == HANDOFF_ID_ACCEPT_V1
            and Path(target).name == HANDOFF_ID_ACCEPT_V1
        ):
            raise OSError("injected directory rename acknowledgement loss")

    monkeypatch.setattr(knowledge_intake.os, "rename", rename_then_lose_ack)

    verdict = knowledge_intake.KnowledgeIntakeAdapterV1(
        str(empty_knowledge_root)
    ).apply(ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1))

    assert verdict == IntakeAppliedV1("active", "applied")
    formal = empty_knowledge_root / "imports" / HANDOFF_ID_ACCEPT_V1
    assert (formal / "manifest.json").read_bytes() == ACCEPT_MANIFEST_V1
    assert (formal / "candidates.jsonl").read_bytes() == ACCEPT_CANDIDATES_V1


def test_unresolved_directory_rename_is_recoverable_with_the_same_handoff(
    empty_knowledge_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gezhi._knowledge_intake as knowledge_intake
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    handoff = ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1)
    real_rename = os.rename

    def lose_directory_rename(source: object, target: object) -> None:
        if (
            Path(source).name == HANDOFF_ID_ACCEPT_V1
            and Path(target).name == HANDOFF_ID_ACCEPT_V1
        ):
            raise OSError("injected directory rename failure")
        real_rename(source, target)

    with monkeypatch.context() as fault:
        fault.setattr(knowledge_intake.os, "rename", lose_directory_rename)
        with pytest.raises(RuntimeError, match="directory commit is uncertain"):
            knowledge_intake.KnowledgeIntakeAdapterV1(
                str(empty_knowledge_root)
            ).apply(handoff)

    stage = empty_knowledge_root / "imports" / ".staging" / HANDOFF_ID_ACCEPT_V1
    assert (stage / "manifest.json").read_bytes() == ACCEPT_MANIFEST_V1
    assert (stage / "candidates.jsonl").read_bytes() == ACCEPT_CANDIDATES_V1
    assert not (empty_knowledge_root / "registry.sqlite3").exists()

    assert knowledge_intake.KnowledgeIntakeAdapterV1(
        str(empty_knowledge_root)
    ).apply(handoff) == IntakeAppliedV1("active", "applied")
    assert not stage.exists()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("doi", "https://doi.org/10.1234/example"),
        ("arxiv_id", "arXiv:2301.00001"),
    ],
)
def test_citation_identifiers_are_independently_validated_before_side_effects(
    empty_knowledge_root: Path,
    field: str,
    invalid_value: str,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    record = json.loads(ACCEPT_CANDIDATES_V1)
    record["citation"][field] = invalid_value
    candidates_bytes = _canonical_file_bytes(record)
    manifest_bytes = _manifest_for_candidates(ACCEPT_MANIFEST_V1, candidates_bytes)

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(manifest_bytes, candidates_bytes)
    )

    assert verdict == IntakeFailedV1("import_failed")
    assert list(empty_knowledge_root.iterdir()) == []


def test_provenance_run_identifiers_are_independently_validated(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    manifest = json.loads(ACCEPT_MANIFEST_V1)
    manifest["canonical_run_id"] = "../canonical"
    manifest["provenance"]["canonical_run_id"] = "../canonical"
    manifest["provenance"]["semantic_run_id"] = "../semantic"
    manifest_bytes = _canonical_file_bytes(manifest)

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(manifest_bytes, ACCEPT_CANDIDATES_V1)
    )

    assert verdict == IntakeFailedV1("import_failed")
    assert list(empty_knowledge_root.iterdir()) == []


def test_witness_only_identifiers_are_not_reusable_in_reassembled_handoff(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    record = json.loads(ACCEPT_CANDIDATES_V1)
    record["candidate"]["payload"]["statement"]["text"] = "重组后的结论"
    manifest_bytes, candidates_bytes = _rebind_accept_handoff(record)

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(manifest_bytes, candidates_bytes)
    )

    assert verdict == IntakeFailedV1("import_failed")
    assert list(empty_knowledge_root.iterdir()) == []


def test_evidence_block_identifier_is_independently_validated(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    record = json.loads(ACCEPT_CANDIDATES_V1)
    pointer = record["candidate"]["payload"]["statement"]["evidence_pointers"][0]
    pointer["block_id"] = "../block"
    record["evidence_snapshots"][0]["pointer"]["block_id"] = "../block"
    manifest_bytes, candidates_bytes = _rebind_accept_handoff(record)

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(manifest_bytes, candidates_bytes)
    )

    assert verdict == IntakeFailedV1("import_failed")
    assert list(empty_knowledge_root.iterdir()) == []


def test_study_descriptor_evidence_pointers_must_use_frozen_order(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    record = json.loads(ACCEPT_CANDIDATES_V1)
    canonical_sha256 = record["candidate"]["payload"][
        "canonical_content_sha256"
    ]
    first = {
        "block_id": "blk_" + "a" * 24,
        "canonical_content_sha256": canonical_sha256,
        "schema_version": "gezhi.evidence_pointer.v1",
    }
    second = {
        "block_id": "blk_" + "b" * 24,
        "canonical_content_sha256": canonical_sha256,
        "schema_version": "gezhi.evidence_pointer.v1",
    }
    descriptor_payload = {
        "kind": "object",
        "schema_version": "gezhi.descriptor_payload.v1",
        "value": {
            "evidence_pointers": [second, first],
            "label": "示例对象",
            "source_terms": [],
        },
    }
    descriptor_sha256 = hashlib.sha256(
        _canonical_file_bytes(descriptor_payload)[:-1]
    ).hexdigest()
    reference = {
        "descriptor_id": "desc_" + descriptor_sha256[:24],
        "kind": "object",
        "payload_sha256": descriptor_sha256,
        "schema_version": "gezhi.descriptor_reference.v1",
    }
    record["candidate"]["payload"]["descriptor_refs"] = [reference]
    record["descriptor_snapshots"] = [
        {"payload": descriptor_payload, "reference": reference}
    ]
    statement_pointer = record["candidate"]["payload"]["statement"][
        "evidence_pointers"
    ][0]
    record["evidence_snapshots"] = [
        {
            "excerpt": "First descriptor evidence.",
            "page_index": None,
            "pointer": first,
        },
        {
            "excerpt": "Second descriptor evidence.",
            "page_index": None,
            "pointer": second,
        },
        {
            "excerpt": "Example evidence.",
            "page_index": None,
            "pointer": statement_pointer,
        },
    ]
    manifest_bytes, candidates_bytes = _rebind_accept_handoff(record)

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(manifest_bytes, candidates_bytes)
    )

    assert verdict == IntakeFailedV1("import_failed")
    assert list(empty_knowledge_root.iterdir()) == []


def test_registry_path_that_is_not_a_regular_file_is_unavailable(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeBlockedV1, ReviewedHandoffBytesV1

    registry_path = empty_knowledge_root / "registry.sqlite3"
    registry_path.mkdir()

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1)
    )

    assert verdict == IntakeBlockedV1("registry_unavailable")
    assert registry_path.is_dir()
    evidence = empty_knowledge_root / "imports" / HANDOFF_ID_ACCEPT_V1
    assert (evidence / "manifest.json").read_bytes() == ACCEPT_MANIFEST_V1


def test_non_sqlite_registry_is_a_registry_conflict(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    registry_path = empty_knowledge_root / "registry.sqlite3"
    registry_path.write_bytes(b"not a SQLite database\n")

    verdict = KnowledgeIntakeAdapterV1(str(empty_knowledge_root)).apply(
        ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1)
    )

    assert verdict == IntakeFailedV1("registry_conflict")
    assert registry_path.read_bytes() == b"not a SQLite database\n"


def test_schema_is_revalidated_inside_the_registry_write_transaction(
    empty_knowledge_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gezhi._knowledge_intake as knowledge_intake
    from gezhi._literature_review import IntakeFailedV1, ReviewedHandoffBytesV1

    real_bootstrap = knowledge_intake._bootstrap_registry

    def drift_after_bootstrap(connection: sqlite3.Connection) -> None:
        real_bootstrap(connection)
        connection.execute("CREATE TABLE injected_schema_drift(value TEXT)")

    monkeypatch.setattr(
        knowledge_intake,
        "_bootstrap_registry",
        drift_after_bootstrap,
    )

    verdict = knowledge_intake.KnowledgeIntakeAdapterV1(
        str(empty_knowledge_root)
    ).apply(ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1))

    assert verdict == IntakeFailedV1("registry_conflict")
    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute("SELECT count(*) FROM candidate_content").fetchone() == (
            0,
        )


@pytest.mark.parametrize(
    ("column", "tampered_value"),
    [
        ("candidate_json", b"{}"),
        ("citation_json", b"{}"),
        ("descriptor_snapshots_json", b"[ ]"),
        ("evidence_snapshots_json", b"[]"),
        ("content_handoff_id", "hnd_" + "0" * 24),
        ("content_manifest_sha256", "0" * 64),
        ("content_candidates_sha256", "0" * 64),
    ],
)
def test_withdraw_replay_rejects_tampered_accepted_content_and_bindings(
    empty_knowledge_root: Path,
    column: str,
    tampered_value: bytes | str,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import (
        IntakeAppliedV1,
        IntakeFailedV1,
        ReviewedHandoffBytesV1,
    )

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    accepted = ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1)
    withdrawn = ReviewedHandoffBytesV1(
        WITHDRAW_MANIFEST_V1,
        WITHDRAW_CANDIDATES_V1,
    )
    assert intake.apply(accepted) == IntakeAppliedV1("active", "applied")
    assert intake.apply(withdrawn) == IntakeAppliedV1("withdrawn", "applied")
    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(sqlite3.connect(registry_path)) as registry:
        registry.execute(
            f"UPDATE candidate_content SET {column} = ?",
            (tampered_value,),
        )
        registry.commit()

    assert intake.apply(withdrawn) == IntakeFailedV1("registry_conflict")


def test_withdraw_history_remains_bound_to_first_accept_content_identity(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import (
        IntakeAppliedV1,
        IntakeFailedV1,
        ReviewedHandoffBytesV1,
    )

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    accepted = ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1)
    withdrawn = ReviewedHandoffBytesV1(
        WITHDRAW_MANIFEST_V1,
        WITHDRAW_CANDIDATES_V1,
    )
    assert intake.apply(accepted) == IntakeAppliedV1("active", "applied")
    assert intake.apply(withdrawn) == IntakeAppliedV1("withdrawn", "applied")

    work_id = "wrk_223e4567-e89b-42d3-a456-426614174000"
    source_sha256 = "d" * 64
    source_id = "src_" + source_sha256[:24]
    canonical_sha256 = "e" * 64
    canonical_run_id = "canrun_223e4567-e89b-42d3-a456-426614174000"
    semantic_run_id = "semrun_323e4567-e89b-42d3-a456-426614174000"
    manifest = json.loads(WITHDRAW_MANIFEST_V1)
    manifest.update(
        {
            "canonical_content_sha256": canonical_sha256,
            "canonical_run_id": canonical_run_id,
            "provenance": {
                "canonical_run_id": canonical_run_id,
                "semantic_run_id": semantic_run_id,
            },
            "source_id": source_id,
            "source_sha256": source_sha256,
            "work_id": work_id,
        }
    )
    tampered_manifest_bytes = _canonical_file_bytes(manifest)
    evidence = empty_knowledge_root / "imports" / HANDOFF_ID_WITHDRAW_V1
    (evidence / "manifest.json").write_bytes(tampered_manifest_bytes)
    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(sqlite3.connect(registry_path)) as registry:
        registry.execute(
            """
            UPDATE handoff_revisions
            SET work_id = ?, source_id = ?, source_sha256 = ?,
                canonical_content_sha256 = ?, canonical_run_id = ?,
                semantic_run_id = ?, manifest_sha256 = ?
            WHERE handoff_id = ?
            """,
            (
                work_id,
                source_id,
                source_sha256,
                canonical_sha256,
                canonical_run_id,
                semantic_run_id,
                hashlib.sha256(tampered_manifest_bytes).hexdigest(),
                HANDOFF_ID_WITHDRAW_V1,
            ),
        )
        registry.commit()

    assert intake.apply(
        ReviewedHandoffBytesV1(
            tampered_manifest_bytes,
            WITHDRAW_CANDIDATES_V1,
        )
    ) == IntakeFailedV1("registry_conflict")


def test_registry_generation_must_match_committed_handoff_count(
    empty_knowledge_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import (
        IntakeAppliedV1,
        IntakeFailedV1,
        ReviewedHandoffBytesV1,
    )

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    handoff = ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1)
    assert intake.apply(handoff) == IntakeAppliedV1("active", "applied")
    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(sqlite3.connect(registry_path)) as registry:
        registry.execute("UPDATE registry_meta SET generation = 99")
        registry.commit()

    assert intake.apply(handoff) == IntakeFailedV1("registry_conflict")


@pytest.mark.parametrize("phase", ["migration", "accept", "withdraw"])
def test_registry_rollback_uncertainty_is_not_reported_as_handled(
    empty_knowledge_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    import gezhi._knowledge_intake as knowledge_intake
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    intake = knowledge_intake.KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    accepted = ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1)
    withdrawn = ReviewedHandoffBytesV1(
        WITHDRAW_MANIFEST_V1,
        WITHDRAW_CANDIDATES_V1,
    )
    if phase != "migration":
        assert intake.apply(accepted) == IntakeAppliedV1("active", "applied")

    real_connect = knowledge_intake.sqlite3.connect

    class RollbackFailsConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self.connection = connection

        def __getattr__(self, name: str) -> object:
            return getattr(self.connection, name)

        def execute(self, statement: str, *parameters: object) -> sqlite3.Cursor:
            normalized = " ".join(statement.split())
            if phase == "migration" and normalized.startswith(
                "CREATE TABLE registry_meta"
            ):
                raise sqlite3.IntegrityError("injected migration failure")
            if phase != "migration" and normalized.startswith(
                "INSERT INTO candidate_current"
            ):
                raise sqlite3.IntegrityError("injected transaction failure")
            return self.connection.execute(statement, *parameters)

        def rollback(self) -> None:
            raise sqlite3.OperationalError("injected rollback uncertainty")

    def connect_with_uncertain_rollback(
        *args: object,
        **kwargs: object,
    ) -> RollbackFailsConnection:
        return RollbackFailsConnection(real_connect(*args, **kwargs))

    target = accepted if phase != "withdraw" else withdrawn
    with monkeypatch.context() as fault:
        fault.setattr(
            knowledge_intake.sqlite3,
            "connect",
            connect_with_uncertain_rollback,
        )
        with pytest.raises(RuntimeError, match="rollback is uncertain"):
            intake.apply(target)


def test_registry_commit_uncertainty_is_recovered_by_exact_replay(
    empty_knowledge_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gezhi._knowledge_intake as knowledge_intake
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    intake = knowledge_intake.KnowledgeIntakeAdapterV1(str(empty_knowledge_root))
    accepted = ReviewedHandoffBytesV1(ACCEPT_MANIFEST_V1, ACCEPT_CANDIDATES_V1)
    withdrawn = ReviewedHandoffBytesV1(
        WITHDRAW_MANIFEST_V1,
        WITHDRAW_CANDIDATES_V1,
    )
    assert intake.apply(accepted) == IntakeAppliedV1("active", "applied")
    real_commit = knowledge_intake._commit_registry_transaction

    def commit_then_lose_ack(connection: sqlite3.Connection) -> None:
        real_commit(connection)
        raise knowledge_intake._CommitIndeterminateV1(  # type: ignore[attr-defined]
            "injected Registry commit acknowledgement loss"
        )

    with monkeypatch.context() as fault:
        fault.setattr(
            knowledge_intake,
            "_commit_registry_transaction",
            commit_then_lose_ack,
        )
        with pytest.raises(RuntimeError, match="acknowledgement loss"):
            intake.apply(withdrawn)

    assert intake.apply(withdrawn) == IntakeAppliedV1("withdrawn", "unchanged")
    registry_path = empty_knowledge_root / "registry.sqlite3"
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute("SELECT count(*) FROM handoff_revisions").fetchone() == (
            2,
        )
        assert registry.execute(
            "SELECT generation FROM registry_meta"
        ).fetchone() == (2,)
