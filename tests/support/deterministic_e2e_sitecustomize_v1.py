from __future__ import annotations

import json
import ntpath
import os
import subprocess
import sys
from pathlib import Path


def _canonical_json_line(value: object) -> bytes:
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


def _reader_output_v1(prompt: bytes) -> bytes:
    begin = b"--- BEGIN READER INPUT JSONL ---\n"
    end = b"--- END READER INPUT JSONL ---\n"
    payload = prompt.split(begin, 1)[1].split(end, 1)[0]
    records = [json.loads(line) for line in payload.splitlines()]
    block = next(item for item in records if item.get("record_type") == "block")
    source_term = "Deterministic OCR evidence"
    if source_term not in block["text"]:
        raise AssertionError("the OCR fixture evidence did not reach the reader")
    statement = {
        "evidence_block_ids": [block["block_id"]],
        "risk_flags": [],
        "source_terms": [source_term],
        "support_kind": "direct",
        "text": "确定性 OCR 证据支持格致完整公开流程。",
    }
    return _canonical_json_line(
        {
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
    )


def _answerer_output_v1(prompt: bytes) -> bytes:
    begin = b"--- BEGIN RETRIEVAL VIEW JSON ---\n"
    end = b"--- END RETRIEVAL VIEW JSON ---\n"
    retrieval = json.loads(prompt.split(begin, 1)[1].split(end, 1)[0])
    items = retrieval["items"]
    if len(items) != 1:
        raise AssertionError("the deterministic answer fixture needs one Candidate")
    candidate_id = items[0]["candidate"]["candidate_id"]
    return _canonical_json_line(
        {
            "answer_status": "answered",
            "answer_units": [
                {
                    "candidate_id": candidate_id,
                    "text": "确定性全链证据由该 Candidate 支持。",
                }
            ],
            "insufficiency_reason": None,
            "qualification_units": [],
            "schema_version": "gezhi.answer_output.v1",
        }
    )


def _run_codex_double_v1(
    request: object,
    *,
    capture_profile: str,
    codex_double: Path,
    output_name: str,
    output_payload: bytes,
) -> object:
    from gezhi._codex_child_process import (
        AttemptTerminalEvidenceV1,
        NeverCancelledV1,
        _run_codex_child_test_double_v1,
    )
    from gezhi._codex_role_plan import _freeze_test_double_launch_v1

    output_path = request.attempt_root / output_name
    output_path.write_bytes(output_payload)
    capture_parent = request.attempt_root / "captures"
    capture = capture_parent / f"{request.attempt_ordinal:02d}"
    staging = capture_parent / f".{request.attempt_ordinal:02d}.codex-stage"
    final_spool = staging / ".final_message.spool"
    plan = _freeze_test_double_launch_v1(
        executable=Path(sys.executable),
        arguments=(
            "-I",
            "-B",
            str(codex_double),
            "final-from-file",
            "--final",
            str(final_spool),
            "--payload-file",
            str(output_path),
        ),
        prompt=request.prompt,
        attempt_ordinal=request.attempt_ordinal,
        working_directory=request.attempt_root / "working",
        capture_directory=capture,
        staging_directory=staging,
        temporary_directory=request.attempt_root / "temporary",
        source_environment={"SystemRoot": os.environ["SystemRoot"]},
        timeout_seconds=10.0,
        capture_profile=capture_profile,
    )
    result = _run_codex_child_test_double_v1(plan, NeverCancelledV1())
    if not isinstance(result, AttemptTerminalEvidenceV1):
        raise TypeError(f"the deterministic {capture_profile} child did not complete")
    return result


def _install_literature_doubles_v1() -> None:
    from gezhi import _literature_reader as reader
    from gezhi import _literature_resume as resume
    from gezhi._bounded_probe import run_bounded_probe_v1

    ocr_double = Path(os.environ["T25_OCR_DOUBLE_EXE"])
    codex_double = Path(os.environ["T25_CODEX_DOUBLE_EXE"])

    def resolve_ocr_runtime() -> object:
        return resume.OcrRuntimeProfileV1(
            executable_path=str(ocr_double),
            environment=(("SystemRoot", os.environ["SystemRoot"]),),
            profile_identity_sha256=(resume.expected_ocr_profile_identity_sha256_v1()),
        )

    def run_ocr_attempt(
        _profile: object,
        input_path: Path,
        output_root: Path,
    ) -> object:
        if not ocr_double.is_file():
            raise resume.OcrRuntimeUnavailableV1
        child_environment = {"SystemRoot": os.environ["SystemRoot"]}
        marker = os.environ.get("T25_OCR_DOUBLE_MARKER")
        if marker:
            child_environment["T25_OCR_DOUBLE_MARKER"] = marker
        scenario = os.environ.get("T25_OCR_DOUBLE_SCENARIO")
        if scenario:
            child_environment["T25_OCR_DOUBLE_SCENARIO"] = scenario
        completed = run_bounded_probe_v1(
            (
                sys.executable,
                "-I",
                "-B",
                str(ocr_double),
                "-p",
                str(input_path),
                "-o",
                str(output_root),
                "-b",
                "pipeline",
                "-m",
                "ocr",
                "-l",
                "ch",
            ),
            environment=child_environment,
            timeout_seconds=10.0,
            output_limit=1_048_576,
            creation_flags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return resume.OcrAttemptResultV1(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def run_reader_attempt(request: object) -> object:
        return _run_codex_double_v1(
            request,
            capture_profile="literature",
            codex_double=codex_double,
            output_name="reader-output.json",
            output_payload=_reader_output_v1(request.prompt),
        )

    resume._resolve_ocr_runtime_v1 = resolve_ocr_runtime
    resume._run_ocr_attempt_v1 = run_ocr_attempt
    reader._prepare_role_invocation_v1 = lambda: object()
    reader._run_role_attempt_v1 = run_reader_attempt


def _install_answerer_double_v1() -> None:
    from gezhi import _knowledge_answerer as answerer

    codex_double = Path(os.environ["T25_CODEX_DOUBLE_EXE"])

    def run_answerer_attempt(request: object) -> object:
        return _run_codex_double_v1(
            request,
            capture_profile="knowledge",
            codex_double=codex_double,
            output_name="answer-output.json",
            output_payload=_answerer_output_v1(request.prompt),
        )

    answerer._prepare_role_invocation_v1 = lambda: object()
    answerer._run_role_attempt_v1 = run_answerer_attempt


def _install_codex_forbidden_guard_v1() -> None:
    marker = Path(os.environ["T25_CODEX_GUARD_MARKER"])
    marker.write_bytes(b"armed\n")
    real_popen = subprocess.Popen

    def guarded_popen(command: object, *args: object, **kwargs: object) -> object:
        executable = command[0] if isinstance(command, (list, tuple)) else command
        if ntpath.basename(os.fspath(executable)).casefold() == "codex.exe":
            with marker.open("ab", buffering=0) as target:
                target.write(b"launched\n")
            raise AssertionError("Codex must not run for a zero-match answer")
        return real_popen(command, *args, **kwargs)

    subprocess.Popen = guarded_popen


def _install_doctor_observation_v1() -> None:
    from gezhi import _doctor_runtime as runtime

    def observe_doctor(*, cli_patch: object) -> tuple[tuple[str, str, None], ...]:
        assert type(cli_patch) is tuple
        return tuple(
            (check_id, "ready", None)
            for check_id in (
                "configuration",
                "core_python",
                "core_dependencies",
                "literature_data_root",
                "knowledge_data_root",
                "ocr_runtime",
                "codex_runtime",
            )
        )

    runtime.observe_doctor = observe_doctor


def install_from_environment_v1() -> None:
    mode = os.environ.get("T25_DOUBLE_MODE")
    if mode == "literature":
        _install_literature_doubles_v1()
    elif mode == "answerer":
        _install_answerer_double_v1()
    elif mode == "forbid-codex":
        _install_codex_forbidden_guard_v1()
    elif mode == "doctor":
        _install_doctor_observation_v1()
