from __future__ import annotations

import json
import os
import shutil
import subprocess
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
from literature_pdf_support import write_text_pdf


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


def _run_resume(
    literature: Path,
    work_id: str,
    *,
    pythonpath_roots: tuple[Path, ...] = (SOURCE_ROOT,),
) -> subprocess.CompletedProcess[bytes]:
    return run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature),
                "literature",
                "resume",
                work_id,
                "--json",
            )
        )[1],
        pythonpath_roots=pythonpath_roots,
    )


def _canonical_json_line(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _stop_before_reader_sitecustomize(site_root: Path) -> None:
    (site_root / "sitecustomize.py").write_text(
        """
import gezhi._literature_reader as reader


def stop_before_reader(*_args, **_kwargs):
    raise reader.ReaderStageStoppedV1(
        "blocked", "codex_runtime_unavailable"
    )


reader.advance_reader_v1 = stop_before_reader
""",
        encoding="utf-8",
    )


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


@pytest.mark.parametrize(
    ("terminal_status", "reason"),
    [
        pytest.param("blocked", "codex_runtime_unavailable", id="blocked"),
        pytest.param("failed", "codex_process_failed", id="failed"),
        pytest.param("interrupted", "interrupted", id="interrupted"),
    ],
)
def test_reader_terminal_run_projects_its_historical_stage_state(
    status_roots: tuple[Path, Path, Path],
    terminal_status: str,
    reason: str,
) -> None:
    from gezhi._literature_status import project_literature_work_status_v1
    from gezhi._windows_data_root import open_validated_data_root_v1

    base, literature, _knowledge = status_roots
    pdf_path = base / "reader-terminal.pdf"
    write_text_pdf(
        pdf_path,
        "This native PDF has enough searchable text for Reader status projection.",
    )
    added = _run_add(literature, pdf_path)
    work_id = str(added["work_id"])
    resumed = _run_resume(literature, work_id)
    assert resumed.returncode == 2

    semantic_runs = (
        literature
        / "works"
        / work_id
        / "sources"
        / str(added["source_id"])
        / "semantic"
        / "runs"
    )
    run_directories = [path for path in semantic_runs.iterdir() if path.is_dir()]
    assert len(run_directories) == 1
    manifest_path = run_directories[0] / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["status"] == "blocked"
    if terminal_status == "failed":
        from gezhi import _literature_reader as reader

        attempt = {
            "attempt_ordinal": 1,
            "cached_input_tokens": None,
            "elapsed_ms": 1,
            "exit_code": 71,
            "failure_class": "process_error",
            "finished_at": "2026-08-31T12:00:01.000Z",
            "input_tokens": None,
            "output_tokens": None,
            "reasoning_output_tokens": None,
            "resource_ledger_count": 0,
            "schema_version": "gezhi.literature_codex_attempt.v1",
            "started_at": "2026-08-31T12:00:00.000Z",
            "usage_unavailable": True,
        }
        attempt_dir = run_directories[0] / "attempts" / "01"
        attempt_dir.mkdir()
        (attempt_dir / "attempt.json").write_bytes(_canonical_json_line(attempt))
        (attempt_dir / "events.jsonl").write_bytes(b"not-json\n")
        manifest["attempt_count"] = 1
        manifest["attempts"] = [attempt]
        manifest["usage_totals"] = {
            "cached_input_tokens": None,
            "input_tokens": None,
            "output_tokens": None,
            "reasoning_output_tokens": None,
        }
        manifest["assets"] = reader._asset_entries(run_directories[0])
    if terminal_status != "blocked":
        manifest["status"] = terminal_status
        manifest["reason"] = reason
        manifest_path.write_bytes(_canonical_json_line(manifest))
    before = _tree_snapshot(literature)

    with open_validated_data_root_v1(str(literature)) as root:
        report = project_literature_work_status_v1(
            root,
            work_id,
            include_intake_staging=True,
        )

    assert report is not None
    assert report["stages"][3] == {
        "stage": "read",
        "status": terminal_status,
    }
    assert before == _tree_snapshot(literature)


def test_live_work_writer_and_reader_staging_project_read_as_running(
    status_roots: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    from gezhi._literature_status import project_literature_work_status_v1
    from gezhi._windows_data_root import open_validated_data_root_v1
    from gezhi._windows_ownership import try_acquire_work_writer_v1

    base, literature, _knowledge = status_roots
    pdf_path = base / "reader-running.pdf"
    write_text_pdf(
        pdf_path,
        "This native PDF has enough searchable text for live Reader projection.",
    )
    added = _run_add(literature, pdf_path)
    work_id = str(added["work_id"])
    _stop_before_reader_sitecustomize(tmp_path)
    resumed = _run_resume(
        literature,
        work_id,
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )
    assert resumed.returncode == 2

    semantic_staging = (
        literature
        / "works"
        / work_id
        / "sources"
        / str(added["source_id"])
        / "semantic"
        / ".staging"
    )
    semantic_staging.mkdir(parents=True)
    (semantic_staging / "semrun_00000000-0000-4000-8000-000000000086").mkdir()
    before = _tree_snapshot(literature)

    with open_validated_data_root_v1(str(literature)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_work_writer_v1(identity, work_id)
        assert owner is not None
        try:
            report = project_literature_work_status_v1(
                root,
                work_id,
                include_intake_staging=True,
            )
        finally:
            owner.close()

    assert report is not None
    assert report["stages"][3] == {"stage": "read", "status": "running"}
    assert before == _tree_snapshot(literature)


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


@pytest.mark.parametrize(
    ("name", "is_directory"),
    [
        pytest.param("not-an-answer", True, id="invalid-directory-name"),
        pytest.param(
            "ans_00000000-0000-4000-8000-000000000084",
            False,
            id="answer-id-file",
        ),
    ],
)
def test_unattributable_answer_staging_only_counts_as_overall_inconsistent(
    status_roots: tuple[Path, Path, Path],
    name: str,
    is_directory: bool,
) -> None:
    from gezhi._knowledge_status import project_knowledge_status_v1
    from gezhi._windows_data_root import open_validated_data_root_v1

    _base, _literature, knowledge = status_roots
    entry = knowledge / "answers" / ".staging" / name
    entry.parent.mkdir(parents=True)
    if is_directory:
        entry.mkdir()
    else:
        entry.write_bytes(b"not a directory")
    before = _tree_snapshot(knowledge)
    work_id = "wrk_123e4567-e89b-42d3-a456-426614174000"

    with open_validated_data_root_v1(str(knowledge)) as root:
        overall = project_knowledge_status_v1(root, work_id=None)
        scoped = project_knowledge_status_v1(root, work_id=work_id)

    assert overall["availability"] == "partial"
    assert overall["recovery"] == {
        "staging_count": 0,
        "orphaned_count": 0,
        "quarantined_count": 0,
        "inconsistent_count": 1,
    }
    assert scoped["availability"] == "ready"
    assert scoped["recovery"] == {
        "staging_count": 0,
        "orphaned_count": 0,
        "quarantined_count": 0,
        "inconsistent_count": 0,
    }
    assert before == _tree_snapshot(knowledge)


def test_unavailable_answer_subroot_preserves_a_partial_projection(
    status_roots: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi._knowledge_status import project_knowledge_status_v1
    from gezhi._windows_data_root import (
        DataRootOpenErrorV1,
        ValidatedDataRootV1,
        open_validated_data_root_v1,
    )

    _base, _literature, knowledge = status_roots
    (knowledge / "answers").mkdir()
    before = _tree_snapshot(knowledge)
    original_open = ValidatedDataRootV1.open_relative_data_root_v1

    def fail_answer_open(
        self: ValidatedDataRootV1,
        parts: tuple[str, ...],
    ) -> ValidatedDataRootV1:
        if parts == ("answers",):
            raise DataRootOpenErrorV1("unavailable")
        return original_open(self, parts)

    monkeypatch.setattr(
        ValidatedDataRootV1,
        "open_relative_data_root_v1",
        fail_answer_open,
    )
    work_id = "wrk_123e4567-e89b-42d3-a456-426614174000"

    with open_validated_data_root_v1(str(knowledge)) as root:
        overall = project_knowledge_status_v1(root, work_id=None)
        scoped = project_knowledge_status_v1(root, work_id=work_id)

    assert overall["availability"] == "partial"
    assert overall["answer_status_counts"] == []
    assert overall["recovery"] == {
        "staging_count": 0,
        "orphaned_count": 0,
        "quarantined_count": 0,
        "inconsistent_count": 0,
    }
    assert scoped["availability"] == "partial"
    assert scoped["related_answer_status_counts"] == []
    assert scoped["recovery"] == overall["recovery"]
    assert before == _tree_snapshot(knowledge)


def test_answer_work_relation_requires_a_matching_validated_source_snapshot() -> None:
    from support.knowledge_handoff_factory_v1 import accepted_handoff_v1

    from gezhi._knowledge_status import (
        KnowledgeStatusProjectionFailedV1,
        _answer_work_ids,
    )

    handoff = accepted_handoff_v1(
        ordinal=85,
        statement_text="Answer 与 Work 的关系必须来自完整验证的来源快照。",
        source_terms=["Answer", "Work", "快照"],
    )
    record = json.loads(handoff.candidates_bytes)
    item = {
        "candidate": record["candidate"],
        "citation": record["citation"],
        "descriptor_snapshots": record["descriptor_snapshots"],
        "evidence_snapshots": record["evidence_snapshots"],
        "governance": {
            "intake_status": "active",
            "promotion_status": "not_promoted",
            "review_status": "accepted",
        },
        "rank": 1,
    }
    view = {
        "answer_kind": "candidate_backed",
        "candidate_count": 1,
        "items": [item],
        "schema_version": "gezhi.retrieval_view.v1",
    }
    view_bytes = (
        json.dumps(
            view,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    work_id = record["candidate"]["payload"]["work_id"]

    assert _answer_work_ids(view_bytes) == frozenset({work_id})

    mismatched = json.loads(view_bytes)
    mismatched["items"][0]["citation"]["work_id"] = (
        "wrk_223e4567-e89b-42d3-a456-426614174000"
    )
    mismatched_bytes = (
        json.dumps(
            mismatched,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )

    with pytest.raises(KnowledgeStatusProjectionFailedV1):
        _answer_work_ids(mismatched_bytes)


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
