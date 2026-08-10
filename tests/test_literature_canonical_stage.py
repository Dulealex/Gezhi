from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from gezhi import _literature_canonical as canonical
from gezhi import _windows_data_root as windows_root


def _native_document(*texts: str) -> dict[str, object]:
    return {
        "pages": [
            {"page_index": index, "text": text}
            for index, text in enumerate(texts)
        ],
        "schema_version": "gezhi.literature_native_text.v1",
        "source_id": "src_" + "a" * 24,
        "work_id": "wrk_123e4567-e89b-42d3-a456-426614174000",
    }


def test_native_normalization_has_stable_blocks_and_content_identity() -> None:
    decomposed = _native_document("  Cafe\u0301\r\nline\r\n\r\nnext  ")
    composed = _native_document("Caf\u00e9\nline\n\nnext")

    first = canonical._native_bundle(decomposed)
    second = canonical._native_bundle(composed)

    assert first.document_bytes == second.document_bytes
    assert first.blocks_bytes == second.blocks_bytes
    assert first.canonical_content_sha256 == second.canonical_content_sha256
    blocks = [json.loads(line) for line in first.blocks_bytes.splitlines()]
    assert [block["text"] for block in blocks] == ["Caf\u00e9\nline", "next"]
    assert [block["order"] for block in blocks] == [0, 1]
    identity = {
        "blocks_sha256": hashlib.sha256(first.blocks_bytes).hexdigest(),
        "document_sha256": hashlib.sha256(first.document_bytes).hexdigest(),
        "images": [],
        "schema_version": "gezhi.canonical_content.v1",
    }
    expected = hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert first.canonical_content_sha256 == expected


def test_content_identity_ignores_source_metadata_orders_images_and_detects_bytes(
    tmp_path: Path,
) -> None:
    first_bytes = b"\x89PNG\r\n\x1a\nfirst"
    second_bytes = b"\xff\xd8\xffsecond"
    first_hash = hashlib.sha256(first_bytes).hexdigest()
    second_hash = hashlib.sha256(second_bytes).hexdigest()
    first = canonical._ImageSourceV1(
        canonical_path=f"images/{first_hash}.png",
        source_path=tmp_path / "provider-a.png",
        sha256=first_hash,
        byte_length=len(first_bytes),
        media_type="image/png",
    )
    same_content_other_source = canonical._ImageSourceV1(
        canonical_path=first.canonical_path,
        source_path=tmp_path / "provider-b.png",
        sha256=first_hash,
        byte_length=len(first_bytes),
        media_type="image/png",
    )
    second = canonical._ImageSourceV1(
        canonical_path=f"images/{second_hash}.jpg",
        source_path=tmp_path / "provider-c.jpg",
        sha256=second_hash,
        byte_length=len(second_bytes),
        media_type="image/jpeg",
    )
    base = canonical._content_identity(b"document\n", b"blocks\n", (first, second))

    assert canonical._content_identity(
        b"document\n",
        b"blocks\n",
        (second, same_content_other_source),
    ) == base
    assert canonical._content_identity(
        b"changed\n", b"blocks\n", (first, second)
    ) != base
    assert canonical._content_identity(
        b"document\n", b"changed\n", (first, second)
    ) != base
    changed_hash = hashlib.sha256(first_bytes + b"changed").hexdigest()
    changed_image = canonical._ImageSourceV1(
        canonical_path=f"images/{changed_hash}.png",
        source_path=tmp_path / "provider-a.png",
        sha256=changed_hash,
        byte_length=len(first_bytes) + len(b"changed"),
        media_type="image/png",
    )
    assert canonical._content_identity(
        b"document\n", b"blocks\n", (changed_image, second)
    ) != base


def test_native_normalizes_each_paragraph_after_deterministic_splitting() -> None:
    bundle = canonical._native_bundle(
        _native_document("Alpha\n\n  Beta  \n\n\tGamma")
    )

    blocks = [json.loads(line) for line in bundle.blocks_bytes.splitlines()]

    assert [block["text"] for block in blocks] == ["Alpha", "Beta", "Gamma"]


def test_blocks_encoding_stops_at_the_first_decisive_file_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocks: tuple[dict[str, object], ...] = (
        {"order": 0},
        {"order": 1},
        {"order": 2},
    )
    observed: list[int] = []
    monkeypatch.setattr(canonical, "_MAX_JSON_OR_TEXT_BYTES", 10)

    def encode(value: object) -> Iterator[bytes]:
        assert isinstance(value, dict)
        observed.append(int(value["order"]))
        yield b"123456"

    monkeypatch.setattr(canonical, "_canonical_json_payload_chunks", encode)

    with pytest.raises(canonical._CanonicalizationInvalidV1):
        canonical._blocks_bytes(blocks)

    assert observed == [0, 1]


@pytest.mark.parametrize("text", ["safe\x00unsafe", "safe\ud800unsafe"])
def test_native_normalization_rejects_unrepairable_unicode(text: str) -> None:
    with pytest.raises(canonical._CanonicalizationInvalidV1):
        canonical._native_bundle(_native_document(text))


def test_native_preserves_empty_pages_at_the_page_limit() -> None:
    pages = ["one evidence block", *([""] * (canonical._MAX_PAGE_COUNT - 1))]

    bundle = canonical._native_bundle(_native_document(*pages))

    assert bundle.page_count == canonical._MAX_PAGE_COUNT
    assert bundle.document_bytes.endswith(
        f"<!-- gezhi-page:{canonical._MAX_PAGE_COUNT - 1} -->\n".encode()
    )
    with pytest.raises(canonical._CanonicalizationInvalidV1):
        canonical._native_bundle(_native_document(*pages, ""))


def test_native_enforces_block_and_block_text_limits_without_truncation() -> None:
    exact_blocks = "\n\n".join(
        f"paragraph-{index}" for index in range(canonical._MAX_BLOCK_COUNT)
    )
    bundle = canonical._native_bundle(_native_document(exact_blocks))
    assert len(bundle.blocks) == canonical._MAX_BLOCK_COUNT

    too_many = exact_blocks + "\n\nover-limit"
    with pytest.raises(canonical._CanonicalizationInvalidV1):
        canonical._native_bundle(_native_document(too_many))

    exact_text = "x" * canonical._MAX_BLOCK_TEXT_BYTES
    assert canonical._native_bundle(_native_document(exact_text)).blocks[0][
        "text"
    ] == exact_text
    with pytest.raises(canonical._CanonicalizationInvalidV1):
        canonical._native_bundle(_native_document(exact_text + "x"))


def test_native_rejects_an_entirely_empty_document() -> None:
    with pytest.raises(canonical._CanonicalizationInvalidV1):
        canonical._native_bundle(_native_document(" \r\n", "\t"))


def test_mineru_v2_preserves_empty_pages_structure_and_referenced_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    leaf = tmp_path / "source" / "ocr"
    images = leaf / "images"
    images.mkdir(parents=True)
    image_bytes = b"\x89PNG\r\n\x1a\ncanonical-image"
    (images / "table.png").write_bytes(image_bytes)
    pages = [
        [],
        [
            {
                "bbox": [10, 20, 200, 40],
                "content": {
                    "level": 1,
                    "title_content": [{"content": "  Heading  ", "type": "text"}],
                },
                "type": "title",
            },
            {
                "bbox": [10, 50, 200, 80],
                "content": {
                    "paragraph_content": [
                        {"content": "Mixed ", "type": "text"},
                        {"content": "text", "type": "md"},
                    ]
                },
                "type": "paragraph",
            },
            {
                "bbox": [10, 90, 200, 130],
                "content": {
                    "list_items": [
                        {
                            "item_content": [
                                {"content": "First", "type": "text"}
                            ],
                            "item_type": "text",
                        },
                        {
                            "item_content": [
                                {"content": "Second", "type": "text"}
                            ],
                            "item_type": "text",
                        },
                    ],
                    "list_type": "text_list",
                },
                "type": "list",
            },
            {
                "bbox": [10, 140, 300, 260],
                "content": {
                    "html": "<table><tr><td>42</td></tr></table>",
                    "image_source": {"path": "images/table.png"},
                    "table_caption": [
                        {"content": "Results", "type": "text"}
                    ],
                    "table_footnote": [],
                    "table_nest_level": 1,
                    "table_type": "simple_table",
                },
                "type": "table",
            },
        ],
    ]

    bundle = canonical._mineru_bundle(pages, leaf)

    blocks = [json.loads(line) for line in bundle.blocks_bytes.splitlines()]
    assert [block["kind"] for block in blocks] == [
        "heading",
        "paragraph",
        "list_item",
        "list_item",
        "figure_caption",
        "table",
    ]
    assert {block["page_index"] for block in blocks} == {1}
    assert blocks[1]["heading_path"] == ["Heading"]
    image_path = "images/" + hashlib.sha256(image_bytes).hexdigest() + ".png"
    assert blocks[-1]["image_path"] == image_path
    assert blocks[-2]["image_path"] == image_path
    assert [image.canonical_path for image in bundle.images] == [image_path]
    assert bundle.document_bytes.startswith(b"<!-- gezhi-page:0 -->\n\n")


def test_mineru_same_level_heading_replaces_the_previous_heading() -> None:
    pages = [
        [
            {
                "bbox": [10, 10, 100, 20],
                "content": {
                    "level": 2,
                    "title_content": [{"content": "First", "type": "text"}],
                },
                "type": "title",
            },
            {
                "bbox": [10, 30, 100, 40],
                "content": {
                    "level": 2,
                    "title_content": [{"content": "Second", "type": "text"}],
                },
                "type": "title",
            },
            {
                "bbox": [10, 50, 100, 70],
                "content": {
                    "paragraph_content": [
                        {"content": "Body", "type": "text"}
                    ]
                },
                "type": "paragraph",
            },
        ]
    ]

    bundle = canonical._mineru_bundle(pages, Path("unused"))
    blocks = [json.loads(line) for line in bundle.blocks_bytes.splitlines()]

    assert [block["heading_path"] for block in blocks] == [
        [],
        [],
        ["Second"],
    ]


def test_mineru_deduplicates_same_image_bytes_from_different_provider_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    leaf = tmp_path / "source" / "ocr"
    images = leaf / "images"
    images.mkdir(parents=True)
    image_bytes = b"\x89PNG\r\n\x1a\nsame-image"
    (images / "first.png").write_bytes(image_bytes)
    (images / "second.png").write_bytes(image_bytes)

    def table(path: str, caption: str, top: int) -> dict[str, object]:
        return {
            "bbox": [10, top, 200, top + 40],
            "content": {
                "html": f"<table><tr><td>{caption}</td></tr></table>",
                "image_source": {"path": path},
                "table_caption": [{"content": caption, "type": "text"}],
                "table_footnote": [],
                "table_nest_level": 1,
                "table_type": "simple_table",
            },
            "type": "table",
        }

    bundle = canonical._mineru_bundle(
        [[table("images/first.png", "First", 10), table("images/second.png", "Second", 60)]],
        leaf,
    )
    blocks = [json.loads(line) for line in bundle.blocks_bytes.splitlines()]

    assert len(bundle.images) == 1
    assert len({block["image_path"] for block in blocks}) == 1


def test_mineru_stops_reading_at_the_first_decisive_image_count_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    monkeypatch.setattr(canonical, "_MAX_IMAGE_COUNT", 1)
    leaf = tmp_path / "source" / "ocr"
    images = leaf / "images"
    images.mkdir(parents=True)
    for name in ("first.png", "second.png", "third.png"):
        (images / name).write_bytes(
            b"\x89PNG\r\n\x1a\n" + name.encode("ascii")
        )
    observed: list[str] = []
    real_image_source = canonical._mineru_image_source

    def observe_image_source(
        leaf_path: Path,
        value: object,
        cache: dict[str, canonical._ImageSourceV1],
        *,
        ocr_assets: dict[str, canonical._OcrManifestAssetV1] | None = None,
        asset_prefix: str = "",
    ) -> canonical._ImageSourceV1:
        assert isinstance(value, dict)
        observed.append(str(value["path"]))
        return real_image_source(
            leaf_path,
            value,
            cache,
            ocr_assets=ocr_assets,
            asset_prefix=asset_prefix,
        )

    monkeypatch.setattr(canonical, "_mineru_image_source", observe_image_source)

    def table(name: str, top: int) -> dict[str, object]:
        return {
            "bbox": [10, top, 200, top + 20],
            "content": {
                "html": f"<table><tr><td>{name}</td></tr></table>",
                "image_source": {"path": f"images/{name}.png"},
                "table_caption": [{"content": name, "type": "text"}],
                "table_footnote": [],
                "table_nest_level": 1,
                "table_type": "simple_table",
            },
            "type": "table",
        }

    with pytest.raises(canonical._CanonicalizationInvalidV1):
        canonical._mineru_bundle(
            [[table("first", 10), table("second", 40), table("third", 70)]],
            leaf,
        )

    assert observed == ["images/first.png", "images/second.png"]


@pytest.mark.parametrize(
    "bbox",
    [
        ["10", "0", "1", "1"],
        ["0", "10", "1", "10"],
    ],
)
def test_persisted_bbox_must_keep_positive_geometry(bbox: list[str]) -> None:
    identity = {
        "bbox": bbox,
        "heading_path": [],
        "image_path": None,
        "kind": "paragraph",
        "order": 0,
        "page_index": 0,
        "schema_version": "gezhi.evidence_block_identity.v1",
        "text": "Evidence",
    }
    full_hash = hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    block = {
        **identity,
        "block_id": "blk_" + full_hash[:24],
        "schema_version": "gezhi.evidence_block.v1",
    }
    payload = (
        json.dumps(
            block,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )

    with pytest.raises(canonical._CanonicalInvalidV1):
        canonical._parse_blocks(payload, page_count=1)


def test_persisted_mineru_block_must_have_a_bbox() -> None:
    block = canonical._block_record(
        order=0,
        kind="paragraph",
        text="Evidence",
        heading_path=(),
        page_index=0,
        bbox=None,
        image_path=None,
        identities={},
    )

    with pytest.raises(canonical._CanonicalInvalidV1):
        canonical._validate_method_block_semantics("mineru_ocr", (block,))
