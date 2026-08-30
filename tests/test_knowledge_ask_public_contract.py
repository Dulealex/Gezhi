from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest
from launcher_support import (
    PYTHON_EXE,
    REPOSITORY_ROOT,
    SOURCE_ROOT,
    run_both_launchers,
    subprocess_environment,
)
from support.reviewed_handoff_witness_v1 import (
    ACCEPT_CANDIDATES_V1,
    ACCEPT_MANIFEST_V1,
    WITHDRAW_CANDIDATES_V1,
    WITHDRAW_MANIFEST_V1,
)

_ANSWER_ID = re.compile(
    r"^ans_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_UTC_MILLISECONDS = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:"
    r"[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
)
_TERMINAL_ASSETS = {
    "answer.md": ("media_type", "text/markdown; charset=utf-8"),
    "answer_output.json": ("schema_id", "gezhi.answer_output.v1"),
    "effective_config.json": (
        "schema_id",
        "gezhi.knowledge_answerer_effective_config.v1",
    ),
    "question.json": ("schema_id", "gezhi.question.v1"),
    "retrieval_audit.json": ("schema_id", "gezhi.retrieval_audit.v1"),
    "retrieval_query.json": ("schema_id", "gezhi.retrieval_query.v1"),
    "retrieval_view.json": ("schema_id", "gezhi.retrieval_view.v1"),
}


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


def _blocked_json_line(reason: str) -> bytes:
    return _canonical_json_line(
        {
            "command": "knowledge.ask",
            "diagnostics": [
                {
                    "code": f"knowledge.ask.{reason}.v1",
                    "context": {},
                }
            ],
            "outcome": "blocked",
            "result": None,
            "schema_version": "gezhi.cli_result.v1",
        }
    )


@pytest.fixture
def empty_knowledge_ask_root() -> Iterator[Path]:
    container = Path(r"E:\Gezhi\data")
    container.mkdir(parents=True, exist_ok=True)
    base = container / ("t20-" + uuid.uuid4().hex[:12])
    knowledge_root = base / "knowledge"
    knowledge_root.mkdir(parents=True)
    try:
        yield knowledge_root
    finally:
        resolved = base.resolve(strict=True)
        assert resolved.parent == container.resolve(strict=True)
        assert resolved.name.startswith("t20-")
        shutil.rmtree(resolved)


@pytest.fixture
def active_knowledge_ask_root(empty_knowledge_ask_root: Path) -> Path:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_ask_root))
    assert intake.apply(
        ReviewedHandoffBytesV1(
            manifest_bytes=ACCEPT_MANIFEST_V1,
            candidates_bytes=ACCEPT_CANDIDATES_V1,
        )
    ) == IntakeAppliedV1("active", "applied")
    return empty_knowledge_ask_root


@pytest.fixture
def zero_active_knowledge_ask_root(active_knowledge_ask_root: Path) -> Path:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    intake = KnowledgeIntakeAdapterV1(str(active_knowledge_ask_root))
    assert intake.apply(
        ReviewedHandoffBytesV1(
            manifest_bytes=WITHDRAW_MANIFEST_V1,
            candidates_bytes=WITHDRAW_CANDIDATES_V1,
        )
    ) == IntakeAppliedV1("withdrawn", "applied")
    return active_knowledge_ask_root


@pytest.fixture
def empty_registry_knowledge_ask_root(empty_knowledge_ask_root: Path) -> Path:
    from gezhi._knowledge_intake import (
        _APPLICATION_ID,
        _SCHEMA_STATEMENTS,
        _SCHEMA_VERSION,
        _USER_VERSION,
    )
    from gezhi._knowledge_registry import SEARCH_PROJECTION_SCHEMA_VERSION

    registry_path = empty_knowledge_ask_root / "registry.sqlite3"
    with closing(sqlite3.connect(registry_path, isolation_level=None)) as registry:
        registry.execute("PRAGMA foreign_keys = ON")
        registry.execute("BEGIN IMMEDIATE")
        for statement in _SCHEMA_STATEMENTS:
            registry.execute(statement)
        registry.execute(
            "INSERT INTO registry_meta(singleton, schema_version, generation) "
            "VALUES (1, ?, 0)",
            (_SCHEMA_VERSION,),
        )
        registry.execute(
            "INSERT INTO registry_search_meta("
            "singleton, schema_version, registry_generation"
            ") VALUES (1, ?, 0)",
            (SEARCH_PROJECTION_SCHEMA_VERSION,),
        )
        registry.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        registry.execute(f"PRAGMA user_version = {_USER_VERSION}")
        registry.commit()
    return empty_knowledge_ask_root


def _install_codex_launch_guard(site_root: Path) -> Path:
    marker = site_root / "codex-launched.marker"
    site_root.mkdir()
    (site_root / "sitecustomize.py").write_text(
        "import ntpath, os, subprocess\n"
        "_gezhi_real_popen = subprocess.Popen\n"
        "def _gezhi_guarded_popen(command, *args, **kwargs):\n"
        "    executable = command[0] if isinstance(command, (list, tuple)) else command\n"
        "    if ntpath.basename(os.fspath(executable)).casefold() == 'codex.exe':\n"
        "        with open(os.environ['T20_CODEX_LAUNCH_MARKER'], 'xb') as target:\n"
        "            target.write(b'called\\n')\n"
        "        raise RuntimeError('Codex executable must not be called')\n"
        "    return _gezhi_real_popen(command, *args, **kwargs)\n"
        "subprocess.Popen = _gezhi_guarded_popen\n",
        encoding="utf-8",
    )
    return marker


def _assert_zero_candidate_terminal_answer(
    knowledge_root: Path,
    answer_id: str,
    *,
    question: str,
    answer_output: dict[str, object],
) -> None:
    committed = knowledge_root / "answers" / answer_id
    assert committed.is_dir()
    assert {entry.name for entry in committed.iterdir()} == {
        *_TERMINAL_ASSETS,
        "manifest.json",
    }
    assert not (knowledge_root / "answers" / "current.json").exists()
    assert list((knowledge_root / "answers" / ".staging").iterdir()) == []

    manifest_bytes = (committed / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    assert manifest_bytes == _canonical_json_line(manifest)
    assert set(manifest) == {
        "answer_id",
        "assets",
        "attempts",
        "elapsed_ms",
        "error",
        "finished_at",
        "provenance",
        "schema_version",
        "started_at",
        "status",
        "usage_totals",
    }
    assert manifest["schema_version"] == "gezhi.answer_manifest.v1"
    assert manifest["answer_id"] == answer_id
    assert manifest["status"] == "succeeded"
    assert manifest["error"] is None
    assert manifest["attempts"] == []
    assert manifest["usage_totals"] == {
        "cached_input_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    assert type(manifest["elapsed_ms"]) is int and manifest["elapsed_ms"] >= 0
    for timestamp_key in ("started_at", "finished_at"):
        timestamp = manifest[timestamp_key]
        assert type(timestamp) is str
        assert _UTC_MILLISECONDS.fullmatch(timestamp) is not None
        datetime.fromisoformat(timestamp)
    assert manifest["provenance"] == {
        "codex_cli_version": "0.146.0",
        "git": manifest["provenance"]["git"],
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "role_version": "knowledge_answerer_v1",
    }
    git = manifest["provenance"]["git"]
    assert set(git) == {"revision", "state"}
    assert git["state"] in {"clean", "dirty", "unborn"}
    if git["state"] == "unborn":
        assert git["revision"] is None
    else:
        assert re.fullmatch(r"[0-9a-f]{40}", git["revision"]) is not None

    assets = manifest["assets"]
    assert [item["path"] for item in assets] == sorted(_TERMINAL_ASSETS)
    for item in assets:
        path = item["path"]
        payload = (committed / path).read_bytes()
        identity_key, identity_value = _TERMINAL_ASSETS[path]
        assert set(item) == {"byte_length", identity_key, "path", "sha256"}
        assert item["byte_length"] == len(payload)
        assert item["sha256"] == hashlib.sha256(payload).hexdigest()
        assert item[identity_key] == identity_value

    assert (committed / "effective_config.json").read_bytes() == _canonical_json_line(
        {
            "attempt_timeout_ms": 1_800_000,
            "attempt_window_limit_ms": 5_700_000,
            "retry_backoff_schedule_ms": [10_000, 30_000],
            "schema_version": "gezhi.knowledge_answerer_effective_config.v1",
        }
    )
    question_bytes = _canonical_json_line(
        {"question": question, "schema_version": "gezhi.question.v1"}
    )
    assert (committed / "question.json").read_bytes() == question_bytes
    assert (committed / "answer_output.json").read_bytes() == _canonical_json_line(
        answer_output
    )
    retrieval_view_bytes = _canonical_json_line(
        {
            "answer_kind": "candidate_backed",
            "candidate_count": 0,
            "items": [],
            "schema_version": "gezhi.retrieval_view.v1",
        }
    )
    assert (committed / "retrieval_view.json").read_bytes() == retrieval_view_bytes
    retrieval_query_bytes = (committed / "retrieval_query.json").read_bytes()
    retrieval_audit = json.loads((committed / "retrieval_audit.json").read_bytes())
    assert retrieval_audit["final_selection"] == []
    assert retrieval_audit["branch_results"] == {"trigram": [], "unicode61": []}
    assert (
        retrieval_audit["question_asset_sha256"]
        == hashlib.sha256(question_bytes).hexdigest()
    )
    assert (
        retrieval_audit["retrieval_query_asset_sha256"]
        == hashlib.sha256(retrieval_query_bytes).hexdigest()
    )
    assert retrieval_audit["retrieval_view_measurement"] == {
        "byte_length": len(retrieval_view_bytes),
        "limit_bytes": 262_144,
        "sha256": hashlib.sha256(retrieval_view_bytes).hexdigest(),
        "status": "within_limit",
    }


def test_ask_rejects_an_empty_question_before_root_io(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing-knowledge-root"
    expected = _blocked_json_line("invalid_question")

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(missing_root),
            "knowledge",
            "ask",
            "   ",
            "--json",
        )
    )

    for result in results:
        assert result.returncode == 2
        assert result.stdout == expected
        assert result.stderr == b""
    assert not missing_root.exists()


@pytest.mark.parametrize(
    ("question", "reason"),
    [
        ("+#._/-", "invalid_question"),
        ("文", "invalid_question"),
        ("valid\u000bquestion", "invalid_question"),
        ("a" * 2_001, "question_too_large"),
        ("界" * 2_731, "question_too_large"),
        (
            " ".join(f"atom{index:03d}" for index in range(129)),
            "question_too_complex",
        ),
    ],
)
def test_ask_enforces_the_question_barrier_before_root_io(
    tmp_path: Path,
    question: str,
    reason: str,
) -> None:
    missing_root = tmp_path / "missing-knowledge-root"

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(missing_root),
            "knowledge",
            "ask",
            question,
            "--json",
        )
    )

    for result in results:
        assert result.returncode == 2
        assert result.stdout == _blocked_json_line(reason)
        assert result.stderr == b""
    assert not missing_root.exists()


def test_ask_renders_the_exact_human_receipt_for_an_empty_question(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing-knowledge-root"
    expected = (
        "Knowledge ask：已阻塞\n"
        "原因：问题为空、语义不足或包含不支持的控制字符\n"
        "下一步：输入一个单轮、自包含且可读的问题后重试\n"
    ).encode()

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(missing_root),
            "knowledge",
            "ask",
            "   ",
        )
    )

    for result in results:
        assert result.returncode == 2
        assert result.stdout == expected
        assert result.stderr == b""
    assert not missing_root.exists()


def test_ask_stops_at_invalid_configuration_before_root_io(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing-knowledge-root"

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(missing_root),
            "knowledge",
            "ask",
            "Which evidence supports this conclusion?",
            "--json",
        ),
        environment_updates={"GEZHI_UNKNOWN_SETTING": "rejected"},
    )

    for result in results:
        assert result.returncode == 2
        assert result.stdout == _blocked_json_line("configuration_invalid")
        assert result.stderr == b""
    assert not missing_root.exists()


def test_ask_stops_when_git_provenance_is_unavailable_before_root_io(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing-knowledge-root"

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(missing_root),
            "knowledge",
            "ask",
            "Which evidence supports this conclusion?",
            "--json",
        ),
        environment_updates={"PATH": ""},
    )

    for result in results:
        assert result.returncode == 2
        assert result.stdout == _blocked_json_line("provenance_unavailable")
        assert result.stderr == b""
    assert not missing_root.exists()


def test_ask_stops_when_the_knowledge_root_is_unavailable(
    empty_knowledge_ask_root: Path,
) -> None:
    missing_root = empty_knowledge_ask_root / "missing"

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(missing_root),
            "knowledge",
            "ask",
            "Which evidence supports this conclusion?",
            "--json",
        )
    )

    for result in results:
        assert result.returncode == 2
        assert result.stdout == _blocked_json_line("data_root_unavailable")
        assert result.stderr == b""
    assert not missing_root.exists()


def test_ask_does_not_wait_when_the_answer_writer_is_busy(
    empty_knowledge_ask_root: Path,
) -> None:
    source = (
        "import sys\n"
        "from gezhi._windows_data_root import open_validated_data_root_v1\n"
        "from gezhi._windows_ownership import "
        "try_acquire_knowledge_answer_writer_v1\n"
        f"root = open_validated_data_root_v1({str(empty_knowledge_ask_root)!r})\n"
        "with root:\n"
        "    identity = root.inspection.identity\n"
        "    assert identity is not None\n"
        "    owner = try_acquire_knowledge_answer_writer_v1(identity)\n"
        "    assert owner is not None\n"
        "    with owner:\n"
        "        print('ready', flush=True)\n"
        "        sys.stdin.buffer.read(1)\n"
    )
    writer = subprocess.Popen(
        [str(PYTHON_EXE), "-c", source],
        cwd=REPOSITORY_ROOT,
        env=subprocess_environment(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    try:
        assert writer.stdout is not None
        assert writer.stdout.readline() in {b"ready\n", b"ready\r\n"}
        results = run_both_launchers(
            (
                "--knowledge-data-root",
                str(empty_knowledge_ask_root),
                "knowledge",
                "ask",
                "Which evidence supports this conclusion?",
                "--json",
            )
        )
        assert writer.stdin is not None
        writer.stdin.write(b"x")
        writer.stdin.close()
        assert writer.wait(timeout=5) == 0
        assert writer.stderr is not None
        assert writer.stderr.read() == b""
    finally:
        if writer.poll() is None:
            writer.kill()
            writer.wait(timeout=5)

    for result in results:
        assert result.returncode == 2
        assert result.stdout == _blocked_json_line("answer_writer_busy")
        assert result.stderr == b""
    assert not (empty_knowledge_ask_root / "answers").exists()


def test_ask_commits_insufficient_evidence_without_starting_codex(
    zero_active_knowledge_ask_root: Path,
    tmp_path: Path,
) -> None:
    site_root = tmp_path / "site"
    marker = _install_codex_launch_guard(site_root)
    answer_output = {
        "answer_status": "insufficient_evidence",
        "answer_units": [],
        "insufficiency_reason": "no_matching_candidates",
        "qualification_units": [],
        "schema_version": "gezhi.answer_output.v1",
    }

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(zero_active_knowledge_ask_root),
            "knowledge",
            "ask",
            "Which evidence supports this conclusion?",
            "--json",
        ),
        pythonpath_roots=(site_root, SOURCE_ROOT),
        environment_updates={"T20_CODEX_LAUNCH_MARKER": str(marker)},
    )

    observed_ids: set[str] = set()
    for result in results:
        assert result.returncode == 0
        assert result.stderr == b""
        envelope = json.loads(result.stdout)
        assert envelope == {
            "command": "knowledge.ask",
            "diagnostics": [],
            "outcome": "succeeded",
            "result": {
                "answer_id": envelope["result"]["answer_id"],
                "answer_output": answer_output,
            },
            "schema_version": "gezhi.cli_result.v1",
        }
        answer_id = envelope["result"]["answer_id"]
        assert _ANSWER_ID.fullmatch(answer_id) is not None
        observed_ids.add(answer_id)
        committed = zero_active_knowledge_ask_root / "answers" / answer_id
        _assert_zero_candidate_terminal_answer(
            zero_active_knowledge_ask_root,
            answer_id,
            question="Which evidence supports this conclusion?",
            answer_output=answer_output,
        )
        assert not (committed / "prompt.txt").exists()
        assert not (committed / "schema.json").exists()
        assert not (committed / "attempts").exists()

    assert len(observed_ids) == 2
    assert not marker.exists()


def test_ask_treats_a_valid_empty_registry_as_insufficient_evidence(
    empty_registry_knowledge_ask_root: Path,
    tmp_path: Path,
) -> None:
    site_root = tmp_path / "site"
    marker = _install_codex_launch_guard(site_root)

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(empty_registry_knowledge_ask_root),
            "knowledge",
            "ask",
            "Which evidence supports this conclusion?",
            "--json",
        ),
        pythonpath_roots=(site_root, SOURCE_ROOT),
        environment_updates={"T20_CODEX_LAUNCH_MARKER": str(marker)},
    )

    for result in results:
        assert result.returncode == 0
        assert result.stderr == b""
        envelope = json.loads(result.stdout)
        answer_id = envelope["result"]["answer_id"]
        assert envelope["result"]["answer_output"]["answer_status"] == (
            "insufficient_evidence"
        )
        _assert_zero_candidate_terminal_answer(
            empty_registry_knowledge_ask_root,
            answer_id,
            question="Which evidence supports this conclusion?",
            answer_output=envelope["result"]["answer_output"],
        )
    assert not marker.exists()


def test_ask_does_not_start_codex_when_active_candidates_do_not_match(
    active_knowledge_ask_root: Path,
    tmp_path: Path,
) -> None:
    site_root = tmp_path / "site"
    marker = _install_codex_launch_guard(site_root)
    question = "zzqvtwentynohit termalpha termbeta"

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(active_knowledge_ask_root),
            "knowledge",
            "ask",
            question,
            "--json",
        ),
        pythonpath_roots=(site_root, SOURCE_ROOT),
        environment_updates={"T20_CODEX_LAUNCH_MARKER": str(marker)},
    )

    for result in results:
        assert result.returncode == 0
        assert result.stderr == b""
        envelope = json.loads(result.stdout)
        answer_id = envelope["result"]["answer_id"]
        answer_output = envelope["result"]["answer_output"]
        assert answer_output["insufficiency_reason"] == "no_matching_candidates"
        _assert_zero_candidate_terminal_answer(
            active_knowledge_ask_root,
            answer_id,
            question=question,
            answer_output=answer_output,
        )
    assert not marker.exists()


def test_ask_human_success_appends_the_exact_committed_markdown(
    empty_registry_knowledge_ask_root: Path,
    tmp_path: Path,
) -> None:
    site_root = tmp_path / "site"
    marker = _install_codex_launch_guard(site_root)
    question = "哪些证据支持这个结论？"

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(empty_registry_knowledge_ask_root),
            "knowledge",
            "ask",
            question,
        ),
        pythonpath_roots=(site_root, SOURCE_ROOT),
        environment_updates={"T20_CODEX_LAUNCH_MARKER": str(marker)},
    )

    observed_ids: set[str] = set()
    for result in results:
        assert result.returncode == 0
        assert result.stderr == b""
        first_line, id_line, next_line, blank, markdown = result.stdout.split(b"\n", 4)
        assert first_line == "Knowledge ask：完成".encode()
        assert id_line.startswith("Answer ID：".encode())
        answer_id = id_line.decode().removeprefix("Answer ID：")
        assert _ANSWER_ID.fullmatch(answer_id) is not None
        assert next_line == "下一步：无需操作".encode()
        assert blank == b""
        committed_markdown = (
            empty_registry_knowledge_ask_root / "answers" / answer_id / "answer.md"
        ).read_bytes()
        assert markdown == committed_markdown
        observed_ids.add(answer_id)
    assert len(observed_ids) == 2
    assert not marker.exists()


def test_ask_persists_the_exact_normalized_question_and_retrieval_query(
    empty_registry_knowledge_ask_root: Path,
) -> None:
    raw_question = " \tCafe\u0301?\r\n  Evidence\t "
    normalized_question = "Café?\n  Evidence"

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(empty_registry_knowledge_ask_root),
            "knowledge",
            "ask",
            raw_question,
            "--json",
        )
    )

    for result in results:
        assert result.returncode == 0
        assert result.stderr == b""
        envelope = json.loads(result.stdout)
        answer_id = envelope["result"]["answer_id"]
        committed = empty_registry_knowledge_ask_root / "answers" / answer_id
        assert (committed / "question.json").read_bytes() == _canonical_json_line(
            {
                "question": normalized_question,
                "schema_version": "gezhi.question.v1",
            }
        )
        assert (committed / "retrieval_query.json").read_bytes() == (
            _canonical_json_line(
                {
                    "normalized_text": "café? evidence",
                    "schema_version": "gezhi.retrieval_query.v1",
                    "trigram_atoms": ["café", "evidence"],
                    "unicode61_atoms": ["café", "evidence"],
                }
            )
        )
        assert (
            b"Caf\xc3\xa9\\?\\\n&#32;&#32;Evidence"
            in (committed / "answer.md").read_bytes()
        )
