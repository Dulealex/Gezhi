from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from gezhi._codex_child_process import (
    LITERATURE_EVENTS_CAPTURE_CAP_V1,
    LITERATURE_FINAL_CAPTURE_CAP_V1,
)
from gezhi._literature_canonical import CurrentCanonicalAssetV1
from gezhi._literature_intake import ActiveSourceAuthorityV1
from gezhi._literature_reader import (
    LiteratureReaderOutputV1,
    ReaderStageStoppedV1,
    _attempt_documents_from_run_v1,
    _reader_input,
    _source_environment,
    _validate_evidence,
)

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


def _attempt_run(base: Path, name: str) -> Path:
    run = base / name
    (run / "attempts").mkdir(parents=True)
    return run


def _write_recovery_attempt(
    run: Path,
    ordinal: int,
    *,
    failure_class: str | None,
    exit_code: int | None,
    events: bytes = b'{"type":"thread.started"}\n',
    final: bytes | None = None,
    token_value: int | None = None,
) -> None:
    attempt = run / "attempts" / f"{ordinal:02d}"
    attempt.mkdir()
    (attempt / "attempt.json").write_bytes(
        _canonical_bytes(
            {
                "attempt_ordinal": ordinal,
                "cached_input_tokens": token_value,
                "elapsed_ms": 25,
                "exit_code": exit_code,
                "failure_class": failure_class,
                "finished_at": "2026-08-28T12:00:01.000Z",
                "input_tokens": token_value,
                "output_tokens": token_value,
                "reasoning_output_tokens": token_value,
                "resource_ledger_count": 0,
                "schema_version": "gezhi.literature_codex_attempt.v1",
                "started_at": "2026-08-28T12:00:00.000Z",
                "usage_unavailable": token_value is None,
            }
        )
    )
    (attempt / "events.jsonl").write_bytes(events)
    if final is not None:
        (attempt / "final_message.txt").write_bytes(final)


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


def test_reader_source_term_must_occur_inside_one_cited_evidence_block() -> None:
    first_id = "blk_" + "a" * 24
    second_id = "blk_" + "b" * 24
    synopsis = {
        "evidence_block_ids": [first_id],
        "risk_flags": [],
        "source_terms": ["alpha"],
        "support_kind": "direct",
        "text": "概述。",
    }
    crossing = {
        "evidence_block_ids": [first_id, second_id],
        "risk_flags": [],
        "source_terms": ["alpha\nbeta"],
        "support_kind": "direct",
        "text": "该术语不能跨证据块边界拼接。",
    }
    output = LiteratureReaderOutputV1.model_validate(
        {
            "candidate_drafts": [],
            "reading_result": {
                "findings": [crossing],
                "limitations": [],
                "methods": [],
                "open_questions": [],
                "relevance": [],
                "research_problems": [],
                "study_descriptors": {
                    "datasets": [],
                    "experiments": [],
                    "metrics": [],
                    "objects": [],
                },
                "synopsis": synopsis,
            },
            "schema_version": "gezhi.literature_reader_output.v1",
        },
        strict=True,
    )

    with pytest.raises(ReaderStageStoppedV1) as stopped:
        _validate_evidence(
            output,
            {first_id: "alpha", second_id: "beta"},
        )

    assert stopped.value.outcome == "failed"
    assert stopped.value.reason == "reader_output_invalid"


@pytest.mark.parametrize(
    "group",
    ["synopsis", "research_problems", "methods", "findings", "limitations"],
)
def test_reading_result_allows_interpretive_evidence_support(group: str) -> None:
    block_id = "blk_" + "a" * 24
    direct = {
        "evidence_block_ids": [block_id],
        "risk_flags": [],
        "source_terms": ["evidence"],
        "support_kind": "direct",
        "text": "直接陈述。",
    }
    interpretive = {
        **direct,
        "support_kind": "interpretive",
        "text": "解释性陈述。",
    }
    reading_result: dict[str, object] = {
        "findings": [],
        "limitations": [],
        "methods": [],
        "open_questions": [],
        "relevance": [],
        "research_problems": [],
        "study_descriptors": {
            "datasets": [],
            "experiments": [],
            "metrics": [],
            "objects": [],
        },
        "synopsis": direct,
    }
    if group == "synopsis":
        reading_result[group] = interpretive
    else:
        reading_result[group] = [interpretive]

    output = LiteratureReaderOutputV1.model_validate(
        {
            "candidate_drafts": [],
            "reading_result": reading_result,
            "schema_version": "gezhi.literature_reader_output.v1",
        },
        strict=True,
    )

    if group == "synopsis":
        assert output.reading_result.synopsis.support_kind == "interpretive"
    else:
        statements = getattr(output.reading_result, group)
        assert statements[0].support_kind == "interpretive"


@pytest.mark.parametrize(
    "source",
    [
        {
            "SystemRoot": r"C:\Windows",
            "HTTPS_PROXY": "https://one.invalid",
            "https_proxy": "https://two.invalid",
        },
        {
            "SystemRoot": r"C:\Windows",
            "UNRELATED=INVALID": "must still be validated",
        },
    ],
)
def test_reader_validates_the_complete_source_environment_before_filtering(
    source: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        _source_environment(source)


def test_reader_recovery_accepts_only_a_bounded_retry_sequence(
    reader_input_base: Path,
) -> None:
    too_many = _attempt_run(reader_input_base, "too-many")
    for ordinal in range(1, 5):
        _write_recovery_attempt(
            too_many,
            ordinal,
            failure_class="timeout",
            exit_code=None,
        )
    with pytest.raises(ValueError):
        _attempt_documents_from_run_v1(too_many)

    impossible_retry = _attempt_run(reader_input_base, "impossible-retry")
    _write_recovery_attempt(
        impossible_retry,
        1,
        failure_class="process_error",
        exit_code=1,
    )
    _write_recovery_attempt(
        impossible_retry,
        2,
        failure_class="timeout",
        exit_code=None,
    )
    with pytest.raises(ValueError):
        _attempt_documents_from_run_v1(impossible_retry)


@pytest.mark.parametrize(
    ("exit_code", "events", "final"),
    [
        (0, b'{"type":"thread.started"}\n', None),
        (1, b'{"type":"thread.started"}\n', b"{}"),
        (0, b"not-json\n", b"{}"),
    ],
)
def test_reader_recovery_rejects_an_impossible_clean_attempt(
    reader_input_base: Path,
    exit_code: int,
    events: bytes,
    final: bytes | None,
) -> None:
    run = _attempt_run(reader_input_base, "impossible-clean")
    _write_recovery_attempt(
        run,
        1,
        failure_class=None,
        exit_code=exit_code,
        events=events,
        final=final,
    )

    with pytest.raises(ValueError):
        _attempt_documents_from_run_v1(run)


def test_reader_recovery_recomputes_usage_from_captured_events(
    reader_input_base: Path,
) -> None:
    run = _attempt_run(reader_input_base, "usage-mismatch")
    _write_recovery_attempt(
        run,
        1,
        failure_class="process_error",
        exit_code=1,
        events=(
            b'{"type":"turn.completed","usage":{"cached_input_tokens":1,'
            b'"input_tokens":1,"output_tokens":1,'
            b'"reasoning_output_tokens":1}}\n'
        ),
    )

    with pytest.raises(ValueError):
        _attempt_documents_from_run_v1(run)


@pytest.mark.parametrize(
    ("asset_name", "byte_length"),
    [
        ("events.jsonl", LITERATURE_EVENTS_CAPTURE_CAP_V1 + 1),
        ("final_message.txt", LITERATURE_FINAL_CAPTURE_CAP_V1 + 1),
    ],
)
def test_reader_recovery_rejects_an_oversized_attempt_capture(
    reader_input_base: Path,
    asset_name: str,
    byte_length: int,
) -> None:
    run = _attempt_run(reader_input_base, "oversized-" + asset_name.split(".")[0])
    _write_recovery_attempt(
        run,
        1,
        failure_class="process_error",
        exit_code=1,
    )
    (run / "attempts" / "01" / asset_name).write_bytes(b"x" * byte_length)

    with pytest.raises(ValueError):
        _attempt_documents_from_run_v1(run)


def test_reader_recovery_accepts_zero_attempts_and_a_legal_retry_sequence(
    reader_input_base: Path,
) -> None:
    empty = _attempt_run(reader_input_base, "zero-attempts")
    assert _attempt_documents_from_run_v1(empty) == []

    retried = _attempt_run(reader_input_base, "legal-retry")
    for ordinal in (1, 2):
        _write_recovery_attempt(
            retried,
            ordinal,
            failure_class="timeout",
            exit_code=None,
            events=b"not-json\n",
        )
    _write_recovery_attempt(
        retried,
        3,
        failure_class=None,
        exit_code=0,
        final=b"{}",
    )

    documents = _attempt_documents_from_run_v1(retried)
    assert [document["failure_class"] for document in documents] == [
        "timeout",
        "timeout",
        None,
    ]
