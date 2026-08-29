from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from launcher_support import SOURCE_ROOT, launcher_commands, run_launcher
from literature_pdf_support import write_text_pdf

_DOUBLE = Path(__file__).parent / "support" / "codex_child_executable_double_v1.py"


@dataclass(frozen=True, slots=True)
class _ReviewCandidateTemplateV1:
    candidate_id: str
    literature_root: Path
    payload_sha256: str
    source_id: str
    work_id: str


def _canonical_file_bytes(value: object) -> bytes:
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


def _canonical_payload_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _handoff_id(
    template: _ReviewCandidateTemplateV1,
    *,
    action: str,
    revision: int,
) -> str:
    identity = {
        "action": action,
        "candidate_id": template.candidate_id,
        "payload_sha256": template.payload_sha256,
        "review_revision": revision,
        "schema_version": "gezhi.reviewed_handoff_identity.v1",
    }
    return "hnd_" + hashlib.sha256(_canonical_payload_bytes(identity)).hexdigest()[:24]


def _expected_review_result(
    template: _ReviewCandidateTemplateV1,
    *,
    decision_disposition: str,
    handoff_action: str,
    handoff_id: str | None,
    handoff_status: str,
    import_status: str,
    revision: int,
    status: str,
) -> dict[str, object]:
    return {
        "candidate_id": template.candidate_id,
        "decision_disposition": decision_disposition,
        "handoff_action": handoff_action,
        "handoff_id": handoff_id,
        "handoff_status": handoff_status,
        "import_status": import_status,
        "intake_status": None,
        "payload_sha256": template.payload_sha256,
        "review_revision": revision,
        "review_status": status,
        "schema_version": "gezhi.literature_review_result.v1",
        "work_id": template.work_id,
    }


def _canonicalize_only_sitecustomize(site_root: Path) -> None:
    source = """
import gezhi._literature_reader as reader


def stop_before_reader(*_args, **_kwargs):
    raise reader.ReaderStageStoppedV1(
        "blocked", "codex_runtime_unavailable"
    )


reader.advance_reader_v1 = stop_before_reader
"""
    (site_root / "sitecustomize.py").write_text(source, encoding="utf-8")


def _successful_reader_sitecustomize(site_root: Path) -> None:
    source = """
import os
import sys
from pathlib import Path

import gezhi._literature_reader as reader
from gezhi._codex_child_process import AttemptTerminalEvidenceV1
from gezhi._codex_child_process import NeverCancelledV1
from gezhi._codex_child_process import _run_codex_child_test_double_v1
from gezhi._codex_role_plan import _freeze_test_double_launch_v1


def run_double(request):
    capture_parent = request.attempt_root / "captures"
    capture = capture_parent / f"{request.attempt_ordinal:02d}"
    staging = capture_parent / f".{request.attempt_ordinal:02d}.codex-stage"
    final_spool = staging / ".final_message.spool"
    plan = _freeze_test_double_launch_v1(
        executable=Path(sys.executable),
        arguments=(
            "-I",
            "-B",
            os.environ["REVIEW_DOUBLE_EXE"],
            "final-from-file",
            "--final",
            str(final_spool),
            "--payload-file",
            os.environ["REVIEW_DOUBLE_FINAL"],
        ),
        prompt=request.prompt,
        attempt_ordinal=request.attempt_ordinal,
        working_directory=request.attempt_root / "working",
        capture_directory=capture,
        staging_directory=staging,
        temporary_directory=request.attempt_root / "temporary",
        source_environment={"SystemRoot": os.environ["SystemRoot"]},
        timeout_seconds=10,
        capture_profile="literature",
    )
    result = _run_codex_child_test_double_v1(plan, NeverCancelledV1())
    assert isinstance(result, AttemptTerminalEvidenceV1), result
    return result


reader._run_role_attempt_v1 = run_double
reader._prepare_role_invocation_v1 = lambda: object()
"""
    (site_root / "sitecustomize.py").write_text(source, encoding="utf-8")


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
    assert completed.returncode == 0, (completed.stdout + completed.stderr).decode(
        errors="replace"
    )
    return json.loads(completed.stdout)["result"]


@pytest.fixture(scope="module")
def review_candidate_template() -> Iterator[_ReviewCandidateTemplateV1]:
    data_container = Path(r"E:\Gezhi\data")
    runtime_container = Path(r"E:\gztest")
    data_container.mkdir(parents=True, exist_ok=True)
    runtime_container.mkdir(parents=True, exist_ok=True)
    suffix = "v" + uuid.uuid4().hex[:7]
    base = data_container / suffix
    runtime = runtime_container / suffix
    literature_root = base / "lit"
    literature_root.mkdir(parents=True)
    runtime.mkdir()
    pdf_path = base / "paper.pdf"
    try:
        write_text_pdf(
            pdf_path,
            "A direct evidence sentence is available for review and handoff.",
        )
        added = _run_add(literature_root, pdf_path)
        work_id = str(added["work_id"])
        source_id = str(added["source_id"])
        source_dir = literature_root / "works" / work_id / "sources" / source_id

        canonical_site = runtime / "canonical-site"
        canonical_site.mkdir()
        _canonicalize_only_sitecustomize(canonical_site)
        canonicalized = run_launcher(
            launcher_commands(
                (
                    "--literature-data-root",
                    str(literature_root),
                    "literature",
                    "resume",
                    work_id,
                    "--json",
                )
            )[1],
            pythonpath_roots=(canonical_site, SOURCE_ROOT),
        )
        assert canonicalized.returncode == 2, (
            canonicalized.stdout + canonicalized.stderr
        ).decode(errors="replace")
        canonical_current = json.loads(
            (source_dir / "canonical" / "current.json").read_bytes()
        )
        canonical_run = (
            source_dir / "canonical" / "runs" / str(canonical_current["run_id"])
        )
        block = json.loads(
            (canonical_run / "blocks.jsonl").read_bytes().splitlines()[0]
        )
        statement = {
            "evidence_block_ids": [block["block_id"]],
            "risk_flags": [],
            "source_terms": ["direct evidence"],
            "support_kind": "direct",
            "text": "该资料包含可直接定位、可供人工审核的证据。",
        }
        reader_output = {
            "candidate_drafts": [
                {
                    "candidate_type": "claim",
                    "descriptor_refs": [],
                    "statement": statement,
                }
            ],
            "reading_result": {
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
                "synopsis": statement,
            },
            "schema_version": "gezhi.literature_reader_output.v1",
        }
        reader_final = runtime / "reader-final.json"
        reader_final.write_bytes(_canonical_file_bytes(reader_output))
        reader_site = runtime / "reader-site"
        reader_site.mkdir()
        _successful_reader_sitecustomize(reader_site)
        codex_home = runtime / "home"
        temporary = runtime / "temp"
        codex_home.mkdir()
        temporary.mkdir()
        resumed = run_launcher(
            launcher_commands(
                (
                    "--literature-data-root",
                    str(literature_root),
                    "literature",
                    "resume",
                    work_id,
                    "--json",
                )
            )[1],
            pythonpath_roots=(reader_site, SOURCE_ROOT),
            environment_updates={
                "CODEX_HOME": str(codex_home),
                "REVIEW_DOUBLE_EXE": str(_DOUBLE),
                "REVIEW_DOUBLE_FINAL": str(reader_final),
                "TEMP": str(temporary),
                "TMP": str(temporary),
            },
            timeout=30,
        )
        assert resumed.returncode == 2, (resumed.stdout + resumed.stderr).decode(
            errors="replace"
        )
        result = json.loads(resumed.stdout)["result"]
        candidate_id = str(result["pending_candidate_ids"][0])
        materializations = source_dir / "semantic" / "materializations"
        materialization_current = json.loads(
            (materializations / "current.json").read_bytes()
        )
        materialization_run = (
            materializations / "runs" / str(materialization_current["run_id"])
        )
        candidate = json.loads(
            (materialization_run / "result" / "candidate_knowledge.jsonl").read_bytes()
        )
        assert candidate["candidate_id"] == candidate_id
        yield _ReviewCandidateTemplateV1(
            candidate_id=candidate_id,
            literature_root=literature_root,
            payload_sha256=str(candidate["payload_sha256"]),
            source_id=source_id,
            work_id=work_id,
        )
    finally:
        resolved_base = base.resolve(strict=True)
        resolved_runtime = runtime.resolve(strict=True)
        assert resolved_base.parent == data_container.resolve(strict=True)
        assert resolved_runtime.parent == runtime_container.resolve(strict=True)
        assert resolved_base.name == suffix == resolved_runtime.name
        shutil.rmtree(resolved_base)
        shutil.rmtree(resolved_runtime)


@pytest.fixture
def review_candidate_root(
    review_candidate_template: _ReviewCandidateTemplateV1,
) -> Iterator[tuple[Path, _ReviewCandidateTemplateV1]]:
    container = Path(r"E:\Gezhi\data")
    suffix = "v" + uuid.uuid4().hex[:7]
    base = container / suffix
    literature_root = base / "lit"
    shutil.copytree(review_candidate_template.literature_root, literature_root)
    try:
        yield literature_root, review_candidate_template
    finally:
        resolved = base.resolve(strict=True)
        assert resolved.parent == container.resolve(strict=True)
        assert resolved.name == suffix
        shutil.rmtree(resolved)


@pytest.fixture
def review_empty_root() -> Iterator[Path]:
    container = Path(r"E:\Gezhi\data")
    container.mkdir(parents=True, exist_ok=True)
    suffix = "v" + uuid.uuid4().hex[:7]
    base = container / suffix
    literature_root = base / "lit"
    literature_root.mkdir(parents=True)
    try:
        yield literature_root
    finally:
        resolved = base.resolve(strict=True)
        assert resolved.parent == container.resolve(strict=True)
        assert resolved.name == suffix
        shutil.rmtree(resolved)


def _run_review(
    data_root: Path,
    candidate_id: str,
    action: str,
    *,
    launcher_index: int,
) -> object:
    return run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(data_root),
                "literature",
                "review",
                candidate_id,
                action,
                "--json",
            )
        )[launcher_index]
    )


def _run_resume(
    data_root: Path,
    work_id: str,
    *,
    launcher_index: int,
) -> object:
    return run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(data_root),
                "literature",
                "resume",
                work_id,
                "--json",
            )
        )[launcher_index]
    )


def _resume_with_intake(
    data_root: Path,
    work_id: str,
    intake: object,
) -> object:
    from gezhi._literature_resume import resume_work
    from gezhi._windows_data_root import open_validated_data_root_v1

    with open_validated_data_root_v1(str(data_root)) as root:
        return resume_work(
            work_id,
            root=root,
            source_environment={},
            knowledge_intake=intake,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("launcher_index", [0, 1])
def test_raw_candidate_selector_is_rejected_before_asset_lookup(
    review_empty_root: Path,
    launcher_index: int,
) -> None:
    completed = _run_review(
        review_empty_root,
        "CAND_aaaaaaaaaaaaaaaaaaaaaaaa",
        "--reject",
        launcher_index=launcher_index,
    )

    assert completed.returncode == 2
    assert completed.stderr == b""
    assert json.loads(completed.stdout) == {
        "command": "literature.review",
        "diagnostics": [
            {
                "code": "literature.review.candidate_invalid.v1",
                "context": {},
            }
        ],
        "outcome": "blocked",
        "result": None,
        "schema_version": "gezhi.cli_result.v1",
    }


@pytest.mark.parametrize("launcher_index", [0, 1])
def test_canonical_missing_candidate_is_not_found(
    review_empty_root: Path,
    launcher_index: int,
) -> None:
    completed = _run_review(
        review_empty_root,
        "cand_aaaaaaaaaaaaaaaaaaaaaaaa",
        "--defer",
        launcher_index=launcher_index,
    )

    assert completed.returncode == 2
    assert completed.stderr == b""
    assert json.loads(completed.stdout) == {
        "command": "literature.review",
        "diagnostics": [
            {
                "code": "literature.review.candidate_not_found.v1",
                "context": {},
            }
        ],
        "outcome": "blocked",
        "result": None,
        "schema_version": "gezhi.cli_result.v1",
    }


@pytest.mark.parametrize("launcher_index", [0, 1])
def test_unavailable_literature_root_stops_before_candidate_lookup(
    review_empty_root: Path,
    launcher_index: int,
) -> None:
    missing = review_empty_root.parent / "missing-literature"
    assert not missing.exists()

    completed = _run_review(
        missing,
        "cand_aaaaaaaaaaaaaaaaaaaaaaaa",
        "--reject",
        launcher_index=launcher_index,
    )

    assert completed.returncode == 2
    assert completed.stderr == b""
    assert json.loads(completed.stdout) == {
        "command": "literature.review",
        "diagnostics": [
            {
                "code": "literature.review.data_root_unavailable.v1",
                "context": {"data_root": "literature"},
            }
        ],
        "outcome": "blocked",
        "result": None,
        "schema_version": "gezhi.cli_result.v1",
    }


def test_candidate_id_mentioned_only_in_statement_text_is_not_a_binding(
    review_empty_root: Path,
) -> None:
    target = "cand_aaaaaaaaaaaaaaaaaaaaaaaa"
    run = (
        review_empty_root
        / "works"
        / "wrk_123e4567-e89b-42d3-a456-426614174000"
        / "sources"
        / "src_bbbbbbbbbbbbbbbbbbbbbbbb"
        / "semantic"
        / "materializations"
        / "runs"
        / "matrun_123e4567-e89b-42d3-a456-426614174000"
        / "result"
    )
    run.mkdir(parents=True)
    (run / "candidate_knowledge.jsonl").write_bytes(
        _canonical_file_bytes(
            {
                "candidate_id": "cand_bbbbbbbbbbbbbbbbbbbbbbbb",
                "payload": {"statement": {"text": target}},
            }
        )
    )

    completed = _run_review(
        review_empty_root,
        target,
        "--reject",
        launcher_index=1,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["diagnostics"] == [
        {"code": "literature.review.candidate_not_found.v1", "context": {}}
    ]


@pytest.mark.parametrize("launcher_index", [0, 1])
def test_reject_commits_one_append_only_decision_and_no_action_receipt(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    launcher_index: int,
) -> None:
    literature_root, template = review_candidate_root

    completed = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=launcher_index,
    )

    assert completed.returncode == 0, (completed.stdout + completed.stderr).decode(
        errors="replace"
    )
    assert completed.stderr == b""
    expected_result = {
        "candidate_id": template.candidate_id,
        "decision_disposition": "created",
        "handoff_action": "none",
        "handoff_id": None,
        "handoff_status": "not_required",
        "import_status": "not_required",
        "intake_status": None,
        "payload_sha256": template.payload_sha256,
        "review_revision": 1,
        "review_status": "rejected",
        "schema_version": "gezhi.literature_review_result.v1",
        "work_id": template.work_id,
    }
    assert json.loads(completed.stdout) == {
        "command": "literature.review",
        "diagnostics": [],
        "outcome": "succeeded",
        "result": expected_result,
        "schema_version": "gezhi.cli_result.v1",
    }

    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    decision_bytes = (candidate_reviews / "1.json").read_bytes()
    decision = json.loads(decision_bytes)
    assert re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:"
        r"[0-9]{2}\.[0-9]{3}Z",
        decision.pop("decided_at"),
    )
    assert decision == {
        "candidate_id": template.candidate_id,
        "payload_sha256": template.payload_sha256,
        "review_revision": 1,
        "review_status": "rejected",
        "reviewer_kind": "local_human_cli",
        "schema_version": "gezhi.review_decision.v1",
        "work_id": template.work_id,
    }
    assert json.loads((candidate_reviews / "current.json").read_bytes()) == {
        "candidate_id": template.candidate_id,
        "decision_sha256": hashlib.sha256(decision_bytes).hexdigest(),
        "payload_sha256": template.payload_sha256,
        "review_revision": 1,
        "schema_version": "gezhi.review_decision_current.v1",
        "work_id": template.work_id,
    }
    assert json.loads((candidate_reviews / "no_actions" / "1.json").read_bytes()) == {
        "candidate_id": template.candidate_id,
        "payload_sha256": template.payload_sha256,
        "reason": "never_imported",
        "review_revision": 1,
        "review_status": "rejected",
        "schema_version": "gezhi.review_no_action_receipt.v1",
        "work_id": template.work_id,
    }
    assert not (literature_root / "handoffs").exists()


def test_repeating_reject_reuses_the_same_decision_and_no_action_bytes(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    literature_root, template = review_candidate_root
    first = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=1,
    )
    assert first.returncode == 0
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    immutable_paths = (
        candidate_reviews / "1.json",
        candidate_reviews / "current.json",
        candidate_reviews / "no_actions" / "1.json",
    )
    before = tuple(path.read_bytes() for path in immutable_paths)

    repeated = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=0,
    )

    assert repeated.returncode == 0
    assert repeated.stderr == b""
    assert json.loads(repeated.stdout)["result"] == _expected_review_result(
        template,
        decision_disposition="unchanged",
        handoff_action="none",
        handoff_id=None,
        handoff_status="not_required",
        import_status="not_required",
        revision=1,
        status="rejected",
    )
    assert tuple(path.read_bytes() for path in immutable_paths) == before
    assert not (candidate_reviews / "2.json").exists()


def test_changed_nonaccepted_action_appends_revision_two_without_rewriting_one(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    literature_root, template = review_candidate_root
    rejected = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=1,
    )
    assert rejected.returncode == 0
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    revision_one = (candidate_reviews / "1.json").read_bytes()
    no_action_one = (candidate_reviews / "no_actions" / "1.json").read_bytes()

    deferred = _run_review(
        literature_root,
        template.candidate_id,
        "--defer",
        launcher_index=0,
    )

    assert deferred.returncode == 0
    assert deferred.stderr == b""
    assert json.loads(deferred.stdout)["result"] == _expected_review_result(
        template,
        decision_disposition="created",
        handoff_action="none",
        handoff_id=None,
        handoff_status="not_required",
        import_status="not_required",
        revision=2,
        status="deferred",
    )
    assert (candidate_reviews / "1.json").read_bytes() == revision_one
    assert (candidate_reviews / "no_actions" / "1.json").read_bytes() == no_action_one
    revision_two = (candidate_reviews / "2.json").read_bytes()
    assert json.loads(revision_two)["review_status"] == "deferred"
    assert (
        json.loads((candidate_reviews / "no_actions" / "2.json").read_bytes())[
            "review_revision"
        ]
        == 2
    )
    assert json.loads((candidate_reviews / "current.json").read_bytes()) == {
        "candidate_id": template.candidate_id,
        "decision_sha256": hashlib.sha256(revision_two).hexdigest(),
        "payload_sha256": template.payload_sha256,
        "review_revision": 2,
        "schema_version": "gezhi.review_decision_current.v1",
        "work_id": template.work_id,
    }


def test_accept_commits_self_contained_handoff_then_blocks_only_on_import(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    literature_root, template = review_candidate_root
    expected_handoff_id = _handoff_id(template, action="accept", revision=1)

    accepted = _run_review(
        literature_root,
        template.candidate_id,
        "--accept",
        launcher_index=1,
    )

    assert accepted.returncode == 2, (accepted.stdout + accepted.stderr).decode(
        errors="replace"
    )
    assert accepted.stderr == b""
    assert json.loads(accepted.stdout) == {
        "command": "literature.review",
        "diagnostics": [
            {
                "code": "literature.review.import_blocked.v1",
                "context": {},
            }
        ],
        "outcome": "blocked",
        "result": _expected_review_result(
            template,
            decision_disposition="created",
            handoff_action="accept",
            handoff_id=expected_handoff_id,
            handoff_status="committed",
            import_status="pending",
            revision=1,
            status="accepted",
        ),
        "schema_version": "gezhi.cli_result.v1",
    }

    handoff = (
        literature_root / "works" / template.work_id / "handoffs" / expected_handoff_id
    )
    assert {path.name for path in handoff.iterdir()} == {
        "candidates.jsonl",
        "manifest.json",
    }
    candidates_bytes = (handoff / "candidates.jsonl").read_bytes()
    manifest_bytes = (handoff / "manifest.json").read_bytes()
    assert candidates_bytes.endswith(b"\n") and candidates_bytes.count(b"\n") == 1
    record = json.loads(candidates_bytes)
    assert set(record) == {
        "action",
        "candidate",
        "citation",
        "descriptor_snapshots",
        "evidence_snapshots",
        "review_receipt",
        "schema_version",
    }
    assert record["action"] == "accept"
    assert record["candidate"]["candidate_id"] == template.candidate_id
    assert record["candidate"]["payload_sha256"] == template.payload_sha256
    assert record["descriptor_snapshots"] == []
    assert record["review_receipt"] == {
        "review_revision": 1,
        "review_status": "accepted",
        "reviewer_kind": "local_human_cli",
    }
    assert set(record["citation"]) == {
        "arxiv_id",
        "author_count",
        "doi",
        "primary_authors",
        "source_id",
        "source_sha256",
        "title",
        "work_id",
        "year",
    }
    assert len(record["evidence_snapshots"]) == 1
    evidence = record["evidence_snapshots"][0]
    assert set(evidence) == {"excerpt", "page_index", "pointer"}
    assert evidence["excerpt"]
    assert evidence["pointer"]["canonical_content_sha256"]
    manifest = json.loads(manifest_bytes)
    assert manifest["handoff_id"] == expected_handoff_id
    assert manifest["candidates_sha256"] == hashlib.sha256(candidates_bytes).hexdigest()
    assert manifest["record_count"] == 1
    assert manifest["source_id"] == template.source_id
    assert manifest["work_id"] == template.work_id

    decision_path = (
        literature_root
        / "works"
        / template.work_id
        / "reviews"
        / template.candidate_id
        / "1.json"
    )
    candidate_reviews = decision_path.parent
    assert not (candidate_reviews / "import_attempts").exists()
    assert not (candidate_reviews / "imports").exists()
    immutable_before = (
        decision_path.read_bytes(),
        candidates_bytes,
        manifest_bytes,
    )
    repeated = _run_review(
        literature_root,
        template.candidate_id,
        "--accept",
        launcher_index=0,
    )
    assert repeated.returncode == 2
    assert json.loads(repeated.stdout)["result"] == _expected_review_result(
        template,
        decision_disposition="unchanged",
        handoff_action="accept",
        handoff_id=expected_handoff_id,
        handoff_status="committed",
        import_status="pending",
        revision=1,
        status="accepted",
    )
    assert (
        decision_path.read_bytes(),
        (handoff / "candidates.jsonl").read_bytes(),
        (handoff / "manifest.json").read_bytes(),
    ) == immutable_before


def test_single_unpointed_decision_recovers_current_without_new_revision(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    literature_root, template = review_candidate_root
    rejected = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=1,
    )
    assert rejected.returncode == 0
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    current_path = candidate_reviews / "current.json"
    expected_current = current_path.read_bytes()
    current_path.unlink()

    recovered = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=0,
    )

    assert recovered.returncode == 0
    assert json.loads(recovered.stdout)["result"]["decision_disposition"] == (
        "unchanged"
    )
    assert current_path.read_bytes() == expected_current
    assert not (candidate_reviews / "2.json").exists()


def test_multiple_unpointed_decisions_are_not_guessed(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    literature_root, template = review_candidate_root
    assert (
        _run_review(
            literature_root,
            template.candidate_id,
            "--reject",
            launcher_index=1,
        ).returncode
        == 0
    )
    assert (
        _run_review(
            literature_root,
            template.candidate_id,
            "--defer",
            launcher_index=1,
        ).returncode
        == 0
    )
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    (candidate_reviews / "current.json").unlink()

    stopped = _run_review(
        literature_root,
        template.candidate_id,
        "--defer",
        launcher_index=0,
    )

    assert stopped.returncode == 1
    assert json.loads(stopped.stdout) == {
        "command": "literature.review",
        "diagnostics": [
            {
                "code": "literature.review.review_state_invalid.v1",
                "context": {},
            }
        ],
        "outcome": "failed",
        "result": None,
        "schema_version": "gezhi.cli_result.v1",
    }
    assert not (candidate_reviews / "current.json").exists()
    assert not (candidate_reviews / "3.json").exists()


def test_candidate_from_an_inactive_historical_source_remains_reviewable(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    literature_root, template = review_candidate_root
    second_pdf = literature_root.parent / "second.pdf"
    write_text_pdf(second_pdf, "A replacement source becomes active for this Work.")
    added = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "literature",
                "add",
                str(second_pdf),
                "--work-id",
                template.work_id,
                "--json",
            )
        )[1]
    )
    assert added.returncode == 0, (added.stdout + added.stderr).decode(errors="replace")
    assert json.loads(added.stdout)["result"]["source_id"] != template.source_id

    reviewed = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=0,
    )

    assert reviewed.returncode == 0, (reviewed.stdout + reviewed.stderr).decode(
        errors="replace"
    )
    assert json.loads(reviewed.stdout)["result"] == _expected_review_result(
        template,
        decision_disposition="created",
        handoff_action="none",
        handoff_id=None,
        handoff_status="not_required",
        import_status="not_required",
        revision=1,
        status="rejected",
    )


def test_rehashed_tampered_handoff_is_rejected_against_source_authority(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    literature_root, template = review_candidate_root
    accepted = _run_review(
        literature_root,
        template.candidate_id,
        "--accept",
        launcher_index=1,
    )
    assert accepted.returncode == 2
    handoff_id = str(json.loads(accepted.stdout)["result"]["handoff_id"])
    handoff = literature_root / "works" / template.work_id / "handoffs" / handoff_id
    record = json.loads((handoff / "candidates.jsonl").read_bytes())
    record["citation"]["title"] = "tampered but rehashed"
    candidates_bytes = _canonical_file_bytes(record)
    (handoff / "candidates.jsonl").write_bytes(candidates_bytes)
    manifest = json.loads((handoff / "manifest.json").read_bytes())
    manifest["candidates_sha256"] = hashlib.sha256(candidates_bytes).hexdigest()
    (handoff / "manifest.json").write_bytes(_canonical_file_bytes(manifest))

    stopped = _run_review(
        literature_root,
        template.candidate_id,
        "--accept",
        launcher_index=0,
    )

    assert stopped.returncode == 1
    document = json.loads(stopped.stdout)
    assert document["outcome"] == "failed"
    assert document["diagnostics"] == [
        {"code": "literature.review.handoff_failed.v1", "context": {}}
    ]
    assert document["result"] == _expected_review_result(
        template,
        decision_disposition="unchanged",
        handoff_action="accept",
        handoff_id=handoff_id,
        handoff_status="pending",
        import_status="pending",
        revision=1,
        status="accepted",
    )


def test_relevant_candidate_materialization_tamper_is_integrity_lost(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    literature_root, template = review_candidate_root
    materializations = (
        literature_root
        / "works"
        / template.work_id
        / "sources"
        / template.source_id
        / "semantic"
        / "materializations"
    )
    current = json.loads((materializations / "current.json").read_bytes())
    candidates_path = (
        materializations
        / "runs"
        / str(current["run_id"])
        / "result"
        / "candidate_knowledge.jsonl"
    )
    candidate = json.loads(candidates_path.read_bytes())
    candidate["payload"]["statement"]["text"] = "tampered"
    candidates_path.write_bytes(_canonical_file_bytes(candidate))

    stopped = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=1,
    )

    assert stopped.returncode == 1
    assert json.loads(stopped.stdout) == {
        "command": "literature.review",
        "diagnostics": [
            {
                "code": "literature.review.candidate_integrity_lost.v1",
                "context": {},
            }
        ],
        "outcome": "failed",
        "result": None,
        "schema_version": "gezhi.cli_result.v1",
    }


def test_boolean_review_revision_cannot_impersonate_integer_one(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    literature_root, template = review_candidate_root
    assert (
        _run_review(
            literature_root,
            template.candidate_id,
            "--reject",
            launcher_index=1,
        ).returncode
        == 0
    )
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    decision_path = candidate_reviews / "1.json"
    decision = json.loads(decision_path.read_bytes())
    decision["review_revision"] = True
    decision_path.write_bytes(_canonical_file_bytes(decision))

    stopped = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=0,
    )

    assert stopped.returncode == 1
    assert json.loads(stopped.stdout)["diagnostics"] == [
        {"code": "literature.review.review_state_invalid.v1", "context": {}}
    ]


def test_review_uses_the_shared_cross_process_work_writer(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    from gezhi._windows_data_root import open_validated_data_root_v1
    from gezhi._windows_ownership import try_acquire_work_writer_v1

    literature_root, template = review_candidate_root
    with open_validated_data_root_v1(str(literature_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_work_writer_v1(identity, template.work_id)
        assert owner is not None
        with owner:
            stopped = _run_review(
                literature_root,
                template.candidate_id,
                "--reject",
                launcher_index=1,
            )

    assert stopped.returncode == 2
    assert json.loads(stopped.stdout) == {
        "command": "literature.review",
        "diagnostics": [{"code": "literature.review.work_busy.v1", "context": {}}],
        "outcome": "blocked",
        "result": None,
        "schema_version": "gezhi.cli_result.v1",
    }


def test_verified_import_receipts_drive_withdraw_and_are_reused_without_adapter(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    from gezhi._literature_review import (
        IntakeAppliedV1,
        ReviewCandidateCommandV1,
        ReviewedHandoffBytesV1,
        ReviewSucceededV1,
        review_candidate_v1,
    )
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    class RecordingIntake:
        def __init__(self) -> None:
            self.actions: list[str] = []

        def apply(self, handoff: ReviewedHandoffBytesV1) -> object:
            candidates_bytes = handoff.candidates_bytes
            action = str(json.loads(candidates_bytes)["action"])
            self.actions.append(action)
            return IntakeAppliedV1(
                "active" if action == "accept" else "withdrawn",
                "applied",
            )

    intake = RecordingIntake()
    with open_validated_data_root_v1(str(literature_root)) as root:
        accepted = review_candidate_v1(
            ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=intake,
        )
        rejected = review_candidate_v1(
            ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=intake,
        )
        repeated = review_candidate_v1(
            ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )

    assert type(accepted) is ReviewSucceededV1
    assert accepted.progress.import_status == "applied"
    assert accepted.progress.intake_status == "active"
    assert type(rejected) is ReviewSucceededV1
    assert rejected.progress.review_revision == 2
    assert rejected.progress.handoff_action == "withdraw"
    assert rejected.progress.intake_status == "withdrawn"
    assert type(repeated) is ReviewSucceededV1
    assert repeated.progress.decision_disposition == "unchanged"
    assert repeated.progress.intake_status == "withdrawn"
    assert intake.actions == ["accept", "withdraw"]

    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    for revision, action, status in (
        (1, "accept", "active"),
        (2, "withdraw", "withdrawn"),
    ):
        attempt = json.loads(
            (candidate_reviews / "import_attempts" / f"{revision}.json").read_bytes()
        )
        receipt = json.loads(
            (candidate_reviews / "imports" / f"{revision}.json").read_bytes()
        )
        assert attempt["schema_version"] == "gezhi.review_import_attempt.v1"
        assert attempt["action"] == action
        assert receipt == {
            **attempt,
            "intake_status": status,
            "schema_version": "gezhi.review_import_receipt.v1",
        }
    handoffs = literature_root / "works" / template.work_id / "handoffs"
    assert len([path for path in handoffs.iterdir() if path.name != ".staging"]) == 2
    assert not (candidate_reviews / "no_actions").exists()


def test_unresolved_import_attempt_is_replayed_before_a_new_human_decision(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    from gezhi._literature_review import (
        IntakeAppliedV1,
        ReviewBlockedV1,
        ReviewCandidateCommandV1,
        ReviewedHandoffBytesV1,
        ReviewIndeterminateV1,
        ReviewSucceededV1,
        review_candidate_v1,
    )
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    class CrashAfterApply:
        def apply(self, _handoff: ReviewedHandoffBytesV1) -> object:
            raise RuntimeError("simulated process loss after external apply")

    class RecoveringIntake:
        def __init__(self) -> None:
            self.actions: list[str] = []

        def apply(self, handoff: ReviewedHandoffBytesV1) -> object:
            action = str(json.loads(handoff.candidates_bytes)["action"])
            self.actions.append(action)
            return IntakeAppliedV1(
                "active" if action == "accept" else "withdrawn",
                "unchanged" if action == "accept" else "applied",
            )

    with open_validated_data_root_v1(str(literature_root)) as root:
        with pytest.raises(ReviewIndeterminateV1):
            review_candidate_v1(
                ReviewCandidateCommandV1(template.candidate_id, "accept"),
                root=root,
                knowledge_intake=CrashAfterApply(),
            )
        blocked = review_candidate_v1(
            ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )
        intake = RecoveringIntake()
        recovered = review_candidate_v1(
            ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=intake,
        )

    assert type(blocked) is ReviewBlockedV1
    assert blocked.cause.reason == "import_blocked"
    assert blocked.progress is not None
    assert blocked.progress.review_revision == 1
    assert blocked.progress.review_status == "accepted"
    assert type(recovered) is ReviewSucceededV1
    assert recovered.progress.review_revision == 2
    assert recovered.progress.review_status == "rejected"
    assert recovered.progress.handoff_action == "withdraw"
    assert recovered.progress.intake_status == "withdrawn"
    assert intake.actions == ["accept", "withdraw"]
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert (candidate_reviews / "imports" / "1.json").is_file()
    assert (candidate_reviews / "imports" / "2.json").is_file()
    assert not (candidate_reviews / "no_actions").exists()


def test_invalid_import_receipt_stops_before_appending_a_new_decision(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    from gezhi._literature_review import (
        IntakeAppliedV1,
        ReviewCandidateCommandV1,
        ReviewedHandoffBytesV1,
        ReviewFailedV1,
        ReviewSucceededV1,
        review_candidate_v1,
    )
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    class AppliedIntake:
        def apply(self, _handoff: ReviewedHandoffBytesV1) -> object:
            return IntakeAppliedV1("active", "applied")

    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    with open_validated_data_root_v1(str(literature_root)) as root:
        accepted = review_candidate_v1(
            ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=AppliedIntake(),
        )
        receipt_path = candidate_reviews / "imports" / "1.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["candidates_sha256"] = "0" * 64
        receipt_path.write_bytes(_canonical_file_bytes(receipt))
        stopped = review_candidate_v1(
            ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )

    assert type(accepted) is ReviewSucceededV1
    assert accepted.progress.import_status == "applied"
    assert type(stopped) is ReviewFailedV1
    assert stopped.cause.reason == "review_state_invalid"
    assert stopped.progress is None
    assert not (candidate_reviews / "2.json").exists()


def test_no_action_failure_preserves_the_committed_decision_as_pending_progress(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    def fail_no_action(*_args: object, **_kwargs: object) -> None:
        raise review._HandoffFailedV1("injected no-action failure")

    monkeypatch.setattr(review, "_commit_no_action_receipt", fail_no_action)
    with open_validated_data_root_v1(str(literature_root)) as root:
        stopped = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )

    assert type(stopped) is review.ReviewFailedV1
    assert stopped.cause.reason == "handoff_failed"
    assert stopped.progress is not None
    assert stopped.progress.decision_disposition == "created"
    assert stopped.progress.handoff_action == "none"
    assert stopped.progress.handoff_status == "pending"
    assert stopped.progress.import_status == "not_required"
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert (candidate_reviews / "1.json").is_file()
    assert (candidate_reviews / "current.json").is_file()
    assert not (candidate_reviews / "no_actions" / "1.json").exists()


def test_uncertain_current_replacement_never_becomes_a_handled_failed_receipt(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    def uncertain_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected current replace failure")

    monkeypatch.setattr(review.os, "replace", uncertain_replace)
    with (
        open_validated_data_root_v1(str(literature_root)) as root,
        pytest.raises(review.ReviewIndeterminateV1),
    ):
        review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )

    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert (candidate_reviews / "1.json").is_file()
    assert not (candidate_reviews / "current.json").exists()


def test_no_action_rename_failure_uses_private_staging_and_retry_succeeds(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root
    real_rename = review.os.rename
    failed = False

    def fail_first_no_action(source: object, target: object) -> None:
        nonlocal failed
        if not failed and Path(target).parent.name == "no_actions":
            failed = True
            raise OSError("injected no-action rename failure")
        real_rename(source, target)

    monkeypatch.setattr(review.os, "rename", fail_first_no_action)
    with open_validated_data_root_v1(str(literature_root)) as root:
        stopped = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )
        recovered = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )

    assert type(stopped) is review.ReviewFailedV1
    assert stopped.cause.reason == "handoff_failed"
    assert stopped.progress is not None
    assert stopped.progress.handoff_status == "pending"
    assert type(recovered) is review.ReviewSucceededV1
    assert recovered.progress.decision_disposition == "unchanged"
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert {path.name for path in (candidate_reviews / "no_actions").iterdir()} == {
        "1.json"
    }
    private_files = candidate_reviews.parent / ".staging" / ".files"
    assert any(
        path.name.startswith("no_actions.1.json.") for path in private_files.iterdir()
    )


def test_import_receipt_rename_failure_replays_the_unresolved_attempt(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    class IdempotentIntake:
        def __init__(self) -> None:
            self.actions: list[str] = []

        def apply(self, handoff: review.ReviewedHandoffBytesV1) -> object:
            action = str(json.loads(handoff.candidates_bytes)["action"])
            self.actions.append(action)
            return review.IntakeAppliedV1(
                "active",
                "applied" if len(self.actions) == 1 else "unchanged",
            )

    real_rename = review.os.rename
    failed = False

    def fail_first_import_receipt(source: object, target: object) -> None:
        nonlocal failed
        if not failed and Path(target).parent.name == "imports":
            failed = True
            raise OSError("injected import receipt rename failure")
        real_rename(source, target)

    monkeypatch.setattr(review.os, "rename", fail_first_import_receipt)
    intake = IdempotentIntake()
    with open_validated_data_root_v1(str(literature_root)) as root:
        with pytest.raises(review.ReviewIndeterminateV1):
            review.review_candidate_v1(
                review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
                root=root,
                knowledge_intake=intake,
            )
        recovered = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=intake,
        )

    assert type(recovered) is review.ReviewSucceededV1
    assert recovered.progress.decision_disposition == "unchanged"
    assert recovered.progress.import_status == "applied"
    assert intake.actions == ["accept", "accept"]
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert {path.name for path in (candidate_reviews / "imports").iterdir()} == {
        "1.json"
    }
    assert (candidate_reviews / "import_attempts" / "1.json").is_file()
    private_files = candidate_reviews.parent / ".staging" / ".files"
    assert any(
        path.name.startswith("imports.1.json.") for path in private_files.iterdir()
    )


def test_unknown_immutable_target_state_is_not_a_handled_failure(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root
    inspect_exact_file = review._inspect_exact_file

    def unknown_no_action(path: Path, payload: bytes) -> str:
        if path.parent.name == "no_actions" and path.name == "1.json":
            return "unknown"
        return inspect_exact_file(path, payload)

    monkeypatch.setattr(review, "_inspect_exact_file", unknown_no_action)
    with (
        open_validated_data_root_v1(str(literature_root)) as root,
        pytest.raises(review.ReviewIndeterminateV1),
    ):
        review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )

    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert (candidate_reviews / "1.json").is_file()
    assert (candidate_reviews / "current.json").is_file()
    assert not (candidate_reviews / "no_actions" / "1.json").exists()


def test_rename_after_move_still_requires_the_post_commit_root_checkpoint(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._literature_intake import AddStoppedV1
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root
    real_rename = review.os.rename
    root_checkpoint = review._root_checkpoint
    moved = False
    checkpoint_failed = False

    def move_then_report_failure(source: object, target: object) -> None:
        nonlocal moved
        if not moved and Path(target).parent.name == "no_actions":
            real_rename(source, target)
            moved = True
            raise OSError("rename completed before reporting failure")
        real_rename(source, target)

    def fail_post_commit_checkpoint(root: object) -> None:
        nonlocal checkpoint_failed
        if moved and not checkpoint_failed:
            checkpoint_failed = True
            raise AddStoppedV1("failed", "data_root_integrity_lost")
        root_checkpoint(root)

    monkeypatch.setattr(review.os, "rename", move_then_report_failure)
    monkeypatch.setattr(review, "_root_checkpoint", fail_post_commit_checkpoint)
    with open_validated_data_root_v1(str(literature_root)) as root:
        with pytest.raises(review.ReviewIndeterminateV1):
            review.review_candidate_v1(
                review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
                root=root,
                knowledge_intake=None,
            )
        recovered = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )

    assert moved is True
    assert checkpoint_failed is True
    assert type(recovered) is review.ReviewSucceededV1
    assert recovered.progress.decision_disposition == "unchanged"


def test_unreadable_formal_handoff_after_rename_is_indeterminate_and_recoverable(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root
    inspect_handoff = review._inspect_handoff_directory
    real_rename = review.os.rename
    formal_moved = False
    unavailable_reported = False

    def record_formal_move(source: object, target: object) -> None:
        nonlocal formal_moved
        real_rename(source, target)
        destination = Path(target)
        if destination.parent.name == "handoffs" and destination.name.startswith(
            "hnd_"
        ):
            formal_moved = True

    def unavailable_once(
        path: Path,
        expected: review.ReviewedHandoffBytesV1,
    ) -> str:
        nonlocal unavailable_reported
        if (
            formal_moved
            and not unavailable_reported
            and path.parent.name == "handoffs"
            and path.name.startswith("hnd_")
        ):
            unavailable_reported = True
            return "unknown"
        return inspect_handoff(path, expected)

    monkeypatch.setattr(review.os, "rename", record_formal_move)
    monkeypatch.setattr(review, "_inspect_handoff_directory", unavailable_once)
    with open_validated_data_root_v1(str(literature_root)) as root:
        with pytest.raises(review.ReviewIndeterminateV1):
            review.review_candidate_v1(
                review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
                root=root,
                knowledge_intake=None,
            )
        recovered = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=None,
        )

    assert formal_moved is True
    assert unavailable_reported is True
    assert type(recovered) is review.ReviewBlockedV1
    assert recovered.cause.reason == "import_blocked"
    assert recovered.progress is not None
    assert recovered.progress.handoff_status == "committed"


def test_no_action_after_a_prior_accept_import_is_rejected_before_apply(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    class AppliedIntake:
        def apply(self, _handoff: review.ReviewedHandoffBytesV1) -> object:
            return review.IntakeAppliedV1("active", "applied")

    class MustNotApply:
        def __init__(self) -> None:
            self.calls = 0

        def apply(self, _handoff: review.ReviewedHandoffBytesV1) -> object:
            self.calls += 1
            raise AssertionError("contradictory no-action reached KnowledgeIntake")

    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    with open_validated_data_root_v1(str(literature_root)) as root:
        accepted = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=AppliedIntake(),
        )
        rejected = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )
        no_actions = candidate_reviews / "no_actions"
        no_actions.mkdir()
        no_actions.joinpath("2.json").write_bytes(
            _canonical_file_bytes(
                {
                    "candidate_id": template.candidate_id,
                    "payload_sha256": template.payload_sha256,
                    "reason": "never_imported",
                    "review_revision": 2,
                    "review_status": "rejected",
                    "schema_version": "gezhi.review_no_action_receipt.v1",
                    "work_id": template.work_id,
                }
            )
        )
        intake = MustNotApply()
        stopped = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=intake,
        )

    assert type(accepted) is review.ReviewSucceededV1
    assert type(rejected) is review.ReviewBlockedV1
    assert type(stopped) is review.ReviewFailedV1
    assert stopped.cause.reason == "review_state_invalid"
    assert stopped.progress is None
    assert intake.calls == 0
    assert not (candidate_reviews / "import_attempts" / "2.json").exists()
    assert not (candidate_reviews / "imports" / "2.json").exists()


def test_root_drift_before_current_replace_keeps_committed_decision_progress(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._literature_intake import AddStoppedV1
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root
    real_rename = review.os.rename
    root_checkpoint = review._root_checkpoint
    atomic_replace = review.os.replace
    decision_published = False
    decision_sealed = False
    drifted = False
    replace_calls = 0

    def record_decision_publish(source: object, target: object) -> None:
        nonlocal decision_published
        real_rename(source, target)
        destination = Path(target)
        if (
            destination.name == "1.json"
            and destination.parent.name == template.candidate_id
        ):
            decision_published = True

    def drift_before_replace(root: object) -> None:
        nonlocal decision_sealed, drifted
        if decision_published and not decision_sealed:
            decision_sealed = True
        elif decision_sealed and not drifted:
            drifted = True
            raise AddStoppedV1("failed", "data_root_integrity_lost")
        root_checkpoint(root)

    def count_replace(*args: object, **kwargs: object) -> None:
        nonlocal replace_calls
        replace_calls += 1
        atomic_replace(*args, **kwargs)

    monkeypatch.setattr(review.os, "rename", record_decision_publish)
    monkeypatch.setattr(review, "_root_checkpoint", drift_before_replace)
    monkeypatch.setattr(review.os, "replace", count_replace)
    with open_validated_data_root_v1(str(literature_root)) as root:
        stopped = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )

    assert type(stopped) is review.ReviewFailedV1
    assert stopped.cause.reason == "data_root_integrity_lost"
    assert stopped.cause.data_root == "literature"
    assert stopped.progress is not None
    assert stopped.progress.review_revision == 1
    assert stopped.progress.review_status == "rejected"
    assert stopped.progress.handoff_action == "none"
    assert stopped.progress.handoff_status == "pending"
    assert replace_calls == 0
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert (candidate_reviews / "1.json").is_file()
    assert not (candidate_reviews / "current.json").exists()


def test_unreadable_decision_target_after_rename_is_indeterminate(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root
    real_rename = review.os.rename
    inspect_exact_file = review._inspect_exact_file
    decision_target: Path | None = None
    unavailable_reported = False

    def record_decision_publish(source: object, target: object) -> None:
        nonlocal decision_target
        real_rename(source, target)
        destination = Path(target)
        if (
            destination.name == "1.json"
            and destination.parent.name == template.candidate_id
        ):
            decision_target = destination

    def unavailable_once(path: Path, payload: bytes) -> str:
        nonlocal unavailable_reported
        if decision_target == path and not unavailable_reported:
            unavailable_reported = True
            return "unknown"
        return inspect_exact_file(path, payload)

    monkeypatch.setattr(review.os, "rename", record_decision_publish)
    monkeypatch.setattr(review, "_inspect_exact_file", unavailable_once)
    with (
        open_validated_data_root_v1(str(literature_root)) as root,
        pytest.raises(review.ReviewIndeterminateV1),
    ):
        review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )

    assert unavailable_reported is True


def test_orphan_decision_root_drift_returns_non_null_recovery_progress(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._literature_intake import AddStoppedV1
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root
    real_replace = review.os.replace
    replace_failed = False

    def fail_first_replace(source: object, target: object) -> None:
        nonlocal replace_failed
        if not replace_failed:
            replace_failed = True
            raise OSError("injected current replace failure")
        real_replace(source, target)

    monkeypatch.setattr(review.os, "replace", fail_first_replace)
    with open_validated_data_root_v1(str(literature_root)) as root:
        with pytest.raises(review.ReviewIndeterminateV1):
            review.review_candidate_v1(
                review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
                root=root,
                knowledge_intake=None,
            )

        monkeypatch.setattr(review.os, "replace", real_replace)
        real_checkpoint = review._root_checkpoint
        checkpoint_calls = 0
        recovery_replace_calls = 0

        def drift_on_recovery_checkpoint(root_value: object) -> None:
            nonlocal checkpoint_calls
            checkpoint_calls += 1
            if checkpoint_calls == 2:
                raise AddStoppedV1("failed", "data_root_integrity_lost")
            real_checkpoint(root_value)

        def count_recovery_replace(source: object, target: object) -> None:
            nonlocal recovery_replace_calls
            recovery_replace_calls += 1
            real_replace(source, target)

        monkeypatch.setattr(review, "_root_checkpoint", drift_on_recovery_checkpoint)
        monkeypatch.setattr(review.os, "replace", count_recovery_replace)
        stopped = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )

    assert type(stopped) is review.ReviewFailedV1
    assert stopped.cause.reason == "data_root_integrity_lost"
    assert stopped.progress is not None
    assert stopped.progress.decision_disposition == "unchanged"
    assert stopped.progress.review_revision == 1
    assert stopped.progress.review_status == "rejected"
    assert stopped.progress.handoff_action == "none"
    assert stopped.progress.handoff_status == "pending"
    assert recovery_replace_calls == 0
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert (candidate_reviews / "1.json").is_file()
    assert not (candidate_reviews / "current.json").exists()
    assert {path.name for path in candidate_reviews.iterdir()} == {"1.json"}
    private_files = candidate_reviews.parent / ".staging" / ".files"
    assert any(".current." in path.name for path in private_files.iterdir())


def test_unavailable_unresolved_attempt_cannot_be_skipped_for_a_new_decision(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    class CrashAfterApply:
        def apply(self, _handoff: review.ReviewedHandoffBytesV1) -> object:
            raise RuntimeError("simulated uncertain Knowledge completion")

    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    with open_validated_data_root_v1(str(literature_root)) as root:
        with pytest.raises(review.ReviewIndeterminateV1):
            review.review_candidate_v1(
                review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
                root=root,
                knowledge_intake=CrashAfterApply(),
            )

        path_presence = review._path_presence
        unavailable_reported = False

        def hide_attempt_directory_once(path: Path) -> str:
            nonlocal unavailable_reported
            if path.name == "import_attempts" and not unavailable_reported:
                unavailable_reported = True
                return "unknown"
            return path_presence(path)

        monkeypatch.setattr(review, "_path_presence", hide_attempt_directory_once)
        with pytest.raises(review.ReviewIndeterminateV1):
            review.review_candidate_v1(
                review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
                root=root,
                knowledge_intake=None,
            )

    assert unavailable_reported is True
    assert (candidate_reviews / "import_attempts" / "1.json").is_file()
    assert not (candidate_reviews / "2.json").exists()
    assert not (candidate_reviews / "no_actions" / "2.json").exists()


def test_decision_rename_failure_leaves_evidence_only_in_private_staging(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._literature_resume import ResumeWorkResultV1
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root
    real_rename = review.os.rename
    failed = False

    def fail_first_decision(source: object, target: object) -> None:
        nonlocal failed
        destination = Path(target)
        if (
            not failed
            and destination.parent.name == template.candidate_id
            and destination.name == "1.json"
        ):
            failed = True
            raise OSError("injected Decision rename failure")
        real_rename(source, target)

    monkeypatch.setattr(review.os, "rename", fail_first_decision)
    with open_validated_data_root_v1(str(literature_root)) as root:
        stopped = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )
        recovered = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )

    assert type(stopped) is review.ReviewFailedV1
    assert stopped.cause.reason == "review_commit_failed"
    assert stopped.progress is None
    assert type(recovered) is review.ReviewSucceededV1
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert {path.name for path in candidate_reviews.iterdir()} == {
        "1.json",
        "current.json",
        "no_actions",
    }
    private_files = candidate_reviews.parent / ".staging" / ".files"
    assert any(
        path.name.startswith(f"{template.candidate_id}.1.")
        for path in private_files.iterdir()
    )

    resumed = _resume_with_intake(literature_root, template.work_id, None)

    assert type(resumed) is ResumeWorkResultV1
    assert resumed.start_stage == "complete"
    assert resumed.advanced_stages == ()
    assert resumed.pipeline_complete is True
    assert any(
        path.name.startswith(f"{template.candidate_id}.1.")
        for path in private_files.iterdir()
    )


def test_unknown_staged_handoff_readback_is_indeterminate_and_recoverable(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root
    inspect_handoff = review._inspect_handoff_directory
    unavailable_reported = False

    def hide_staged_handoff_once(
        path: Path,
        expected: review.ReviewedHandoffBytesV1,
    ) -> str:
        nonlocal unavailable_reported
        if (
            path.parent.name == ".staging"
            and path.name.startswith("hnd_")
            and not unavailable_reported
        ):
            unavailable_reported = True
            return "unknown"
        return inspect_handoff(path, expected)

    monkeypatch.setattr(review, "_inspect_handoff_directory", hide_staged_handoff_once)
    with open_validated_data_root_v1(str(literature_root)) as root:
        with pytest.raises(review.ReviewIndeterminateV1):
            review.review_candidate_v1(
                review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
                root=root,
                knowledge_intake=None,
            )
        recovered = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=None,
        )

    assert unavailable_reported is True
    assert type(recovered) is review.ReviewBlockedV1
    assert recovered.cause.reason == "import_blocked"
    assert recovered.progress is not None
    assert recovered.progress.handoff_status == "committed"


def test_low_level_unavailable_decision_read_is_indeterminate(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_intake as intake
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import (
        DataRootOpenErrorV1,
        open_validated_data_root_v1,
    )

    literature_root, template = review_candidate_root
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    with open_validated_data_root_v1(str(literature_root)) as root:
        completed = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )
        open_local_file = intake.open_validated_local_file_v1

        def unavailable_decision(value: str) -> object:
            if Path(value) == candidate_reviews / "1.json":
                raise DataRootOpenErrorV1("unavailable")
            return open_local_file(value)

        monkeypatch.setattr(
            intake,
            "open_validated_local_file_v1",
            unavailable_decision,
        )
        with pytest.raises(review.ReviewIndeterminateV1):
            review.review_candidate_v1(
                review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
                root=root,
                knowledge_intake=None,
            )

    assert type(completed) is review.ReviewSucceededV1


def test_low_level_unavailable_post_rename_readback_is_indeterminate(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_intake as intake
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import (
        DataRootOpenErrorV1,
        open_validated_data_root_v1,
    )

    literature_root, template = review_candidate_root
    open_local_file = intake.open_validated_local_file_v1

    def unavailable_no_action(value: str) -> object:
        path = Path(value)
        if path.parent.name == "no_actions" and path.name == "1.json":
            raise DataRootOpenErrorV1("unavailable")
        return open_local_file(value)

    monkeypatch.setattr(
        intake,
        "open_validated_local_file_v1",
        unavailable_no_action,
    )
    with (
        open_validated_data_root_v1(str(literature_root)) as root,
        pytest.raises(review.ReviewIndeterminateV1),
    ):
        review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )

    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert (candidate_reviews / "no_actions" / "1.json").is_file()


def test_low_level_unavailable_private_staging_directory_is_indeterminate(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_intake as intake
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import (
        DataRootOpenErrorV1,
        open_validated_data_root_v1,
    )

    literature_root, template = review_candidate_root
    open_data_root = intake.open_validated_data_root_v1

    def unavailable_private_staging(value: str) -> object:
        path = Path(value)
        if path.name == ".files" and path.parent.name == ".staging":
            raise DataRootOpenErrorV1("unavailable")
        return open_data_root(value)

    monkeypatch.setattr(
        intake,
        "open_validated_data_root_v1",
        unavailable_private_staging,
    )
    with (
        open_validated_data_root_v1(str(literature_root)) as root,
        pytest.raises(review.ReviewIndeterminateV1),
    ):
        review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )


def test_immutable_conflict_is_root_sealed_before_a_handled_failure(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._literature_intake import AddStoppedV1
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root
    with open_validated_data_root_v1(str(literature_root)) as root:
        completed = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )
        inspect_exact_file = review._inspect_exact_file
        root_checkpoint = review._root_checkpoint
        conflict_observed = False

        def conflicting_no_action(path: Path, payload: bytes) -> str:
            nonlocal conflict_observed
            if path.parent.name == "no_actions" and path.name == "1.json":
                conflict_observed = True
                return "different"
            return inspect_exact_file(path, payload)

        def drift_after_conflict(root_value: object) -> None:
            if conflict_observed:
                raise AddStoppedV1("failed", "data_root_integrity_lost")
            root_checkpoint(root_value)

        monkeypatch.setattr(review, "_inspect_exact_file", conflicting_no_action)
        monkeypatch.setattr(review, "_root_checkpoint", drift_after_conflict)
        stopped = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )

    assert type(completed) is review.ReviewSucceededV1
    assert conflict_observed is True
    assert type(stopped) is review.ReviewFailedV1
    assert stopped.cause.reason == "data_root_integrity_lost"
    assert stopped.progress is not None


def test_staged_handoff_conflict_is_root_sealed_before_a_handled_failure(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._literature_intake import AddStoppedV1
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root
    inspect_handoff = review._inspect_handoff_directory
    root_checkpoint = review._root_checkpoint
    conflict_observed = False

    def conflicting_stage(
        path: Path,
        expected: review.ReviewedHandoffBytesV1,
    ) -> str:
        nonlocal conflict_observed
        if path.parent.name == ".staging" and path.name.startswith("hnd_"):
            conflict_observed = True
            return "different"
        return inspect_handoff(path, expected)

    def drift_after_conflict(root_value: object) -> None:
        if conflict_observed:
            raise AddStoppedV1("failed", "data_root_integrity_lost")
        root_checkpoint(root_value)

    monkeypatch.setattr(review, "_inspect_handoff_directory", conflicting_stage)
    monkeypatch.setattr(review, "_root_checkpoint", drift_after_conflict)
    with open_validated_data_root_v1(str(literature_root)) as root:
        stopped = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=None,
        )

    assert conflict_observed is True
    assert type(stopped) is review.ReviewFailedV1
    assert stopped.cause.reason == "data_root_integrity_lost"
    assert stopped.progress is not None


def test_unavailable_candidate_work_cannot_be_reported_as_not_found(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import (
        DataRootOpenErrorV1,
        open_validated_data_root_v1,
    )

    literature_root, template = review_candidate_root
    work_directory = literature_root / "works" / template.work_id
    open_data_root = review.open_validated_data_root_v1

    def unavailable_work(value: str) -> object:
        if Path(value) == work_directory:
            raise DataRootOpenErrorV1("unavailable")
        return open_data_root(value)

    monkeypatch.setattr(
        review,
        "open_validated_data_root_v1",
        unavailable_work,
    )
    with (
        open_validated_data_root_v1(str(literature_root)) as root,
        pytest.raises(review.ReviewIndeterminateV1),
    ):
        review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )


@pytest.mark.parametrize("launcher_index", [0, 1])
def test_resume_observes_a_completed_rejected_no_action_decision(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    launcher_index: int,
) -> None:
    literature_root, template = review_candidate_root
    rejected = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=1 - launcher_index,
    )
    assert rejected.returncode == 0
    source_directory = (
        literature_root / "works" / template.work_id / "sources" / template.source_id
    )
    semantic_runs_before = {
        path.name for path in (source_directory / "semantic" / "runs").iterdir()
    }
    materialization_runs_before = {
        path.name
        for path in (
            source_directory / "semantic" / "materializations" / "runs"
        ).iterdir()
    }

    resumed = _run_resume(
        literature_root,
        template.work_id,
        launcher_index=launcher_index,
    )

    assert resumed.returncode == 0, (resumed.stdout + resumed.stderr).decode(
        errors="replace"
    )
    assert json.loads(resumed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [],
        "outcome": "succeeded",
        "result": {
            "active_source_id": template.source_id,
            "advanced_stages": [],
            "pending_candidate_ids": [],
            "pipeline_complete": True,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "complete",
            "stop_stage": "complete",
            "work_id": template.work_id,
        },
        "schema_version": "gezhi.cli_result.v1",
    }
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert {path.name for path in candidate_reviews.glob("[0-9]*.json")} == {"1.json"}
    assert not (literature_root / "works" / template.work_id / "handoffs").exists()
    assert {
        path.name for path in (source_directory / "semantic" / "runs").iterdir()
    } == semantic_runs_before
    assert {
        path.name
        for path in (
            source_directory / "semantic" / "materializations" / "runs"
        ).iterdir()
    } == materialization_runs_before


@pytest.mark.parametrize("launcher_index", [0, 1])
def test_resume_reports_committed_accept_as_import_backlog_without_t18(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    launcher_index: int,
) -> None:
    literature_root, template = review_candidate_root
    accepted = _run_review(
        literature_root,
        template.candidate_id,
        "--accept",
        launcher_index=1 - launcher_index,
    )
    assert accepted.returncode == 2
    accepted_document = json.loads(accepted.stdout)
    handoff_id = accepted_document["result"]["handoff_id"]

    resumed = _run_resume(
        literature_root,
        template.work_id,
        launcher_index=launcher_index,
    )

    assert resumed.returncode == 2, (resumed.stdout + resumed.stderr).decode(
        errors="replace"
    )
    assert json.loads(resumed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.stage_blocked.v1",
                "context": {
                    "reason": "import_blocked",
                    "stage": "knowledge_import",
                },
            }
        ],
        "outcome": "blocked",
        "result": {
            "active_source_id": template.source_id,
            "advanced_stages": [],
            "pending_candidate_ids": [],
            "pipeline_complete": False,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "knowledge_import",
            "stop_stage": "knowledge_import",
            "work_id": template.work_id,
        },
        "schema_version": "gezhi.cli_result.v1",
    }
    reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert not (reviews / "import_attempts").exists()
    assert not (reviews / "imports").exists()
    assert (
        literature_root
        / "works"
        / template.work_id
        / "handoffs"
        / str(handoff_id)
        / "manifest.json"
    ).is_file()


def test_resume_repairs_a_missing_no_action_receipt_without_a_new_decision(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    def fail_no_action(*_args: object, **_kwargs: object) -> None:
        raise review._HandoffFailedV1("injected no-action failure")

    monkeypatch.setattr(review, "_commit_no_action_receipt", fail_no_action)
    with open_validated_data_root_v1(str(literature_root)) as root:
        stopped = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )
    assert type(stopped) is review.ReviewFailedV1
    assert stopped.progress is not None
    assert stopped.progress.handoff_status == "pending"

    resumed = _run_resume(literature_root, template.work_id, launcher_index=1)

    assert resumed.returncode == 0, (resumed.stdout + resumed.stderr).decode(
        errors="replace"
    )
    document = json.loads(resumed.stdout)
    assert document["result"] == {
        "active_source_id": template.source_id,
        "advanced_stages": ["handoff", "knowledge_import"],
        "pending_candidate_ids": [],
        "pipeline_complete": True,
        "schema_version": "gezhi.literature_resume_result.v1",
        "start_stage": "handoff",
        "stop_stage": "complete",
        "work_id": template.work_id,
    }
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert (candidate_reviews / "no_actions" / "1.json").is_file()
    assert {path.name for path in candidate_reviews.glob("[0-9]*.json")} == {"1.json"}


def test_resume_repairs_a_missing_accept_handoff_then_stops_at_import(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    def fail_handoff(*_args: object, **_kwargs: object) -> object:
        raise review._HandoffFailedV1("injected Handoff failure")

    monkeypatch.setattr(review, "_commit_or_reuse_handoff", fail_handoff)
    with open_validated_data_root_v1(str(literature_root)) as root:
        stopped = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=None,
        )
    assert type(stopped) is review.ReviewFailedV1
    assert stopped.progress is not None
    assert stopped.progress.handoff_status == "pending"

    resumed = _run_resume(literature_root, template.work_id, launcher_index=0)

    assert resumed.returncode == 2, (resumed.stdout + resumed.stderr).decode(
        errors="replace"
    )
    document = json.loads(resumed.stdout)
    assert document["diagnostics"][0]["context"] == {
        "reason": "import_blocked",
        "stage": "knowledge_import",
    }
    assert document["result"] == {
        "active_source_id": template.source_id,
        "advanced_stages": ["handoff"],
        "pending_candidate_ids": [],
        "pipeline_complete": False,
        "schema_version": "gezhi.literature_resume_result.v1",
        "start_stage": "handoff",
        "stop_stage": "knowledge_import",
        "work_id": template.work_id,
    }
    handoffs = literature_root / "works" / template.work_id / "handoffs"
    assert len([path for path in handoffs.iterdir() if path.name != ".staging"]) == 1


def test_resume_reports_work_busy_without_observing_partial_state(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    from gezhi._windows_data_root import open_validated_data_root_v1
    from gezhi._windows_ownership import try_acquire_work_writer_v1

    literature_root, template = review_candidate_root
    with open_validated_data_root_v1(str(literature_root)) as root:
        assert root.inspection.identity is not None
        owner = try_acquire_work_writer_v1(
            root.inspection.identity,
            template.work_id,
        )
        assert owner is not None
        with owner:
            resumed = _run_resume(
                literature_root,
                template.work_id,
                launcher_index=1,
            )

    assert resumed.returncode == 2
    assert json.loads(resumed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.work_busy.v1",
                "context": {},
            }
        ],
        "outcome": "blocked",
        "result": None,
        "schema_version": "gezhi.cli_result.v1",
    }


def test_resume_applies_accept_backlog_once_then_skips_the_verified_receipt(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    from gezhi._literature_resume import ResumeWorkResultV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    literature_root, template = review_candidate_root
    accepted = _run_review(
        literature_root,
        template.candidate_id,
        "--accept",
        launcher_index=1,
    )
    assert accepted.returncode == 2

    class RecordingIntake:
        def __init__(self) -> None:
            self.actions: list[str] = []

        def apply(self, handoff: ReviewedHandoffBytesV1) -> object:
            action = str(json.loads(handoff.candidates_bytes)["action"])
            self.actions.append(action)
            return IntakeAppliedV1("active", "applied")

    intake = RecordingIntake()
    resumed = _resume_with_intake(literature_root, template.work_id, intake)

    assert type(resumed) is ResumeWorkResultV1
    assert resumed.start_stage == "knowledge_import"
    assert resumed.advanced_stages == ("knowledge_import",)
    assert resumed.pipeline_complete is True
    assert intake.actions == ["accept"]

    class NoSecondApply:
        def apply(self, _handoff: ReviewedHandoffBytesV1) -> object:
            raise AssertionError("verified import receipt was replayed")

    repeated = _resume_with_intake(
        literature_root,
        template.work_id,
        NoSecondApply(),
    )
    assert type(repeated) is ResumeWorkResultV1
    assert repeated.start_stage == "complete"
    assert repeated.advanced_stages == ()
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert (candidate_reviews / "import_attempts" / "1.json").is_file()
    assert (candidate_reviews / "imports" / "1.json").is_file()


def test_resume_replays_an_unresolved_import_attempt_with_identical_bytes(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    from gezhi._literature_resume import ResumeWorkResultV1
    from gezhi._literature_review import (
        IntakeAppliedV1,
        ReviewCandidateCommandV1,
        ReviewedHandoffBytesV1,
        ReviewIndeterminateV1,
        review_candidate_v1,
    )
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    class CrashAfterApply:
        def apply(self, _handoff: ReviewedHandoffBytesV1) -> object:
            raise RuntimeError("simulated loss after external apply")

    with (
        open_validated_data_root_v1(str(literature_root)) as root,
        pytest.raises(ReviewIndeterminateV1),
    ):
        review_candidate_v1(
            ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=CrashAfterApply(),
        )

    class RecoveringIntake:
        def __init__(self) -> None:
            self.handoffs: list[bytes] = []

        def apply(self, handoff: ReviewedHandoffBytesV1) -> object:
            self.handoffs.append(handoff.manifest_bytes + handoff.candidates_bytes)
            return IntakeAppliedV1("active", "unchanged")

    intake = RecoveringIntake()
    resumed = _resume_with_intake(literature_root, template.work_id, intake)

    assert type(resumed) is ResumeWorkResultV1
    assert resumed.start_stage == "knowledge_import"
    assert resumed.advanced_stages == ("knowledge_import",)
    assert len(intake.handoffs) == 1
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    attempt = json.loads(
        (candidate_reviews / "import_attempts" / "1.json").read_bytes()
    )
    receipt = json.loads((candidate_reviews / "imports" / "1.json").read_bytes())
    assert receipt == {
        **attempt,
        "intake_status": "active",
        "schema_version": "gezhi.review_import_receipt.v1",
    }


@pytest.mark.parametrize(
    ("verdict_kind", "reason", "expected_outcome"),
    [
        ("blocked", "registry_unavailable", "blocked"),
        ("blocked", "registry_busy", "blocked"),
        ("blocked", "import_blocked", "blocked"),
        ("failed", "revision_conflict", "failed"),
        ("failed", "registry_conflict", "failed"),
        ("failed", "commit_failed", "failed"),
        ("failed", "import_failed", "failed"),
    ],
)
def test_resume_preserves_specific_knowledge_intake_reasons(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    verdict_kind: str,
    reason: str,
    expected_outcome: str,
) -> None:
    from gezhi._literature_resume import ResumeStoppedV1
    from gezhi._literature_review import (
        IntakeBlockedV1,
        IntakeFailedV1,
        ReviewBlockedV1,
        ReviewCandidateCommandV1,
        ReviewedHandoffBytesV1,
        review_candidate_v1,
    )
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root
    with open_validated_data_root_v1(str(literature_root)) as root:
        accepted = review_candidate_v1(
            ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=None,
        )
    assert type(accepted) is ReviewBlockedV1

    class StoppedIntake:
        def apply(self, _handoff: ReviewedHandoffBytesV1) -> object:
            if verdict_kind == "blocked":
                return IntakeBlockedV1(reason)  # type: ignore[arg-type]
            return IntakeFailedV1(reason)  # type: ignore[arg-type]

    with pytest.raises(ResumeStoppedV1) as caught:
        _resume_with_intake(
            literature_root,
            template.work_id,
            StoppedIntake(),
        )

    stopped = caught.value
    assert stopped.outcome == expected_outcome
    assert stopped.reason == reason
    assert stopped.stage == "knowledge_import"
    assert stopped.data_root is None
    assert stopped.result is not None
    assert stopped.result.start_stage == "knowledge_import"
    assert stopped.result.stop_stage == "knowledge_import"
    assert stopped.result.advanced_stages == ()


def test_resume_repairs_every_historical_no_action_before_current_import(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    def fail_no_action(*_args: object, **_kwargs: object) -> None:
        raise review._HandoffFailedV1("injected historical no-action failure")

    with monkeypatch.context() as patch:
        patch.setattr(review, "_commit_no_action_receipt", fail_no_action)
        with open_validated_data_root_v1(str(literature_root)) as root:
            rejected = review.review_candidate_v1(
                review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
                root=root,
                knowledge_intake=None,
            )
    assert type(rejected) is review.ReviewFailedV1
    assert rejected.progress is not None
    assert rejected.progress.review_revision == 1

    with open_validated_data_root_v1(str(literature_root)) as root:
        accepted = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=None,
        )
    assert type(accepted) is review.ReviewBlockedV1
    assert accepted.progress is not None
    assert accepted.progress.review_revision == 2

    resumed = _run_resume(literature_root, template.work_id, launcher_index=1)

    assert resumed.returncode == 2
    document = json.loads(resumed.stdout)
    assert document["diagnostics"][0]["context"] == {
        "reason": "import_blocked",
        "stage": "knowledge_import",
    }
    assert document["result"]["start_stage"] == "handoff"
    assert document["result"]["advanced_stages"] == ["handoff"]
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert (candidate_reviews / "no_actions" / "1.json").is_file()
    assert {path.name for path in candidate_reviews.glob("[0-9]*.json")} == {
        "1.json",
        "2.json",
    }


def test_resume_commits_but_does_not_import_a_superseded_accept_handoff(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    def fail_handoff(*_args: object, **_kwargs: object) -> object:
        raise review._HandoffFailedV1("injected historical Handoff failure")

    with monkeypatch.context() as patch:
        patch.setattr(review, "_commit_or_reuse_handoff", fail_handoff)
        with open_validated_data_root_v1(str(literature_root)) as root:
            accepted = review.review_candidate_v1(
                review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
                root=root,
                knowledge_intake=None,
            )
    assert type(accepted) is review.ReviewFailedV1

    with open_validated_data_root_v1(str(literature_root)) as root:
        rejected = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )
    assert type(rejected) is review.ReviewSucceededV1
    assert rejected.progress.review_revision == 2

    resumed = _run_resume(literature_root, template.work_id, launcher_index=0)

    assert resumed.returncode == 0, (resumed.stdout + resumed.stderr).decode(
        errors="replace"
    )
    result = json.loads(resumed.stdout)["result"]
    assert result["start_stage"] == "handoff"
    assert result["advanced_stages"] == ["handoff"]
    assert result["pipeline_complete"] is True
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert not (candidate_reviews / "import_attempts").exists()
    assert not (candidate_reviews / "imports").exists()
    handoffs = literature_root / "works" / template.work_id / "handoffs"
    assert len([path for path in handoffs.iterdir() if path.name != ".staging"]) == 1


def test_resume_repairs_missing_review_current_from_review_stage(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    literature_root, template = review_candidate_root
    rejected = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=1,
    )
    assert rejected.returncode == 0
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    (candidate_reviews / "current.json").unlink()

    resumed = _run_resume(literature_root, template.work_id, launcher_index=0)

    assert resumed.returncode == 0, (resumed.stdout + resumed.stderr).decode(
        errors="replace"
    )
    result = json.loads(resumed.stdout)["result"]
    assert result["start_stage"] == "review"
    assert result["advanced_stages"] == ["review"]
    assert result["pipeline_complete"] is True
    assert (candidate_reviews / "current.json").is_file()


def test_resume_quarantines_partial_handoff_staging_in_place(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    def fail_handoff(*_args: object, **_kwargs: object) -> object:
        raise review._HandoffFailedV1("injected pre-staging failure")

    with monkeypatch.context() as patch:
        patch.setattr(review, "_commit_or_reuse_handoff", fail_handoff)
        with open_validated_data_root_v1(str(literature_root)) as root:
            accepted = review.review_candidate_v1(
                review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
                root=root,
                knowledge_intake=None,
            )
    assert type(accepted) is review.ReviewFailedV1
    handoff_id = _handoff_id(template, action="accept", revision=1)
    handoffs = literature_root / "works" / template.work_id / "handoffs"
    partial = handoffs / ".staging" / handoff_id
    partial.mkdir(parents=True)
    marker = b'{"partial":true}\n'
    (partial / "manifest.json").write_bytes(marker)

    resumed = _run_resume(literature_root, template.work_id, launcher_index=1)

    assert resumed.returncode == 1
    document = json.loads(resumed.stdout)
    assert document["diagnostics"] == [
        {
            "code": "literature.resume.stage_failed.v1",
            "context": {
                "reason": "asset_integrity_lost",
                "stage": "handoff",
            },
        }
    ]
    assert document["result"]["start_stage"] == "handoff"
    assert document["result"]["stop_stage"] == "handoff"
    assert (partial / "manifest.json").read_bytes() == marker
    assert not (handoffs / handoff_id).exists()


def test_resume_rejects_partial_staging_when_formal_handoff_is_exact(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    literature_root, template = review_candidate_root
    accepted = _run_review(
        literature_root,
        template.candidate_id,
        "--accept",
        launcher_index=0,
    )
    assert accepted.returncode == 2

    handoff_id = _handoff_id(template, action="accept", revision=1)
    handoffs = literature_root / "works" / template.work_id / "handoffs"
    formal = handoffs / handoff_id
    formal_bytes = {
        name: (formal / name).read_bytes()
        for name in ("candidates.jsonl", "manifest.json")
    }
    partial = handoffs / ".staging" / handoff_id
    partial.mkdir(parents=True)
    marker = b'{"partial":true}\n'
    (partial / "manifest.json").write_bytes(marker)

    resumed = _run_resume(literature_root, template.work_id, launcher_index=1)

    assert resumed.returncode == 1
    document = json.loads(resumed.stdout)
    assert document["diagnostics"] == [
        {
            "code": "literature.resume.stage_failed.v1",
            "context": {
                "reason": "asset_integrity_lost",
                "stage": "handoff",
            },
        }
    ]
    assert (partial / "manifest.json").read_bytes() == marker
    assert {
        name: (formal / name).read_bytes()
        for name in ("candidates.jsonl", "manifest.json")
    } == formal_bytes


def test_work_snapshot_scans_all_candidates_before_sealing_pending(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1
    from gezhi._windows_ownership import try_acquire_work_writer_v1

    literature_root, template = review_candidate_root
    invalid_id = "cand_000000000000000000000000"
    with open_validated_data_root_v1(str(literature_root)) as root:
        original = review._find_candidate_authority_v1(template.candidate_id, root=root)
        authority = original.source
        invalid = replace(
            original,
            candidate={**original.candidate, "candidate_id": invalid_id},
        )
        decided = review._DecisionV1(
            document={},
            payload=b"",
            revision=1,
            status="rejected",
        )

        def candidate_ids(_authority: object) -> tuple[str, ...]:
            return (invalid_id, template.candidate_id)

        def find_candidate(candidate_id: str, **_kwargs: object) -> object:
            return invalid if candidate_id == invalid_id else original

        def snapshot(candidate: object, **_kwargs: object) -> object:
            if candidate is invalid:
                raise review._ReviewStateInvalidV1("injected first Candidate failure")
            return (
                literature_root / "works" / template.work_id / "reviews",
                literature_root
                / "works"
                / template.work_id
                / "reviews"
                / template.candidate_id,
                (decided,),
                frozenset({1}),
                (),
                (),
                False,
            )

        monkeypatch.setattr(review, "_work_review_candidate_ids", candidate_ids)
        monkeypatch.setattr(review, "_find_candidate_authority_v1", find_candidate)
        monkeypatch.setattr(review, "_review_authority_snapshot", snapshot)
        assert root.inspection.identity is not None
        owner = try_acquire_work_writer_v1(
            root.inspection.identity,
            template.work_id,
        )
        assert owner is not None
        with owner:
            result = review.continue_work_review_v1(
                authority,
                (invalid_id, template.candidate_id),
                owner=owner,
                root=root,
                knowledge_intake=None,
            )

    assert result.stop is not None
    assert result.stop.stage == "review"
    assert result.stop.reason == "review_state_invalid"
    assert result.pending_candidate_ids == ()


def test_work_continuation_maps_initial_root_checkpoint_drift(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._windows_data_root import open_validated_data_root_v1
    from gezhi._windows_ownership import try_acquire_work_writer_v1

    literature_root, template = review_candidate_root
    with open_validated_data_root_v1(str(literature_root)) as root:
        candidate = review._find_candidate_authority_v1(
            template.candidate_id,
            root=root,
        )
        assert root.inspection.identity is not None
        owner = try_acquire_work_writer_v1(
            root.inspection.identity,
            template.work_id,
        )
        assert owner is not None

        def drift(_root: object) -> None:
            raise review.AddStoppedV1("failed", "data_root_integrity_lost")

        monkeypatch.setattr(review, "_root_checkpoint", drift)
        with owner:
            result = review.continue_work_review_v1(
                candidate.source,
                (template.candidate_id,),
                owner=owner,
                root=root,
                knowledge_intake=None,
            )

    assert result.stop is not None
    assert result.stop.outcome == "failed"
    assert result.stop.stage == "review"
    assert result.stop.reason == "data_root_integrity_lost"
    assert result.stop.data_root == "literature"
    assert result.pending_candidate_ids == ()


def test_resume_fails_closed_when_review_authority_drifts_before_final_seal(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._literature_resume import ResumeStoppedV1

    literature_root, template = review_candidate_root
    rejected = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=1,
    )
    assert rejected.returncode == 0
    no_action = (
        literature_root
        / "works"
        / template.work_id
        / "reviews"
        / template.candidate_id
        / "no_actions"
        / "1.json"
    )
    assert no_action.is_file()
    continue_review = review.continue_work_review_v1

    def drift_after_continuation(*args: object, **kwargs: object) -> object:
        result = continue_review(*args, **kwargs)  # type: ignore[arg-type]
        no_action.unlink()
        return result

    monkeypatch.setattr(
        review,
        "continue_work_review_v1",
        drift_after_continuation,
    )

    with pytest.raises(ResumeStoppedV1) as caught:
        _resume_with_intake(literature_root, template.work_id, None)

    assert caught.value.outcome == "failed"
    assert caught.value.reason == "recovery_failed"
    assert caught.value.result is None


def test_resume_quarantines_review_file_staging_in_place(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    literature_root, template = review_candidate_root
    rejected = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=0,
    )
    assert rejected.returncode == 0
    staged = (
        literature_root
        / "works"
        / template.work_id
        / "reviews"
        / ".staging"
        / ".files"
        / "foreign.tmp"
    )
    marker = b"quarantined-review-staging"
    staged.write_bytes(marker)

    resumed = _run_resume(literature_root, template.work_id, launcher_index=1)

    assert resumed.returncode == 1
    document = json.loads(resumed.stdout)
    assert document["diagnostics"] == [
        {
            "code": "literature.resume.recovery_failed.v1",
            "context": {},
        }
    ]
    assert document["result"] is None
    assert staged.read_bytes() == marker


def test_resume_retries_a_valid_no_action_private_staging_file(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._literature_resume import ResumeWorkResultV1
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root
    real_rename = review.os.rename
    failed = False

    def fail_first_no_action(source: object, target: object) -> None:
        nonlocal failed
        if not failed and Path(target).parent.name == "no_actions":
            failed = True
            raise OSError("injected no-action rename failure")
        real_rename(source, target)

    monkeypatch.setattr(review.os, "rename", fail_first_no_action)
    with open_validated_data_root_v1(str(literature_root)) as root:
        stopped = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
            root=root,
            knowledge_intake=None,
        )
    assert type(stopped) is review.ReviewFailedV1
    assert stopped.cause.reason == "handoff_failed"
    private_files = (
        literature_root / "works" / template.work_id / "reviews" / ".staging" / ".files"
    )
    evidence = {
        path.name: path.read_bytes()
        for path in private_files.iterdir()
        if path.name.startswith("no_actions.1.json.")
    }
    assert len(evidence) == 1

    resumed = _resume_with_intake(literature_root, template.work_id, None)

    assert type(resumed) is ResumeWorkResultV1
    assert resumed.start_stage == "handoff"
    assert resumed.advanced_stages == ("handoff", "knowledge_import")
    assert resumed.pipeline_complete is True
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert (candidate_reviews / "no_actions" / "1.json").is_file()
    assert {name: (private_files / name).read_bytes() for name in evidence} == evidence


def test_resume_retries_a_valid_import_receipt_private_staging_file(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._literature_resume import ResumeWorkResultV1
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    class IdempotentIntake:
        def __init__(self) -> None:
            self.actions: list[str] = []

        def apply(self, handoff: review.ReviewedHandoffBytesV1) -> object:
            action = str(json.loads(handoff.candidates_bytes)["action"])
            self.actions.append(action)
            return review.IntakeAppliedV1(
                "active",
                "applied" if len(self.actions) == 1 else "unchanged",
            )

    real_rename = review.os.rename
    failed = False

    def fail_first_import_receipt(source: object, target: object) -> None:
        nonlocal failed
        if not failed and Path(target).parent.name == "imports":
            failed = True
            raise OSError("injected import receipt rename failure")
        real_rename(source, target)

    monkeypatch.setattr(review.os, "rename", fail_first_import_receipt)
    intake = IdempotentIntake()
    with (
        open_validated_data_root_v1(str(literature_root)) as root,
        pytest.raises(review.ReviewIndeterminateV1),
    ):
        review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=intake,
        )
    private_files = (
        literature_root / "works" / template.work_id / "reviews" / ".staging" / ".files"
    )
    evidence = {
        path.name: path.read_bytes()
        for path in private_files.iterdir()
        if path.name.startswith("imports.1.json.")
    }
    assert len(evidence) == 1

    resumed = _resume_with_intake(literature_root, template.work_id, intake)

    assert type(resumed) is ResumeWorkResultV1
    assert resumed.start_stage == "knowledge_import"
    assert resumed.advanced_stages == ("knowledge_import",)
    assert resumed.pipeline_complete is True
    assert intake.actions == ["accept", "accept"]
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert (candidate_reviews / "imports" / "1.json").is_file()
    assert {name: (private_files / name).read_bytes() for name in evidence} == evidence


def test_resume_rejects_orphan_formal_handoff_namespace(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
) -> None:
    literature_root, template = review_candidate_root
    rejected = _run_review(
        literature_root,
        template.candidate_id,
        "--reject",
        launcher_index=1,
    )
    assert rejected.returncode == 0
    orphan = (
        literature_root
        / "works"
        / template.work_id
        / "handoffs"
        / "hnd_000000000000000000000000"
    )
    orphan.mkdir(parents=True)
    marker = b'{"orphan":true}\n'
    (orphan / "manifest.json").write_bytes(marker)

    resumed = _run_resume(literature_root, template.work_id, launcher_index=0)

    assert resumed.returncode == 1
    document = json.loads(resumed.stdout)
    assert document["diagnostics"] == [
        {
            "code": "literature.resume.stage_failed.v1",
            "context": {
                "reason": "asset_integrity_lost",
                "stage": "handoff",
            },
        }
    ]
    assert document["result"]["start_stage"] == "handoff"
    assert document["result"]["stop_stage"] == "handoff"
    assert (orphan / "manifest.json").read_bytes() == marker


def test_resume_replays_historical_withdraw_before_the_current_accept(
    review_candidate_root: tuple[Path, _ReviewCandidateTemplateV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _literature_review as review
    from gezhi._literature_resume import ResumeStoppedV1, ResumeWorkResultV1
    from gezhi._windows_data_root import open_validated_data_root_v1

    literature_root, template = review_candidate_root

    class AppliedIntake:
        def __init__(self) -> None:
            self.actions: list[str] = []

        def apply(self, handoff: review.ReviewedHandoffBytesV1) -> object:
            action = str(json.loads(handoff.candidates_bytes)["action"])
            self.actions.append(action)
            return review.IntakeAppliedV1(
                "active" if action == "accept" else "withdrawn",
                "applied",
            )

    initial_intake = AppliedIntake()
    with open_validated_data_root_v1(str(literature_root)) as root:
        accepted = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=initial_intake,
        )
    assert type(accepted) is review.ReviewSucceededV1
    assert initial_intake.actions == ["accept"]

    def fail_withdraw(*_args: object, **_kwargs: object) -> object:
        raise review._HandoffFailedV1("injected historical withdraw failure")

    with monkeypatch.context() as patch:
        patch.setattr(review, "_commit_or_reuse_handoff", fail_withdraw)
        with open_validated_data_root_v1(str(literature_root)) as root:
            rejected = review.review_candidate_v1(
                review.ReviewCandidateCommandV1(template.candidate_id, "reject"),
                root=root,
                knowledge_intake=None,
            )
    assert type(rejected) is review.ReviewFailedV1
    assert rejected.progress is not None
    assert rejected.progress.review_revision == 2

    with open_validated_data_root_v1(str(literature_root)) as root:
        current_accept = review.review_candidate_v1(
            review.ReviewCandidateCommandV1(template.candidate_id, "accept"),
            root=root,
            knowledge_intake=None,
        )
    assert type(current_accept) is review.ReviewBlockedV1
    assert current_accept.progress is not None
    assert current_accept.progress.review_revision == 3

    class BlockOnceIntake:
        def __init__(self) -> None:
            self.actions: list[str] = []

        def apply(self, handoff: review.ReviewedHandoffBytesV1) -> object:
            action = str(json.loads(handoff.candidates_bytes)["action"])
            self.actions.append(action)
            if len(self.actions) == 1:
                return review.IntakeBlockedV1("import_blocked")
            return review.IntakeAppliedV1(
                "active" if action == "accept" else "withdrawn",
                "applied",
            )

    recovery_intake = BlockOnceIntake()
    with pytest.raises(ResumeStoppedV1) as first_stop:
        _resume_with_intake(
            literature_root,
            template.work_id,
            recovery_intake,
        )

    assert first_stop.value.outcome == "blocked"
    assert first_stop.value.reason == "import_blocked"
    assert first_stop.value.stage == "knowledge_import"
    assert first_stop.value.result is not None
    assert first_stop.value.result.start_stage == "handoff"
    assert first_stop.value.result.advanced_stages == ("handoff",)
    candidate_reviews = (
        literature_root / "works" / template.work_id / "reviews" / template.candidate_id
    )
    assert (candidate_reviews / "import_attempts" / "2.json").is_file()
    assert not (candidate_reviews / "imports" / "2.json").exists()

    resumed = _resume_with_intake(literature_root, template.work_id, recovery_intake)

    assert type(resumed) is ResumeWorkResultV1
    assert resumed.start_stage == "knowledge_import"
    assert resumed.advanced_stages == ("knowledge_import",)
    assert resumed.pipeline_complete is True
    assert recovery_intake.actions == ["withdraw", "withdraw", "accept"]
    assert (candidate_reviews / "imports" / "2.json").is_file()
    assert (candidate_reviews / "imports" / "3.json").is_file()
