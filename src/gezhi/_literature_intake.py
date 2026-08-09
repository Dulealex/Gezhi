from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import sqlite3
import unicodedata
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, TypeAlias, cast

from gezhi._windows_data_root import (
    DataRootOpenErrorV1,
    ValidatedDataRootV1,
    normalize_local_path_v1,
    open_validated_data_root_v1,
    open_validated_local_file_v1,
)
from gezhi._windows_ownership import (
    try_acquire_catalog_projection_v1,
    try_acquire_identity_intake_v1,
    try_acquire_work_writer_v1,
)

_WORK_ID = re.compile(
    r"^wrk_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
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
_SOURCE_ID = re.compile(r"^src_[0-9a-f]{24}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_INT64 = 9_223_372_036_854_775_807

AddStopOutcome: TypeAlias = Literal["blocked", "failed"]
ActiveSourceAuthorityStopReason: TypeAlias = Literal[
    "active_source_invalid",
    "active_source_unavailable",
    "data_root_integrity_lost",
    "identity_review_required",
    "recovery_failed",
    "work_not_found",
]


@dataclass(frozen=True, slots=True)
class AddLocalPdfRequestV1:
    pdf_path: str
    work_id: str | None
    doi: str | None
    arxiv_id: str | None
    citation: str | None


@dataclass(frozen=True, slots=True)
class ValidatedAddInputV1:
    pdf_path: str
    work_id: str | None
    doi: str | None
    arxiv_id: str | None
    citation: str | None


class AddInputInvalidV1(ValueError):
    def __init__(self, field: str) -> None:
        super().__init__(f"add input is invalid: {field}")
        self.field = field


class AddStoppedV1(RuntimeError):
    def __init__(
        self,
        outcome: AddStopOutcome,
        reason: str,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(f"Literature add {outcome}: {reason}")
        self.outcome = outcome
        self.reason = reason
        self.context = {} if context is None else context


@dataclass(frozen=True, slots=True)
class AddLocalPdfResultV1:
    active_source_changed: bool
    disposition: Literal["created_work", "added_source", "reused_source"]
    source_id: str
    source_sha256: str
    work_id: str

    def as_mapping_v1(self) -> dict[str, object]:
        return {
            "active_source_changed": self.active_source_changed,
            "disposition": self.disposition,
            "schema_version": "gezhi.literature_add_result.v1",
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
            "work_id": self.work_id,
        }


@dataclass(frozen=True, slots=True)
class _PdfSnapshotV1:
    stage_name: str
    stage_dir: Path
    original_path: Path
    byte_length: int
    source_sha256: str
    source_id: str


@dataclass(frozen=True, slots=True)
class _SourceStateV1:
    work_id: str
    source_id: str
    source_sha256: str
    byte_length: int
    manifest_sha256: str
    directory: Path


@dataclass(frozen=True, slots=True)
class _WorkStateV1:
    work_id: str
    directory: Path
    aliases: dict[str, frozenset[str]]
    identity_sha256: str
    active_source_id: str | None


@dataclass(frozen=True, slots=True)
class _AuthoritySnapshotV1:
    works: dict[str, _WorkStateV1]
    sources_by_id: dict[str, _SourceStateV1]
    sources_by_hash: dict[str, _SourceStateV1]
    alias_owners: dict[tuple[str, str], frozenset[str]]


@dataclass(frozen=True, slots=True)
class _IdentityReservationV1:
    arxiv_id: str | None
    citation: str | None
    doi: str | None
    source_id: str
    source_sha256: str
    work_id: str
    path: Path


@dataclass(frozen=True, slots=True)
class _ActiveSourcePointerV1:
    manifest_sha256: str
    source_id: str
    source_sha256: str
    work_id: str


@dataclass(frozen=True, slots=True)
class ActiveSourceAuthorityV1:
    """One target Work's validated Source authority for continuation."""

    work_id: str
    source_id: str
    source_sha256: str
    source_byte_length: int
    source_manifest_sha256: str
    work_directory: Path
    source_directory: Path
    original_pdf_path: Path
    ingest_identity_ready: bool


class ActiveSourceAuthorityStoppedV1(RuntimeError):
    def __init__(self, reason: ActiveSourceAuthorityStopReason) -> None:
        super().__init__(f"Active Source authority stopped: {reason}")
        self.reason = reason


def _valid_pdf_path(value: object) -> bool:
    return type(value) is str and normalize_local_path_v1(value) is not None


def _valid_work_id(value: object) -> bool:
    return type(value) is str and _WORK_ID.fullmatch(value) is not None


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


def _normalize_citation(value: object) -> str | None:
    if type(value) is not str:
        return None
    normalized = unicodedata.normalize(
        "NFC",
        value.replace("\r\n", "\n").replace("\r", "\n"),
    ).strip()
    if not 1 <= len(normalized) <= 4096:
        return None
    for character in normalized:
        category = unicodedata.category(character)
        if character == "\x00" or category == "Cs":
            return None
        if category == "Cc" and character not in {"\t", "\n"}:
            return None
    try:
        encoded = normalized.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return normalized if len(encoded) <= 16_384 else None


def validate_add_request_v1(
    request: AddLocalPdfRequestV1,
) -> ValidatedAddInputV1:
    if type(request) is not AddLocalPdfRequestV1:
        raise TypeError("add request is invalid")
    if not _valid_pdf_path(request.pdf_path):
        raise AddInputInvalidV1("pdf_path")
    if request.work_id is not None and not _valid_work_id(request.work_id):
        raise AddInputInvalidV1("work_id")
    if request.doi is not None and not _valid_doi(request.doi):
        raise AddInputInvalidV1("doi")
    if request.arxiv_id is not None and not _valid_arxiv_id(request.arxiv_id):
        raise AddInputInvalidV1("arxiv_id")

    citation = request.citation
    normalized_citation: str | None = None
    if citation is not None:
        normalized_citation = _normalize_citation(citation)
        if normalized_citation is None:
            raise AddInputInvalidV1("citation")
    return ValidatedAddInputV1(
        pdf_path=request.pdf_path,
        work_id=request.work_id,
        doi=request.doi,
        arxiv_id=request.arxiv_id,
        citation=normalized_citation,
    )


def _canonical_json_bytes(value: object) -> bytes:
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


def _is_plain_directory(path: Path) -> bool:
    try:
        with open_validated_data_root_v1(str(path)):
            return True
    except DataRootOpenErrorV1:
        return False


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
        raise AddStoppedV1("failed", "commit_failed") from error


def _read_safe_bytes(path: Path, *, limit: int) -> bytes:
    try:
        with open_validated_local_file_v1(str(path)) as source:
            if source.size > limit:
                raise ValueError("Literature authority file exceeds its limit")
            return b"".join(source.iter_verified_chunks_v1())
    except DataRootOpenErrorV1 as error:
        raise ValueError("Literature authority file is unsafe") from error


def _write_all(destination: BinaryIO, payload: bytes) -> None:
    view = memoryview(payload)
    offset = 0
    while offset < len(payload):
        count = destination.write(view[offset:])
        remaining = len(payload) - offset
        if type(count) is not int or not 1 <= count <= remaining:
            raise OSError("file write did not complete deterministically")
        offset += count


def _write_new_verified(path: Path, payload: bytes) -> None:
    try:
        with open_validated_data_root_v1(str(path.parent)):
            with path.open("xb", buffering=0) as destination:
                _write_all(destination, payload)
            observed = _read_safe_bytes(path, limit=len(payload))
    except (OSError, ValueError, DataRootOpenErrorV1) as error:
        raise AddStoppedV1("failed", "commit_failed") from error
    if observed != payload:
        raise AddStoppedV1("failed", "commit_failed")


def _atomic_replace_json(parent: Path, name: str, value: object) -> bytes:
    payload = _canonical_json_bytes(value)
    temporary = parent / f".{name}.{uuid.uuid4().hex}.tmp"
    try:
        with open_validated_data_root_v1(str(parent)):
            _write_new_verified(temporary, payload)
            try:
                os.replace(temporary, parent / name)
            except OSError:
                try:
                    temporary.unlink()
                except OSError:
                    pass
                raise
            observed = _read_safe_bytes(parent / name, limit=len(payload))
    except (OSError, ValueError, DataRootOpenErrorV1) as error:
        raise AddStoppedV1("failed", "commit_failed") from error
    if observed != payload:
        raise AddStoppedV1("failed", "commit_failed")
    return payload


def _root_checkpoint(root: ValidatedDataRootV1) -> None:
    expected = root.inspection
    path = expected.canonical_path
    if path is None:
        raise RuntimeError("validated Literature root is incomplete")
    try:
        with open_validated_data_root_v1(path) as current:
            observed = current.inspection
    except DataRootOpenErrorV1 as error:
        raise AddStoppedV1("failed", "data_root_integrity_lost") from error
    observed_path = observed.canonical_path
    if (
        observed.identity != expected.identity
        or observed.ancestor_identities != expected.ancestor_identities
        or observed_path is None
        or ntpath.normcase(observed_path) != ntpath.normcase(path)
    ):
        raise AddStoppedV1("failed", "data_root_integrity_lost")


def _create_pdf_snapshot(
    root: ValidatedDataRootV1,
    validated: ValidatedAddInputV1,
) -> _PdfSnapshotV1:
    root_path_text = root.inspection.canonical_path
    if root_path_text is None:
        raise RuntimeError("validated Literature root is incomplete")
    root_path = Path(root_path_text)
    works = root_path / "works"
    staging = works / ".staging"
    _ensure_plain_directory(works)
    _ensure_plain_directory(staging)
    stage_name = "intake-" + uuid.uuid4().hex
    stage_dir = staging / stage_name
    _ensure_plain_directory(stage_dir)
    original_path = stage_dir / "original.pdf"

    try:
        opened = open_validated_local_file_v1(validated.pdf_path)
    except DataRootOpenErrorV1 as error:
        raise AddStoppedV1("blocked", "pdf_unavailable") from error
    with opened:
        if opened.size > _MAX_INT64:
            raise AddInputInvalidV1("pdf_content")
        digest = hashlib.sha256()
        byte_length = 0
        prefix = b""
        source_error: DataRootOpenErrorV1 | None = None
        write_error: OSError | None = None
        destination: BinaryIO | None = None
        try:
            destination = original_path.open("xb", buffering=0)
            try:
                for chunk in opened.iter_verified_chunks_v1():
                    _write_all(destination, chunk)
                    digest.update(chunk)
                    byte_length += len(chunk)
                    if len(prefix) < 5:
                        prefix = (prefix + chunk)[:5]
                    if byte_length > _MAX_INT64:
                        raise AddInputInvalidV1("pdf_content")
            except DataRootOpenErrorV1 as error:
                source_error = error
            except OSError as error:
                write_error = error
        except AddInputInvalidV1:
            raise
        except OSError as error:
            write_error = error
        finally:
            if destination is not None:
                try:
                    destination.close()
                except OSError as error:
                    if write_error is None:
                        write_error = error
        if source_error is not None:
            raise AddStoppedV1("failed", "source_changed") from source_error
        if write_error is not None:
            raise AddStoppedV1("failed", "commit_failed") from write_error

    if byte_length == 0 or prefix != b"%PDF-":
        raise AddInputInvalidV1("pdf_content")
    source_sha256 = digest.hexdigest()
    source_id = "src_" + source_sha256[:24]
    try:
        with root.open_relative_file_v1(
            ("works", ".staging", stage_name, "original.pdf")
        ) as staged:
            if (
                staged.size != byte_length
                or staged.sha256_v1() != source_sha256
            ):
                raise AddStoppedV1("failed", "commit_failed")
    except DataRootOpenErrorV1 as error:
        raise AddStoppedV1("failed", "commit_failed") from error
    return _PdfSnapshotV1(
        stage_name=stage_name,
        stage_dir=stage_dir,
        original_path=original_path,
        byte_length=byte_length,
        source_sha256=source_sha256,
        source_id=source_id,
    )


def _read_canonical_document(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        payload = _read_safe_bytes(path, limit=_MAX_INT64)
        value = json.loads(payload)
        canonical = _canonical_json_bytes(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Literature authority document is invalid") from error
    if type(value) is not dict or payload != canonical:
        raise ValueError("Literature authority document is not canonical")
    return value, payload


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    length = 0
    try:
        with open_validated_local_file_v1(str(path)) as source:
            for chunk in source.iter_verified_chunks_v1():
                digest.update(chunk)
                length += len(chunk)
    except DataRootOpenErrorV1 as error:
        raise ValueError("Literature source asset is unreadable") from error
    return length, digest.hexdigest()


def _load_work_identity(
    work_dir: Path, work_id: str
) -> tuple[dict[str, frozenset[str]], str]:
    current_path = work_dir / "identity" / "current.json"
    if not current_path.exists():
        raise ValueError("Work identity current is missing")
    current, _current_bytes = _read_canonical_document(current_path)
    if (
        set(current) != {"identity_sha256", "revision", "schema_version", "work_id"}
        or current.get("schema_version")
        != "gezhi.literature_work_identity_current.v1"
        or current.get("work_id") != work_id
        or type(current.get("revision")) is not str
        or type(current.get("identity_sha256")) is not str
    ):
        raise ValueError("Work identity current is invalid")
    revision_name = cast(str, current["revision"])
    identity_sha256 = cast(str, current["identity_sha256"])
    if (
        _SHA256.fullmatch(identity_sha256) is None
        or revision_name != f"idrev_{identity_sha256[:24]}.json"
    ):
        raise ValueError("Work identity current is invalid")
    revision, revision_bytes = _read_canonical_document(
        work_dir / "identity" / "revisions" / revision_name
    )
    if hashlib.sha256(revision_bytes).hexdigest() != identity_sha256:
        raise ValueError("Work identity hash is invalid")
    if (
        set(revision)
        != {"arxiv_ids", "citations", "dois", "schema_version", "work_id"}
        or revision.get("schema_version") != "gezhi.literature_work_identity.v1"
        or revision.get("work_id") != work_id
    ):
        raise ValueError("Work identity revision is invalid")
    values: dict[str, frozenset[str]] = {}
    for plural, singular in (
        ("dois", "doi"),
        ("arxiv_ids", "arxiv_id"),
        ("citations", "citation"),
    ):
        raw = revision[plural]
        if type(raw) is not list or any(type(item) is not str for item in raw):
            raise ValueError("Work identity aliases are invalid")
        if raw != sorted(set(raw), key=lambda item: item.encode("utf-8")):
            raise ValueError("Work identity aliases are not canonical")
        validator = {
            "doi": _valid_doi,
            "arxiv_id": _valid_arxiv_id,
            "citation": lambda item: _normalize_citation(item) == item,
        }[singular]
        if any(not validator(item) for item in raw):
            raise ValueError("Work identity alias is invalid")
        values[singular] = frozenset(raw)
    return values, identity_sha256


def _load_source(
    source_dir: Path,
    *,
    work_id: str,
    source_id: str,
) -> _SourceStateV1:
    if not _is_plain_directory(source_dir):
        raise ValueError("Source directory is unsafe")
    try:
        entries = {entry.name: entry for entry in source_dir.iterdir()}
    except OSError as error:
        raise ValueError("Source directory is unreadable") from error
    required_files = {"manifest.json", "original.pdf", "source.json"}
    stage_directories = {"ocr", "canonical", "semantic"}
    if not required_files.issubset(entries) or set(entries) - (
        required_files | stage_directories
    ):
        raise ValueError("Source directory inventory is invalid")
    if any(
        name in entries and not _is_plain_directory(entries[name])
        for name in stage_directories
    ):
        raise ValueError("Source stage directory is unsafe")
    manifest, manifest_bytes = _read_canonical_document(
        source_dir / "manifest.json"
    )
    source, source_bytes = _read_canonical_document(source_dir / "source.json")
    source_sha256 = source.get("source_sha256")
    byte_length = source.get("byte_length")
    if (
        set(source)
        != {
            "byte_length",
            "media_type",
            "schema_version",
            "source_id",
            "source_sha256",
            "work_id",
        }
        or source.get("schema_version") != "gezhi.literature_source.v1"
        or source.get("media_type") != "application/pdf"
        or source.get("work_id") != work_id
        or source.get("source_id") != source_id
        or type(source_sha256) is not str
        or _SHA256.fullmatch(source_sha256) is None
        or source_id != "src_" + source_sha256[:24]
        or type(byte_length) is not int
        or not 0 <= byte_length <= _MAX_INT64
    ):
        raise ValueError("Source description is invalid")
    original_length, original_hash = _hash_file(source_dir / "original.pdf")
    if (
        original_length != source["byte_length"]
        or original_hash != source["source_sha256"]
    ):
        raise ValueError("Source original is invalid")
    expected_manifest = {
        "assets": [
            {
                "byte_length": original_length,
                "media_type": "application/pdf",
                "path": "original.pdf",
                "sha256": original_hash,
            },
            {
                "byte_length": len(source_bytes),
                "media_type": "application/json",
                "path": "source.json",
                "schema_version": "gezhi.literature_source.v1",
                "sha256": hashlib.sha256(source_bytes).hexdigest(),
            },
        ],
        "schema_version": "gezhi.literature_source_manifest.v1",
        "source_id": source_id,
        "source_sha256": original_hash,
        "work_id": work_id,
    }
    if manifest != expected_manifest:
        raise ValueError("Source manifest is invalid")
    return _SourceStateV1(
        work_id=work_id,
        source_id=source_id,
        source_sha256=original_hash,
        byte_length=original_length,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        directory=source_dir,
    )


def _load_active_source(
    work_dir: Path,
    work_id: str,
) -> _ActiveSourcePointerV1 | None:
    path = work_dir / "active_source.json"
    if not path.exists():
        return None
    value, _payload = _read_canonical_document(path)
    if (
        set(value)
        != {
            "manifest_sha256",
            "schema_version",
            "source_id",
            "source_sha256",
            "work_id",
        }
        or value.get("schema_version")
        != "gezhi.literature_active_source.v1"
        or value.get("work_id") != work_id
        or type(value.get("source_id")) is not str
        or _SOURCE_ID.fullmatch(str(value["source_id"])) is None
        or type(value.get("source_sha256")) is not str
        or _SHA256.fullmatch(str(value["source_sha256"])) is None
        or value["source_id"]
        != "src_" + str(value["source_sha256"])[:24]
        or type(value.get("manifest_sha256")) is not str
        or _SHA256.fullmatch(str(value["manifest_sha256"])) is None
    ):
        raise ValueError("Active Source pointer is invalid")
    return _ActiveSourcePointerV1(
        manifest_sha256=cast(str, value["manifest_sha256"]),
        source_id=cast(str, value["source_id"]),
        source_sha256=cast(str, value["source_sha256"]),
        work_id=work_id,
    )


def _entry_names(parent: Path) -> frozenset[str]:
    try:
        with open_validated_data_root_v1(str(parent)):
            return frozenset(entry.name for entry in parent.iterdir())
    except (DataRootOpenErrorV1, OSError) as error:
        raise ActiveSourceAuthorityStoppedV1("recovery_failed") from error


def load_active_source_authority_v1(
    work_id: str,
    *,
    root: ValidatedDataRootV1,
) -> ActiveSourceAuthorityV1:
    """Validate only the requested Work and its Active Source.

    Resume must not let an unrelated damaged Work contaminate this target's
    continuation point, so this deliberately avoids the root-wide catalog
    projection scan used by add.
    """

    if type(work_id) is not str or _WORK_ID.fullmatch(work_id) is None:
        raise TypeError("a validated Work ID is required")
    root_path_text = root.inspection.canonical_path
    if root_path_text is None:
        raise RuntimeError("validated Literature root is incomplete")
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise ActiveSourceAuthorityStoppedV1(
            "data_root_integrity_lost"
        ) from error

    root_path = Path(root_path_text)
    works_path = root_path / "works"
    try:
        work_names = _entry_names(works_path)
    except ActiveSourceAuthorityStoppedV1 as error:
        if not works_path.exists():
            raise ActiveSourceAuthorityStoppedV1("work_not_found") from error
        raise
    if work_id not in work_names:
        raise ActiveSourceAuthorityStoppedV1("work_not_found")
    work_dir = works_path / work_id
    if not _is_plain_directory(work_dir):
        raise ActiveSourceAuthorityStoppedV1("recovery_failed")

    try:
        work, _work_bytes = _read_canonical_document(work_dir / "work.json")
    except (OSError, ValueError) as error:
        raise ActiveSourceAuthorityStoppedV1("recovery_failed") from error
    if work != {
        "schema_version": "gezhi.literature_work.v1",
        "work_id": work_id,
    }:
        raise ActiveSourceAuthorityStoppedV1("recovery_failed")

    try:
        _aliases, _identity_sha256 = _load_work_identity(work_dir, work_id)
    except (OSError, ValueError):
        ingest_identity_ready = False
    else:
        ingest_identity_ready = True

    work_entries = _entry_names(work_dir)
    if "active_source.json" not in work_entries:
        raise ActiveSourceAuthorityStoppedV1("active_source_unavailable")
    try:
        pointer = _load_active_source(work_dir, work_id)
    except ValueError as error:
        cause = error.__cause__
        reason: ActiveSourceAuthorityStopReason = (
            "active_source_unavailable"
            if isinstance(cause, DataRootOpenErrorV1)
            and cause.status == "unavailable"
            else "active_source_invalid"
        )
        raise ActiveSourceAuthorityStoppedV1(reason) from error
    if pointer is None:
        raise ActiveSourceAuthorityStoppedV1("active_source_unavailable")

    sources_path = work_dir / "sources"
    try:
        source_names = _entry_names(sources_path)
    except ActiveSourceAuthorityStoppedV1 as error:
        if not sources_path.exists():
            raise ActiveSourceAuthorityStoppedV1(
                "active_source_unavailable"
            ) from error
        raise
    if pointer.source_id not in source_names:
        raise ActiveSourceAuthorityStoppedV1("active_source_unavailable")
    source_dir = sources_path / pointer.source_id
    if not _is_plain_directory(source_dir):
        raise ActiveSourceAuthorityStoppedV1("active_source_invalid")
    try:
        source_entries = _entry_names(source_dir)
    except ActiveSourceAuthorityStoppedV1 as error:
        raise ActiveSourceAuthorityStoppedV1("active_source_invalid") from error
    if not {"manifest.json", "original.pdf", "source.json"}.issubset(
        source_entries
    ):
        raise ActiveSourceAuthorityStoppedV1("active_source_unavailable")
    try:
        source = _load_source(
            source_dir,
            work_id=work_id,
            source_id=pointer.source_id,
        )
    except (OSError, ValueError) as error:
        raise ActiveSourceAuthorityStoppedV1("active_source_invalid") from error
    if (
        source.source_sha256 != pointer.source_sha256
        or source.manifest_sha256 != pointer.manifest_sha256
    ):
        raise ActiveSourceAuthorityStoppedV1("active_source_invalid")
    try:
        _root_checkpoint(root)
    except AddStoppedV1 as error:
        raise ActiveSourceAuthorityStoppedV1(
            "data_root_integrity_lost"
        ) from error
    return ActiveSourceAuthorityV1(
        work_id=work_id,
        source_id=source.source_id,
        source_sha256=source.source_sha256,
        source_byte_length=source.byte_length,
        source_manifest_sha256=source.manifest_sha256,
        work_directory=work_dir,
        source_directory=source.directory,
        original_pdf_path=source.directory / "original.pdf",
        ingest_identity_ready=ingest_identity_ready,
    )


def _authority_snapshot(root_path: Path) -> _AuthoritySnapshotV1:
    works_path = root_path / "works"
    _ensure_plain_directory(works_path)
    _ensure_plain_directory(works_path / ".staging")
    works: dict[str, _WorkStateV1] = {}
    sources_by_id: dict[str, _SourceStateV1] = {}
    sources_by_hash: dict[str, _SourceStateV1] = {}
    owners: dict[tuple[str, str], set[str]] = {}
    try:
        entries = tuple(works_path.iterdir())
    except OSError as error:
        raise AddStoppedV1("failed", "commit_failed") from error
    for work_dir in entries:
        if work_dir.name == ".staging":
            continue
        work_id = work_dir.name
        if _WORK_ID.fullmatch(work_id) is None or not _is_plain_directory(work_dir):
            continue
        try:
            work, _work_bytes = _read_canonical_document(work_dir / "work.json")
            if work != {
                "schema_version": "gezhi.literature_work.v1",
                "work_id": work_id,
            }:
                raise ValueError("Work descriptor is invalid")
            aliases, identity_sha256 = _load_work_identity(work_dir, work_id)
        except ValueError as error:
            raise AddStoppedV1(
                "blocked", "identity_review_required"
            ) from error
        try:
            active_pointer = _load_active_source(work_dir, work_id)
        except ValueError as error:
            raise AddStoppedV1(
                "failed", "content_identity_collision"
            ) from error
        state = _WorkStateV1(
            work_id=work_id,
            directory=work_dir,
            aliases=aliases,
            identity_sha256=identity_sha256,
            active_source_id=(
                None if active_pointer is None else active_pointer.source_id
            ),
        )
        works[work_id] = state
        for kind, values in aliases.items():
            for value in values:
                owners.setdefault((kind, value), set()).add(work_id)
        sources_path = work_dir / "sources"
        if not _is_plain_directory(sources_path):
            continue
        try:
            source_entries = tuple(sources_path.iterdir())
        except OSError as error:
            raise AddStoppedV1("failed", "commit_failed") from error
        for source_dir in source_entries:
            source_id = source_dir.name
            if source_id == ".staging":
                continue
            if _SOURCE_ID.fullmatch(source_id) is None or not _is_plain_directory(
                source_dir
            ):
                continue
            try:
                source = _load_source(
                    source_dir,
                    work_id=work_id,
                    source_id=source_id,
                )
            except ValueError as error:
                raise AddStoppedV1(
                    "failed", "content_identity_collision"
                ) from error
            prior_id = sources_by_id.get(source_id)
            prior_hash = sources_by_hash.get(source.source_sha256)
            if (
                prior_id is not None
                and prior_id.source_sha256 != source.source_sha256
            ) or (
                prior_hash is not None and prior_hash.work_id != source.work_id
            ):
                raise AddStoppedV1("failed", "content_identity_collision")
            sources_by_id[source_id] = source
            sources_by_hash[source.source_sha256] = source
        if active_pointer is not None:
            active_source = sources_by_id.get(active_pointer.source_id)
            if (
                active_source is None
                or active_source.work_id != work_id
                or active_source.source_sha256 != active_pointer.source_sha256
                or active_source.manifest_sha256
                != active_pointer.manifest_sha256
            ):
                raise AddStoppedV1("failed", "content_identity_collision")
    return _AuthoritySnapshotV1(
        works=works,
        sources_by_id=sources_by_id,
        sources_by_hash=sources_by_hash,
        alias_owners={key: frozenset(value) for key, value in owners.items()},
    )


def _reservation_document(
    validated: ValidatedAddInputV1,
    snapshot: _PdfSnapshotV1,
    work_id: str,
) -> dict[str, object]:
    return {
        "arxiv_id": validated.arxiv_id,
        "citation": validated.citation,
        "doi": validated.doi,
        "schema_version": "gezhi.literature_intake_reservation.v1",
        "source_id": snapshot.source_id,
        "source_sha256": snapshot.source_sha256,
        "work_id": work_id,
    }


def _load_reservations(root_path: Path) -> tuple[_IdentityReservationV1, ...]:
    reservation_dir = root_path / "works" / ".staging" / "reservations"
    if not reservation_dir.exists():
        return ()
    if not _is_plain_directory(reservation_dir):
        raise AddStoppedV1("blocked", "identity_review_required")
    try:
        entries = tuple(reservation_dir.iterdir())
    except OSError as error:
        raise AddStoppedV1("failed", "commit_failed") from error
    observed: list[_IdentityReservationV1] = []
    for path in entries:
        if path.suffix != ".json" or _SOURCE_ID.fullmatch(path.stem) is None:
            raise AddStoppedV1("blocked", "identity_review_required")
        try:
            value, _payload = _read_canonical_document(path)
        except ValueError as error:
            raise AddStoppedV1(
                "blocked", "identity_review_required"
            ) from error
        if (
            set(value)
            != {
                "arxiv_id",
                "citation",
                "doi",
                "schema_version",
                "source_id",
                "source_sha256",
                "work_id",
            }
            or value.get("schema_version")
            != "gezhi.literature_intake_reservation.v1"
            or value.get("source_id") != path.stem
            or type(value.get("source_sha256")) is not str
            or _SHA256.fullmatch(str(value["source_sha256"])) is None
            or value["source_id"]
            != "src_" + str(value["source_sha256"])[:24]
            or type(value.get("work_id")) is not str
            or _WORK_ID.fullmatch(str(value["work_id"])) is None
            or (
                value.get("doi") is not None and not _valid_doi(value.get("doi"))
            )
            or (
                value.get("arxiv_id") is not None
                and not _valid_arxiv_id(value.get("arxiv_id"))
            )
            or (
                value.get("citation") is not None
                and _normalize_citation(value.get("citation"))
                != value.get("citation")
            )
        ):
            raise AddStoppedV1("blocked", "identity_review_required")
        observed.append(
            _IdentityReservationV1(
                arxiv_id=cast(str | None, value["arxiv_id"]),
                citation=cast(str | None, value["citation"]),
                doi=cast(str | None, value["doi"]),
                source_id=cast(str, value["source_id"]),
                source_sha256=cast(str, value["source_sha256"]),
                work_id=cast(str, value["work_id"]),
                path=path,
            )
        )
    return tuple(observed)


def _ensure_reservation(
    root_path: Path,
    validated: ValidatedAddInputV1,
    snapshot: _PdfSnapshotV1,
    work_id: str,
    reservations: tuple[_IdentityReservationV1, ...],
) -> _IdentityReservationV1:
    matching = tuple(
        item for item in reservations if item.source_id == snapshot.source_id
    )
    if matching:
        if len(matching) != 1:
            raise AddStoppedV1("blocked", "identity_review_required")
        reservation = matching[0]
        if reservation.source_sha256 != snapshot.source_sha256:
            raise AddStoppedV1("failed", "content_identity_collision")
        if reservation.work_id != work_id:
            raise AddStoppedV1("blocked", "identity_review_required")
        return reservation
    reservation_dir = root_path / "works" / ".staging" / "reservations"
    _ensure_plain_directory(reservation_dir)
    path = reservation_dir / f"{snapshot.source_id}.json"
    _write_new_verified(
        path,
        _canonical_json_bytes(
            _reservation_document(validated, snapshot, work_id)
        ),
    )
    return _IdentityReservationV1(
        arxiv_id=validated.arxiv_id,
        citation=validated.citation,
        doi=validated.doi,
        source_id=snapshot.source_id,
        source_sha256=snapshot.source_sha256,
        work_id=work_id,
        path=path,
    )


def _remove_reservation(reservation: _IdentityReservationV1) -> None:
    try:
        reservation.path.unlink()
        reservation.path.parent.rmdir()
    except OSError:
        # A stale valid reservation remains a conservative identity fact.
        return


def _files_equal(first: Path, second: Path) -> bool:
    try:
        with open_validated_local_file_v1(str(first)) as left, (
            open_validated_local_file_v1(str(second))
        ) as right:
            if left.size != right.size:
                return False
            left_chunks = left.iter_verified_chunks_v1()
            right_chunks = right.iter_verified_chunks_v1()
            while True:
                left_chunk = next(left_chunks, None)
                right_chunk = next(right_chunks, None)
                if left_chunk != right_chunk:
                    return False
                if left_chunk is None:
                    return True
    except DataRootOpenErrorV1 as error:
        raise AddStoppedV1("failed", "commit_failed") from error


def _resolve_work(
    validated: ValidatedAddInputV1,
    snapshot: _PdfSnapshotV1,
    authority: _AuthoritySnapshotV1,
    reservations: tuple[_IdentityReservationV1, ...] = (),
    *,
    proposed_new_work_id: str | None = None,
) -> tuple[str, bool]:
    same_source = authority.sources_by_hash.get(snapshot.source_sha256)
    short_source = authority.sources_by_id.get(snapshot.source_id)
    if short_source is not None and (
        short_source.source_sha256 != snapshot.source_sha256
        or not _files_equal(short_source.directory / "original.pdf", snapshot.original_path)
    ):
        raise AddStoppedV1("failed", "content_identity_collision")
    strong_owners: set[str] = set()
    if same_source is not None:
        if not _files_equal(
            same_source.directory / "original.pdf", snapshot.original_path
        ):
            raise AddStoppedV1("failed", "content_identity_collision")
        strong_owners.add(same_source.work_id)
    matching_reservations = tuple(
        item
        for item in reservations
        if item.source_id == snapshot.source_id
        or item.source_sha256 == snapshot.source_sha256
    )
    if any(
        item.source_id == snapshot.source_id
        and item.source_sha256 != snapshot.source_sha256
        for item in matching_reservations
    ):
        raise AddStoppedV1("failed", "content_identity_collision")
    strong_owners.update(item.work_id for item in matching_reservations)
    for kind, value in (("doi", validated.doi), ("arxiv_id", validated.arxiv_id)):
        if value is not None:
            owners = authority.alias_owners.get((kind, value), frozenset())
            if len(owners) > 1:
                raise AddStoppedV1("blocked", "identity_review_required")
            strong_owners.update(owners)
            reserved_owners = {
                item.work_id
                for item in reservations
                if getattr(item, kind) == value
            }
            if len(reserved_owners) > 1:
                raise AddStoppedV1("blocked", "identity_review_required")
            strong_owners.update(reserved_owners)

    if validated.work_id is not None:
        if validated.work_id not in authority.works:
            raise AddStoppedV1("blocked", "work_not_found")
        if strong_owners - {validated.work_id}:
            raise AddStoppedV1("blocked", "identity_conflict")
        target = validated.work_id
        created = False
    else:
        if len(strong_owners) > 1:
            raise AddStoppedV1("blocked", "identity_review_required")
        if strong_owners:
            target = next(iter(strong_owners))
            created = target not in authority.works
        else:
            if validated.citation is not None:
                weak_owners = set(authority.alias_owners.get(
                    ("citation", validated.citation), frozenset()
                ))
                weak_owners.update(
                    item.work_id
                    for item in reservations
                    if item.citation == validated.citation
                )
                if weak_owners:
                    raise AddStoppedV1("blocked", "identity_review_required")
            target = proposed_new_work_id or "wrk_" + str(uuid.uuid4())
            created = True

    if validated.citation is not None:
        weak_owners = set(authority.alias_owners.get(
            ("citation", validated.citation), frozenset()
        ))
        weak_owners.update(
            item.work_id
            for item in reservations
            if item.citation == validated.citation
        )
        if weak_owners - {target}:
            raise AddStoppedV1("blocked", "identity_review_required")
    return target, created


def _write_work_identity(
    work_dir: Path,
    work_id: str,
    existing: _WorkStateV1 | None,
    validated: ValidatedAddInputV1,
    *,
    root: ValidatedDataRootV1,
) -> tuple[dict[str, frozenset[str]], str]:
    aliases = {
        "doi": set() if existing is None else set(existing.aliases["doi"]),
        "arxiv_id": (
            set() if existing is None else set(existing.aliases["arxiv_id"])
        ),
        "citation": (
            set() if existing is None else set(existing.aliases["citation"])
        ),
    }
    for kind, value in (
        ("doi", validated.doi),
        ("arxiv_id", validated.arxiv_id),
        ("citation", validated.citation),
    ):
        if value is not None:
            aliases[kind].add(value)
    revision = {
        "arxiv_ids": sorted(aliases["arxiv_id"], key=lambda item: item.encode("utf-8")),
        "citations": sorted(aliases["citation"], key=lambda item: item.encode("utf-8")),
        "dois": sorted(aliases["doi"], key=lambda item: item.encode("utf-8")),
        "schema_version": "gezhi.literature_work_identity.v1",
        "work_id": work_id,
    }
    payload = _canonical_json_bytes(revision)
    identity_sha256 = hashlib.sha256(payload).hexdigest()
    revision_name = "idrev_" + identity_sha256[:24] + ".json"
    identity_dir = work_dir / "identity"
    revisions = identity_dir / "revisions"
    _ensure_plain_directory(identity_dir)
    _ensure_plain_directory(revisions)
    revision_path = revisions / revision_name
    if revision_path.exists():
        try:
            if _read_safe_bytes(revision_path, limit=len(payload)) != payload:
                raise AddStoppedV1("failed", "content_identity_collision")
        except (OSError, ValueError) as error:
            raise AddStoppedV1("failed", "commit_failed") from error
    else:
        _write_new_verified(revision_path, payload)
    _root_checkpoint(root)
    _atomic_replace_json(
        identity_dir,
        "current.json",
        {
            "identity_sha256": identity_sha256,
            "revision": revision_name,
            "schema_version": "gezhi.literature_work_identity_current.v1",
            "work_id": work_id,
        },
    )
    frozen = {kind: frozenset(values) for kind, values in aliases.items()}
    return frozen, identity_sha256


def _write_source_bundle(
    work_dir: Path,
    work_id: str,
    snapshot: _PdfSnapshotV1,
    *,
    root: ValidatedDataRootV1,
) -> _SourceStateV1:
    sources = work_dir / "sources"
    source_staging = sources / ".staging"
    _ensure_plain_directory(sources)
    _ensure_plain_directory(source_staging)
    stage = source_staging / (
        snapshot.source_id + "-" + uuid.uuid4().hex
    )
    _ensure_plain_directory(stage)
    try:
        os.rename(snapshot.original_path, stage / "original.pdf")
    except OSError as error:
        raise AddStoppedV1("failed", "commit_failed") from error
    source = {
        "byte_length": snapshot.byte_length,
        "media_type": "application/pdf",
        "schema_version": "gezhi.literature_source.v1",
        "source_id": snapshot.source_id,
        "source_sha256": snapshot.source_sha256,
        "work_id": work_id,
    }
    source_bytes = _canonical_json_bytes(source)
    _write_new_verified(stage / "source.json", source_bytes)
    manifest = {
        "assets": [
            {
                "byte_length": snapshot.byte_length,
                "media_type": "application/pdf",
                "path": "original.pdf",
                "sha256": snapshot.source_sha256,
            },
            {
                "byte_length": len(source_bytes),
                "media_type": "application/json",
                "path": "source.json",
                "schema_version": "gezhi.literature_source.v1",
                "sha256": hashlib.sha256(source_bytes).hexdigest(),
            },
        ],
        "schema_version": "gezhi.literature_source_manifest.v1",
        "source_id": snapshot.source_id,
        "source_sha256": snapshot.source_sha256,
        "work_id": work_id,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    _write_new_verified(stage / "manifest.json", manifest_bytes)
    try:
        observed = _load_source(
            stage,
            work_id=work_id,
            source_id=snapshot.source_id,
        )
    except (OSError, ValueError) as error:
        raise AddStoppedV1("failed", "commit_failed") from error
    target = sources / snapshot.source_id
    _root_checkpoint(root)
    try:
        os.rename(stage, target)
    except FileExistsError as error:
        raise AddStoppedV1("failed", "content_identity_collision") from error
    except OSError as error:
        raise AddStoppedV1("failed", "commit_failed") from error
    return _SourceStateV1(
        work_id=work_id,
        source_id=snapshot.source_id,
        source_sha256=snapshot.source_sha256,
        byte_length=snapshot.byte_length,
        manifest_sha256=observed.manifest_sha256,
        directory=target,
    )


def _recover_staged_new_work(
    work_stage: Path,
    work_id: str,
    snapshot: _PdfSnapshotV1,
    validated: ValidatedAddInputV1,
    *,
    root: ValidatedDataRootV1,
) -> tuple[_SourceStateV1, dict[str, frozenset[str]], str]:
    try:
        if not _is_plain_directory(work_stage):
            raise ValueError("staged Work directory is unsafe")
        entries = {entry.name: entry for entry in work_stage.iterdir()}
        allowed = {
            "active_source.json",
            "handoffs",
            "identity",
            "reviews",
            "sources",
            "work.json",
        }
        if (
            not {"identity", "sources", "work.json"}.issubset(entries)
            or set(entries) - allowed
            or any(
                name in entries and not _is_plain_directory(entries[name])
                for name in ("handoffs", "identity", "reviews", "sources")
            )
        ):
            raise ValueError("staged Work inventory is invalid")
        work, _work_bytes = _read_canonical_document(work_stage / "work.json")
        if work != {
            "schema_version": "gezhi.literature_work.v1",
            "work_id": work_id,
        }:
            raise ValueError("staged Work descriptor is invalid")
        source = _load_source(
            work_stage / "sources" / snapshot.source_id,
            work_id=work_id,
            source_id=snapshot.source_id,
        )
        if (
            source.source_sha256 != snapshot.source_sha256
            or not _files_equal(
                source.directory / "original.pdf", snapshot.original_path
            )
        ):
            raise AddStoppedV1("failed", "content_identity_collision")
        active_pointer = _load_active_source(work_stage, work_id)
        aliases, identity_sha256 = _load_work_identity(work_stage, work_id)
        existing = _WorkStateV1(
            work_id=work_id,
            directory=work_stage,
            aliases=aliases,
            identity_sha256=identity_sha256,
            active_source_id=(
                None if active_pointer is None else active_pointer.source_id
            ),
        )
    except AddStoppedV1:
        raise
    except (OSError, ValueError) as error:
        raise AddStoppedV1("failed", "commit_failed") from error
    aliases, identity_sha256 = _write_work_identity(
        work_stage,
        work_id,
        existing,
        validated,
        root=root,
    )
    if existing.active_source_id is None:
        _root_checkpoint(root)
        _atomic_replace_json(
            work_stage,
            "active_source.json",
            _active_source_document(work_id, source),
        )
    elif existing.active_source_id != source.source_id:
        raise AddStoppedV1("failed", "content_identity_collision")
    _remove_consumed_intake(snapshot)
    return source, aliases, identity_sha256


def _active_source_document(
    work_id: str,
    source: _SourceStateV1,
) -> dict[str, object]:
    return {
        "manifest_sha256": source.manifest_sha256,
        "schema_version": "gezhi.literature_active_source.v1",
        "source_id": source.source_id,
        "source_sha256": source.source_sha256,
        "work_id": work_id,
    }


def _remove_consumed_intake(snapshot: _PdfSnapshotV1) -> None:
    try:
        if snapshot.original_path.exists():
            snapshot.original_path.unlink()
        snapshot.stage_dir.rmdir()
    except OSError:
        # A settled private staging artifact is ignored by every authority reader.
        return


def _project_catalog(
    root_path: Path,
    *,
    root: ValidatedDataRootV1,
) -> None:
    database_path = root_path / "catalog.sqlite3"
    temporary_path = root_path / f".catalog-{uuid.uuid4().hex}.tmp"
    try:
        authority = _authority_snapshot(root_path)
        with closing(sqlite3.connect(temporary_path)) as database:
            database.executescript(
                """
                PRAGMA journal_mode=DELETE;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS metadata (
                    schema_version TEXT PRIMARY KEY
                ) STRICT;
                CREATE TABLE IF NOT EXISTS works (
                    work_id TEXT PRIMARY KEY,
                    active_source_id TEXT NOT NULL,
                    identity_sha256 TEXT NOT NULL
                ) STRICT;
                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT PRIMARY KEY,
                    source_sha256 TEXT NOT NULL UNIQUE,
                    work_id TEXT NOT NULL,
                    byte_length INTEGER NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    FOREIGN KEY(work_id) REFERENCES works(work_id)
                ) STRICT;
                CREATE TABLE IF NOT EXISTS work_aliases (
                    work_id TEXT NOT NULL,
                    alias_kind TEXT NOT NULL,
                    alias_value TEXT NOT NULL,
                    identity_sha256 TEXT NOT NULL,
                    PRIMARY KEY(work_id, alias_kind, alias_value),
                    FOREIGN KEY(work_id) REFERENCES works(work_id)
                ) STRICT;
                CREATE UNIQUE INDEX IF NOT EXISTS strong_alias_owner
                ON work_aliases(alias_kind, alias_value)
                WHERE alias_kind IN ('doi', 'arxiv_id');
                """
            )
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                "INSERT INTO metadata(schema_version) VALUES (?)",
                ("gezhi.literature_catalog.v1",),
            )
            for work_id in sorted(authority.works, key=lambda item: item.encode("ascii")):
                work = authority.works[work_id]
                if work.active_source_id is None:
                    raise sqlite3.IntegrityError("Work has no Active Source")
                active = authority.sources_by_id.get(work.active_source_id)
                if active is None or active.work_id != work_id:
                    raise sqlite3.IntegrityError("Active Source is invalid")
                database.execute(
                    "INSERT INTO works(work_id, active_source_id, "
                    "identity_sha256) VALUES (?, ?, ?)",
                    (work_id, work.active_source_id, work.identity_sha256),
                )
                for kind in ("doi", "arxiv_id", "citation"):
                    for value in sorted(
                        work.aliases[kind], key=lambda item: item.encode("utf-8")
                    ):
                        database.execute(
                            "INSERT INTO work_aliases("
                            "work_id, alias_kind, alias_value, identity_sha256"
                            ") VALUES (?, ?, ?, ?)",
                            (work_id, kind, value, work.identity_sha256),
                        )
            for source_id in sorted(
                authority.sources_by_id, key=lambda item: item.encode("ascii")
            ):
                source = authority.sources_by_id[source_id]
                database.execute(
                    "INSERT INTO sources(source_id, source_sha256, work_id, "
                    "byte_length, manifest_sha256) VALUES (?, ?, ?, ?, ?)",
                    (
                        source.source_id,
                        source.source_sha256,
                        source.work_id,
                        source.byte_length,
                        source.manifest_sha256,
                    ),
                )
            database.commit()
            if database.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise sqlite3.DatabaseError("catalog integrity check failed")
        _root_checkpoint(root)
        os.replace(temporary_path, database_path)
    except (OSError, ValueError, sqlite3.Error) as error:
        raise AddStoppedV1("failed", "catalog_projection_failed") from error


def add_local_pdf(
    request: AddLocalPdfRequestV1,
    *,
    root: ValidatedDataRootV1,
) -> AddLocalPdfResultV1:
    validated = validate_add_request_v1(request)
    root_identity = root.inspection.identity
    root_path_text = root.inspection.canonical_path
    if root_identity is None or root_path_text is None:
        raise RuntimeError("validated Literature root is incomplete")
    identity_owner = try_acquire_identity_intake_v1(root_identity)
    if identity_owner is None:
        raise AddStoppedV1("blocked", "identity_intake_busy")
    try:
        _root_checkpoint(root)
        pdf = _create_pdf_snapshot(root, validated)
        _root_checkpoint(root)
        root_path = Path(root_path_text)
        authority = _authority_snapshot(root_path)
        reservations = _load_reservations(root_path)
        work_id, created_work = _resolve_work(
            validated,
            pdf,
            authority,
            reservations,
        )
        reservation = _ensure_reservation(
            root_path,
            validated,
            pdf,
            work_id,
            reservations,
        )
    finally:
        identity_owner.close()

    work_owner = try_acquire_work_writer_v1(root_identity, work_id)
    if work_owner is None:
        raise AddStoppedV1("blocked", "work_busy")
    try:
        _root_checkpoint(root)
        root_path = Path(root_path_text)
        authority = _authority_snapshot(root_path)
        reservations = _load_reservations(root_path)
        confirmed_work_id, confirmed_created = _resolve_work(
            validated,
            pdf,
            authority,
            reservations,
            proposed_new_work_id=work_id if created_work else None,
        )
        if confirmed_work_id != work_id or confirmed_created != created_work:
            raise AddStoppedV1("blocked", "identity_review_required")
        existing_work = authority.works.get(work_id)
        existing_source = authority.sources_by_hash.get(pdf.source_sha256)

        works_path = root_path / "works"
        if created_work:
            work_stage = works_path / ".staging" / work_id
            if work_stage.exists():
                source, _aliases, _identity_sha256 = _recover_staged_new_work(
                    work_stage,
                    work_id,
                    pdf,
                    validated,
                    root=root,
                )
                work_dir = work_stage
            else:
                work_dir = pdf.stage_dir
                _write_new_verified(
                    work_dir / "work.json",
                    _canonical_json_bytes(
                        {
                            "schema_version": "gezhi.literature_work.v1",
                            "work_id": work_id,
                        }
                    ),
                )
                source = _write_source_bundle(
                    work_dir,
                    work_id,
                    pdf,
                    root=root,
                )
                _aliases, _identity_sha256 = _write_work_identity(
                    work_dir,
                    work_id,
                    None,
                    validated,
                    root=root,
                )
                _root_checkpoint(root)
                _atomic_replace_json(
                    work_dir,
                    "active_source.json",
                    _active_source_document(work_id, source),
                )
                _root_checkpoint(root)
                try:
                    os.rename(work_dir, work_stage)
                except FileExistsError as error:
                    raise AddStoppedV1("failed", "commit_failed") from error
                except OSError as error:
                    raise AddStoppedV1("failed", "commit_failed") from error
                work_dir = work_stage
            _root_checkpoint(root)
            target = works_path / work_id
            try:
                os.rename(work_dir, target)
            except FileExistsError as error:
                raise AddStoppedV1("failed", "commit_failed") from error
            except OSError as error:
                raise AddStoppedV1("failed", "commit_failed") from error
            source = _SourceStateV1(
                work_id=source.work_id,
                source_id=source.source_id,
                source_sha256=source.source_sha256,
                byte_length=source.byte_length,
                manifest_sha256=source.manifest_sha256,
                directory=target / "sources" / source.source_id,
            )
            active_changed = True
            disposition: Literal[
                "created_work", "added_source", "reused_source"
            ] = "created_work"
        else:
            if existing_work is None:
                raise AddStoppedV1("blocked", "work_not_found")
            work_dir = existing_work.directory
            if existing_source is None:
                source = _write_source_bundle(
                    work_dir,
                    work_id,
                    pdf,
                    root=root,
                )
                _remove_consumed_intake(pdf)
                disposition = "added_source"
            else:
                source = existing_source
                disposition = "reused_source"
                _remove_consumed_intake(pdf)
            _aliases, _identity_sha256 = _write_work_identity(
                work_dir,
                work_id,
                existing_work,
                validated,
                root=root,
            )
            active_changed = existing_work.active_source_id != source.source_id
            if active_changed:
                _root_checkpoint(root)
                _atomic_replace_json(
                    work_dir,
                    "active_source.json",
                    _active_source_document(work_id, source),
                )

        _root_checkpoint(root)
        _remove_reservation(reservation)
        catalog_owner = try_acquire_catalog_projection_v1(root_identity)
        if catalog_owner is None:
            raise AddStoppedV1("failed", "catalog_projection_failed")
        try:
            _project_catalog(Path(root_path_text), root=root)
        finally:
            catalog_owner.close()
        return AddLocalPdfResultV1(
            active_source_changed=active_changed,
            disposition=disposition,
            source_id=source.source_id,
            source_sha256=source.source_sha256,
            work_id=work_id,
        )
    finally:
        work_owner.close()
