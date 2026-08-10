from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from launcher_support import SOURCE_ROOT, launcher_commands, run_launcher
from literature_pdf_support import write_text_pdf

from gezhi import _literature_canonical as canonical
from gezhi import _literature_resume as resume
from gezhi._literature_intake import ActiveSourceAuthorityV1
from gezhi._windows_data_root import (
    ValidatedDataRootV1,
    open_validated_data_root_v1,
)


@pytest.fixture
def resume_workspace() -> Iterator[tuple[Path, Path]]:
    container = Path(r"E:\Gezhi\data")
    container.mkdir(parents=True, exist_ok=True)
    while True:
        base = container / ("r" + uuid.uuid4().hex[:7])
        try:
            base.mkdir()
        except FileExistsError:
            continue
        break
    data_root = base / "lit"
    data_root.mkdir()
    pdf_path = base / "paper.pdf"
    try:
        yield data_root, pdf_path
    finally:
        resolved_base = base.resolve(strict=True)
        assert resolved_base.parent == container.resolve(strict=True)
        assert resolved_base.name.startswith("r") and len(resolved_base.name) == 8
        shutil.rmtree(resolved_base)


def _run_add(data_root: Path, pdf_path: Path) -> dict[str, object]:
    completed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(data_root),
                "literature",
                "add",
                str(pdf_path),
                "--json",
            )
        )[1]
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    return json.loads(completed.stdout)["result"]


def _run_resume(
    data_root: Path,
    work_id: str,
    *,
    launcher_index: int = 1,
    json_output: bool = True,
    pythonpath_roots: tuple[Path, ...] = (SOURCE_ROOT,),
) -> subprocess.CompletedProcess[bytes]:
    arguments = (
        "--literature-data-root",
        str(data_root),
        "literature",
        "resume",
        work_id,
        *(("--json",) if json_output else ()),
    )
    return run_launcher(
        launcher_commands(arguments)[launcher_index],
        pythonpath_roots=pythonpath_roots,
    )


def _rehash_run_and_current(run_dir: Path, current_path: Path) -> None:
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["assets"] = resume._asset_entries(run_dir)
    manifest_bytes = resume._canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)
    current = json.loads(current_path.read_bytes())
    current["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    current_path.write_bytes(resume._canonical_json_bytes(current))


def _clone_canonical_success(source: Path, target: Path, run_id: str) -> Path:
    shutil.copytree(source, target)
    provenance_path = target / "provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    provenance["canonical_run_id"] = run_id
    provenance_path.write_bytes(canonical._canonical_json_file_bytes(provenance))
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["run_id"] = run_id
    manifest["assets"] = canonical._asset_entries(target)
    manifest_path.write_bytes(canonical._canonical_json_file_bytes(manifest))
    return target


def _rehash_canonical_run_and_current(
    run_dir: Path,
    current_path: Path,
) -> None:
    blocks_bytes = (run_dir / "blocks.jsonl").read_bytes()
    document_bytes = (run_dir / "document.md").read_bytes()
    image_entries = [
        {
            "path": f"images/{path.name}",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(
            (run_dir / "images").iterdir(),
            key=lambda value: value.name.encode("utf-8"),
        )
    ]
    identity = {
        "blocks_sha256": hashlib.sha256(blocks_bytes).hexdigest(),
        "document_sha256": hashlib.sha256(document_bytes).hexdigest(),
        "images": image_entries,
        "schema_version": "gezhi.canonical_content.v1",
    }
    content_sha256 = hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["assets"] = canonical._asset_entries(run_dir)
    manifest["canonical_content_sha256"] = content_sha256
    manifest_bytes = canonical._canonical_json_file_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)
    current = json.loads(current_path.read_bytes())
    current["canonical_content_sha256"] = content_sha256
    current["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    current_path.write_bytes(canonical._canonical_json_file_bytes(current))


@pytest.mark.parametrize("launcher_index", [0, 1])
def test_native_text_resume_publishes_canonical_success_and_stops_at_read(
    resume_workspace: tuple[Path, Path],
    launcher_index: int,
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This native PDF contains enough searchable text for explicit bypass.",
    )
    added = _run_add(data_root, pdf_path)

    completed = _run_resume(
        data_root,
        str(added["work_id"]),
        launcher_index=launcher_index,
    )

    assert completed.returncode == 2, completed.stderr.decode(errors="replace")
    assert completed.stderr == b""
    expected_result = {
        "active_source_id": added["source_id"],
        "advanced_stages": ["ocr", "canonicalize"],
        "pending_candidate_ids": [],
        "pipeline_complete": False,
        "schema_version": "gezhi.literature_resume_result.v1",
        "start_stage": "ocr",
        "stop_stage": "read",
        "work_id": added["work_id"],
    }
    expected_document = {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.stage_blocked.v1",
                "context": {
                    "reason": "reader_prerequisite_unavailable",
                    "stage": "read",
                },
            }
        ],
        "outcome": "blocked",
        "result": expected_result,
        "schema_version": "gezhi.cli_result.v1",
    }
    assert completed.stdout == (
        json.dumps(
            expected_document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )

    source_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
    )
    ocr_dir = source_dir / "ocr"
    current_bytes = (ocr_dir / "current.json").read_bytes()
    current = json.loads(current_bytes)
    assert current["schema_version"] == "gezhi.literature_ocr_current.v1"
    assert current["source_id"] == added["source_id"]
    assert current["source_sha256"] == added["source_sha256"]
    run_dir = ocr_dir / "runs" / current["run_id"]
    receipt = json.loads((run_dir / "receipt.json").read_bytes())
    assert receipt["status"] == "succeeded"
    assert receipt["method"] == "native_text"
    assert receipt["attempt_count"] == 0
    manifest_bytes = (run_dir / "manifest.json").read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == current["manifest_sha256"]
    assert json.loads((run_dir / "selection.json").read_bytes())["method"] == (
        "native_text"
    )
    native = json.loads((run_dir / "output" / "native_text.json").read_bytes())
    assert native["pages"][0]["text"].startswith("This native PDF")
    assert not tuple((ocr_dir / "runs" / ".staging").iterdir())

    canonical_dir = source_dir / "canonical"
    canonical_current_bytes = (canonical_dir / "current.json").read_bytes()
    canonical_current = json.loads(canonical_current_bytes)
    assert canonical_current["schema_version"] == (
        "gezhi.literature_canonical_current.v1"
    )
    assert canonical_current["source_id"] == added["source_id"]
    assert canonical_current["source_sha256"] == added["source_sha256"]
    canonical_run = canonical_dir / "runs" / canonical_current["run_id"]
    canonical_manifest_bytes = (canonical_run / "manifest.json").read_bytes()
    assert hashlib.sha256(canonical_manifest_bytes).hexdigest() == (
        canonical_current["manifest_sha256"]
    )
    canonical_manifest = json.loads(canonical_manifest_bytes)
    assert canonical_manifest["canonical_content_sha256"] == (
        canonical_current["canonical_content_sha256"]
    )
    assert canonical_manifest["ocr_run_id"] == current["run_id"]
    schema_bytes = (canonical_run / "schema.json").read_bytes()
    assert json.loads(schema_bytes)["$id"] == (
        "https://gezhi.local/schemas/evidence-block-v1.schema.json"
    )
    assert canonical_manifest["schema_sha256"] == hashlib.sha256(
        schema_bytes
    ).hexdigest()
    provenance = json.loads((canonical_run / "provenance.json").read_bytes())
    assert provenance["canonical_run_id"] == canonical_current["run_id"]
    assert provenance["ocr_run_id"] == current["run_id"]
    assert provenance["ocr_manifest_sha256"] == current["manifest_sha256"]
    assert provenance["page_count"] == 1
    assert provenance["block_count"] == 1
    assert (canonical_run / "document.md").read_text(encoding="utf-8").endswith(
        "explicit bypass.\n"
    )
    block_lines = (canonical_run / "blocks.jsonl").read_bytes().splitlines()
    assert len(block_lines) == 1
    block = json.loads(block_lines[0])
    assert block == {
        "bbox": None,
        "block_id": block["block_id"],
        "heading_path": [],
        "image_path": None,
        "kind": "paragraph",
        "order": 0,
        "page_index": 0,
        "schema_version": "gezhi.evidence_block.v1",
        "text": (
            "This native PDF contains enough searchable text for explicit "
            "bypass."
        ),
    }
    assert isinstance(block["block_id"], str)
    assert block["block_id"].startswith("blk_")
    block_identity = {
        "bbox": None,
        "heading_path": [],
        "image_path": None,
        "kind": "paragraph",
        "order": 0,
        "page_index": 0,
        "schema_version": "gezhi.evidence_block_identity.v1",
        "text": block["text"],
    }
    block_hash = hashlib.sha256(
        json.dumps(
            block_identity,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert block["block_id"] == "blk_" + block_hash[:24]
    content_identity = {
        "blocks_sha256": hashlib.sha256(
            (canonical_run / "blocks.jsonl").read_bytes()
        ).hexdigest(),
        "document_sha256": hashlib.sha256(
            (canonical_run / "document.md").read_bytes()
        ).hexdigest(),
        "images": [],
        "schema_version": "gezhi.canonical_content.v1",
    }
    expected_content_sha256 = hashlib.sha256(
        json.dumps(
            content_identity,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert canonical_current["canonical_content_sha256"] == (
        expected_content_sha256
    )
    assert {
        "block_id": block["block_id"],
        "canonical_content_sha256": expected_content_sha256,
        "schema_version": "gezhi.evidence_pointer.v1",
    } == {
        "block_id": block["block_id"],
        "canonical_content_sha256": canonical_current[
            "canonical_content_sha256"
        ],
        "schema_version": "gezhi.evidence_pointer.v1",
    }
    assert not tuple((canonical_dir / "runs" / ".staging").iterdir())


@pytest.mark.parametrize("launcher_index", [0, 1])
def test_canonical_success_has_exact_human_reader_prerequisite_receipt(
    resume_workspace: tuple[Path, Path],
    launcher_index: int,
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This native PDF has enough text for the exact Human receipt.",
    )
    added = _run_add(data_root, pdf_path)

    completed = _run_resume(
        data_root,
        str(added["work_id"]),
        launcher_index=launcher_index,
        json_output=False,
    )

    assert completed.returncode == 2
    assert completed.stderr == b""
    expected_lines = [
        "Literature resume：已阻塞",
        f"Active Source ID：{added['source_id']}",
        "本次推进阶段：",
        "  - ocr",
        "  - canonicalize",
        "待审核 Candidate：[]",
        "管线已完成：否",
        "Schema：gezhi.literature_resume_result.v1",
        "开始阶段：ocr",
        "停止阶段：read",
        f"Work ID：{added['work_id']}",
        "原因：read 阶段已阻塞（reader_prerequisite_unavailable）",
        (
            "下一步：修复该前置条件后重新运行 resume；"
            "awaiting_review 时对列出的 Candidate 显式 review"
        ),
    ]
    assert completed.stdout == ("\n".join(expected_lines) + "\n").encode("utf-8")


def test_matching_native_ocr_success_is_reused_without_a_second_run(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This PDF has enough native text and must remain idempotent on resume.",
    )
    added = _run_add(data_root, pdf_path)
    first = _run_resume(data_root, str(added["work_id"]))
    assert first.returncode == 2
    runs_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
        / "ocr"
        / "runs"
    )
    first_runs = {entry.name for entry in runs_dir.iterdir() if entry.name != ".staging"}
    current_before = (runs_dir.parent / "current.json").read_bytes()
    canonical_dir = runs_dir.parents[1] / "canonical"
    canonical_runs_dir = canonical_dir / "runs"
    first_canonical_runs = {
        entry.name
        for entry in canonical_runs_dir.iterdir()
        if entry.name != ".staging"
    }
    canonical_current_before = (canonical_dir / "current.json").read_bytes()

    second = _run_resume(data_root, str(added["work_id"]))

    assert second.returncode == 2
    document = json.loads(second.stdout)
    assert document["result"] == {
        "active_source_id": added["source_id"],
        "advanced_stages": [],
        "pending_candidate_ids": [],
        "pipeline_complete": False,
        "schema_version": "gezhi.literature_resume_result.v1",
        "start_stage": "read",
        "stop_stage": "read",
        "work_id": added["work_id"],
    }
    assert {entry.name for entry in runs_dir.iterdir() if entry.name != ".staging"} == (
        first_runs
    )
    assert (runs_dir.parent / "current.json").read_bytes() == current_before
    assert {
        entry.name
        for entry in canonical_runs_dir.iterdir()
        if entry.name != ".staging"
    } == first_canonical_runs
    assert (canonical_dir / "current.json").read_bytes() == canonical_current_before


def test_reused_canonical_revalidates_consumed_ocr_assets(
    resume_workspace: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This PDF has enough native text before reuse-time OCR asset drift.",
    )
    added = _run_add(data_root, pdf_path)
    assert _run_resume(data_root, str(added["work_id"])).returncode == 2
    source_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
    )
    ocr_dir = source_dir / "ocr"
    ocr_current = json.loads((ocr_dir / "current.json").read_bytes())
    native_path = (
        ocr_dir
        / "runs"
        / ocr_current["run_id"]
        / "output"
        / "native_text.json"
    )
    canonical_dir = source_dir / "canonical"
    canonical_current_before = (canonical_dir / "current.json").read_bytes()
    canonical_runs_before = {
        entry.name
        for entry in (canonical_dir / "runs").iterdir()
        if entry.name != ".staging"
    }
    real_advance = canonical.advance_canonicalize_v1
    drifted = False

    def drift_then_advance(
        authority: ActiveSourceAuthorityV1,
        ocr: canonical.CurrentOcrAssetV1,
        *,
        root: ValidatedDataRootV1,
    ) -> canonical.CanonicalAdvanceV1:
        nonlocal drifted
        if not drifted:
            drifted = True
            native = json.loads(native_path.read_bytes())
            native["pages"][0]["text"] = "forged after OCR validation"
            native_path.write_bytes(resume._canonical_json_bytes(native))
        return real_advance(authority, ocr, root=root)

    monkeypatch.setattr(canonical, "advance_canonicalize_v1", drift_then_advance)

    with open_validated_data_root_v1(str(data_root)) as root, pytest.raises(
        resume.ResumeStoppedV1
    ) as caught:
        resume.resume_work(str(added["work_id"]), root=root)

    stopped = caught.value
    assert drifted is True
    assert (stopped.outcome, stopped.stage, stopped.reason) == (
        "failed",
        "canonicalize",
        "asset_integrity_lost",
    )
    assert (canonical_dir / "current.json").read_bytes() == canonical_current_before
    assert {
        entry.name
        for entry in (canonical_dir / "runs").iterdir()
        if entry.name != ".staging"
    } == canonical_runs_before


def test_committed_canonical_run_with_missing_current_repairs_only_the_pointer(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This PDF has enough native text for canonical pointer recovery.",
    )
    added = _run_add(data_root, pdf_path)
    assert _run_resume(data_root, str(added["work_id"])).returncode == 2
    canonical_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
        / "canonical"
    )
    runs_dir = canonical_dir / "runs"
    run_names = {
        entry.name for entry in runs_dir.iterdir() if entry.name != ".staging"
    }
    current_path = canonical_dir / "current.json"
    expected_current = current_path.read_bytes()
    current_path.unlink()

    completed = _run_resume(data_root, str(added["work_id"]))

    assert completed.returncode == 2
    document = json.loads(completed.stdout)
    assert document["diagnostics"] == [
        {
            "code": "literature.resume.stage_blocked.v1",
            "context": {
                "reason": "reader_prerequisite_unavailable",
                "stage": "read",
            },
        }
    ]
    assert document["result"]["advanced_stages"] == ["canonicalize"]
    assert document["result"]["start_stage"] == "canonicalize"
    assert document["result"]["stop_stage"] == "read"
    assert {
        entry.name for entry in runs_dir.iterdir() if entry.name != ".staging"
    } == run_names
    assert current_path.read_bytes() == expected_current


def test_complete_canonical_staging_orphan_is_committed_without_rebuilding(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This PDF has enough native text for canonical orphan recovery.",
    )
    added = _run_add(data_root, pdf_path)
    assert _run_resume(data_root, str(added["work_id"])).returncode == 2
    canonical_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
        / "canonical"
    )
    current_path = canonical_dir / "current.json"
    expected_current = current_path.read_bytes()
    current = json.loads(expected_current)
    runs_dir = canonical_dir / "runs"
    staging_dir = runs_dir / ".staging"
    formal_run = runs_dir / current["run_id"]
    staged_run = staging_dir / current["run_id"]
    formal_run.rename(staged_run)
    current_path.unlink()

    completed = _run_resume(data_root, str(added["work_id"]))

    assert completed.returncode == 2
    document = json.loads(completed.stdout)
    assert document["result"]["advanced_stages"] == ["canonicalize"]
    assert document["result"]["start_stage"] == "canonicalize"
    assert document["result"]["stop_stage"] == "read"
    assert current_path.read_bytes() == expected_current
    assert (runs_dir / current["run_id"]).is_dir()
    assert not staged_run.exists()
    assert {
        entry.name for entry in runs_dir.iterdir() if entry.name != ".staging"
    } == {current["run_id"]}


def test_canonical_staging_recovery_revalidates_consumed_ocr_assets(
    resume_workspace: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This PDF has enough native text before orphan recovery drift.",
    )
    added = _run_add(data_root, pdf_path)
    assert _run_resume(data_root, str(added["work_id"])).returncode == 2
    source_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
    )
    canonical_dir = source_dir / "canonical"
    current_path = canonical_dir / "current.json"
    current = json.loads(current_path.read_bytes())
    runs_dir = canonical_dir / "runs"
    staging_dir = runs_dir / ".staging"
    staged_run = staging_dir / current["run_id"]
    (runs_dir / current["run_id"]).rename(staged_run)
    current_path.unlink()
    real_commit = canonical._commit_stage
    drifted = False

    def drift_then_commit(
        stage: Path,
        formal_runs: Path,
        authority: ActiveSourceAuthorityV1,
        ocr: canonical.CurrentOcrAssetV1,
        root: ValidatedDataRootV1,
        *,
        consumed_ocr_assets: tuple[
            canonical._OcrManifestAssetV1, ...
        ] = (),
    ) -> canonical._ValidatedCanonicalRunV1:
        nonlocal drifted
        if not drifted:
            drifted = True
            native_path = ocr.run_directory / "output" / "native_text.json"
            native = json.loads(native_path.read_bytes())
            native["pages"][0]["text"] = "forged after recovery inventory"
            native_path.write_bytes(resume._canonical_json_bytes(native))
        return real_commit(
            stage,
            formal_runs,
            authority,
            ocr,
            root,
            consumed_ocr_assets=consumed_ocr_assets,
        )

    monkeypatch.setattr(canonical, "_commit_stage", drift_then_commit)

    with open_validated_data_root_v1(str(data_root)) as root, pytest.raises(
        resume.ResumeStoppedV1
    ) as caught:
        resume.resume_work(str(added["work_id"]), root=root)

    stopped = caught.value
    assert (stopped.outcome, stopped.stage, stopped.reason) == (
        "failed",
        "canonicalize",
        "asset_integrity_lost",
    )
    assert staged_run.is_dir()
    assert not current_path.exists()
    assert not (runs_dir / current["run_id"]).exists()


def test_current_recovery_retries_replace_while_previous_current_is_valid(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This PDF has enough native text before a replace action is retried.",
    )
    added = _run_add(data_root, pdf_path)
    assert _run_resume(data_root, str(added["work_id"])).returncode == 2
    source_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
    )
    canonical_dir = source_dir / "canonical"
    runs_dir = canonical_dir / "runs"
    staging_dir = runs_dir / ".staging"
    current_path = canonical_dir / "current.json"
    previous_bytes = current_path.read_bytes()
    previous_document = json.loads(previous_bytes)
    ocr_dir = source_dir / "ocr"
    ocr_document = json.loads((ocr_dir / "current.json").read_bytes())
    ocr_run_dir = ocr_dir / "runs" / ocr_document["run_id"]
    ocr_receipt = json.loads((ocr_run_dir / "receipt.json").read_bytes())

    with open_validated_data_root_v1(str(data_root)) as root:
        authority = resume._load_authority_or_stop(str(added["work_id"]), root)
        previous_run = canonical._ValidatedCanonicalRunV1(
            path=runs_dir / previous_document["run_id"],
            run_id=previous_document["run_id"],
            input_fingerprint_sha256=previous_document[
                "input_fingerprint_sha256"
            ],
            manifest_sha256=previous_document["manifest_sha256"],
            canonical_content_sha256=previous_document[
                "canonical_content_sha256"
            ],
        )
        next_run_id = "canrun_" + str(uuid.uuid4())
        next_fingerprint = hashlib.sha256(b"next canonical input").hexdigest()
        next_run = canonical._ValidatedCanonicalRunV1(
            path=runs_dir / next_run_id,
            run_id=next_run_id,
            input_fingerprint_sha256=next_fingerprint,
            manifest_sha256=hashlib.sha256(b"next manifest").hexdigest(),
            canonical_content_sha256=hashlib.sha256(b"next content").hexdigest(),
        )
        next_bytes = canonical._canonical_json_file_bytes(
            canonical._current_document(authority, next_run)
        )
        temporary = canonical_dir / f".current.json.{uuid.uuid4().hex}.tmp"
        replacement = (
            staging_dir / f".current-replace.{uuid.uuid4().hex}.tmp"
        )
        temporary.write_bytes(next_bytes)
        replacement.write_bytes(next_bytes)
        ocr = canonical.CurrentOcrAssetV1(
            method=ocr_receipt["method"],
            run_id=ocr_document["run_id"],
            run_directory=ocr_run_dir,
            input_fingerprint_sha256=ocr_document[
                "input_fingerprint_sha256"
            ],
            manifest_sha256=ocr_document["manifest_sha256"],
        )

        recovered, repaired = canonical._load_or_recover_current(
            canonical_dir,
            staging_dir,
            runs={previous_run.run_id: previous_run, next_run.run_id: next_run},
            expected_fingerprint=next_fingerprint,
            replacement_names=(replacement.name,),
            staging_snapshot=(replacement.name,),
            authority=authority,
            ocr=ocr,
            root=root,
        )

    assert repaired is True
    assert recovered == next_run
    assert previous_bytes != next_bytes
    assert current_path.read_bytes() == next_bytes
    assert not temporary.exists()
    assert not replacement.exists()


def test_multiple_canonical_successes_take_priority_over_invalid_formal_run(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This PDF has enough native text before canonical ambiguity.",
    )
    added = _run_add(data_root, pdf_path)
    assert _run_resume(data_root, str(added["work_id"])).returncode == 2
    canonical_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
        / "canonical"
    )
    current_path = canonical_dir / "current.json"
    current_before = current_path.read_bytes()
    current = json.loads(current_before)
    runs_dir = canonical_dir / "runs"
    first = runs_dir / current["run_id"]
    clone_id = "canrun_" + str(uuid.uuid4())
    _clone_canonical_success(first, runs_dir / clone_id, clone_id)
    invalid = runs_dir / ("canrun_" + str(uuid.uuid4()))
    invalid.mkdir()
    marker = invalid / "document.md"
    marker.write_bytes(b"invalid formal evidence\n")

    with open_validated_data_root_v1(str(data_root)) as root, pytest.raises(
        RuntimeError
    ) as caught:
        resume.resume_work(str(added["work_id"]), root=root)

    assert type(caught.value).__name__ == "CanonicalRecoveryUncertainV1"
    assert current_path.read_bytes() == current_before
    assert marker.read_bytes() == b"invalid formal evidence\n"
    assert first.is_dir()
    assert (runs_dir / clone_id).is_dir()


def test_orphaned_replacement_takes_priority_over_invalid_formal_run(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This PDF has enough native text before combined recovery faults.",
    )
    added = _run_add(data_root, pdf_path)
    assert _run_resume(data_root, str(added["work_id"])).returncode == 2
    canonical_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
        / "canonical"
    )
    current_path = canonical_dir / "current.json"
    current_before = current_path.read_bytes()
    runs_dir = canonical_dir / "runs"
    invalid = runs_dir / ("canrun_" + str(uuid.uuid4()))
    invalid.mkdir()
    marker = invalid / "document.md"
    marker.write_bytes(b"invalid formal evidence\n")
    replacement = (
        runs_dir
        / ".staging"
        / f".current-replace.{uuid.uuid4().hex}.tmp"
    )
    replacement.write_bytes(current_before)

    with open_validated_data_root_v1(str(data_root)) as root, pytest.raises(
        RuntimeError
    ) as caught:
        resume.resume_work(str(added["work_id"]), root=root)

    assert type(caught.value).__name__ == "CanonicalRecoveryUncertainV1"
    assert current_path.read_bytes() == current_before
    assert replacement.read_bytes() == current_before
    assert marker.read_bytes() == b"invalid formal evidence\n"


def test_partial_canonical_staging_is_preserved_and_fail_stops(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This PDF has enough native text beside a partial canonical orphan.",
    )
    added = _run_add(data_root, pdf_path)
    canonical_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
        / "canonical"
    )
    staging_dir = canonical_dir / "runs" / ".staging"
    staging_dir.mkdir(parents=True)
    orphan = staging_dir / ("canrun_" + str(uuid.uuid4()))
    orphan.mkdir()
    marker = orphan / "document.md"
    marker.write_bytes(b"partial recovery evidence\n")

    with open_validated_data_root_v1(str(data_root)) as root, pytest.raises(
        RuntimeError
    ) as caught:
        resume.resume_work(str(added["work_id"]), root=root)

    assert type(caught.value).__name__ == "CanonicalRecoveryUncertainV1"
    assert marker.read_bytes() == b"partial recovery evidence\n"
    assert not (canonical_dir / "current.json").exists()
    assert not tuple(
        entry
        for entry in (canonical_dir / "runs").iterdir()
        if entry.name != ".staging"
    )


def test_orphaned_canonical_current_replacement_evidence_fail_stops(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This PDF has enough native text before orphaned replace evidence.",
    )
    added = _run_add(data_root, pdf_path)
    assert _run_resume(data_root, str(added["work_id"])).returncode == 2
    canonical_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
        / "canonical"
    )
    current_path = canonical_dir / "current.json"
    current_before = current_path.read_bytes()
    replacement = (
        canonical_dir
        / "runs"
        / ".staging"
        / f".current-replace.{uuid.uuid4().hex}.tmp"
    )
    replacement.write_bytes(current_before)

    with open_validated_data_root_v1(str(data_root)) as root, pytest.raises(
        RuntimeError
    ) as caught:
        resume.resume_work(str(added["work_id"]), root=root)

    assert type(caught.value).__name__ == "CanonicalRecoveryUncertainV1"
    assert replacement.read_bytes() == current_before
    assert current_path.read_bytes() == current_before


def test_canonical_current_recovery_consumes_unique_preserved_replacement(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This PDF has enough native text for current replacement recovery.",
    )
    added = _run_add(data_root, pdf_path)
    assert _run_resume(data_root, str(added["work_id"])).returncode == 2
    canonical_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
        / "canonical"
    )
    current_path = canonical_dir / "current.json"
    current_before = current_path.read_bytes()
    temporary = canonical_dir / f".current.json.{uuid.uuid4().hex}.tmp"
    temporary.write_bytes(current_before)
    staging_dir = canonical_dir / "runs" / ".staging"
    replacement = (
        staging_dir / f".current-replace.{uuid.uuid4().hex}.tmp"
    )
    replacement.write_bytes(current_before)

    completed = _run_resume(data_root, str(added["work_id"]))

    assert completed.returncode == 2
    document = json.loads(completed.stdout)
    assert document["result"]["advanced_stages"] == ["canonicalize"]
    assert document["result"]["start_stage"] == "canonicalize"
    assert current_path.read_bytes() == current_before
    assert not temporary.exists()
    assert not replacement.exists()
    assert not tuple(staging_dir.iterdir())


def test_tampered_canonical_success_is_asset_integrity_lost(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This PDF has enough native text before canonical corruption.",
    )
    added = _run_add(data_root, pdf_path)
    assert _run_resume(data_root, str(added["work_id"])).returncode == 2
    canonical_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
        / "canonical"
    )
    current = json.loads((canonical_dir / "current.json").read_bytes())
    runs_dir = canonical_dir / "runs"
    run_dir = runs_dir / current["run_id"]
    run_names = {
        entry.name for entry in runs_dir.iterdir() if entry.name != ".staging"
    }
    (run_dir / "document.md").write_bytes(b"forged\n")

    completed = _run_resume(data_root, str(added["work_id"]))

    assert completed.returncode == 1
    document = json.loads(completed.stdout)
    assert document["outcome"] == "failed"
    assert document["result"]["advanced_stages"] == []
    assert document["result"]["start_stage"] == "canonicalize"
    assert document["result"]["stop_stage"] == "canonicalize"
    assert document["diagnostics"] == [
        {
            "code": "literature.resume.stage_failed.v1",
            "context": {
                "reason": "asset_integrity_lost",
                "stage": "canonicalize",
            },
        }
    ]
    assert {
        entry.name for entry in runs_dir.iterdir() if entry.name != ".staging"
    } == run_names


def test_rehashed_native_block_with_forged_bbox_is_asset_integrity_lost(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This native PDF has enough text before a semantic bbox forgery.",
    )
    added = _run_add(data_root, pdf_path)
    assert _run_resume(data_root, str(added["work_id"])).returncode == 2
    canonical_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
        / "canonical"
    )
    current_path = canonical_dir / "current.json"
    current = json.loads(current_path.read_bytes())
    run_dir = canonical_dir / "runs" / current["run_id"]
    block = json.loads((run_dir / "blocks.jsonl").read_bytes())
    block["bbox"] = ["0", "0", "1", "1"]
    identity = {
        key: value
        for key, value in block.items()
        if key != "block_id"
    }
    identity["schema_version"] = "gezhi.evidence_block_identity.v1"
    full_hash = hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    block["block_id"] = "blk_" + full_hash[:24]
    (run_dir / "blocks.jsonl").write_bytes(
        canonical._canonical_json_file_bytes(block)
    )
    _rehash_canonical_run_and_current(run_dir, current_path)

    completed = _run_resume(data_root, str(added["work_id"]))

    assert completed.returncode == 1
    document = json.loads(completed.stdout)
    assert document["outcome"] == "failed"
    assert document["result"]["advanced_stages"] == []
    assert document["result"]["start_stage"] == "canonicalize"
    assert document["result"]["stop_stage"] == "canonicalize"
    assert document["diagnostics"] == [
        {
            "code": "literature.resume.stage_failed.v1",
            "context": {
                "reason": "asset_integrity_lost",
                "stage": "canonicalize",
            },
        }
    ]


@pytest.mark.parametrize(
    "relative_directory",
    [("rogue",), ("images", "rogue")],
)
def test_extra_canonical_directory_is_asset_integrity_lost(
    resume_workspace: tuple[Path, Path],
    relative_directory: tuple[str, ...],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This PDF has enough native text before namespace corruption.",
    )
    added = _run_add(data_root, pdf_path)
    assert _run_resume(data_root, str(added["work_id"])).returncode == 2
    canonical_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
        / "canonical"
    )
    current = json.loads((canonical_dir / "current.json").read_bytes())
    run_dir = canonical_dir / "runs" / current["run_id"]
    run_dir.joinpath(*relative_directory).mkdir()

    completed = _run_resume(data_root, str(added["work_id"]))

    assert completed.returncode == 1
    document = json.loads(completed.stdout)
    assert document["outcome"] == "failed"
    assert document["result"]["advanced_stages"] == []
    assert document["result"]["start_stage"] == "canonicalize"
    assert document["result"]["stop_stage"] == "canonicalize"
    assert document["diagnostics"] == [
        {
            "code": "literature.resume.stage_failed.v1",
            "context": {
                "reason": "asset_integrity_lost",
                "stage": "canonicalize",
            },
        }
    ]


def test_semantically_forged_native_output_is_asset_integrity_lost(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This native PDF has enough text before its audit asset is forged.",
    )
    added = _run_add(data_root, pdf_path)
    assert _run_resume(data_root, str(added["work_id"])).returncode == 2
    ocr_dir = (
        data_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
        / "ocr"
    )
    current_path = ocr_dir / "current.json"
    current = json.loads(current_path.read_bytes())
    run_dir = ocr_dir / "runs" / current["run_id"]
    native_path = run_dir / "output" / "native_text.json"
    native = json.loads(native_path.read_bytes())
    native["pages"][0]["text"] = "forged"
    native_path.write_bytes(resume._canonical_json_bytes(native))
    _rehash_run_and_current(run_dir, current_path)

    completed = _run_resume(data_root, str(added["work_id"]))

    assert completed.returncode == 1
    document = json.loads(completed.stdout)
    assert document["outcome"] == "failed"
    assert document["result"]["advanced_stages"] == []
    assert document["result"]["start_stage"] == "ocr"
    assert document["result"]["stop_stage"] == "ocr"
    assert document["diagnostics"] == [
        {
            "code": "literature.resume.stage_failed.v1",
            "context": {"reason": "asset_integrity_lost", "stage": "ocr"},
        }
    ]


def test_native_text_path_does_not_load_ocr_only_runtime_modules(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "Native text proves that the OCR runtime is not reached by this command.",
    )
    added = _run_add(data_root, pdf_path)
    site_root = pdf_path.parent / "site"
    site_root.mkdir()
    marker = site_root / "forbidden.txt"
    (site_root / "sitecustomize.py").write_text(
        "import importlib.abc\n"
        "import pathlib\n"
        f"marker = pathlib.Path({str(marker)!r})\n"
        "blocked = {'gezhi._doctor_runtime', 'mineru', 'torch', 'torchvision'}\n"
        "class Guard(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname in blocked:\n"
        "            marker.write_text(fullname, encoding='utf-8')\n"
        "            raise RuntimeError('forbidden import: ' + fullname)\n"
        "        return None\n"
        "import sys\n"
        "sys.meta_path.insert(0, Guard())\n",
        encoding="utf-8",
    )

    completed = _run_resume(
        data_root,
        str(added["work_id"]),
        pythonpath_roots=(site_root, SOURCE_ROOT),
    )

    assert completed.returncode == 2, completed.stderr.decode(errors="replace")
    assert not marker.exists()


@pytest.mark.parametrize(
    ("work_id", "code"),
    [
        ("bad", "literature.resume.work_invalid.v1"),
        (
            "wrk_123e4567-e89b-42d3-a456-426614174000",
            "literature.resume.work_not_found.v1",
        ),
    ],
)
def test_resume_rejects_invalid_or_missing_work_before_ocr(
    resume_workspace: tuple[Path, Path],
    work_id: str,
    code: str,
) -> None:
    data_root, _pdf_path = resume_workspace

    completed = _run_resume(data_root, work_id)

    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [{"code": code, "context": {}}],
        "outcome": "blocked",
        "result": None,
        "schema_version": "gezhi.cli_result.v1",
    }


def test_missing_active_pointer_is_unavailable_but_corrupt_source_is_invalid(
    resume_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = resume_workspace
    write_text_pdf(
        pdf_path,
        "This native source is long enough for the active source gate checks.",
    )
    first = _run_add(data_root, pdf_path)
    work_dir = data_root / "works" / str(first["work_id"])
    active_path = work_dir / "active_source.json"
    active_bytes = active_path.read_bytes()
    active_path.unlink()

    unavailable = _run_resume(data_root, str(first["work_id"]))

    assert unavailable.returncode == 2
    assert json.loads(unavailable.stdout)["diagnostics"] == [
        {"code": "literature.resume.active_source_unavailable.v1", "context": {}}
    ]
    assert json.loads(unavailable.stdout)["result"] is None

    active_path.write_bytes(active_bytes)
    source_path = (
        work_dir
        / "sources"
        / str(first["source_id"])
        / "original.pdf"
    )
    source_path.write_bytes(b"%PDF-corrupted")

    invalid = _run_resume(data_root, str(first["work_id"]))

    assert invalid.returncode == 1
    assert json.loads(invalid.stdout)["diagnostics"] == [
        {"code": "literature.resume.active_source_invalid.v1", "context": {}}
    ]
    assert json.loads(invalid.stdout)["result"] is None
