from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Literal, TypeAlias

from gezhi._configuration import ConfigurationError, resolve_configuration_v1
from gezhi._knowledge_intake import (
    _APPLICATION_ID,
    _MAX_HANDOFF_BYTES,
    _SCHEMA_VERSION,
    _USER_VERSION,
    _WITNESS_FILE_HASH_PAIRS,
    _DataRootIntegrityLostV1,
    _expected_base_schema_rows,
    _expected_schema_rows,
    _HandoffInvalidV1,
    _RegistryBusyV1,
    _root_checkpoint,
    _schema_rows,
    _sqlite_is_busy,
    _validate_accept_record,
    _validate_candidate,
    _validate_handoff,
    _ValidatedHandoffV1,
)
from gezhi._knowledge_registry import (
    SearchQueryInvalidV1,
    SearchQueryTooComplexV1,
    SearchQueryTooLargeV1,
    SearchTextV1,
    canonical_json_bytes_v1,
    decode_canonical_json_blob_v1,
    fts_literal_query_v1,
    normalize_search_query_v1,
)
from gezhi._literature_review import ReviewedHandoffBytesV1
from gezhi._windows_data_root import (
    DataRootOpenErrorV1,
    ValidatedDataRootV1,
    ValidatedFileV1,
    open_validated_data_root_v1,
)

KnowledgeReadCommandV1: TypeAlias = Literal["knowledge.search", "knowledge.show"]
KnowledgeReadOutcomeV1: TypeAlias = Literal["succeeded", "blocked", "failed"]

_CANDIDATE_ID = re.compile(r"^cand_[0-9a-f]{24}$", re.ASCII)


@dataclass(frozen=True, slots=True)
class KnowledgeReadReportV1:
    command: KnowledgeReadCommandV1
    outcome: KnowledgeReadOutcomeV1
    result: dict[str, object] | None
    reason: str | None


class _RegistryUnavailableV1(RuntimeError):
    pass


class _RegistryIncompatibleV1(RuntimeError):
    pass


class _RegistryCorruptV1(RuntimeError):
    pass


class _FtsUnavailableV1(RuntimeError):
    pass


class _CandidateNotFoundV1(RuntimeError):
    pass


class _CandidateCorruptV1(RuntimeError):
    pass


class _EvidenceCorruptV1(RuntimeError):
    pass


class _RegistryReadFailedV1(RuntimeError):
    pass


class _RetrievalQueryFailedV1(RuntimeError):
    pass


class _RetrievalMaterializationFailedV1(RuntimeError):
    pass


def _report(
    command: KnowledgeReadCommandV1,
    outcome: KnowledgeReadOutcomeV1,
    *,
    result: dict[str, object] | None = None,
    reason: str | None = None,
) -> KnowledgeReadReportV1:
    if (outcome == "succeeded") != (result is not None and reason is None):
        raise ValueError("Knowledge read report presence is invalid")
    if outcome != "succeeded" and (result is not None or reason is None):
        raise ValueError("Knowledge read failure report presence is invalid")
    return KnowledgeReadReportV1(command, outcome, result, reason)


def _data_root_open_reason_v1(error: DataRootOpenErrorV1) -> str:
    if error.cause == "identity_unavailable":
        return "data_root_identity_unavailable"
    if error.status == "unsafe":
        return "data_root_unsafe"
    return "data_root_unavailable"


def _open_registry_read_only_v1(
    root: ValidatedDataRootV1,
) -> tuple[sqlite3.Connection, ValidatedFileV1]:
    try:
        guard = root.open_relative_file_v1(("registry.sqlite3",))
    except (DataRootOpenErrorV1, OSError) as error:
        raise _RegistryUnavailableV1("Candidate Registry is unavailable") from error
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"file:{guard.canonical_path}?mode=ro",
            uri=True,
            timeout=0.25,
            isolation_level=None,
        )
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 250")
        guard.revalidate_identity_v1()
        return connection, guard
    except (DataRootOpenErrorV1, sqlite3.Error) as error:
        if connection is not None:
            connection.close()
        guard.close()
        raise _RegistryUnavailableV1("Candidate Registry cannot be opened") from error


def _branch_rows_v1(
    connection: sqlite3.Connection,
    *,
    table: Literal["candidate_search_unicode", "candidate_search_trigram"],
    atoms: tuple[str, ...],
) -> tuple[tuple[str, int], ...]:
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
            raise _FtsUnavailableV1("required FTS5 tokenizer is unavailable") from error
        raise _RetrievalQueryFailedV1("FTS branch failed") from error
    observed: list[tuple[str, int]] = []
    seen: set[str] = set()
    for rank, row in enumerate(rows, start=1):
        if (
            type(row) is not tuple
            or len(row) != 2
            or type(row[0]) is not str
            or _CANDIDATE_ID.fullmatch(row[0]) is None
            or row[0] in seen
            or type(row[1]) is not float
        ):
            raise _RetrievalQueryFailedV1("FTS branch result is invalid")
        seen.add(row[0])
        observed.append((row[0], rank))
    return tuple(observed)


def _validate_registry_for_search_v1(connection: sqlite3.Connection) -> None:
    try:
        application_id = connection.execute("PRAGMA application_id").fetchone()
        user_version = connection.execute("PRAGMA user_version").fetchone()
        if application_id != (_APPLICATION_ID,) or user_version != (_USER_VERSION,):
            raise _RegistryIncompatibleV1(
                "Candidate Registry generation is unsupported"
            )
        observed_schema = _schema_rows(connection)
        if observed_schema == _expected_base_schema_rows():
            raise _RegistryIncompatibleV1("search projection generation is absent")
        if observed_schema != _expected_schema_rows():
            raise _RegistryCorruptV1("Candidate Registry schema is invalid")
        if (
            connection.execute("PRAGMA query_only").fetchone() != (1,)
            or connection.execute("PRAGMA foreign_keys").fetchone() != (1,)
            or connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]
            or connection.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise _RegistryCorruptV1("Candidate Registry integrity is invalid")
        meta = connection.execute(
            "SELECT singleton, schema_version, generation FROM registry_meta"
        ).fetchall()
        if len(meta) != 1 or meta[0][0] != 1:
            raise _RegistryCorruptV1("Candidate Registry metadata is invalid")
        if meta[0][1] != _SCHEMA_VERSION:
            raise _RegistryIncompatibleV1(
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
            raise _RegistryCorruptV1("Candidate Registry generation is invalid")
        search_meta = connection.execute(
            "SELECT singleton, schema_version, registry_generation "
            "FROM registry_search_meta"
        ).fetchall()
        if len(search_meta) != 1 or search_meta[0][0] != 1:
            raise _RegistryCorruptV1("search projection metadata is invalid")
        if search_meta[0][1] != "gezhi.candidate_search_projection.v1":
            raise _RegistryIncompatibleV1("search projection generation is unsupported")
        if search_meta[0][2] != meta[0][2]:
            raise _RegistryCorruptV1("search projection generation differs")
        active_ids = tuple(
            row[0]
            for row in connection.execute(
                """
                SELECT content.candidate_id
                FROM candidate_content AS content
                JOIN candidate_current AS current USING(candidate_id)
                WHERE current.review_status = 'accepted'
                  AND current.intake_status = 'active'
                  AND content.promotion_status = 'not_promoted'
                ORDER BY content.candidate_id COLLATE BINARY ASC
                """
            ).fetchall()
        )
        branch_ids: list[tuple[object, ...]] = []
        for table in ("candidate_search_unicode", "candidate_search_trigram"):
            branch_ids.append(
                tuple(
                    row[0]
                    for row in connection.execute(
                        f"SELECT candidate_id FROM {table} "
                        "ORDER BY candidate_id COLLATE BINARY ASC"
                    ).fetchall()
                )
            )
        if any(ids != active_ids for ids in branch_ids):
            raise _RegistryCorruptV1("search projection membership differs")
    except (_FtsUnavailableV1, _RegistryCorruptV1, _RegistryIncompatibleV1):
        raise
    except sqlite3.Error as error:
        if _sqlite_is_busy(error):
            raise _RegistryBusyV1("Candidate Registry is busy") from error
        message = str(error).casefold()
        if "no such module: fts5" in message or "no such tokenizer" in message:
            raise _FtsUnavailableV1("required FTS5 tokenizer is unavailable") from error
        raise _RegistryCorruptV1("Candidate Registry cannot be validated") from error


def _validate_registry_for_show_v1(connection: sqlite3.Connection) -> None:
    try:
        if connection.execute("PRAGMA application_id").fetchone() != (
            _APPLICATION_ID,
        ) or connection.execute("PRAGMA user_version").fetchone() != (_USER_VERSION,):
            raise _RegistryIncompatibleV1(
                "Candidate Registry generation is unsupported"
            )
        observed_schema = _schema_rows(connection)
        if observed_schema not in {
            _expected_base_schema_rows(),
            _expected_schema_rows(),
        }:
            raise _RegistryCorruptV1("Candidate Registry schema is invalid")
        if (
            connection.execute("PRAGMA query_only").fetchone() != (1,)
            or connection.execute("PRAGMA foreign_keys").fetchone() != (1,)
            or connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]
            or connection.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise _RegistryCorruptV1("Candidate Registry integrity is invalid")
        meta = connection.execute(
            "SELECT singleton, schema_version, generation FROM registry_meta"
        ).fetchall()
        revision_count = connection.execute(
            "SELECT count(*) FROM handoff_revisions"
        ).fetchone()
        if len(meta) != 1 or meta[0][0] != 1:
            raise _RegistryCorruptV1("Candidate Registry metadata is invalid")
        if meta[0][1] != _SCHEMA_VERSION:
            raise _RegistryIncompatibleV1(
                "Candidate Registry schema identity is unsupported"
            )
        if (
            type(meta[0][2]) is not int
            or meta[0][2] < 0
            or revision_count != (meta[0][2],)
        ):
            raise _RegistryCorruptV1("Candidate Registry generation is invalid")
    except (_RegistryCorruptV1, _RegistryIncompatibleV1):
        raise
    except sqlite3.Error as error:
        if _sqlite_is_busy(error):
            raise _RegistryBusyV1("Candidate Registry is busy") from error
        raise _RegistryCorruptV1("Candidate Registry cannot be validated") from error


def _rank_candidates_v1(
    unicode_rows: Sequence[tuple[str, int]],
    trigram_rows: Sequence[tuple[str, int]],
) -> tuple[str, ...]:
    scores: dict[str, Fraction] = {}
    for rows in (unicode_rows, trigram_rows):
        for candidate_id, branch_rank in rows:
            scores[candidate_id] = scores.get(candidate_id, Fraction()) + Fraction(
                1,
                12 + branch_rank,
            )
    return tuple(
        candidate_id
        for candidate_id, _score in sorted(
            scores.items(),
            key=lambda item: (-item[1], item[0].encode("ascii")),
        )[:12]
    )


def _materialize_search_candidate_v1(
    connection: sqlite3.Connection,
    candidate_id: str,
) -> dict[str, object]:
    try:
        row = connection.execute(
            """
            SELECT content.candidate_json, content.payload_sha256,
                   content.work_id, content.source_id, content.source_sha256,
                   content.canonical_content_sha256,
                   content.content_manifest_sha256,
                   content.content_candidates_sha256,
                   content.promotion_status, current.review_status,
                   current.intake_status
            FROM candidate_content AS content
            JOIN candidate_current AS current USING(candidate_id)
            WHERE content.candidate_id = ?
            """,
            (candidate_id,),
        ).fetchone()
    except sqlite3.Error as error:
        raise _RetrievalMaterializationFailedV1(
            "Candidate materialization query failed"
        ) from error
    if row is None or len(row) != 11:
        raise _RetrievalMaterializationFailedV1("Candidate content is missing")
    try:
        candidate = decode_canonical_json_blob_v1(row[0])
        exact_witness = (row[6], row[7]) in _WITNESS_FILE_HASH_PAIRS
        validated, payload = _validate_candidate(
            candidate,
            exact_witness=exact_witness,
        )
    except (KeyError, TypeError, ValueError, _HandoffInvalidV1) as error:
        raise _RetrievalMaterializationFailedV1(
            "Candidate content is invalid"
        ) from error
    if (
        validated.get("candidate_id") != candidate_id
        or validated.get("payload_sha256") != row[1]
        or payload.get("work_id") != row[2]
        or payload.get("source_id") != row[3]
        or payload.get("source_sha256") != row[4]
        or payload.get("canonical_content_sha256") != row[5]
        or row[8:] != ("not_promoted", "accepted", "active")
    ):
        raise _RetrievalMaterializationFailedV1(
            "Candidate content and governance differ"
        )
    return validated


def _read_handoff_v1(
    root: ValidatedDataRootV1,
    handoff_id: str,
) -> _ValidatedHandoffV1:
    try:
        with root.open_relative_data_root_v1(("imports", handoff_id)) as directory:
            if set(directory.relative_entry_names_v1()) != {
                "candidates.jsonl",
                "manifest.json",
            }:
                raise _EvidenceCorruptV1("Handoff namespace is invalid")
            with directory.open_relative_file_v1(("manifest.json",)) as manifest_file:
                manifest_bytes = manifest_file.read_bytes_v1(limit=_MAX_HANDOFF_BYTES)
            with directory.open_relative_file_v1(
                ("candidates.jsonl",)
            ) as candidates_file:
                candidates_bytes = candidates_file.read_bytes_v1(
                    limit=_MAX_HANDOFF_BYTES
                )
        return _validate_handoff(
            ReviewedHandoffBytesV1(
                manifest_bytes=manifest_bytes,
                candidates_bytes=candidates_bytes,
            )
        )
    except _EvidenceCorruptV1:
        raise
    except (DataRootOpenErrorV1, OSError, ValueError, _HandoffInvalidV1) as error:
        raise _EvidenceCorruptV1("Handoff evidence is invalid") from error


def _handoff_rows_v1(
    connection: sqlite3.Connection,
    handoff_ids: tuple[str, ...],
) -> dict[str, tuple[object, ...]]:
    observed: dict[str, tuple[object, ...]] = {}
    try:
        for handoff_id in handoff_ids:
            row = connection.execute(
                """
                SELECT handoff_id, candidate_id, payload_sha256,
                       review_revision, action, review_status, work_id,
                       source_id, source_sha256, canonical_content_sha256,
                       canonical_run_id, semantic_run_id,
                       manifest_sha256, candidates_sha256
                FROM handoff_revisions
                WHERE handoff_id = ?
                """,
                (handoff_id,),
            ).fetchone()
            if row is None:
                raise _CandidateCorruptV1("Candidate Handoff binding is missing")
            observed[handoff_id] = row
    except sqlite3.Error as error:
        raise _RegistryReadFailedV1("Candidate Handoff lookup failed") from error
    return observed


def _validated_handoff_row_v1(
    value: _ValidatedHandoffV1,
) -> tuple[object, ...]:
    return (
        value.handoff_id,
        value.candidate_id,
        value.payload_sha256,
        value.review_revision,
        value.action,
        value.review_status,
        value.work_id,
        value.source_id,
        value.source_sha256,
        value.canonical_content_sha256,
        value.canonical_run_id,
        value.semantic_run_id,
        value.manifest_sha256,
        value.candidates_sha256,
    )


def _import_result_v1(value: _ValidatedHandoffV1) -> dict[str, object]:
    return {
        "action": value.action,
        "candidates_sha256": value.candidates_sha256,
        "handoff_id": value.handoff_id,
        "manifest_sha256": value.manifest_sha256,
        "review_revision": value.review_revision,
    }


def _show_candidate_v1(
    connection: sqlite3.Connection,
    root: ValidatedDataRootV1,
    candidate_id: str,
) -> dict[str, object]:
    try:
        row = connection.execute(
            """
            SELECT content.candidate_json, content.citation_json,
                   content.descriptor_snapshots_json,
                   content.evidence_snapshots_json,
                   content.payload_sha256, content.work_id,
                   content.source_id, content.source_sha256,
                   content.canonical_content_sha256,
                   content.content_handoff_id,
                   content.content_manifest_sha256,
                   content.content_candidates_sha256,
                   content.promotion_status, current.review_revision,
                   current.review_status, current.intake_status,
                   current.status_handoff_id
            FROM candidate_content AS content
            JOIN candidate_current AS current USING(candidate_id)
            WHERE content.candidate_id = ?
            """,
            (candidate_id,),
        ).fetchone()
    except sqlite3.Error as error:
        raise _RegistryReadFailedV1("Candidate lookup failed") from error
    if row is None:
        raise _CandidateNotFoundV1("Candidate is absent")
    if len(row) != 17:
        raise _CandidateCorruptV1("Candidate Registry row is invalid")
    try:
        candidate = decode_canonical_json_blob_v1(row[0])
        citation = decode_canonical_json_blob_v1(row[1])
        descriptor_snapshots = decode_canonical_json_blob_v1(row[2])
        evidence_snapshots = decode_canonical_json_blob_v1(row[3])
    except ValueError as error:
        raise _CandidateCorruptV1("Candidate Registry content is invalid") from error
    if (
        type(candidate) is not dict
        or type(citation) is not dict
        or type(descriptor_snapshots) is not list
        or type(evidence_snapshots) is not list
    ):
        raise _CandidateCorruptV1("Candidate Registry content shape is invalid")
    synthetic_record: dict[str, object] = {
        "action": "accept",
        "candidate": candidate,
        "citation": citation,
        "descriptor_snapshots": descriptor_snapshots,
        "evidence_snapshots": evidence_snapshots,
        "review_receipt": {},
        "schema_version": "gezhi.reviewed_candidate_action.v1",
    }
    try:
        observed_candidate_id, observed_payload_sha256 = _validate_accept_record(
            synthetic_record,
            exact_witness=(row[10], row[11]) in _WITNESS_FILE_HASH_PAIRS,
        )
    except (KeyError, TypeError, _HandoffInvalidV1) as error:
        raise _CandidateCorruptV1("Candidate Registry content is invalid") from error
    payload = candidate["payload"]
    if type(payload) is not dict:
        raise _CandidateCorruptV1("Candidate payload is invalid")
    if (
        observed_candidate_id != candidate_id
        or observed_payload_sha256 != row[4]
        or payload.get("work_id") != row[5]
        or payload.get("source_id") != row[6]
        or payload.get("source_sha256") != row[7]
        or payload.get("canonical_content_sha256") != row[8]
        or row[12] != "not_promoted"
        or type(row[9]) is not str
        or type(row[16]) is not str
    ):
        raise _CandidateCorruptV1("Candidate Registry identity differs")
    content_handoff_id = row[9]
    status_handoff_id = row[16]
    bindings = _handoff_rows_v1(
        connection,
        tuple(dict.fromkeys((content_handoff_id, status_handoff_id))),
    )
    content_handoff = _read_handoff_v1(root, content_handoff_id)
    status_handoff = (
        content_handoff
        if status_handoff_id == content_handoff_id
        else _read_handoff_v1(root, status_handoff_id)
    )
    if (
        bindings[content_handoff_id] != _validated_handoff_row_v1(content_handoff)
        or bindings[status_handoff_id] != _validated_handoff_row_v1(status_handoff)
        or content_handoff.action != "accept"
        or content_handoff.candidate_id != candidate_id
        or content_handoff.payload_sha256 != row[4]
        or content_handoff.manifest_sha256 != row[10]
        or content_handoff.candidates_sha256 != row[11]
        or status_handoff.candidate_id != candidate_id
        or status_handoff.payload_sha256 != row[4]
        or status_handoff.review_revision != row[13]
        or status_handoff.review_status != row[14]
    ):
        raise _EvidenceCorruptV1("Candidate Handoff binding differs")
    if canonical_json_bytes_v1(content_handoff.record["candidate"]) != row[0] or (
        canonical_json_bytes_v1(content_handoff.record["citation"]) != row[1]
        or canonical_json_bytes_v1(content_handoff.record["descriptor_snapshots"])
        != row[2]
        or canonical_json_bytes_v1(content_handoff.record["evidence_snapshots"])
        != row[3]
    ):
        raise _EvidenceCorruptV1("Candidate Registry and Handoff content differ")
    if row[15] == "active":
        if (
            row[14] != "accepted"
            or status_handoff.action != "accept"
            or content_handoff_id != status_handoff_id
        ):
            raise _CandidateCorruptV1("active Candidate governance is invalid")
    elif row[15] == "withdrawn":
        if (
            row[14] not in {"rejected", "deferred"}
            or status_handoff.action != "withdraw"
            or status_handoff.review_revision <= content_handoff.review_revision
        ):
            raise _CandidateCorruptV1("withdrawn Candidate governance is invalid")
    else:
        raise _CandidateCorruptV1("Candidate Intake Status is invalid")
    record = content_handoff.record
    return {
        "candidate": record["candidate"],
        "citation": record["citation"],
        "content_import": _import_result_v1(content_handoff),
        "descriptor_snapshots": record["descriptor_snapshots"],
        "evidence_snapshots": record["evidence_snapshots"],
        "governance": {
            "intake_status": row[15],
            "promotion_status": "not_promoted",
            "review_status": row[14],
        },
        "result_kind": "candidate_backed",
        "schema_version": "gezhi.knowledge_show_result.v1",
        "status_import": _import_result_v1(status_handoff),
    }


def _show_in_root_v1(
    root: ValidatedDataRootV1,
    *,
    candidate_id: str,
) -> dict[str, object]:
    connection: sqlite3.Connection | None = None
    guard: ValidatedFileV1 | None = None
    try:
        connection, guard = _open_registry_read_only_v1(root)
        connection.execute("BEGIN")
        _validate_registry_for_show_v1(connection)
        result = _show_candidate_v1(connection, root, candidate_id)
        connection.rollback()
        guard.revalidate_identity_v1()
        _root_checkpoint(root)
        return result
    finally:
        try:
            if connection is not None:
                connection.close()
        finally:
            if guard is not None:
                guard.close()


def _search_in_root_v1(
    root: ValidatedDataRootV1,
    *,
    normalized_query: SearchTextV1,
) -> dict[str, object]:
    connection: sqlite3.Connection | None = None
    guard: ValidatedFileV1 | None = None
    try:
        connection, guard = _open_registry_read_only_v1(root)
        connection.execute("BEGIN")
        _validate_registry_for_search_v1(connection)
        unicode_rows = _branch_rows_v1(
            connection,
            table="candidate_search_unicode",
            atoms=normalized_query.unicode61_atoms,
        )
        trigram_rows = _branch_rows_v1(
            connection,
            table="candidate_search_trigram",
            atoms=normalized_query.trigram_atoms,
        )
        candidate_ids = _rank_candidates_v1(unicode_rows, trigram_rows)
        items = [
            {
                "candidate": _materialize_search_candidate_v1(connection, candidate_id),
                "governance": {
                    "intake_status": "active",
                    "promotion_status": "not_promoted",
                    "review_status": "accepted",
                },
                "rank": rank,
            }
            for rank, candidate_id in enumerate(candidate_ids, start=1)
        ]
        result: dict[str, object] = {
            "candidate_count": len(items),
            "items": items,
            "query": normalized_query.normalized_text,
            "result_kind": "candidate_backed",
            "schema_version": "gezhi.knowledge_search_result.v1",
        }
        connection.rollback()
        guard.revalidate_identity_v1()
        _root_checkpoint(root)
        return result
    finally:
        try:
            if connection is not None:
                connection.close()
        finally:
            if guard is not None:
                guard.close()


class KnowledgeReadsV1:
    @staticmethod
    def search(
        raw_query: str,
        *,
        cli_patch: Sequence[tuple[str, str]],
        environ: Mapping[str, str] | None = None,
    ) -> KnowledgeReadReportV1:
        try:
            search_text = normalize_search_query_v1(raw_query)
        except SearchQueryInvalidV1:
            return _report("knowledge.search", "blocked", reason="invalid_query")
        except SearchQueryTooLargeV1:
            return _report("knowledge.search", "blocked", reason="query_too_large")
        except SearchQueryTooComplexV1:
            return _report("knowledge.search", "blocked", reason="query_too_complex")
        try:
            configuration = resolve_configuration_v1(
                trusted_project_root=Path(r"E:\Gezhi"),
                cli_patch=cli_patch,
                environ=os.environ.copy() if environ is None else environ,
            )
        except ConfigurationError as error:
            return _report(
                "knowledge.search",
                "blocked",
                reason=error.cause,
            )
        try:
            root = open_validated_data_root_v1(configuration.knowledge_data_root)
        except DataRootOpenErrorV1 as error:
            return _report(
                "knowledge.search",
                "blocked",
                reason=_data_root_open_reason_v1(error),
            )
        with root:
            try:
                result = _search_in_root_v1(root, normalized_query=search_text)
            except _RegistryUnavailableV1:
                return _report(
                    "knowledge.search",
                    "blocked",
                    reason="registry_unavailable",
                )
            except _RegistryBusyV1:
                return _report(
                    "knowledge.search",
                    "blocked",
                    reason="registry_unavailable",
                )
            except _RegistryIncompatibleV1:
                return _report(
                    "knowledge.search",
                    "blocked",
                    reason="registry_incompatible",
                )
            except _FtsUnavailableV1:
                return _report(
                    "knowledge.search",
                    "blocked",
                    reason="fts5_unavailable",
                )
            except _RegistryCorruptV1:
                return _report(
                    "knowledge.search",
                    "failed",
                    reason="registry_corrupt",
                )
            except _RetrievalQueryFailedV1:
                return _report(
                    "knowledge.search",
                    "failed",
                    reason="retrieval_query_failed",
                )
            except _RetrievalMaterializationFailedV1:
                return _report(
                    "knowledge.search",
                    "failed",
                    reason="retrieval_materialization_failed",
                )
            except _DataRootIntegrityLostV1:
                return _report(
                    "knowledge.search",
                    "failed",
                    reason="data_root_integrity_lost",
                )
        return _report("knowledge.search", "succeeded", result=result)

    @staticmethod
    def show(
        candidate_id: str,
        *,
        cli_patch: Sequence[tuple[str, str]],
        environ: Mapping[str, str] | None = None,
    ) -> KnowledgeReadReportV1:
        if (
            type(candidate_id) is not str
            or _CANDIDATE_ID.fullmatch(candidate_id) is None
        ):
            return _report(
                "knowledge.show",
                "blocked",
                reason="invalid_candidate_id",
            )
        try:
            configuration = resolve_configuration_v1(
                trusted_project_root=Path(r"E:\Gezhi"),
                cli_patch=cli_patch,
                environ=os.environ.copy() if environ is None else environ,
            )
        except ConfigurationError as error:
            return _report("knowledge.show", "blocked", reason=error.cause)
        try:
            root = open_validated_data_root_v1(configuration.knowledge_data_root)
        except DataRootOpenErrorV1 as error:
            return _report(
                "knowledge.show",
                "blocked",
                reason=_data_root_open_reason_v1(error),
            )
        with root:
            try:
                result = _show_in_root_v1(root, candidate_id=candidate_id)
            except _RegistryUnavailableV1:
                return _report(
                    "knowledge.show",
                    "blocked",
                    reason="registry_unavailable",
                )
            except _RegistryBusyV1:
                return _report(
                    "knowledge.show",
                    "blocked",
                    reason="registry_unavailable",
                )
            except _RegistryIncompatibleV1:
                return _report(
                    "knowledge.show",
                    "blocked",
                    reason="registry_incompatible",
                )
            except _CandidateNotFoundV1:
                return _report(
                    "knowledge.show",
                    "blocked",
                    reason="candidate_not_found",
                )
            except _RegistryCorruptV1:
                return _report(
                    "knowledge.show",
                    "failed",
                    reason="registry_corrupt",
                )
            except _RegistryReadFailedV1:
                return _report(
                    "knowledge.show",
                    "failed",
                    reason="registry_read_failed",
                )
            except _CandidateCorruptV1:
                return _report(
                    "knowledge.show",
                    "failed",
                    reason="candidate_corrupt",
                )
            except _EvidenceCorruptV1:
                return _report(
                    "knowledge.show",
                    "failed",
                    reason="evidence_corrupt",
                )
            except _DataRootIntegrityLostV1:
                return _report(
                    "knowledge.show",
                    "failed",
                    reason="data_root_integrity_lost",
                )
        return _report("knowledge.show", "succeeded", result=result)


__all__ = ["KnowledgeReadReportV1", "KnowledgeReadsV1"]
