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


@pytest.mark.parametrize("launcher_index", [0, 1])
def test_native_text_resume_publishes_ocr_success_and_stops_at_canonicalize(
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
        "advanced_stages": ["ocr"],
        "pending_candidate_ids": [],
        "pipeline_complete": False,
        "schema_version": "gezhi.literature_resume_result.v1",
        "start_stage": "ocr",
        "stop_stage": "canonicalize",
        "work_id": added["work_id"],
    }
    assert json.loads(completed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.stage_blocked.v1",
                "context": {
                    "reason": "canonical_prerequisite_unavailable",
                    "stage": "canonicalize",
                },
            }
        ],
        "outcome": "blocked",
        "result": expected_result,
        "schema_version": "gezhi.cli_result.v1",
    }

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

    second = _run_resume(data_root, str(added["work_id"]))

    assert second.returncode == 2
    document = json.loads(second.stdout)
    assert document["result"] == {
        "active_source_id": added["source_id"],
        "advanced_stages": [],
        "pending_candidate_ids": [],
        "pipeline_complete": False,
        "schema_version": "gezhi.literature_resume_result.v1",
        "start_stage": "canonicalize",
        "stop_stage": "canonicalize",
        "work_id": added["work_id"],
    }
    assert {entry.name for entry in runs_dir.iterdir() if entry.name != ".staging"} == (
        first_runs
    )
    assert (runs_dir.parent / "current.json").read_bytes() == current_before


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
