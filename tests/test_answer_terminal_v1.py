from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from gezhi import _answer_terminal as terminal
from gezhi import _windows_data_root as windows_root
from gezhi._windows_data_root import open_validated_data_root_v1
from gezhi._windows_ownership import try_acquire_knowledge_answer_writer_v1


def _canonical_json_file(value: object) -> bytes:
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


def _succeeded_request_with_timeout_attempt() -> terminal.AnswerPublishRequestV1:
    retrieval_view_bytes = _canonical_json_file(
        {
            "candidate_count": 1,
            "schema_version": "gezhi.retrieval_view.v1",
        }
    )
    retrieval_audit_bytes = _canonical_json_file(
        {
            "retrieval_view_measurement": {
                "byte_length": len(retrieval_view_bytes),
                "limit_bytes": 262_144,
                "sha256": hashlib.sha256(retrieval_view_bytes).hexdigest(),
                "status": "within_limit",
            },
            "schema_version": "gezhi.retrieval_audit.v1",
        }
    )
    timestamp = "2026-08-31T12:00:00.000Z"
    return terminal.AnswerPublishRequestV1(
        answer_id="ans_00000000-0000-4000-8000-000000000000",
        started_at=timestamp,
        started_monotonic_ns=1,
        provenance={
            "codex_cli_version": "0.146.0",
            "git": {"revision": "0" * 40, "state": "clean"},
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "role_version": "knowledge_answerer_v1",
        },
        effective_config_bytes=_canonical_json_file(
            {
                "attempt_timeout_ms": 1_800_000,
                "attempt_window_limit_ms": 5_700_000,
                "retry_backoff_schedule_ms": [10_000, 30_000],
                "schema_version": "gezhi.knowledge_answerer_effective_config.v1",
            }
        ),
        question_bytes=_canonical_json_file({"schema_version": "gezhi.question.v1"}),
        retrieval_query_bytes=_canonical_json_file(
            {"schema_version": "gezhi.retrieval_query.v1"}
        ),
        retrieval_audit_bytes=retrieval_audit_bytes,
        retrieval_view_bytes=retrieval_view_bytes,
        prompt_bytes=b"prompt\n",
        schema_bytes=_canonical_json_file(
            {"$id": ("https://gezhi.local/schemas/answer-output-v1.schema.json")}
        ),
        attempts=(
            terminal.AnswerAttemptPublishV1(
                record={
                    "cached_input_tokens": None,
                    "elapsed_ms": 1,
                    "exit_code": 0x475A0001,
                    "failure_class": "timeout",
                    "finished_at": timestamp,
                    "input_tokens": None,
                    "output_tokens": None,
                    "reasoning_output_tokens": None,
                    "started_at": timestamp,
                    "usage_unavailable": True,
                },
                events_bytes=b"",
                final_message_bytes=b"",
            ),
        ),
        answer_output_bytes=_canonical_json_file(
            {"schema_version": "gezhi.answer_output.v1"}
        ),
        answer_markdown_bytes=b"answer\n",
    )


def _request_with_terminal_matrix(
    *,
    status: str,
    error: dict[str, object] | None,
    failure_classes: tuple[str | None, ...],
) -> terminal.AnswerPublishRequestV1:
    base = _succeeded_request_with_timeout_attempt()
    prototype = base.attempts[0]
    attempts = []
    for failure_class in failure_classes:
        record = dict(prototype.record)
        record["failure_class"] = failure_class
        record["exit_code"] = 0 if failure_class is None else 0x475A0001
        events_bytes = (
            _canonical_json_file({"type": "turn.completed"})
            if failure_class is None
            else prototype.events_bytes
        )
        attempts.append(replace(prototype, record=record, events_bytes=events_bytes))
    succeeded = status == "succeeded"
    return replace(
        base,
        status=status,  # type: ignore[arg-type]
        error=error,
        attempts=tuple(attempts),
        answer_output_bytes=base.answer_output_bytes if succeeded else None,
        answer_markdown_bytes=base.answer_markdown_bytes if succeeded else None,
    )


def _zero_candidate_request(
    *,
    error: dict[str, object],
) -> terminal.AnswerPublishRequestV1:
    base = _request_with_terminal_matrix(
        status="failed",
        error=error,
        failure_classes=(),
    )
    retrieval_view_bytes = _canonical_json_file(
        {
            "candidate_count": 0,
            "schema_version": "gezhi.retrieval_view.v1",
        }
    )
    retrieval_audit_bytes = _canonical_json_file(
        {
            "retrieval_view_measurement": {
                "byte_length": len(retrieval_view_bytes),
                "limit_bytes": 262_144,
                "sha256": hashlib.sha256(retrieval_view_bytes).hexdigest(),
                "status": "within_limit",
            },
            "schema_version": "gezhi.retrieval_audit.v1",
        }
    )
    return replace(
        base,
        retrieval_audit_bytes=retrieval_audit_bytes,
        retrieval_view_bytes=retrieval_view_bytes,
        prompt_bytes=None,
        schema_bytes=None,
    )


def _request_at_root_prefix(
    request: terminal.AnswerPublishRequestV1,
    prefix: int,
) -> terminal.AnswerPublishRequestV1:
    field_names = (
        "effective_config_bytes",
        "question_bytes",
        "retrieval_query_bytes",
        "retrieval_audit_bytes",
        "retrieval_view_bytes",
    )
    changes = {name: None for name in field_names[prefix + 1 :]}
    if prefix < 4:
        changes.update(prompt_bytes=None, schema_bytes=None)
    return replace(request, **changes)


def _request_with_candidate_count(
    request: terminal.AnswerPublishRequestV1,
    candidate_count: int,
) -> terminal.AnswerPublishRequestV1:
    retrieval_view_bytes = _canonical_json_file(
        {
            "candidate_count": candidate_count,
            "schema_version": "gezhi.retrieval_view.v1",
        }
    )
    retrieval_audit_bytes = _canonical_json_file(
        {
            "retrieval_view_measurement": {
                "byte_length": len(retrieval_view_bytes),
                "limit_bytes": 262_144,
                "sha256": hashlib.sha256(retrieval_view_bytes).hexdigest(),
                "status": "within_limit",
            },
            "schema_version": "gezhi.retrieval_audit.v1",
        }
    )
    return replace(
        request,
        retrieval_audit_bytes=retrieval_audit_bytes,
        retrieval_view_bytes=retrieval_view_bytes,
    )


def _too_large_retrieval_audit_bytes() -> bytes:
    return _canonical_json_file(
        {
            "retrieval_view_measurement": {
                "byte_length": 262_145,
                "limit_bytes": 262_144,
                "sha256": "0" * 64,
                "status": "too_large",
            },
            "schema_version": "gezhi.retrieval_audit.v1",
        }
    )


def test_committed_reader_revalidates_a_published_answer(tmp_path) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert owner is not None
        with owner:
            committed = terminal.publish_answer_v1(root, owner, request)

        observed = terminal.read_committed_answer_v1(root, request.answer_id)

    assert observed.answer_id == committed.answer_id
    assert observed.manifest_sha256 == committed.manifest_sha256
    assert observed.status == "succeeded"
    assert observed.answer_output_bytes == request.answer_output_bytes
    assert observed.answer_markdown_bytes == request.answer_markdown_bytes


@pytest.mark.parametrize(
    "relative_path",
    (None, "attempts", "attempts/01", "manifest.json", "answer.md"),
)
def test_committed_reader_rejects_named_streams_on_terminal_entries(
    tmp_path: Path,
    relative_path: str | None,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert owner is not None
        with owner:
            terminal.publish_answer_v1(root, owner, request)

        target = knowledge_root / "answers" / request.answer_id
        if relative_path is not None:
            target /= relative_path
        Path(f"{target}:unapproved").write_bytes(b"hidden bytes")
        observed = terminal.read_committed_answer_v1(root, request.answer_id)

    assert type(observed) is terminal.TerminalAnswerBytesRejectedV1


def test_writer_readback_rejects_an_asset_changed_after_manifest_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    real_write = terminal._write_new_file

    def write_then_tamper(path: Path, payload: bytes) -> None:
        real_write(path, payload)
        if path.name == "manifest.json":
            (path.parent / "answer.md").write_bytes(b"tampered\n")

    monkeypatch.setattr(terminal, "_write_new_file", write_then_tamper)

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert owner is not None
        with owner, pytest.raises(terminal.AnswerManifestFailedV1):
            terminal.publish_answer_v1(root, owner, request)

    staging = knowledge_root / "answers" / ".staging" / request.answer_id
    target = knowledge_root / "answers" / request.answer_id
    assert staging.is_dir()
    assert not target.exists()


def test_staging_scan_recovers_one_fully_valid_orphan(tmp_path: Path) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        first_owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert first_owner is not None
        with first_owner:
            terminal.publish_answer_v1(root, first_owner, request)

        target = knowledge_root / "answers" / request.answer_id
        orphan = knowledge_root / "answers" / ".staging" / request.answer_id
        target.rename(orphan)

        recovery_owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert recovery_owner is not None
        with recovery_owner:
            scan = terminal.scan_answer_staging_v1(root, recovery_owner)

    assert scan.status == "complete"
    assert scan.entry_count == 1
    assert scan.recovered_count == 1
    assert scan.quarantined_count == 0
    assert scan.recovery_failed_count == 0
    assert scan.target_conflict_count == 0
    assert target.is_dir()
    assert not orphan.exists()


def test_staging_scan_quarantines_one_reparse_candidate_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    reparse_id = "ans_ffffffff-ffff-4fff-8fff-ffffffffffff"

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        first_owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert first_owner is not None
        with first_owner:
            terminal.publish_answer_v1(root, first_owner, request)
        target = knowledge_root / "answers" / request.answer_id
        orphan = knowledge_root / "answers" / ".staging" / request.answer_id
        target.rename(orphan)
        real_entries = type(root).relative_entries_v1

        def enumerate_staging(observed: object) -> tuple[object, ...]:
            inspection = observed.inspection  # type: ignore[attr-defined]
            assert inspection.canonical_path is not None
            if not inspection.canonical_path.endswith(r"answers\.staging"):
                return real_entries(observed)  # type: ignore[arg-type]
            return (
                SimpleNamespace(
                    name=request.answer_id,
                    is_directory=True,
                    is_reparse=False,
                    short_name=None,
                ),
                SimpleNamespace(
                    name=reparse_id,
                    is_directory=True,
                    is_reparse=True,
                    short_name=None,
                ),
            )

        monkeypatch.setattr(
            type(root),
            "relative_entries_v1",
            enumerate_staging,
            raising=False,
        )
        recovery_owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert recovery_owner is not None
        with recovery_owner:
            scan = terminal.scan_answer_staging_v1(root, recovery_owner)

    assert scan.status == "complete"
    assert scan.entry_count == 2
    assert scan.quarantined_count == 1
    assert scan.recovered_count == 1
    assert target.is_dir()
    assert not orphan.exists()
    assert not (knowledge_root / "answers" / reparse_id).exists()


def test_current_publish_ignores_an_unrelated_quarantined_reparse_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    staging = knowledge_root / "answers" / ".staging"
    staging.mkdir(parents=True)
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    real_entries = windows_root.ValidatedDataRootV1.relative_entries_v1
    real_names = windows_root.ValidatedDataRootV1.relative_entry_names_v1

    def is_staging(observed: windows_root.ValidatedDataRootV1) -> bool:
        path = observed.inspection.canonical_path
        return path is not None and path.endswith(r"answers\.staging")

    def entries_with_reparse(
        observed: windows_root.ValidatedDataRootV1,
    ) -> tuple[windows_root.DataRootEntryV1, ...]:
        entries = real_entries(observed)
        if not is_staging(observed):
            return entries
        return (
            *entries,
            windows_root.DataRootEntryV1(
                name="ans_ffffffff-ffff-4fff-8fff-ffffffffffff",
                is_directory=True,
                is_reparse=True,
                short_name=None,
            ),
        )

    def strict_names(
        observed: windows_root.ValidatedDataRootV1,
    ) -> tuple[str, ...]:
        if is_staging(observed):
            raise windows_root.DataRootOpenErrorV1("unsafe")
        return real_names(observed)

    monkeypatch.setattr(
        windows_root.ValidatedDataRootV1,
        "relative_entries_v1",
        entries_with_reparse,
    )
    monkeypatch.setattr(
        windows_root.ValidatedDataRootV1,
        "relative_entry_names_v1",
        strict_names,
    )

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert owner is not None
        with owner:
            committed = terminal.publish_answer_v1(root, owner, request)

    assert committed.answer_id == request.answer_id
    assert (knowledge_root / "answers" / request.answer_id).is_dir()


def test_current_publish_is_consumed_after_one_behavior_call(tmp_path: Path) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    first_request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    second_request = replace(
        first_request,
        answer_id="ans_11111111-1111-4111-8111-111111111111",
    )

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert owner is not None
        with owner:
            terminal.publish_answer_v1(root, owner, first_request)
            with pytest.raises(terminal.AnswerWriterOwnershipInvalidV1):
                terminal.publish_answer_v1(root, owner, second_request)

    assert (knowledge_root / "answers" / first_request.answer_id).is_dir()
    assert not (knowledge_root / "answers" / second_request.answer_id).exists()


def test_current_publish_is_consumed_even_when_request_validation_fails(
    tmp_path: Path,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    invalid_request = _succeeded_request_with_timeout_attempt()
    valid_request = replace(
        _request_with_terminal_matrix(
            status="succeeded",
            error=None,
            failure_classes=(None,),
        ),
        answer_id="ans_22222222-2222-4222-8222-222222222222",
    )

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert owner is not None
        with owner:
            with pytest.raises(terminal.AnswerTerminalRequestInvalidV1):
                terminal.publish_answer_v1(root, owner, invalid_request)
            with pytest.raises(terminal.AnswerWriterOwnershipInvalidV1):
                terminal.publish_answer_v1(root, owner, valid_request)

    assert not (knowledge_root / "answers").exists()


def test_current_publish_target_conflict_is_no_commit_and_consumes_the_attempt(
    tmp_path: Path,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    target = knowledge_root / "answers" / request.answer_id
    target.mkdir(parents=True)

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert owner is not None
        with owner:
            with pytest.raises(terminal.AnswerTargetConflictV1):
                terminal.publish_answer_v1(root, owner, request)
            with pytest.raises(terminal.AnswerWriterOwnershipInvalidV1):
                terminal.publish_answer_v1(root, owner, request)

    assert target.is_dir()
    assert not (knowledge_root / "answers" / ".staging" / request.answer_id).exists()


def test_current_publish_determinate_rename_failure_keeps_staging_and_is_one_shot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    monkeypatch.setattr(
        terminal.os,
        "rename",
        lambda _source, _target: (_ for _ in ()).throw(
            PermissionError("forced determinate publish failure")
        ),
    )

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert owner is not None
        with owner:
            with pytest.raises(terminal.AnswerCommitFailedV1):
                terminal.publish_answer_v1(root, owner, request)
            with pytest.raises(terminal.AnswerWriterOwnershipInvalidV1):
                terminal.publish_answer_v1(root, owner, request)

    assert (knowledge_root / "answers" / ".staging" / request.answer_id).is_dir()
    assert not (knowledge_root / "answers" / request.answer_id).exists()


def test_current_publish_uncertain_completion_keeps_commit_but_returns_no_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    real_rename = terminal.os.rename

    def rename_then_report_failure(source: object, target: object) -> None:
        real_rename(source, target)
        raise PermissionError("forced uncertain publish completion")

    monkeypatch.setattr(terminal.os, "rename", rename_then_report_failure)

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert owner is not None
        with owner:
            with pytest.raises(terminal.AnswerCommitIndeterminateV1):
                terminal.publish_answer_v1(root, owner, request)
            with pytest.raises(terminal.AnswerWriterOwnershipInvalidV1):
                terminal.publish_answer_v1(root, owner, request)

    assert (knowledge_root / "answers" / request.answer_id).is_dir()
    assert not (knowledge_root / "answers" / ".staging" / request.answer_id).exists()
    assert not tuple(knowledge_root.rglob("current.json"))


def test_manifest_aggregate_rejects_a_negative_internal_asset_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    provenance, _request_assets, attempts = terminal._validate_request(request)
    invalid_asset = terminal._VerifiedAssetV1(
        path="answer.md",
        byte_length=-1,
        sha256="0" * 64,
        identity_key="media_type",
        identity_value="text/markdown; charset=utf-8",
    )
    monkeypatch.setattr(terminal, "_canonical_json_file", lambda _value: b"{}\n")

    with pytest.raises(terminal.AnswerManifestFailedV1, match="capacity"):
        terminal._manifest_bytes(
            request,
            provenance,
            (invalid_asset,),
            attempts,
        )


def test_manifest_aggregate_overflow_precedes_manifest_leaf_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    written_names: list[str] = []
    real_write = terminal._write_new_file

    def record_write(path: Path, payload: bytes) -> None:
        written_names.append(path.name)
        real_write(path, payload)

    monkeypatch.setattr(terminal, "_write_new_file", record_write)
    monkeypatch.setattr(terminal, "ANSWER_TERMINAL_MAX_BYTES", 1)

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert owner is not None
        with owner, pytest.raises(terminal.AnswerManifestFailedV1):
            terminal.publish_answer_v1(root, owner, request)

    stage = knowledge_root / "answers" / ".staging" / request.answer_id
    assert "manifest.json" not in written_names
    assert not (stage / "manifest.json").exists()
    assert stage.is_dir()


def test_manifest_aggregate_uses_one_actual_serialized_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    provenance, _request_assets, attempts = terminal._validate_request(request)
    actual_manifest = b"{}\n"
    asset = terminal._VerifiedAssetV1(
        path="answer.md",
        byte_length=terminal.ANSWER_TERMINAL_MAX_BYTES - len(actual_manifest),
        sha256="0" * 64,
        identity_key="media_type",
        identity_value="text/markdown; charset=utf-8",
    )
    serialized: list[object] = []

    def serialize_once(value: object) -> bytes:
        serialized.append(value)
        return actual_manifest

    monkeypatch.setattr(terminal, "_canonical_json_file", serialize_once)

    observed = terminal._manifest_bytes(
        request,
        provenance,
        (asset,),
        attempts,
    )

    assert observed is actual_manifest
    assert len(serialized) == 1
    assert asset.byte_length + 65_536 > terminal.ANSWER_TERMINAL_MAX_BYTES


def test_committed_reader_bounds_each_asset_by_its_declared_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    observed_limits: list[int] = []
    real_read = windows_root.ValidatedFileV1.read_bytes_v1

    def capture_limit(
        source: windows_root.ValidatedFileV1,
        *,
        limit: int,
    ) -> bytes:
        if source.canonical_path.endswith(r"\answer.md"):
            observed_limits.append(limit)
        return real_read(source, limit=limit)

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert owner is not None
        with owner:
            terminal.publish_answer_v1(root, owner, request)
        monkeypatch.setattr(
            windows_root.ValidatedFileV1,
            "read_bytes_v1",
            capture_limit,
        )

        observed = terminal.read_committed_answer_v1(root, request.answer_id)

    assert type(observed) is terminal.TerminalAnswerBytesReadyV1
    assert observed_limits == [len(request.answer_markdown_bytes or b"")]


@pytest.mark.parametrize(
    "payload",
    (
        b'{"a":[[[[[[[[0]]]]]]]]}\n',
        b'{"a":10000000000000000000}\n',
        b'{"a":0.0}\n',
        b'{"a":1,"a":2}\n',
    ),
    ids=("depth-nine", "twenty-digit-integer", "float", "duplicate-key"),
)
def test_terminal_manifest_parser_rejects_resource_profile_violations(
    payload: bytes,
) -> None:
    with pytest.raises(terminal.AnswerTerminalRequestInvalidV1):
        terminal._decode_terminal_manifest_v1(payload)


def test_staging_scan_quarantines_an_invalid_candidate_in_place(
    tmp_path: Path,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    staging = knowledge_root / "answers" / ".staging"
    invalid = staging / "not-an-answer"
    invalid.mkdir(parents=True)

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert owner is not None
        with owner:
            scan = terminal.scan_answer_staging_v1(root, owner)

    assert scan.quarantined_count == 1
    assert scan.recovered_count == 0
    assert invalid.is_dir()


def test_staging_scan_does_not_overwrite_an_existing_target(tmp_path: Path) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        first_owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert first_owner is not None
        with first_owner:
            terminal.publish_answer_v1(root, first_owner, request)
        target = knowledge_root / "answers" / request.answer_id
        orphan = knowledge_root / "answers" / ".staging" / request.answer_id
        shutil.copytree(target, orphan)

        recovery_owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert recovery_owner is not None
        with recovery_owner:
            scan = terminal.scan_answer_staging_v1(root, recovery_owner)

    assert scan.target_conflict_count == 1
    assert scan.recovered_count == 0
    assert target.is_dir()
    assert orphan.is_dir()


def test_staging_scan_keeps_a_determinate_recovery_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        first_owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert first_owner is not None
        with first_owner:
            terminal.publish_answer_v1(root, first_owner, request)
        target = knowledge_root / "answers" / request.answer_id
        orphan = knowledge_root / "answers" / ".staging" / request.answer_id
        target.rename(orphan)

        def fail_rename(_source: object, _target: object) -> None:
            raise PermissionError("forced determinate failure")

        monkeypatch.setattr(terminal.os, "rename", fail_rename)
        recovery_owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert recovery_owner is not None
        with recovery_owner:
            scan = terminal.scan_answer_staging_v1(root, recovery_owner)

    assert scan.recovery_failed_count == 1
    assert scan.recovered_count == 0
    assert orphan.is_dir()
    assert not target.exists()


def test_staging_scan_stops_on_an_indeterminate_recovery_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )

    with open_validated_data_root_v1(str(knowledge_root)) as root:
        identity = root.inspection.identity
        assert identity is not None
        first_owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert first_owner is not None
        with first_owner:
            terminal.publish_answer_v1(root, first_owner, request)
        target = knowledge_root / "answers" / request.answer_id
        orphan = knowledge_root / "answers" / ".staging" / request.answer_id
        target.rename(orphan)
        real_rename = terminal.os.rename

        def rename_then_report_failure(source: object, destination: object) -> None:
            real_rename(source, destination)
            raise PermissionError("forced uncertain completion")

        monkeypatch.setattr(terminal.os, "rename", rename_then_report_failure)
        recovery_owner = try_acquire_knowledge_answer_writer_v1(identity)
        assert recovery_owner is not None
        with recovery_owner, pytest.raises(terminal.AnswerCommitIndeterminateV1):
            terminal.scan_answer_staging_v1(root, recovery_owner)

    assert target.is_dir()
    assert not orphan.exists()


def test_terminal_writer_rejects_success_with_a_timeout_attempt() -> None:
    request = _succeeded_request_with_timeout_attempt()

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_runtime_unavailable_before_synthesis_package() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="blocked",
            error={"code": "codex_runtime_unavailable", "stage": "synthesis"},
            failure_classes=(),
        ),
        0,
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_retrieval_query_failure_before_query_asset() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="failed",
            error={"code": "retrieval_query_failed", "stage": "retrieval"},
            failure_classes=(),
        ),
        1,
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_fts_failure_after_retrieval_view() -> None:
    request = _request_with_terminal_matrix(
        status="blocked",
        error={"code": "fts5_unavailable", "stage": "retrieval"},
        failure_classes=(),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_synthesis_input_failure_before_view() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="failed",
            error={"code": "synthesis_input_invalid", "stage": "synthesis"},
            failure_classes=(),
        ),
        0,
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_materialization_failure_after_view() -> None:
    request = _request_with_terminal_matrix(
        status="failed",
        error={
            "code": "retrieval_materialization_failed",
            "stage": "retrieval",
        },
        failure_classes=(),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_accepts_materialization_failure_after_audit() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="failed",
            error={
                "code": "retrieval_materialization_failed",
                "stage": "retrieval",
            },
            failure_classes=(),
        ),
        3,
    )

    terminal._validate_request(request)


@pytest.mark.parametrize(
    "measurement",
    (
        {
            "byte_length": 109,
            "limit_bytes": 262_144,
            "status": "within_limit",
        },
        {
            "byte_length": 109,
            "extra": None,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "within_limit",
        },
        {
            "byte_length": True,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "within_limit",
        },
        {
            "byte_length": -1,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "within_limit",
        },
        {
            "byte_length": 9_223_372_036_854_775_808,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "too_large",
        },
        {
            "byte_length": 109,
            "limit_bytes": True,
            "sha256": "0" * 64,
            "status": "within_limit",
        },
        {
            "byte_length": 109,
            "limit_bytes": 262_144,
            "sha256": "A" * 64,
            "status": "within_limit",
        },
        {
            "byte_length": 109,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "unknown",
        },
        {
            "byte_length": 109,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": [],
        },
        {
            "byte_length": 262_145,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "within_limit",
        },
        {
            "byte_length": 262_144,
            "limit_bytes": 262_144,
            "sha256": "0" * 64,
            "status": "too_large",
        },
    ),
    ids=(
        "missing-field",
        "extra-field",
        "boolean-length",
        "negative-length",
        "length-over-int64",
        "boolean-limit",
        "non-lowercase-hash",
        "unknown-status",
        "non-scalar-status",
        "within-limit-over-cap",
        "too-large-at-cap",
    ),
)
def test_terminal_writer_rejects_invalid_interrupted_p3_measurement(
    measurement: dict[str, object],
) -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="interrupted",
            error=None,
            failure_classes=(),
        ),
        3,
    )
    request = replace(
        request,
        retrieval_audit_bytes=_canonical_json_file(
            {
                "retrieval_view_measurement": measurement,
                "schema_version": "gezhi.retrieval_audit.v1",
            }
        ),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="Retrieval View measurement",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_float_measurement_as_noncanonical_json() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="interrupted",
            error=None,
            failure_classes=(),
        ),
        3,
    )
    request = replace(
        request,
        retrieval_audit_bytes=_canonical_json_file(
            {
                "retrieval_view_measurement": {
                    "byte_length": 109,
                    "limit_bytes": 262_144.0,
                    "sha256": "0" * 64,
                    "status": "within_limit",
                },
                "schema_version": "gezhi.retrieval_audit.v1",
            }
        ),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="Answer JSON asset is invalid",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_materialization_failure_for_over_limit_view() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="failed",
            error={
                "code": "retrieval_materialization_failed",
                "stage": "retrieval",
            },
            failure_classes=(),
        ),
        3,
    )
    request = replace(
        request,
        retrieval_audit_bytes=_too_large_retrieval_audit_bytes(),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="Missing Retrieval View",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_success_with_negative_candidate_count() -> None:
    request = _request_with_candidate_count(
        replace(
            _request_with_terminal_matrix(
                status="succeeded",
                error=None,
                failure_classes=(),
            ),
            prompt_bytes=None,
            schema_bytes=None,
        ),
        -1,
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_interrupt_with_out_of_range_candidates() -> None:
    request = _request_with_candidate_count(
        replace(
            _request_with_terminal_matrix(
                status="interrupted",
                error=None,
                failure_classes=(),
            ),
            prompt_bytes=None,
            schema_bytes=None,
        ),
        13,
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="root terminal matrix",
    ):
        terminal._validate_request(request)


@pytest.mark.parametrize(
    ("error", "prefix"),
    (
        ({"code": "fts5_unavailable", "stage": "retrieval"}, 2),
        ({"code": "retrieval_query_failed", "stage": "retrieval"}, 2),
        (
            {"code": "retrieval_materialization_failed", "stage": "retrieval"},
            0,
        ),
        (
            {"code": "retrieval_materialization_failed", "stage": "retrieval"},
            1,
        ),
        (
            {"code": "retrieval_materialization_failed", "stage": "retrieval"},
            2,
        ),
        (
            {"code": "retrieval_materialization_failed", "stage": "retrieval"},
            3,
        ),
    ),
    ids=("fts-p2", "query-p2", "materialization-p0", "p1", "p2", "p3"),
)
def test_terminal_writer_accepts_retrieval_terminal_prefixes(
    error: dict[str, object],
    prefix: int,
) -> None:
    status = "blocked" if error["code"] == "fts5_unavailable" else "failed"
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status=status,
            error=error,
            failure_classes=(),
        ),
        prefix,
    )

    terminal._validate_request(request)


def test_terminal_writer_accepts_synthesis_input_failure_without_call_pair() -> None:
    request = replace(
        _request_with_terminal_matrix(
            status="failed",
            error={"code": "synthesis_input_invalid", "stage": "synthesis"},
            failure_classes=(),
        ),
        prompt_bytes=None,
        schema_bytes=None,
    )

    terminal._validate_request(request)


def test_terminal_writer_accepts_runtime_failure_before_first_commitment() -> None:
    request = _request_with_terminal_matrix(
        status="blocked",
        error={"code": "codex_runtime_unavailable", "stage": "synthesis"},
        failure_classes=(),
    )

    terminal._validate_request(request)


def test_terminal_writer_accepts_over_limit_view_at_audit_prefix() -> None:
    request = _request_at_root_prefix(
        _request_with_terminal_matrix(
            status="blocked",
            error={"code": "retrieval_view_too_large", "stage": "retrieval"},
            failure_classes=(),
        ),
        3,
    )
    request = replace(
        request,
        retrieval_audit_bytes=_too_large_retrieval_audit_bytes(),
    )

    terminal._validate_request(request)


def test_terminal_writer_rejects_usage_not_derived_from_attempt_events() -> None:
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    attempt = request.attempts[0]
    record = dict(attempt.record)
    record["input_tokens"] = 7
    request = replace(
        request,
        attempts=(replace(attempt, record=record),),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="attempt usage differs",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_invalid_events_as_retryable_timeout() -> None:
    request = _request_with_terminal_matrix(
        status="blocked",
        error={"code": "codex_timeout_exhausted", "stage": "synthesis"},
        failure_classes=("timeout",),
    )
    attempt = request.attempts[0]
    request = replace(
        request,
        attempts=(replace(attempt, events_bytes=b"not-json\n"),),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="attempt events differ",
    ):
        terminal._validate_request(request)


def test_terminal_writer_rejects_clean_exit_without_completed_event() -> None:
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    attempt = request.attempts[0]
    request = replace(
        request,
        attempts=(replace(attempt, events_bytes=b""),),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="attempt events differ",
    ):
        terminal._validate_request(request)


def test_terminal_writer_accepts_usage_recomputed_from_completed_event() -> None:
    request = _request_with_terminal_matrix(
        status="succeeded",
        error=None,
        failure_classes=(None,),
    )
    attempt = request.attempts[0]
    record = dict(attempt.record)
    record.update(
        input_tokens=11,
        cached_input_tokens=7,
        output_tokens=5,
        reasoning_output_tokens=3,
        usage_unavailable=False,
    )
    events_bytes = _canonical_json_file(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 11,
                "cached_input_tokens": 7,
                "output_tokens": 5,
                "reasoning_output_tokens": 3,
            },
        }
    )
    request = replace(
        request,
        attempts=(replace(attempt, record=record, events_bytes=events_bytes),),
    )

    terminal._validate_request(request)


def test_terminal_writer_accepts_invalid_events_as_process_error() -> None:
    request = _request_with_terminal_matrix(
        status="failed",
        error={"code": "codex_process_failed", "stage": "synthesis"},
        failure_classes=("process_error",),
    )
    attempt = request.attempts[0]
    request = replace(
        request,
        attempts=(replace(attempt, events_bytes=b"not-json\n"),),
    )

    terminal._validate_request(request)


def test_terminal_writer_rejects_invalid_exact_cap_events_as_timeout() -> None:
    request = _request_with_terminal_matrix(
        status="blocked",
        error={"code": "codex_timeout_exhausted", "stage": "synthesis"},
        failure_classes=("timeout",),
    )
    attempt = request.attempts[0]
    invalid_prefix = b"not-json\n"
    events_bytes = invalid_prefix + b" " * (16_777_216 - len(invalid_prefix))
    request = replace(
        request,
        attempts=(replace(attempt, events_bytes=events_bytes),),
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="attempt events differ",
    ):
        terminal._validate_request(request)


@pytest.mark.parametrize(
    ("status", "error", "failure_classes"),
    (
        ("succeeded", None, (None,)),
        ("succeeded", None, ("timeout", None)),
        (
            "blocked",
            {"code": "codex_timeout_exhausted", "stage": "synthesis"},
            ("timeout", "timeout"),
        ),
        (
            "failed",
            {"code": "codex_process_failed", "stage": "synthesis"},
            ("timeout", "process_error"),
        ),
        (
            "failed",
            {"code": "answer_output_invalid", "stage": "validation"},
            ("timeout", None),
        ),
        ("interrupted", None, ("timeout", "interrupted")),
        ("interrupted", None, ("timeout", None)),
    ),
    ids=(
        "success",
        "retry-success",
        "timeout-exhaustion",
        "process-failure",
        "validation-failure",
        "active-interrupt",
        "post-synthesis-interrupt",
    ),
)
def test_terminal_writer_accepts_closed_attempt_matrices(
    status: str,
    error: dict[str, object] | None,
    failure_classes: tuple[str | None, ...],
) -> None:
    request = _request_with_terminal_matrix(
        status=status,
        error=error,
        failure_classes=failure_classes,
    )

    terminal._validate_request(request)


@pytest.mark.parametrize(
    ("status", "error", "failure_classes"),
    (
        (
            "blocked",
            {"code": "codex_timeout_exhausted", "stage": "synthesis"},
            ("timeout", None),
        ),
        (
            "failed",
            {"code": "codex_process_failed", "stage": "synthesis"},
            ("timeout",),
        ),
        (
            "failed",
            {"code": "answer_output_invalid", "stage": "validation"},
            ("process_error",),
        ),
        ("interrupted", None, ("process_error",)),
        ("interrupted", None, ("timeout", "timeout", "timeout")),
        ("succeeded", None, (None, "timeout")),
        (
            "blocked",
            {"code": "codex_timeout_exhausted", "stage": "synthesis"},
            (),
        ),
        (
            "blocked",
            {"code": "codex_network_exhausted", "stage": "synthesis"},
            ("network",),
        ),
        (
            "blocked",
            {"code": "codex_network_exhausted", "stage": "synthesis"},
            (),
        ),
        (
            "blocked",
            {"code": "codex_rate_limit_exhausted", "stage": "synthesis"},
            (),
        ),
        (
            "blocked",
            {"code": "codex_server_error_exhausted", "stage": "synthesis"},
            (),
        ),
        (
            "blocked",
            {"code": "codex_transient_exhausted", "stage": "synthesis"},
            (),
        ),
    ),
    ids=(
        "exhaustion-with-success",
        "process-failure-with-timeout",
        "validation-with-process-error",
        "interrupt-with-process-error",
        "interrupt-after-three-timeouts",
        "failure-after-success",
        "exhaustion-without-attempt",
        "legacy-writer-class",
        "legacy-network-without-attempt",
        "legacy-rate-limit-without-attempt",
        "legacy-server-error-without-attempt",
        "legacy-transient-without-attempt",
    ),
)
def test_terminal_writer_rejects_cross_field_attempt_mismatches(
    status: str,
    error: dict[str, object] | None,
    failure_classes: tuple[str | None, ...],
) -> None:
    request = _request_with_terminal_matrix(
        status=status,
        error=error,
        failure_classes=failure_classes,
    )

    with pytest.raises(
        terminal.AnswerTerminalRequestInvalidV1,
        match="terminal matrix",
    ):
        terminal._validate_request(request)


@pytest.mark.parametrize(
    "error",
    (
        {"code": "answer_output_invalid", "stage": "validation"},
        {"code": "citation_link_construction_failed", "stage": "rendering"},
        {"code": "answer_rendering_failed", "stage": "rendering"},
    ),
    ids=("validation", "citation-link", "rendering"),
)
def test_terminal_writer_accepts_zero_candidate_post_synthesis_failure(
    error: dict[str, object],
) -> None:
    terminal._validate_request(_zero_candidate_request(error=error))
