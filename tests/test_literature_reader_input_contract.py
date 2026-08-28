from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from gezhi._literature_canonical import CurrentCanonicalAssetV1
from gezhi._literature_intake import ActiveSourceAuthorityV1
from gezhi._literature_reader import ReaderStageStoppedV1, _reader_input

_WORK_ID = "wrk_12345678-1234-4abc-8abc-1234567890ab"
_SOURCE_SHA256 = "a" * 64
_SOURCE_ID = "src_" + _SOURCE_SHA256[:24]
_CANONICAL_RUN_ID = "canrun_12345678-1234-4abc-8abc-1234567890ab"


@pytest.fixture
def reader_input_base() -> Iterator[Path]:
    container = Path(r"E:\Gezhi\data")
    container.mkdir(parents=True, exist_ok=True)
    base = container / ("i" + uuid.uuid4().hex[:7])
    base.mkdir()
    try:
        yield base
    finally:
        resolved = base.resolve(strict=True)
        assert resolved.parent == container.resolve(strict=True)
        assert resolved.name == base.name
        shutil.rmtree(resolved)


def _canonical_bytes(value: object) -> bytes:
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


def _reader_fixture(
    base: Path,
) -> tuple[ActiveSourceAuthorityV1, CurrentCanonicalAssetV1, Path]:
    work_directory = base / "work"
    source_directory = work_directory / "sources" / _SOURCE_ID
    run_directory = source_directory / "canonical" / "runs" / _CANONICAL_RUN_ID
    revisions = work_directory / "identity" / "revisions"
    revisions.mkdir(parents=True)
    run_directory.mkdir(parents=True)

    revision_bytes = _canonical_bytes(
        {
            "arxiv_ids": [],
            "citations": [],
            "dois": [],
            "schema_version": "gezhi.literature_work_identity.v1",
            "work_id": _WORK_ID,
        }
    )
    identity_sha256 = hashlib.sha256(revision_bytes).hexdigest()
    revision_name = f"idrev_{identity_sha256[:24]}.json"
    (revisions / revision_name).write_bytes(revision_bytes)
    (work_directory / "identity" / "current.json").write_bytes(
        _canonical_bytes(
            {
                "identity_sha256": identity_sha256,
                "revision": revision_name,
                "schema_version": "gezhi.literature_work_identity_current.v1",
                "work_id": _WORK_ID,
            }
        )
    )

    authority = ActiveSourceAuthorityV1(
        work_id=_WORK_ID,
        source_id=_SOURCE_ID,
        source_sha256=_SOURCE_SHA256,
        source_byte_length=1,
        source_manifest_sha256="b" * 64,
        work_directory=work_directory,
        source_directory=source_directory,
        original_pdf_path=source_directory / "original.pdf",
        ingest_identity_ready=True,
    )
    canonical = CurrentCanonicalAssetV1(
        run_id=_CANONICAL_RUN_ID,
        run_directory=run_directory,
        input_fingerprint_sha256="c" * 64,
        manifest_sha256="d" * 64,
        canonical_content_sha256="e" * 64,
    )
    return authority, canonical, run_directory / "blocks.jsonl"


def _block(
    *,
    text: object = "evidence",
    order: object = 0,
    page_index: object = 0,
    heading_path: object = None,
) -> dict[str, object]:
    return {
        "block_id": "blk_" + "f" * 24,
        "heading_path": [] if heading_path is None else heading_path,
        "kind": "paragraph",
        "order": order,
        "page_index": page_index,
        "text": text,
    }


def test_reader_input_normalizes_text_and_accepts_unknown_page(
    reader_input_base: Path,
) -> None:
    authority, canonical, blocks_path = _reader_fixture(reader_input_base)
    blocks_path.write_bytes(
        _canonical_bytes(
            _block(
                text="Cafe\u0301\r\nline\rend",
                page_index=None,
                heading_path=["Cafe\u0301\r\nSection"],
            )
        )
    )

    input_bytes, evidence = _reader_input(authority, canonical)
    records = [json.loads(line) for line in input_bytes.splitlines()]

    assert records[1]["text"] == "Café\nline\nend"
    assert records[1]["heading_path"] == ["Café\nSection"]
    assert records[1]["page_index"] is None
    assert evidence == {"blk_" + "f" * 24: "Café\nline\nend"}


@pytest.mark.parametrize(
    ("field", "value"),
    [("order", False), ("page_index", False), ("text", "")],
)
def test_reader_input_rejects_invalid_block_scalars(
    reader_input_base: Path,
    field: str,
    value: object,
) -> None:
    authority, canonical, blocks_path = _reader_fixture(reader_input_base)
    document = _block()
    document[field] = value
    blocks_path.write_bytes(_canonical_bytes(document))

    with pytest.raises(ReaderStageStoppedV1) as stopped:
        _reader_input(authority, canonical)

    assert stopped.value.outcome == "failed"
    assert stopped.value.reason == "reader_input_invalid"


def test_reader_input_uses_final_utf8_bytes_for_the_inclusive_limit(
    reader_input_base: Path,
) -> None:
    authority, canonical, blocks_path = _reader_fixture(reader_input_base)
    blocks_path.write_bytes(_canonical_bytes(_block(text="x")))
    baseline, _evidence = _reader_input(authority, canonical)
    exact_text_length = 524_288 - (len(baseline) - 1)

    blocks_path.write_bytes(
        _canonical_bytes(_block(text="x" * exact_text_length))
    )
    exact, _evidence = _reader_input(authority, canonical)
    assert len(exact) == 524_288

    blocks_path.write_bytes(
        _canonical_bytes(_block(text="x" * (exact_text_length + 1)))
    )
    with pytest.raises(ReaderStageStoppedV1) as stopped:
        _reader_input(authority, canonical)

    assert stopped.value.outcome == "blocked"
    assert stopped.value.reason == "reader_input_too_large"
