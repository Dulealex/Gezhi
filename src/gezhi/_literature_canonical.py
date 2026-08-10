from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import BinaryIO, Literal, NoReturn, TypeAlias, cast

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

OcrMethod: TypeAlias = Literal["native_text", "mineru_ocr"]
CanonicalFailureReason: TypeAlias = Literal[
    "canonicalization_failed",
    "asset_integrity_lost",
    "commit_failed",
]
CanonicalAuthorityReason: TypeAlias = Literal[
    "data_root_integrity_lost",
    "active_source_unavailable",
    "active_source_invalid",
    "recovery_failed",
]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OCR_RUN_ID = re.compile(
    r"^ocrrun_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_CANONICAL_RUN_ID = re.compile(
    r"^canrun_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_BLOCK_ID = re.compile(r"^blk_[0-9a-f]{24}$")
_CURRENT_TEMP_NAME = re.compile(r"^\.current\.json\.[0-9a-f]{32}\.tmp$")
_CURRENT_REPLACE_NAME = re.compile(
    r"^\.current-replace\.[0-9a-f]{32}\.tmp$"
)
_CANONICAL_IMAGE_PATH = re.compile(
    r"^images/[0-9a-f]{64}\.(?:jpg|png)$"
)

_MAX_JSON_OR_TEXT_BYTES = 67_108_864
_MAX_PAGE_COUNT = 4_096
_MAX_BLOCK_COUNT = 4_096
_MAX_BLOCK_TEXT_BYTES = 1_048_576
_MAX_IMAGE_COUNT = 4_000
_MAX_IMAGE_BYTES = 67_108_864
_MAX_IMAGE_TOTAL_BYTES = 2_147_483_648
_MAX_RUN_ENTRIES = 4_096
_MAX_OCR_MANIFEST_ASSETS = 4_128

_BLOCK_KINDS = frozenset(
    {
        "heading",
        "paragraph",
        "list_item",
        "table",
        "figure_caption",
        "figure_text",
        "equation",
        "other_text",
    }
)
_MINERU_SPAN_TYPES = frozenset(
    {"code_inline", "equation_inline", "md", "phonetic", "text"}
)


_CANONICAL_JSON_ENCODER = json.JSONEncoder(
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
)


def _canonical_json_payload_chunks(value: object) -> Iterator[bytes]:
    for chunk in _CANONICAL_JSON_ENCODER.iterencode(value):
        yield chunk.encode("utf-8")


def _canonical_json_payload_bytes(value: object) -> bytes:
    return b"".join(_canonical_json_payload_chunks(value))


def _canonical_json_file_bytes(value: object) -> bytes:
    return _canonical_json_payload_bytes(value) + b"\n"


_BLOCK_SCHEMA_DOCUMENT = {
    "$id": "https://gezhi.local/schemas/evidence-block-v1.schema.json",
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "additionalProperties": False,
    "properties": {
        "bbox": {
            "oneOf": [
                {"type": "null"},
                {
                    "items": {
                        "pattern": r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
                        "type": "string",
                    },
                    "maxItems": 4,
                    "minItems": 4,
                    "type": "array",
                },
            ]
        },
        "block_id": {"pattern": r"^blk_[0-9a-f]{24}$", "type": "string"},
        "heading_path": {"items": {"type": "string"}, "type": "array"},
        "image_path": {
            "oneOf": [
                {"type": "null"},
                {
                    "pattern": r"^images/[0-9a-f]{64}\.(?:jpg|png)$",
                    "type": "string",
                },
            ]
        },
        "kind": {"enum": sorted(_BLOCK_KINDS)},
        "order": {"minimum": 0, "type": "integer"},
        "page_index": {"minimum": 0, "type": "integer"},
        "schema_version": {"const": "gezhi.evidence_block.v1"},
        "text": {"minLength": 1, "type": "string"},
    },
    "required": [
        "bbox",
        "block_id",
        "heading_path",
        "image_path",
        "kind",
        "order",
        "page_index",
        "schema_version",
        "text",
    ],
    "title": "EvidenceBlockV1",
    "type": "object",
}
_BLOCK_SCHEMA_BYTES = _canonical_json_file_bytes(_BLOCK_SCHEMA_DOCUMENT)
_BLOCK_SCHEMA_SHA256 = hashlib.sha256(_BLOCK_SCHEMA_BYTES).hexdigest()
_CANONICALIZER_PROFILE = {
    "block_schema_sha256": _BLOCK_SCHEMA_SHA256,
    "canonicalizer": "native-or-mineru-content-list-v2",
    "max_block_count": _MAX_BLOCK_COUNT,
    "max_block_text_bytes": _MAX_BLOCK_TEXT_BYTES,
    "max_image_bytes": _MAX_IMAGE_BYTES,
    "max_image_count": _MAX_IMAGE_COUNT,
    "max_image_total_bytes": _MAX_IMAGE_TOTAL_BYTES,
    "max_page_count": _MAX_PAGE_COUNT,
    "normalization": "crlf-cr-to-lf+nfc+python311-strip",
    "python": "3.11",
    "schema_version": "gezhi.literature_canonicalizer_profile.v1",
}
_CANONICALIZER_PROFILE_SHA256 = hashlib.sha256(
    _canonical_json_payload_bytes(_CANONICALIZER_PROFILE)
).hexdigest()


@dataclass(frozen=True, slots=True)
class CurrentOcrAssetV1:
    method: OcrMethod
    run_id: str
    run_directory: Path
    input_fingerprint_sha256: str
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class _OcrManifestAssetV1:
    relative_path: str
    source_path: Path
    byte_length: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CurrentCanonicalAssetV1:
    run_id: str
    run_directory: Path
    input_fingerprint_sha256: str
    manifest_sha256: str
    canonical_content_sha256: str


@dataclass(frozen=True, slots=True)
class CanonicalAdvanceV1:
    advanced: bool
    current: CurrentCanonicalAssetV1


class CanonicalStageStoppedV1(RuntimeError):
    def __init__(self, reason: CanonicalFailureReason) -> None:
        super().__init__(f"Canonical stage stopped: {reason}")
        self.reason = reason


class CanonicalAuthorityStoppedV1(RuntimeError):
    def __init__(self, reason: CanonicalAuthorityReason) -> None:
        super().__init__(f"Canonical authority stopped: {reason}")
        self.reason = reason


class CanonicalRecoveryUncertainV1(RuntimeError):
    """A commit or namespace result cannot be represented as handled."""


class _CanonicalInvalidV1(RuntimeError):
    pass


class _CanonicalizationInvalidV1(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _ImageSourceV1:
    canonical_path: str
    source_path: Path
    sha256: str
    byte_length: int
    media_type: Literal["image/jpeg", "image/png"]
    ocr_relative_path: str | None = None


@dataclass(frozen=True, slots=True)
class _BundleV1:
    page_count: int
    blocks: tuple[dict[str, object], ...]
    document_bytes: bytes
    blocks_bytes: bytes
    images: tuple[_ImageSourceV1, ...]
    canonical_content_sha256: str
    consumed_ocr_assets: tuple[_OcrManifestAssetV1, ...] = ()


@dataclass(frozen=True, slots=True)
class _ValidatedCanonicalRunV1:
    path: Path
    run_id: str
    input_fingerprint_sha256: str
    manifest_sha256: str
    canonical_content_sha256: str


def _normalize_text(value: object) -> str:
    if type(value) is not str:
        raise _CanonicalizationInvalidV1("Canonical text is not a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise _CanonicalizationInvalidV1(
            "Canonical text contains an unpaired surrogate"
        ) from error
    if "\x00" in value:
        raise _CanonicalizationInvalidV1("Canonical text contains NUL")
    normalized = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    ).strip()
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as error:
        raise _CanonicalizationInvalidV1(
            "Canonical text cannot be encoded"
        ) from error
    return normalized


def _split_native_paragraphs(value: object) -> Iterator[str]:
    text = _normalize_text(value)
    if not text:
        return
    current: list[str] = []
    start = 0
    while True:
        stop = text.find("\n", start)
        line = text[start:] if stop < 0 else text[start:stop]
        if line.strip():
            current.append(line)
        elif current:
            paragraph = _normalize_text("\n".join(current))
            if paragraph:
                yield paragraph
            current = []
        if stop < 0:
            break
        start = stop + 1
    if current:
        paragraph = _normalize_text("\n".join(current))
        if paragraph:
            yield paragraph


def _normalize_decimal(value: object) -> str:
    if type(value) is int:
        return str(value)
    if type(value) is not float or not math.isfinite(value):
        raise _CanonicalizationInvalidV1("Canonical bbox is invalid")
    if value == 0:
        return "0"
    rendered = format(Decimal(str(value)), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered in {"-0", ""}:
        rendered = "0"
    return rendered


def _normalize_bbox(value: object) -> list[str] | None:
    if value is None:
        return None
    if type(value) is not list or len(value) != 4:
        raise _CanonicalizationInvalidV1("Canonical bbox is invalid")
    numeric: list[float] = []
    rendered: list[str] = []
    for item in value:
        if type(item) not in {int, float}:
            raise _CanonicalizationInvalidV1("Canonical bbox is invalid")
        number = float(cast(int | float, item))
        if not math.isfinite(number):
            raise _CanonicalizationInvalidV1("Canonical bbox is invalid")
        numeric.append(number)
        rendered.append(_normalize_decimal(item))
    if numeric[2] <= numeric[0] or numeric[3] <= numeric[1]:
        raise _CanonicalizationInvalidV1("Canonical bbox is invalid")
    return rendered


def _block_record(
    *,
    order: int,
    kind: str,
    text: str,
    heading_path: tuple[str, ...],
    page_index: int,
    bbox: list[str] | None,
    image_path: str | None,
    identities: dict[str, str],
) -> dict[str, object]:
    if kind not in _BLOCK_KINDS or not text:
        raise _CanonicalizationInvalidV1("Evidence Block is invalid")
    text_bytes = text.encode("utf-8")
    if len(text_bytes) > _MAX_BLOCK_TEXT_BYTES:
        raise _CanonicalizationInvalidV1("Evidence Block text exceeds its limit")
    identity = {
        "bbox": bbox,
        "heading_path": list(heading_path),
        "image_path": image_path,
        "kind": kind,
        "order": order,
        "page_index": page_index,
        "schema_version": "gezhi.evidence_block_identity.v1",
        "text": text,
    }
    full_hash = hashlib.sha256(
        _canonical_json_payload_bytes(identity)
    ).hexdigest()
    block_id = "blk_" + full_hash[:24]
    prior = identities.get(block_id)
    if prior is not None and prior != full_hash:
        raise _CanonicalizationInvalidV1("Evidence Block identity collision")
    if prior is not None:
        raise _CanonicalizationInvalidV1("Evidence Block identity is duplicated")
    identities[block_id] = full_hash
    return {
        "bbox": bbox,
        "block_id": block_id,
        "heading_path": list(heading_path),
        "image_path": image_path,
        "kind": kind,
        "order": order,
        "page_index": page_index,
        "schema_version": "gezhi.evidence_block.v1",
        "text": text,
    }


def _document_bytes(
    page_count: int,
    blocks: tuple[dict[str, object], ...],
) -> bytes:
    by_page: list[list[str]] = [[] for _ in range(page_count)]
    for block in blocks:
        by_page[cast(int, block["page_index"])].append(cast(str, block["text"]))
    payload = bytearray()

    def extend(chunk: bytes) -> None:
        if len(payload) + len(chunk) > _MAX_JSON_OR_TEXT_BYTES:
            raise _CanonicalizationInvalidV1(
                "Canonical document exceeds its limit"
            )
        payload.extend(chunk)

    for index, page_blocks in enumerate(by_page):
        if index:
            extend(b"\n\n")
        extend(f"<!-- gezhi-page:{index} -->".encode())
        for text in page_blocks:
            extend(b"\n\n")
            extend(text.encode("utf-8"))
    extend(b"\n")
    return bytes(payload)


def _blocks_bytes(blocks: tuple[dict[str, object], ...]) -> bytes:
    payload = bytearray()
    for block in blocks:
        for chunk in _canonical_json_payload_chunks(block):
            if len(payload) + len(chunk) > _MAX_JSON_OR_TEXT_BYTES:
                raise _CanonicalizationInvalidV1(
                    "Canonical blocks exceed their limit"
                )
            payload.extend(chunk)
        if len(payload) + 1 > _MAX_JSON_OR_TEXT_BYTES:
            raise _CanonicalizationInvalidV1(
                "Canonical blocks exceed their limit"
            )
        payload.append(0x0A)
    return bytes(payload)


def _content_identity(
    document_bytes: bytes,
    blocks_bytes: bytes,
    images: tuple[_ImageSourceV1, ...],
) -> str:
    image_entries = [
        {"path": image.canonical_path, "sha256": image.sha256}
        for image in sorted(images, key=lambda item: item.canonical_path.encode("utf-8"))
    ]
    identity = {
        "blocks_sha256": hashlib.sha256(blocks_bytes).hexdigest(),
        "document_sha256": hashlib.sha256(document_bytes).hexdigest(),
        "images": image_entries,
        "schema_version": "gezhi.canonical_content.v1",
    }
    return hashlib.sha256(_canonical_json_payload_bytes(identity)).hexdigest()


def _native_bundle(value: object) -> _BundleV1:
    if type(value) is not dict or set(value) != {
        "pages",
        "schema_version",
        "source_id",
        "work_id",
    }:
        raise _CanonicalizationInvalidV1("Native OCR document is invalid")
    native = cast(dict[str, object], value)
    pages = native["pages"]
    if (
        native["schema_version"] != "gezhi.literature_native_text.v1"
        or type(pages) is not list
        or not 1 <= len(pages) <= _MAX_PAGE_COUNT
    ):
        raise _CanonicalizationInvalidV1("Native OCR pages are invalid")
    identities: dict[str, str] = {}
    blocks: list[dict[str, object]] = []
    for page_index, page in enumerate(pages):
        if (
            type(page) is not dict
            or set(page) != {"page_index", "text"}
            or type(page.get("page_index")) is not int
            or page.get("page_index") != page_index
        ):
            raise _CanonicalizationInvalidV1("Native OCR page is invalid")
        for paragraph in _split_native_paragraphs(page.get("text")):
            if len(blocks) >= _MAX_BLOCK_COUNT:
                raise _CanonicalizationInvalidV1(
                    "Canonical block count exceeds its limit"
                )
            blocks.append(
                _block_record(
                    order=len(blocks),
                    kind="paragraph",
                    text=paragraph,
                    heading_path=(),
                    page_index=page_index,
                    bbox=None,
                    image_path=None,
                    identities=identities,
                )
            )
    if not blocks:
        raise _CanonicalizationInvalidV1("Canonical document has no text")
    block_tuple = tuple(blocks)
    document = _document_bytes(len(pages), block_tuple)
    encoded_blocks = _blocks_bytes(block_tuple)
    return _BundleV1(
        page_count=len(pages),
        blocks=block_tuple,
        document_bytes=document,
        blocks_bytes=encoded_blocks,
        images=(),
        canonical_content_sha256=_content_identity(document, encoded_blocks, ()),
    )


def _mineru_span_text(value: object) -> str:
    if type(value) is not list:
        raise _CanonicalizationInvalidV1("MinerU text spans are invalid")
    pieces: list[str] = []
    for span in value:
        if (
            type(span) is not dict
            or set(span) != {"content", "type"}
            or span.get("type") not in _MINERU_SPAN_TYPES
            or type(span.get("content")) is not str
        ):
            raise _CanonicalizationInvalidV1("MinerU text span is invalid")
        pieces.append(cast(str, span["content"]))
    return _normalize_text("".join(pieces))


def _mineru_image_source(
    leaf: Path,
    value: object,
    cache: dict[str, _ImageSourceV1],
    *,
    ocr_assets: dict[str, _OcrManifestAssetV1] | None = None,
    asset_prefix: str = "",
) -> _ImageSourceV1:
    if type(value) is not dict or set(value) != {"path"}:
        raise _CanonicalizationInvalidV1("MinerU image source is invalid")
    provider_path = value["path"]
    if (
        type(provider_path) is not str
        or unicodedata.normalize("NFC", provider_path) != provider_path
        or re.fullmatch(
            r"images/[^/]+\.(?:jpeg|jpg|png)",
            provider_path,
            flags=re.IGNORECASE,
        )
        is None
    ):
        raise _CanonicalizationInvalidV1("MinerU image path is invalid")
    cached = cache.get(provider_path)
    if cached is not None:
        return cached
    ocr_relative_path = (
        f"{asset_prefix}/{provider_path}" if asset_prefix else None
    )
    bound_asset = (
        None
        if ocr_assets is None or ocr_relative_path is None
        else _required_ocr_asset(ocr_assets, ocr_relative_path)
    )
    try:
        parts = validate_relative_parts_v1(tuple(provider_path.split("/")))
        source_path = leaf.joinpath(*parts)
        with open_validated_local_file_v1(str(source_path)) as source:
            if source.size > _MAX_IMAGE_BYTES:
                raise _CanonicalizationInvalidV1(
                    "MinerU image exceeds its limit"
                )
            digest = hashlib.sha256()
            prefix = bytearray()
            for chunk in source.iter_verified_chunks_v1():
                if len(prefix) < 8:
                    prefix.extend(chunk[: 8 - len(prefix)])
                digest.update(chunk)
            byte_length = source.size
    except _CanonicalizationInvalidV1:
        raise
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        ValueError,
    ) as error:
        if ocr_assets is not None:
            raise _CanonicalInvalidV1(
                "MinerU image differs from its OCR manifest"
            ) from error
        raise _CanonicalizationInvalidV1(
            "MinerU image cannot be read safely"
        ) from error
    sha256 = digest.hexdigest()
    if bound_asset is not None and (
        bound_asset.source_path != source_path
        or bound_asset.byte_length != byte_length
        or bound_asset.sha256 != sha256
    ):
        raise _CanonicalInvalidV1("MinerU image differs from its OCR manifest")
    if bytes(prefix).startswith(b"\xff\xd8\xff"):
        suffix = ".jpg"
        media: Literal["image/jpeg", "image/png"] = "image/jpeg"
    elif bytes(prefix).startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
        media = "image/png"
    else:
        raise _CanonicalizationInvalidV1("MinerU image magic is invalid")
    image = _ImageSourceV1(
        canonical_path=f"images/{sha256}{suffix}",
        source_path=source_path,
        sha256=sha256,
        byte_length=byte_length,
        media_type=media,
        ocr_relative_path=ocr_relative_path,
    )
    cache[provider_path] = image
    return image


def _mineru_bundle(
    value: object,
    leaf: Path,
    *,
    ocr_assets: dict[str, _OcrManifestAssetV1] | None = None,
    asset_prefix: str = "",
) -> _BundleV1:
    if (
        type(value) is not list
        or not 1 <= len(value) <= _MAX_PAGE_COUNT
    ):
        raise _CanonicalizationInvalidV1("MinerU page list is invalid")
    pages = cast(list[object], value)
    identities: dict[str, str] = {}
    blocks: list[dict[str, object]] = []
    headings: list[tuple[int, str]] = []
    image_cache: dict[str, _ImageSourceV1] = {}
    used_images: dict[str, _ImageSourceV1] = {}
    used_image_total = 0

    def emit(
        *,
        kind: str,
        raw_text: object,
        page_index: int,
        bbox: list[str],
        image: _ImageSourceV1 | None = None,
        heading_path: tuple[str, ...] | None = None,
    ) -> str | None:
        nonlocal used_image_total
        text = _normalize_text(raw_text)
        if not text:
            return None
        if len(blocks) >= _MAX_BLOCK_COUNT:
            raise _CanonicalizationInvalidV1(
                "Canonical block count exceeds its limit"
            )
        path = (
            tuple(title for _level, title in headings)
            if heading_path is None
            else heading_path
        )
        block = _block_record(
            order=len(blocks),
            kind=kind,
            text=text,
            heading_path=path,
            page_index=page_index,
            bbox=bbox,
            image_path=None if image is None else image.canonical_path,
            identities=identities,
        )
        blocks.append(block)
        if image is not None:
            prior = used_images.get(image.canonical_path)
            if prior is not None and (
                prior.sha256 != image.sha256
                or prior.byte_length != image.byte_length
                or prior.media_type != image.media_type
            ):
                raise _CanonicalizationInvalidV1(
                    "Canonical image identity collision"
                )
            if prior is None:
                if (
                    len(used_images) >= _MAX_IMAGE_COUNT
                    or used_image_total + image.byte_length
                    > _MAX_IMAGE_TOTAL_BYTES
                ):
                    raise _CanonicalizationInvalidV1(
                        "Canonical images exceed their limit"
                    )
                used_images[image.canonical_path] = image
                used_image_total += image.byte_length
        return text

    for page_index, page in enumerate(pages):
        if type(page) is not list:
            raise _CanonicalizationInvalidV1("MinerU page is invalid")
        for item in page:
            if type(item) is not dict:
                raise _CanonicalizationInvalidV1("MinerU item is invalid")
            item_type = item.get("type")
            content = item.get("content")
            if type(item_type) is not str or type(content) is not dict:
                raise _CanonicalizationInvalidV1("MinerU item is invalid")
            bbox = _normalize_bbox(item.get("bbox"))
            if bbox is None:
                raise _CanonicalizationInvalidV1("MinerU item bbox is invalid")
            body = cast(dict[str, object], content)
            if item_type == "title":
                level = body.get("level")
                if type(level) is not int or level <= 0:
                    raise _CanonicalizationInvalidV1(
                        "MinerU heading level is invalid"
                    )
                while headings and headings[-1][0] >= level:
                    headings.pop()
                ancestors = tuple(title for _level, title in headings)
                title = emit(
                    kind="heading",
                    raw_text=_mineru_span_text(body.get("title_content")),
                    page_index=page_index,
                    bbox=bbox,
                    heading_path=ancestors,
                )
                if title is not None:
                    headings.append((level, title))
                continue
            if item_type == "paragraph":
                emit(
                    kind="paragraph",
                    raw_text=_mineru_span_text(body.get("paragraph_content")),
                    page_index=page_index,
                    bbox=bbox,
                )
                continue
            if item_type in {
                "page_aside_text",
                "page_footer",
                "page_footnote",
                "page_header",
                "page_number",
            }:
                emit(
                    kind="other_text",
                    raw_text=_mineru_span_text(body.get(f"{item_type}_content")),
                    page_index=page_index,
                    bbox=bbox,
                )
                continue
            if item_type == "equation_interline":
                image = _mineru_image_source(
                    leaf,
                    body.get("image_source"),
                    image_cache,
                    ocr_assets=ocr_assets,
                    asset_prefix=asset_prefix,
                )
                emit(
                    kind="equation",
                    raw_text=body.get("math_content"),
                    page_index=page_index,
                    bbox=bbox,
                    image=image,
                )
                continue
            if item_type in {"image", "chart"}:
                image = _mineru_image_source(
                    leaf,
                    body.get("image_source"),
                    image_cache,
                    ocr_assets=ocr_assets,
                    asset_prefix=asset_prefix,
                )
                emit(
                    kind="figure_caption",
                    raw_text=_mineru_span_text(
                        body.get(f"{item_type}_caption")
                    ),
                    page_index=page_index,
                    bbox=bbox,
                    image=image,
                )
                emit(
                    kind="figure_text",
                    raw_text=_mineru_span_text(
                        body.get(f"{item_type}_footnote")
                    ),
                    page_index=page_index,
                    bbox=bbox,
                    image=image,
                )
                continue
            if item_type == "table":
                image = _mineru_image_source(
                    leaf,
                    body.get("image_source"),
                    image_cache,
                    ocr_assets=ocr_assets,
                    asset_prefix=asset_prefix,
                )
                emit(
                    kind="figure_caption",
                    raw_text=_mineru_span_text(body.get("table_caption")),
                    page_index=page_index,
                    bbox=bbox,
                    image=image,
                )
                emit(
                    kind="table",
                    raw_text=body.get("html"),
                    page_index=page_index,
                    bbox=bbox,
                    image=image,
                )
                emit(
                    kind="figure_text",
                    raw_text=_mineru_span_text(body.get("table_footnote")),
                    page_index=page_index,
                    bbox=bbox,
                    image=image,
                )
                continue
            if item_type in {"code", "algorithm"}:
                for field in (
                    f"{item_type}_caption",
                    f"{item_type}_content",
                    f"{item_type}_footnote",
                ):
                    emit(
                        kind="other_text",
                        raw_text=_mineru_span_text(body.get(field)),
                        page_index=page_index,
                        bbox=bbox,
                    )
                continue
            if item_type in {"list", "index"}:
                items = body.get("list_items")
                if type(items) is not list:
                    raise _CanonicalizationInvalidV1(
                        "MinerU list items are invalid"
                    )
                for list_item in items:
                    if (
                        type(list_item) is not dict
                        or set(list_item) != {"item_content", "item_type"}
                        or list_item.get("item_type") != "text"
                    ):
                        raise _CanonicalizationInvalidV1(
                            "MinerU list item is invalid"
                        )
                    emit(
                        kind="list_item",
                        raw_text=_mineru_span_text(
                            list_item.get("item_content")
                        ),
                        page_index=page_index,
                        bbox=bbox,
                    )
                continue
            raise _CanonicalizationInvalidV1("MinerU item type is invalid")

    if not blocks:
        raise _CanonicalizationInvalidV1("Canonical document has no text")
    images = tuple(
        sorted(
            used_images.values(),
            key=lambda image: image.canonical_path.encode("utf-8"),
        )
    )
    if (
        len(images) > _MAX_IMAGE_COUNT
        or used_image_total > _MAX_IMAGE_TOTAL_BYTES
    ):
        raise _CanonicalizationInvalidV1("Canonical images exceed their limit")
    block_tuple = tuple(blocks)
    document = _document_bytes(len(pages), block_tuple)
    encoded_blocks = _blocks_bytes(block_tuple)
    consumed_images: tuple[_OcrManifestAssetV1, ...] = ()
    if ocr_assets is not None:
        consumed_paths = sorted(
            {
                image.ocr_relative_path
                for image in image_cache.values()
                if image.ocr_relative_path is not None
            },
            key=lambda value: value.encode("utf-8"),
        )
        consumed_images = tuple(
            _required_ocr_asset(ocr_assets, path)
            for path in consumed_paths
        )
    return _BundleV1(
        page_count=len(pages),
        blocks=block_tuple,
        document_bytes=document,
        blocks_bytes=encoded_blocks,
        images=images,
        canonical_content_sha256=_content_identity(
            document, encoded_blocks, images
        ),
        consumed_ocr_assets=consumed_images,
    )


def _write_all(destination: BinaryIO, payload: bytes) -> None:
    offset = 0
    view = memoryview(payload)
    while offset < len(payload):
        count = destination.write(view[offset:])
        remaining = len(payload) - offset
        if type(count) is not int or not 1 <= count <= remaining:
            raise OSError("file write did not complete deterministically")
        offset += count


def _read_safe_bytes(path: Path, *, limit: int) -> bytes:
    try:
        with open_validated_local_file_v1(str(path)) as source:
            return source.read_bytes_v1(limit=limit)
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        ValueError,
    ) as error:
        raise _CanonicalInvalidV1("Canonical asset is unreadable") from error


def _read_json_document(
    path: Path,
    *,
    limit: int = _MAX_JSON_OR_TEXT_BYTES,
) -> tuple[dict[str, object], bytes]:
    payload = _read_safe_bytes(path, limit=limit)
    return _decode_json_document(payload), payload


def _decode_json_document(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(payload)
        canonical = _canonical_json_file_bytes(value)
    except (
        json.JSONDecodeError,
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as error:
        raise _CanonicalInvalidV1("Canonical JSON is invalid") from error
    if type(value) is not dict or payload != canonical:
        raise _CanonicalInvalidV1("Canonical JSON bytes are invalid")
    return cast(dict[str, object], value)


def _read_json_value(path: Path, *, limit: int) -> object:
    payload = _read_safe_bytes(path, limit=limit)
    return _decode_json_value(payload)


def _decode_json_value(payload: bytes) -> object:

    def closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON object key")
            value[key] = item
        return value

    def reject_constant(value: str) -> NoReturn:
        raise ValueError(f"invalid JSON constant: {value}")

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=closed_object,
            parse_constant=reject_constant,
        )
    except (
        json.JSONDecodeError,
        RecursionError,
        UnicodeError,
        ValueError,
    ) as error:
        raise _CanonicalInvalidV1("OCR JSON is invalid") from error


def _write_new_verified(path: Path, payload: bytes) -> None:
    try:
        with (
            open_validated_data_root_v1(str(path.parent)),
            path.open("xb", buffering=0) as destination,
        ):
            _write_all(destination, payload)
        if _read_safe_bytes(path, limit=len(payload)) != payload:
            raise OSError("Canonical asset readback differs")
    except FileExistsError as error:
        raise CanonicalRecoveryUncertainV1(
            "Canonical asset target conflicts"
        ) from error
    except (
        _CanonicalInvalidV1,
        DataRootOpenErrorV1,
        OSError,
    ) as error:
        raise CanonicalStageStoppedV1("commit_failed") from error


def _ensure_directory(path: Path) -> None:
    try:
        with open_validated_data_root_v1(str(path.parent)):
            try:
                path.mkdir()
            except FileExistsError:
                pass
        with open_validated_data_root_v1(str(path)):
            pass
    except (DataRootOpenErrorV1, OSError) as error:
        raise CanonicalStageStoppedV1("commit_failed") from error


def _entry_names(path: Path) -> tuple[str, ...]:
    try:
        with open_validated_data_root_v1(str(path)), os.scandir(path) as entries:
            names: list[str] = []
            for entry in entries:
                names.append(entry.name)
                if len(names) > _MAX_RUN_ENTRIES:
                    raise CanonicalRecoveryUncertainV1(
                        "Canonical namespace exceeds its limit"
                    )
            return tuple(names)
    except CanonicalRecoveryUncertainV1:
        raise
    except (DataRootOpenErrorV1, OSError) as error:
        raise CanonicalRecoveryUncertainV1(
            "Canonical namespace cannot be proven"
        ) from error


def _name_exists(path: Path, name: str) -> bool:
    try:
        with open_validated_data_root_v1(str(path)):
            try:
                (path / name).lstat()
            except FileNotFoundError:
                return False
            return True
    except (DataRootOpenErrorV1, OSError) as error:
        raise CanonicalRecoveryUncertainV1(
            "Canonical namespace membership cannot be proven"
        ) from error


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


def _expected_ocr_current(
    authority: ActiveSourceAuthorityV1,
    ocr: CurrentOcrAssetV1,
) -> bytes:
    return _canonical_json_file_bytes(
        {
            "input_fingerprint_sha256": ocr.input_fingerprint_sha256,
            "manifest_sha256": ocr.manifest_sha256,
            "run_id": ocr.run_id,
            "schema_version": "gezhi.literature_ocr_current.v1",
            "source_id": authority.source_id,
            "source_sha256": authority.source_sha256,
            "work_id": authority.work_id,
        }
    )


def _load_ocr_manifest_assets(
    authority: ActiveSourceAuthorityV1,
    ocr: CurrentOcrAssetV1,
) -> dict[str, _OcrManifestAssetV1]:
    manifest, payload = _read_json_document(
        ocr.run_directory / "manifest.json"
    )
    if (
        hashlib.sha256(payload).hexdigest() != ocr.manifest_sha256
        or set(manifest)
        != {
            "assets",
            "input_fingerprint_sha256",
            "run_id",
            "schema_version",
            "source_id",
            "status",
            "work_id",
        }
        or manifest["input_fingerprint_sha256"]
        != ocr.input_fingerprint_sha256
        or manifest["run_id"] != ocr.run_id
        or manifest["schema_version"]
        != "gezhi.literature_ocr_run_manifest.v1"
        or manifest["source_id"] != authority.source_id
        or manifest["status"] != "succeeded"
        or manifest["work_id"] != authority.work_id
    ):
        raise _CanonicalInvalidV1("OCR manifest binding is invalid")
    values = manifest["assets"]
    if type(values) is not list or len(values) > _MAX_OCR_MANIFEST_ASSETS:
        raise _CanonicalInvalidV1("OCR manifest assets are invalid")
    assets: dict[str, _OcrManifestAssetV1] = {}
    prior_path: bytes | None = None
    for raw in values:
        if type(raw) is not dict or frozenset(raw) not in {
            frozenset({"byte_length", "media_type", "path", "sha256"}),
            frozenset(
                {
                    "byte_length",
                    "media_type",
                    "path",
                    "schema_version",
                    "sha256",
                }
            ),
        }:
            raise _CanonicalInvalidV1("OCR manifest asset shape is invalid")
        entry = cast(dict[str, object], raw)
        relative_path = entry["path"]
        byte_length = entry["byte_length"]
        sha256 = entry["sha256"]
        if (
            type(relative_path) is not str
            or not relative_path
            or unicodedata.normalize("NFC", relative_path) != relative_path
            or type(byte_length) is not int
            or byte_length < 0
            or type(sha256) is not str
            or _SHA256.fullmatch(sha256) is None
            or type(entry["media_type"]) is not str
            or not entry["media_type"]
            or (
                "schema_version" in entry
                and type(entry["schema_version"]) is not str
            )
        ):
            raise _CanonicalInvalidV1("OCR manifest asset is invalid")
        try:
            parts = validate_relative_parts_v1(
                tuple(relative_path.split("/"))
            )
        except ValueError as error:
            raise _CanonicalInvalidV1(
                "OCR manifest asset path is invalid"
            ) from error
        if "/".join(parts) != relative_path or relative_path == "manifest.json":
            raise _CanonicalInvalidV1("OCR manifest asset path is invalid")
        encoded_path = relative_path.encode("utf-8")
        if (
            relative_path in assets
            or (prior_path is not None and encoded_path <= prior_path)
        ):
            raise _CanonicalInvalidV1("OCR manifest asset order is invalid")
        prior_path = encoded_path
        assets[relative_path] = _OcrManifestAssetV1(
            relative_path=relative_path,
            source_path=ocr.run_directory.joinpath(*parts),
            byte_length=byte_length,
            sha256=sha256,
        )
    return assets


def _required_ocr_asset(
    assets: dict[str, _OcrManifestAssetV1],
    relative_path: str,
) -> _OcrManifestAssetV1:
    asset = assets.get(relative_path)
    if asset is None:
        raise _CanonicalInvalidV1("Required OCR asset is not manifest-bound")
    return asset


def _read_ocr_asset_bytes(
    asset: _OcrManifestAssetV1,
    *,
    limit: int,
) -> bytes:
    if asset.byte_length > limit:
        raise _CanonicalInvalidV1("OCR asset exceeds its consumer limit")
    try:
        with open_validated_local_file_v1(str(asset.source_path)) as source:
            if source.size != asset.byte_length:
                raise OSError("OCR asset length differs")
            payload = source.read_bytes_v1(limit=limit)
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        ValueError,
    ) as error:
        raise _CanonicalInvalidV1("OCR asset cannot be read safely") from error
    if hashlib.sha256(payload).hexdigest() != asset.sha256:
        raise _CanonicalInvalidV1("OCR asset hash differs")
    return payload


def _verify_ocr_assets(
    assets: tuple[_OcrManifestAssetV1, ...],
) -> None:
    for asset in assets:
        try:
            with open_validated_local_file_v1(str(asset.source_path)) as source:
                if (
                    source.size != asset.byte_length
                    or source.sha256_v1() != asset.sha256
                ):
                    raise OSError("OCR asset binding differs")
        except (
            DataRootLifecycleErrorV1,
            DataRootOpenErrorV1,
            OSError,
            ValueError,
        ) as error:
            raise CanonicalStageStoppedV1(
                "asset_integrity_lost"
            ) from error


def _validate_ocr_binding(
    authority: ActiveSourceAuthorityV1,
    ocr: CurrentOcrAssetV1,
) -> None:
    if (
        ocr.method not in {"native_text", "mineru_ocr"}
        or _OCR_RUN_ID.fullmatch(ocr.run_id) is None
        or _SHA256.fullmatch(ocr.input_fingerprint_sha256) is None
        or _SHA256.fullmatch(ocr.manifest_sha256) is None
        or ocr.run_directory
        != authority.source_directory / "ocr" / "runs" / ocr.run_id
    ):
        raise CanonicalStageStoppedV1("asset_integrity_lost")
    try:
        current = _read_safe_bytes(
            authority.source_directory / "ocr" / "current.json",
            limit=_MAX_JSON_OR_TEXT_BYTES,
        )
        manifest = _read_safe_bytes(
            ocr.run_directory / "manifest.json",
            limit=_MAX_JSON_OR_TEXT_BYTES,
        )
    except _CanonicalInvalidV1 as error:
        raise CanonicalStageStoppedV1("asset_integrity_lost") from error
    if (
        current != _expected_ocr_current(authority, ocr)
        or hashlib.sha256(manifest).hexdigest() != ocr.manifest_sha256
    ):
        raise CanonicalStageStoppedV1("asset_integrity_lost")


def _checkpoint(
    authority: ActiveSourceAuthorityV1,
    ocr: CurrentOcrAssetV1,
    root: ValidatedDataRootV1,
) -> None:
    try:
        fresh = load_active_source_authority_v1(authority.work_id, root=root)
    except ActiveSourceAuthorityStoppedV1 as error:
        reason: CanonicalAuthorityReason
        if error.reason in {
            "data_root_integrity_lost",
            "active_source_unavailable",
            "active_source_invalid",
            "recovery_failed",
        }:
            reason = cast(CanonicalAuthorityReason, error.reason)
        else:
            reason = "recovery_failed"
        raise CanonicalAuthorityStoppedV1(reason) from error
    if not _same_authority(authority, fresh):
        raise CanonicalAuthorityStoppedV1("recovery_failed")
    _validate_ocr_binding(authority, ocr)


def _input_fingerprint(
    *,
    work_id: str,
    source_id: str,
    source_sha256: str,
    ocr_run_id: str,
    ocr_manifest_sha256: str,
    ocr_input_fingerprint_sha256: str,
) -> str:
    value = {
        "canonicalizer_profile_sha256": _CANONICALIZER_PROFILE_SHA256,
        "ocr_input_fingerprint_sha256": ocr_input_fingerprint_sha256,
        "ocr_manifest_sha256": ocr_manifest_sha256,
        "ocr_run_id": ocr_run_id,
        "schema_version": "gezhi.literature_canonical_input.v1",
        "source_id": source_id,
        "source_sha256": source_sha256,
        "work_id": work_id,
    }
    return hashlib.sha256(_canonical_json_payload_bytes(value)).hexdigest()


def _build_bundle(
    authority: ActiveSourceAuthorityV1,
    ocr: CurrentOcrAssetV1,
) -> _BundleV1:
    try:
        assets = _load_ocr_manifest_assets(authority, ocr)
        if ocr.method == "native_text":
            native_asset = _required_ocr_asset(
                assets, "output/native_text.json"
            )
            value = _decode_json_document(
                _read_ocr_asset_bytes(
                    native_asset,
                    limit=_MAX_JSON_OR_TEXT_BYTES,
                )
            )
            if (
                value.get("work_id") != authority.work_id
                or value.get("source_id") != authority.source_id
            ):
                raise _CanonicalInvalidV1("Native OCR identity is invalid")
            bundle = _native_bundle(value)
            return _BundleV1(
                page_count=bundle.page_count,
                blocks=bundle.blocks,
                document_bytes=bundle.document_bytes,
                blocks_bytes=bundle.blocks_bytes,
                images=bundle.images,
                canonical_content_sha256=bundle.canonical_content_sha256,
                consumed_ocr_assets=(native_asset,),
            )
        leaf = ocr.run_directory / "output" / "mineru" / "source" / "ocr"
        asset_prefix = "output/mineru/source/ocr"
        content_asset = _required_ocr_asset(
            assets, f"{asset_prefix}/source_content_list_v2.json"
        )
        mineru_value = _decode_json_value(
            _read_ocr_asset_bytes(
                content_asset,
                limit=_MAX_JSON_OR_TEXT_BYTES,
            )
        )
        bundle = _mineru_bundle(
            mineru_value,
            leaf,
            ocr_assets=assets,
            asset_prefix=asset_prefix,
        )
        return _BundleV1(
            page_count=bundle.page_count,
            blocks=bundle.blocks,
            document_bytes=bundle.document_bytes,
            blocks_bytes=bundle.blocks_bytes,
            images=bundle.images,
            canonical_content_sha256=bundle.canonical_content_sha256,
            consumed_ocr_assets=(content_asset, *bundle.consumed_ocr_assets),
        )
    except _CanonicalizationInvalidV1 as error:
        raise CanonicalStageStoppedV1("canonicalization_failed") from error
    except _CanonicalInvalidV1 as error:
        raise CanonicalStageStoppedV1("asset_integrity_lost") from error


def _canonical_media_type(path: str) -> str:
    if path == "schema.json":
        return "application/schema+json"
    if path == "blocks.jsonl":
        return "application/x-ndjson"
    suffix = Path(path).suffix.casefold()
    return {
        ".json": "application/json",
        ".md": "text/markdown; charset=utf-8",
        ".jpg": "image/jpeg",
        ".png": "image/png",
    }.get(suffix, "application/octet-stream")


def _canonical_schema_version(path: str) -> str | None:
    if path == "blocks.jsonl":
        return "gezhi.evidence_block.v1"
    if path == "provenance.json":
        return "gezhi.literature_canonical_provenance.v1"
    return None


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
                    key=lambda value: value.encode("utf-8"),
                )
            )
            assets: list[dict[str, object]] = []
            image_count = 0
            image_total = 0
            for path in paths:
                parts = validate_relative_parts_v1(tuple(path.split("/")))
                with run.open_relative_file_v1(parts) as asset:
                    if path.startswith("images/"):
                        image_count += 1
                        image_total += asset.size
                        if (
                            _CANONICAL_IMAGE_PATH.fullmatch(path) is None
                            or asset.size > _MAX_IMAGE_BYTES
                            or image_count > _MAX_IMAGE_COUNT
                            or image_total > _MAX_IMAGE_TOTAL_BYTES
                        ):
                            raise _CanonicalInvalidV1(
                                "Canonical image inventory is invalid"
                            )
                    elif asset.size > _MAX_JSON_OR_TEXT_BYTES:
                        raise _CanonicalInvalidV1(
                            "Canonical text asset exceeds its limit"
                        )
                    entry: dict[str, object] = {
                        "byte_length": asset.size,
                        "media_type": _canonical_media_type(path),
                        "path": path,
                        "sha256": asset.sha256_v1(),
                    }
                schema = _canonical_schema_version(path)
                if schema is not None:
                    entry["schema_version"] = schema
                assets.append(entry)
            return assets
    except _CanonicalInvalidV1:
        raise
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        ValueError,
    ) as error:
        raise _CanonicalInvalidV1(
            "Canonical run inventory is invalid"
        ) from error


def _valid_decimal_text(value: object) -> bool:
    if type(value) is not str or re.fullmatch(
        r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$", value
    ) is None:
        return False
    try:
        decimal = Decimal(value)
    except InvalidOperation:
        return False
    if not decimal.is_finite():
        return False
    rendered = format(decimal, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered in {"-0", ""}:
        rendered = "0"
    return value == rendered


def _valid_persisted_bbox(value: object) -> bool:
    if (
        type(value) is not list
        or len(value) != 4
        or not all(_valid_decimal_text(item) for item in value)
    ):
        return False
    coordinates = [Decimal(cast(str, item)) for item in value]
    return (
        coordinates[2] > coordinates[0]
        and coordinates[3] > coordinates[1]
    )


def _parse_blocks(
    payload: bytes,
    *,
    page_count: int,
) -> tuple[dict[str, object], ...]:
    if not payload or len(payload) > _MAX_JSON_OR_TEXT_BYTES:
        raise _CanonicalInvalidV1("Canonical blocks are invalid")
    lines = payload.splitlines(keepends=True)
    if len(lines) > _MAX_BLOCK_COUNT or any(not line.endswith(b"\n") for line in lines):
        raise _CanonicalInvalidV1("Canonical blocks are invalid")
    identities: dict[str, str] = {}
    blocks: list[dict[str, object]] = []
    for order, line in enumerate(lines):
        if line == b"\n":
            raise _CanonicalInvalidV1("Canonical block is empty")
        try:
            value = json.loads(line)
            canonical = _canonical_json_file_bytes(value)
        except (
            json.JSONDecodeError,
            OverflowError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as error:
            raise _CanonicalInvalidV1("Canonical block JSON is invalid") from error
        if type(value) is not dict or line != canonical:
            raise _CanonicalInvalidV1("Canonical block bytes are invalid")
        block = cast(dict[str, object], value)
        if set(block) != {
            "bbox",
            "block_id",
            "heading_path",
            "image_path",
            "kind",
            "order",
            "page_index",
            "schema_version",
            "text",
        }:
            raise _CanonicalInvalidV1("Canonical block shape is invalid")
        bbox = block["bbox"]
        if bbox is not None and not _valid_persisted_bbox(bbox):
            raise _CanonicalInvalidV1("Canonical block bbox is invalid")
        headings = block["heading_path"]
        page_index = block["page_index"]
        image_path = block["image_path"]
        text = block["text"]
        if (
            type(block["block_id"]) is not str
            or _BLOCK_ID.fullmatch(cast(str, block["block_id"])) is None
            or type(block["order"]) is not int
            or block["order"] != order
            or block["kind"] not in _BLOCK_KINDS
            or type(text) is not str
            or not text
            or _normalize_text(text) != text
            or len(text.encode("utf-8")) > _MAX_BLOCK_TEXT_BYTES
            or type(headings) is not list
            or any(
                type(item) is not str or not item or _normalize_text(item) != item
                for item in headings
            )
            or type(page_index) is not int
            or not 0 <= page_index < page_count
            or (
                image_path is not None
                and (
                    type(image_path) is not str
                    or _CANONICAL_IMAGE_PATH.fullmatch(image_path) is None
                )
            )
            or block["schema_version"] != "gezhi.evidence_block.v1"
        ):
            raise _CanonicalInvalidV1("Canonical block is invalid")
        expected = _block_record(
            order=order,
            kind=cast(str, block["kind"]),
            text=text,
            heading_path=tuple(cast(list[str], headings)),
            page_index=page_index,
            bbox=cast(list[str] | None, bbox),
            image_path=cast(str | None, image_path),
            identities=identities,
        )
        if block != expected:
            raise _CanonicalInvalidV1("Canonical block identity is invalid")
        blocks.append(block)
    return tuple(blocks)


def _validate_method_block_semantics(
    method: OcrMethod,
    blocks: tuple[dict[str, object], ...],
) -> None:
    if method == "native_text":
        if any(
            block["kind"] != "paragraph"
            or block["bbox"] is not None
            or block["image_path"] is not None
            or block["heading_path"] != []
            for block in blocks
        ):
            raise _CanonicalInvalidV1(
                "Native Canonical block semantics are invalid"
            )
        return
    if any(block["bbox"] is None for block in blocks):
        raise _CanonicalInvalidV1(
            "MinerU Canonical block semantics are invalid"
        )


def _provenance_document(
    authority: ActiveSourceAuthorityV1,
    ocr: CurrentOcrAssetV1,
    *,
    run_id: str,
    bundle: _BundleV1,
) -> dict[str, object]:
    return {
        "block_count": len(bundle.blocks),
        "canonical_run_id": run_id,
        "canonicalizer_profile_sha256": _CANONICALIZER_PROFILE_SHA256,
        "image_count": len(bundle.images),
        "ocr_input_fingerprint_sha256": ocr.input_fingerprint_sha256,
        "ocr_manifest_sha256": ocr.manifest_sha256,
        "ocr_method": ocr.method,
        "ocr_run_id": ocr.run_id,
        "page_count": bundle.page_count,
        "schema_version": "gezhi.literature_canonical_provenance.v1",
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "work_id": authority.work_id,
    }


def _validate_provenance(
    value: dict[str, object],
    *,
    authority: ActiveSourceAuthorityV1,
    run_id: str,
) -> tuple[OcrMethod, str, str, str, int, int, int]:
    if set(value) != {
        "block_count",
        "canonical_run_id",
        "canonicalizer_profile_sha256",
        "image_count",
        "ocr_input_fingerprint_sha256",
        "ocr_manifest_sha256",
        "ocr_method",
        "ocr_run_id",
        "page_count",
        "schema_version",
        "source_id",
        "source_sha256",
        "work_id",
    }:
        raise _CanonicalInvalidV1("Canonical provenance shape is invalid")
    method = value["ocr_method"]
    ocr_run_id = value["ocr_run_id"]
    ocr_manifest = value["ocr_manifest_sha256"]
    ocr_fingerprint = value["ocr_input_fingerprint_sha256"]
    page_count = value["page_count"]
    block_count = value["block_count"]
    image_count = value["image_count"]
    if (
        value["canonical_run_id"] != run_id
        or value["canonicalizer_profile_sha256"]
        != _CANONICALIZER_PROFILE_SHA256
        or method not in {"native_text", "mineru_ocr"}
        or type(ocr_run_id) is not str
        or _OCR_RUN_ID.fullmatch(ocr_run_id) is None
        or type(ocr_manifest) is not str
        or _SHA256.fullmatch(ocr_manifest) is None
        or type(ocr_fingerprint) is not str
        or _SHA256.fullmatch(ocr_fingerprint) is None
        or type(page_count) is not int
        or not 1 <= page_count <= _MAX_PAGE_COUNT
        or type(block_count) is not int
        or not 1 <= block_count <= _MAX_BLOCK_COUNT
        or type(image_count) is not int
        or not 0 <= image_count <= _MAX_IMAGE_COUNT
        or value["schema_version"]
        != "gezhi.literature_canonical_provenance.v1"
        or value["source_id"] != authority.source_id
        or value["source_sha256"] != authority.source_sha256
        or value["work_id"] != authority.work_id
    ):
        raise _CanonicalInvalidV1("Canonical provenance is invalid")
    return (
        cast(OcrMethod, method),
        ocr_run_id,
        ocr_manifest,
        ocr_fingerprint,
        page_count,
        block_count,
        image_count,
    )


def _validate_image_assets(
    run_dir: Path,
    blocks: tuple[dict[str, object], ...],
) -> tuple[_ImageSourceV1, ...]:
    referenced = {
        cast(str, block["image_path"])
        for block in blocks
        if block["image_path"] is not None
    }
    images_dir = run_dir / "images"
    expected = {path.removeprefix("images/") for path in referenced}
    try:
        inventory = _entry_names(images_dir)
        with open_validated_data_root_v1(str(images_dir)) as root:
            observed = set(root.relative_file_paths_v1())
    except (
        CanonicalRecoveryUncertainV1,
        DataRootOpenErrorV1,
        OSError,
    ) as error:
        raise _CanonicalInvalidV1("Canonical images directory is invalid") from error
    if (
        set(inventory) != expected
        or len(inventory) != len(expected)
        or observed != expected
        or len(observed) > _MAX_IMAGE_COUNT
    ):
        raise _CanonicalInvalidV1("Canonical image inventory is invalid")
    images: list[_ImageSourceV1] = []
    total = 0
    casefolded: set[str] = set()
    for path in sorted(referenced, key=lambda value: value.encode("utf-8")):
        if (
            unicodedata.normalize("NFC", path) != path
            or _CANONICAL_IMAGE_PATH.fullmatch(path) is None
            or path.casefold() in casefolded
        ):
            raise _CanonicalInvalidV1("Canonical image path is invalid")
        casefolded.add(path.casefold())
        asset_path = run_dir / Path(path)
        payload = _read_safe_bytes(asset_path, limit=_MAX_IMAGE_BYTES)
        digest = hashlib.sha256(payload).hexdigest()
        suffix = Path(path).suffix
        if path != f"images/{digest}{suffix}":
            raise _CanonicalInvalidV1("Canonical image identity is invalid")
        if suffix == ".jpg":
            if not payload.startswith(b"\xff\xd8\xff"):
                raise _CanonicalInvalidV1("Canonical JPEG is invalid")
            media: Literal["image/jpeg", "image/png"] = "image/jpeg"
        else:
            if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
                raise _CanonicalInvalidV1("Canonical PNG is invalid")
            media = "image/png"
        total += len(payload)
        if total > _MAX_IMAGE_TOTAL_BYTES:
            raise _CanonicalInvalidV1("Canonical images exceed their limit")
        images.append(
            _ImageSourceV1(
                canonical_path=path,
                source_path=asset_path,
                sha256=digest,
                byte_length=len(payload),
                media_type=media,
            )
        )
    return tuple(images)


def _validate_referenced_ocr_manifest(
    authority: ActiveSourceAuthorityV1,
    *,
    ocr_run_id: str,
    ocr_manifest_sha256: str,
) -> None:
    try:
        payload = _read_safe_bytes(
            authority.source_directory
            / "ocr"
            / "runs"
            / ocr_run_id
            / "manifest.json",
            limit=_MAX_JSON_OR_TEXT_BYTES,
        )
    except _CanonicalInvalidV1 as error:
        raise _CanonicalInvalidV1(
            "Canonical provenance OCR run is unavailable"
        ) from error
    if hashlib.sha256(payload).hexdigest() != ocr_manifest_sha256:
        raise _CanonicalInvalidV1("Canonical provenance OCR manifest differs")


def _load_run(
    run_dir: Path,
    run_id: str,
    authority: ActiveSourceAuthorityV1,
) -> _ValidatedCanonicalRunV1:
    if _CANONICAL_RUN_ID.fullmatch(run_id) is None:
        raise _CanonicalInvalidV1("Canonical run ID is invalid")
    try:
        try:
            run_inventory = _entry_names(run_dir)
        except CanonicalRecoveryUncertainV1 as error:
            raise _CanonicalInvalidV1(
                "Canonical run namespace is invalid"
            ) from error
        expected_run_inventory = {
            "blocks.jsonl",
            "document.md",
            "images",
            "manifest.json",
            "provenance.json",
            "schema.json",
        }
        if (
            set(run_inventory) != expected_run_inventory
            or len(run_inventory) != len(expected_run_inventory)
        ):
            raise _CanonicalInvalidV1(
                "Canonical run namespace is invalid"
            )
        schema = _read_safe_bytes(
            run_dir / "schema.json", limit=_MAX_JSON_OR_TEXT_BYTES
        )
        if schema != _BLOCK_SCHEMA_BYTES:
            raise _CanonicalInvalidV1("Canonical schema snapshot differs")
        provenance, _provenance_bytes = _read_json_document(
            run_dir / "provenance.json"
        )
        (
            method,
            ocr_run_id,
            ocr_manifest,
            ocr_fingerprint,
            page_count,
            block_count,
            image_count,
        ) = _validate_provenance(
            provenance,
            authority=authority,
            run_id=run_id,
        )
        _validate_referenced_ocr_manifest(
            authority,
            ocr_run_id=ocr_run_id,
            ocr_manifest_sha256=ocr_manifest,
        )
        blocks_payload = _read_safe_bytes(
            run_dir / "blocks.jsonl", limit=_MAX_JSON_OR_TEXT_BYTES
        )
        blocks = _parse_blocks(blocks_payload, page_count=page_count)
        if len(blocks) != block_count:
            raise _CanonicalInvalidV1("Canonical block count differs")
        _validate_method_block_semantics(method, blocks)
        document = _read_safe_bytes(
            run_dir / "document.md", limit=_MAX_JSON_OR_TEXT_BYTES
        )
        if document != _document_bytes(page_count, blocks):
            raise _CanonicalInvalidV1("Canonical document view differs")
        images = _validate_image_assets(run_dir, blocks)
        if len(images) != image_count:
            raise _CanonicalInvalidV1("Canonical image count differs")
        content_identity = _content_identity(document, blocks_payload, images)
        fingerprint = _input_fingerprint(
            work_id=authority.work_id,
            source_id=authority.source_id,
            source_sha256=authority.source_sha256,
            ocr_run_id=ocr_run_id,
            ocr_manifest_sha256=ocr_manifest,
            ocr_input_fingerprint_sha256=ocr_fingerprint,
        )
        assets = _asset_entries(run_dir)
        manifest, manifest_bytes = _read_json_document(run_dir / "manifest.json")
        expected_manifest = {
            "assets": assets,
            "block_count": block_count,
            "canonical_content_sha256": content_identity,
            "canonicalizer_profile_sha256": _CANONICALIZER_PROFILE_SHA256,
            "image_count": image_count,
            "input_fingerprint_sha256": fingerprint,
            "ocr_manifest_sha256": ocr_manifest,
            "ocr_run_id": ocr_run_id,
            "page_count": page_count,
            "run_id": run_id,
            "schema_sha256": _BLOCK_SCHEMA_SHA256,
            "schema_version": "gezhi.literature_canonical_run_manifest.v1",
            "source_id": authority.source_id,
            "source_sha256": authority.source_sha256,
            "status": "succeeded",
            "work_id": authority.work_id,
        }
        if manifest != expected_manifest:
            raise _CanonicalInvalidV1("Canonical manifest is invalid")
    except _CanonicalInvalidV1:
        raise
    except _CanonicalizationInvalidV1 as error:
        raise _CanonicalInvalidV1("Canonical run content is invalid") from error
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
        OverflowError,
        RecursionError,
        UnicodeError,
        ValueError,
    ) as error:
        raise _CanonicalInvalidV1("Canonical run is invalid") from error
    return _ValidatedCanonicalRunV1(
        path=run_dir,
        run_id=run_id,
        input_fingerprint_sha256=fingerprint,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        canonical_content_sha256=content_identity,
    )


def _current_document(
    authority: ActiveSourceAuthorityV1,
    run: _ValidatedCanonicalRunV1,
) -> dict[str, object]:
    return {
        "canonical_content_sha256": run.canonical_content_sha256,
        "input_fingerprint_sha256": run.input_fingerprint_sha256,
        "manifest_sha256": run.manifest_sha256,
        "run_id": run.run_id,
        "schema_version": "gezhi.literature_canonical_current.v1",
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "work_id": authority.work_id,
    }


def _load_current_path(
    path: Path,
    *,
    runs: dict[str, _ValidatedCanonicalRunV1],
    authority: ActiveSourceAuthorityV1,
) -> tuple[_ValidatedCanonicalRunV1, bytes]:
    value, payload = _read_json_document(path)
    if set(value) != {
        "canonical_content_sha256",
        "input_fingerprint_sha256",
        "manifest_sha256",
        "run_id",
        "schema_version",
        "source_id",
        "source_sha256",
        "work_id",
    }:
        raise _CanonicalInvalidV1("Canonical current shape is invalid")
    run_id = value["run_id"]
    if (
        type(run_id) is not str
        or run_id not in runs
        or value["schema_version"] != "gezhi.literature_canonical_current.v1"
        or value["source_id"] != authority.source_id
        or value["source_sha256"] != authority.source_sha256
        or value["work_id"] != authority.work_id
    ):
        raise _CanonicalInvalidV1("Canonical current is invalid")
    run = runs[run_id]
    if value != _current_document(authority, run):
        raise _CanonicalInvalidV1("Canonical current binding is invalid")
    return run, payload


def _ensure_layout(
    authority: ActiveSourceAuthorityV1,
) -> tuple[Path, Path, Path]:
    canonical_dir = authority.source_directory / "canonical"
    runs_dir = canonical_dir / "runs"
    staging_dir = runs_dir / ".staging"
    _ensure_directory(canonical_dir)
    _ensure_directory(runs_dir)
    _ensure_directory(staging_dir)
    return canonical_dir, runs_dir, staging_dir


def _scan_runs(
    runs_dir: Path,
    staging_dir: Path,
    authority: ActiveSourceAuthorityV1,
) -> tuple[
    dict[str, _ValidatedCanonicalRunV1],
    tuple[_ValidatedCanonicalRunV1, ...],
    tuple[str, ...],
    tuple[str, ...],
    _CanonicalInvalidV1 | None,
]:
    formal_snapshot = tuple(
        sorted(_entry_names(runs_dir), key=lambda value: value.encode("utf-8"))
    )
    staging_snapshot = tuple(
        sorted(_entry_names(staging_dir), key=lambda value: value.encode("utf-8"))
    )
    formal: dict[str, _ValidatedCanonicalRunV1] = {}
    invalid_formal: _CanonicalInvalidV1 | None = None
    for name in formal_snapshot:
        if name == ".staging":
            continue
        if _CANONICAL_RUN_ID.fullmatch(name) is None:
            raise CanonicalRecoveryUncertainV1(
                "Canonical formal namespace is invalid"
            )
        try:
            formal[name] = _load_run(runs_dir / name, name, authority)
        except _CanonicalInvalidV1 as error:
            if invalid_formal is None:
                invalid_formal = error

    staged: list[_ValidatedCanonicalRunV1] = []
    replacements: list[str] = []
    invalid_staged: _CanonicalInvalidV1 | None = None
    for name in staging_snapshot:
        if _CURRENT_REPLACE_NAME.fullmatch(name) is not None:
            replacements.append(name)
            continue
        if _CANONICAL_RUN_ID.fullmatch(name) is None:
            raise CanonicalRecoveryUncertainV1(
                "Canonical staging namespace is invalid"
            )
        if _name_exists(runs_dir, name):
            raise CanonicalRecoveryUncertainV1(
                "Canonical staging target conflicts"
            )
        try:
            staged.append(_load_run(staging_dir / name, name, authority))
        except _CanonicalInvalidV1 as error:
            if invalid_staged is None:
                invalid_staged = error
            continue
    if tuple(
        sorted(_entry_names(runs_dir), key=lambda value: value.encode("utf-8"))
    ) != formal_snapshot or tuple(
        sorted(_entry_names(staging_dir), key=lambda value: value.encode("utf-8"))
    ) != staging_snapshot:
        raise CanonicalRecoveryUncertainV1(
            "Canonical recovery namespace changed"
        )
    if invalid_staged is not None:
        raise CanonicalRecoveryUncertainV1(
            "Canonical partial staging evidence is present"
        ) from invalid_staged
    if len(staged) > 1 or len(replacements) > 1:
        raise CanonicalRecoveryUncertainV1(
            "Canonical staging evidence is ambiguous"
        )
    return (
        formal,
        tuple(staged),
        tuple(replacements),
        staging_snapshot,
        invalid_formal,
    )


def _current_inventory(canonical_dir: Path) -> tuple[bool, str | None, tuple[str, ...]]:
    names = _entry_names(canonical_dir)
    if "runs" not in names:
        raise CanonicalRecoveryUncertainV1(
            "Canonical current namespace is incomplete"
        )
    has_current = names.count("current.json") == 1
    temporary_names = [
        name for name in names if _CURRENT_TEMP_NAME.fullmatch(name) is not None
    ]
    allowed = {"runs", "current.json", *temporary_names}
    if (
        any(name not in allowed for name in names)
        or len(temporary_names) > 1
        or names.count("runs") != 1
    ):
        raise CanonicalRecoveryUncertainV1(
            "Canonical current namespace is ambiguous"
        )
    return has_current, temporary_names[0] if temporary_names else None, tuple(
        sorted(names, key=lambda value: value.encode("utf-8"))
    )


def _write_current_staging(path: Path, payload: bytes) -> None:
    try:
        with (
            open_validated_data_root_v1(str(path.parent)),
            path.open("xb", buffering=0) as destination,
        ):
            _write_all(destination, payload)
    except FileExistsError as error:
        raise CanonicalRecoveryUncertainV1(
            "Canonical current staging target conflicts"
        ) from error
    except (DataRootOpenErrorV1, OSError) as error:
        raise CanonicalStageStoppedV1("commit_failed") from error
    try:
        if _read_safe_bytes(path, limit=len(payload)) != payload:
            raise OSError("Canonical current staging readback differs")
    except (_CanonicalInvalidV1, OSError) as error:
        raise CanonicalStageStoppedV1("commit_failed") from error


def _create_current_replace_copy(staging_dir: Path, payload: bytes) -> Path:
    replacement = staging_dir / f".current-replace.{uuid.uuid4().hex}.tmp"
    try:
        _write_current_staging(replacement, payload)
    except (CanonicalStageStoppedV1, CanonicalRecoveryUncertainV1) as error:
        raise CanonicalRecoveryUncertainV1(
            "Canonical current replacement evidence cannot be preserved"
        ) from error
    return replacement


def _replace_current_from_evidence(
    canonical_dir: Path,
    temporary: Path,
    replacement: Path,
    payload: bytes,
) -> None:
    try:
        os.replace(replacement, canonical_dir / "current.json")
        if _read_safe_bytes(
            canonical_dir / "current.json", limit=len(payload)
        ) != payload:
            raise OSError("Canonical current readback differs")
        has_current, temporary_name, _snapshot = _current_inventory(canonical_dir)
        if not has_current or temporary_name != temporary.name:
            raise OSError("Canonical current namespace differs")
        with open_validated_data_root_v1(str(canonical_dir)):
            temporary.unlink()
    except (
        _CanonicalInvalidV1,
        DataRootOpenErrorV1,
        OSError,
    ) as error:
        raise CanonicalRecoveryUncertainV1(
            "Canonical current replacement is uncertain"
        ) from error


def _publish_current(
    canonical_dir: Path,
    staging_dir: Path,
    authority: ActiveSourceAuthorityV1,
    ocr: CurrentOcrAssetV1,
    root: ValidatedDataRootV1,
    run: _ValidatedCanonicalRunV1,
) -> None:
    payload = _canonical_json_file_bytes(_current_document(authority, run))
    temporary = canonical_dir / f".current.json.{uuid.uuid4().hex}.tmp"
    if _entry_names(staging_dir):
        raise CanonicalRecoveryUncertainV1(
            "Canonical staging namespace is not empty"
        )
    _checkpoint(authority, ocr, root)
    _write_current_staging(temporary, payload)
    _has_current, temporary_name, snapshot = _current_inventory(canonical_dir)
    if temporary_name != temporary.name:
        raise CanonicalRecoveryUncertainV1(
            "Canonical current replacement evidence is ambiguous"
        )
    replacement = _create_current_replace_copy(staging_dir, payload)
    _checkpoint(authority, ocr, root)
    if _current_inventory(canonical_dir)[2] != snapshot:
        raise CanonicalRecoveryUncertainV1(
            "Canonical current namespace changed before replacement"
        )
    if tuple(_entry_names(staging_dir)) != (replacement.name,):
        raise CanonicalRecoveryUncertainV1(
            "Canonical staging namespace changed before replacement"
        )
    _replace_current_from_evidence(
        canonical_dir, temporary, replacement, payload
    )
    if _entry_names(staging_dir):
        raise CanonicalRecoveryUncertainV1(
            "Canonical staging namespace changed after replacement"
        )


def _load_or_recover_current(
    canonical_dir: Path,
    staging_dir: Path,
    *,
    runs: dict[str, _ValidatedCanonicalRunV1],
    expected_fingerprint: str,
    replacement_names: tuple[str, ...],
    staging_snapshot: tuple[str, ...],
    authority: ActiveSourceAuthorityV1,
    ocr: CurrentOcrAssetV1,
    root: ValidatedDataRootV1,
) -> tuple[_ValidatedCanonicalRunV1 | None, bool]:
    has_current, temporary_name, snapshot = _current_inventory(canonical_dir)
    if temporary_name is None:
        if replacement_names:
            raise CanonicalRecoveryUncertainV1(
                "Canonical current replacement evidence is orphaned"
            )
        if not has_current:
            if _current_inventory(canonical_dir)[2] != snapshot:
                raise CanonicalRecoveryUncertainV1(
                    "Canonical current namespace changed"
                )
            return None, False
        try:
            current, _payload = _load_current_path(
                canonical_dir / "current.json",
                runs=runs,
                authority=authority,
            )
        except _CanonicalInvalidV1 as error:
            raise CanonicalStageStoppedV1("asset_integrity_lost") from error
        if _current_inventory(canonical_dir)[2] != snapshot:
            raise CanonicalRecoveryUncertainV1(
                "Canonical current namespace changed"
            )
        return current, False

    temporary = canonical_dir / temporary_name
    try:
        temporary_run, temporary_bytes = _load_current_path(
            temporary,
            runs=runs,
            authority=authority,
        )
        if temporary_run.input_fingerprint_sha256 != expected_fingerprint:
            raise _CanonicalInvalidV1(
                "Canonical current staging belongs to another input"
            )
        if has_current:
            _load_current_path(
                canonical_dir / "current.json",
                runs=runs,
                authority=authority,
            )
    except _CanonicalInvalidV1 as error:
        raise CanonicalRecoveryUncertainV1(
            "Canonical current staging evidence is invalid"
        ) from error
    if _current_inventory(canonical_dir)[2] != snapshot:
        raise CanonicalRecoveryUncertainV1(
            "Canonical current namespace changed"
        )
    if replacement_names:
        replacement = staging_dir / replacement_names[0]
        try:
            if _read_safe_bytes(
                replacement, limit=len(temporary_bytes)
            ) != temporary_bytes:
                raise _CanonicalInvalidV1(
                    "Canonical replacement evidence differs"
                )
        except _CanonicalInvalidV1 as error:
            raise CanonicalRecoveryUncertainV1(
                "Canonical replacement evidence is invalid"
            ) from error
        replacement_snapshot = staging_snapshot
    else:
        replacement = _create_current_replace_copy(
            staging_dir, temporary_bytes
        )
        replacement_snapshot = tuple(
            sorted(
                (*staging_snapshot, replacement.name),
                key=lambda value: value.encode("utf-8"),
            )
        )
    _checkpoint(authority, ocr, root)
    if _current_inventory(canonical_dir)[2] != snapshot:
        raise CanonicalRecoveryUncertainV1(
            "Canonical current namespace changed"
        )
    if tuple(
        sorted(_entry_names(staging_dir), key=lambda value: value.encode("utf-8"))
    ) != replacement_snapshot:
        raise CanonicalRecoveryUncertainV1(
            "Canonical staging namespace changed"
        )
    try:
        if _read_safe_bytes(replacement, limit=len(temporary_bytes)) != temporary_bytes:
            raise _CanonicalInvalidV1(
                "Canonical replacement evidence differs"
            )
    except _CanonicalInvalidV1 as error:
        raise CanonicalRecoveryUncertainV1(
            "Canonical replacement evidence is invalid"
        ) from error
    _replace_current_from_evidence(
        canonical_dir,
        temporary,
        replacement,
        temporary_bytes,
    )
    expected_after = tuple(
        name for name in replacement_snapshot if name != replacement.name
    )
    if tuple(
        sorted(_entry_names(staging_dir), key=lambda value: value.encode("utf-8"))
    ) != expected_after:
        raise CanonicalRecoveryUncertainV1(
            "Canonical staging namespace changed after replacement"
        )
    return temporary_run, True


def _preflight_current_recovery_evidence(
    canonical_dir: Path,
    staging_dir: Path,
    *,
    runs: dict[str, _ValidatedCanonicalRunV1],
    expected_fingerprint: str,
    replacement_names: tuple[str, ...],
    staging_snapshot: tuple[str, ...],
    authority: ActiveSourceAuthorityV1,
) -> None:
    """Classify pending current recovery without mutating its evidence."""

    has_current, temporary_name, current_snapshot = _current_inventory(canonical_dir)
    if temporary_name is None:
        if replacement_names:
            raise CanonicalRecoveryUncertainV1(
                "Canonical current replacement evidence is orphaned"
            )
    else:
        temporary = canonical_dir / temporary_name
        try:
            temporary_run, temporary_bytes = _load_current_path(
                temporary,
                runs=runs,
                authority=authority,
            )
            if temporary_run.input_fingerprint_sha256 != expected_fingerprint:
                raise _CanonicalInvalidV1(
                    "Canonical current staging belongs to another input"
                )
            if has_current:
                _load_current_path(
                    canonical_dir / "current.json",
                    runs=runs,
                    authority=authority,
                )
            if replacement_names and _read_safe_bytes(
                staging_dir / replacement_names[0],
                limit=len(temporary_bytes),
            ) != temporary_bytes:
                raise _CanonicalInvalidV1(
                    "Canonical replacement evidence differs"
                )
        except _CanonicalInvalidV1 as error:
            raise CanonicalRecoveryUncertainV1(
                "Canonical current recovery evidence is invalid"
            ) from error

    if _current_inventory(canonical_dir)[2] != current_snapshot or tuple(
        sorted(_entry_names(staging_dir), key=lambda value: value.encode("utf-8"))
    ) != staging_snapshot:
        raise CanonicalRecoveryUncertainV1(
            "Canonical current recovery namespace changed"
        )


def _copy_image(source: _ImageSourceV1, destination: Path) -> None:
    digest = hashlib.sha256()
    length = 0
    try:
        with open_validated_local_file_v1(str(source.source_path)) as origin:
            if origin.size != source.byte_length or origin.size > _MAX_IMAGE_BYTES:
                raise OSError("Canonical image source length differs")
            try:
                with (
                    open_validated_data_root_v1(str(destination.parent)),
                    destination.open("xb", buffering=0) as target,
                ):
                    chunks = iter(origin.iter_verified_chunks_v1())
                    while True:
                        try:
                            chunk = next(chunks)
                        except StopIteration:
                            break
                        except (
                            DataRootLifecycleErrorV1,
                            DataRootOpenErrorV1,
                            OSError,
                        ) as error:
                            raise CanonicalStageStoppedV1(
                                "asset_integrity_lost"
                            ) from error
                        try:
                            _write_all(target, chunk)
                        except OSError as error:
                            raise CanonicalStageStoppedV1(
                                "commit_failed"
                            ) from error
                        digest.update(chunk)
                        length += len(chunk)
            except FileExistsError as error:
                raise CanonicalRecoveryUncertainV1(
                    "Canonical image target conflicts"
                ) from error
            except (CanonicalRecoveryUncertainV1, CanonicalStageStoppedV1):
                raise
            except (DataRootOpenErrorV1, OSError) as error:
                raise CanonicalStageStoppedV1("commit_failed") from error
    except (CanonicalRecoveryUncertainV1, CanonicalStageStoppedV1):
        raise
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
    ) as error:
        raise CanonicalStageStoppedV1("asset_integrity_lost") from error
    if length != source.byte_length or digest.hexdigest() != source.sha256:
        raise CanonicalStageStoppedV1("asset_integrity_lost")
    try:
        with open_validated_local_file_v1(str(destination)) as copied:
            copied_hash = copied.sha256_v1()
            copied_length = copied.size
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        OSError,
    ) as error:
        raise CanonicalStageStoppedV1("commit_failed") from error
    if copied_length != length or copied_hash != source.sha256:
        raise CanonicalStageStoppedV1("commit_failed")


def _create_stage(
    staging_dir: Path,
    runs_dir: Path,
    run_id: str,
    *,
    authority: ActiveSourceAuthorityV1,
    ocr: CurrentOcrAssetV1,
    root: ValidatedDataRootV1,
) -> Path:
    _checkpoint(authority, ocr, root)
    if _name_exists(staging_dir, run_id) or _name_exists(runs_dir, run_id):
        raise CanonicalRecoveryUncertainV1("Canonical run ID collides")
    stage = staging_dir / run_id
    try:
        with open_validated_data_root_v1(str(staging_dir)):
            stage.mkdir()
        with open_validated_data_root_v1(str(stage)):
            pass
    except FileExistsError as error:
        raise CanonicalRecoveryUncertainV1("Canonical run ID collides") from error
    except (DataRootOpenErrorV1, OSError) as error:
        raise CanonicalStageStoppedV1("commit_failed") from error
    return stage


def _publish_stage(
    stage: Path,
    authority: ActiveSourceAuthorityV1,
    ocr: CurrentOcrAssetV1,
    bundle: _BundleV1,
) -> _ValidatedCanonicalRunV1:
    images_dir = stage / "images"
    _ensure_directory(images_dir)
    _write_new_verified(stage / "document.md", bundle.document_bytes)
    _write_new_verified(stage / "blocks.jsonl", bundle.blocks_bytes)
    _write_new_verified(stage / "schema.json", _BLOCK_SCHEMA_BYTES)
    for image in bundle.images:
        _copy_image(
            image,
            stage / Path(image.canonical_path),
        )
    provenance = _provenance_document(
        authority,
        ocr,
        run_id=stage.name,
        bundle=bundle,
    )
    _write_new_verified(
        stage / "provenance.json",
        _canonical_json_file_bytes(provenance),
    )
    assets = _asset_entries(stage)
    manifest = {
        "assets": assets,
        "block_count": len(bundle.blocks),
        "canonical_content_sha256": bundle.canonical_content_sha256,
        "canonicalizer_profile_sha256": _CANONICALIZER_PROFILE_SHA256,
        "image_count": len(bundle.images),
        "input_fingerprint_sha256": _input_fingerprint(
            work_id=authority.work_id,
            source_id=authority.source_id,
            source_sha256=authority.source_sha256,
            ocr_run_id=ocr.run_id,
            ocr_manifest_sha256=ocr.manifest_sha256,
            ocr_input_fingerprint_sha256=ocr.input_fingerprint_sha256,
        ),
        "ocr_manifest_sha256": ocr.manifest_sha256,
        "ocr_run_id": ocr.run_id,
        "page_count": bundle.page_count,
        "run_id": stage.name,
        "schema_sha256": _BLOCK_SCHEMA_SHA256,
        "schema_version": "gezhi.literature_canonical_run_manifest.v1",
        "source_id": authority.source_id,
        "source_sha256": authority.source_sha256,
        "status": "succeeded",
        "work_id": authority.work_id,
    }
    _write_new_verified(
        stage / "manifest.json", _canonical_json_file_bytes(manifest)
    )
    try:
        return _load_run(stage, stage.name, authority)
    except _CanonicalInvalidV1 as error:
        raise CanonicalStageStoppedV1("commit_failed") from error


def _commit_stage(
    stage: Path,
    runs_dir: Path,
    authority: ActiveSourceAuthorityV1,
    ocr: CurrentOcrAssetV1,
    root: ValidatedDataRootV1,
    *,
    consumed_ocr_assets: tuple[_OcrManifestAssetV1, ...] = (),
) -> _ValidatedCanonicalRunV1:
    try:
        expected = _load_run(stage, stage.name, authority)
    except _CanonicalInvalidV1 as error:
        raise CanonicalStageStoppedV1("commit_failed") from error
    _checkpoint(authority, ocr, root)
    _verify_ocr_assets(consumed_ocr_assets)
    _checkpoint(authority, ocr, root)
    if _name_exists(runs_dir, stage.name):
        raise CanonicalRecoveryUncertainV1(
            "Canonical run target conflicts"
        )
    target = runs_dir / stage.name
    try:
        os.rename(stage, target)
    except OSError as error:
        raise CanonicalRecoveryUncertainV1(
            "Canonical run commit is uncertain"
        ) from error
    try:
        committed = _load_run(target, stage.name, authority)
    except _CanonicalInvalidV1 as error:
        raise CanonicalRecoveryUncertainV1(
            "Canonical committed run cannot be proven"
        ) from error
    if committed != _ValidatedCanonicalRunV1(
        path=target,
        run_id=expected.run_id,
        input_fingerprint_sha256=expected.input_fingerprint_sha256,
        manifest_sha256=expected.manifest_sha256,
        canonical_content_sha256=expected.canonical_content_sha256,
    ):
        raise CanonicalRecoveryUncertainV1(
            "Canonical committed run differs"
        )
    return committed


def _as_current(run: _ValidatedCanonicalRunV1) -> CurrentCanonicalAssetV1:
    return CurrentCanonicalAssetV1(
        run_id=run.run_id,
        run_directory=run.path,
        input_fingerprint_sha256=run.input_fingerprint_sha256,
        manifest_sha256=run.manifest_sha256,
        canonical_content_sha256=run.canonical_content_sha256,
    )


def advance_canonicalize_v1(
    authority: ActiveSourceAuthorityV1,
    ocr: CurrentOcrAssetV1,
    *,
    root: ValidatedDataRootV1,
) -> CanonicalAdvanceV1:
    """Publish or reuse the Canonical Reading Asset for one OCR success."""

    _checkpoint(authority, ocr, root)
    canonical_dir, runs_dir, staging_dir = _ensure_layout(authority)
    fingerprint = _input_fingerprint(
        work_id=authority.work_id,
        source_id=authority.source_id,
        source_sha256=authority.source_sha256,
        ocr_run_id=ocr.run_id,
        ocr_manifest_sha256=ocr.manifest_sha256,
        ocr_input_fingerprint_sha256=ocr.input_fingerprint_sha256,
    )
    (
        formal,
        staged,
        replacement_names,
        staging_snapshot,
        invalid_formal,
    ) = _scan_runs(runs_dir, staging_dir, authority)
    if staged and staged[0].input_fingerprint_sha256 != fingerprint:
        raise CanonicalRecoveryUncertainV1(
            "Canonical staged success belongs to another input"
        )
    matching = [
        run
        for run in (*formal.values(), *staged)
        if run.input_fingerprint_sha256 == fingerprint
    ]
    if len(matching) > 1:
        raise CanonicalRecoveryUncertainV1(
            "Canonical input has multiple success runs"
        )
    if invalid_formal is not None:
        _preflight_current_recovery_evidence(
            canonical_dir,
            staging_dir,
            runs=formal,
            expected_fingerprint=fingerprint,
            replacement_names=replacement_names,
            staging_snapshot=staging_snapshot,
            authority=authority,
        )
        raise CanonicalStageStoppedV1(
            "asset_integrity_lost"
        ) from invalid_formal
    matching_bundle: _BundleV1 | None = None
    if len(matching) == 1:
        matching_bundle = _build_bundle(authority, ocr)
        if (
            matching_bundle.canonical_content_sha256
            != matching[0].canonical_content_sha256
        ):
            raise CanonicalRecoveryUncertainV1(
                "Canonical success differs from current OCR input"
            )
        _checkpoint(authority, ocr, root)
        _verify_ocr_assets(matching_bundle.consumed_ocr_assets)
        _checkpoint(authority, ocr, root)
    current, current_repaired = _load_or_recover_current(
        canonical_dir,
        staging_dir,
        runs=formal,
        expected_fingerprint=fingerprint,
        replacement_names=replacement_names,
        staging_snapshot=staging_snapshot,
        authority=authority,
        ocr=ocr,
        root=root,
    )
    if current is not None and current.input_fingerprint_sha256 == fingerprint:
        if len(matching) != 1 or matching[0].run_id != current.run_id:
            raise CanonicalRecoveryUncertainV1(
                "Canonical current success is not unique"
            )
        return CanonicalAdvanceV1(
            advanced=current_repaired,
            current=_as_current(current),
        )
    if len(matching) == 1:
        recovered = matching[0]
        if recovered.path.parent == staging_dir:
            if matching_bundle is None:
                raise RuntimeError("Canonical matching bundle is unavailable")
            recovered = _commit_stage(
                recovered.path,
                runs_dir,
                authority,
                ocr,
                root,
                consumed_ocr_assets=matching_bundle.consumed_ocr_assets,
            )
            formal[recovered.run_id] = recovered
        _publish_current(
            canonical_dir,
            staging_dir,
            authority,
            ocr,
            root,
            recovered,
        )
        return CanonicalAdvanceV1(advanced=True, current=_as_current(recovered))

    bundle = _build_bundle(authority, ocr)
    run_id = "canrun_" + str(uuid.uuid4())
    stage = _create_stage(
        staging_dir,
        runs_dir,
        run_id,
        authority=authority,
        ocr=ocr,
        root=root,
    )
    _publish_stage(stage, authority, ocr, bundle)
    committed = _commit_stage(
        stage,
        runs_dir,
        authority,
        ocr,
        root,
        consumed_ocr_assets=bundle.consumed_ocr_assets,
    )
    _publish_current(
        canonical_dir,
        staging_dir,
        authority,
        ocr,
        root,
        committed,
    )
    return CanonicalAdvanceV1(advanced=True, current=_as_current(committed))
