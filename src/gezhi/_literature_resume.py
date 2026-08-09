from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, NoReturn, TypeAlias, cast

from pypdf import PdfReader

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
        reader = PdfReader(str(pdf_path), strict=True)
        texts: list[str] = []
        counts: list[int] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            texts.append(text)
            counts.append(sum(not character.isspace() for character in text))
    except Exception:  # noqa: BLE001 - inability to prove native text selects OCR.
        return _SelectionV1(
            method="mineru_ocr",
            reason="native_text_proof_unavailable",
            page_count=None,
            non_whitespace_counts=(),
            page_texts=(),
        )
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


def _run_ocr_attempt_v1(
    profile: OcrRuntimeProfileV1,
    input_path: Path,
    output_root: Path,
) -> OcrAttemptResultV1:
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
    )
    return OcrAttemptResultV1(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _provider_output_leaf(output_root: Path) -> Path:
    return output_root / "source" / "ocr"


def _validate_provider_output(output_root: Path) -> None:
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
        markdown = _read_safe_bytes(leaf / "source.md")
        markdown.decode("utf-8")
        for name in (
            "source_content_list.json",
            "source_content_list_v2.json",
            "source_middle.json",
            "source_model.json",
        ):
            json.loads(_read_safe_bytes(leaf / name))
        middle = json.loads(_read_safe_bytes(leaf / "source_middle.json"))
        if (
            type(middle) is not dict
            or middle.get("_backend") != "pipeline"
            or middle.get("_version_name") != "3.4.4"
        ):
            raise _OcrOutputInvalidV1("MinerU identity is invalid")
        for name in (
            "source_layout.pdf",
            "source_origin.pdf",
            "source_span.pdf",
        ):
            if not _read_safe_bytes(leaf / name).startswith(b"%PDF-"):
                raise _OcrOutputInvalidV1("MinerU PDF output is invalid")
    except (
        DataRootOpenErrorV1,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        _RunInvalidV1,
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
            for path in paths:
                parts = validate_relative_parts_v1(tuple(path.split("/")))
                with run.open_relative_file_v1(parts) as asset:
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
        method not in {"native_text", "mineru_ocr"}
        or value["minimum_non_whitespace_per_page"] != _MINIMUM_NON_WHITESPACE
        or type(counts) is not list
        or any(type(count) is not int or count < 0 for count in counts)
        or (page_count is not None and (type(page_count) is not int or page_count < 0))
        or type(value["reason"]) is not str
        or value["schema_version"] != "gezhi.literature_ocr_selection.v1"
        or value["selector_profile"] != _SELECTOR_PROFILE
    ):
        raise _RunInvalidV1("OCR selection is invalid")
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
        status not in {"succeeded", "blocked", "failed"}
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
            if (
                set(native) != {"pages", "schema_version", "source_id", "work_id"}
                or native["schema_version"] != "gezhi.literature_native_text.v1"
                or native["source_id"] != authority.source_id
                or native["work_id"] != authority.work_id
                or type(native["pages"]) is not list
            ):
                raise _RunInvalidV1("native text output is invalid")
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
                _validate_provider_output(run_dir / "output" / "mineru")
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


def _recover_complete_staged_successes(
    staging_dir: Path,
    runs_dir: Path,
    authority: ActiveSourceAuthorityV1,
) -> None:
    try:
        entries = tuple(staging_dir.iterdir())
    except OSError as error:
        raise _RunInvalidV1("OCR staging cannot be inspected") from error
    for entry in entries:
        if _RUN_ID.fullmatch(entry.name) is None:
            continue
        try:
            run = _load_run(entry, entry.name, authority)
        except _RunInvalidV1:
            continue
        if run.status != "succeeded":
            continue
        target = runs_dir / entry.name
        if target.exists():
            raise _RunInvalidV1("OCR recovery target conflicts")
        try:
            os.rename(entry, target)
        except OSError as error:
            raise _RunInvalidV1("OCR staged success recovery failed") from error


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
    try:
        os.rename(stage, target)
    except FileExistsError as error:
        raise _RunInvalidV1("OCR run target conflicts") from error
    except OSError as error:
        raise _CommitFailedV1("OCR run directory commit failed") from error
    return _load_run(target, run_id, authority)


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
        try:
            completed = _run_ocr_attempt_v1(profile, input_path, provider_output)
        except ProbeUnavailableError:
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
        except subprocess.TimeoutExpired:
            _write_attempt_assets(
                attempt_dir,
                stdout=b"",
                stderr=b"",
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
        except ProbeOutputLimitExceeded:
            _write_attempt_assets(
                attempt_dir,
                stdout=b"",
                stderr=b"",
                document=_attempt_document(
                    attempt,
                    outcome="output_limit_exceeded",
                    returncode=None,
                ),
            )
            return "failed", "ocr_failed", attempt

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
            _validate_provider_output(provider_output)
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
    if current is not None and _run_matches_current_profile(current):
        return False, "canonicalize"

    try:
        _recover_complete_staged_successes(staging_dir, runs_dir, authority)
        matches = _matching_success_runs(runs_dir, authority)
    except _RunInvalidV1 as error:
        raise ResumeStoppedV1("failed", "recovery_failed") from error
    if len(matches) > 1:
        raise ResumeStoppedV1("failed", "recovery_failed")
    if len(matches) == 1:
        try:
            _fresh_authority_or_stop(authority, root)
            _atomic_replace_current(ocr_dir, authority, matches[0])
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
        _ensure_plain_directory(stage)
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
