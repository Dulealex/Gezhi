from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import time
import uuid
import zlib
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Literal, NoReturn, TypeAlias, cast

from pypdf import PageObject, PdfReader

from gezhi._bounded_probe import (
    ProbeOutputLimitExceeded,
    ProbeUnavailableError,
    run_bounded_probe_v1,
)
from gezhi._literature_intake import (
    ActiveSourceAuthorityStoppedV1,
    ActiveSourceAuthorityV1,
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
from gezhi._windows_ownership import try_acquire_work_writer_v1

_WORK_ID = re.compile(
    r"^wrk_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SOURCE_ID = re.compile(r"^src_[0-9a-f]{24}$")
_RUN_ID = re.compile(
    r"^ocrrun_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_INT64 = 9_223_372_036_854_775_807
_SELECTOR_PROFILE = "native_text_every_page_32_v1"
_MINIMUM_NON_WHITESPACE = 32
_OCR_TIMEOUT_SECONDS = 900.0
_OCR_OUTPUT_LIMIT = 1_048_576
_OCR_RETRY_BACKOFF_SECONDS = 10.0
_OCR_ARTIFACT_FILE_LIMIT = 536_870_912
_OCR_ARTIFACT_AGGREGATE_LIMIT = 2_147_483_648
_OCR_ARTIFACT_FILE_COUNT_LIMIT = 4_096
_OCR_AUDIT_FREE_SPACE_RESERVE = 16_777_216
_OCR_JSON_FILE_LIMIT = 67_108_864
_OCR_MARKDOWN_FILE_LIMIT = 67_108_864
_OCR_IMAGE_FILE_LIMIT = 67_108_864
_OCR_PDF_FILE_LIMIT = 134_217_728
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_STAGES = (
    "ingest",
    "ocr",
    "canonicalize",
    "read",
    "review",
    "handoff",
    "knowledge_import",
)

ResumeOutcome: TypeAlias = Literal["blocked", "failed"]
ResumeStage: TypeAlias = Literal[
    "ingest",
    "ocr",
    "canonicalize",
    "read",
    "review",
    "handoff",
    "knowledge_import",
]
OcrMethod: TypeAlias = Literal["native_text", "mineru_ocr"]


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


_NATIVE_PROFILE_DOCUMENT = {
    "provider": "native_text",
    "pypdf": "6.14.2",
    "selector_profile": _SELECTOR_PROFILE,
}
_MINERU_PROFILE_DOCUMENT = {
    "backend": "pipeline",
    "cuda_build": "13.0",
    "device": "NVIDIA GeForce RTX 4090",
    "language": "ch",
    "method": "ocr",
    "mineru": "3.4.4",
    "model_id": "OpenDataLab/PDF-Extract-Kit-1.0",
    "model_manifest_sha256": (
        "c338109a48b0a979478e9fbae0650d169024fbe4e3f4fb37565551726303fb20"
    ),
    "model_snapshot": "master",
    "offline": True,
    "loopback_no_proxy": "127.0.0.1,localhost",
    "python": "3.11.15",
    "six": "1.17.0",
    "torch": "2.9.1+cu130",
    "torchvision": "0.24.1+cu130",
}
_NATIVE_PROFILE_IDENTITY = hashlib.sha256(
    _canonical_json_bytes(_NATIVE_PROFILE_DOCUMENT)
).hexdigest()
_MINERU_PROFILE_IDENTITY = hashlib.sha256(
    _canonical_json_bytes(_MINERU_PROFILE_DOCUMENT)
).hexdigest()


def expected_ocr_profile_identity_sha256_v1() -> str:
    return _MINERU_PROFILE_IDENTITY


@dataclass(frozen=True, slots=True)
class OcrRuntimeProfileV1:
    executable_path: str
    environment: tuple[tuple[str, str], ...]
    profile_identity_sha256: str


@dataclass(frozen=True, slots=True)
class OcrAttemptResultV1:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True, slots=True)
class ResumeWorkResultV1:
    active_source_id: str
    advanced_stages: tuple[ResumeStage, ...]
    pending_candidate_ids: tuple[str, ...]
    pipeline_complete: bool
    start_stage: ResumeStage | Literal["complete"]
    stop_stage: ResumeStage | Literal["complete"]
    work_id: str

    def as_mapping_v1(self) -> dict[str, object]:
        return {
            "active_source_id": self.active_source_id,
            "advanced_stages": list(self.advanced_stages),
            "pending_candidate_ids": list(self.pending_candidate_ids),
            "pipeline_complete": self.pipeline_complete,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": self.start_stage,
            "stop_stage": self.stop_stage,
            "work_id": self.work_id,
        }


class ResumeStoppedV1(RuntimeError):
    def __init__(
        self,
        outcome: ResumeOutcome,
        reason: str,
        *,
        stage: ResumeStage | None = None,
        data_root: Literal["literature", "knowledge"] | None = None,
        result: ResumeWorkResultV1 | None = None,
    ) -> None:
        super().__init__(f"Literature resume {outcome}: {reason}")
        self.outcome = outcome
        self.reason = reason
        self.stage = stage
        self.data_root = data_root
        self.result = result


class OcrRuntimeUnavailableV1(RuntimeError):
    pass


class _CommitFailedV1(RuntimeError):
    pass


class _OcrOutputInvalidV1(RuntimeError):
    pass


class _RunInvalidV1(RuntimeError):
    pass


class _RecoveryCertaintyLostV1(RuntimeError):
    """A namespace mutation cannot be represented by a handled receipt."""


class _OcrArtifactBudgetExceededV1(RuntimeError):
    """Provider output cannot remain inside the frozen audit budget."""


@dataclass(frozen=True, slots=True)
class _SelectionV1:
    method: OcrMethod
    reason: str
    page_count: int | None
    non_whitespace_counts: tuple[int, ...]
    page_texts: tuple[str, ...]

    def document_v1(self) -> dict[str, object]:
        return {
            "method": self.method,
            "minimum_non_whitespace_per_page": _MINIMUM_NON_WHITESPACE,
            "non_whitespace_counts": list(self.non_whitespace_counts),
            "page_count": self.page_count,
            "reason": self.reason,
            "schema_version": "gezhi.literature_ocr_selection.v1",
            "selector_profile": _SELECTOR_PROFILE,
        }


@dataclass(frozen=True, slots=True)
class _PdfPageEvidenceV1:
    media_box: tuple[float, float, float, float]
    crop_box: tuple[float, float, float, float]
    rotation: int
    user_unit: float
    content_stream_sha256: tuple[str, ...]
    xobjects: tuple[tuple[str, str, int | None, int | None, str], ...]


@dataclass(frozen=True, slots=True)
class _ValidatedRunV1:
    path: Path
    run_id: str
    method: OcrMethod
    status: Literal["succeeded", "blocked", "failed"]
    reason: str | None
    input_fingerprint_sha256: str
    provider_profile_identity_sha256: str
    manifest_sha256: str
    work_id: str
    source_id: str


def _write_all(destination: BinaryIO, payload: bytes) -> None:
    offset = 0
    view = memoryview(payload)
    while offset < len(payload):
        count = destination.write(view[offset:])
        remaining = len(payload) - offset
        if type(count) is not int or not 1 <= count <= remaining:
            raise OSError("file write did not complete deterministically")
        offset += count


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
        raise _CommitFailedV1("OCR directory commit failed") from error


def _safe_entry_names(path: Path) -> frozenset[str]:
    try:
        with open_validated_data_root_v1(str(path)):
            return frozenset(item.name for item in path.iterdir())
    except (DataRootOpenErrorV1, OSError) as error:
        raise _RunInvalidV1("OCR directory inventory is invalid") from error


def _read_safe_bytes(path: Path, *, limit: int = _MAX_INT64) -> bytes:
    try:
        with open_validated_local_file_v1(str(path)) as source:
            return source.read_bytes_v1(limit=limit)
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        raise _RunInvalidV1("OCR asset is unreadable") from error


def _read_canonical_document(path: Path) -> tuple[dict[str, object], bytes]:
    payload = _read_safe_bytes(path)
    try:
        value = json.loads(payload)
        canonical = _canonical_json_bytes(value)
    except (TypeError, ValueError) as error:
        raise _RunInvalidV1("OCR document is invalid") from error
    if type(value) is not dict or payload != canonical:
        raise _RunInvalidV1("OCR document is not canonical")
    return cast(dict[str, object], value), payload


def _write_new_verified(path: Path, payload: bytes) -> None:
    try:
        with (
            open_validated_data_root_v1(str(path.parent)),
            path.open("xb", buffering=0) as destination,
        ):
            _write_all(destination, payload)
        if _read_safe_bytes(path, limit=len(payload)) != payload:
            raise OSError("OCR asset readback differs")
    except (_RunInvalidV1, DataRootOpenErrorV1, OSError) as error:
        raise _CommitFailedV1("OCR asset commit failed") from error


def _copy_source_to_private_input(
    authority: ActiveSourceAuthorityV1,
    destination: Path,
) -> None:
    digest = hashlib.sha256()
    length = 0
    try:
        with (
            open_validated_data_root_v1(str(destination.parent)),
            open_validated_local_file_v1(
                str(authority.original_pdf_path)
            ) as source,
            destination.open("xb", buffering=0) as target,
        ):
            for chunk in source.iter_verified_chunks_v1():
                _write_all(target, chunk)
                digest.update(chunk)
                length += len(chunk)
        with open_validated_local_file_v1(str(destination)) as copied:
            copied_hash = copied.sha256_v1()
            copied_length = copied.size
    except (DataRootOpenErrorV1, OSError) as error:
        raise _CommitFailedV1("OCR private input copy failed") from error
    if (
        length != authority.source_byte_length
        or copied_length != length
        or digest.hexdigest() != authority.source_sha256
        or copied_hash != authority.source_sha256
    ):
        raise ResumeStoppedV1("failed", "active_source_invalid")


def _remove_private_input(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
        path.parent.rmdir()
    except OSError as error:
        raise _CommitFailedV1("OCR private input cleanup failed") from error


def _select_source_text_v1(pdf_path: Path) -> _SelectionV1:
    try:
        stable_input = open_validated_local_file_v1(str(pdf_path))
    except DataRootOpenErrorV1 as error:
        raise _CommitFailedV1("OCR selector input is unavailable") from error
    try:
        with stable_input:
            try:
                reader = PdfReader(str(pdf_path), strict=True)
                texts: list[str] = []
                counts: list[int] = []
                for page in reader.pages:
                    text = page.extract_text() or ""
                    texts.append(text)
                    counts.append(sum(not character.isspace() for character in text))
            except Exception:  # noqa: BLE001 - failure to prove text selects OCR.
                return _SelectionV1(
                    method="mineru_ocr",
                    reason="native_text_proof_unavailable",
                    page_count=None,
                    non_whitespace_counts=(),
                    page_texts=(),
                )
    except DataRootLifecycleErrorV1 as error:
        raise _CommitFailedV1("OCR selector input could not be settled") from error
    if not texts:
        return _SelectionV1(
            method="mineru_ocr",
            reason="no_pages",
            page_count=0,
            non_whitespace_counts=(),
            page_texts=(),
        )
    if any(count < _MINIMUM_NON_WHITESPACE for count in counts):
        return _SelectionV1(
            method="mineru_ocr",
            reason="page_below_minimum",
            page_count=len(texts),
            non_whitespace_counts=tuple(counts),
            page_texts=(),
        )
    return _SelectionV1(
        method="native_text",
        reason="all_pages_meet_minimum",
        page_count=len(texts),
        non_whitespace_counts=tuple(counts),
        page_texts=tuple(texts),
    )


def _input_document(
    authority: ActiveSourceAuthorityV1,
    selection_bytes: bytes,
    *,
    provider_profile_identity_sha256: str,
) -> dict[str, object]:
    identity = {
        "provider_profile_identity_sha256": provider_profile_identity_sha256,
        "schema_version": "gezhi.literature_ocr_input.v1",
        "selection_sha256": hashlib.sha256(selection_bytes).hexdigest(),
        "source_id": authority.source_id,
        "source_manifest_sha256": authority.source_manifest_sha256,
        "source_sha256": authority.source_sha256,
        "work_id": authority.work_id,
    }
    fingerprint = hashlib.sha256(_canonical_json_bytes(identity)).hexdigest()
    return {"input_fingerprint_sha256": fingerprint, **identity}


def _profile_identity_for_method(method: OcrMethod) -> str:
    return (
        _NATIVE_PROFILE_IDENTITY
        if method == "native_text"
        else _MINERU_PROFILE_IDENTITY
    )


def _resolve_ocr_runtime_v1() -> OcrRuntimeProfileV1:
    from gezhi._doctor_runtime import (  # Imported only after the OCR stage is reached.
        RuntimeUnavailableError,
        resolve_ocr_execution_runtime_v1,
    )

    try:
        runtime = resolve_ocr_execution_runtime_v1(
            project_root=Path(r"E:\Gezhi"),
            deployment_root=Path(r"E:\Gezhi"),
        )
    except RuntimeUnavailableError as error:
        raise OcrRuntimeUnavailableV1 from error
    return OcrRuntimeProfileV1(
        executable_path=runtime.executable_path,
        environment=runtime.environment,
        profile_identity_sha256=_MINERU_PROFILE_IDENTITY,
    )


def _stage_for_provider_output(output_root: Path) -> Path | None:
    if (
        output_root.name != "provider_output"
        or output_root.parent.name not in {"1", "2"}
        or output_root.parent.parent.name != "attempts"
    ):
        return None
    return output_root.parents[2]


def _provider_budget_roots(stage: Path) -> tuple[Path, ...]:
    attempts = tuple(
        stage / "attempts" / attempt / "provider_output"
        for attempt in ("1", "2")
    )
    return attempts + (stage / "output" / "mineru",)


def _scan_ocr_artifact_tree(root: Path) -> tuple[int, int]:
    try:
        root.stat(follow_symlinks=False)
    except FileNotFoundError:
        return 0, 0
    except OSError as error:
        raise _OcrArtifactBudgetExceededV1(
            "OCR artifact namespace is unavailable"
        ) from error
    count = 0
    total = 0
    directories = [root]
    seen: set[tuple[int, int]] = set()
    while directories:
        directory = directories.pop()
        try:
            directory_stat = directory.stat(follow_symlinks=False)
            identity = (directory_stat.st_dev, directory_stat.st_ino)
            if (
                directory.is_symlink()
                or getattr(directory_stat, "st_file_attributes", 0)
                & _FILE_ATTRIBUTE_REPARSE_POINT
                or not stat.S_ISDIR(directory_stat.st_mode)
                or identity in seen
            ):
                raise _OcrArtifactBudgetExceededV1(
                    "OCR artifact namespace is unsafe"
                )
            seen.add(identity)
            entries = tuple(os.scandir(directory))
        except _OcrArtifactBudgetExceededV1:
            raise
        except OSError as error:
            raise _OcrArtifactBudgetExceededV1(
                "OCR artifact namespace is unavailable"
            ) from error
        for entry in entries:
            try:
                facts = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise _OcrArtifactBudgetExceededV1(
                    "OCR artifact cannot be measured"
                ) from error
            if (
                entry.is_symlink()
                or getattr(facts, "st_file_attributes", 0)
                & _FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise _OcrArtifactBudgetExceededV1(
                    "OCR artifact reparse point is forbidden"
                )
            if stat.S_ISDIR(facts.st_mode):
                directories.append(Path(entry.path))
                continue
            if not stat.S_ISREG(facts.st_mode) or facts.st_size < 0:
                raise _OcrArtifactBudgetExceededV1(
                    "OCR artifact file type is forbidden"
                )
            count += 1
            total += facts.st_size
            if (
                facts.st_size > _OCR_ARTIFACT_FILE_LIMIT
                or count > _OCR_ARTIFACT_FILE_COUNT_LIMIT
                or total > _OCR_ARTIFACT_AGGREGATE_LIMIT
            ):
                raise _OcrArtifactBudgetExceededV1(
                    "OCR artifact budget was exceeded"
                )
    return count, total


def _enforce_ocr_artifact_budget_v1(stage: Path) -> None:
    try:
        free = shutil.disk_usage(stage).free
    except OSError as error:
        raise _OcrArtifactBudgetExceededV1(
            "OCR audit free space cannot be measured"
        ) from error
    if free < _OCR_AUDIT_FREE_SPACE_RESERVE:
        raise _OcrArtifactBudgetExceededV1(
            "OCR audit free-space reserve is unavailable"
        )
    count = 0
    total = 0
    for root in _provider_budget_roots(stage):
        root_count, root_total = _scan_ocr_artifact_tree(root)
        count += root_count
        total += root_total
        if (
            count > _OCR_ARTIFACT_FILE_COUNT_LIMIT
            or total > _OCR_ARTIFACT_AGGREGATE_LIMIT
        ):
            raise _OcrArtifactBudgetExceededV1(
                "OCR artifact aggregate budget was exceeded"
            )


def _run_ocr_attempt_v1(
    profile: OcrRuntimeProfileV1,
    input_path: Path,
    output_root: Path,
) -> OcrAttemptResultV1:
    stage = _stage_for_provider_output(output_root)
    completed = run_bounded_probe_v1(
        (
            profile.executable_path,
            "-p",
            str(input_path),
            "-o",
            str(output_root),
            "-b",
            "pipeline",
            "-m",
            "ocr",
            "-l",
            "ch",
        ),
        environment=dict(profile.environment),
        timeout_seconds=_OCR_TIMEOUT_SECONDS,
        output_limit=_OCR_OUTPUT_LIMIT,
        creation_flags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        progress_guard=(
            None
            if stage is None
            else lambda: _enforce_ocr_artifact_budget_v1(stage)
        ),
    )
    return OcrAttemptResultV1(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _run_stable_ocr_attempt_v1(
    profile: OcrRuntimeProfileV1,
    input_path: Path,
    output_root: Path,
    authority: ActiveSourceAuthorityV1,
) -> OcrAttemptResultV1:
    try:
        with open_validated_local_file_v1(str(input_path)) as stable_input:
            if (
                stable_input.size != authority.source_byte_length
                or stable_input.sha256_v1() != authority.source_sha256
            ):
                raise _CommitFailedV1("OCR private input integrity was lost")
            return _run_ocr_attempt_v1(profile, input_path, output_root)
    except (DataRootLifecycleErrorV1, DataRootOpenErrorV1) as error:
        raise _CommitFailedV1("OCR private input is unavailable") from error


def _provider_output_leaf(output_root: Path) -> Path:
    return output_root / "source" / "ocr"


_CONTENT_LIST_TYPES = frozenset(
    {
        "aside_text",
        "chart",
        "code",
        "equation",
        "footer",
        "header",
        "image",
        "index",
        "list",
        "page_footnote",
        "page_number",
        "table",
        "text",
    }
)
_CONTENT_LIST_V2_TYPES = frozenset(
    {
        "algorithm",
        "chart",
        "code",
        "equation_interline",
        "image",
        "index",
        "list",
        "page_aside_text",
        "page_footer",
        "page_footnote",
        "page_header",
        "page_number",
        "paragraph",
        "table",
        "title",
    }
)


def _valid_positive_dimension(value: object) -> bool:
    return (
        type(value) in {int, float}
        and math.isfinite(cast(float, value))
        and cast(float, value) > 0
    )


def _validate_middle_document(value: object) -> int:
    if (
        type(value) is not dict
        or value.get("_backend") != "pipeline"
        or value.get("_version_name") != "3.4.4"
        or type(value.get("pdf_info")) is not list
    ):
        raise _OcrOutputInvalidV1("MinerU middle JSON is invalid")
    pages = cast(list[object], value["pdf_info"])
    if not pages:
        raise _OcrOutputInvalidV1("MinerU middle JSON has no pages")
    for index, page in enumerate(pages):
        if type(page) is not dict:
            raise _OcrOutputInvalidV1("MinerU middle page is invalid")
        size = page.get("page_size")
        if (
            page.get("page_idx") != index
            or type(size) is not list
            or len(size) != 2
            or not all(_valid_positive_dimension(item) for item in size)
            or type(page.get("para_blocks")) is not list
            or type(page.get("discarded_blocks")) is not list
        ):
            raise _OcrOutputInvalidV1("MinerU middle page is invalid")
    return len(pages)


def _validate_content_documents(
    content_list: object,
    content_list_v2: object,
    *,
    page_count: int,
) -> None:
    if type(content_list) is not list or type(content_list_v2) is not list:
        raise _OcrOutputInvalidV1("MinerU content list is invalid")
    for item in content_list:
        if (
            type(item) is not dict
            or type(item.get("type")) is not str
            or item.get("type") not in _CONTENT_LIST_TYPES
            or type(item.get("page_idx")) is not int
            or not 0 <= cast(int, item["page_idx"]) < page_count
        ):
            raise _OcrOutputInvalidV1("MinerU content item is invalid")
    if len(content_list_v2) != page_count:
        raise _OcrOutputInvalidV1("MinerU v2 page list is invalid")
    for page in content_list_v2:
        if type(page) is not list:
            raise _OcrOutputInvalidV1("MinerU v2 page is invalid")
        for item in page:
            if (
                type(item) is not dict
                or type(item.get("type")) is not str
                or item.get("type") not in _CONTENT_LIST_V2_TYPES
                or type(item.get("content")) is not dict
                or not item["content"]
            ):
                raise _OcrOutputInvalidV1("MinerU v2 content item is invalid")


def _validate_model_document(value: object, *, page_count: int) -> None:
    if type(value) is not list or len(value) != page_count:
        raise _OcrOutputInvalidV1("MinerU model output is invalid")
    for index, item in enumerate(value):
        if type(item) is not dict or type(item.get("layout_dets")) is not list:
            raise _OcrOutputInvalidV1("MinerU model page is invalid")
        page = item.get("page_info")
        if (
            type(page) is not dict
            or page.get("page_no") != index
            or not _valid_positive_dimension(page.get("width"))
            or not _valid_positive_dimension(page.get("height"))
        ):
            raise _OcrOutputInvalidV1("MinerU model page is invalid")


def _pdf_rectangle_v1(value: object) -> tuple[float, float, float, float]:
    try:
        coordinates = tuple(
            float(cast(float, item)) for item in cast(Iterable[object], value)
        )
    except (TypeError, ValueError) as error:
        raise _OcrOutputInvalidV1("MinerU PDF page box is invalid") from error
    if (
        len(coordinates) != 4
        or not all(math.isfinite(item) for item in coordinates)
        or coordinates[2] <= coordinates[0]
        or coordinates[3] <= coordinates[1]
    ):
        raise _OcrOutputInvalidV1("MinerU PDF page box is invalid")
    return cast(tuple[float, float, float, float], coordinates)


def _resolved_pdf_object_v1(value: object) -> object:
    resolver = getattr(value, "get_object", None)
    return resolver() if callable(resolver) else value


def _bounded_flate_decode_v1(payload: bytes, *, limit: int) -> bytes:
    try:
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(payload, limit + 1)
        if len(decoded) > limit or decoder.unconsumed_tail:
            raise _OcrOutputInvalidV1("MinerU PDF content exceeds its limit")
        decoded += decoder.flush(limit + 1 - len(decoded))
    except zlib.error as error:
        raise _OcrOutputInvalidV1("MinerU PDF content stream is invalid") from error
    if (
        len(decoded) > limit
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise _OcrOutputInvalidV1("MinerU PDF content stream is invalid")
    return decoded


def _decoded_pdf_stream_hashes_v1(
    value: object,
    *,
    budget: list[int],
) -> tuple[str, ...]:
    resolved = _resolved_pdf_object_v1(value)
    if resolved is None:
        return ()
    if isinstance(resolved, list):
        return tuple(
            digest
            for item in resolved
            for digest in _decoded_pdf_stream_hashes_v1(item, budget=budget)
        )
    if not isinstance(resolved, dict):
        raise _OcrOutputInvalidV1("MinerU PDF content stream is invalid")
    payload = getattr(resolved, "_data", None)
    if type(payload) is not bytes:
        raise _OcrOutputInvalidV1("MinerU PDF content stream is invalid")
    filter_value = _resolved_pdf_object_v1(resolved.get("/Filter"))
    decode_parameters = _resolved_pdf_object_v1(resolved.get("/DecodeParms"))
    if filter_value is None:
        decoded = payload
    elif str(filter_value) in {"/Fl", "/FlateDecode"} and (
        decode_parameters is None
        or isinstance(decode_parameters, dict)
        and not decode_parameters
    ):
        decoded = _bounded_flate_decode_v1(
            payload,
            limit=_OCR_PDF_FILE_LIMIT - budget[1],
        )
    else:
        raise _OcrOutputInvalidV1("MinerU PDF content filter is unsupported")
    budget[0] += 1
    budget[1] += len(decoded)
    if (
        budget[0] > _OCR_ARTIFACT_FILE_COUNT_LIMIT
        or budget[1] > _OCR_PDF_FILE_LIMIT
    ):
        raise _OcrOutputInvalidV1("MinerU PDF content exceeds its limit")
    return (hashlib.sha256(decoded).hexdigest(),)


def _pdf_xobject_evidence_v1(page: PageObject) -> tuple[
    tuple[str, str, int | None, int | None, str], ...
]:
    records: list[tuple[str, str, int | None, int | None, str]] = []

    def collect(
        resources_value: object,
        *,
        prefix: str,
        ancestors: frozenset[int],
    ) -> None:
        resources = _resolved_pdf_object_v1(resources_value)
        if resources is None:
            return
        if not isinstance(resources, dict):
            raise _OcrOutputInvalidV1("MinerU PDF resources are invalid")
        xobjects = _resolved_pdf_object_v1(resources.get("/XObject"))
        if xobjects is None:
            return
        if not isinstance(xobjects, dict):
            raise _OcrOutputInvalidV1("MinerU PDF XObjects are invalid")
        for name, value in sorted(
            xobjects.items(),
            key=lambda item: str(item[0]).encode("utf-8"),
        ):
            xobject = _resolved_pdf_object_v1(value)
            if not isinstance(xobject, dict):
                raise _OcrOutputInvalidV1("MinerU PDF XObject is invalid")
            identity = id(xobject)
            if identity in ancestors:
                raise _OcrOutputInvalidV1("MinerU PDF XObject cycle is invalid")
            payload = getattr(xobject, "_data", None)
            if type(payload) is not bytes:
                raise _OcrOutputInvalidV1("MinerU PDF XObject stream is invalid")
            width_value = xobject.get("/Width")
            height_value = xobject.get("/Height")
            width = width_value if type(width_value) is int else None
            height = height_value if type(height_value) is int else None
            path = f"{prefix}{name}"
            records.append(
                (
                    path,
                    str(xobject.get("/Subtype")),
                    width,
                    height,
                    hashlib.sha256(payload).hexdigest(),
                )
            )
            if len(records) > _OCR_ARTIFACT_FILE_COUNT_LIMIT:
                raise _OcrOutputInvalidV1("MinerU PDF XObjects exceed their limit")
            nested = xobject.get("/Resources")
            if nested is not None:
                collect(
                    nested,
                    prefix=f"{path}/",
                    ancestors=ancestors | {identity},
                )

    collect(page.get("/Resources"), prefix="", ancestors=frozenset())
    return tuple(records)


def _pdf_page_evidence_v1(
    page: PageObject,
    *,
    decode_budget: list[int],
) -> _PdfPageEvidenceV1:
    try:
        media_box = _pdf_rectangle_v1(page.mediabox)
        crop_box = _pdf_rectangle_v1(page.cropbox)
        rotation = page.rotation
        user_unit = float(page.user_unit)
    except (AttributeError, TypeError, ValueError) as error:
        raise _OcrOutputInvalidV1("MinerU PDF page is invalid") from error
    if (
        type(rotation) is not int
        or rotation not in {0, 90, 180, 270}
        or not math.isfinite(user_unit)
        or user_unit <= 0
    ):
        raise _OcrOutputInvalidV1("MinerU PDF page is invalid")
    return _PdfPageEvidenceV1(
        media_box=media_box,
        crop_box=crop_box,
        rotation=rotation,
        user_unit=user_unit,
        content_stream_sha256=_decoded_pdf_stream_hashes_v1(
            page.get("/Contents"),
            budget=decode_budget,
        ),
        xobjects=_pdf_xobject_evidence_v1(page),
    )


def _validate_pdf_output(
    path: Path,
    *,
    page_count: int,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> tuple[_PdfPageEvidenceV1, ...]:
    try:
        with open_validated_local_file_v1(str(path)) as stable:
            if stable.size > _OCR_PDF_FILE_LIMIT:
                raise _OcrOutputInvalidV1("MinerU PDF exceeds its limit")
            if (
                expected_byte_length is not None
                and stable.size != expected_byte_length
            ):
                raise _OcrOutputInvalidV1("MinerU source PDF length differs")
            payload = stable.read_bytes_v1(limit=_OCR_PDF_FILE_LIMIT)
        if (
            expected_sha256 is not None
            and hashlib.sha256(payload).hexdigest() != expected_sha256
        ):
            raise _OcrOutputInvalidV1("MinerU source PDF hash differs")
        with BytesIO(payload) as stream:
            reader = PdfReader(stream, strict=True)
            if len(reader.pages) != page_count:
                raise _OcrOutputInvalidV1("MinerU PDF page count differs")
            decode_budget = [0, 0]
            return tuple(
                _pdf_page_evidence_v1(page, decode_budget=decode_budget)
                for page in reader.pages
            )
    except _OcrOutputInvalidV1:
        raise
    except Exception as error:
        raise _OcrOutputInvalidV1("MinerU PDF output is invalid") from error


def _validate_provider_images(leaf: Path, paths: Collection[str]) -> None:
    for path in paths:
        if not path.startswith("images/"):
            continue
        payload = _read_safe_bytes(leaf / Path(path), limit=_OCR_IMAGE_FILE_LIMIT)
        suffix = Path(path).suffix.casefold()
        if (
            suffix in {".jpg", ".jpeg"}
            and not payload.startswith(b"\xff\xd8\xff")
        ) or (suffix == ".png" and not payload.startswith(b"\x89PNG\r\n\x1a\n")):
            raise _OcrOutputInvalidV1("MinerU image output is invalid")


def _validate_provider_output(
    output_root: Path,
    authority: ActiveSourceAuthorityV1,
) -> None:
    leaf = _provider_output_leaf(output_root)
    try:
        with open_validated_data_root_v1(str(leaf)) as output:
            paths = output.relative_file_paths_v1()
            required = {
                "source.md",
                "source_content_list.json",
                "source_content_list_v2.json",
                "source_layout.pdf",
                "source_middle.json",
                "source_model.json",
                "source_origin.pdf",
                "source_span.pdf",
            }
            if not required.issubset(paths):
                raise _OcrOutputInvalidV1("MinerU output is incomplete")
            if any(
                path not in required
                and not (
                    path.startswith("images/")
                    and path.count("/") == 1
                    and path.casefold().endswith((".jpg", ".jpeg", ".png"))
                )
                for path in paths
            ):
                raise _OcrOutputInvalidV1("MinerU output inventory is invalid")
        markdown = _read_safe_bytes(
            leaf / "source.md",
            limit=_OCR_MARKDOWN_FILE_LIMIT,
        )
        markdown.decode("utf-8")
        content_list = json.loads(
            _read_safe_bytes(
                leaf / "source_content_list.json",
                limit=_OCR_JSON_FILE_LIMIT,
            )
        )
        content_list_v2 = json.loads(
            _read_safe_bytes(
                leaf / "source_content_list_v2.json",
                limit=_OCR_JSON_FILE_LIMIT,
            )
        )
        middle = json.loads(
            _read_safe_bytes(
                leaf / "source_middle.json",
                limit=_OCR_JSON_FILE_LIMIT,
            )
        )
        model = json.loads(
            _read_safe_bytes(
                leaf / "source_model.json",
                limit=_OCR_JSON_FILE_LIMIT,
            )
        )
        page_count = _validate_middle_document(middle)
        _validate_content_documents(
            content_list,
            content_list_v2,
            page_count=page_count,
        )
        _validate_model_document(model, page_count=page_count)
        _validate_pdf_output(leaf / "source_layout.pdf", page_count=page_count)
        _validate_pdf_output(leaf / "source_span.pdf", page_count=page_count)
        source_pages = _validate_pdf_output(
            authority.original_pdf_path,
            page_count=page_count,
            expected_sha256=authority.source_sha256,
            expected_byte_length=authority.source_byte_length,
        )
        origin_pages = _validate_pdf_output(
            leaf / "source_origin.pdf",
            page_count=page_count,
        )
        if origin_pages != source_pages:
            raise _OcrOutputInvalidV1("MinerU origin PDF does not bind to source")
        _validate_provider_images(leaf, paths)
    except (
        DataRootOpenErrorV1,
        DataRootLifecycleErrorV1,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        _RunInvalidV1,
        _OcrOutputInvalidV1,
    ) as error:
        raise _OcrOutputInvalidV1("MinerU output is invalid") from error


def _known_schema(path: str) -> str | None:
    if path == "input.json":
        return "gezhi.literature_ocr_input.v1"
    if path == "selection.json":
        return "gezhi.literature_ocr_selection.v1"
    if path == "receipt.json":
        return "gezhi.literature_ocr_run_receipt.v1"
    if path == "output/native_text.json":
        return "gezhi.literature_native_text.v1"
    if path == "output/output.json":
        return "gezhi.literature_ocr_output.v1"
    if re.fullmatch(r"attempts/[12]/receipt\.json", path) is not None:
        return "gezhi.literature_ocr_attempt.v1"
    return None


def _media_type(path: str) -> str:
    suffix = Path(path).suffix.casefold()
    return {
        ".json": "application/json",
        ".md": "text/markdown; charset=utf-8",
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(suffix, "application/octet-stream")


def _is_provider_asset(path: str) -> bool:
    return path.startswith("output/mineru/") or re.match(
        r"^attempts/[12]/provider_output/",
        path,
    ) is not None


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
                    key=lambda item: item.encode("utf-8"),
                )
            )
            assets: list[dict[str, object]] = []
            provider_count = 0
            provider_total = 0
            for path in paths:
                parts = validate_relative_parts_v1(tuple(path.split("/")))
                with run.open_relative_file_v1(parts) as asset:
                    if _is_provider_asset(path):
                        provider_count += 1
                        provider_total += asset.size
                        if (
                            asset.size > _OCR_ARTIFACT_FILE_LIMIT
                            or provider_count > _OCR_ARTIFACT_FILE_COUNT_LIMIT
                            or provider_total > _OCR_ARTIFACT_AGGREGATE_LIMIT
                        ):
                            raise _RunInvalidV1(
                                "OCR provider artifact budget is invalid"
                            )
                    entry: dict[str, object] = {
                        "byte_length": asset.size,
                        "media_type": _media_type(path),
                        "path": path,
                        "sha256": asset.sha256_v1(),
                    }
                schema = _known_schema(path)
                if schema is not None:
                    entry["schema_version"] = schema
                assets.append(entry)
            return assets
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        raise _RunInvalidV1("OCR run inventory is invalid") from error


def _attempt_document(
    attempt: int,
    *,
    outcome: str,
    returncode: int | None,
) -> dict[str, object]:
    return {
        "attempt": attempt,
        "outcome": outcome,
        "returncode": returncode,
        "schema_version": "gezhi.literature_ocr_attempt.v1",
    }


def _write_attempt_assets(
    attempt_dir: Path,
    *,
    stdout: bytes,
    stderr: bytes,
    document: dict[str, object],
) -> None:
    _write_new_verified(attempt_dir / "stdout.bin", stdout)
    _write_new_verified(attempt_dir / "stderr.bin", stderr)
    _write_new_verified(
        attempt_dir / "receipt.json",
        _canonical_json_bytes(document),
    )


def _bounded_exception_capture(error: object) -> tuple[bytes, bytes]:
    stdout = getattr(error, "stdout", b"")
    stderr = getattr(error, "stderr", b"")
    return (
        stdout if type(stdout) is bytes else b"",
        stderr if type(stderr) is bytes else b"",
    )


def _write_terminal_receipt(
    stage: Path,
    *,
    run_id: str,
    input_document: dict[str, object],
    selection: _SelectionV1,
    attempt_count: int,
    status: Literal["succeeded", "blocked", "failed"],
    reason: str | None,
    authority: ActiveSourceAuthorityV1,
) -> dict[str, object]:
    receipt = {
        "attempt_count": attempt_count,
        "input_fingerprint_sha256": input_document[
            "input_fingerprint_sha256"
        ],
        "method": selection.method,
        "reason": reason,
        "run_id": run_id,
        "schema_version": "gezhi.literature_ocr_run_receipt.v1",
        "source_id": authority.source_id,
        "status": status,
        "work_id": authority.work_id,
    }
    _write_new_verified(stage / "receipt.json", _canonical_json_bytes(receipt))
    return receipt


def _write_manifest(
    stage: Path,
    *,
    receipt: dict[str, object],
) -> bytes:
    manifest = {
        "assets": _asset_entries(stage),
        "input_fingerprint_sha256": receipt["input_fingerprint_sha256"],
        "run_id": receipt["run_id"],
        "schema_version": "gezhi.literature_ocr_run_manifest.v1",
        "source_id": receipt["source_id"],
        "status": receipt["status"],
        "work_id": receipt["work_id"],
    }
    payload = _canonical_json_bytes(manifest)
    _write_new_verified(stage / "manifest.json", payload)
    return payload


def _validate_selection(value: dict[str, object]) -> OcrMethod:
    if set(value) != {
        "method",
        "minimum_non_whitespace_per_page",
        "non_whitespace_counts",
        "page_count",
        "reason",
        "schema_version",
        "selector_profile",
    }:
        raise _RunInvalidV1("OCR selection shape is invalid")
    method = value["method"]
    counts = value["non_whitespace_counts"]
    page_count = value["page_count"]
    if (
        type(method) is not str
        or method not in {"native_text", "mineru_ocr"}
        or value["minimum_non_whitespace_per_page"] != _MINIMUM_NON_WHITESPACE
        or type(counts) is not list
        or any(type(count) is not int or count < 0 for count in counts)
        or (page_count is not None and (type(page_count) is not int or page_count < 0))
        or type(value["reason"]) is not str
        or value["schema_version"] != "gezhi.literature_ocr_selection.v1"
        or value["selector_profile"] != _SELECTOR_PROFILE
    ):
        raise _RunInvalidV1("OCR selection is invalid")
    frozen_counts = cast(list[int], counts)
    reason = cast(str, value["reason"])
    if method == "native_text":
        if (
            type(page_count) is not int
            or page_count <= 0
            or len(frozen_counts) != page_count
            or any(count < _MINIMUM_NON_WHITESPACE for count in frozen_counts)
            or reason != "all_pages_meet_minimum"
        ):
            raise _RunInvalidV1("native text selection is invalid")
    elif reason == "no_pages":
        if page_count != 0 or frozen_counts:
            raise _RunInvalidV1("zero-page OCR selection is invalid")
    elif reason == "page_below_minimum":
        if (
            type(page_count) is not int
            or page_count <= 0
            or len(frozen_counts) != page_count
            or not any(
                count < _MINIMUM_NON_WHITESPACE for count in frozen_counts
            )
        ):
            raise _RunInvalidV1("low-text OCR selection is invalid")
    elif reason == "native_text_proof_unavailable":
        if page_count is not None or frozen_counts:
            raise _RunInvalidV1("unavailable native proof selection is invalid")
    else:
        raise _RunInvalidV1("OCR selection reason is invalid")
    return cast(OcrMethod, method)


def _validate_input(
    value: dict[str, object],
    selection_bytes: bytes,
    authority: ActiveSourceAuthorityV1,
) -> tuple[str, str]:
    if set(value) != {
        "input_fingerprint_sha256",
        "provider_profile_identity_sha256",
        "schema_version",
        "selection_sha256",
        "source_id",
        "source_manifest_sha256",
        "source_sha256",
        "work_id",
    }:
        raise _RunInvalidV1("OCR input shape is invalid")
    fingerprint = value["input_fingerprint_sha256"]
    profile = value["provider_profile_identity_sha256"]
    if (
        type(fingerprint) is not str
        or _SHA256.fullmatch(fingerprint) is None
        or type(profile) is not str
        or _SHA256.fullmatch(profile) is None
        or value["schema_version"] != "gezhi.literature_ocr_input.v1"
        or value["selection_sha256"]
        != hashlib.sha256(selection_bytes).hexdigest()
        or value["source_id"] != authority.source_id
        or value["source_manifest_sha256"]
        != authority.source_manifest_sha256
        or value["source_sha256"] != authority.source_sha256
        or value["work_id"] != authority.work_id
    ):
        raise _RunInvalidV1("OCR input is invalid")
    identity = {key: item for key, item in value.items() if key != "input_fingerprint_sha256"}
    if hashlib.sha256(_canonical_json_bytes(identity)).hexdigest() != fingerprint:
        raise _RunInvalidV1("OCR input fingerprint is invalid")
    return cast(str, fingerprint), cast(str, profile)


def _validate_attempts(
    run_dir: Path,
    *,
    method: OcrMethod,
    status: Literal["succeeded", "blocked", "failed"],
    reason: str | None,
    attempt_count: int,
) -> None:
    run_entries = _safe_entry_names(run_dir)
    if attempt_count == 0:
        if "attempts" in run_entries:
            raise _RunInvalidV1("zero-attempt OCR run has attempt assets")
        return
    if method != "mineru_ocr" or "attempts" not in run_entries:
        raise _RunInvalidV1("OCR attempt assets are missing")
    attempts_dir = run_dir / "attempts"
    expected_names = frozenset(str(index) for index in range(1, attempt_count + 1))
    if _safe_entry_names(attempts_dir) != expected_names:
        raise _RunInvalidV1("OCR attempt namespace is invalid")

    outcomes: list[str] = []
    for attempt in range(1, attempt_count + 1):
        attempt_dir = attempts_dir / str(attempt)
        names = _safe_entry_names(attempt_dir)
        if not {"receipt.json", "stderr.bin", "stdout.bin"}.issubset(names):
            raise _RunInvalidV1("OCR attempt evidence is incomplete")
        if names - {"provider_output", "receipt.json", "stderr.bin", "stdout.bin"}:
            raise _RunInvalidV1("OCR attempt inventory is invalid")
        if "provider_output" in names:
            try:
                with open_validated_data_root_v1(
                    str(attempt_dir / "provider_output")
                ):
                    pass
            except DataRootOpenErrorV1 as error:
                raise _RunInvalidV1("OCR partial output is unsafe") from error
        document, _document_bytes = _read_canonical_document(
            attempt_dir / "receipt.json"
        )
        outcome = document.get("outcome")
        returncode = document.get("returncode")
        if (
            set(document) != {"attempt", "outcome", "returncode", "schema_version"}
            or document.get("attempt") != attempt
            or type(outcome) is not str
            or outcome
            not in {
                "output_invalid",
                "output_limit_exceeded",
                "process_failed",
                "runtime_unavailable",
                "succeeded",
                "timed_out",
            }
            or document.get("schema_version")
            != "gezhi.literature_ocr_attempt.v1"
            or (
                outcome in {"process_failed", "succeeded", "output_invalid"}
                and type(returncode) is not int
            )
            or (
                outcome
                in {
                    "output_limit_exceeded",
                    "runtime_unavailable",
                    "timed_out",
                }
                and returncode is not None
            )
            or (outcome == "succeeded" and returncode != 0)
            or (outcome == "output_invalid" and returncode != 0)
            or (outcome == "process_failed" and returncode == 0)
        ):
            raise _RunInvalidV1("OCR attempt receipt is invalid")
        outcomes.append(cast(str, outcome))

    transient = {"process_failed", "timed_out"}
    if status == "succeeded":
        if outcomes[-1] != "succeeded" or any(
            outcome not in transient for outcome in outcomes[:-1]
        ):
            raise _RunInvalidV1("successful OCR attempt sequence is invalid")
    elif reason == "ocr_transient_exhausted":
        if attempt_count != 2 or any(outcome not in transient for outcome in outcomes):
            raise _RunInvalidV1("exhausted OCR attempt sequence is invalid")
    elif reason == "ocr_runtime_unavailable":
        if outcomes[-1] != "runtime_unavailable" or any(
            outcome not in transient for outcome in outcomes[:-1]
        ):
            raise _RunInvalidV1("unavailable OCR attempt sequence is invalid")
    elif reason == "ocr_failed":
        if outcomes[-1] not in {"output_invalid", "output_limit_exceeded"} or any(
            outcome not in transient for outcome in outcomes[:-1]
        ):
            raise _RunInvalidV1("failed OCR attempt sequence is invalid")
    else:
        raise _RunInvalidV1("OCR terminal attempt sequence is invalid")


def _load_run(
    run_dir: Path,
    run_id: str,
    authority: ActiveSourceAuthorityV1,
) -> _ValidatedRunV1:
    if _RUN_ID.fullmatch(run_id) is None:
        raise _RunInvalidV1("OCR run ID is invalid")
    selection, selection_bytes = _read_canonical_document(
        run_dir / "selection.json"
    )
    method = _validate_selection(selection)
    input_value, _input_bytes = _read_canonical_document(run_dir / "input.json")
    fingerprint, profile = _validate_input(
        input_value,
        selection_bytes,
        authority,
    )
    receipt, _receipt_bytes = _read_canonical_document(run_dir / "receipt.json")
    if set(receipt) != {
        "attempt_count",
        "input_fingerprint_sha256",
        "method",
        "reason",
        "run_id",
        "schema_version",
        "source_id",
        "status",
        "work_id",
    }:
        raise _RunInvalidV1("OCR receipt shape is invalid")
    status = receipt["status"]
    reason = receipt["reason"]
    attempt_count = receipt["attempt_count"]
    if (
        type(status) is not str
        or status not in {"succeeded", "blocked", "failed"}
        or type(attempt_count) is not int
        or not 0 <= attempt_count <= 2
        or receipt["input_fingerprint_sha256"] != fingerprint
        or receipt["method"] != method
        or receipt["run_id"] != run_id
        or receipt["schema_version"]
        != "gezhi.literature_ocr_run_receipt.v1"
        or receipt["source_id"] != authority.source_id
        or receipt["work_id"] != authority.work_id
        or (reason is not None and type(reason) is not str)
        or (status == "succeeded" and reason is not None)
    ):
        raise _RunInvalidV1("OCR receipt is invalid")
    if method == "native_text":
        if status != "succeeded" or attempt_count != 0:
            raise _RunInvalidV1("native text receipt is invalid")
    elif status == "succeeded":
        if attempt_count not in {1, 2}:
            raise _RunInvalidV1("successful MinerU attempt count is invalid")
    elif status == "blocked":
        if reason == "ocr_runtime_unavailable" and attempt_count not in {0, 1, 2}:
            raise _RunInvalidV1("unavailable MinerU receipt is invalid")
        if reason == "ocr_transient_exhausted" and attempt_count != 2:
            raise _RunInvalidV1("exhausted MinerU receipt is invalid")
        if reason not in {"ocr_runtime_unavailable", "ocr_transient_exhausted"}:
            raise _RunInvalidV1("blocked MinerU reason is invalid")
    elif reason != "ocr_failed" or attempt_count not in {1, 2}:
        raise _RunInvalidV1("failed MinerU receipt is invalid")
    _validate_attempts(
        run_dir,
        method=method,
        status=cast(Literal["succeeded", "blocked", "failed"], status),
        reason=cast(str | None, reason),
        attempt_count=attempt_count,
    )
    manifest, manifest_bytes = _read_canonical_document(run_dir / "manifest.json")
    expected_manifest = {
        "assets": _asset_entries(run_dir),
        "input_fingerprint_sha256": fingerprint,
        "run_id": run_id,
        "schema_version": "gezhi.literature_ocr_run_manifest.v1",
        "source_id": authority.source_id,
        "status": status,
        "work_id": authority.work_id,
    }
    if manifest != expected_manifest:
        raise _RunInvalidV1("OCR manifest is invalid")
    if status == "succeeded":
        if method == "native_text":
            native, _native_bytes = _read_canonical_document(
                run_dir / "output" / "native_text.json"
            )
            pages = native.get("pages")
            counts = cast(list[int], selection["non_whitespace_counts"])
            page_count = cast(int, selection["page_count"])
            if (
                set(native) != {"pages", "schema_version", "source_id", "work_id"}
                or native["schema_version"] != "gezhi.literature_native_text.v1"
                or native["source_id"] != authority.source_id
                or native["work_id"] != authority.work_id
                or type(pages) is not list
                or len(pages) != page_count
            ):
                raise _RunInvalidV1("native text output is invalid")
            for index, page in enumerate(pages):
                if (
                    type(page) is not dict
                    or set(page) != {"page_index", "text"}
                    or page.get("page_index") != index
                    or type(page.get("text")) is not str
                    or sum(
                        not character.isspace()
                        for character in cast(str, page["text"])
                    )
                    != counts[index]
                ):
                    raise _RunInvalidV1("native text page output is invalid")
        else:
            output, _output_bytes = _read_canonical_document(
                run_dir / "output" / "output.json"
            )
            if output != {
                "artifact_root": "output/mineru/source/ocr",
                "content_list_path": (
                    "output/mineru/source/ocr/source_content_list.json"
                ),
                "content_list_v2_path": (
                    "output/mineru/source/ocr/source_content_list_v2.json"
                ),
                "markdown_path": "output/mineru/source/ocr/source.md",
                "middle_path": "output/mineru/source/ocr/source_middle.json",
                "schema_version": "gezhi.literature_ocr_output.v1",
            }:
                raise _RunInvalidV1("MinerU output descriptor is invalid")
            try:
                _validate_provider_output(
                    run_dir / "output" / "mineru",
                    authority,
                )
            except _OcrOutputInvalidV1 as error:
                raise _RunInvalidV1("MinerU success output is invalid") from error
    return _ValidatedRunV1(
        path=run_dir,
        run_id=run_id,
        method=method,
        status=cast(Literal["succeeded", "blocked", "failed"], status),
        reason=cast(str | None, reason),
        input_fingerprint_sha256=fingerprint,
        provider_profile_identity_sha256=profile,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        work_id=authority.work_id,
        source_id=authority.source_id,
    )


def _run_matches_current_profile(run: _ValidatedRunV1) -> bool:
    return (
        run.status == "succeeded"
        and run.provider_profile_identity_sha256
        == _profile_identity_for_method(run.method)
    )


def _current_document(
    authority: ActiveSourceAuthorityV1,
    run: _ValidatedRunV1,
) -> dict[str, object]:
    return {
        "input_fingerprint_sha256": run.input_fingerprint_sha256,
        "manifest_sha256": run.manifest_sha256,
        "run_id": run.run_id,
        "schema_version": "gezhi.literature_ocr_current.v1",
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "work_id": authority.work_id,
    }


def _atomic_replace_current(
    ocr_dir: Path,
    authority: ActiveSourceAuthorityV1,
    run: _ValidatedRunV1,
) -> None:
    payload = _canonical_json_bytes(_current_document(authority, run))
    temporary = ocr_dir / f".current.json.{uuid.uuid4().hex}.tmp"
    try:
        _write_new_verified(temporary, payload)
        os.replace(temporary, ocr_dir / "current.json")
        if _read_safe_bytes(ocr_dir / "current.json", limit=len(payload)) != payload:
            raise OSError("OCR current readback differs")
    except (_CommitFailedV1, _RunInvalidV1, OSError) as error:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass
        raise _CommitFailedV1("OCR current commit failed") from error


def _load_current_run(
    ocr_dir: Path,
    runs_dir: Path,
    authority: ActiveSourceAuthorityV1,
) -> _ValidatedRunV1 | None:
    if "current.json" not in _safe_entry_names(ocr_dir):
        return None
    current, _current_bytes = _read_canonical_document(ocr_dir / "current.json")
    if (
        set(current)
        != {
            "input_fingerprint_sha256",
            "manifest_sha256",
            "run_id",
            "schema_version",
            "source_id",
            "source_sha256",
            "work_id",
        }
        or current.get("schema_version") != "gezhi.literature_ocr_current.v1"
        or current.get("source_id") != authority.source_id
        or current.get("source_sha256") != authority.source_sha256
        or current.get("work_id") != authority.work_id
        or type(current.get("run_id")) is not str
        or _RUN_ID.fullmatch(cast(str, current["run_id"])) is None
    ):
        raise _RunInvalidV1("OCR current is invalid")
    run_id = cast(str, current["run_id"])
    run = _load_run(runs_dir / run_id, run_id, authority)
    if (
        current.get("input_fingerprint_sha256")
        != run.input_fingerprint_sha256
        or current.get("manifest_sha256") != run.manifest_sha256
        or run.status != "succeeded"
    ):
        raise _RunInvalidV1("OCR current binding is invalid")
    return run


def _matching_staged_success_runs(
    staging_dir: Path,
    authority: ActiveSourceAuthorityV1,
) -> tuple[_ValidatedRunV1, ...]:
    runs: list[_ValidatedRunV1] = []
    for name in sorted(
        _safe_entry_names(staging_dir),
        key=lambda item: item.encode("utf-8"),
    ):
        if _RUN_ID.fullmatch(name) is None:
            continue
        try:
            run = _load_run(staging_dir / name, name, authority)
        except _RunInvalidV1:
            continue
        if run.status == "succeeded" and _run_matches_current_profile(run):
            runs.append(run)
    return tuple(runs)


def _matching_success_runs(
    runs_dir: Path,
    authority: ActiveSourceAuthorityV1,
) -> tuple[_ValidatedRunV1, ...]:
    runs: list[_ValidatedRunV1] = []
    try:
        entries = tuple(runs_dir.iterdir())
    except OSError as error:
        raise _RunInvalidV1("OCR runs cannot be inspected") from error
    for entry in entries:
        if entry.name == ".staging":
            continue
        if _RUN_ID.fullmatch(entry.name) is None:
            raise _RunInvalidV1("OCR run namespace is invalid")
        run = _load_run(entry, entry.name, authority)
        if _run_matches_current_profile(run):
            runs.append(run)
    return tuple(runs)


def _inventory_matching_successes(
    staging_dir: Path,
    runs_dir: Path,
    authority: ActiveSourceAuthorityV1,
) -> tuple[_ValidatedRunV1, ...]:
    staged = _matching_staged_success_runs(staging_dir, authority)
    formal_names = _safe_entry_names(runs_dir) - {".staging"}
    if any(run.run_id in formal_names for run in staged):
        raise _RecoveryCertaintyLostV1("OCR recovery target conflicts")
    formal = _matching_success_runs(runs_dir, authority)
    matches = formal + staged
    if len(matches) > 1:
        raise _RecoveryCertaintyLostV1("OCR recovery success is ambiguous")
    return matches


def _recover_unique_staged_success(
    run: _ValidatedRunV1,
    staging_dir: Path,
    runs_dir: Path,
    authority: ActiveSourceAuthorityV1,
    root: ValidatedDataRootV1,
) -> _ValidatedRunV1:
    if run.path.parent != staging_dir:
        return run
    _fresh_authority_or_stop(authority, root)
    if (
        run.run_id not in _safe_entry_names(staging_dir)
        or run.run_id in (_safe_entry_names(runs_dir) - {".staging"})
    ):
        raise _RecoveryCertaintyLostV1("OCR recovery namespace changed")
    target = runs_dir / run.run_id
    try:
        os.rename(run.path, target)
    except OSError as error:
        raise _RecoveryCertaintyLostV1(
            "OCR staged success rename is uncertain"
        ) from error
    try:
        return _load_run(target, run.run_id, authority)
    except _RunInvalidV1 as error:
        raise _RecoveryCertaintyLostV1(
            "OCR recovered success cannot be proven"
        ) from error


def _create_unique_stage(
    stage: Path,
    staging_dir: Path,
    runs_dir: Path,
) -> None:
    if (
        stage.name in _safe_entry_names(staging_dir)
        or stage.name in (_safe_entry_names(runs_dir) - {".staging"})
    ):
        raise _RecoveryCertaintyLostV1("OCR run ID collides with its namespace")
    try:
        with open_validated_data_root_v1(str(staging_dir)):
            stage.mkdir()
    except FileExistsError as error:
        raise _RecoveryCertaintyLostV1("OCR run ID collides with staging") from error
    except (DataRootOpenErrorV1, OSError) as error:
        raise _CommitFailedV1("OCR staging creation failed") from error
    try:
        with open_validated_data_root_v1(str(stage)):
            pass
    except DataRootOpenErrorV1 as error:
        raise _RecoveryCertaintyLostV1("OCR new staging cannot be proven") from error


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


def _load_authority_or_stop(
    work_id: str,
    root: ValidatedDataRootV1,
) -> ActiveSourceAuthorityV1:
    try:
        return load_active_source_authority_v1(work_id, root=root)
    except ActiveSourceAuthorityStoppedV1 as error:
        reason = error.reason
        if reason == "data_root_integrity_lost":
            raise ResumeStoppedV1(
                "failed",
                reason,
                data_root="literature",
            ) from error
        if reason in {"active_source_invalid", "recovery_failed"}:
            raise ResumeStoppedV1("failed", reason) from error
        if reason == "identity_review_required":
            raise RuntimeError("identity readiness is returned as authority state")
        raise ResumeStoppedV1("blocked", reason) from error


def _fresh_authority_or_stop(
    authority: ActiveSourceAuthorityV1,
    root: ValidatedDataRootV1,
) -> ActiveSourceAuthorityV1:
    fresh = _load_authority_or_stop(authority.work_id, root)
    if not _same_authority(authority, fresh):
        raise ResumeStoppedV1("failed", "recovery_failed")
    return fresh


def _stop_stage(
    authority: ActiveSourceAuthorityV1,
    root: ValidatedDataRootV1,
    *,
    start_stage: ResumeStage,
    advanced_stages: tuple[ResumeStage, ...],
    outcome: ResumeOutcome,
    stage: ResumeStage,
    reason: str,
) -> NoReturn:
    _fresh_authority_or_stop(authority, root)
    result = ResumeWorkResultV1(
        active_source_id=authority.source_id,
        advanced_stages=advanced_stages,
        pending_candidate_ids=(),
        pipeline_complete=False,
        start_stage=start_stage,
        stop_stage=stage,
        work_id=authority.work_id,
    )
    raise ResumeStoppedV1(
        outcome,
        reason,
        stage=stage,
        result=result,
    )


def _ensure_ocr_layout(
    authority: ActiveSourceAuthorityV1,
) -> tuple[Path, Path, Path]:
    ocr_dir = authority.source_directory / "ocr"
    runs_dir = ocr_dir / "runs"
    staging_dir = runs_dir / ".staging"
    _ensure_plain_directory(ocr_dir)
    _ensure_plain_directory(runs_dir)
    _ensure_plain_directory(staging_dir)
    return ocr_dir, runs_dir, staging_dir


def _commit_run(
    stage: Path,
    runs_dir: Path,
    authority: ActiveSourceAuthorityV1,
    root: ValidatedDataRootV1,
) -> _ValidatedRunV1:
    run_id = stage.name
    _load_run(stage, run_id, authority)
    _fresh_authority_or_stop(authority, root)
    target = runs_dir / run_id
    if run_id in (_safe_entry_names(runs_dir) - {".staging"}):
        raise _RecoveryCertaintyLostV1("OCR run target conflicts")
    try:
        os.rename(stage, target)
    except OSError as error:
        raise _RecoveryCertaintyLostV1("OCR run commit is uncertain") from error
    try:
        return _load_run(target, run_id, authority)
    except _RunInvalidV1 as error:
        raise _RecoveryCertaintyLostV1(
            "OCR committed run cannot be proven"
        ) from error


def _publish_native_success(
    stage: Path,
    run_id: str,
    authority: ActiveSourceAuthorityV1,
    selection: _SelectionV1,
    input_document: dict[str, object],
) -> None:
    output_dir = stage / "output"
    _ensure_plain_directory(output_dir)
    pages = [
        {"page_index": index, "text": text}
        for index, text in enumerate(selection.page_texts)
    ]
    native = {
        "pages": pages,
        "schema_version": "gezhi.literature_native_text.v1",
        "source_id": authority.source_id,
        "work_id": authority.work_id,
    }
    _write_new_verified(
        output_dir / "native_text.json",
        _canonical_json_bytes(native),
    )
    receipt = _write_terminal_receipt(
        stage,
        run_id=run_id,
        input_document=input_document,
        selection=selection,
        attempt_count=0,
        status="succeeded",
        reason=None,
        authority=authority,
    )
    _write_manifest(stage, receipt=receipt)


def _publish_mineru_output_descriptor(stage: Path) -> None:
    output = {
        "artifact_root": "output/mineru/source/ocr",
        "content_list_path": "output/mineru/source/ocr/source_content_list.json",
        "content_list_v2_path": (
            "output/mineru/source/ocr/source_content_list_v2.json"
        ),
        "markdown_path": "output/mineru/source/ocr/source.md",
        "middle_path": "output/mineru/source/ocr/source_middle.json",
        "schema_version": "gezhi.literature_ocr_output.v1",
    }
    _write_new_verified(
        stage / "output" / "output.json",
        _canonical_json_bytes(output),
    )


def _publish_terminal_stop(
    stage: Path,
    run_id: str,
    authority: ActiveSourceAuthorityV1,
    selection: _SelectionV1,
    input_document: dict[str, object],
    *,
    attempt_count: int,
    outcome: ResumeOutcome,
    reason: str,
) -> None:
    receipt = _write_terminal_receipt(
        stage,
        run_id=run_id,
        input_document=input_document,
        selection=selection,
        attempt_count=attempt_count,
        status="blocked" if outcome == "blocked" else "failed",
        reason=reason,
        authority=authority,
    )
    _write_manifest(stage, receipt=receipt)


def _execute_mineru_run(
    stage: Path,
    run_id: str,
    authority: ActiveSourceAuthorityV1,
    selection: _SelectionV1,
    input_document: dict[str, object],
    input_path: Path,
) -> tuple[ResumeOutcome | None, str | None, int]:
    try:
        profile = _resolve_ocr_runtime_v1()
    except OcrRuntimeUnavailableV1:
        return "blocked", "ocr_runtime_unavailable", 0
    if (
        type(profile.executable_path) is not str
        or type(profile.environment) is not tuple
        or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not str
            for item in profile.environment
        )
        or profile.profile_identity_sha256 != _MINERU_PROFILE_IDENTITY
    ):
        return "blocked", "ocr_runtime_unavailable", 0

    attempts_dir = stage / "attempts"
    _ensure_plain_directory(attempts_dir)
    for attempt in (1, 2):
        attempt_dir = attempts_dir / str(attempt)
        _ensure_plain_directory(attempt_dir)
        provider_output = attempt_dir / "provider_output"
        _enforce_ocr_artifact_budget_v1(stage)
        try:
            completed = _run_stable_ocr_attempt_v1(
                profile,
                input_path,
                provider_output,
                authority,
            )
        except ProbeUnavailableError:
            _enforce_ocr_artifact_budget_v1(stage)
            _write_attempt_assets(
                attempt_dir,
                stdout=b"",
                stderr=b"",
                document=_attempt_document(
                    attempt,
                    outcome="runtime_unavailable",
                    returncode=None,
                ),
            )
            return "blocked", "ocr_runtime_unavailable", attempt
        except subprocess.TimeoutExpired as error:
            _enforce_ocr_artifact_budget_v1(stage)
            stdout, stderr = _bounded_exception_capture(error)
            _write_attempt_assets(
                attempt_dir,
                stdout=stdout,
                stderr=stderr,
                document=_attempt_document(
                    attempt,
                    outcome="timed_out",
                    returncode=None,
                ),
            )
            if attempt == 1:
                time.sleep(_OCR_RETRY_BACKOFF_SECONDS)
                continue
            return "blocked", "ocr_transient_exhausted", attempt
        except ProbeOutputLimitExceeded as error:
            _enforce_ocr_artifact_budget_v1(stage)
            stdout, stderr = _bounded_exception_capture(error)
            _write_attempt_assets(
                attempt_dir,
                stdout=stdout,
                stderr=stderr,
                document=_attempt_document(
                    attempt,
                    outcome="output_limit_exceeded",
                    returncode=None,
                ),
            )
            return "failed", "ocr_failed", attempt

        _enforce_ocr_artifact_budget_v1(stage)
        if (
            type(completed) is not OcrAttemptResultV1
            or type(completed.returncode) is not int
            or type(completed.stdout) is not bytes
            or type(completed.stderr) is not bytes
        ):
            raise TypeError("OCR attempt returned an invalid result")
        if completed.returncode != 0:
            _write_attempt_assets(
                attempt_dir,
                stdout=completed.stdout,
                stderr=completed.stderr,
                document=_attempt_document(
                    attempt,
                    outcome="process_failed",
                    returncode=completed.returncode,
                ),
            )
            if attempt == 1:
                time.sleep(_OCR_RETRY_BACKOFF_SECONDS)
                continue
            return "blocked", "ocr_transient_exhausted", attempt

        try:
            _validate_provider_output(provider_output, authority)
        except _OcrOutputInvalidV1:
            _write_attempt_assets(
                attempt_dir,
                stdout=completed.stdout,
                stderr=completed.stderr,
                document=_attempt_document(
                    attempt,
                    outcome="output_invalid",
                    returncode=completed.returncode,
                ),
            )
            return "failed", "ocr_failed", attempt
        _write_attempt_assets(
            attempt_dir,
            stdout=completed.stdout,
            stderr=completed.stderr,
            document=_attempt_document(
                attempt,
                outcome="succeeded",
                returncode=completed.returncode,
            ),
        )
        output_dir = stage / "output"
        _ensure_plain_directory(output_dir)
        try:
            os.rename(provider_output, output_dir / "mineru")
        except OSError as error:
            raise _CommitFailedV1("MinerU output publish failed") from error
        _publish_mineru_output_descriptor(stage)
        return None, None, attempt
    raise RuntimeError("OCR attempt loop did not terminate")


def _advance_ocr(
    authority: ActiveSourceAuthorityV1,
    root: ValidatedDataRootV1,
) -> tuple[bool, ResumeStage]:
    try:
        ocr_dir, runs_dir, staging_dir = _ensure_ocr_layout(authority)
    except _CommitFailedV1:
        _stop_stage(
            authority,
            root,
            start_stage="ocr",
            advanced_stages=(),
            outcome="failed",
            stage="ocr",
            reason="commit_failed",
        )

    try:
        current = _load_current_run(ocr_dir, runs_dir, authority)
    except _RunInvalidV1:
        _stop_stage(
            authority,
            root,
            start_stage="ocr",
            advanced_stages=(),
            outcome="failed",
            stage="ocr",
            reason="asset_integrity_lost",
        )
    try:
        matches = _inventory_matching_successes(
            staging_dir,
            runs_dir,
            authority,
        )
    except _RunInvalidV1 as error:
        raise ResumeStoppedV1("failed", "recovery_failed") from error
    if current is not None and _run_matches_current_profile(current):
        if len(matches) != 1 or matches[0].run_id != current.run_id:
            raise _RecoveryCertaintyLostV1(
                "OCR current success cannot be uniquely proven"
            )
        return False, "canonicalize"
    if len(matches) == 1:
        try:
            recovered = _recover_unique_staged_success(
                matches[0],
                staging_dir,
                runs_dir,
                authority,
                root,
            )
            _fresh_authority_or_stop(authority, root)
            _atomic_replace_current(ocr_dir, authority, recovered)
        except _CommitFailedV1:
            _stop_stage(
                authority,
                root,
                start_stage="ocr",
                advanced_stages=(),
                outcome="failed",
                stage="ocr",
                reason="commit_failed",
            )
        return True, "ocr"

    run_id = "ocrrun_" + str(uuid.uuid4())
    stage = staging_dir / run_id
    input_dir = stage / "input"
    try:
        _fresh_authority_or_stop(authority, root)
        _create_unique_stage(stage, staging_dir, runs_dir)
        _ensure_plain_directory(input_dir)
        input_path = input_dir / "source.pdf"
        _copy_source_to_private_input(authority, input_path)
        selection = _select_source_text_v1(input_path)
        selection_bytes = _canonical_json_bytes(selection.document_v1())
        input_document = _input_document(
            authority,
            selection_bytes,
            provider_profile_identity_sha256=_profile_identity_for_method(
                selection.method
            ),
        )
        _write_new_verified(stage / "selection.json", selection_bytes)
        _write_new_verified(
            stage / "input.json",
            _canonical_json_bytes(input_document),
        )

        if selection.method == "native_text":
            _remove_private_input(input_path)
            _publish_native_success(
                stage,
                run_id,
                authority,
                selection,
                input_document,
            )
            committed = _commit_run(stage, runs_dir, authority, root)
            _atomic_replace_current(ocr_dir, authority, committed)
            return True, "ocr"

        outcome, reason, attempt_count = _execute_mineru_run(
            stage,
            run_id,
            authority,
            selection,
            input_document,
            input_path,
        )
        _remove_private_input(input_path)
        if outcome is not None:
            if reason is None:
                raise RuntimeError("OCR stop reason is unavailable")
            _publish_terminal_stop(
                stage,
                run_id,
                authority,
                selection,
                input_document,
                attempt_count=attempt_count,
                outcome=outcome,
                reason=reason,
            )
            _commit_run(stage, runs_dir, authority, root)
            _stop_stage(
                authority,
                root,
                start_stage="ocr",
                advanced_stages=(),
                outcome=outcome,
                stage="ocr",
                reason=reason,
            )

        receipt = _write_terminal_receipt(
            stage,
            run_id=run_id,
            input_document=input_document,
            selection=selection,
            attempt_count=attempt_count,
            status="succeeded",
            reason=None,
            authority=authority,
        )
        _write_manifest(stage, receipt=receipt)
        committed = _commit_run(stage, runs_dir, authority, root)
        _atomic_replace_current(ocr_dir, authority, committed)
        return True, "ocr"
    except ResumeStoppedV1:
        raise
    except _RunInvalidV1 as error:
        raise ResumeStoppedV1("failed", "recovery_failed") from error
    except _OcrOutputInvalidV1:
        _stop_stage(
            authority,
            root,
            start_stage="ocr",
            advanced_stages=(),
            outcome="failed",
            stage="ocr",
            reason="ocr_failed",
        )
    except _CommitFailedV1:
        _stop_stage(
            authority,
            root,
            start_stage="ocr",
            advanced_stages=(),
            outcome="failed",
            stage="ocr",
            reason="commit_failed",
        )


def resume_work(
    work_id: str,
    *,
    root: ValidatedDataRootV1,
) -> ResumeWorkResultV1:
    if type(work_id) is not str or _WORK_ID.fullmatch(work_id) is None:
        raise ResumeStoppedV1("blocked", "work_invalid")
    root_identity = root.inspection.identity
    if root_identity is None:
        raise RuntimeError("validated Literature root is incomplete")
    owner = try_acquire_work_writer_v1(root_identity, work_id)
    if owner is None:
        raise ResumeStoppedV1("blocked", "work_busy")
    try:
        authority = _load_authority_or_stop(work_id, root)
        if not authority.ingest_identity_ready:
            _stop_stage(
                authority,
                root,
                start_stage="ingest",
                advanced_stages=(),
                outcome="blocked",
                stage="ingest",
                reason="identity_review_required",
            )
        advanced, start = _advance_ocr(authority, root)
        _stop_stage(
            authority,
            root,
            start_stage=start,
            advanced_stages=(("ocr",) if advanced else ()),
            outcome="blocked",
            stage="canonicalize",
            reason="canonical_prerequisite_unavailable",
        )
    finally:
        owner.close()
