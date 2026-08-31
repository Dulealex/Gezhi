from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest
from launcher_support import (
    SOURCE_ROOT,
    launcher_commands,
    run_both_launchers,
    run_launcher,
)
from literature_pdf_support import write_blank_pdf
from support.deterministic_e2e_contract_v1 import (
    assert_command_result_v1,
    assert_diagnostic_matrix_v1,
    expected_human_bytes_v1,
)

TEST_ROOT = Path(__file__).parent
OCR_DOUBLE = TEST_ROOT / "support" / "ocr_executable_double_v1.py"
CODEX_DOUBLE = TEST_ROOT / "support" / "codex_child_executable_double_v1.py"
_OUTCOME_EXIT_CODES = {
    "blocked": 2,
    "failed": 1,
    "interrupted": 130,
    "succeeded": 0,
}
_ANSWER_ID = re.compile(
    rb"ans_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)


@dataclass(frozen=True, slots=True)
class _E2eWorkspaceV1:
    literature_root: Path
    knowledge_root: Path
    pdf_path: Path
    site_root: Path
    runtime_root: Path


@pytest.fixture
def deterministic_e2e_workspace() -> Iterator[_E2eWorkspaceV1]:
    data_container = Path(r"E:\Gezhi\data")
    runtime_container = Path(r"E:\gztest")
    data_container.mkdir(parents=True, exist_ok=True)
    runtime_container.mkdir(parents=True, exist_ok=True)
    suffix = "t25-" + uuid.uuid4().hex[:12]
    data_root = data_container / suffix
    runtime_root = runtime_container / suffix
    literature_root = data_root / "literature"
    knowledge_root = data_root / "knowledge"
    site_root = runtime_root / "site"
    for path in (literature_root, knowledge_root, site_root):
        path.mkdir(parents=True)
    (runtime_root / "temp").mkdir()
    (runtime_root / "codex-home").mkdir()
    (site_root / "sitecustomize.py").write_text(
        "from support.deterministic_e2e_sitecustomize_v1 import "
        "install_from_environment_v1\n"
        "install_from_environment_v1()\n",
        encoding="utf-8",
    )
    pdf_path = data_root / "scanned-paper.pdf"
    write_blank_pdf(pdf_path)
    try:
        yield _E2eWorkspaceV1(
            literature_root=literature_root,
            knowledge_root=knowledge_root,
            pdf_path=pdf_path,
            site_root=site_root,
            runtime_root=runtime_root,
        )
    finally:
        resolved_data = data_root.resolve(strict=True)
        resolved_runtime = runtime_root.resolve(strict=True)
        assert resolved_data.parent == data_container.resolve(strict=True)
        assert resolved_runtime.parent == runtime_container.resolve(strict=True)
        assert resolved_data.name == suffix == resolved_runtime.name
        shutil.rmtree(resolved_data)
        shutil.rmtree(resolved_runtime)


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


def _read_canonical_json(path: Path) -> tuple[dict[str, object], bytes]:
    payload = path.read_bytes()
    value = json.loads(payload)
    assert isinstance(value, dict)
    assert payload == _canonical_json_line(value)
    return value, payload


def _json_result(completed: object) -> dict[str, object]:
    assert completed.stderr == b""
    assert completed.stdout.endswith(b"\n")
    envelope = json.loads(completed.stdout)
    assert completed.stdout == _canonical_json_line(envelope)
    assert set(envelope) == {
        "command",
        "diagnostics",
        "outcome",
        "result",
        "schema_version",
    }
    assert envelope["schema_version"] == "gezhi.cli_result.v1"
    command = envelope["command"]
    outcome = envelope["outcome"]
    assert isinstance(command, str)
    assert outcome in _OUTCOME_EXIT_CODES
    assert completed.returncode == _OUTCOME_EXIT_CODES[outcome]
    diagnostics = envelope["diagnostics"]
    assert isinstance(diagnostics, list)
    diagnostic_prefix = {
        "doctor": "operations.doctor.",
        "status": "operations.status.",
    }.get(command, command + ".")
    assert all(
        isinstance(item, dict)
        and set(item) == {"code", "context"}
        and isinstance(item["code"], str)
        and item["code"].startswith(diagnostic_prefix)
        and isinstance(item["context"], dict)
        for item in diagnostics
    )
    result = envelope["result"]
    if result is not None:
        assert_command_result_v1(command, result)
    assert_diagnostic_matrix_v1(
        command=command,
        outcome=outcome,
        result=result,
        diagnostics=diagnostics,
    )
    return envelope


def _assert_human_success(completed: object) -> None:
    assert completed.returncode == 0
    assert completed.stderr == b""
    assert completed.stdout
    assert completed.stdout.endswith(b"\n")
    assert b"\r" not in completed.stdout
    assert b"\x1b" not in completed.stdout


def _assert_exact_answer_human(
    workspace: _E2eWorkspaceV1,
    completed: object,
) -> None:
    _assert_human_success(completed)
    first_line, id_line, next_line, blank, markdown = completed.stdout.split(b"\n", 4)
    assert first_line == "Knowledge ask：完成".encode()
    assert id_line.startswith("Answer ID：".encode())
    answer_id = id_line.decode().removeprefix("Answer ID：")
    assert _ANSWER_ID.fullmatch(answer_id.encode("ascii")) is not None
    assert next_line == "下一步：无需操作".encode()
    assert blank == b""
    assert (
        markdown
        == (workspace.knowledge_root / "answers" / answer_id / "answer.md").read_bytes()
    )


def _assert_manifest_assets(
    root: Path,
    manifest: dict[str, object],
    *,
    complete_inventory: bool = True,
) -> None:
    assets = manifest["assets"]
    assert isinstance(assets, list)
    paths = [str(item["path"]) for item in assets]
    assert paths == sorted(paths, key=lambda value: value.encode("utf-8"))
    assert len(paths) == len(set(paths))
    for item in assets:
        assert isinstance(item, dict)
        relative = str(item["path"])
        assert "\\" not in relative
        assert not relative.startswith("/")
        assert ".." not in Path(relative).parts
        payload = (root / Path(relative)).read_bytes()
        assert item["byte_length"] == len(payload)
        assert item["sha256"] == hashlib.sha256(payload).hexdigest()
    if complete_inventory:
        observed = sorted(
            (
                path.relative_to(root).as_posix()
                for path in root.rglob("*")
                if path.is_file() and path.name != "manifest.json"
            ),
            key=lambda value: value.encode("utf-8"),
        )
        assert paths == observed


def _read_current_run(
    namespace: Path,
    *,
    current_schema: str,
    manifest_schema: str,
) -> tuple[dict[str, object], Path, dict[str, object], bytes]:
    current, _current_bytes = _read_canonical_json(namespace / "current.json")
    assert current["schema_version"] == current_schema
    run = namespace / "runs" / str(current["run_id"])
    manifest, manifest_bytes = _read_canonical_json(run / "manifest.json")
    assert current["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert manifest["schema_version"] == manifest_schema
    assert manifest["run_id"] == current["run_id"]
    _assert_manifest_assets(run, manifest)
    return current, run, manifest, manifest_bytes


def _tree_snapshot(root: Path) -> tuple[tuple[str, int, str], ...]:
    if not root.exists():
        return ()
    return tuple(
        (
            path.relative_to(root).as_posix(),
            len(payload := path.read_bytes()),
            hashlib.sha256(payload).hexdigest(),
        )
        for path in sorted(
            (item for item in root.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(root).as_posix().encode("utf-8"),
        )
    )


def _assert_exact_launcher_parity(
    arguments: tuple[str, ...],
    *,
    expected_command: str,
    environment_updates: dict[str, str] | None = None,
    pythonpath_roots: tuple[Path, ...] = (SOURCE_ROOT,),
    timeout: float = 45.0,
) -> None:
    json_results = run_both_launchers(
        (*arguments, "--json"),
        environment_updates=environment_updates,
        pythonpath_roots=pythonpath_roots,
        timeout=timeout,
    )
    json_receipts = [
        (result.returncode, result.stdout, result.stderr) for result in json_results
    ]
    assert json_receipts[0] == json_receipts[1]
    envelopes = [_json_result(result) for result in json_results]
    assert all(envelope["command"] == expected_command for envelope in envelopes)
    expected_human = expected_human_bytes_v1(envelopes[0])

    human_results = run_both_launchers(
        arguments,
        environment_updates=environment_updates,
        pythonpath_roots=pythonpath_roots,
        timeout=timeout,
    )
    human_receipts = [
        (result.returncode, result.stdout, result.stderr) for result in human_results
    ]
    assert human_receipts[0] == human_receipts[1]
    assert human_receipts[0] == (
        _OUTCOME_EXIT_CODES[str(envelopes[0]["outcome"])],
        expected_human,
        b"",
    )


def _assert_dynamic_answer_launcher_parity(
    workspace: _E2eWorkspaceV1,
    arguments: tuple[str, ...],
    *,
    environment_updates: dict[str, str],
) -> None:
    json_results = run_both_launchers(
        (*arguments, "--json"),
        environment_updates=environment_updates,
        pythonpath_roots=(workspace.site_root, TEST_ROOT, SOURCE_ROOT),
        timeout=45.0,
    )
    normalized_json: list[bytes] = []
    for completed in json_results:
        envelope = _json_result(completed)
        assert envelope["command"] == "knowledge.ask"
        assert envelope["outcome"] == "succeeded"
        result = envelope["result"]
        assert isinstance(result, dict)
        answer_id = str(result["answer_id"])
        assert _ANSWER_ID.fullmatch(answer_id.encode("ascii")) is not None
        result["answer_id"] = "ans_<dynamic>"
        normalized_json.append(_canonical_json_line(envelope))
    assert normalized_json[0] == normalized_json[1]

    human_results = run_both_launchers(
        arguments,
        environment_updates=environment_updates,
        pythonpath_roots=(workspace.site_root, TEST_ROOT, SOURCE_ROOT),
        timeout=45.0,
    )
    for completed in human_results:
        _assert_exact_answer_human(workspace, completed)
    assert _ANSWER_ID.sub(b"ans_<dynamic>", human_results[0].stdout) == _ANSWER_ID.sub(
        b"ans_<dynamic>", human_results[1].stdout
    )


def _assert_full_evidence_chain(
    workspace: _E2eWorkspaceV1,
    *,
    added: dict[str, object],
    reviewed: dict[str, object],
    shown: dict[str, object],
    asked: dict[str, object],
) -> None:
    work_id = str(added["work_id"])
    source_id = str(added["source_id"])
    candidate_id = str(reviewed["candidate_id"])
    source_sha256 = hashlib.sha256(workspace.pdf_path.read_bytes()).hexdigest()
    assert added["source_sha256"] == source_sha256
    work_root = workspace.literature_root / "works" / work_id
    source_root = work_root / "sources" / source_id

    assert (
        source_root / "original.pdf"
    ).read_bytes() == workspace.pdf_path.read_bytes()
    source_document, source_document_bytes = _read_canonical_json(
        source_root / "source.json"
    )
    assert source_document == {
        "byte_length": len(workspace.pdf_path.read_bytes()),
        "media_type": "application/pdf",
        "schema_version": "gezhi.literature_source.v1",
        "source_id": source_id,
        "source_sha256": source_sha256,
        "work_id": work_id,
    }
    source_manifest, source_manifest_bytes = _read_canonical_json(
        source_root / "manifest.json"
    )
    assert source_manifest["schema_version"] == "gezhi.literature_source_manifest.v1"
    assert source_manifest["source_id"] == source_id
    assert source_manifest["source_sha256"] == source_sha256
    assert source_manifest["work_id"] == work_id
    _assert_manifest_assets(source_root, source_manifest, complete_inventory=False)
    source_assets = {str(item["path"]): item for item in source_manifest["assets"]}
    assert source_assets["original.pdf"]["sha256"] == source_sha256
    assert (
        source_assets["source.json"]["sha256"]
        == hashlib.sha256(source_document_bytes).hexdigest()
    )
    active_source, _active_source_bytes = _read_canonical_json(
        work_root / "active_source.json"
    )
    assert active_source == {
        "manifest_sha256": hashlib.sha256(source_manifest_bytes).hexdigest(),
        "schema_version": "gezhi.literature_active_source.v1",
        "source_id": source_id,
        "source_sha256": source_sha256,
        "work_id": work_id,
    }

    ocr_current, ocr_run, ocr_manifest, ocr_manifest_bytes = _read_current_run(
        source_root / "ocr",
        current_schema="gezhi.literature_ocr_current.v1",
        manifest_schema="gezhi.literature_ocr_run_manifest.v1",
    )
    assert ocr_current["source_id"] == source_id
    assert ocr_current["source_sha256"] == source_sha256
    assert ocr_current["work_id"] == work_id
    assert ocr_manifest["status"] == "succeeded"
    ocr_input, _ocr_input_bytes = _read_canonical_json(ocr_run / "input.json")
    assert (
        ocr_input["source_manifest_sha256"]
        == hashlib.sha256(source_manifest_bytes).hexdigest()
    )
    assert ocr_input["source_sha256"] == source_sha256
    assert (
        ocr_input["input_fingerprint_sha256"] == ocr_current["input_fingerprint_sha256"]
    )
    ocr_selection, _ocr_selection_bytes = _read_canonical_json(
        ocr_run / "selection.json"
    )
    assert ocr_selection["method"] == "mineru_ocr"
    ocr_receipt, _ocr_receipt_bytes = _read_canonical_json(ocr_run / "receipt.json")
    assert ocr_receipt["status"] == "succeeded"
    assert ocr_receipt["method"] == "mineru_ocr"
    assert ocr_receipt["run_id"] == ocr_current["run_id"]

    (
        canonical_current,
        canonical_run,
        canonical_manifest,
        canonical_manifest_bytes,
    ) = _read_current_run(
        source_root / "canonical",
        current_schema="gezhi.literature_canonical_current.v1",
        manifest_schema="gezhi.literature_canonical_run_manifest.v1",
    )
    assert canonical_manifest["status"] == "succeeded"
    assert canonical_manifest["source_sha256"] == source_sha256
    assert canonical_manifest["ocr_run_id"] == ocr_current["run_id"]
    assert (
        canonical_manifest["ocr_manifest_sha256"]
        == hashlib.sha256(ocr_manifest_bytes).hexdigest()
    )
    assert (
        canonical_manifest["canonical_content_sha256"]
        == canonical_current["canonical_content_sha256"]
    )
    provenance, _provenance_bytes = _read_canonical_json(
        canonical_run / "provenance.json"
    )
    assert provenance["canonical_run_id"] == canonical_current["run_id"]
    assert provenance["ocr_run_id"] == ocr_current["run_id"]
    assert (
        provenance["ocr_manifest_sha256"]
        == hashlib.sha256(ocr_manifest_bytes).hexdigest()
    )
    assert provenance["source_sha256"] == source_sha256
    canonical_blocks = [
        json.loads(line)
        for line in (canonical_run / "blocks.jsonl").read_bytes().splitlines()
    ]
    assert canonical_blocks

    semantic_current, semantic_run, semantic_manifest, semantic_manifest_bytes = (
        _read_current_run(
            source_root / "semantic",
            current_schema="gezhi.literature_semantic_current.v1",
            manifest_schema="gezhi.literature_semantic_run_manifest.v1",
        )
    )
    assert semantic_manifest["status"] == "succeeded"
    assert semantic_manifest["canonical_run_id"] == canonical_current["run_id"]
    assert (
        semantic_manifest["canonical_manifest_sha256"]
        == hashlib.sha256(canonical_manifest_bytes).hexdigest()
    )
    assert (
        semantic_manifest["canonical_content_sha256"]
        == canonical_current["canonical_content_sha256"]
    )
    assert semantic_manifest["source_sha256"] == source_sha256
    reader_input_records = [
        json.loads(line)
        for line in (semantic_run / "input.jsonl").read_bytes().splitlines()
    ]
    assert reader_input_records[0]["canonical_run_id"] == canonical_current["run_id"]
    assert reader_input_records[0]["source_sha256"] == source_sha256
    assert {item["block_id"] for item in reader_input_records[1:]} == {
        item["block_id"] for item in canonical_blocks
    }

    materialization_root = source_root / "semantic" / "materializations"
    (
        materialization_current,
        materialization_run,
        materialization_manifest,
        _materialization_manifest_bytes,
    ) = _read_current_run(
        materialization_root,
        current_schema="gezhi.candidate_materialization_current.v1",
        manifest_schema="gezhi.candidate_materialization_run_manifest.v1",
    )
    assert materialization_manifest["status"] == "succeeded"
    assert materialization_manifest["reader_run_id"] == semantic_current["run_id"]
    assert (
        materialization_manifest["reader_manifest_sha256"]
        == hashlib.sha256(semantic_manifest_bytes).hexdigest()
    )
    assert (
        materialization_manifest["canonical_content_sha256"]
        == (canonical_current["canonical_content_sha256"])
    )
    assert materialization_manifest["source_sha256"] == source_sha256
    candidate_bytes = (
        materialization_run / "result" / "candidate_knowledge.jsonl"
    ).read_bytes()
    assert candidate_bytes.endswith(b"\n") and candidate_bytes.count(b"\n") == 1
    candidate = json.loads(candidate_bytes)
    assert candidate_bytes == _canonical_json_line(candidate)
    assert candidate["candidate_id"] == candidate_id
    assert candidate["payload"]["work_id"] == work_id
    assert candidate["payload"]["source_id"] == source_id
    assert candidate["payload"]["source_sha256"] == source_sha256
    assert (
        candidate["payload"]["canonical_content_sha256"]
        == canonical_current["canonical_content_sha256"]
    )
    pointer = candidate["payload"]["statement"]["evidence_pointers"][0]
    assert (
        pointer["canonical_content_sha256"]
        == canonical_current["canonical_content_sha256"]
    )
    assert pointer["block_id"] in {item["block_id"] for item in canonical_blocks}
    review_queue, _review_queue_bytes = _read_canonical_json(
        materialization_run / "result" / "review_queue.json"
    )
    assert review_queue["materialization_run_id"] == materialization_current["run_id"]
    assert review_queue["reader_run_id"] == semantic_current["run_id"]
    assert (
        review_queue["reader_manifest_sha256"]
        == hashlib.sha256(semantic_manifest_bytes).hexdigest()
    )
    assert review_queue["candidates"][0]["candidate_id"] == candidate_id

    reviews_root = work_root / "reviews" / candidate_id
    decision, decision_bytes = _read_canonical_json(reviews_root / "1.json")
    assert decision["candidate_id"] == candidate_id
    assert decision["payload_sha256"] == candidate["payload_sha256"]
    assert decision["review_revision"] == 1
    assert decision["review_status"] == "accepted"
    decision_current, _decision_current_bytes = _read_canonical_json(
        reviews_root / "current.json"
    )
    assert (
        decision_current["decision_sha256"]
        == hashlib.sha256(decision_bytes).hexdigest()
    )
    assert decision_current["payload_sha256"] == candidate["payload_sha256"]
    assert decision_current["review_revision"] == 1

    handoff_id = str(reviewed["handoff_id"])
    handoff_root = work_root / "handoffs" / handoff_id
    handoff_manifest, handoff_manifest_bytes = _read_canonical_json(
        handoff_root / "manifest.json"
    )
    handoff_candidates_bytes = (handoff_root / "candidates.jsonl").read_bytes()
    handoff_record = json.loads(handoff_candidates_bytes)
    assert handoff_candidates_bytes == _canonical_json_line(handoff_record)
    assert handoff_manifest["schema_version"] == "gezhi.reviewed_handoff_manifest.v1"
    assert handoff_manifest["handoff_id"] == handoff_id
    assert (
        handoff_manifest["candidates_sha256"]
        == hashlib.sha256(handoff_candidates_bytes).hexdigest()
    )
    assert handoff_manifest["canonical_run_id"] == canonical_current["run_id"]
    assert (
        handoff_manifest["canonical_content_sha256"]
        == canonical_current["canonical_content_sha256"]
    )
    assert handoff_manifest["provenance"] == {
        "canonical_run_id": canonical_current["run_id"],
        "semantic_run_id": semantic_current["run_id"],
    }
    assert handoff_manifest["source_sha256"] == source_sha256
    assert handoff_record["action"] == "accept"
    assert handoff_record["candidate"] == candidate
    assert handoff_record["evidence_snapshots"][0]["pointer"] == pointer

    import_attempt, _import_attempt_bytes = _read_canonical_json(
        reviews_root / "import_attempts" / "1.json"
    )
    import_receipt, _import_receipt_bytes = _read_canonical_json(
        reviews_root / "imports" / "1.json"
    )
    for document in (import_attempt, import_receipt):
        assert document["handoff_id"] == handoff_id
        assert (
            document["manifest_sha256"]
            == hashlib.sha256(handoff_manifest_bytes).hexdigest()
        )
        assert (
            document["candidates_sha256"]
            == hashlib.sha256(handoff_candidates_bytes).hexdigest()
        )
    assert import_receipt["intake_status"] == "active"
    knowledge_import = workspace.knowledge_root / "imports" / handoff_id
    assert (knowledge_import / "manifest.json").read_bytes() == handoff_manifest_bytes
    assert (
        knowledge_import / "candidates.jsonl"
    ).read_bytes() == handoff_candidates_bytes

    registry_path = workspace.knowledge_root / "registry.sqlite3"
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        content = registry.execute(
            "SELECT payload_sha256, work_id, source_id, source_sha256, "
            "canonical_content_sha256, content_handoff_id, "
            "content_manifest_sha256, content_candidates_sha256 "
            "FROM candidate_content WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        assert content == (
            candidate["payload_sha256"],
            work_id,
            source_id,
            source_sha256,
            canonical_current["canonical_content_sha256"],
            handoff_id,
            hashlib.sha256(handoff_manifest_bytes).hexdigest(),
            hashlib.sha256(handoff_candidates_bytes).hexdigest(),
        )
        assert registry.execute(
            "SELECT review_revision, review_status, intake_status, status_handoff_id "
            "FROM candidate_current WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone() == (1, "accepted", "active", handoff_id)

    assert shown["candidate"] == candidate
    assert shown["evidence_snapshots"] == handoff_record["evidence_snapshots"]
    answer_root = workspace.knowledge_root / "answers" / str(asked["answer_id"])
    answer_manifest, _answer_manifest_bytes = _read_canonical_json(
        answer_root / "manifest.json"
    )
    assert answer_manifest["schema_version"] == "gezhi.answer_manifest.v1"
    assert answer_manifest["status"] == "succeeded"
    assert answer_manifest["error"] is None
    _assert_manifest_assets(answer_root, answer_manifest)
    retrieval_view, _retrieval_view_bytes = _read_canonical_json(
        answer_root / "retrieval_view.json"
    )
    assert retrieval_view["items"][0]["candidate"] == candidate
    assert (
        retrieval_view["items"][0]["evidence_snapshots"]
        == handoff_record["evidence_snapshots"]
    )
    answer_output, _answer_output_bytes = _read_canonical_json(
        answer_root / "answer_output.json"
    )
    assert answer_output == asked["answer_output"]
    assert answer_output["answer_units"][0]["candidate_id"] == candidate_id
    question, _question_bytes = _read_canonical_json(answer_root / "question.json")
    assert question["schema_version"] == "gezhi.question.v1"
    answer_markdown = (answer_root / "answer.md").read_bytes()
    assert source_id.encode("ascii") in answer_markdown
    assert answer_output["answer_units"][0]["text"].encode() in answer_markdown


def _assert_governance_terminal(
    workspace: _E2eWorkspaceV1,
    *,
    candidate_id: str,
    result: dict[str, object],
    revision: int,
    action: str,
    review_status: str,
    intake_status: str,
) -> None:
    work_id = str(result["work_id"])
    work_root = workspace.literature_root / "works" / work_id
    reviews_root = work_root / "reviews" / candidate_id
    decision, decision_bytes = _read_canonical_json(reviews_root / f"{revision}.json")
    assert decision["candidate_id"] == candidate_id
    assert decision["payload_sha256"] == result["payload_sha256"]
    assert decision["review_revision"] == revision
    assert decision["review_status"] == review_status
    current, _current_bytes = _read_canonical_json(reviews_root / "current.json")
    assert current["decision_sha256"] == hashlib.sha256(decision_bytes).hexdigest()
    assert current["review_revision"] == revision

    handoff_id = str(result["handoff_id"])
    handoff_root = work_root / "handoffs" / handoff_id
    manifest, manifest_bytes = _read_canonical_json(handoff_root / "manifest.json")
    candidates_bytes = (handoff_root / "candidates.jsonl").read_bytes()
    record = json.loads(candidates_bytes)
    assert candidates_bytes == _canonical_json_line(record)
    assert manifest["handoff_id"] == handoff_id
    assert manifest["candidates_sha256"] == hashlib.sha256(candidates_bytes).hexdigest()
    assert (
        manifest["source_sha256"]
        == hashlib.sha256(workspace.pdf_path.read_bytes()).hexdigest()
    )
    assert record["action"] == action
    assert record["review_receipt"] == {
        "review_revision": revision,
        "review_status": review_status,
        "reviewer_kind": "local_human_cli",
    }
    import_root = workspace.knowledge_root / "imports" / handoff_id
    assert (import_root / "manifest.json").read_bytes() == manifest_bytes
    assert (import_root / "candidates.jsonl").read_bytes() == candidates_bytes
    import_receipt, _receipt_bytes = _read_canonical_json(
        reviews_root / "imports" / f"{revision}.json"
    )
    assert import_receipt["handoff_id"] == handoff_id
    assert (
        import_receipt["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    )
    assert (
        import_receipt["candidates_sha256"]
        == hashlib.sha256(candidates_bytes).hexdigest()
    )
    assert import_receipt["intake_status"] == intake_status

    registry_path = workspace.knowledge_root / "registry.sqlite3"
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute(
            "SELECT review_revision, action, review_status, source_sha256, "
            "canonical_content_sha256, canonical_run_id, semantic_run_id, "
            "manifest_sha256, candidates_sha256 FROM handoff_revisions "
            "WHERE handoff_id = ?",
            (handoff_id,),
        ).fetchone() == (
            revision,
            action,
            review_status,
            manifest["source_sha256"],
            manifest["canonical_content_sha256"],
            manifest["canonical_run_id"],
            manifest["provenance"]["semantic_run_id"],
            hashlib.sha256(manifest_bytes).hexdigest(),
            hashlib.sha256(candidates_bytes).hexdigest(),
        )
        assert registry.execute(
            "SELECT review_revision, review_status, intake_status, status_handoff_id "
            "FROM candidate_current WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone() == (revision, review_status, intake_status, handoff_id)


def _assert_zero_match_answer_terminal(
    workspace: _E2eWorkspaceV1,
    result: dict[str, object],
) -> None:
    answer_root = workspace.knowledge_root / "answers" / str(result["answer_id"])
    manifest, _manifest_bytes = _read_canonical_json(answer_root / "manifest.json")
    assert manifest["schema_version"] == "gezhi.answer_manifest.v1"
    assert manifest["status"] == "succeeded"
    assert manifest["error"] is None
    assert manifest["attempts"] == []
    _assert_manifest_assets(answer_root, manifest)
    retrieval_view, _view_bytes = _read_canonical_json(
        answer_root / "retrieval_view.json"
    )
    assert retrieval_view == {
        "answer_kind": "candidate_backed",
        "candidate_count": 0,
        "items": [],
        "schema_version": "gezhi.retrieval_view.v1",
    }
    answer_output, _output_bytes = _read_canonical_json(
        answer_root / "answer_output.json"
    )
    assert answer_output == result["answer_output"]
    assert not (answer_root / "prompt.txt").exists()
    assert not (answer_root / "schema.json").exists()
    assert not (answer_root / "attempts").exists()


@pytest.mark.parametrize("launcher_index", (0, 1), ids=("console", "module"))
def test_scanned_pdf_reaches_a_citable_answer_and_governance_branches(
    deterministic_e2e_workspace: _E2eWorkspaceV1,
    launcher_index: int,
) -> None:
    workspace = deterministic_e2e_workspace
    added = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(workspace.literature_root),
                "literature",
                "add",
                str(workspace.pdf_path),
                "--json",
            )
        )[launcher_index]
    )
    assert added.returncode == 0
    added_envelope = _json_result(added)
    assert added_envelope["command"] == "literature.add"
    assert added_envelope["outcome"] == "succeeded"
    added_result = added_envelope["result"]
    assert isinstance(added_result, dict)

    resumed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(workspace.literature_root),
                "literature",
                "resume",
                str(added_result["work_id"]),
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(workspace.site_root, TEST_ROOT, SOURCE_ROOT),
        environment_updates={
            "CODEX_HOME": str(workspace.runtime_root / "codex-home"),
            "T25_CODEX_DOUBLE_EXE": str(CODEX_DOUBLE),
            "T25_DOUBLE_MODE": "literature",
            "T25_OCR_DOUBLE_EXE": str(OCR_DOUBLE),
            "TEMP": str(workspace.runtime_root / "temp"),
            "TMP": str(workspace.runtime_root / "temp"),
        },
        timeout=45.0,
    )

    assert resumed.returncode == 2
    resumed_envelope = _json_result(resumed)
    assert resumed_envelope["command"] == "literature.resume"
    assert resumed_envelope["outcome"] == "blocked"
    resumed_result = resumed_envelope["result"]
    assert isinstance(resumed_result, dict)
    assert resumed_result["advanced_stages"] == ["ocr", "canonicalize", "read"]
    assert resumed_result["start_stage"] == "ocr"
    assert resumed_result["stop_stage"] == "review"
    assert len(resumed_result["pending_candidate_ids"]) == 1

    source_root = (
        workspace.literature_root
        / "works"
        / str(added_result["work_id"])
        / "sources"
        / str(added_result["source_id"])
    )
    ocr_current = json.loads((source_root / "ocr" / "current.json").read_bytes())
    ocr_run = source_root / "ocr" / "runs" / str(ocr_current["run_id"])
    ocr_manifest_bytes = (ocr_run / "manifest.json").read_bytes()
    assert (
        ocr_current["manifest_sha256"] == hashlib.sha256(ocr_manifest_bytes).hexdigest()
    )
    assert json.loads((ocr_run / "receipt.json").read_bytes())["method"] == (
        "mineru_ocr"
    )
    assert (source_root / "canonical" / "current.json").is_file()
    assert (source_root / "semantic" / "current.json").is_file()

    candidate_id = str(resumed_result["pending_candidate_ids"][0])
    reviewed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(workspace.literature_root),
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "literature",
                "review",
                candidate_id,
                "--accept",
                "--json",
            )
        )[launcher_index]
    )
    assert reviewed.returncode == 0
    reviewed_envelope = _json_result(reviewed)
    assert reviewed_envelope["command"] == "literature.review"
    assert reviewed_envelope["outcome"] == "succeeded"
    reviewed_result = reviewed_envelope["result"]
    assert isinstance(reviewed_result, dict)
    assert reviewed_result["candidate_id"] == candidate_id
    assert reviewed_result["review_status"] == "accepted"
    assert reviewed_result["handoff_action"] == "accept"
    assert reviewed_result["import_status"] == "applied"
    assert reviewed_result["intake_status"] == "active"

    searched = run_launcher(
        launcher_commands(
            (
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "knowledge",
                "search",
                "Deterministic OCR evidence",
                "--json",
            )
        )[launcher_index]
    )
    assert searched.returncode == 0
    searched_envelope = _json_result(searched)
    assert searched_envelope["command"] == "knowledge.search"
    assert searched_envelope["outcome"] == "succeeded"
    searched_result = searched_envelope["result"]
    assert isinstance(searched_result, dict)
    assert searched_result["candidate_count"] == 1
    search_candidate = searched_result["items"][0]["candidate"]
    assert search_candidate["candidate_id"] == candidate_id

    shown = run_launcher(
        launcher_commands(
            (
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "knowledge",
                "show",
                candidate_id,
                "--json",
            )
        )[launcher_index]
    )
    assert shown.returncode == 0
    shown_envelope = _json_result(shown)
    assert shown_envelope["command"] == "knowledge.show"
    assert shown_envelope["outcome"] == "succeeded"
    shown_result = shown_envelope["result"]
    assert isinstance(shown_result, dict)
    assert shown_result["candidate"]["candidate_id"] == candidate_id
    canonical_current = json.loads(
        (source_root / "canonical" / "current.json").read_bytes()
    )
    candidate_payload = shown_result["candidate"]["payload"]
    assert candidate_payload["work_id"] == added_result["work_id"]
    assert candidate_payload["source_id"] == added_result["source_id"]
    assert candidate_payload["source_sha256"] == added_result["source_sha256"]
    assert (
        candidate_payload["canonical_content_sha256"]
        == (canonical_current["canonical_content_sha256"])
    )
    evidence = shown_result["evidence_snapshots"]
    assert len(evidence) == 1
    assert (
        evidence[0]["pointer"]["canonical_content_sha256"]
        == (canonical_current["canonical_content_sha256"])
    )

    asked = run_launcher(
        launcher_commands(
            (
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "knowledge",
                "ask",
                "Which evidence supports the complete Gezhi workflow?",
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(workspace.site_root, TEST_ROOT, SOURCE_ROOT),
        environment_updates={
            "CODEX_HOME": str(workspace.runtime_root / "codex-home"),
            "T25_CODEX_DOUBLE_EXE": str(CODEX_DOUBLE),
            "T25_DOUBLE_MODE": "answerer",
            "TEMP": str(workspace.runtime_root / "temp"),
            "TMP": str(workspace.runtime_root / "temp"),
        },
        timeout=45.0,
    )
    assert asked.returncode == 0
    asked_envelope = _json_result(asked)
    assert asked_envelope["command"] == "knowledge.ask"
    assert asked_envelope["outcome"] == "succeeded"
    asked_result = asked_envelope["result"]
    assert isinstance(asked_result, dict)
    assert asked_result["answer_output"] == {
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
    answer_root = workspace.knowledge_root / "answers" / str(asked_result["answer_id"])
    answer_manifest = json.loads((answer_root / "manifest.json").read_bytes())
    assert answer_manifest["status"] == "succeeded"
    retrieval_view = json.loads((answer_root / "retrieval_view.json").read_bytes())
    assert retrieval_view["items"][0]["candidate"]["candidate_id"] == candidate_id
    assert (
        retrieval_view["items"][0]["candidate"]["payload"]["source_sha256"]
        == hashlib.sha256(workspace.pdf_path.read_bytes()).hexdigest()
    )
    assert (
        retrieval_view["items"][0]["evidence_snapshots"][0]["pointer"]
        == (evidence[0]["pointer"])
    )
    _assert_full_evidence_chain(
        workspace,
        added=added_result,
        reviewed=reviewed_result,
        shown=shown_result,
        asked=asked_result,
    )

    human_ask = run_launcher(
        launcher_commands(
            (
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "knowledge",
                "ask",
                "Which evidence supports the complete Gezhi workflow?",
            )
        )[launcher_index],
        pythonpath_roots=(workspace.site_root, TEST_ROOT, SOURCE_ROOT),
        environment_updates={
            "CODEX_HOME": str(workspace.runtime_root / "codex-home"),
            "T25_CODEX_DOUBLE_EXE": str(CODEX_DOUBLE),
            "T25_DOUBLE_MODE": "answerer",
            "TEMP": str(workspace.runtime_root / "temp"),
            "TMP": str(workspace.runtime_root / "temp"),
        },
        timeout=45.0,
    )
    _assert_exact_answer_human(workspace, human_ask)

    status_arguments = (
        "--literature-data-root",
        str(workspace.literature_root),
        "--knowledge-data-root",
        str(workspace.knowledge_root),
        "status",
        str(added_result["work_id"]),
    )
    status_json = run_launcher(
        launcher_commands((*status_arguments, "--json"))[launcher_index]
    )
    assert status_json.returncode == 0
    status_envelope = _json_result(status_json)
    assert status_envelope["command"] == "status"
    assert status_envelope["outcome"] == "succeeded"
    status_result = status_envelope["result"]
    assert isinstance(status_result, dict)
    assert status_result["schema_version"] == "gezhi.status_result.v1"
    assert status_result["scope"] == "work"
    assert status_result["work_id"] == added_result["work_id"]
    assert status_result == {
        "knowledge": {
            "availability": "ready",
            "candidate_counts": {"active": 1, "withdrawn": 0},
            "related_answer_status_counts": [{"count": 2, "status": "succeeded"}],
        },
        "literature": {
            "availability": "ready",
            "handoff_status": "available",
            "review_counts": {
                "accepted": 1,
                "deferred": 0,
                "pending": 0,
                "rejected": 0,
            },
            "stages": [
                {"stage": stage, "status": "succeeded"}
                for stage in (
                    "ingest",
                    "ocr",
                    "canonicalize",
                    "read",
                    "review",
                    "handoff",
                    "knowledge_import",
                )
            ],
        },
        "next_action": "none",
        "recovery": {
            "inconsistent_count": 0,
            "orphaned_count": 0,
            "quarantined_count": 0,
            "staging_count": 0,
        },
        "schema_version": "gezhi.status_result.v1",
        "scope": "work",
        "status": "succeeded",
        "work_id": added_result["work_id"],
    }

    doctor_arguments = (
        "--literature-data-root",
        str(workspace.literature_root),
        "--knowledge-data-root",
        str(workspace.knowledge_root),
        "doctor",
    )
    doctor_environment = {"T25_DOUBLE_MODE": "doctor"}
    doctor_before = (
        _tree_snapshot(workspace.literature_root),
        _tree_snapshot(workspace.knowledge_root),
    )
    doctor_json = run_launcher(
        launcher_commands((*doctor_arguments, "--json"))[launcher_index],
        pythonpath_roots=(workspace.site_root, TEST_ROOT, SOURCE_ROOT),
        environment_updates=doctor_environment,
        timeout=45.0,
    )
    doctor_envelope = _json_result(doctor_json)
    assert doctor_envelope["command"] == "doctor"
    assert doctor_envelope["outcome"] == "succeeded"
    doctor_result = doctor_envelope["result"]
    assert isinstance(doctor_result, dict)
    doctor_human = run_launcher(
        launcher_commands(doctor_arguments)[launcher_index],
        pythonpath_roots=(workspace.site_root, TEST_ROOT, SOURCE_ROOT),
        environment_updates=doctor_environment,
        timeout=45.0,
    )
    assert (
        doctor_human.returncode,
        doctor_human.stdout,
        doctor_human.stderr,
    ) == (0, expected_human_bytes_v1(doctor_envelope), b"")
    assert doctor_before == (
        _tree_snapshot(workspace.literature_root),
        _tree_snapshot(workspace.knowledge_root),
    )

    withdrawn = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(workspace.literature_root),
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "literature",
                "review",
                candidate_id,
                "--reject",
                "--json",
            )
        )[launcher_index]
    )
    assert withdrawn.returncode == 0
    withdrawn_envelope = _json_result(withdrawn)
    assert withdrawn_envelope["outcome"] == "succeeded"
    withdrawn_result = withdrawn_envelope["result"]
    assert isinstance(withdrawn_result, dict)
    assert withdrawn_result["handoff_action"] == "withdraw"
    assert withdrawn_result["review_status"] == "rejected"
    assert withdrawn_result["intake_status"] == "withdrawn"
    _assert_governance_terminal(
        workspace,
        candidate_id=candidate_id,
        result=withdrawn_result,
        revision=2,
        action="withdraw",
        review_status="rejected",
        intake_status="withdrawn",
    )

    empty_search = run_launcher(
        launcher_commands(
            (
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "knowledge",
                "search",
                "Deterministic OCR evidence",
                "--json",
            )
        )[launcher_index]
    )
    assert empty_search.returncode == 0
    empty_search_envelope = _json_result(empty_search)
    assert empty_search_envelope["result"]["candidate_count"] == 0

    withdrawn_show = run_launcher(
        launcher_commands(
            (
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "knowledge",
                "show",
                candidate_id,
                "--json",
            )
        )[launcher_index]
    )
    assert withdrawn_show.returncode == 0
    withdrawn_show_envelope = _json_result(withdrawn_show)
    assert withdrawn_show_envelope["result"]["governance"] == {
        "intake_status": "withdrawn",
        "promotion_status": "not_promoted",
        "review_status": "rejected",
    }

    guard_marker = workspace.runtime_root / "codex-launch-guard.marker"
    zero_match_ask = run_launcher(
        launcher_commands(
            (
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "knowledge",
                "ask",
                "Which evidence supports the complete Gezhi workflow?",
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(workspace.site_root, TEST_ROOT, SOURCE_ROOT),
        environment_updates={
            "T25_CODEX_GUARD_MARKER": str(guard_marker),
            "T25_DOUBLE_MODE": "forbid-codex",
        },
    )
    assert zero_match_ask.returncode == 0
    zero_match_envelope = _json_result(zero_match_ask)
    assert zero_match_envelope["result"]["answer_output"] == {
        "answer_status": "insufficient_evidence",
        "answer_units": [],
        "insufficiency_reason": "no_matching_candidates",
        "qualification_units": [],
        "schema_version": "gezhi.answer_output.v1",
    }
    zero_match_result = zero_match_envelope["result"]
    assert isinstance(zero_match_result, dict)
    _assert_zero_match_answer_terminal(workspace, zero_match_result)
    assert guard_marker.read_bytes() == b"armed\n"

    reaccepted = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(workspace.literature_root),
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "literature",
                "review",
                candidate_id,
                "--accept",
                "--json",
            )
        )[launcher_index]
    )
    assert reaccepted.returncode == 0
    reaccepted_envelope = _json_result(reaccepted)
    reaccepted_result = reaccepted_envelope["result"]
    assert isinstance(reaccepted_result, dict)
    assert reaccepted_result["review_revision"] == 3
    assert reaccepted_result["intake_status"] == "active"
    _assert_governance_terminal(
        workspace,
        candidate_id=candidate_id,
        result=reaccepted_result,
        revision=3,
        action="accept",
        review_status="accepted",
        intake_status="active",
    )

    restored_search = run_launcher(
        launcher_commands(
            (
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "knowledge",
                "search",
                "Deterministic OCR evidence",
                "--json",
            )
        )[launcher_index]
    )
    assert restored_search.returncode == 0
    restored_search_envelope = _json_result(restored_search)
    assert restored_search_envelope["result"]["candidate_count"] == 1

    stable_parity_cases = (
        (
            "literature.add",
            (
                "--literature-data-root",
                str(workspace.literature_root),
                "literature",
                "add",
                str(workspace.pdf_path),
            ),
        ),
        (
            "literature.resume",
            (
                "--literature-data-root",
                str(workspace.literature_root),
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "literature",
                "resume",
                str(added_result["work_id"]),
            ),
        ),
        (
            "literature.review",
            (
                "--literature-data-root",
                str(workspace.literature_root),
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "literature",
                "review",
                candidate_id,
                "--accept",
            ),
        ),
        (
            "knowledge.search",
            (
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "knowledge",
                "search",
                "Deterministic OCR evidence",
            ),
        ),
        (
            "knowledge.show",
            (
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "knowledge",
                "show",
                candidate_id,
            ),
        ),
        (
            "status",
            (
                "--literature-data-root",
                str(workspace.literature_root),
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "status",
                str(added_result["work_id"]),
            ),
        ),
        (
            "doctor",
            (
                "--literature-data-root",
                str(workspace.literature_root),
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "doctor",
            ),
        ),
        (
            "knowledge.ask",
            (
                "--knowledge-data-root",
                str(workspace.knowledge_root),
                "knowledge",
                "ask",
                " \t ",
            ),
        ),
    )
    parity_before = (
        _tree_snapshot(workspace.literature_root),
        _tree_snapshot(workspace.knowledge_root),
    )
    for expected_command, arguments in stable_parity_cases:
        _assert_exact_launcher_parity(
            arguments,
            expected_command=expected_command,
            environment_updates=(
                doctor_environment if expected_command == "doctor" else None
            ),
            pythonpath_roots=(
                (workspace.site_root, TEST_ROOT, SOURCE_ROOT)
                if expected_command == "doctor"
                else (SOURCE_ROOT,)
            ),
        )
    assert parity_before == (
        _tree_snapshot(workspace.literature_root),
        _tree_snapshot(workspace.knowledge_root),
    )
    _assert_dynamic_answer_launcher_parity(
        workspace,
        (
            "--knowledge-data-root",
            str(workspace.knowledge_root),
            "knowledge",
            "ask",
            "Which evidence supports the complete Gezhi workflow?",
        ),
        environment_updates={
            "CODEX_HOME": str(workspace.runtime_root / "codex-home"),
            "T25_CODEX_DOUBLE_EXE": str(CODEX_DOUBLE),
            "T25_DOUBLE_MODE": "answerer",
            "TEMP": str(workspace.runtime_root / "temp"),
            "TMP": str(workspace.runtime_root / "temp"),
        },
    )


def test_ocr_failed_terminal_recovers_with_the_other_launcher(
    deterministic_e2e_workspace: _E2eWorkspaceV1,
) -> None:
    workspace = deterministic_e2e_workspace
    added = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(workspace.literature_root),
                "literature",
                "add",
                str(workspace.pdf_path),
                "--json",
            )
        )[0]
    )
    assert added.returncode == 0
    added_result = _json_result(added)["result"]
    assert isinstance(added_result, dict)
    work_id = str(added_result["work_id"])
    marker = workspace.runtime_root / "ocr-double.marker"
    common_environment = {
        "CODEX_HOME": str(workspace.runtime_root / "codex-home"),
        "T25_CODEX_DOUBLE_EXE": str(CODEX_DOUBLE),
        "T25_DOUBLE_MODE": "literature",
        "T25_OCR_DOUBLE_MARKER": str(marker),
        "TEMP": str(workspace.runtime_root / "temp"),
        "TMP": str(workspace.runtime_root / "temp"),
    }
    resume_arguments = (
        "--literature-data-root",
        str(workspace.literature_root),
        "literature",
        "resume",
        work_id,
        "--json",
    )

    failed = run_launcher(
        launcher_commands(resume_arguments)[0],
        pythonpath_roots=(workspace.site_root, TEST_ROOT, SOURCE_ROOT),
        environment_updates={
            **common_environment,
            "T25_OCR_DOUBLE_EXE": str(OCR_DOUBLE),
            "T25_OCR_DOUBLE_SCENARIO": "invalid-output",
        },
    )
    assert failed.returncode == 1
    failed_envelope = _json_result(failed)
    assert failed_envelope["outcome"] == "failed"
    failed_result = failed_envelope["result"]
    assert isinstance(failed_result, dict)
    assert failed_result["advanced_stages"] == []
    assert failed_result["start_stage"] == "ocr"
    assert failed_result["stop_stage"] == "ocr"
    assert marker.read_bytes() == b"invoked\n"

    source_root = (
        workspace.literature_root
        / "works"
        / work_id
        / "sources"
        / str(added_result["source_id"])
    )
    ocr_root = source_root / "ocr"
    assert not (ocr_root / "current.json").exists()
    failed_runs = [
        path for path in (ocr_root / "runs").iterdir() if path.name != ".staging"
    ]
    assert len(failed_runs) == 1
    failed_receipt = json.loads((failed_runs[0] / "receipt.json").read_bytes())
    assert failed_receipt["status"] == "failed"
    assert failed_receipt["reason"] == "ocr_failed"
    failed_manifest, _failed_manifest_bytes = _read_canonical_json(
        failed_runs[0] / "manifest.json"
    )
    assert failed_manifest["status"] == "failed"
    assert failed_manifest["run_id"] == failed_runs[0].name
    _assert_manifest_assets(failed_runs[0], failed_manifest)
    failed_input, _failed_input_bytes = _read_canonical_json(
        failed_runs[0] / "input.json"
    )
    assert failed_input["work_id"] == work_id
    assert failed_input["source_id"] == added_result["source_id"]
    assert failed_input["source_sha256"] == added_result["source_sha256"]
    assert not (source_root / "canonical").exists()
    assert not (source_root / "semantic").exists()

    recovered = run_launcher(
        launcher_commands(resume_arguments)[1],
        pythonpath_roots=(workspace.site_root, TEST_ROOT, SOURCE_ROOT),
        environment_updates={
            **common_environment,
            "T25_OCR_DOUBLE_EXE": str(OCR_DOUBLE),
        },
        timeout=45.0,
    )
    assert recovered.returncode == 2
    recovered_envelope = _json_result(recovered)
    assert recovered_envelope["outcome"] == "blocked"
    recovered_result = recovered_envelope["result"]
    assert isinstance(recovered_result, dict)
    assert recovered_result["advanced_stages"] == ["ocr", "canonicalize", "read"]
    assert recovered_result["start_stage"] == "ocr"
    assert recovered_result["stop_stage"] == "review"
    assert len(recovered_result["pending_candidate_ids"]) == 1
    assert marker.read_bytes() == b"invoked\ninvoked\n"
    assert failed_runs[0].is_dir()
    assert json.loads((failed_runs[0] / "receipt.json").read_bytes()) == failed_receipt
    current = json.loads((ocr_root / "current.json").read_bytes())
    assert current["run_id"] != failed_runs[0].name
    assert current["work_id"] == work_id
    assert current["source_id"] == added_result["source_id"]
    assert current["source_sha256"] == added_result["source_sha256"]
    assert (
        json.loads(
            (ocr_root / "runs" / str(current["run_id"]) / "receipt.json").read_bytes()
        )["status"]
        == "succeeded"
    )


def _run_mineru_coordinate_scenario_v1(
    deterministic_e2e_workspace: _E2eWorkspaceV1,
    launcher_index: int,
    scenario: str,
) -> tuple[int, dict[str, object]]:
    workspace = deterministic_e2e_workspace
    added = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(workspace.literature_root),
                "literature",
                "add",
                str(workspace.pdf_path),
                "--json",
            )
        )[launcher_index]
    )
    assert added.returncode == 0
    added_result = _json_result(added)["result"]
    assert isinstance(added_result, dict)

    resumed = run_launcher(
        launcher_commands(
            (
                "--literature-data-root",
                str(workspace.literature_root),
                "literature",
                "resume",
                str(added_result["work_id"]),
                "--json",
            )
        )[launcher_index],
        pythonpath_roots=(workspace.site_root, TEST_ROOT, SOURCE_ROOT),
        environment_updates={
            "CODEX_HOME": str(workspace.runtime_root / "codex-home"),
            "T25_CODEX_DOUBLE_EXE": str(CODEX_DOUBLE),
            "T25_DOUBLE_MODE": "literature",
            "T25_OCR_DOUBLE_EXE": str(OCR_DOUBLE),
            "T25_OCR_DOUBLE_SCENARIO": scenario,
            "TEMP": str(workspace.runtime_root / "temp"),
            "TMP": str(workspace.runtime_root / "temp"),
        },
        timeout=45.0,
    )

    return resumed.returncode, _json_result(resumed)


@pytest.mark.parametrize("launcher_index", (0, 1), ids=("console", "module"))
def test_real_mineru_coordinate_rounding_is_accepted_through_public_cli(
    deterministic_e2e_workspace: _E2eWorkspaceV1,
    launcher_index: int,
) -> None:
    returncode, envelope = _run_mineru_coordinate_scenario_v1(
        deterministic_e2e_workspace,
        launcher_index,
        "origin-coordinate-rounding",
    )

    assert returncode == 2
    assert envelope["outcome"] == "blocked"
    result = envelope["result"]
    assert isinstance(result, dict)
    assert result["advanced_stages"] == ["ocr", "canonicalize", "read"]
    assert result["start_stage"] == "ocr"
    assert result["stop_stage"] == "review"


@pytest.mark.parametrize("launcher_index", (0, 1), ids=("console", "module"))
def test_mineru_coordinate_change_outside_four_decimals_is_rejected(
    deterministic_e2e_workspace: _E2eWorkspaceV1,
    launcher_index: int,
) -> None:
    returncode, envelope = _run_mineru_coordinate_scenario_v1(
        deterministic_e2e_workspace,
        launcher_index,
        "origin-coordinate-outside-rounding",
    )

    assert returncode == 1
    assert envelope["outcome"] == "failed"
    result = envelope["result"]
    assert isinstance(result, dict)
    assert result["advanced_stages"] == []
    assert result["start_stage"] == "ocr"
    assert result["stop_stage"] == "ocr"
