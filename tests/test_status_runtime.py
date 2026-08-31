from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from launcher_support import (
    SOURCE_ROOT,
    launcher_commands,
    run_both_launchers,
    run_launcher,
)


@pytest.fixture
def status_roots() -> Iterator[tuple[Path, Path, Path]]:
    container = Path(r"E:\Gezhi\data")
    container.mkdir(parents=True, exist_ok=True)
    while True:
        base = container / ("s" + uuid.uuid4().hex[:7])
        try:
            base.mkdir()
        except FileExistsError:
            continue
        break
    literature = base / "lit"
    knowledge = base / "know"
    literature.mkdir()
    knowledge.mkdir()
    try:
        yield base, literature, knowledge
    finally:
        resolved = base.resolve(strict=True)
        assert resolved.parent == container.resolve(strict=True)
        assert resolved.name.startswith("s") and len(resolved.name) == 8
        shutil.rmtree(resolved)


def _status_arguments(
    literature: Path,
    knowledge: Path,
    *suffix: str,
) -> tuple[str, ...]:
    return (
        "--literature-data-root",
        str(literature),
        "--knowledge-data-root",
        str(knowledge),
        "status",
        *suffix,
    )


def _tree_snapshot(root: Path) -> tuple[tuple[object, ...], ...]:
    if not root.exists():
        return ((root.name, "absent"),)
    observed: list[tuple[object, ...]] = []
    for current, directories, files in os.walk(root):
        directories.sort(key=str.casefold)
        files.sort(key=str.casefold)
        current_path = Path(current)
        for name, is_directory in (
            *((name, True) for name in directories),
            *((name, False) for name in files),
        ):
            path = current_path / name
            stat_result = path.stat(follow_symlinks=False)
            observed.append(
                (
                    path.relative_to(root).as_posix(),
                    is_directory,
                    stat_result.st_size,
                    stat_result.st_mtime_ns,
                )
            )
    return tuple(observed)


def _deny_children_site_customize(marker: Path) -> str:
    return (
        "import pathlib\n"
        "import subprocess\n\n"
        f"marker = pathlib.Path({str(marker)!r})\n\n"
        "def denied(*args, **kwargs):\n"
        "    marker.write_text('prohibited', encoding='utf-8')\n"
        "    raise RuntimeError('status must not start a child')\n\n"
        "subprocess.Popen = denied\n"
    )


def test_real_empty_overall_status_is_read_only_and_starts_no_child(
    status_roots: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    _base, literature, knowledge = status_roots
    marker = tmp_path / "prohibited-child.txt"
    (tmp_path / "sitecustomize.py").write_text(
        _deny_children_site_customize(marker),
        encoding="utf-8",
    )
    before = (_tree_snapshot(literature), _tree_snapshot(knowledge))

    results = run_both_launchers(
        _status_arguments(literature, knowledge, "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
        environment_updates={"PYTHONDONTWRITEBYTECODE": "1"},
    )

    after = (_tree_snapshot(literature), _tree_snapshot(knowledge))
    receipts = [json.loads(result.stdout) for result in results]
    assert [result.returncode for result in results] == [0, 0]
    assert all(result.stderr == b"" for result in results)
    assert results[0].stdout == results[1].stdout
    assert receipts[0]["result"] == {
        "schema_version": "gezhi.status_result.v1",
        "scope": "overall",
        "status": "empty",
        "literature": {
            "availability": "ready",
            "work_count": 0,
            "work_status_counts": [],
            "pending_review_count": 0,
            "pending_handoff_count": 0,
        },
        "knowledge": {
            "availability": "ready",
            "active_candidate_count": 0,
            "withdrawn_candidate_count": 0,
            "answer_status_counts": [],
        },
        "recovery": {
            "staging_count": 0,
            "orphaned_count": 0,
            "quarantined_count": 0,
            "inconsistent_count": 0,
        },
        "next_action": "add_work",
    }
    assert receipts[0]["diagnostics"] == []
    assert before == after
    assert not marker.exists()


def test_invalid_work_id_wins_before_missing_roots_and_creates_nothing(
    status_roots: tuple[Path, Path, Path],
) -> None:
    base, literature, knowledge = status_roots
    literature.rmdir()
    knowledge.rmdir()
    invalid = "WRK_123e4567-e89b-42d3-a456-426614174000"

    results = run_both_launchers(
        _status_arguments(literature, knowledge, invalid, "--json"),
        pythonpath_roots=(SOURCE_ROOT,),
        environment_updates={"PYTHONDONTWRITEBYTECODE": "1"},
    )

    receipts = [json.loads(result.stdout) for result in results]
    assert [result.returncode for result in results] == [2, 2]
    assert all(result.stderr == b"" for result in results)
    assert receipts[0] == receipts[1]
    assert receipts[0]["result"] is None
    assert receipts[0]["diagnostics"] == [
        {"code": "operations.status.invalid_work_id.v1", "context": {}}
    ]
    assert invalid.encode() not in results[0].stdout
    assert _tree_snapshot(base) == ()


def _run_add(literature: Path, pdf_path: Path) -> dict[str, object]:
    result = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature),
                "literature",
                "add",
                str(pdf_path),
                "--json",
            )
        )[1]
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return json.loads(result.stdout)["result"]


@pytest.mark.parametrize("launcher_index", [0, 1])
def test_ingested_work_projects_only_ingest_as_succeeded(
    status_roots: tuple[Path, Path, Path],
    launcher_index: int,
) -> None:
    base, literature, knowledge = status_roots
    pdf_path = base / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\nstatus projection\n%%EOF\n")
    added = _run_add(literature, pdf_path)
    before = (_tree_snapshot(literature), _tree_snapshot(knowledge))

    result = run_launcher(
        launcher_commands(
            _status_arguments(
                literature,
                knowledge,
                str(added["work_id"]),
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(SOURCE_ROOT,),
        environment_updates={"PYTHONDONTWRITEBYTECODE": "1"},
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stderr == b""
    report = json.loads(result.stdout)["result"]
    assert report["scope"] == "work"
    assert report["status"] == "pending"
    assert report["literature"]["stages"] == [
        {"stage": "ingest", "status": "succeeded"},
        {"stage": "ocr", "status": "pending"},
        {"stage": "canonicalize", "status": "pending"},
        {"stage": "read", "status": "pending"},
        {"stage": "review", "status": "pending"},
        {"stage": "handoff", "status": "pending"},
        {"stage": "knowledge_import", "status": "pending"},
    ]
    assert report["next_action"] == "resume_work"
    assert before == (_tree_snapshot(literature), _tree_snapshot(knowledge))


def test_valid_absent_work_is_blocked_only_after_literature_is_readable(
    status_roots: tuple[Path, Path, Path],
) -> None:
    _base, literature, knowledge = status_roots
    work_id = "wrk_123e4567-e89b-42d3-a456-426614174000"

    results = run_both_launchers(
        _status_arguments(literature, knowledge, work_id, "--json"),
        pythonpath_roots=(SOURCE_ROOT,),
        environment_updates={"PYTHONDONTWRITEBYTECODE": "1"},
    )

    receipts = [json.loads(result.stdout) for result in results]
    assert [result.returncode for result in results] == [2, 2]
    assert all(result.stderr == b"" for result in results)
    assert receipts[0] == receipts[1]
    assert receipts[0]["diagnostics"] == [
        {
            "code": "operations.status.work_not_found.v1",
            "context": {"work_id": work_id},
        }
    ]


def test_real_candidate_registry_projects_the_same_candidate_for_overall_and_work(
    status_roots: tuple[Path, Path, Path],
) -> None:
    from support.knowledge_handoff_factory_v1 import accepted_handoff_v1

    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._knowledge_status import project_knowledge_status_v1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1
    from gezhi._windows_data_root import open_validated_data_root_v1

    _base, _literature, knowledge = status_roots
    handoff = accepted_handoff_v1(
        ordinal=81,
        statement_text="状态投影必须复用 Candidate Registry 权威。",
        source_terms=["状态", "投影"],
    )
    verdict = KnowledgeIntakeAdapterV1(str(knowledge)).apply(
        ReviewedHandoffBytesV1(
            manifest_bytes=handoff.manifest_bytes,
            candidates_bytes=handoff.candidates_bytes,
        )
    )
    assert verdict == IntakeAppliedV1("active", "applied")
    work_id = json.loads(handoff.manifest_bytes)["work_id"]
    assert type(work_id) is str
    before = _tree_snapshot(knowledge)

    with open_validated_data_root_v1(str(knowledge)) as root:
        overall = project_knowledge_status_v1(root, work_id=None)
        scoped = project_knowledge_status_v1(root, work_id=work_id)

    assert overall == {
        "availability": "ready",
        "active_candidate_count": 1,
        "withdrawn_candidate_count": 0,
        "answer_status_counts": [],
        "recovery": {
            "staging_count": 0,
            "orphaned_count": 0,
            "quarantined_count": 0,
            "inconsistent_count": 0,
        },
    }
    assert scoped == {
        "availability": "ready",
        "candidate_counts": {"active": 1, "withdrawn": 0},
        "related_answer_status_counts": [],
        "recovery": {
            "staging_count": 0,
            "orphaned_count": 0,
            "quarantined_count": 0,
            "inconsistent_count": 0,
        },
    }
    assert before == _tree_snapshot(knowledge)


def test_valid_import_evidence_without_registry_is_an_attributable_orphan(
    status_roots: tuple[Path, Path, Path],
) -> None:
    from support.knowledge_handoff_factory_v1 import accepted_handoff_v1

    from gezhi._knowledge_status import project_knowledge_status_v1
    from gezhi._windows_data_root import open_validated_data_root_v1

    _base, _literature, knowledge = status_roots
    handoff = accepted_handoff_v1(
        ordinal=82,
        statement_text="正式 evidence 先于 Registry 时属于 orphan。",
        source_terms=["evidence", "orphan"],
    )
    manifest = json.loads(handoff.manifest_bytes)
    handoff_id = manifest["handoff_id"]
    work_id = manifest["work_id"]
    assert type(handoff_id) is str
    assert type(work_id) is str
    target = knowledge / "imports" / handoff_id
    target.mkdir(parents=True)
    (target / "manifest.json").write_bytes(handoff.manifest_bytes)
    (target / "candidates.jsonl").write_bytes(handoff.candidates_bytes)
    before = _tree_snapshot(knowledge)

    with open_validated_data_root_v1(str(knowledge)) as root:
        overall = project_knowledge_status_v1(root, work_id=None)
        scoped = project_knowledge_status_v1(root, work_id=work_id)

    assert overall["recovery"] == {
        "staging_count": 0,
        "orphaned_count": 1,
        "quarantined_count": 0,
        "inconsistent_count": 0,
    }
    assert scoped["recovery"] == overall["recovery"]
    assert before == _tree_snapshot(knowledge)


@pytest.mark.parametrize(
    "staged_payload",
    [
        pytest.param(None, id="empty-directory"),
        pytest.param(b"not a manifest", id="invalid-manifest"),
    ],
)
def test_answer_staging_is_counted_without_content_classification(
    status_roots: tuple[Path, Path, Path],
    staged_payload: bytes | None,
) -> None:
    from gezhi._knowledge_status import project_knowledge_status_v1
    from gezhi._windows_data_root import open_validated_data_root_v1

    _base, _literature, knowledge = status_roots
    staging = (
        knowledge / "answers" / ".staging" / "ans_00000000-0000-4000-8000-000000000083"
    )
    staging.mkdir(parents=True)
    if staged_payload is not None:
        (staging / "manifest.json").write_bytes(staged_payload)
    before = _tree_snapshot(knowledge)

    with open_validated_data_root_v1(str(knowledge)) as root:
        overall = project_knowledge_status_v1(root, work_id=None)

    assert overall["availability"] == "ready"
    assert overall["recovery"] == {
        "staging_count": 1,
        "orphaned_count": 0,
        "quarantined_count": 0,
        "inconsistent_count": 0,
    }
    assert before == _tree_snapshot(knowledge)


def test_corrupt_registry_fails_the_unbounded_observation_without_mutation(
    status_roots: tuple[Path, Path, Path],
) -> None:
    _base, literature, knowledge = status_roots
    (knowledge / "registry.sqlite3").write_bytes(b"not sqlite")
    before = (_tree_snapshot(literature), _tree_snapshot(knowledge))

    results = run_both_launchers(
        _status_arguments(literature, knowledge, "--json"),
        pythonpath_roots=(SOURCE_ROOT,),
        environment_updates={"PYTHONDONTWRITEBYTECODE": "1"},
    )

    receipts = [json.loads(result.stdout) for result in results]
    assert [result.returncode for result in results] == [1, 1]
    assert all(result.stderr == b"" for result in results)
    assert receipts[0] == receipts[1]
    assert receipts[0] == {
        "schema_version": "gezhi.cli_result.v1",
        "command": "status",
        "outcome": "failed",
        "result": None,
        "diagnostics": [
            {"code": "operations.status.observation_failed.v1", "context": {}}
        ],
    }
    assert before == (_tree_snapshot(literature), _tree_snapshot(knowledge))


def test_corrupt_ocr_current_is_bounded_as_work_inconsistency(
    status_roots: tuple[Path, Path, Path],
) -> None:
    base, literature, knowledge = status_roots
    pdf_path = base / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\nstatus current pointer\n%%EOF\n")
    added = _run_add(literature, pdf_path)
    work_id = str(added["work_id"])
    sources = literature / "works" / work_id / "sources"
    source_directories = [
        path for path in sources.iterdir() if path.is_dir() and path.name != ".staging"
    ]
    assert len(source_directories) == 1
    ocr = source_directories[0] / "ocr"
    (ocr / "runs").mkdir(parents=True)
    (ocr / "current.json").write_bytes(b"{}\n")
    before = (_tree_snapshot(literature), _tree_snapshot(knowledge))

    results = run_both_launchers(
        _status_arguments(literature, knowledge, work_id, "--json"),
        pythonpath_roots=(SOURCE_ROOT,),
        environment_updates={"PYTHONDONTWRITEBYTECODE": "1"},
    )

    receipts = [json.loads(result.stdout) for result in results]
    assert [result.returncode for result in results] == [0, 0]
    assert all(result.stderr == b"" for result in results)
    assert receipts[0] == receipts[1]
    report = receipts[0]["result"]
    assert report["status"] == "inconsistent"
    assert report["literature"]["availability"] == "partial"
    assert report["literature"]["stages"][1] == {
        "stage": "ocr",
        "status": "failed",
    }
    assert report["recovery"]["inconsistent_count"] == 1
    assert receipts[0]["outcome"] == "succeeded"
    assert receipts[0]["diagnostics"] == [
        {
            "code": "operations.status.integrity_attention.v1",
            "context": {"kinds": ["inconsistent"], "count": 1},
        },
        {
            "code": "operations.status.projection_incomplete.v1",
            "context": {"contexts": ["literature"]},
        },
    ]
    assert before == (_tree_snapshot(literature), _tree_snapshot(knowledge))
