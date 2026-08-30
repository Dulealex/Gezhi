from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from gezhi._knowledge_registry import (
    SEARCH_PROJECTION_SCHEMA_STATEMENTS,
    SEARCH_PROJECTION_SCHEMA_VERSION,
    bind_search_projection_generation_v1,
    decode_canonical_json_blob_v1,
    remove_search_document_v1,
    replace_active_search_document_v1,
)
from gezhi._literature_review import (
    IntakeAppliedV1,
    IntakeBlockedV1,
    IntakeFailedV1,
    KnowledgeIntakeVerdictV1,
    ReviewedHandoffBytesV1,
)
from gezhi._windows_data_root import (
    DataRootOpenErrorV1,
    ValidatedDataRootV1,
    ValidatedFileV1,
    open_validated_data_root_v1,
    open_validated_local_file_v1,
    open_validated_mutable_local_file_v1,
)
from gezhi._windows_ownership import try_acquire_knowledge_registry_writer_v1

_APPLICATION_ID = 0x475A4831
_SCHEMA_VERSION = "gezhi.candidate_registry.v1"
_USER_VERSION = 1
_MAX_HANDOFF_BYTES = 16 * 1024 * 1024
_MAX_INT64 = 9_223_372_036_854_775_807

_WORK_ID = re.compile(
    r"^wrk_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SOURCE_ID = re.compile(r"^src_[0-9a-f]{24}$")
_CANDIDATE_ID = re.compile(r"^cand_[0-9a-f]{24}$")
_DESCRIPTOR_ID = re.compile(r"^desc_[0-9a-f]{24}$")
_HANDOFF_ID = re.compile(r"^hnd_[0-9a-f]{24}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DOI_PREFIX = re.compile(r"^10\.[0-9]+(?:\.[0-9]+)*$", re.ASCII)
_MODERN_ARXIV = re.compile(
    r"^(?P<year_month>[0-9]{4})\.(?P<number>[0-9]+)(?:v[1-9][0-9]*)?$",
    re.ASCII,
)
_LEGACY_ARXIV = re.compile(
    r"^(?P<archive>[a-z]+(?:-[a-z]+)*)/"
    r"(?P<year_month>[0-9]{4})(?P<number>[0-9]{3})"
    r"(?:v[1-9][0-9]*)?$",
    re.ASCII,
)
_CANONICAL_RUN_ID = re.compile(
    r"^canrun_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SEMANTIC_RUN_ID = re.compile(
    r"^semrun_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_BLOCK_ID = re.compile(r"^blk_[0-9a-f]{24}$")
_WITNESS_CANONICAL_RUN_ID = "canonical_fixture_001"
_WITNESS_SEMANTIC_RUN_ID = "semantic_fixture_001"
_WITNESS_BLOCK_ID = "block-001"
_WITNESS_FILE_HASH_PAIRS = frozenset(
    {
        (
            "8f6635fc1f12a442f396c79147c9b454d5237165014b6e4b0039379b0f394930",
            "9a9724ea798c15059e06b2bb60aef971ec491af0f43b4a68745b5c0b01e3c507",
        ),
        (
            "a6c2da28a7e542197222fe646305023178606b1febff6954b3f09f8b9eec5f47",
            "0eb7acfdbb5b679171ffa4b898393d2d58fe9300a61f509711b5659dd99f0d9e",
        ),
    }
)

_DESCRIPTOR_ORDER = {
    "method": 0,
    "object": 1,
    "dataset": 2,
    "experiment": 3,
    "metric": 4,
}
_RISK_FLAGS = {
    "comparative_claim",
    "evidence_gap",
    "numeric_claim",
    "source_ambiguity",
    "translation_sensitive",
}


class _HandoffInvalidV1(ValueError):
    pass


class _CommitFailedV1(RuntimeError):
    pass


class _CommitIndeterminateV1(RuntimeError):
    pass


class _DataRootIntegrityLostV1(RuntimeError):
    pass


class _RevisionConflictV1(ValueError):
    pass


class _RegistryConflictV1(ValueError):
    pass


class _RegistryBusyV1(RuntimeError):
    pass


class _RegistryUnavailableV1(RuntimeError):
    pass


def _sqlite_is_busy(error: sqlite3.Error) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    return type(code) is int and code & 0xFF in {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
    }


def _sqlite_is_unavailable(error: sqlite3.Error) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    return type(code) is int and code & 0xFF in {
        sqlite3.SQLITE_CANTOPEN,
        sqlite3.SQLITE_IOERR,
        sqlite3.SQLITE_PERM,
        sqlite3.SQLITE_READONLY,
    }


@dataclass(frozen=True, slots=True)
class _ValidatedHandoffV1:
    action: Literal["accept", "withdraw"]
    candidate_id: str
    payload_sha256: str
    review_revision: int
    review_status: Literal["accepted", "rejected", "deferred"]
    handoff_id: str
    work_id: str
    source_id: str
    source_sha256: str
    canonical_content_sha256: str
    canonical_run_id: str
    semantic_run_id: str
    manifest_sha256: str
    candidates_sha256: str
    manifest: dict[str, object]
    record: dict[str, object]


def _reject_number(_value: str) -> object:
    raise _HandoffInvalidV1("floating-point JSON values are invalid")


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _HandoffInvalidV1("duplicate JSON object key")
        value[key] = item
    return value


def _canonical_payload_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise _HandoffInvalidV1("value is not CanonicalJsonV1") from error


def _decode_canonical_file(payload: bytes) -> dict[str, object]:
    if (
        type(payload) is not bytes
        or not 1 <= len(payload) <= _MAX_HANDOFF_BYTES
        or not payload.endswith(b"\n")
        or payload.startswith(b"\xef\xbb\xbf")
        or b"\r" in payload
        or payload.count(b"\n") != 1
    ):
        raise _HandoffInvalidV1("canonical file framing is invalid")
    try:
        value = json.loads(
            payload[:-1].decode("utf-8"),
            object_pairs_hook=_closed_object,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _HandoffInvalidV1("canonical file JSON is invalid") from error
    if type(value) is not dict or _canonical_payload_bytes(value) + b"\n" != payload:
        raise _HandoffInvalidV1("canonical file bytes are invalid")
    return cast(dict[str, object], value)


def _exact_keys(value: object, expected: set[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != expected:
        raise _HandoffInvalidV1(f"{label} is not a closed object")
    return cast(dict[str, object], value)


def _is_int(value: object, *, minimum: int = 0, maximum: int = _MAX_INT64) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _valid_doi(value: object) -> bool:
    if type(value) is not str:
        return False
    prefix, separator, suffix = value.partition("/")
    if not separator or not suffix or _DOI_PREFIX.fullmatch(prefix) is None:
        return False
    return all(
        category[0] in {"L", "M", "N", "P", "S"} or category == "Zs"
        for category in map(unicodedata.category, suffix)
    )


def _valid_arxiv_id(value: object) -> bool:
    if type(value) is not str:
        return False
    modern = _MODERN_ARXIV.fullmatch(value)
    if modern is not None:
        year_month = int(modern.group("year_month"))
        month = year_month % 100
        number = modern.group("number")
        if not 1 <= month <= 12 or int(number) == 0:
            return False
        if 704 <= year_month <= 1412:
            return len(number) == 4
        if 1501 <= year_month <= 9912:
            return len(number) == 5
        return False

    legacy = _LEGACY_ARXIV.fullmatch(value)
    if legacy is None:
        return False
    year_month = int(legacy.group("year_month"))
    month = year_month % 100
    number = legacy.group("number")
    return (
        1 <= month <= 12
        and int(number) != 0
        and (9107 <= year_month <= 9912 or 1 <= year_month <= 703)
    )


def _valid_canonical_run_id(value: object, *, exact_witness: bool) -> bool:
    return type(value) is str and (
        _CANONICAL_RUN_ID.fullmatch(value) is not None
        or (exact_witness and value == _WITNESS_CANONICAL_RUN_ID)
    )


def _valid_semantic_run_id(value: object, *, exact_witness: bool) -> bool:
    return type(value) is str and (
        _SEMANTIC_RUN_ID.fullmatch(value) is not None
        or (exact_witness and value == _WITNESS_SEMANTIC_RUN_ID)
    )


def _valid_block_id(value: object, *, exact_witness: bool) -> bool:
    return type(value) is str and (
        _BLOCK_ID.fullmatch(value) is not None
        or (exact_witness and value == _WITNESS_BLOCK_ID)
    )


def _valid_normalized_text(
    value: object,
    *,
    minimum: int = 1,
    maximum: int,
) -> bool:
    if type(value) is not str or not minimum <= len(value) <= maximum:
        return False
    if unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    ).strip() != value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return all(
        character != "\x00"
        and unicodedata.category(character) != "Cs"
        and (
            unicodedata.category(character) != "Cc"
            or character in {"\t", "\n"}
        )
        for character in value
    )


def _validate_pointer(
    value: object,
    canonical_sha256: str,
    *,
    exact_witness: bool,
) -> dict[str, object]:
    pointer = _exact_keys(
        value,
        {"block_id", "canonical_content_sha256", "schema_version"},
        "Evidence Pointer",
    )
    if (
        pointer.get("schema_version") != "gezhi.evidence_pointer.v1"
        or not _valid_block_id(
            pointer.get("block_id"),
            exact_witness=exact_witness,
        )
        or pointer.get("canonical_content_sha256") != canonical_sha256
    ):
        raise _HandoffInvalidV1("Evidence Pointer is invalid")
    return pointer


def _validate_sorted_texts(value: object, *, maximum_count: int) -> list[str]:
    if type(value) is not list or len(value) > maximum_count:
        raise _HandoffInvalidV1("text collection is invalid")
    texts = cast(list[object], value)
    if any(not _valid_normalized_text(item, maximum=160) for item in texts):
        raise _HandoffInvalidV1("text collection item is invalid")
    normalized = cast(list[str], texts)
    if len(set(normalized)) != len(normalized) or normalized != sorted(
        normalized, key=lambda item: item.encode("utf-8")
    ):
        raise _HandoffInvalidV1("text collection order is invalid")
    return normalized


def _validate_statement(
    value: object,
    canonical_sha256: str,
    *,
    exact_witness: bool,
) -> dict[str, object]:
    statement = _exact_keys(
        value,
        {
            "evidence_pointers",
            "risk_flags",
            "source_terms",
            "support_kind",
            "text",
        },
        "Candidate statement",
    )
    if (
        not _valid_normalized_text(statement.get("text"), maximum=600)
        or statement.get("support_kind")
        not in {"direct", "synthesized", "interpretive"}
    ):
        raise _HandoffInvalidV1("Candidate statement is invalid")
    _validate_sorted_texts(statement.get("source_terms"), maximum_count=12)
    raw_risks = statement.get("risk_flags")
    if type(raw_risks) is not list:
        raise _HandoffInvalidV1("Review Risk Flags are invalid")
    risks = cast(list[object], raw_risks)
    if (
        len(risks) > 5
        or any(type(item) is not str or item not in _RISK_FLAGS for item in risks)
    ):
        raise _HandoffInvalidV1("Review Risk Flags are invalid")
    risk_values = cast(list[str], risks)
    if len(set(risk_values)) != len(risk_values) or risk_values != sorted(
        risk_values
    ):
        raise _HandoffInvalidV1("Review Risk Flags are invalid")
    raw_pointers = statement.get("evidence_pointers")
    if type(raw_pointers) is not list or not 1 <= len(raw_pointers) <= 6:
        raise _HandoffInvalidV1("statement Evidence Pointers are invalid")
    pointers = [
        _validate_pointer(
            pointer,
            canonical_sha256,
            exact_witness=exact_witness,
        )
        for pointer in cast(list[object], raw_pointers)
    ]
    pointer_keys = [_canonical_payload_bytes(pointer) for pointer in pointers]
    pointer_order = [
        (
            cast(str, pointer["canonical_content_sha256"]).encode("ascii"),
            cast(str, pointer["block_id"]).encode("utf-8"),
        )
        for pointer in pointers
    ]
    if (
        len(set(pointer_keys)) != len(pointer_keys)
        or pointer_order != sorted(pointer_order)
    ):
        raise _HandoffInvalidV1("statement Evidence Pointer order is invalid")
    return statement


def _validate_descriptor_payload(
    value: object,
    canonical_sha256: str,
    *,
    exact_witness: bool,
) -> dict[str, object]:
    payload = _exact_keys(value, {"kind", "schema_version", "value"}, "Descriptor")
    kind = payload.get("kind")
    if (
        type(kind) is not str
        or kind not in _DESCRIPTOR_ORDER
        or payload.get("schema_version") != "gezhi.descriptor_payload.v1"
    ):
        raise _HandoffInvalidV1("Descriptor payload is invalid")
    if kind == "method":
        _validate_statement(
            payload.get("value"),
            canonical_sha256,
            exact_witness=exact_witness,
        )
    else:
        descriptor = _exact_keys(
            payload.get("value"),
            {"evidence_pointers", "label", "source_terms"},
            "Study Descriptor",
        )
        if not _valid_normalized_text(descriptor.get("label"), maximum=160):
            raise _HandoffInvalidV1("Study Descriptor label is invalid")
        _validate_sorted_texts(descriptor.get("source_terms"), maximum_count=12)
        raw_pointers = descriptor.get("evidence_pointers")
        if type(raw_pointers) is not list or not 1 <= len(raw_pointers) <= 6:
            raise _HandoffInvalidV1("Descriptor Evidence Pointers are invalid")
        pointers = [
            _validate_pointer(
                pointer,
                canonical_sha256,
                exact_witness=exact_witness,
            )
            for pointer in cast(list[object], raw_pointers)
        ]
        encoded = [_canonical_payload_bytes(pointer) for pointer in pointers]
        pointer_order = [
            (
                cast(str, pointer["canonical_content_sha256"]).encode("ascii"),
                cast(str, pointer["block_id"]).encode("utf-8"),
            )
            for pointer in pointers
        ]
        if len(set(encoded)) != len(encoded) or pointer_order != sorted(pointer_order):
            raise _HandoffInvalidV1("Descriptor Evidence Pointer order is invalid")
    return payload


def _validate_candidate(
    value: object,
    *,
    exact_witness: bool,
) -> tuple[dict[str, object], dict[str, object]]:
    candidate = _exact_keys(
        value,
        {"candidate_id", "payload", "payload_sha256", "schema_version"},
        "Candidate Knowledge",
    )
    if candidate.get("schema_version") != "gezhi.candidate_knowledge.v1":
        raise _HandoffInvalidV1("Candidate Schema is invalid")
    payload = _exact_keys(
        candidate.get("payload"),
        {
            "candidate_type",
            "canonical_content_sha256",
            "descriptor_refs",
            "schema_version",
            "source_id",
            "source_sha256",
            "statement",
            "work_id",
        },
        "Candidate payload",
    )
    candidate_type = payload.get("candidate_type")
    source_id = payload.get("source_id")
    source_sha256 = payload.get("source_sha256")
    canonical_sha256 = payload.get("canonical_content_sha256")
    work_id = payload.get("work_id")
    if (
        candidate_type not in {"method", "claim", "limitation", "open_question"}
        or payload.get("schema_version") != "gezhi.candidate_payload.v1"
        or type(source_id) is not str
        or _SOURCE_ID.fullmatch(source_id) is None
        or type(source_sha256) is not str
        or _SHA256.fullmatch(source_sha256) is None
        or source_id != "src_" + source_sha256[:24]
        or type(canonical_sha256) is not str
        or _SHA256.fullmatch(canonical_sha256) is None
        or type(work_id) is not str
        or _WORK_ID.fullmatch(work_id) is None
    ):
        raise _HandoffInvalidV1("Candidate payload identity is invalid")
    _validate_statement(
        payload.get("statement"),
        canonical_sha256,
        exact_witness=exact_witness,
    )
    raw_references = payload.get("descriptor_refs")
    if type(raw_references) is not list or len(raw_references) > 6:
        raise _HandoffInvalidV1("Descriptor References are invalid")
    references: list[dict[str, object]] = []
    for raw_reference in cast(list[object], raw_references):
        reference = _exact_keys(
            raw_reference,
            {"descriptor_id", "kind", "payload_sha256", "schema_version"},
            "Descriptor Reference",
        )
        descriptor_id = reference.get("descriptor_id")
        descriptor_sha256 = reference.get("payload_sha256")
        if (
            reference.get("schema_version") != "gezhi.descriptor_reference.v1"
            or reference.get("kind") not in _DESCRIPTOR_ORDER
            or type(descriptor_id) is not str
            or _DESCRIPTOR_ID.fullmatch(descriptor_id) is None
            or type(descriptor_sha256) is not str
            or _SHA256.fullmatch(descriptor_sha256) is None
            or descriptor_id != "desc_" + descriptor_sha256[:24]
        ):
            raise _HandoffInvalidV1("Descriptor Reference is invalid")
        references.append(reference)
    reference_keys = [
        (
            _DESCRIPTOR_ORDER[cast(str, reference["kind"])],
            cast(str, reference["payload_sha256"]),
        )
        for reference in references
    ]
    if len(set(reference_keys)) != len(reference_keys) or reference_keys != sorted(
        reference_keys
    ):
        raise _HandoffInvalidV1("Descriptor Reference order is invalid")
    payload_bytes = _canonical_payload_bytes(payload)
    payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    candidate_id = candidate.get("candidate_id")
    if (
        candidate.get("payload_sha256") != payload_sha256
        or type(candidate_id) is not str
        or candidate_id != "cand_" + payload_sha256[:24]
        or _CANDIDATE_ID.fullmatch(candidate_id) is None
    ):
        raise _HandoffInvalidV1("Candidate content identity is invalid")
    return candidate, payload


def _validate_accept_record(
    record: dict[str, object],
    *,
    exact_witness: bool,
) -> tuple[str, str]:
    _exact_keys(
        record,
        {
            "action",
            "candidate",
            "citation",
            "descriptor_snapshots",
            "evidence_snapshots",
            "review_receipt",
            "schema_version",
        },
        "accept action",
    )
    if (
        record.get("action") != "accept"
        or record.get("schema_version") != "gezhi.reviewed_candidate_action.v1"
    ):
        raise _HandoffInvalidV1("accept action is invalid")
    candidate, payload = _validate_candidate(
        record.get("candidate"),
        exact_witness=exact_witness,
    )
    candidate_id = cast(str, candidate["candidate_id"])
    payload_sha256 = cast(str, candidate["payload_sha256"])
    work_id = cast(str, payload["work_id"])
    source_id = cast(str, payload["source_id"])
    source_sha256 = cast(str, payload["source_sha256"])
    canonical_sha256 = cast(str, payload["canonical_content_sha256"])

    citation = _exact_keys(
        record.get("citation"),
        {
            "arxiv_id",
            "author_count",
            "doi",
            "primary_authors",
            "source_id",
            "source_sha256",
            "title",
            "work_id",
            "year",
        },
        "Citation snapshot",
    )
    author_count = citation.get("author_count")
    primary_authors = citation.get("primary_authors")
    if (
        citation.get("work_id") != work_id
        or citation.get("source_id") != source_id
        or citation.get("source_sha256") != source_sha256
        or not (author_count is None or _is_int(author_count))
        or type(primary_authors) is not list
        or any(
            not _valid_normalized_text(author, maximum=600)
            for author in cast(list[object], primary_authors)
        )
        or (
            author_count is None
            and cast(list[object], primary_authors)
        )
        or (
            type(author_count) is int
            and len(cast(list[object], primary_authors)) != min(3, author_count)
        )
        or not (
            citation.get("title") is None
            or _valid_normalized_text(citation.get("title"), maximum=4096)
        )
        or not (
            citation.get("year") is None
            or _is_int(citation.get("year"), minimum=1000, maximum=9999)
        )
        or not (citation.get("doi") is None or _valid_doi(citation.get("doi")))
        or not (
            citation.get("arxiv_id") is None
            or _valid_arxiv_id(citation.get("arxiv_id"))
        )
    ):
        raise _HandoffInvalidV1("Citation snapshot is invalid")

    raw_references = cast(list[object], payload["descriptor_refs"])
    raw_descriptors = record.get("descriptor_snapshots")
    if type(raw_descriptors) is not list or len(raw_descriptors) != len(raw_references):
        raise _HandoffInvalidV1("Descriptor snapshots are invalid")
    descriptor_payloads: list[dict[str, object]] = []
    for raw_snapshot, raw_reference in zip(
        cast(list[object], raw_descriptors), raw_references, strict=True
    ):
        snapshot = _exact_keys(
            raw_snapshot,
            {"payload", "reference"},
            "Descriptor snapshot",
        )
        if snapshot.get("reference") != raw_reference:
            raise _HandoffInvalidV1("Descriptor snapshot reference differs")
        descriptor_payload = _validate_descriptor_payload(
            snapshot.get("payload"),
            canonical_sha256,
            exact_witness=exact_witness,
        )
        descriptor_sha256 = hashlib.sha256(
            _canonical_payload_bytes(descriptor_payload)
        ).hexdigest()
        reference = cast(dict[str, object], raw_reference)
        if (
            reference.get("payload_sha256") != descriptor_sha256
            or reference.get("descriptor_id") != "desc_" + descriptor_sha256[:24]
            or reference.get("kind") != descriptor_payload.get("kind")
        ):
            raise _HandoffInvalidV1("Descriptor snapshot identity differs")
        descriptor_payloads.append(descriptor_payload)

    pointer_sources: list[dict[str, object]] = [
        cast(dict[str, object], payload["statement"]),
        *[
            cast(dict[str, object], descriptor_payload["value"])
            for descriptor_payload in descriptor_payloads
        ],
    ]
    unique_pointers: dict[bytes, dict[str, object]] = {}
    for source in pointer_sources:
        for raw_pointer in cast(list[object], source["evidence_pointers"]):
            pointer = _validate_pointer(
                raw_pointer,
                canonical_sha256,
                exact_witness=exact_witness,
            )
            unique_pointers[_canonical_payload_bytes(pointer)] = pointer
    expected_pointers = sorted(
        unique_pointers.values(),
        key=lambda pointer: (
            cast(str, pointer["canonical_content_sha256"]).encode("ascii"),
            cast(str, pointer["block_id"]).encode("utf-8"),
        ),
    )
    raw_evidence = record.get("evidence_snapshots")
    if type(raw_evidence) is not list or not 1 <= len(raw_evidence) <= 42:
        raise _HandoffInvalidV1("Evidence snapshots are invalid")
    observed_pointers: list[dict[str, object]] = []
    for raw_snapshot in cast(list[object], raw_evidence):
        snapshot = _exact_keys(
            raw_snapshot,
            {"excerpt", "page_index", "pointer"},
            "Evidence snapshot",
        )
        if (
            not _valid_normalized_text(snapshot.get("excerpt"), maximum=800)
            or not (
                snapshot.get("page_index") is None
                or _is_int(snapshot.get("page_index"))
            )
        ):
            raise _HandoffInvalidV1("Evidence snapshot is invalid")
        observed_pointers.append(
            _validate_pointer(
                snapshot.get("pointer"),
                canonical_sha256,
                exact_witness=exact_witness,
            )
        )
    if observed_pointers != expected_pointers:
        raise _HandoffInvalidV1("Evidence snapshot coverage differs")
    return candidate_id, payload_sha256


def _validate_handoff(handoff: ReviewedHandoffBytesV1) -> _ValidatedHandoffV1:
    if type(handoff) is not ReviewedHandoffBytesV1:
        raise _HandoffInvalidV1("KnowledgeIntake input is invalid")
    manifest_sha256 = hashlib.sha256(handoff.manifest_bytes).hexdigest()
    candidates_sha256 = hashlib.sha256(handoff.candidates_bytes).hexdigest()
    exact_witness = (
        manifest_sha256,
        candidates_sha256,
    ) in _WITNESS_FILE_HASH_PAIRS
    manifest = _decode_canonical_file(handoff.manifest_bytes)
    record = _decode_canonical_file(handoff.candidates_bytes)
    manifest = _exact_keys(
        manifest,
        {
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
        },
        "Reviewed Handoff manifest",
    )
    work_id = manifest.get("work_id")
    source_id = manifest.get("source_id")
    source_sha256 = manifest.get("source_sha256")
    canonical_sha256 = manifest.get("canonical_content_sha256")
    handoff_id = manifest.get("handoff_id")
    canonical_run_id = manifest.get("canonical_run_id")
    provenance = _exact_keys(
        manifest.get("provenance"),
        {"canonical_run_id", "semantic_run_id"},
        "Reviewed Handoff provenance",
    )
    if (
        manifest.get("schema_version") != "gezhi.reviewed_handoff_manifest.v1"
        or manifest.get("record_count") != 1
        or type(work_id) is not str
        or _WORK_ID.fullmatch(work_id) is None
        or type(source_id) is not str
        or _SOURCE_ID.fullmatch(source_id) is None
        or type(source_sha256) is not str
        or _SHA256.fullmatch(source_sha256) is None
        or source_id != "src_" + source_sha256[:24]
        or type(canonical_sha256) is not str
        or _SHA256.fullmatch(canonical_sha256) is None
        or type(handoff_id) is not str
        or _HANDOFF_ID.fullmatch(handoff_id) is None
        or not _valid_canonical_run_id(
            canonical_run_id,
            exact_witness=exact_witness,
        )
        or provenance.get("canonical_run_id") != canonical_run_id
        or not _valid_semantic_run_id(
            provenance.get("semantic_run_id"),
            exact_witness=exact_witness,
        )
        or manifest.get("candidates_sha256") != candidates_sha256
    ):
        raise _HandoffInvalidV1("Reviewed Handoff manifest is invalid")

    action = record.get("action")
    if action == "accept":
        candidate_id, payload_sha256 = _validate_accept_record(
            record,
            exact_witness=exact_witness,
        )
        candidate = cast(dict[str, object], record["candidate"])
        payload = cast(dict[str, object], candidate["payload"])
        if (
            payload.get("work_id") != work_id
            or payload.get("source_id") != source_id
            or payload.get("source_sha256") != source_sha256
            or payload.get("canonical_content_sha256") != canonical_sha256
        ):
            raise _HandoffInvalidV1("Candidate and manifest identity differ")
    elif action == "withdraw":
        _exact_keys(
            record,
            {
                "action",
                "candidate_id",
                "payload_sha256",
                "review_receipt",
                "schema_version",
            },
            "withdraw action",
        )
        raw_candidate_id = record.get("candidate_id")
        raw_payload_sha256 = record.get("payload_sha256")
        if (
            record.get("schema_version")
            != "gezhi.reviewed_candidate_action.v1"
            or type(raw_candidate_id) is not str
            or _CANDIDATE_ID.fullmatch(raw_candidate_id) is None
            or type(raw_payload_sha256) is not str
            or _SHA256.fullmatch(raw_payload_sha256) is None
            or raw_candidate_id != "cand_" + raw_payload_sha256[:24]
        ):
            raise _HandoffInvalidV1("withdraw action identity is invalid")
        candidate_id = cast(str, raw_candidate_id)
        payload_sha256 = cast(str, raw_payload_sha256)
    else:
        raise _HandoffInvalidV1("Reviewed Handoff action is invalid")
    review_receipt = _exact_keys(
        record.get("review_receipt"),
        {"review_revision", "review_status", "reviewer_kind"},
        "Review receipt",
    )
    revision = review_receipt.get("review_revision")
    if (
        not _is_int(revision, minimum=1)
        or (
            action == "accept"
            and review_receipt.get("review_status") != "accepted"
        )
        or (
            action == "withdraw"
            and review_receipt.get("review_status") not in {"rejected", "deferred"}
        )
        or review_receipt.get("reviewer_kind") != "local_human_cli"
    ):
        raise _HandoffInvalidV1("Review receipt is invalid")
    identity = {
        "action": action,
        "candidate_id": candidate_id,
        "payload_sha256": payload_sha256,
        "review_revision": revision,
        "schema_version": "gezhi.reviewed_handoff_identity.v1",
    }
    expected_handoff_id = "hnd_" + hashlib.sha256(
        _canonical_payload_bytes(identity)
    ).hexdigest()[:24]
    if handoff_id != expected_handoff_id:
        raise _HandoffInvalidV1("Reviewed Handoff identity is invalid")
    return _ValidatedHandoffV1(
        action=cast(Literal["accept", "withdraw"], action),
        candidate_id=candidate_id,
        payload_sha256=payload_sha256,
        review_revision=cast(int, revision),
        review_status=cast(
            Literal["accepted", "rejected", "deferred"],
            review_receipt["review_status"],
        ),
        handoff_id=handoff_id,
        work_id=work_id,
        source_id=source_id,
        source_sha256=source_sha256,
        canonical_content_sha256=canonical_sha256,
        canonical_run_id=cast(str, canonical_run_id),
        semantic_run_id=cast(str, provenance["semantic_run_id"]),
        manifest_sha256=manifest_sha256,
        candidates_sha256=candidates_sha256,
        manifest=manifest,
        record=record,
    )


def _root_checkpoint(root: ValidatedDataRootV1) -> None:
    expected = root.inspection
    path = expected.canonical_path
    if path is None:
        raise RuntimeError("validated Knowledge root is incomplete")
    try:
        with open_validated_data_root_v1(path) as current:
            observed = current.inspection
    except DataRootOpenErrorV1 as error:
        raise _DataRootIntegrityLostV1("Knowledge root proof was lost") from error
    if (
        observed.identity != expected.identity
        or observed.ancestor_identities != expected.ancestor_identities
        or observed.canonical_path is None
        or ntpath.normcase(observed.canonical_path) != ntpath.normcase(path)
    ):
        raise _DataRootIntegrityLostV1("Knowledge root identity changed")


def _ensure_plain_directory(path: Path) -> None:
    try:
        with open_validated_data_root_v1(str(path.parent)):
            try:
                path.mkdir()
            except FileExistsError:
                pass
            with open_validated_data_root_v1(str(path)):
                pass
    except (DataRootOpenErrorV1, OSError) as error:
        raise _CommitFailedV1("Knowledge directory publication failed") from error


def _read_safe_bytes(path: Path, *, limit: int) -> bytes:
    try:
        with open_validated_local_file_v1(str(path)) as source:
            if source.size > limit:
                raise _HandoffInvalidV1("Knowledge import evidence is too large")
            return b"".join(source.iter_verified_chunks_v1())
    except DataRootOpenErrorV1 as error:
        raise _HandoffInvalidV1("Knowledge import evidence is unsafe") from error


def _write_new_verified(path: Path, payload: bytes) -> None:
    try:
        with open_validated_data_root_v1(str(path.parent)), path.open(
            "xb", buffering=0
        ) as destination:
            view = memoryview(payload)
            offset = 0
            while offset < len(view):
                count = destination.write(view[offset:])
                if type(count) is not int or not 1 <= count <= len(view) - offset:
                    raise OSError("Knowledge write did not complete")
                offset += count
        if _read_safe_bytes(path, limit=len(payload)) != payload:
            raise OSError("Knowledge write readback differs")
    except (OSError, ValueError, DataRootOpenErrorV1) as error:
        raise _CommitFailedV1("Knowledge evidence write failed") from error


def _inspect_import_directory(
    path: Path,
    handoff: ReviewedHandoffBytesV1,
) -> Literal["missing", "exact", "conflict"]:
    try:
        with open_validated_data_root_v1(str(path)) as directory:
            if set(directory.relative_entry_names_v1()) != {
                "candidates.jsonl",
                "manifest.json",
            }:
                return "conflict"
        observed = ReviewedHandoffBytesV1(
            manifest_bytes=_read_safe_bytes(
                path / "manifest.json", limit=_MAX_HANDOFF_BYTES
            ),
            candidates_bytes=_read_safe_bytes(
                path / "candidates.jsonl", limit=_MAX_HANDOFF_BYTES
            ),
        )
    except DataRootOpenErrorV1 as error:
        if not path.exists():
            return "missing"
        if error.status == "unsafe":
            raise _HandoffInvalidV1(
                "Knowledge import target is unsafe"
            ) from error
        raise _CommitIndeterminateV1("Knowledge import target is unavailable") from error
    except FileNotFoundError:
        return "missing"
    return "exact" if observed == handoff else "conflict"


def _commit_or_reuse_evidence(
    root: ValidatedDataRootV1,
    handoff: ReviewedHandoffBytesV1,
    validated: _ValidatedHandoffV1,
) -> None:
    root_path_text = root.inspection.canonical_path
    if root_path_text is None:
        raise RuntimeError("validated Knowledge root is incomplete")
    root_path = Path(root_path_text)
    imports = root_path / "imports"
    staging = imports / ".staging"
    private_files = staging / ".files"
    formal = imports / validated.handoff_id
    _ensure_plain_directory(imports)
    _ensure_plain_directory(staging)
    _ensure_plain_directory(private_files)
    stage = staging / validated.handoff_id
    state = _inspect_import_directory(formal, handoff)
    if state == "exact":
        if _inspect_import_directory(stage, handoff) != "missing":
            raise _HandoffInvalidV1(
                "formal Knowledge evidence has contradictory staging"
            )
        return
    if state == "conflict":
        raise _RevisionConflictV1("immutable Knowledge import evidence conflicts")

    staged_state = _inspect_import_directory(stage, handoff)
    if staged_state == "conflict":
        raise _HandoffInvalidV1("Knowledge import staging conflicts")
    if staged_state == "missing":
        try:
            stage.mkdir()
            with open_validated_data_root_v1(str(stage)):
                pass
        except (FileExistsError, DataRootOpenErrorV1, OSError) as error:
            raise _HandoffInvalidV1("Knowledge import staging conflicts") from error
        for name, payload in (
            ("candidates.jsonl", handoff.candidates_bytes),
            ("manifest.json", handoff.manifest_bytes),
        ):
            temporary = private_files / (
                f"{validated.handoff_id}.{name}.{uuid.uuid4().hex}.tmp"
            )
            _write_new_verified(temporary, payload)
            try:
                os.rename(temporary, stage / name)
            except OSError as error:
                raise _CommitIndeterminateV1(
                    "Knowledge evidence file commit is uncertain"
                ) from error
            if _read_safe_bytes(stage / name, limit=len(payload)) != payload:
                raise _CommitIndeterminateV1("Knowledge staged evidence differs")
    try:
        os.rename(stage, formal)
    except OSError as error:
        formal_state = _inspect_import_directory(formal, handoff)
        staged_state = _inspect_import_directory(stage, handoff)
        if formal_state == "exact" and staged_state == "missing":
            _root_checkpoint(root)
            return
        if formal_state == "conflict":
            raise _RevisionConflictV1(
                "immutable Knowledge import evidence conflicts"
            ) from error
        raise _CommitIndeterminateV1(
            "Knowledge evidence directory commit is uncertain"
        ) from error
    if _inspect_import_directory(formal, handoff) != "exact":
        raise _CommitIndeterminateV1("Knowledge formal evidence cannot be proven")
    _root_checkpoint(root)


_BASE_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE registry_meta (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        schema_version TEXT NOT NULL CHECK (
            schema_version = 'gezhi.candidate_registry.v1'
        ),
        generation INTEGER NOT NULL CHECK (generation >= 0)
    ) STRICT
    """,
    """
    CREATE TABLE candidate_content (
        candidate_id TEXT PRIMARY KEY,
        payload_sha256 TEXT NOT NULL UNIQUE,
        candidate_json BLOB NOT NULL,
        citation_json BLOB NOT NULL,
        descriptor_snapshots_json BLOB NOT NULL,
        evidence_snapshots_json BLOB NOT NULL,
        work_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_sha256 TEXT NOT NULL,
        canonical_content_sha256 TEXT NOT NULL,
        content_handoff_id TEXT NOT NULL,
        content_manifest_sha256 TEXT NOT NULL,
        content_candidates_sha256 TEXT NOT NULL,
        promotion_status TEXT NOT NULL CHECK (
            promotion_status = 'not_promoted'
        )
    ) STRICT
    """,
    """
    CREATE TABLE handoff_revisions (
        handoff_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        review_revision INTEGER NOT NULL CHECK (review_revision >= 1),
        action TEXT NOT NULL CHECK (action IN ('accept', 'withdraw')),
        review_status TEXT NOT NULL CHECK (
            review_status IN ('accepted', 'rejected', 'deferred')
        ),
        work_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_sha256 TEXT NOT NULL,
        canonical_content_sha256 TEXT NOT NULL,
        canonical_run_id TEXT NOT NULL,
        semantic_run_id TEXT NOT NULL,
        manifest_sha256 TEXT NOT NULL,
        candidates_sha256 TEXT NOT NULL,
        UNIQUE (candidate_id, review_revision),
        FOREIGN KEY (candidate_id) REFERENCES candidate_content(candidate_id)
    ) STRICT
    """,
    """
    CREATE TABLE candidate_current (
        candidate_id TEXT PRIMARY KEY,
        review_revision INTEGER NOT NULL CHECK (review_revision >= 1),
        review_status TEXT NOT NULL CHECK (
            review_status IN ('accepted', 'rejected', 'deferred')
        ),
        intake_status TEXT NOT NULL CHECK (
            intake_status IN ('active', 'withdrawn')
        ),
        status_handoff_id TEXT NOT NULL UNIQUE,
        FOREIGN KEY (candidate_id) REFERENCES candidate_content(candidate_id),
        FOREIGN KEY (status_handoff_id) REFERENCES handoff_revisions(handoff_id)
    ) STRICT
    """,
)
_SCHEMA_STATEMENTS = (*_BASE_SCHEMA_STATEMENTS, *SEARCH_PROJECTION_SCHEMA_STATEMENTS)


def _schema_rows(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    return tuple(
        connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_schema
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type COLLATE BINARY, name COLLATE BINARY
            """
        ).fetchall()
    )


def _expected_schema_rows_for(
    statements: tuple[str, ...],
) -> tuple[tuple[object, ...], ...]:
    expected = sqlite3.connect(":memory:", isolation_level=None)
    try:
        expected.execute("PRAGMA foreign_keys = ON")
        for statement in statements:
            expected.execute(statement)
        return _schema_rows(expected)
    finally:
        expected.close()


def _expected_base_schema_rows() -> tuple[tuple[object, ...], ...]:
    return _expected_schema_rows_for(_BASE_SCHEMA_STATEMENTS)


def _expected_schema_rows() -> tuple[tuple[object, ...], ...]:
    return _expected_schema_rows_for(_SCHEMA_STATEMENTS)


def _validate_registry_schema(connection: sqlite3.Connection) -> None:
    _validate_registry_schema_generation(
        connection,
        expected_schema_rows=_expected_schema_rows(),
    )


def _validate_base_registry_schema(connection: sqlite3.Connection) -> None:
    _validate_registry_schema_generation(
        connection,
        expected_schema_rows=_expected_base_schema_rows(),
    )


def _validate_registry_schema_generation(
    connection: sqlite3.Connection,
    *,
    expected_schema_rows: tuple[tuple[object, ...], ...],
) -> None:
    try:
        if (
            connection.execute("PRAGMA application_id").fetchone()
            != (_APPLICATION_ID,)
            or connection.execute("PRAGMA user_version").fetchone()
            != (_USER_VERSION,)
            or connection.execute("PRAGMA foreign_keys").fetchone() != (1,)
            or _schema_rows(connection) != expected_schema_rows
            or connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]
            or connection.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise _RegistryConflictV1("Candidate Registry schema is invalid")
        meta = connection.execute(
            "SELECT singleton, schema_version, generation FROM registry_meta"
        ).fetchall()
        revision_count = cast(
            int,
            connection.execute("SELECT count(*) FROM handoff_revisions").fetchone()[
                0
            ],
        )
        if (
            len(meta) != 1
            or meta[0][0] != 1
            or meta[0][1] != _SCHEMA_VERSION
            or type(meta[0][2]) is not int
            or meta[0][2] < 0
            or meta[0][2] != revision_count
        ):
            raise _RegistryConflictV1("Candidate Registry metadata is invalid")
    except sqlite3.Error as error:
        if _sqlite_is_busy(error):
            raise _RegistryBusyV1("Candidate Registry is busy") from error
        raise _RegistryConflictV1("Candidate Registry cannot be validated") from error


def _rebuild_search_projection_v1(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT content.candidate_id, content.payload_sha256,
               content.candidate_json, content.citation_json,
               content.descriptor_snapshots_json,
               content.evidence_snapshots_json,
               content.work_id, content.source_id, content.source_sha256,
               content.canonical_content_sha256,
               content.content_manifest_sha256,
               content.content_candidates_sha256,
               content.promotion_status, current.review_status,
               current.intake_status
        FROM candidate_content AS content
        JOIN candidate_current AS current USING(candidate_id)
        WHERE current.intake_status = 'active'
        ORDER BY content.candidate_id COLLATE BINARY ASC
        """
    ).fetchall()
    for row in rows:
        try:
            candidate = decode_canonical_json_blob_v1(row[2])
            citation = decode_canonical_json_blob_v1(row[3])
            descriptor_snapshots = decode_canonical_json_blob_v1(row[4])
            evidence_snapshots = decode_canonical_json_blob_v1(row[5])
        except ValueError as error:
            raise _RegistryConflictV1(
                "Candidate search projection source is invalid"
            ) from error
        if (
            type(candidate) is not dict
            or type(citation) is not dict
            or type(descriptor_snapshots) is not list
            or type(evidence_snapshots) is not list
        ):
            raise _RegistryConflictV1("Candidate search projection source is invalid")
        synthetic_record: dict[str, object] = {
            "action": "accept",
            "candidate": candidate,
            "citation": citation,
            "descriptor_snapshots": descriptor_snapshots,
            "evidence_snapshots": evidence_snapshots,
            "review_receipt": {},
            "schema_version": "gezhi.reviewed_candidate_action.v1",
        }
        exact_witness = (row[10], row[11]) in _WITNESS_FILE_HASH_PAIRS
        candidate_id, payload_sha256 = _validate_accept_record(
            synthetic_record,
            exact_witness=exact_witness,
        )
        payload = cast(dict[str, object], candidate["payload"])
        if (
            candidate_id != row[0]
            or payload_sha256 != row[1]
            or payload.get("work_id") != row[6]
            or payload.get("source_id") != row[7]
            or payload.get("source_sha256") != row[8]
            or payload.get("canonical_content_sha256") != row[9]
            or row[12:] != ("not_promoted", "accepted", "active")
        ):
            raise _RegistryConflictV1(
                "Candidate search projection source differs"
            )
        replace_active_search_document_v1(
            connection,
            candidate_id=candidate_id,
            candidate=candidate,
            citation=citation,
            descriptor_snapshots=descriptor_snapshots,
        )


def _open_registry(path: Path) -> tuple[sqlite3.Connection, ValidatedFileV1]:
    try:
        path.lstat()
    except FileNotFoundError:
        try:
            with path.open("xb", buffering=0):
                pass
        except FileExistsError:
            pass
        except OSError as error:
            raise _RegistryUnavailableV1(
                "Candidate Registry cannot be created"
            ) from error
    except OSError as error:
        raise _RegistryUnavailableV1(
            "Candidate Registry path is unavailable"
        ) from error

    connection: sqlite3.Connection | None = None
    guard: ValidatedFileV1 | None = None
    try:
        guard = open_validated_mutable_local_file_v1(str(path))
        connection = sqlite3.connect(
            path,
            timeout=0.25,
            isolation_level=None,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 250")
        guard.revalidate_identity_v1()
        return connection, guard
    except DataRootOpenErrorV1 as error:
        if connection is not None:
            connection.close()
        if guard is not None:
            guard.close()
        raise _RegistryUnavailableV1(
            "Candidate Registry path cannot be proven"
        ) from error
    except sqlite3.Error as error:
        if connection is not None:
            connection.close()
        if guard is not None:
            guard.close()
        if _sqlite_is_busy(error):
            raise _RegistryBusyV1("Candidate Registry is busy") from error
        if _sqlite_is_unavailable(error):
            raise _RegistryUnavailableV1(
                "Candidate Registry cannot be opened"
            ) from error
        raise _RegistryConflictV1(
            "Candidate Registry cannot be initialized"
        ) from error


def _require_exact_projection_upgrade_replay_v1(
    connection: sqlite3.Connection,
    validated: _ValidatedHandoffV1,
    imports_root: Path,
) -> tuple[str, ...]:
    try:
        candidate_rows = connection.execute(
            "SELECT candidate_id FROM candidate_content "
            "ORDER BY candidate_id COLLATE BINARY"
        ).fetchall()
        candidate_ids: list[str] = []
        for row in candidate_rows:
            if (
                type(row) is not tuple
                or len(row) != 1
                or type(row[0]) is not str
                or _CANDIDATE_ID.fullmatch(row[0]) is None
            ):
                raise _RegistryConflictV1(
                    "Candidate Registry replay identity is invalid"
                )
            candidate_id = cast(str, row[0])
            _verify_candidate_import_history(
                connection,
                imports_root,
                candidate_id,
                allow_historical_content_projection=True,
            )
            candidate_ids.append(candidate_id)
        recorded = connection.execute(
            """
            SELECT candidate_id, payload_sha256, review_revision, action,
                   review_status, work_id, source_id, source_sha256,
                   canonical_content_sha256, canonical_run_id, semantic_run_id,
                   manifest_sha256, candidates_sha256
            FROM handoff_revisions WHERE handoff_id = ?
            """,
            (validated.handoff_id,),
        ).fetchone()
    except (_RegistryBusyV1, _RegistryConflictV1):
        raise
    except sqlite3.Error as error:
        if _sqlite_is_busy(error):
            raise _RegistryBusyV1("Candidate Registry is busy") from error
        raise _RegistryConflictV1(
            "Candidate Registry replay cannot be verified"
        ) from error
    expected = (
        validated.candidate_id,
        validated.payload_sha256,
        validated.review_revision,
        validated.action,
        validated.review_status,
        validated.work_id,
        validated.source_id,
        validated.source_sha256,
        validated.canonical_content_sha256,
        validated.canonical_run_id,
        validated.semantic_run_id,
        validated.manifest_sha256,
        validated.candidates_sha256,
    )
    if recorded != expected:
        raise _RegistryConflictV1(
            "search projection upgrade requires an exact Handoff replay"
        )
    return tuple(candidate_ids)


def _bootstrap_registry(
    connection: sqlite3.Connection,
    validated: _ValidatedHandoffV1,
    imports_root: Path,
) -> None:
    try:
        application_id = cast(
            int,
            connection.execute("PRAGMA application_id").fetchone()[0],
        )
        user_version = cast(
            int,
            connection.execute("PRAGMA user_version").fetchone()[0],
        )
        user_objects = connection.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' "
            "AND type IN ('table', 'index', 'view', 'trigger')"
        ).fetchall()
    except sqlite3.Error as error:
        if _sqlite_is_busy(error):
            raise _RegistryBusyV1("Candidate Registry is busy") from error
        if _sqlite_is_unavailable(error):
            raise _RegistryUnavailableV1(
                "Candidate Registry is unavailable"
            ) from error
        raise _RegistryConflictV1(
            "Candidate Registry header is invalid"
        ) from error
    if user_version == 1 and application_id == _APPLICATION_ID:
        observed_schema = _schema_rows(connection)
        if observed_schema == _expected_schema_rows():
            _validate_registry_schema(connection)
            return
        if observed_schema != _expected_base_schema_rows():
            raise _RegistryConflictV1("Candidate Registry schema is invalid")
        _validate_base_registry_schema(connection)
        try:
            connection.execute("BEGIN IMMEDIATE")
            _validate_base_registry_schema(connection)
            candidate_ids = _require_exact_projection_upgrade_replay_v1(
                connection,
                validated,
                imports_root,
            )
            for candidate_id in candidate_ids:
                _rebuild_current_projection(connection, candidate_id)
                _rebuild_content_import_projection(connection, candidate_id)
            for statement in SEARCH_PROJECTION_SCHEMA_STATEMENTS:
                connection.execute(statement)
            generation = connection.execute(
                "SELECT generation FROM registry_meta WHERE singleton = 1"
            ).fetchone()
            if (
                generation is None
                or len(generation) != 1
                or type(generation[0]) is not int
            ):
                raise _RegistryConflictV1(
                    "Candidate Registry generation is invalid"
                )
            connection.execute(
                "INSERT INTO registry_search_meta("
                "singleton, schema_version, registry_generation"
                ") VALUES (1, ?, ?)",
                (SEARCH_PROJECTION_SCHEMA_VERSION, generation[0]),
            )
            _rebuild_search_projection_v1(connection)
            _commit_registry_transaction(connection)
        except (_HandoffInvalidV1, _RegistryConflictV1):
            _rollback_registry_transaction(connection)
            raise
        except sqlite3.Error as error:
            _rollback_registry_transaction(connection)
            if _sqlite_is_busy(error):
                raise _RegistryBusyV1("Candidate Registry is busy") from error
            if _sqlite_is_unavailable(error):
                raise _RegistryUnavailableV1(
                    "Candidate Registry projection migration is unavailable"
                ) from error
            raise _CommitFailedV1(
                "Candidate Registry projection migration failed"
            ) from error
        _validate_registry_schema(connection)
        return
    if user_version != 0 or application_id not in {0, _APPLICATION_ID} or user_objects:
        raise _RegistryConflictV1("Candidate Registry migration baseline conflicts")
    try:
        connection.execute("BEGIN IMMEDIATE")
        for statement in _SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO registry_meta(singleton, schema_version, generation) "
            "VALUES (1, ?, 0)",
            (_SCHEMA_VERSION,),
        )
        connection.execute(
            "INSERT INTO registry_search_meta("
            "singleton, schema_version, registry_generation"
            ") VALUES (1, ?, 0)",
            (SEARCH_PROJECTION_SCHEMA_VERSION,),
        )
        connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {_USER_VERSION}")
        _commit_registry_transaction(connection)
    except sqlite3.Error as error:
        _rollback_registry_transaction(connection)
        if _sqlite_is_busy(error):
            raise _RegistryBusyV1("Candidate Registry is busy") from error
        if _sqlite_is_unavailable(error):
            raise _RegistryUnavailableV1(
                "Candidate Registry migration is unavailable"
            ) from error
        raise _CommitFailedV1("Candidate Registry migration failed") from error
    _validate_registry_schema(connection)


def _rebuild_current_projection(
    connection: sqlite3.Connection,
    candidate_id: str,
) -> None:
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
    if latest is None:
        connection.execute(
            "DELETE FROM candidate_current WHERE candidate_id = ?",
            (candidate_id,),
        )
        return
    revision, review_status, action, handoff_id = latest
    if (
        not _is_int(revision, minimum=1)
        or (
            action == "accept"
            and review_status != "accepted"
        )
        or (
            action == "withdraw"
            and review_status not in {"rejected", "deferred"}
        )
        or action not in {"accept", "withdraw"}
        or type(handoff_id) is not str
    ):
        raise _RegistryConflictV1("Candidate revision history is invalid")
    intake_status = "active" if action == "accept" else "withdrawn"
    connection.execute(
        """
        INSERT INTO candidate_current(
            candidate_id, review_revision, review_status,
            intake_status, status_handoff_id
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(candidate_id) DO UPDATE SET
            review_revision = excluded.review_revision,
            review_status = excluded.review_status,
            intake_status = excluded.intake_status,
            status_handoff_id = excluded.status_handoff_id
        """,
        (
            candidate_id,
            revision,
            review_status,
            intake_status,
            handoff_id,
        ),
    )


def _rebuild_content_import_projection(
    connection: sqlite3.Connection,
    candidate_id: str,
) -> None:
    latest_accept = connection.execute(
        """
        SELECT handoff_id, manifest_sha256, candidates_sha256
        FROM handoff_revisions
        WHERE candidate_id = ? AND action = 'accept'
        ORDER BY review_revision DESC
        LIMIT 1
        """,
        (candidate_id,),
    ).fetchone()
    if latest_accept is None:
        raise _RegistryConflictV1("Candidate has no accepted content import")
    cursor = connection.execute(
        """
        UPDATE candidate_content
        SET content_handoff_id = ?, content_manifest_sha256 = ?,
            content_candidates_sha256 = ?
        WHERE candidate_id = ?
        """,
        (*latest_accept, candidate_id),
    )
    if cursor.rowcount != 1:
        raise _RegistryConflictV1("Candidate content projection is missing")


def _synchronize_candidate_search_projection_v1(
    connection: sqlite3.Connection,
    candidate_id: str,
) -> None:
    row = connection.execute(
        """
        SELECT content.candidate_json, content.citation_json,
               content.descriptor_snapshots_json, content.promotion_status,
               current.review_status, current.intake_status
        FROM candidate_content AS content
        JOIN candidate_current AS current USING(candidate_id)
        WHERE content.candidate_id = ?
        """,
        (candidate_id,),
    ).fetchone()
    if row is None or len(row) != 6 or row[3] != "not_promoted":
        raise _RegistryConflictV1("Candidate search projection source is invalid")
    if row[4:] == ("accepted", "active"):
        try:
            candidate = decode_canonical_json_blob_v1(row[0])
            citation = decode_canonical_json_blob_v1(row[1])
            descriptor_snapshots = decode_canonical_json_blob_v1(row[2])
        except ValueError as error:
            raise _RegistryConflictV1(
                "Candidate search projection source is invalid"
            ) from error
        if (
            type(candidate) is not dict
            or type(citation) is not dict
            or type(descriptor_snapshots) is not list
        ):
            raise _RegistryConflictV1(
                "Candidate search projection source is invalid"
            )
        replace_active_search_document_v1(
            connection,
            candidate_id=candidate_id,
            candidate=candidate,
            citation=citation,
            descriptor_snapshots=descriptor_snapshots,
        )
        return
    if row[4] in {"rejected", "deferred"} and row[5] == "withdrawn":
        remove_search_document_v1(connection, candidate_id=candidate_id)
        return
    raise _RegistryConflictV1("Candidate search governance is invalid")


def _commit_registry_transaction(connection: sqlite3.Connection) -> None:
    try:
        connection.commit()
    except sqlite3.Error as error:
        raise _CommitIndeterminateV1(
            "Candidate Registry commit is uncertain"
        ) from error


def _rollback_registry_transaction(connection: sqlite3.Connection) -> None:
    try:
        connection.rollback()
    except sqlite3.Error as error:
        raise _CommitIndeterminateV1(
            "Candidate Registry rollback is uncertain"
        ) from error


def _accepted_content_values(
    validated: _ValidatedHandoffV1,
) -> tuple[object, ...]:
    if validated.action != "accept":
        raise _RegistryConflictV1("Candidate content has no accepted Handoff")
    record = validated.record
    candidate = cast(dict[str, object], record["candidate"])
    citation = cast(dict[str, object], record["citation"])
    descriptor_snapshots = cast(list[object], record["descriptor_snapshots"])
    evidence_snapshots = cast(list[object], record["evidence_snapshots"])
    return (
        validated.payload_sha256,
        _canonical_payload_bytes(candidate),
        _canonical_payload_bytes(citation),
        _canonical_payload_bytes(descriptor_snapshots),
        _canonical_payload_bytes(evidence_snapshots),
        validated.work_id,
        validated.source_id,
        validated.source_sha256,
        validated.canonical_content_sha256,
        "not_promoted",
    )


def _stored_content_values(validated: _ValidatedHandoffV1) -> tuple[object, ...]:
    accepted = _accepted_content_values(validated)
    return (
        *accepted[:-1],
        validated.handoff_id,
        validated.manifest_sha256,
        validated.candidates_sha256,
        accepted[-1],
    )


def _verify_candidate_import_history(
    connection: sqlite3.Connection,
    imports_root: Path,
    candidate_id: str,
    *,
    allow_historical_content_projection: bool = False,
) -> None:
    rows = connection.execute(
        """
        SELECT handoff_id, candidate_id, payload_sha256, review_revision,
               action, review_status, work_id, source_id, source_sha256,
               canonical_content_sha256, canonical_run_id, semantic_run_id,
               manifest_sha256, candidates_sha256
        FROM handoff_revisions
        WHERE candidate_id = ?
        ORDER BY review_revision ASC
        """,
        (candidate_id,),
    ).fetchall()
    stored_content = connection.execute(
        """
        SELECT payload_sha256, candidate_json, citation_json,
               descriptor_snapshots_json, evidence_snapshots_json,
               work_id, source_id, source_sha256,
               canonical_content_sha256, content_handoff_id,
               content_manifest_sha256, content_candidates_sha256,
               promotion_status
        FROM candidate_content
        WHERE candidate_id = ?
        """,
        (candidate_id,),
    ).fetchone()
    immutable_content: tuple[object, ...] | None = None
    latest_content_projection: tuple[object, ...] | None = None
    historical_content_projections: set[tuple[object, ...]] = set()
    for row in rows:
        handoff_id = row[0]
        if type(handoff_id) is not str or _HANDOFF_ID.fullmatch(handoff_id) is None:
            raise _RegistryConflictV1("Registry Handoff identity is invalid")
        formal = imports_root / handoff_id
        try:
            with open_validated_data_root_v1(str(formal)) as directory:
                if set(directory.relative_entry_names_v1()) != {
                    "candidates.jsonl",
                    "manifest.json",
                }:
                    raise _RegistryConflictV1(
                        "Registry import evidence namespace is invalid"
                    )
            evidence = ReviewedHandoffBytesV1(
                manifest_bytes=_read_safe_bytes(
                    formal / "manifest.json", limit=_MAX_HANDOFF_BYTES
                ),
                candidates_bytes=_read_safe_bytes(
                    formal / "candidates.jsonl", limit=_MAX_HANDOFF_BYTES
                ),
            )
            observed = _validate_handoff(evidence)
        except (
            DataRootOpenErrorV1,
            FileNotFoundError,
            _HandoffInvalidV1,
        ) as error:
            raise _RegistryConflictV1(
                "Registry import evidence cannot be verified"
            ) from error
        if row != (
            observed.handoff_id,
            observed.candidate_id,
            observed.payload_sha256,
            observed.review_revision,
            observed.action,
            observed.review_status,
            observed.work_id,
            observed.source_id,
            observed.source_sha256,
            observed.canonical_content_sha256,
            observed.canonical_run_id,
            observed.semantic_run_id,
            observed.manifest_sha256,
            observed.candidates_sha256,
        ):
            raise _RegistryConflictV1(
                "Registry row and immutable import evidence differ"
            )
        if observed.action == "accept":
            observed_content = _accepted_content_values(observed)
            if immutable_content is None:
                immutable_content = observed_content
            elif observed_content != immutable_content:
                raise _RegistryConflictV1(
                    "Accepted Candidate snapshots changed across revisions"
                )
            latest_content_projection = _stored_content_values(observed)
            historical_content_projections.add(latest_content_projection)
        elif immutable_content is None or (
            observed.payload_sha256,
            observed.work_id,
            observed.source_id,
            observed.source_sha256,
            observed.canonical_content_sha256,
        ) != (
            immutable_content[0],
            immutable_content[5],
            immutable_content[6],
            immutable_content[7],
            immutable_content[8],
        ):
            raise _RegistryConflictV1(
                "Withdraw evidence differs from accepted Candidate identity"
            )
    if not rows and stored_content is not None:
        raise _RegistryConflictV1("Candidate content has no Handoff history")
    if rows and immutable_content is None:
        raise _RegistryConflictV1("Candidate history has no accepted Handoff")
    content_projection_is_valid = stored_content == latest_content_projection
    if allow_historical_content_projection and stored_content is not None:
        content_projection_is_valid = stored_content in historical_content_projections
    if stored_content is not None and not content_projection_is_valid:
        raise _RegistryConflictV1(
            "Candidate content and latest accept evidence differ"
        )


def _apply_accept_transaction(
    connection: sqlite3.Connection,
    validated: _ValidatedHandoffV1,
    imports_root: Path,
) -> Literal["applied", "unchanged"]:
    record = validated.record
    candidate = cast(dict[str, object], record["candidate"])
    citation = cast(dict[str, object], record["citation"])
    descriptor_snapshots = cast(list[object], record["descriptor_snapshots"])
    evidence_snapshots = cast(list[object], record["evidence_snapshots"])
    try:
        connection.execute("BEGIN IMMEDIATE")
        _validate_registry_schema(connection)
        _verify_candidate_import_history(
            connection,
            imports_root,
            validated.candidate_id,
        )
        existing_revision = connection.execute(
            """
            SELECT candidate_id, payload_sha256, review_revision, action,
                   review_status, work_id, source_id, source_sha256,
                   canonical_content_sha256, canonical_run_id, semantic_run_id,
                   manifest_sha256, candidates_sha256
            FROM handoff_revisions WHERE handoff_id = ?
            """,
            (validated.handoff_id,),
        ).fetchone()
        expected_revision = (
            validated.candidate_id,
            validated.payload_sha256,
            validated.review_revision,
            "accept",
            "accepted",
            validated.work_id,
            validated.source_id,
            validated.source_sha256,
            validated.canonical_content_sha256,
            validated.canonical_run_id,
            validated.semantic_run_id,
            validated.manifest_sha256,
            validated.candidates_sha256,
        )
        expected_content = _accepted_content_values(validated)
        if existing_revision is not None:
            if existing_revision != expected_revision:
                raise _RevisionConflictV1("Recorded Handoff identity conflicts")
            existing_content = connection.execute(
                """
                SELECT payload_sha256, candidate_json, citation_json,
                       descriptor_snapshots_json, evidence_snapshots_json,
                       work_id, source_id, source_sha256,
                       canonical_content_sha256, promotion_status
                FROM candidate_content WHERE candidate_id = ?
                """,
                (validated.candidate_id,),
            ).fetchone()
            if existing_content != expected_content:
                raise _RegistryConflictV1("Recorded Candidate content conflicts")
            _rebuild_current_projection(connection, validated.candidate_id)
            _rebuild_content_import_projection(connection, validated.candidate_id)
            _synchronize_candidate_search_projection_v1(
                connection,
                validated.candidate_id,
            )
            bind_search_projection_generation_v1(connection)
            _commit_registry_transaction(connection)
            return "unchanged"
        if connection.execute(
            "SELECT 1 FROM handoff_revisions "
            "WHERE candidate_id = ? AND review_revision = ?",
            (validated.candidate_id, validated.review_revision),
        ).fetchone() is not None:
            raise _RevisionConflictV1("Candidate review revision conflicts")
        existing_content = connection.execute(
            """
            SELECT payload_sha256, candidate_json, citation_json,
                   descriptor_snapshots_json, evidence_snapshots_json,
                   work_id, source_id, source_sha256,
                   canonical_content_sha256, promotion_status
            FROM candidate_content WHERE candidate_id = ?
            """,
            (validated.candidate_id,),
        ).fetchone()
        is_new_candidate = existing_content is None
        if is_new_candidate:
            connection.execute(
                """
                INSERT INTO candidate_content(
                    candidate_id, payload_sha256, candidate_json, citation_json,
                    descriptor_snapshots_json, evidence_snapshots_json, work_id,
                    source_id, source_sha256, canonical_content_sha256,
                    content_handoff_id, content_manifest_sha256,
                    content_candidates_sha256, promotion_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_promoted')
                """,
                (
                    validated.candidate_id,
                    validated.payload_sha256,
                    sqlite3.Binary(_canonical_payload_bytes(candidate)),
                    sqlite3.Binary(_canonical_payload_bytes(citation)),
                    sqlite3.Binary(_canonical_payload_bytes(descriptor_snapshots)),
                    sqlite3.Binary(_canonical_payload_bytes(evidence_snapshots)),
                    validated.work_id,
                    validated.source_id,
                    validated.source_sha256,
                    validated.canonical_content_sha256,
                    validated.handoff_id,
                    validated.manifest_sha256,
                    validated.candidates_sha256,
                ),
            )
        else:
            if existing_content != expected_content:
                raise _RegistryConflictV1("Accepted Candidate content drifted")
            _rebuild_current_projection(connection, validated.candidate_id)
            current = connection.execute(
                "SELECT review_revision FROM candidate_current WHERE candidate_id = ?",
                (validated.candidate_id,),
            ).fetchone()
            if current is None:
                raise _RegistryConflictV1("Candidate current projection is missing")
            if validated.review_revision <= cast(int, current[0]):
                raise _RevisionConflictV1("accept revision is not newer")
        connection.execute(
            """
            INSERT INTO handoff_revisions(
                handoff_id, candidate_id, payload_sha256, review_revision,
                action, review_status, work_id, source_id, source_sha256,
                canonical_content_sha256, canonical_run_id, semantic_run_id,
                manifest_sha256, candidates_sha256
            ) VALUES (?, ?, ?, ?, 'accept', 'accepted', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                validated.handoff_id,
                validated.candidate_id,
                validated.payload_sha256,
                validated.review_revision,
                validated.work_id,
                validated.source_id,
                validated.source_sha256,
                validated.canonical_content_sha256,
                validated.canonical_run_id,
                validated.semantic_run_id,
                validated.manifest_sha256,
                validated.candidates_sha256,
            ),
        )
        if is_new_candidate:
            connection.execute(
                """
                INSERT INTO candidate_current(
                    candidate_id, review_revision, review_status,
                    intake_status, status_handoff_id
                ) VALUES (?, ?, 'accepted', 'active', ?)
                """,
                (
                    validated.candidate_id,
                    validated.review_revision,
                    validated.handoff_id,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE candidate_current
                SET review_revision = ?, review_status = 'accepted',
                    intake_status = 'active', status_handoff_id = ?
                WHERE candidate_id = ?
                """,
                (
                    validated.review_revision,
                    validated.handoff_id,
                    validated.candidate_id,
                ),
            )
        _rebuild_content_import_projection(connection, validated.candidate_id)
        replace_active_search_document_v1(
            connection,
            candidate_id=validated.candidate_id,
            candidate=candidate,
            citation=citation,
            descriptor_snapshots=descriptor_snapshots,
        )
        connection.execute(
            "UPDATE registry_meta SET generation = generation + 1 WHERE singleton = 1"
        )
        bind_search_projection_generation_v1(connection)
    except sqlite3.IntegrityError as error:
        _rollback_registry_transaction(connection)
        raise _RegistryConflictV1("Candidate Registry content conflicts") from error
    except sqlite3.OperationalError as error:
        _rollback_registry_transaction(connection)
        if _sqlite_is_busy(error):
            raise _RegistryBusyV1("Candidate Registry is busy") from error
        raise _CommitFailedV1("Candidate Registry transaction failed") from error
    except sqlite3.Error as error:
        _rollback_registry_transaction(connection)
        raise _CommitFailedV1("Candidate Registry transaction failed") from error
    _commit_registry_transaction(connection)
    return "applied"


def _apply_withdraw_transaction(
    connection: sqlite3.Connection,
    validated: _ValidatedHandoffV1,
    imports_root: Path,
) -> Literal["applied", "unchanged"]:
    try:
        connection.execute("BEGIN IMMEDIATE")
        _validate_registry_schema(connection)
        _verify_candidate_import_history(
            connection,
            imports_root,
            validated.candidate_id,
        )
        existing_revision = connection.execute(
            """
            SELECT candidate_id, payload_sha256, review_revision, action,
                   review_status, work_id, source_id, source_sha256,
                   canonical_content_sha256, canonical_run_id, semantic_run_id,
                   manifest_sha256, candidates_sha256
            FROM handoff_revisions WHERE handoff_id = ?
            """,
            (validated.handoff_id,),
        ).fetchone()
        expected_revision = (
            validated.candidate_id,
            validated.payload_sha256,
            validated.review_revision,
            "withdraw",
            validated.review_status,
            validated.work_id,
            validated.source_id,
            validated.source_sha256,
            validated.canonical_content_sha256,
            validated.canonical_run_id,
            validated.semantic_run_id,
            validated.manifest_sha256,
            validated.candidates_sha256,
        )
        if existing_revision is not None:
            if existing_revision != expected_revision:
                raise _RevisionConflictV1("Recorded Handoff identity conflicts")
            _rebuild_current_projection(connection, validated.candidate_id)
            _rebuild_content_import_projection(connection, validated.candidate_id)
            _synchronize_candidate_search_projection_v1(
                connection,
                validated.candidate_id,
            )
            bind_search_projection_generation_v1(connection)
            _commit_registry_transaction(connection)
            return "unchanged"

        content = connection.execute(
            """
            SELECT payload_sha256, work_id, source_id, source_sha256,
                   canonical_content_sha256, promotion_status
            FROM candidate_content WHERE candidate_id = ?
            """,
            (validated.candidate_id,),
        ).fetchone()
        if content is None:
            raise _RevisionConflictV1("withdraw has no earlier accepted Candidate")
        if content != (
            validated.payload_sha256,
            validated.work_id,
            validated.source_id,
            validated.source_sha256,
            validated.canonical_content_sha256,
            "not_promoted",
        ):
            raise _RegistryConflictV1("withdraw Candidate identity conflicts")
        _rebuild_current_projection(connection, validated.candidate_id)
        current = connection.execute(
            "SELECT review_revision FROM candidate_current WHERE candidate_id = ?",
            (validated.candidate_id,),
        ).fetchone()
        if current is None:
            raise _RegistryConflictV1("Candidate current projection is missing")
        if validated.review_revision <= cast(int, current[0]):
            raise _RevisionConflictV1("withdraw revision is not newer")

        connection.execute(
            """
            INSERT INTO handoff_revisions(
                handoff_id, candidate_id, payload_sha256, review_revision,
                action, review_status, work_id, source_id, source_sha256,
                canonical_content_sha256, canonical_run_id, semantic_run_id,
                manifest_sha256, candidates_sha256
            ) VALUES (?, ?, ?, ?, 'withdraw', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                validated.handoff_id,
                validated.candidate_id,
                validated.payload_sha256,
                validated.review_revision,
                validated.review_status,
                validated.work_id,
                validated.source_id,
                validated.source_sha256,
                validated.canonical_content_sha256,
                validated.canonical_run_id,
                validated.semantic_run_id,
                validated.manifest_sha256,
                validated.candidates_sha256,
            ),
        )
        connection.execute(
            """
            UPDATE candidate_current
            SET review_revision = ?, review_status = ?,
                intake_status = 'withdrawn', status_handoff_id = ?
            WHERE candidate_id = ?
            """,
            (
                validated.review_revision,
                validated.review_status,
                validated.handoff_id,
                validated.candidate_id,
            ),
        )
        _rebuild_content_import_projection(connection, validated.candidate_id)
        connection.execute(
            "UPDATE registry_meta SET generation = generation + 1 WHERE singleton = 1"
        )
        remove_search_document_v1(
            connection,
            candidate_id=validated.candidate_id,
        )
        bind_search_projection_generation_v1(connection)
    except sqlite3.IntegrityError as error:
        _rollback_registry_transaction(connection)
        raise _RegistryConflictV1("Candidate Registry content conflicts") from error
    except sqlite3.OperationalError as error:
        _rollback_registry_transaction(connection)
        if _sqlite_is_busy(error):
            raise _RegistryBusyV1("Candidate Registry is busy") from error
        raise _CommitFailedV1("Candidate Registry transaction failed") from error
    except sqlite3.Error as error:
        _rollback_registry_transaction(connection)
        raise _CommitFailedV1("Candidate Registry transaction failed") from error
    _commit_registry_transaction(connection)
    return "applied"


def _verify_applied(
    connection: sqlite3.Connection,
    validated: _ValidatedHandoffV1,
) -> None:
    recorded = connection.execute(
        """
        SELECT candidate_id, payload_sha256, review_revision, action,
               review_status, work_id, source_id, source_sha256,
               canonical_content_sha256, canonical_run_id, semantic_run_id,
               manifest_sha256, candidates_sha256
        FROM handoff_revisions WHERE handoff_id = ?
        """,
        (validated.handoff_id,),
    ).fetchone()
    if recorded != (
        validated.candidate_id,
        validated.payload_sha256,
        validated.review_revision,
        validated.action,
        validated.review_status,
        validated.work_id,
        validated.source_id,
        validated.source_sha256,
        validated.canonical_content_sha256,
        validated.canonical_run_id,
        validated.semantic_run_id,
        validated.manifest_sha256,
        validated.candidates_sha256,
    ):
        raise _CommitIndeterminateV1("Candidate Registry Handoff differs")
    latest = connection.execute(
        """
        SELECT review_revision, review_status, action, handoff_id
        FROM handoff_revisions
        WHERE candidate_id = ?
        ORDER BY review_revision DESC
        LIMIT 1
        """,
        (validated.candidate_id,),
    ).fetchone()
    if latest is None:
        raise _CommitIndeterminateV1("Candidate Registry history is missing")
    latest_intake_status = "active" if latest[2] == "accept" else "withdrawn"
    current = connection.execute(
        """
        SELECT c.payload_sha256, c.promotion_status, r.review_revision,
               r.review_status, r.intake_status, r.status_handoff_id
        FROM candidate_content AS c
        JOIN candidate_current AS r USING(candidate_id)
        WHERE c.candidate_id = ?
        """,
        (validated.candidate_id,),
    ).fetchone()
    if current != (
        validated.payload_sha256,
        "not_promoted",
        latest[0],
        latest[1],
        latest_intake_status,
        latest[3],
    ):
        raise _CommitIndeterminateV1("Candidate Registry acknowledgement differs")


@dataclass(frozen=True, slots=True)
class KnowledgeIntakeAdapterV1:
    data_root: str

    def apply(self, handoff: ReviewedHandoffBytesV1) -> KnowledgeIntakeVerdictV1:
        try:
            validated = _validate_handoff(handoff)
        except (KeyError, TypeError, _HandoffInvalidV1):
            return IntakeFailedV1("import_failed")
        try:
            root = open_validated_data_root_v1(self.data_root)
        except DataRootOpenErrorV1 as error:
            return IntakeBlockedV1(
                "data_root_unsafe" if error.status == "unsafe" else "data_root_unavailable",
                "knowledge",
            )
        with root:
            root_identity = root.inspection.identity
            if root_identity is None:
                raise RuntimeError("validated Knowledge root is incomplete")
            owner = try_acquire_knowledge_registry_writer_v1(root_identity)
            if owner is None:
                return IntakeBlockedV1("registry_busy")
            connection: sqlite3.Connection | None = None
            registry_guard: ValidatedFileV1 | None = None
            with owner:
                try:
                    _root_checkpoint(root)
                    _commit_or_reuse_evidence(root, handoff, validated)
                    root_path = root.inspection.canonical_path
                    if root_path is None:
                        raise RuntimeError("validated Knowledge root is incomplete")
                    connection, registry_guard = _open_registry(
                        Path(root_path) / "registry.sqlite3"
                    )
                    imports_root = Path(root_path) / "imports"
                    _bootstrap_registry(
                        connection,
                        validated,
                        imports_root,
                    )
                    disposition = (
                        _apply_accept_transaction(
                            connection,
                            validated,
                            imports_root,
                        )
                        if validated.action == "accept"
                        else _apply_withdraw_transaction(
                            connection,
                            validated,
                            imports_root,
                        )
                    )
                    _verify_applied(connection, validated)
                    registry_guard.revalidate_identity_v1()
                    _root_checkpoint(root)
                except _RevisionConflictV1:
                    return IntakeFailedV1("revision_conflict")
                except _RegistryConflictV1:
                    return IntakeFailedV1("registry_conflict")
                except _HandoffInvalidV1:
                    return IntakeFailedV1("import_failed")
                except _RegistryUnavailableV1:
                    return IntakeBlockedV1("registry_unavailable")
                except _RegistryBusyV1:
                    return IntakeBlockedV1("registry_busy")
                except _DataRootIntegrityLostV1:
                    return IntakeFailedV1("data_root_integrity_lost", "knowledge")
                except _CommitFailedV1:
                    return IntakeFailedV1("commit_failed")
                finally:
                    try:
                        if connection is not None:
                            connection.close()
                    finally:
                        if registry_guard is not None:
                            registry_guard.close()
        intake_status: Literal["active", "withdrawn"] = (
            "active" if validated.action == "accept" else "withdrawn"
        )
        return IntakeAppliedV1(intake_status, disposition)


__all__ = ["KnowledgeIntakeAdapterV1"]
