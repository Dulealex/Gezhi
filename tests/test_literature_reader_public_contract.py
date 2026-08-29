from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from launcher_support import SOURCE_ROOT, launcher_commands, run_launcher
from literature_pdf_support import write_text_pdf

_DOUBLE = Path(__file__).parent / "support" / "codex_child_executable_double_v1.py"


@pytest.fixture
def reader_workspace() -> Iterator[tuple[Path, Path, Path, Path]]:
    data_container = Path(r"E:\Gezhi\data")
    attempt_container = Path(r"E:\gztest")
    data_container.mkdir(parents=True, exist_ok=True)
    attempt_container.mkdir(parents=True, exist_ok=True)
    suffix = "r" + uuid.uuid4().hex[:7]
    base = data_container / suffix
    runtime_base = attempt_container / suffix
    base.mkdir()
    runtime_base.mkdir()
    literature_root = base / "lit"
    knowledge_root = base / "know"
    literature_root.mkdir()
    knowledge_root.mkdir()
    pdf_path = base / "paper.pdf"
    try:
        yield literature_root, knowledge_root, pdf_path, runtime_base
    finally:
        resolved_base = base.resolve(strict=True)
        resolved_runtime = runtime_base.resolve(strict=True)
        assert resolved_base.parent == data_container.resolve(strict=True)
        assert resolved_runtime.parent == attempt_container.resolve(strict=True)
        assert resolved_base.name == suffix == resolved_runtime.name
        shutil.rmtree(resolved_base)
        shutil.rmtree(resolved_runtime)


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
    assert completed.returncode == 0, (
        completed.stdout + completed.stderr
    ).decode(errors="replace")
    return json.loads(completed.stdout)["result"]


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


def _canonical_payload_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


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


def _reject_reader_attempt_sitecustomize(site_root: Path) -> None:
    source = """
import gezhi._literature_reader as reader


def reject_attempt(*_args, **_kwargs):
    raise AssertionError("a valid semantic current must be reused")


reader._run_role_attempt_v1 = reject_attempt
reader._prepare_role_invocation_v1 = lambda: object()
"""
    (site_root / "sitecustomize.py").write_text(source, encoding="utf-8")


def _inject_reader_reparse_sitecustomize(site_root: Path) -> None:
    source = """
import os
import subprocess
from pathlib import Path

import gezhi._literature_reader as reader


original = reader.advance_reader_v1


def inject_reparse(authority, canonical, **kwargs):
    semantic = authority.source_directory / "semantic"
    outside = Path(os.environ["READER_REPARSE_TARGET"])
    try:
        os.symlink(outside, semantic, target_is_directory=True)
    except OSError as error:
        junction = subprocess.run(
            (
                "cmd",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(semantic),
                str(outside),
            ),
            capture_output=True,
            check=False,
        )
        if junction.returncode != 0:
            raise error
    return original(authority, canonical, **kwargs)


def reject_attempt(*_args, **_kwargs):
    raise AssertionError("Reader must reject the injected reparse before launch")


reader.advance_reader_v1 = inject_reparse
reader._run_role_attempt_v1 = reject_attempt
reader._prepare_role_invocation_v1 = lambda: object()
"""
    (site_root / "sitecustomize.py").write_text(source, encoding="utf-8")


def _reader_sitecustomize(site_root: Path) -> None:
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
            os.environ["READER_DOUBLE_EXE"],
            "final-from-file",
            "--final",
            str(final_spool),
            "--payload-file",
            os.environ["READER_DOUBLE_FINAL"],
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


def _timeout_sitecustomize(site_root: Path) -> None:
    source = """
import os
import sys
from pathlib import Path

import gezhi._literature_reader as reader
from gezhi._codex_child_process import AttemptTerminalEvidenceV1
from gezhi._codex_child_process import NeverCancelledV1
from gezhi._codex_child_process import _run_codex_child_test_double_v1
from gezhi._codex_role_plan import _freeze_test_double_launch_v1


def run_timeout(request):
    capture_parent = request.attempt_root / "captures"
    capture = capture_parent / f"{request.attempt_ordinal:02d}"
    staging = capture_parent / f".{request.attempt_ordinal:02d}.codex-stage"
    plan = _freeze_test_double_launch_v1(
        executable=Path(sys.executable),
        arguments=(
            "-I",
            "-B",
            os.environ["READER_DOUBLE_EXE"],
            "hang",
            "--final",
            str(staging / ".final_message.spool"),
        ),
        prompt=request.prompt,
        attempt_ordinal=request.attempt_ordinal,
        working_directory=request.attempt_root / "working",
        capture_directory=capture,
        staging_directory=staging,
        temporary_directory=request.attempt_root / "temporary",
        source_environment={"SystemRoot": os.environ["SystemRoot"]},
        timeout_seconds=0.05,
        capture_profile="literature",
    )
    result = _run_codex_child_test_double_v1(plan, NeverCancelledV1())
    assert isinstance(result, AttemptTerminalEvidenceV1), result
    return result


reader._run_role_attempt_v1 = run_timeout
reader._prepare_role_invocation_v1 = lambda: object()
reader._wait_before_retry_v1 = lambda _seconds: None
"""
    (site_root / "sitecustomize.py").write_text(source, encoding="utf-8")


def _timeout_then_success_sitecustomize(site_root: Path) -> None:
    source = """
import os
import sys
from pathlib import Path

import gezhi._literature_reader as reader
from gezhi._codex_child_process import _run_codex_child_test_double_v1
from gezhi._codex_role_plan import _freeze_test_double_launch_v1


def resolve_runtime(_project_root):
    counter = Path(os.environ["READER_RESOLVE_COUNT"])
    previous = int(counter.read_text(encoding="ascii")) if counter.exists() else 0
    counter.write_text(str(previous + 1), encoding="ascii")
    return object()


def freeze_launch(
    *,
    prompt,
    attempt_ordinal,
    workspace,
    existing_shared_deadline_monotonic_ns=None,
    **_values,
):
    with Path(os.environ["READER_DEADLINE_LOG"]).open(
        "a", encoding="ascii"
    ) as target:
        target.write(f"{existing_shared_deadline_monotonic_ns}\\n")
    attempt_root = Path(workspace.attempt_root)
    capture_parent = attempt_root / "captures"
    capture = capture_parent / f"{attempt_ordinal:02d}"
    staging = capture_parent / f".{attempt_ordinal:02d}.codex-stage"
    final_spool = staging / ".final_message.spool"
    if attempt_ordinal == 1:
        arguments = (
            "-I",
            "-B",
            os.environ["READER_DOUBLE_EXE"],
            "hang",
            "--final",
            str(final_spool),
        )
        timeout_seconds = 0.05
    else:
        arguments = (
            "-I",
            "-B",
            os.environ["READER_DOUBLE_EXE"],
            "final-from-file",
            "--final",
            str(final_spool),
            "--payload-file",
            os.environ["READER_DOUBLE_FINAL"],
        )
        timeout_seconds = 10
    return _freeze_test_double_launch_v1(
        executable=Path(sys.executable),
        arguments=arguments,
        prompt=prompt,
        attempt_ordinal=attempt_ordinal,
        working_directory=attempt_root / "working",
        capture_directory=capture,
        staging_directory=staging,
        temporary_directory=attempt_root / "temporary",
        source_environment={"SystemRoot": os.environ["SystemRoot"]},
        timeout_seconds=timeout_seconds,
        capture_profile="literature",
        existing_shared_deadline_monotonic_ns=(
            existing_shared_deadline_monotonic_ns
        ),
    )


def record_wait(seconds):
    with Path(os.environ["READER_WAIT_LOG"]).open("a", encoding="ascii") as target:
        target.write(f"{seconds}\\n")


reader.resolve_codex_runtime_v1 = resolve_runtime
reader.freeze_codex_role_launch_v1 = freeze_launch
reader.run_codex_child_v1 = _run_codex_child_test_double_v1
reader._wait_before_retry_v1 = record_wait
"""
    (site_root / "sitecustomize.py").write_text(source, encoding="utf-8")


def _process_error_sitecustomize(site_root: Path) -> None:
    source = """
import os
import sys
from pathlib import Path

import gezhi._literature_reader as reader
from gezhi._codex_child_process import AttemptTerminalEvidenceV1
from gezhi._codex_child_process import NeverCancelledV1
from gezhi._codex_child_process import _run_codex_child_test_double_v1
from gezhi._codex_role_plan import _freeze_test_double_launch_v1


def run_failure(request):
    capture_parent = request.attempt_root / "captures"
    capture = capture_parent / f"{request.attempt_ordinal:02d}"
    staging = capture_parent / f".{request.attempt_ordinal:02d}.codex-stage"
    plan = _freeze_test_double_launch_v1(
        executable=Path(sys.executable),
        arguments=(
            "-I",
            "-B",
            os.environ["READER_DOUBLE_EXE"],
            "message-failure",
            "--final",
            str(staging / ".final_message.spool"),
            "--payload-file",
            os.environ["READER_DOUBLE_MESSAGE"],
            "--value",
            "71",
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


def reject_retry(_seconds):
    raise AssertionError("process errors must not use retry backoff")


reader._run_role_attempt_v1 = run_failure
reader._prepare_role_invocation_v1 = lambda: object()
reader._wait_before_retry_v1 = reject_retry
"""
    (site_root / "sitecustomize.py").write_text(source, encoding="utf-8")


def _capture_overflow_sitecustomize(site_root: Path) -> None:
    source = """
import os
import sys
from pathlib import Path

import gezhi._literature_reader as reader
from gezhi._codex_child_process import AttemptTerminalEvidenceV1
from gezhi._codex_child_process import NeverCancelledV1
from gezhi._codex_child_process import _run_codex_child_test_double_v1
from gezhi._codex_role_plan import _freeze_test_double_launch_v1


def run_overflow(request):
    capture_parent = request.attempt_root / "captures"
    capture = capture_parent / f"{request.attempt_ordinal:02d}"
    staging = capture_parent / f".{request.attempt_ordinal:02d}.codex-stage"
    plan = _freeze_test_double_launch_v1(
        executable=Path(sys.executable),
        arguments=(
            "-I",
            "-B",
            os.environ["READER_DOUBLE_EXE"],
            "final-overflow-hang",
            "--final",
            str(staging / ".final_message.spool"),
            "--value",
            "1048577",
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


def reject_retry(_seconds):
    raise AssertionError("capture overflow must not use retry backoff")


reader._run_role_attempt_v1 = run_overflow
reader._prepare_role_invocation_v1 = lambda: object()
reader._wait_before_retry_v1 = reject_retry
"""
    (site_root / "sitecustomize.py").write_text(source, encoding="utf-8")


def _pre_attempt_rejected_sitecustomize(site_root: Path) -> None:
    source = """
import gezhi._literature_reader as reader
from gezhi._codex_child_process import PreAttemptRejectedV1


def reject_before_commit(_request):
    return PreAttemptRejectedV1(
        reason="preparation_failed:ReaderTest",
        resource_ledger_count=0,
    )


reader._run_role_attempt_v1 = reject_before_commit
reader._prepare_role_invocation_v1 = lambda: object()
"""
    (site_root / "sitecustomize.py").write_text(source, encoding="utf-8")


def _malformed_events_sitecustomize(site_root: Path) -> None:
    source = """
import os
import sys
from pathlib import Path

import gezhi._literature_reader as reader
from gezhi._codex_child_process import AttemptTerminalEvidenceV1
from gezhi._codex_child_process import NeverCancelledV1
from gezhi._codex_child_process import _run_codex_child_test_double_v1
from gezhi._codex_role_plan import _freeze_test_double_launch_v1


def run_malformed(request):
    capture_parent = request.attempt_root / "captures"
    capture = capture_parent / f"{request.attempt_ordinal:02d}"
    staging = capture_parent / f".{request.attempt_ordinal:02d}.codex-stage"
    plan = _freeze_test_double_launch_v1(
        executable=Path(sys.executable),
        arguments=(
            "-I",
            "-B",
            os.environ["READER_DOUBLE_EXE"],
            "malformed",
            "--final",
            str(staging / ".final_message.spool"),
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


def reject_retry(_seconds):
    raise AssertionError("malformed events must not be retried")


reader._run_role_attempt_v1 = run_malformed
reader._prepare_role_invocation_v1 = lambda: object()
reader._wait_before_retry_v1 = reject_retry
"""
    (site_root / "sitecustomize.py").write_text(source, encoding="utf-8")


@pytest.mark.parametrize("launcher_index", [0, 1])
def test_public_resume_retries_once_and_publishes_an_evidence_bound_draft(
    reader_workspace: tuple[Path, Path, Path, Path],
    launcher_index: int,
) -> None:
    literature_root, knowledge_root, pdf_path, runtime_base = reader_workspace
    unavailable_knowledge_root = runtime_base / "missing-knowledge"
    source_text = (
        "This native PDF contains explicit searchable evidence for the Reader."
    )
    write_text_pdf(pdf_path, source_text)
    added = _run_add(literature_root, pdf_path)

    canonical_site = runtime_base / "canonical-site"
    canonical_site.mkdir()
    _canonicalize_only_sitecustomize(canonical_site)
    first_resume = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(canonical_site, SOURCE_ROOT),
    )
    assert first_resume.returncode == 2
    source_dir = (
        literature_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
    )
    canonical_current = json.loads(
        (source_dir / "canonical" / "current.json").read_bytes()
    )
    canonical_run = source_dir / "canonical" / "runs" / canonical_current["run_id"]
    block = json.loads((canonical_run / "blocks.jsonl").read_bytes().splitlines()[0])

    statement = {
        "evidence_block_ids": [block["block_id"]],
        "risk_flags": [],
        "source_terms": ["explicit searchable evidence"],
        "support_kind": "direct",
        "text": "该资料提供了可由原文直接定位的明确证据。",
    }
    candidate_draft = {
        "candidate_type": "claim",
        "descriptor_refs": [],
        "statement": statement,
    }
    reader_output = {
        "candidate_drafts": [candidate_draft],
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
    final_path = runtime_base / "reader-final.json"
    final_bytes = _canonical_bytes(reader_output)
    final_path.write_bytes(final_bytes)
    site_root = runtime_base / "reader-site"
    site_root.mkdir()
    _timeout_then_success_sitecustomize(site_root)
    codex_home = runtime_base / "home"
    temporary = runtime_base / "temp"
    codex_home.mkdir()
    temporary.mkdir()
    resolve_count = runtime_base / "resolve-count.txt"
    wait_log = runtime_base / "wait-log.txt"
    deadline_log = runtime_base / "deadline-log.txt"

    completed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(unavailable_knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(site_root, SOURCE_ROOT),
        environment_updates={
            "CODEX_HOME": str(codex_home),
            "READER_DOUBLE_EXE": str(_DOUBLE),
            "READER_DOUBLE_FINAL": str(final_path),
            "READER_DEADLINE_LOG": str(deadline_log),
            "READER_RESOLVE_COUNT": str(resolve_count),
            "READER_WAIT_LOG": str(wait_log),
            "TEMP": str(temporary),
            "TMP": str(temporary),
        },
        timeout=30,
    )

    assert completed.returncode == 2, (
        completed.stdout + completed.stderr
    ).decode(errors="replace")
    assert completed.stderr == b""
    deadline_values = deadline_log.read_text(encoding="ascii").splitlines()
    assert deadline_values[0] == "None"
    assert len(deadline_values) == 2
    assert deadline_values[1].isdigit()
    candidate_payload = {
        "candidate_type": "claim",
        "canonical_content_sha256": canonical_current[
            "canonical_content_sha256"
        ],
        "descriptor_refs": [],
        "schema_version": "gezhi.candidate_payload.v1",
        "source_id": added["source_id"],
        "source_sha256": added["source_sha256"],
        "statement": {
            "evidence_pointers": [
                {
                    "block_id": block["block_id"],
                    "canonical_content_sha256": canonical_current[
                        "canonical_content_sha256"
                    ],
                    "schema_version": "gezhi.evidence_pointer.v1",
                }
            ],
            "risk_flags": [],
            "source_terms": ["explicit searchable evidence"],
            "support_kind": "direct",
            "text": "该资料提供了可由原文直接定位的明确证据。",
        },
        "work_id": added["work_id"],
    }
    payload_sha256 = hashlib.sha256(
        _canonical_payload_bytes(candidate_payload)
    ).hexdigest()
    candidate_id = "cand_" + payload_sha256[:24]
    candidate = {
        "candidate_id": candidate_id,
        "payload": candidate_payload,
        "payload_sha256": payload_sha256,
        "schema_version": "gezhi.candidate_knowledge.v1",
    }

    document = json.loads(completed.stdout)
    assert document == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.stage_blocked.v1",
                "context": {
                    "reason": "awaiting_review",
                    "stage": "review",
                },
            }
        ],
        "outcome": "blocked",
        "result": {
            "active_source_id": added["source_id"],
            "advanced_stages": ["read"],
            "pending_candidate_ids": [candidate_id],
            "pipeline_complete": False,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "read",
            "stop_stage": "review",
            "work_id": added["work_id"],
        },
        "schema_version": "gezhi.cli_result.v1",
    }

    semantic = source_dir / "semantic"
    current_bytes = (semantic / "current.json").read_bytes()
    current = json.loads(current_bytes)
    run_dir = semantic / "runs" / current["run_id"]
    manifest_bytes = (run_dir / "manifest.json").read_bytes()
    assert current == {
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "run_id": current["run_id"],
        "schema_version": "gezhi.literature_semantic_current.v1",
    }
    reading = json.loads((run_dir / "result" / "reading_result.json").read_bytes())
    assert reading["reading_result"] == reader_output["reading_result"]
    assert (
        reading["canonical_content_sha256"]
        == canonical_current["canonical_content_sha256"]
    )
    assert (
        json.loads((run_dir / "result" / "candidate_drafts.json").read_bytes())[
            "candidate_drafts"
        ]
        == [candidate_draft]
    )
    assert (run_dir / "result" / "candidate_knowledge.jsonl").read_bytes() == b""
    assert (
        json.loads((run_dir / "result" / "review_queue.json").read_bytes())[
            "candidates"
        ]
        == []
    )

    materializations = semantic / "materializations"
    materialization_current_bytes = (materializations / "current.json").read_bytes()
    materialization_current = json.loads(materialization_current_bytes)
    materialization_run = (
        materializations / "runs" / materialization_current["run_id"]
    )
    materialization_manifest_bytes = (
        materialization_run / "manifest.json"
    ).read_bytes()
    assert materialization_current == {
        "manifest_sha256": hashlib.sha256(
            materialization_manifest_bytes
        ).hexdigest(),
        "run_id": materialization_current["run_id"],
        "schema_version": "gezhi.candidate_materialization_current.v1",
    }
    assert (
        materialization_run / "result" / "descriptor_payloads.jsonl"
    ).read_bytes() == b""
    assert [
        json.loads(line)
        for line in (
            materialization_run / "result" / "candidate_knowledge.jsonl"
        ).read_bytes().splitlines()
    ] == [candidate]
    assert json.loads(
        (materialization_run / "result" / "review_queue.json").read_bytes()
    ) == {
        "candidates": [
            {
                "candidate_id": candidate_id,
                "payload_sha256": payload_sha256,
                "review_status": "pending",
                "schema_version": "gezhi.review_queue_candidate.v1",
            }
        ],
        "canonical_content_sha256": canonical_current[
            "canonical_content_sha256"
        ],
        "materialization_run_id": materialization_current["run_id"],
        "reader_manifest_sha256": current["manifest_sha256"],
        "reader_run_id": current["run_id"],
        "schema_version": "gezhi.review_queue.v2",
        "source_id": added["source_id"],
        "source_sha256": added["source_sha256"],
        "work_id": added["work_id"],
    }
    first_attempt = run_dir / "attempts" / "01"
    second_attempt = run_dir / "attempts" / "02"
    first_attempt_document = json.loads(
        (first_attempt / "attempt.json").read_bytes()
    )
    second_attempt_document = json.loads(
        (second_attempt / "attempt.json").read_bytes()
    )
    assert first_attempt_document["failure_class"] == "timeout"
    assert not (first_attempt / "final_message.txt").exists()
    assert (second_attempt / "events.jsonl").read_bytes().splitlines()
    assert (second_attempt / "final_message.txt").read_bytes() == final_bytes
    assert second_attempt_document["exit_code"] == 0
    assert second_attempt_document["failure_class"] is None
    assert resolve_count.read_text(encoding="ascii") == "1"
    assert wait_log.read_text(encoding="ascii") == "10.0\n"

    input_bytes = (run_dir / "input.jsonl").read_bytes()
    assert input_bytes.endswith(b"\n")
    assert b"\r" not in input_bytes
    input_records = [json.loads(line) for line in input_bytes.splitlines()]
    assert input_records[0] == {
        "arxiv_id": None,
        "authors": [],
        "canonical_content_sha256": canonical_current[
            "canonical_content_sha256"
        ],
        "canonical_run_id": canonical_current["run_id"],
        "doi": None,
        "record_type": "metadata",
        "schema_version": "gezhi.reader_input.v1",
        "source_id": added["source_id"],
        "source_sha256": added["source_sha256"],
        "title": None,
        "work_id": added["work_id"],
        "year": None,
    }
    assert [record["order"] for record in input_records[1:]] == list(
        range(len(input_records) - 1)
    )
    assert all(record["record_type"] == "block" for record in input_records[1:])

    prompt_bytes = (run_dir / "prompt.txt").read_bytes()
    assert prompt_bytes.startswith(b"You are literature_reader_v1.")
    assert prompt_bytes.count(input_bytes) == 1
    assert prompt_bytes.endswith(b"--- END READER INPUT JSONL ---\n")
    schema_bytes = (run_dir / "schema.json").read_bytes()
    schema = json.loads(schema_bytes)
    assert schema["$id"] == (
        "https://gezhi.local/schemas/literature-reader-output-v1.schema.json"
    )
    assert schema["additionalProperties"] is False

    manifest = json.loads(manifest_bytes)
    assert manifest["status"] == "succeeded"
    assert manifest["candidate_count"] == 0
    assert manifest["candidate_draft_count"] == 1
    assert manifest["codex_cli_version"] == "0.146.0"
    assert manifest["attempt_count"] == 2
    assert manifest["attempts"] == [
        first_attempt_document,
        second_attempt_document,
    ]
    assert manifest["usage_totals"] == {
        "cached_input_tokens": None,
        "input_tokens": None,
        "output_tokens": None,
        "reasoning_output_tokens": None,
    }
    assert manifest["input_block_count"] == len(input_records) - 1
    assert manifest["input_block_limit"] == 4_096
    assert manifest["input_byte_length"] == len(input_bytes)
    assert manifest["input_byte_limit"] == 524_288
    assert manifest["input_sha256"] == hashlib.sha256(input_bytes).hexdigest()
    assert manifest["prompt_sha256"] == hashlib.sha256(prompt_bytes).hexdigest()
    assert manifest["schema_sha256"] == hashlib.sha256(schema_bytes).hexdigest()
    asset_paths = [entry["path"] for entry in manifest["assets"]]
    assert asset_paths == sorted(asset_paths, key=lambda value: value.encode("utf-8"))
    assert asset_paths == [
        path.relative_to(run_dir).as_posix()
        for path in sorted(
            (
                path
                for path in run_dir.rglob("*")
                if path.is_file() and path.name != "manifest.json"
            ),
            key=lambda path: path.relative_to(run_dir)
            .as_posix()
            .encode("utf-8"),
        )
    ]
    for entry in manifest["assets"]:
        payload = (run_dir / entry["path"]).read_bytes()
        assert entry["byte_length"] == len(payload)
        assert entry["sha256"] == hashlib.sha256(payload).hexdigest()

    reuse_site = runtime_base / "reuse-site"
    reuse_site.mkdir()
    _reject_reader_attempt_sitecustomize(reuse_site)
    resumed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(unavailable_knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(reuse_site, SOURCE_ROOT),
    )
    assert json.loads(resumed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.stage_blocked.v1",
                "context": {
                    "reason": "awaiting_review",
                    "stage": "review",
                },
            }
        ],
        "outcome": "blocked",
        "result": {
            "active_source_id": added["source_id"],
            "advanced_stages": [],
            "pending_candidate_ids": [candidate_id],
            "pipeline_complete": False,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "review",
            "stop_stage": "review",
            "work_id": added["work_id"],
        },
        "schema_version": "gezhi.cli_result.v1",
    }
    assert resumed.returncode == 2
    assert resumed.stderr == b""
    assert (semantic / "current.json").read_bytes() == current_bytes
    assert [path.name for path in (semantic / "runs").iterdir()] == [
        run_dir.name
    ]
    materialization_run_names = [
        path.name for path in (materializations / "runs").iterdir()
    ]
    assert (materializations / "current.json").read_bytes() == (
        materialization_current_bytes
    )
    assert materialization_run_names == [materialization_run.name]

    (semantic / "current.json").unlink()
    recovered = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(unavailable_knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(reuse_site, SOURCE_ROOT),
    )
    assert json.loads(recovered.stdout) == json.loads(resumed.stdout)
    assert recovered.returncode == 2
    assert recovered.stderr == b""
    assert (semantic / "current.json").read_bytes() == current_bytes
    assert [path.name for path in (semantic / "runs").iterdir()] == [
        run_dir.name
    ]
    assert (materializations / "current.json").read_bytes() == (
        materialization_current_bytes
    )
    assert [path.name for path in (materializations / "runs").iterdir()] == (
        materialization_run_names
    )

    (materializations / "current.json").unlink()
    materialization_recovered = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(unavailable_knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(reuse_site, SOURCE_ROOT),
    )
    expected_materialization_recovery = json.loads(resumed.stdout)
    expected_materialization_recovery["result"]["advanced_stages"] = ["read"]
    expected_materialization_recovery["result"]["start_stage"] = "read"
    assert json.loads(materialization_recovered.stdout) == (
        expected_materialization_recovery
    )
    assert materialization_recovered.returncode == 2
    assert materialization_recovered.stderr == b""
    assert (materializations / "current.json").read_bytes() == (
        materialization_current_bytes
    )
    assert [path.name for path in (materializations / "runs").iterdir()] == (
        materialization_run_names
    )

    (materializations / "current.json").replace(
        materializations / ".current.next.json"
    )
    next_pointer_recovered = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(unavailable_knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(reuse_site, SOURCE_ROOT),
    )
    assert json.loads(next_pointer_recovered.stdout) == (
        expected_materialization_recovery
    )
    assert next_pointer_recovered.returncode == 2
    assert next_pointer_recovered.stderr == b""
    assert (materializations / "current.json").read_bytes() == (
        materialization_current_bytes
    )
    assert not (materializations / ".current.next.json").exists()

    (materializations / "current.json").unlink()
    staged_materialization = (
        materializations / ".staging" / materialization_run.name
    )
    materialization_run.replace(staged_materialization)
    staging_recovered = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(unavailable_knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(reuse_site, SOURCE_ROOT),
    )
    assert json.loads(staging_recovered.stdout) == (
        expected_materialization_recovery
    )
    assert staging_recovered.returncode == 2
    assert staging_recovered.stderr == b""
    assert (materializations / "current.json").read_bytes() == (
        materialization_current_bytes
    )
    assert materialization_run.is_dir()
    assert list((materializations / ".staging").iterdir()) == []

    (materializations / "current.json").write_bytes(b"{}\n")
    invalid_materialization_current = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(unavailable_knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(reuse_site, SOURCE_ROOT),
    )
    assert json.loads(invalid_materialization_current.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.stage_failed.v1",
                "context": {
                    "reason": "asset_integrity_lost",
                    "stage": "read",
                },
            }
        ],
        "outcome": "failed",
        "result": {
            "active_source_id": added["source_id"],
            "advanced_stages": [],
            "pending_candidate_ids": [],
            "pipeline_complete": False,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "read",
            "stop_stage": "read",
            "work_id": added["work_id"],
        },
        "schema_version": "gezhi.cli_result.v1",
    }
    assert invalid_materialization_current.returncode == 1
    assert invalid_materialization_current.stderr == b""
    (materializations / "current.json").write_bytes(
        materialization_current_bytes
    )

    partial_materialization = (
        materializations
        / ".staging"
        / "matrun_33333333-3333-4333-8333-333333333333"
    )
    partial_materialization.mkdir()
    (partial_materialization / "input.json").write_bytes(b"{}\n")
    invalid_staging = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(unavailable_knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(reuse_site, SOURCE_ROOT),
    )
    assert json.loads(invalid_staging.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.recovery_failed.v1",
                "context": {},
            }
        ],
        "outcome": "failed",
        "result": None,
        "schema_version": "gezhi.cli_result.v1",
    }
    assert invalid_staging.returncode == 1
    assert invalid_staging.stderr == b""
    assert partial_materialization.is_dir()
    assert (materializations / "current.json").read_bytes() == (
        materialization_current_bytes
    )
    shutil.rmtree(partial_materialization)

    corrupted_reading = run_dir / "result" / "reading_result.json"
    corrupted_payload = b"{}\n"
    corrupted_reading.write_bytes(corrupted_payload)
    for entry in manifest["assets"]:
        if entry["path"] == "result/reading_result.json":
            entry["byte_length"] = len(corrupted_payload)
            entry["sha256"] = hashlib.sha256(corrupted_payload).hexdigest()
            break
    else:
        raise AssertionError("reading_result asset is missing")
    (run_dir / "manifest.json").write_bytes(_canonical_bytes(manifest))
    (semantic / "current.json").unlink()

    corrupted = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(reuse_site, SOURCE_ROOT),
    )
    corrupted_document = json.loads(corrupted.stdout)
    assert corrupted.returncode == 1
    assert corrupted.stderr == b""
    assert corrupted_document["diagnostics"] == [
        {
            "code": "literature.resume.stage_failed.v1",
            "context": {
                "reason": "asset_integrity_lost",
                "stage": "read",
            },
        }
    ]
    assert not (semantic / "current.json").exists()


def test_public_resume_rejects_candidate_budget_without_partial_publication(
    reader_workspace: tuple[Path, Path, Path, Path],
) -> None:
    literature_root, knowledge_root, pdf_path, runtime_base = reader_workspace
    write_text_pdf(pdf_path, "Evidence supports several distinct Reader drafts.")
    added = _run_add(literature_root, pdf_path)

    canonical_site = runtime_base / "canonical-site"
    canonical_site.mkdir()
    _canonicalize_only_sitecustomize(canonical_site)
    canonicalized = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(canonical_site, SOURCE_ROOT),
    )
    assert canonicalized.returncode == 2

    source_dir = (
        literature_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
    )
    canonical_current = json.loads(
        (source_dir / "canonical" / "current.json").read_bytes()
    )
    canonical_run = (
        source_dir / "canonical" / "runs" / canonical_current["run_id"]
    )
    block = json.loads((canonical_run / "blocks.jsonl").read_bytes().splitlines()[0])
    synopsis = {
        "evidence_block_ids": [block["block_id"]],
        "risk_flags": [],
        "source_terms": ["distinct Reader drafts"],
        "support_kind": "direct",
        "text": "该资料为多个不同候选草稿提供了直接证据。",
    }
    drafts = [
        {
            "candidate_type": "claim",
            "descriptor_refs": [],
            "statement": {
                **synopsis,
                "text": f"这是第 {index} 条具有不同正文的候选结论。",
            },
        }
        for index in range(5)
    ]
    reader_output = {
        "candidate_drafts": drafts,
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
            "synopsis": synopsis,
        },
        "schema_version": "gezhi.literature_reader_output.v1",
    }
    final_path = runtime_base / "reader-final.json"
    final_path.write_bytes(_canonical_bytes(reader_output))
    reader_site = runtime_base / "reader-site"
    reader_site.mkdir()
    _reader_sitecustomize(reader_site)
    codex_home = runtime_base / "home"
    temporary = runtime_base / "temp"
    codex_home.mkdir()
    temporary.mkdir()

    completed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(reader_site, SOURCE_ROOT),
        environment_updates={
            "CODEX_HOME": str(codex_home),
            "READER_DOUBLE_EXE": str(_DOUBLE),
            "READER_DOUBLE_FINAL": str(final_path),
            "TEMP": str(temporary),
            "TMP": str(temporary),
        },
        timeout=30,
    )

    assert json.loads(completed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.stage_failed.v1",
                "context": {
                    "reason": "candidate_validation_failed",
                    "stage": "read",
                },
            }
        ],
        "outcome": "failed",
        "result": {
            "active_source_id": added["source_id"],
            "advanced_stages": [],
            "pending_candidate_ids": [],
            "pipeline_complete": False,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "read",
            "stop_stage": "read",
            "work_id": added["work_id"],
        },
        "schema_version": "gezhi.cli_result.v1",
    }
    assert completed.returncode == 1
    assert completed.stderr == b""
    semantic = source_dir / "semantic"
    assert (semantic / "current.json").exists()
    materializations = semantic / "materializations"
    assert not (materializations / "current.json").exists()
    assert list((materializations / "runs").iterdir()) == []
    assert list((materializations / ".staging").iterdir()) == []


def test_public_resume_never_follows_a_semantic_directory_reparse_point(
    reader_workspace: tuple[Path, Path, Path, Path],
) -> None:
    literature_root, knowledge_root, pdf_path, runtime_base = reader_workspace
    write_text_pdf(pdf_path, "Semantic assets remain inside Literature authority.")
    added = _run_add(literature_root, pdf_path)

    canonical_site = runtime_base / "canonical-site"
    canonical_site.mkdir()
    _canonicalize_only_sitecustomize(canonical_site)
    canonicalized = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(canonical_site, SOURCE_ROOT),
    )
    assert canonicalized.returncode == 2

    source_dir = (
        literature_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
    )
    semantic = source_dir / "semantic"
    outside = runtime_base / "outside-semantic"
    outside.mkdir()
    inject_site = runtime_base / "inject-site"
    inject_site.mkdir()
    _inject_reader_reparse_sitecustomize(inject_site)
    try:
        completed = run_launcher(
            launcher_commands(
                (
                    "--literature-data-root",
                    str(literature_root),
                    "--knowledge-data-root",
                    str(knowledge_root),
                    "literature",
                    "resume",
                    str(added["work_id"]),
                    "--json",
                )
            )[1],
            pythonpath_roots=(inject_site, SOURCE_ROOT),
            environment_updates={"READER_REPARSE_TARGET": str(outside)},
        )

        assert completed.returncode == 1
        assert completed.stderr == b""
        assert json.loads(completed.stdout) == {
            "command": "literature.resume",
            "diagnostics": [
                {
                    "code": "literature.resume.active_source_invalid.v1",
                    "context": {},
                }
            ],
            "outcome": "failed",
            "result": None,
            "schema_version": "gezhi.cli_result.v1",
        }
        assert list(outside.iterdir()) == []
    finally:
        if os.path.lexists(semantic):
            os.rmdir(semantic)


def test_public_resume_retries_only_mechanical_timeouts_and_commits_the_audit(
    reader_workspace: tuple[Path, Path, Path, Path],
) -> None:
    literature_root, knowledge_root, pdf_path, runtime_base = reader_workspace
    write_text_pdf(pdf_path, "Timeout evidence remains immutable across attempts.")
    added = _run_add(literature_root, pdf_path)

    canonical_site = runtime_base / "canonical-site"
    canonical_site.mkdir()
    _canonicalize_only_sitecustomize(canonical_site)
    first_resume = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(canonical_site, SOURCE_ROOT),
    )
    assert first_resume.returncode == 2

    site_root = runtime_base / "timeout-site"
    site_root.mkdir()
    _timeout_sitecustomize(site_root)
    codex_home = runtime_base / "home"
    temporary = runtime_base / "temp"
    codex_home.mkdir()
    temporary.mkdir()
    completed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(site_root, SOURCE_ROOT),
        environment_updates={
            "CODEX_HOME": str(codex_home),
            "READER_DOUBLE_EXE": str(_DOUBLE),
            "TEMP": str(temporary),
            "TMP": str(temporary),
        },
        timeout=30,
    )

    assert json.loads(completed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.stage_blocked.v1",
                "context": {
                    "reason": "codex_timeout_exhausted",
                    "stage": "read",
                },
            }
        ],
        "outcome": "blocked",
        "result": {
            "active_source_id": added["source_id"],
            "advanced_stages": [],
            "pending_candidate_ids": [],
            "pipeline_complete": False,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "read",
            "stop_stage": "read",
            "work_id": added["work_id"],
        },
        "schema_version": "gezhi.cli_result.v1",
    }
    assert completed.returncode == 2
    assert completed.stderr == b""

    source_dir = (
        literature_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
    )
    semantic = source_dir / "semantic"
    assert not (semantic / "current.json").exists()
    run_dirs = [path for path in (semantic / "runs").iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    manifest = json.loads((run_dir / "manifest.json").read_bytes())
    assert manifest["status"] == "blocked"
    assert manifest["reason"] == "codex_timeout_exhausted"
    assert manifest["attempt_count"] == 3
    assert not (run_dir / "result").exists()
    assert [path.name for path in (run_dir / "attempts").iterdir()] == [
        "01",
        "02",
        "03",
    ]
    for ordinal in (1, 2, 3):
        attempt = json.loads(
            (
                run_dir
                / "attempts"
                / f"{ordinal:02d}"
                / "attempt.json"
            ).read_bytes()
        )
        assert attempt["attempt_ordinal"] == ordinal
        assert attempt["failure_class"] == "timeout"


def test_public_resume_does_not_retry_or_guess_from_provider_error_messages(
    reader_workspace: tuple[Path, Path, Path, Path],
) -> None:
    literature_root, knowledge_root, pdf_path, runtime_base = reader_workspace
    write_text_pdf(pdf_path, "Provider messages are evidence, not classifiers.")
    added = _run_add(literature_root, pdf_path)

    canonical_site = runtime_base / "canonical-site"
    canonical_site.mkdir()
    _canonicalize_only_sitecustomize(canonical_site)
    first_resume = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(canonical_site, SOURCE_ROOT),
    )
    assert first_resume.returncode == 2

    message = (
        "429 rate limit; network unavailable; server 503; "
        "context window exceeded"
    )
    message_path = runtime_base / "provider-message.txt"
    message_path.write_text(message, encoding="utf-8")
    site_root = runtime_base / "process-error-site"
    site_root.mkdir()
    _process_error_sitecustomize(site_root)
    codex_home = runtime_base / "home"
    temporary = runtime_base / "temp"
    codex_home.mkdir()
    temporary.mkdir()
    completed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(site_root, SOURCE_ROOT),
        environment_updates={
            "CODEX_HOME": str(codex_home),
            "READER_DOUBLE_EXE": str(_DOUBLE),
            "READER_DOUBLE_MESSAGE": str(message_path),
            "TEMP": str(temporary),
            "TMP": str(temporary),
        },
        timeout=30,
    )

    assert json.loads(completed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.stage_failed.v1",
                "context": {
                    "reason": "codex_process_failed",
                    "stage": "read",
                },
            }
        ],
        "outcome": "failed",
        "result": {
            "active_source_id": added["source_id"],
            "advanced_stages": [],
            "pending_candidate_ids": [],
            "pipeline_complete": False,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "read",
            "stop_stage": "read",
            "work_id": added["work_id"],
        },
        "schema_version": "gezhi.cli_result.v1",
    }
    assert completed.returncode == 1
    assert completed.stderr == b""

    source_dir = (
        literature_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
    )
    semantic = source_dir / "semantic"
    assert not (semantic / "current.json").exists()
    run_dirs = [path for path in (semantic / "runs").iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    manifest = json.loads((run_dir / "manifest.json").read_bytes())
    assert manifest["status"] == "failed"
    assert manifest["reason"] == "codex_process_failed"
    assert manifest["attempt_count"] == 1
    assert not (run_dir / "result").exists()
    assert [path.name for path in (run_dir / "attempts").iterdir()] == ["01"]
    attempt_dir = run_dir / "attempts" / "01"
    attempt = json.loads((attempt_dir / "attempt.json").read_bytes())
    assert attempt["attempt_ordinal"] == 1
    assert attempt["exit_code"] == 71
    assert attempt["failure_class"] == "process_error"
    events = [
        json.loads(line)
        for line in (attempt_dir / "events.jsonl").read_bytes().splitlines()
    ]
    assert events[-1]["error"]["message"] == message


def test_public_resume_preserves_a_bounded_capture_overflow_without_retry(
    reader_workspace: tuple[Path, Path, Path, Path],
) -> None:
    literature_root, knowledge_root, pdf_path, runtime_base = reader_workspace
    write_text_pdf(pdf_path, "Capture overflow remains bounded audit evidence.")
    added = _run_add(literature_root, pdf_path)

    canonical_site = runtime_base / "canonical-site"
    canonical_site.mkdir()
    _canonicalize_only_sitecustomize(canonical_site)
    first_resume = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(canonical_site, SOURCE_ROOT),
    )
    assert first_resume.returncode == 2

    site_root = runtime_base / "capture-overflow-site"
    site_root.mkdir()
    _capture_overflow_sitecustomize(site_root)
    codex_home = runtime_base / "home"
    temporary = runtime_base / "temp"
    codex_home.mkdir()
    temporary.mkdir()
    completed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(site_root, SOURCE_ROOT),
        environment_updates={
            "CODEX_HOME": str(codex_home),
            "READER_DOUBLE_EXE": str(_DOUBLE),
            "TEMP": str(temporary),
            "TMP": str(temporary),
        },
        timeout=30,
    )

    assert completed.returncode == 1
    assert completed.stderr == b""
    assert json.loads(completed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.stage_failed.v1",
                "context": {
                    "reason": "codex_process_failed",
                    "stage": "read",
                },
            }
        ],
        "outcome": "failed",
        "result": {
            "active_source_id": added["source_id"],
            "advanced_stages": [],
            "pending_candidate_ids": [],
            "pipeline_complete": False,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "read",
            "stop_stage": "read",
            "work_id": added["work_id"],
        },
        "schema_version": "gezhi.cli_result.v1",
    }

    source_dir = (
        literature_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
    )
    semantic = source_dir / "semantic"
    assert not (semantic / "current.json").exists()
    run_dirs = [path for path in (semantic / "runs").iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    manifest = json.loads((run_dir / "manifest.json").read_bytes())
    assert manifest["status"] == "failed"
    assert manifest["reason"] == "codex_process_failed"
    assert manifest["attempt_count"] == 1
    assert not (run_dir / "result").exists()
    attempt_dir = run_dir / "attempts" / "01"
    attempt = json.loads((attempt_dir / "attempt.json").read_bytes())
    assert attempt["failure_class"] == "process_error"
    assert (attempt_dir / "final_message.txt").read_bytes() == (
        b"f" * 1_048_576
    )


@pytest.mark.parametrize("failure_case", ["invalid_json", "out_of_scope_evidence"])
def test_public_resume_preserves_invalid_model_output_without_publishing_results(
    reader_workspace: tuple[Path, Path, Path, Path],
    failure_case: str,
) -> None:
    literature_root, knowledge_root, pdf_path, runtime_base = reader_workspace
    write_text_pdf(pdf_path, "Only evidence from this canonical asset is allowed.")
    added = _run_add(literature_root, pdf_path)

    canonical_site = runtime_base / "canonical-site"
    canonical_site.mkdir()
    _canonicalize_only_sitecustomize(canonical_site)
    first_resume = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(canonical_site, SOURCE_ROOT),
    )
    assert first_resume.returncode == 2

    if failure_case == "invalid_json":
        final_bytes = b'{"schema_version":'
    else:
        statement = {
            "evidence_block_ids": ["blk_" + "0" * 24],
            "risk_flags": [],
            "source_terms": [],
            "support_kind": "direct",
            "text": "这条陈述引用了本次输入范围之外的证据。",
        }
        final_bytes = _canonical_bytes(
            {
                "candidate_drafts": [],
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
        )
    final_path = runtime_base / "invalid-reader-final.bin"
    final_path.write_bytes(final_bytes)
    site_root = runtime_base / "reader-site"
    site_root.mkdir()
    _reader_sitecustomize(site_root)
    codex_home = runtime_base / "home"
    temporary = runtime_base / "temp"
    codex_home.mkdir()
    temporary.mkdir()
    completed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(site_root, SOURCE_ROOT),
        environment_updates={
            "CODEX_HOME": str(codex_home),
            "READER_DOUBLE_EXE": str(_DOUBLE),
            "READER_DOUBLE_FINAL": str(final_path),
            "TEMP": str(temporary),
            "TMP": str(temporary),
        },
        timeout=30,
    )

    assert json.loads(completed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.stage_failed.v1",
                "context": {
                    "reason": "reader_output_invalid",
                    "stage": "read",
                },
            }
        ],
        "outcome": "failed",
        "result": {
            "active_source_id": added["source_id"],
            "advanced_stages": [],
            "pending_candidate_ids": [],
            "pipeline_complete": False,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "read",
            "stop_stage": "read",
            "work_id": added["work_id"],
        },
        "schema_version": "gezhi.cli_result.v1",
    }
    assert completed.returncode == 1
    assert completed.stderr == b""

    source_dir = (
        literature_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
    )
    semantic = source_dir / "semantic"
    assert not (semantic / "current.json").exists()
    run_dirs = [path for path in (semantic / "runs").iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert list((semantic / ".staging").iterdir()) == []
    manifest = json.loads((run_dir / "manifest.json").read_bytes())
    assert manifest["status"] == "failed"
    assert manifest["reason"] == "reader_output_invalid"
    assert manifest["attempt_count"] == 1
    assert manifest["candidate_count"] == 0
    assert not (run_dir / "result").exists()
    attempt_dir = run_dir / "attempts" / "01"
    attempt = json.loads((attempt_dir / "attempt.json").read_bytes())
    assert attempt["failure_class"] is None
    assert (attempt_dir / "final_message.txt").read_bytes() == final_bytes


def test_public_resume_commits_a_runtime_block_and_recovers_attempted_staging(
    reader_workspace: tuple[Path, Path, Path, Path],
) -> None:
    literature_root, knowledge_root, pdf_path, runtime_base = reader_workspace
    write_text_pdf(pdf_path, "Runtime preflight happens before attempt commitment.")
    added = _run_add(literature_root, pdf_path)

    canonical_site = runtime_base / "canonical-site"
    canonical_site.mkdir()
    _canonicalize_only_sitecustomize(canonical_site)
    first_resume = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(canonical_site, SOURCE_ROOT),
    )
    assert first_resume.returncode == 2

    site_root = runtime_base / "pre-attempt-site"
    site_root.mkdir()
    _pre_attempt_rejected_sitecustomize(site_root)
    temporary = runtime_base / "temp"
    temporary.mkdir()
    completed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(site_root, SOURCE_ROOT),
        environment_updates={"TEMP": str(temporary), "TMP": str(temporary)},
        timeout=30,
    )

    assert json.loads(completed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.stage_blocked.v1",
                "context": {
                    "reason": "codex_runtime_unavailable",
                    "stage": "read",
                },
            }
        ],
        "outcome": "blocked",
        "result": {
            "active_source_id": added["source_id"],
            "advanced_stages": [],
            "pending_candidate_ids": [],
            "pipeline_complete": False,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "read",
            "stop_stage": "read",
            "work_id": added["work_id"],
        },
        "schema_version": "gezhi.cli_result.v1",
    }
    assert completed.returncode == 2
    assert completed.stderr == b""

    source_dir = (
        literature_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
    )
    semantic = source_dir / "semantic"
    assert not (semantic / "current.json").exists()
    run_dirs = [path for path in (semantic / "runs").iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert list((semantic / ".staging").iterdir()) == []
    manifest = json.loads((run_dir / "manifest.json").read_bytes())
    assert manifest["status"] == "blocked"
    assert manifest["reason"] == "codex_runtime_unavailable"
    assert manifest["attempt_count"] == 0
    assert manifest["attempts"] == []
    assert manifest["usage_totals"] == {
        "cached_input_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    assert list((run_dir / "attempts").iterdir()) == []
    assert not (run_dir / "result").exists()

    orphan_run_id = run_dir.name
    interrupted_attempt = {
        "attempt_ordinal": 1,
        "cached_input_tokens": None,
        "elapsed_ms": 25,
        "exit_code": None,
        "failure_class": "process_error",
        "finished_at": "2026-08-28T12:00:01.000Z",
        "input_tokens": None,
        "output_tokens": None,
        "reasoning_output_tokens": None,
        "resource_ledger_count": 0,
        "schema_version": "gezhi.literature_codex_attempt.v1",
        "started_at": "2026-08-28T12:00:00.000Z",
        "usage_unavailable": True,
    }
    interrupted_attempt_dir = run_dir / "attempts" / "01"
    interrupted_attempt_dir.mkdir()
    (interrupted_attempt_dir / "attempt.json").write_bytes(
        _canonical_bytes(interrupted_attempt)
    )
    (interrupted_attempt_dir / "events.jsonl").write_bytes(
        b'{"error":{"message":"raw provider evidence"},"type":"turn.failed"}\n'
    )
    (run_dir / "manifest.json").unlink()
    orphan_stage = semantic / ".staging" / orphan_run_id
    run_dir.rename(orphan_stage)

    canonical_current = json.loads(
        (source_dir / "canonical" / "current.json").read_bytes()
    )
    canonical_run = (
        source_dir / "canonical" / "runs" / canonical_current["run_id"]
    )
    block = json.loads((canonical_run / "blocks.jsonl").read_bytes().splitlines()[0])
    statement = {
        "evidence_block_ids": [block["block_id"]],
        "risk_flags": [],
        "source_terms": ["Runtime preflight"],
        "support_kind": "direct",
        "text": "运行时预检发生在 attempt 承诺之前。",
    }
    final_bytes = _canonical_bytes(
        {
            "candidate_drafts": [],
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
    )
    final_path = runtime_base / "recovery-reader-final.json"
    final_path.write_bytes(final_bytes)
    reader_site = runtime_base / "reader-site"
    reader_site.mkdir()
    _reader_sitecustomize(reader_site)
    codex_home = runtime_base / "home"
    codex_home.mkdir()
    resumed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(reader_site, SOURCE_ROOT),
        environment_updates={
            "CODEX_HOME": str(codex_home),
            "READER_DOUBLE_EXE": str(_DOUBLE),
            "READER_DOUBLE_FINAL": str(final_path),
            "TEMP": str(temporary),
            "TMP": str(temporary),
        },
        timeout=30,
    )
    assert resumed.returncode == 0, (
        resumed.stdout + resumed.stderr
    ).decode(errors="replace")
    assert resumed.stderr == b""
    assert json.loads(resumed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [],
        "outcome": "succeeded",
        "result": {
            "active_source_id": added["source_id"],
            "advanced_stages": ["read"],
            "pending_candidate_ids": [],
            "pipeline_complete": True,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "read",
            "stop_stage": "complete",
            "work_id": added["work_id"],
        },
        "schema_version": "gezhi.cli_result.v1",
    }
    current = json.loads((semantic / "current.json").read_bytes())
    assert current["run_id"] != orphan_run_id
    assert list((semantic / ".staging").iterdir()) == []
    recovered_orphan = semantic / "runs" / orphan_run_id
    interrupted = json.loads((recovered_orphan / "manifest.json").read_bytes())
    assert interrupted["status"] == "interrupted"
    assert interrupted["reason"] == "interrupted"
    assert interrupted["attempt_count"] == 1
    assert interrupted["attempts"] == [interrupted_attempt]
    assert interrupted["usage_totals"] == {
        "cached_input_tokens": None,
        "input_tokens": None,
        "output_tokens": None,
        "reasoning_output_tokens": None,
    }
    assert not (recovered_orphan / "result").exists()

    materializations = semantic / "materializations"
    materialization_current = json.loads(
        (materializations / "current.json").read_bytes()
    )
    materialization_run = (
        materializations / "runs" / materialization_current["run_id"]
    )
    assert (
        materialization_run / "result" / "descriptor_payloads.jsonl"
    ).read_bytes() == b""
    assert (
        materialization_run / "result" / "candidate_knowledge.jsonl"
    ).read_bytes() == b""
    assert json.loads(
        (materialization_run / "result" / "review_queue.json").read_bytes()
    )["candidates"] == []
    work_dir = literature_root / "works" / str(added["work_id"])
    assert not (work_dir / "reviews").exists()
    assert not (work_dir / "handoffs").exists()

    materialization_run_names = [
        path.name for path in (materializations / "runs").iterdir()
    ]
    reuse_site = runtime_base / "reuse-site"
    reuse_site.mkdir()
    _reject_reader_attempt_sitecustomize(reuse_site)
    reused = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(reuse_site, SOURCE_ROOT),
    )
    assert json.loads(reused.stdout) == {
        "command": "literature.resume",
        "diagnostics": [],
        "outcome": "succeeded",
        "result": {
            "active_source_id": added["source_id"],
            "advanced_stages": [],
            "pending_candidate_ids": [],
            "pipeline_complete": True,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "complete",
            "stop_stage": "complete",
            "work_id": added["work_id"],
        },
        "schema_version": "gezhi.cli_result.v1",
    }
    assert reused.returncode == 0
    assert reused.stderr == b""
    assert [path.name for path in (materializations / "runs").iterdir()] == (
        materialization_run_names
    )

    partial_run_id = "semrun_33333333-3333-4333-8333-333333333333"
    partial_stage = semantic / ".staging" / partial_run_id
    partial_attempt = partial_stage / "attempts" / "01"
    partial_attempt.mkdir(parents=True)
    successful_run = semantic / "runs" / current["run_id"]
    for name in ("input.jsonl", "prompt.txt", "schema.json"):
        shutil.copyfile(successful_run / name, partial_stage / name)
    (partial_attempt / "events.jsonl").write_bytes(
        b'{"type":"thread.started"}\n'
    )
    reject_partial_site = runtime_base / "reject-partial-site"
    reject_partial_site.mkdir()
    _reject_reader_attempt_sitecustomize(reject_partial_site)
    partial = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(reject_partial_site, SOURCE_ROOT),
        timeout=30,
    )
    assert json.loads(partial.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.recovery_failed.v1",
                "context": {},
            }
        ],
        "outcome": "failed",
        "result": None,
        "schema_version": "gezhi.cli_result.v1",
    }
    assert partial.returncode == 1
    assert partial.stderr == b""
    assert partial_stage.is_dir()
    assert not (partial_stage / "manifest.json").exists()
    assert json.loads((semantic / "current.json").read_bytes()) == current
    shutil.rmtree(partial_stage)

    ambiguous_names = (
        "semrun_11111111-1111-4111-8111-111111111111",
        "semrun_22222222-2222-4222-8222-222222222222",
    )
    for name in ambiguous_names:
        (semantic / ".staging" / name).mkdir()
    reject_site = runtime_base / "reject-site"
    reject_site.mkdir()
    _reject_reader_attempt_sitecustomize(reject_site)
    ambiguous = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(reject_site, SOURCE_ROOT),
        timeout=30,
    )
    assert json.loads(ambiguous.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.recovery_failed.v1",
                "context": {},
            }
        ],
        "outcome": "failed",
        "result": None,
        "schema_version": "gezhi.cli_result.v1",
    }
    assert ambiguous.returncode == 1
    assert ambiguous.stderr == b""
    assert sorted(path.name for path in (semantic / ".staging").iterdir()) == list(
        ambiguous_names
    )


def test_public_resume_classifies_malformed_events_as_one_process_error(
    reader_workspace: tuple[Path, Path, Path, Path],
) -> None:
    literature_root, knowledge_root, pdf_path, runtime_base = reader_workspace
    write_text_pdf(pdf_path, "Malformed provider events remain raw audit evidence.")
    added = _run_add(literature_root, pdf_path)

    canonical_site = runtime_base / "canonical-site"
    canonical_site.mkdir()
    _canonicalize_only_sitecustomize(canonical_site)
    first_resume = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(canonical_site, SOURCE_ROOT),
    )
    assert first_resume.returncode == 2

    site_root = runtime_base / "malformed-site"
    site_root.mkdir()
    _malformed_events_sitecustomize(site_root)
    temporary = runtime_base / "temp"
    temporary.mkdir()
    completed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(literature_root),
                "--knowledge-data-root",
                str(knowledge_root),
                "literature",
                "resume",
                str(added["work_id"]),
                "--json",
            )
        )[1],
        pythonpath_roots=(site_root, SOURCE_ROOT),
        environment_updates={
            "READER_DOUBLE_EXE": str(_DOUBLE),
            "TEMP": str(temporary),
            "TMP": str(temporary),
        },
        timeout=30,
    )
    assert json.loads(completed.stdout) == {
        "command": "literature.resume",
        "diagnostics": [
            {
                "code": "literature.resume.stage_failed.v1",
                "context": {
                    "reason": "codex_process_failed",
                    "stage": "read",
                },
            }
        ],
        "outcome": "failed",
        "result": {
            "active_source_id": added["source_id"],
            "advanced_stages": [],
            "pending_candidate_ids": [],
            "pipeline_complete": False,
            "schema_version": "gezhi.literature_resume_result.v1",
            "start_stage": "read",
            "stop_stage": "read",
            "work_id": added["work_id"],
        },
        "schema_version": "gezhi.cli_result.v1",
    }
    assert completed.returncode == 1
    assert completed.stderr == b""

    source_dir = (
        literature_root
        / "works"
        / str(added["work_id"])
        / "sources"
        / str(added["source_id"])
    )
    semantic = source_dir / "semantic"
    assert not (semantic / "current.json").exists()
    run_dirs = [path for path in (semantic / "runs").iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert not (run_dir / "result").exists()
    manifest = json.loads((run_dir / "manifest.json").read_bytes())
    assert manifest["status"] == "failed"
    assert manifest["reason"] == "codex_process_failed"
    assert manifest["attempt_count"] == 1
    attempt_dir = run_dir / "attempts" / "01"
    attempt = json.loads((attempt_dir / "attempt.json").read_bytes())
    assert attempt["exit_code"] == 0
    assert attempt["failure_class"] == "process_error"
    assert attempt["usage_unavailable"] is True
    assert attempt["input_tokens"] is None
    assert attempt["cached_input_tokens"] is None
    assert attempt["output_tokens"] is None
    assert attempt["reasoning_output_tokens"] is None
    assert (attempt_dir / "events.jsonl").read_bytes() == b"\xff{not-json\n"
    assert (attempt_dir / "final_message.txt").read_bytes() == b"\xffnot-json"
