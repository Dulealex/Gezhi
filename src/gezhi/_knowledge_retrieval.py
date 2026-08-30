from __future__ import annotations

import hashlib
import math
import re
import sqlite3
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Literal, TypeAlias, TypeGuard, cast

from gezhi._knowledge_intake import (
    _APPLICATION_ID,
    _MAX_INT64,
    _SCHEMA_VERSION,
    _USER_VERSION,
    _WITNESS_FILE_HASH_PAIRS,
    _DataRootIntegrityLostV1,
    _expected_base_schema_rows,
    _expected_schema_rows,
    _HandoffInvalidV1,
    _root_checkpoint,
    _schema_rows,
    _sqlite_is_busy,
    _validate_accept_record,
)
from gezhi._knowledge_registry import (
    SearchQueryInvalidV1,
    SearchTextV1,
    canonical_json_bytes_v1,
    decode_canonical_json_blob_v1,
    fts_literal_query_v1,
    search_document_fields_v1,
    validate_normalized_search_text_v1,
)
from gezhi._windows_data_root import (
    DataRootLifecycleErrorV1,
    DataRootOpenErrorV1,
    ValidatedDataRootV1,
    ValidatedFileV1,
)

_ALGORITHM_VERSION = "gezhi.fts5_dual_rrf_k12.v1"
_AUDIT_SCHEMA_VERSION = "gezhi.retrieval_audit.v1"
_SNAPSHOT_SCHEMA_VERSION = "gezhi.registry_retrieval_snapshot_identity.v1"
_VIEW_SCHEMA_VERSION = "gezhi.retrieval_view.v1"
_VIEW_LIMIT_BYTES = 262_144
_AUDIT_LIMIT_BYTES = 2_097_152
_ZERO_VIEW_SHA256 = "51aebe839e0caa991344efe4c0a19518b93a1d59aaa9bccbd1c6220a367641ec"
_CANDIDATE_ID = re.compile(r"^cand_[0-9a-f]{24}$", re.ASCII)
_HANDOFF_ID = re.compile(r"^hnd_[0-9a-f]{24}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


class RegistryUnavailableV1(RuntimeError):
    """The immutable Candidate Registry read handle could not be established."""


class RegistryIncompatibleV1(RuntimeError):
    """The Registry or search projection generation is not supported by V1."""


class RegistryCorruptV1(RuntimeError):
    """The declared V1 Registry structure or integrity proof is invalid."""


class Fts5UnavailableV1(RuntimeError):
    """One of the two required SQLite FTS5 tokenizers is unavailable."""


class RetrievalQueryFailedV1(RuntimeError):
    """A dual-branch FTS query or its snapshot release failed."""


class RetrievalMaterializationFailedV1(RuntimeError):
    """A retrieval identity, projection, or deterministic asset could not form."""


class DataRootIntegrityLostV1(RuntimeError):
    """The validated Knowledge Data Root proof changed during retrieval."""


@dataclass(frozen=True, slots=True)
class MeasuredRetrievalViewV1:
    value: dict[str, object]
    buffer: bytes
    byte_length: int
    sha256: str
    status: Literal["within_limit", "too_large"]


@dataclass(frozen=True, slots=True)
class ZeroCandidateRetrievalV1:
    registry_snapshot_sha256: str
    measured_retrieval_view: MeasuredRetrievalViewV1
    retrieval_audit: dict[str, object]
    retrieval_audit_bytes: bytes


@dataclass(frozen=True, slots=True)
class NonZeroCandidatesV1:
    """A T21 hand-off verdict; T20 must not publish an approximate zero Answer."""

    registry_snapshot_sha256: str
    selected_candidate_ids: tuple[str, ...]
    trigram_match_count: int
    unicode61_match_count: int


KnowledgeRetrievalResultV1: TypeAlias = ZeroCandidateRetrievalV1 | NonZeroCandidatesV1


@dataclass(frozen=True, slots=True)
class _BranchHitV1:
    candidate_id: str
    rank: int
    bm25_float64_hex: str


def _is_hash_v1(value: object) -> TypeGuard[str]:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _canonical_json_file_v1(value: object) -> bytes:
    try:
        return canonical_json_bytes_v1(value) + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise RetrievalMaterializationFailedV1(
            "Retrieval asset is not canonical JSON"
        ) from error


def _open_registry_read_only_v1(
    root: ValidatedDataRootV1,
) -> tuple[sqlite3.Connection, ValidatedFileV1]:
    try:
        guard = root.open_relative_file_v1(("registry.sqlite3",))
    except (DataRootOpenErrorV1, OSError) as error:
        raise RegistryUnavailableV1("Candidate Registry is unavailable") from error
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{Path(guard.canonical_path).as_uri()}?mode=ro",
            uri=True,
            timeout=0.25,
            isolation_level=None,
        )
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 250")
        connection.execute("PRAGMA temp_store = MEMORY")
        guard.revalidate_identity_v1()
        return connection, guard
    except (DataRootOpenErrorV1, sqlite3.Error) as error:
        if connection is not None:
            connection.close()
        guard.close()
        raise RegistryUnavailableV1("Candidate Registry cannot be opened") from error


def _fetch_at_most_two_v1(
    connection: sqlite3.Connection,
    statement: str,
    parameters: tuple[object, ...] = (),
) -> list[tuple[object, ...]]:
    cursor = connection.execute(statement, parameters)
    try:
        return cast(list[tuple[object, ...]], cursor.fetchmany(2))
    finally:
        cursor.close()


def _next_candidate_id_v1(cursor: sqlite3.Cursor) -> str | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if (
        type(row) is not tuple
        or len(row) != 1
        or type(row[0]) is not str
        or _CANDIDATE_ID.fullmatch(row[0]) is None
    ):
        raise RegistryCorruptV1("Candidate Registry membership is invalid")
    return row[0]


def _assert_same_candidate_stream_v1(
    connection: sqlite3.Connection,
    left_statement: str,
    right_statement: str,
    *,
    message: str,
) -> None:
    left = connection.execute(left_statement)
    right = connection.execute(right_statement)
    previous: str | None = None
    try:
        while True:
            left_id = _next_candidate_id_v1(left)
            right_id = _next_candidate_id_v1(right)
            if left_id != right_id:
                raise RegistryCorruptV1(message)
            if left_id is None:
                return
            if previous is not None and previous.encode("ascii") >= left_id.encode(
                "ascii"
            ):
                raise RegistryCorruptV1("Candidate Registry membership is not unique")
            previous = left_id
    finally:
        left.close()
        right.close()


def _validate_registry_v1(connection: sqlite3.Connection) -> None:
    try:
        application_id = connection.execute("PRAGMA application_id").fetchone()
        user_version = connection.execute("PRAGMA user_version").fetchone()
        if application_id != (_APPLICATION_ID,) or user_version != (_USER_VERSION,):
            raise RegistryIncompatibleV1("Candidate Registry generation is unsupported")

        observed_schema = _schema_rows(connection)
        expected_base_schema = _expected_base_schema_rows()
        base_names = frozenset(row[1] for row in expected_base_schema)
        observed_base_schema = tuple(
            row for row in observed_schema if row[1] in base_names
        )
        if observed_base_schema != expected_base_schema:
            raise RegistryCorruptV1("Candidate Registry governance schema is invalid")
        if observed_schema == expected_base_schema:
            raise RegistryIncompatibleV1("search projection generation is absent")

        quick_check = _fetch_at_most_two_v1(connection, "PRAGMA quick_check")
        foreign_key_check = _fetch_at_most_two_v1(
            connection, "PRAGMA foreign_key_check"
        )
        if (
            connection.execute("PRAGMA query_only").fetchone() != (1,)
            or connection.execute("PRAGMA foreign_keys").fetchone() != (1,)
            or quick_check != [("ok",)]
            or foreign_key_check
        ):
            raise RegistryCorruptV1("Candidate Registry integrity is invalid")

        meta = _fetch_at_most_two_v1(
            connection,
            "SELECT singleton, schema_version, generation FROM registry_meta",
        )
        if len(meta) != 1 or meta[0][0] != 1:
            raise RegistryCorruptV1("Candidate Registry metadata is invalid")
        if meta[0][1] != _SCHEMA_VERSION:
            raise RegistryIncompatibleV1(
                "Candidate Registry schema identity is unsupported"
            )
        revision_count = connection.execute(
            "SELECT count(*) FROM handoff_revisions"
        ).fetchone()
        if (
            type(meta[0][2]) is not int
            or meta[0][2] < 0
            or revision_count != (meta[0][2],)
        ):
            raise RegistryCorruptV1("Candidate Registry generation is invalid")

        search_meta = _fetch_at_most_two_v1(
            connection,
            "SELECT singleton, schema_version, registry_generation "
            "FROM registry_search_meta",
        )
        if len(search_meta) != 1 or search_meta[0][0] != 1:
            raise RegistryCorruptV1("search projection metadata is invalid")
        if search_meta[0][1] != "gezhi.candidate_search_projection.v1":
            raise RegistryIncompatibleV1("search projection generation is unsupported")
        if observed_schema != _expected_schema_rows():
            raise RegistryCorruptV1("Candidate Registry schema is invalid")
        if search_meta[0][2] != meta[0][2]:
            raise RegistryCorruptV1("search projection generation differs")

        content_ids = (
            "SELECT candidate_id FROM candidate_content "
            "ORDER BY candidate_id COLLATE BINARY ASC"
        )
        current_ids = (
            "SELECT candidate_id FROM candidate_current "
            "ORDER BY candidate_id COLLATE BINARY ASC"
        )
        _assert_same_candidate_stream_v1(
            connection,
            content_ids,
            current_ids,
            message="Candidate current projection membership differs",
        )
        eligible_ids = """
            SELECT content.candidate_id
            FROM candidate_content AS content
            JOIN candidate_current AS current USING(candidate_id)
            WHERE current.review_status = 'accepted'
              AND current.intake_status = 'active'
              AND content.promotion_status = 'not_promoted'
            ORDER BY content.candidate_id COLLATE BINARY ASC
        """
        for table in ("candidate_search_unicode", "candidate_search_trigram"):
            _assert_same_candidate_stream_v1(
                connection,
                eligible_ids,
                f"SELECT candidate_id FROM {table} "
                "ORDER BY candidate_id COLLATE BINARY ASC",
                message="search projection membership differs",
            )
    except (RegistryCorruptV1, RegistryIncompatibleV1):
        raise
    except sqlite3.Error as error:
        if _sqlite_is_busy(error):
            raise RegistryUnavailableV1("Candidate Registry is busy") from error
        message = str(error).casefold()
        if "no such module: fts5" in message or "no such tokenizer" in message:
            raise Fts5UnavailableV1("required FTS5 tokenizer is unavailable") from error
        raise RegistryCorruptV1("Candidate Registry cannot be validated") from error


def _projection_fields_v1(
    connection: sqlite3.Connection,
    table: Literal["candidate_search_unicode", "candidate_search_trigram"],
    candidate_id: str,
) -> tuple[str, str, str, str]:
    try:
        rows = _fetch_at_most_two_v1(
            connection,
            f"SELECT statement_text, source_terms_text, descriptor_text, work_title "
            f"FROM {table} WHERE candidate_id = ?",
            (candidate_id,),
        )
    except sqlite3.Error as error:
        raise RetrievalMaterializationFailedV1(
            "Candidate search projection cannot be read"
        ) from error
    if (
        len(rows) != 1
        or len(rows[0]) != 4
        or any(type(value) is not str for value in rows[0])
    ):
        raise RetrievalMaterializationFailedV1(
            "Candidate search projection is not singular"
        )
    return cast(tuple[str, str, str, str], rows[0])


def _snapshot_entry_v1(
    connection: sqlite3.Connection,
    row: tuple[object, ...],
) -> dict[str, object]:
    if len(row) != 17:
        raise RetrievalMaterializationFailedV1(
            "Candidate snapshot row shape is invalid"
        )
    (
        candidate_id,
        payload_sha256,
        candidate_blob,
        citation_blob,
        descriptor_blob,
        evidence_blob,
        content_manifest_sha256,
        content_candidates_sha256,
        promotion_status,
        review_revision,
        review_status,
        intake_status,
        status_handoff_id,
        work_id,
        source_id,
        source_sha256,
        canonical_content_sha256,
    ) = row
    if (
        type(candidate_id) is not str
        or _CANDIDATE_ID.fullmatch(candidate_id) is None
        or not _is_hash_v1(payload_sha256)
        or candidate_id != "cand_" + payload_sha256[:24]
        or type(review_revision) is not int
        or not 1 <= review_revision <= _MAX_INT64
        or type(status_handoff_id) is not str
        or _HANDOFF_ID.fullmatch(status_handoff_id) is None
        or not _is_hash_v1(content_manifest_sha256)
        or not _is_hash_v1(content_candidates_sha256)
        or not _is_hash_v1(source_sha256)
        or not _is_hash_v1(canonical_content_sha256)
        or (promotion_status, review_status, intake_status)
        != ("not_promoted", "accepted", "active")
    ):
        raise RetrievalMaterializationFailedV1("Candidate snapshot identity is invalid")
    try:
        candidate = decode_canonical_json_blob_v1(candidate_blob)
        citation = decode_canonical_json_blob_v1(citation_blob)
        descriptor_snapshots = decode_canonical_json_blob_v1(descriptor_blob)
        evidence_snapshots = decode_canonical_json_blob_v1(evidence_blob)
        if (
            type(candidate) is not dict
            or type(citation) is not dict
            or type(descriptor_snapshots) is not list
            or type(evidence_snapshots) is not list
        ):
            raise ValueError("Candidate snapshot source shape is invalid")
        synthetic_record: dict[str, object] = {
            "action": "accept",
            "candidate": candidate,
            "citation": citation,
            "descriptor_snapshots": descriptor_snapshots,
            "evidence_snapshots": evidence_snapshots,
            "review_receipt": {},
            "schema_version": "gezhi.reviewed_candidate_action.v1",
        }
        observed_candidate_id, observed_payload_sha256 = _validate_accept_record(
            synthetic_record,
            exact_witness=(content_manifest_sha256, content_candidates_sha256)
            in _WITNESS_FILE_HASH_PAIRS,
        )
        payload = candidate["payload"]
        if type(payload) is not dict:
            raise ValueError("Candidate payload is invalid")
        unicode_fields, trigram_fields = search_document_fields_v1(
            candidate,
            citation,
            descriptor_snapshots,
        )
    except (KeyError, TypeError, ValueError, _HandoffInvalidV1) as error:
        raise RetrievalMaterializationFailedV1(
            "Candidate snapshot source is invalid"
        ) from error
    if (
        observed_candidate_id != candidate_id
        or observed_payload_sha256 != payload_sha256
        or payload.get("work_id") != work_id
        or payload.get("source_id") != source_id
        or payload.get("source_sha256") != source_sha256
        or payload.get("canonical_content_sha256") != canonical_content_sha256
    ):
        raise RetrievalMaterializationFailedV1(
            "Candidate snapshot source identity differs"
        )
    try:
        latest = connection.execute(
            """
            SELECT review_revision, review_status, action, handoff_id
            FROM handoff_revisions
            WHERE candidate_id = ?
            ORDER BY review_revision DESC
            LIMIT 1
            """,
            (candidate_id,),
        ).fetchone()
    except sqlite3.Error as error:
        raise RetrievalMaterializationFailedV1(
            "Candidate snapshot revision cannot be read"
        ) from error
    if latest != (review_revision, "accepted", "accept", status_handoff_id):
        raise RetrievalMaterializationFailedV1(
            "Candidate snapshot revision identity differs"
        )
    if (
        _projection_fields_v1(connection, "candidate_search_unicode", candidate_id)
        != unicode_fields
        or _projection_fields_v1(connection, "candidate_search_trigram", candidate_id)
        != trigram_fields
    ):
        raise RetrievalMaterializationFailedV1(
            "Candidate search projection content differs"
        )
    projection = {
        "candidate_source_terms": trigram_fields[1],
        "candidate_statement": trigram_fields[0],
        "descriptor_terms": trigram_fields[2],
        "schema_version": "gezhi.candidate_search_projection.v1",
        "work_title": trigram_fields[3],
    }
    search_projection_sha256 = hashlib.sha256(
        canonical_json_bytes_v1(projection)
    ).hexdigest()
    return {
        "candidate_id": candidate_id,
        "payload_sha256": payload_sha256,
        "review_revision": review_revision,
        "search_projection_sha256": search_projection_sha256,
    }


def _registry_snapshot_sha256_v1(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    digest.update(b'{"entries":[')
    previous_candidate_id: str | None = None
    first = True
    try:
        cursor = connection.execute(
            """
            SELECT content.candidate_id, content.payload_sha256,
                   content.candidate_json, content.citation_json,
                   content.descriptor_snapshots_json,
                   content.evidence_snapshots_json,
                   content.content_manifest_sha256,
                   content.content_candidates_sha256,
                   content.promotion_status, current.review_revision,
                   current.review_status, current.intake_status,
                   current.status_handoff_id, content.work_id,
                   content.source_id, content.source_sha256,
                   content.canonical_content_sha256
            FROM candidate_content AS content
            JOIN candidate_current AS current USING(candidate_id)
            WHERE current.intake_status = 'active'
            ORDER BY content.candidate_id COLLATE BINARY ASC
            """
        )
        try:
            for raw_row in cursor:
                row = cast(tuple[object, ...], raw_row)
                entry = _snapshot_entry_v1(connection, row)
                candidate_id = cast(str, entry["candidate_id"])
                if previous_candidate_id is not None and previous_candidate_id.encode(
                    "ascii"
                ) >= candidate_id.encode("ascii"):
                    raise RetrievalMaterializationFailedV1(
                        "Candidate snapshot order or uniqueness is invalid"
                    )
                if not first:
                    digest.update(b",")
                digest.update(canonical_json_bytes_v1(entry))
                previous_candidate_id = candidate_id
                first = False
        finally:
            cursor.close()
    except RetrievalMaterializationFailedV1:
        raise
    except sqlite3.Error as error:
        raise RetrievalMaterializationFailedV1(
            "Candidate snapshot cannot be streamed"
        ) from error
    digest.update(
        b'],"schema_version":"gezhi.registry_retrieval_snapshot_identity.v1"}'
    )
    return digest.hexdigest()


def _branch_hits_v1(
    connection: sqlite3.Connection,
    *,
    table: Literal["candidate_search_unicode", "candidate_search_trigram"],
    atoms: tuple[str, ...],
) -> tuple[_BranchHitV1, ...]:
    if not atoms:
        return ()
    match = fts_literal_query_v1(atoms)
    statement = f"""
        SELECT search.candidate_id,
               bm25({table}, 0.0, 1.0, 1.0, 1.0, 1.0) AS score
        FROM {table} AS search
        JOIN candidate_current AS current
          ON current.candidate_id = search.candidate_id
        JOIN candidate_content AS content
          ON content.candidate_id = search.candidate_id
        WHERE {table} MATCH ?
          AND current.review_status = 'accepted'
          AND current.intake_status = 'active'
          AND content.promotion_status = 'not_promoted'
        ORDER BY score ASC, search.candidate_id COLLATE BINARY ASC
        LIMIT 48
    """
    try:
        rows = connection.execute(statement, (match,)).fetchall()
    except sqlite3.Error as error:
        message = str(error).casefold()
        if "no such module: fts5" in message or "no such tokenizer" in message:
            raise Fts5UnavailableV1("required FTS5 tokenizer is unavailable") from error
        raise RetrievalQueryFailedV1("FTS branch failed") from error
    observed: list[_BranchHitV1] = []
    seen: set[str] = set()
    previous: tuple[float, bytes] | None = None
    for rank, row in enumerate(rows, start=1):
        if (
            type(row) is not tuple
            or len(row) != 2
            or type(row[0]) is not str
            or _CANDIDATE_ID.fullmatch(row[0]) is None
            or row[0] in seen
            or type(row[1]) is not float
            or not math.isfinite(row[1])
        ):
            raise RetrievalQueryFailedV1("FTS branch result is invalid")
        order_key = (row[1], row[0].encode("ascii"))
        if previous is not None and previous >= order_key:
            raise RetrievalQueryFailedV1("FTS branch order is invalid")
        score_hex = row[1].hex()
        try:
            score_round_trip = float.fromhex(score_hex).hex()
        except ValueError as error:
            raise RetrievalQueryFailedV1("FTS branch score is invalid") from error
        if score_round_trip != score_hex:
            raise RetrievalQueryFailedV1("FTS branch score is not exact")
        seen.add(row[0])
        observed.append(_BranchHitV1(row[0], rank, score_hex))
        previous = order_key
    return tuple(observed)


def _rank_candidates_v1(
    unicode_hits: tuple[_BranchHitV1, ...],
    trigram_hits: tuple[_BranchHitV1, ...],
) -> tuple[str, ...]:
    scores: dict[str, Fraction] = {}
    for hits in (unicode_hits, trigram_hits):
        for hit in hits:
            scores[hit.candidate_id] = scores.get(
                hit.candidate_id, Fraction()
            ) + Fraction(1, 12 + hit.rank)
    return tuple(
        candidate_id
        for candidate_id, _score in sorted(
            scores.items(),
            key=lambda item: (-item[1], item[0].encode("ascii")),
        )[:12]
    )


def _zero_candidate_result_v1(
    *,
    search_text: SearchTextV1,
    question_asset_sha256: str,
    retrieval_query_asset_sha256: str,
    registry_snapshot_sha256: str,
) -> ZeroCandidateRetrievalV1:
    view: dict[str, object] = {
        "answer_kind": "candidate_backed",
        "candidate_count": 0,
        "items": [],
        "schema_version": _VIEW_SCHEMA_VERSION,
    }
    view_buffer = _canonical_json_file_v1(view)
    view_sha256 = hashlib.sha256(view_buffer).hexdigest()
    if len(view_buffer) != 109 or view_sha256 != _ZERO_VIEW_SHA256:
        raise RetrievalMaterializationFailedV1(
            "Zero-candidate Retrieval View witness differs"
        )
    measured = MeasuredRetrievalViewV1(
        value=view,
        buffer=view_buffer,
        byte_length=len(view_buffer),
        sha256=view_sha256,
        status="within_limit",
    )
    audit: dict[str, object] = {
        "algorithm_version": _ALGORITHM_VERSION,
        "branch_results": {"trigram": [], "unicode61": []},
        "final_selection": [],
        "query_atoms": {
            "trigram": list(search_text.trigram_atoms),
            "unicode61": list(search_text.unicode61_atoms),
        },
        "question_asset_sha256": question_asset_sha256,
        "registry_snapshot_sha256": registry_snapshot_sha256,
        "retrieval_query_asset_sha256": retrieval_query_asset_sha256,
        "retrieval_view_measurement": {
            "byte_length": measured.byte_length,
            "limit_bytes": _VIEW_LIMIT_BYTES,
            "sha256": measured.sha256,
            "status": measured.status,
        },
        "schema_version": _AUDIT_SCHEMA_VERSION,
    }
    audit_bytes = _canonical_json_file_v1(audit)
    if len(audit_bytes) > _AUDIT_LIMIT_BYTES:
        raise RetrievalMaterializationFailedV1("Retrieval Audit exceeds its byte limit")
    return ZeroCandidateRetrievalV1(
        registry_snapshot_sha256=registry_snapshot_sha256,
        measured_retrieval_view=measured,
        retrieval_audit=audit,
        retrieval_audit_bytes=audit_bytes,
    )


def _seal_root_v1(
    root: ValidatedDataRootV1,
    guard: ValidatedFileV1 | None,
) -> None:
    try:
        if guard is not None:
            guard.revalidate_identity_v1()
        _root_checkpoint(root)
    except _DataRootIntegrityLostV1 as error:
        raise DataRootIntegrityLostV1("Knowledge Data Root identity changed") from error
    except (DataRootOpenErrorV1, OSError) as error:
        raise DataRootIntegrityLostV1("Knowledge Data Root proof was lost") from error


def _retrieve_v1(
    root: ValidatedDataRootV1,
    search_text: SearchTextV1,
    *,
    question_asset_sha256: str,
    retrieval_query_asset_sha256: str,
) -> KnowledgeRetrievalResultV1:
    connection: sqlite3.Connection | None = None
    guard: ValidatedFileV1 | None = None
    transaction_started = False
    result: KnowledgeRetrievalResultV1 | None = None
    operation_error: Exception | None = None
    try:
        try:
            connection, guard = _open_registry_read_only_v1(root)
            try:
                connection.execute("BEGIN")
                transaction_started = True
            except sqlite3.Error as error:
                raise RegistryUnavailableV1(
                    "Candidate Registry snapshot cannot begin"
                ) from error
            _validate_registry_v1(connection)
            registry_snapshot_sha256 = _registry_snapshot_sha256_v1(connection)
            unicode_hits = _branch_hits_v1(
                connection,
                table="candidate_search_unicode",
                atoms=search_text.unicode61_atoms,
            )
            trigram_hits = _branch_hits_v1(
                connection,
                table="candidate_search_trigram",
                atoms=search_text.trigram_atoms,
            )
            selected = _rank_candidates_v1(unicode_hits, trigram_hits)
            if selected:
                result = NonZeroCandidatesV1(
                    registry_snapshot_sha256=registry_snapshot_sha256,
                    selected_candidate_ids=selected,
                    trigram_match_count=len(trigram_hits),
                    unicode61_match_count=len(unicode_hits),
                )
            else:
                result = _zero_candidate_result_v1(
                    search_text=search_text,
                    question_asset_sha256=question_asset_sha256,
                    retrieval_query_asset_sha256=retrieval_query_asset_sha256,
                    registry_snapshot_sha256=registry_snapshot_sha256,
                )
        except Exception as error:  # noqa: BLE001 - release can change precedence.
            operation_error = error
        finally:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error as error:
                    if transaction_started:
                        operation_error = RetrievalQueryFailedV1(
                            "Candidate Registry snapshot cannot be released"
                        )
                    else:
                        operation_error = RegistryUnavailableV1(
                            "Candidate Registry connection cannot be released"
                        )
                    operation_error.__cause__ = error
            try:
                _seal_root_v1(root, guard)
            except DataRootIntegrityLostV1 as error:
                operation_error = error
        if operation_error is not None:
            raise operation_error
        if result is None:
            raise RetrievalMaterializationFailedV1(
                "Knowledge retrieval completed without a verdict"
            )
        return result
    finally:
        try:
            if connection is not None:
                connection.close()
        except sqlite3.Error as error:
            raise RetrievalQueryFailedV1(
                "Candidate Registry connection cannot close"
            ) from error
        finally:
            if guard is not None:
                try:
                    guard.close()
                except DataRootLifecycleErrorV1 as error:
                    raise DataRootIntegrityLostV1(
                        "Candidate Registry guard cannot close"
                    ) from error


class KnowledgeRetrievalV1:
    @staticmethod
    def retrieve(
        root: ValidatedDataRootV1,
        search_text: SearchTextV1,
        *,
        question_asset_sha256: str,
        retrieval_query_asset_sha256: str,
    ) -> KnowledgeRetrievalResultV1:
        if (
            type(root) is not ValidatedDataRootV1
            or type(search_text) is not SearchTextV1
        ):
            raise TypeError("Knowledge retrieval input type is invalid")
        if not _is_hash_v1(question_asset_sha256) or not _is_hash_v1(
            retrieval_query_asset_sha256
        ):
            raise RetrievalMaterializationFailedV1(
                "Knowledge retrieval asset identity is invalid"
            )
        try:
            observed_search_text = validate_normalized_search_text_v1(
                search_text.normalized_text
            )
        except SearchQueryInvalidV1 as error:
            raise RetrievalMaterializationFailedV1(
                "Knowledge retrieval query is invalid"
            ) from error
        if observed_search_text != search_text:
            raise RetrievalMaterializationFailedV1(
                "Knowledge retrieval query identity differs"
            )
        return _retrieve_v1(
            root,
            search_text,
            question_asset_sha256=question_asset_sha256,
            retrieval_query_asset_sha256=retrieval_query_asset_sha256,
        )


__all__ = [
    "DataRootIntegrityLostV1",
    "Fts5UnavailableV1",
    "KnowledgeRetrievalResultV1",
    "KnowledgeRetrievalV1",
    "MeasuredRetrievalViewV1",
    "NonZeroCandidatesV1",
    "RegistryCorruptV1",
    "RegistryIncompatibleV1",
    "RegistryUnavailableV1",
    "RetrievalMaterializationFailedV1",
    "RetrievalQueryFailedV1",
    "ZeroCandidateRetrievalV1",
]
