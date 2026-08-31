from __future__ import annotations

from dataclasses import replace

import pytest

from gezhi import _knowledge_commands as commands
from gezhi import _presentation as presentation
from gezhi._knowledge_ask import CommittedAnswerLocatorV1, KnowledgeAskReportV1
from gezhi._knowledge_cancellation import CancellationSnapshotV1


def _committed_locator_v1() -> CommittedAnswerLocatorV1:
    return CommittedAnswerLocatorV1(
        root_path=r"E:\test\knowledge",
        answer_id="ans_550e8400-e29b-41d4-a716-446655440000",
        manifest_sha256="0" * 64,
    )


def _failed_overflow_report_v1() -> KnowledgeAskReportV1:
    return KnowledgeAskReportV1(
        outcome="failed",
        result={
            "answer_id": "ans_550e8400-e29b-41d4-a716-446655440000",
            "answer_output": None,
        },
        reason="codex_process_failed",
        capture_overflow_channels=("final_message",),
        committed_answer_locator=_committed_locator_v1(),
    )


def test_human_supplemental_precedes_the_next_step() -> None:
    payload = commands._knowledge_ask_human_buffer_v1(
        _failed_overflow_report_v1(),
        answer_markdown_bytes=None,
    )

    assert payload.decode("utf-8").splitlines() == [
        "Knowledge ask：失败",
        "Answer ID：ans_550e8400-e29b-41d4-a716-446655440000",
        "原因：Codex 子进程或捕获链失败",
        "提示：Codex 最终消息捕获超过 1048576 字节上限，已保留精确上限前缀",
        "下一步：先运行 gezhi status 观察 Knowledge 与 Answer 整体状态（status 不会修复）；必要时运行 gezhi doctor 检查 Codex 环境能力",
    ]


def test_orphan_recovery_facts_project_to_closed_supplementals() -> None:
    report = KnowledgeAskReportV1(
        outcome="failed",
        result={
            "answer_id": "ans_550e8400-e29b-41d4-a716-446655440000",
            "answer_output": None,
        },
        reason="codex_process_failed",
        committed_answer_locator=_committed_locator_v1(),
        orphan_quarantined_count=2,
        orphan_recovered_count=3,
        orphan_recovery_failed_count=4,
        orphan_target_conflict_count=5,
    )

    diagnostics = commands._knowledge_ask_diagnostics_v1(report)

    assert diagnostics == [
        {"code": "knowledge.ask.codex_process_failed.v1", "context": {}},
        {
            "code": "knowledge.ask.orphan_quarantined.v1",
            "context": {"count": 2},
        },
        {
            "code": "knowledge.ask.orphan_recovered.v1",
            "context": {"count": 3},
        },
        {
            "code": "knowledge.ask.orphan_recovery_failed.v1",
            "context": {"count": 4},
        },
        {
            "code": "knowledge.ask.orphan_target_conflict.v1",
            "context": {"count": 5},
        },
    ]
    human = commands._knowledge_ask_human_buffer_v1(
        report,
        answer_markdown_bytes=None,
    ).decode("utf-8")
    assert "提示：发现 2 个无法安全恢复的历史 Answer staging，已原地逻辑隔离\n" in human
    assert "提示：已恢复并提交 3 个完整历史 Answer\n" in human
    assert (
        "提示：有 4 个历史 Answer 的确定性恢复提交失败，staging 已原地保留\n" in human
    )
    assert "提示：有 5 个历史 Answer 因同身份 target 已存在而未恢复\n" in human


def test_human_success_uses_the_committed_terminal_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = KnowledgeAskReportV1(
        outcome="succeeded",
        result={
            "answer_id": "ans_550e8400-e29b-41d4-a716-446655440000",
            "answer_output": {
                "answer_status": "insufficient_evidence",
                "answer_units": [],
                "insufficiency_reason": "no_matching_candidates",
                "qualification_units": [],
                "schema_version": "gezhi.answer_output.v1",
            },
        },
        reason=None,
        answer_markdown_bytes=b"writer-copy\n",
        committed_answer_locator=_committed_locator_v1(),
    )
    calls: list[KnowledgeAskReportV1] = []

    def read_committed(
        observed: KnowledgeAskReportV1,
    ) -> commands._HumanTerminalAnswerReadyV1:
        calls.append(observed)
        return commands._HumanTerminalAnswerReadyV1(
            answer_markdown_bytes=b"reader-copy\n",
            answer_markdown_text="reader-copy\n",
        )

    monkeypatch.setattr(
        commands,
        "_read_committed_answer_for_human_v1",
        read_committed,
        raising=False,
    )

    candidate = commands._prepare_knowledge_ask_presentation_v1(
        report,
        json_output=False,
        answer_markdown_bytes=report.answer_markdown_bytes,
    )

    assert calls == [report]
    assert candidate.disposition == "ready_bytes"
    assert type(candidate.buffer) is bytes
    payload = candidate.buffer
    assert payload.endswith(b"reader-copy\n")
    assert b"writer-copy" not in payload


def test_human_terminal_reader_rejection_forms_a_typed_no_output_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = KnowledgeAskReportV1(
        outcome="succeeded",
        result={
            "answer_id": "ans_550e8400-e29b-41d4-a716-446655440000",
            "answer_output": {
                "answer_status": "insufficient_evidence",
                "answer_units": [],
                "insufficiency_reason": "no_matching_candidates",
                "qualification_units": [],
                "schema_version": "gezhi.answer_output.v1",
            },
        },
        reason=None,
        answer_markdown_bytes=b"writer-copy\n",
        committed_answer_locator=_committed_locator_v1(),
    )
    monkeypatch.setattr(
        commands,
        "_read_committed_answer_for_human_v1",
        lambda _report: None,
    )

    candidate = commands._prepare_knowledge_ask_presentation_v1(
        report,
        json_output=False,
        answer_markdown_bytes=report.answer_markdown_bytes,
    )

    assert candidate.disposition == "no_output_presentation_failure"
    assert candidate.failure_kind == "human_terminal_answer_bytes_rejected"
    assert candidate.buffer is None
    assert candidate.byte_length is None
    assert candidate.json_output is False


def test_human_terminal_reader_rejection_exits_only_after_release_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _HardExit(BaseException):
        pass

    class _CancellationV1:
        def snapshot_v1(self) -> CancellationSnapshotV1:
            events.append("snapshot")
            return CancellationSnapshotV1(
                phase="accepting",
                generation=0,
                observed_monotonic_ns=None,
                accepted_in_flight=0,
                publication_ready=False,
                sealed_candidate_token=0,
            )

        def conditional_seal_v1(self, **_kwargs: int) -> bool:
            events.append("seal")
            return True

        def release_v1(self) -> None:
            events.append("release")

    def succeeded_report(
        _question: str,
        **_kwargs: object,
    ) -> KnowledgeAskReportV1:
        events.append("ask")
        return KnowledgeAskReportV1(
            outcome="succeeded",
            result={
                "answer_id": "ans_550e8400-e29b-41d4-a716-446655440000",
                "answer_output": {
                    "answer_status": "insufficient_evidence",
                    "answer_units": [],
                    "insufficiency_reason": "no_matching_candidates",
                    "qualification_units": [],
                    "schema_version": "gezhi.answer_output.v1",
                },
            },
            reason=None,
            answer_markdown_bytes=b"writer-copy\n",
            committed_answer_locator=_committed_locator_v1(),
        )

    def hard_exit(code: int) -> None:
        events.append(f"exit:{code}")
        raise _HardExit

    monkeypatch.setattr(
        commands,
        "activate_knowledge_ask_cancellation_v1",
        _CancellationV1,
    )
    monkeypatch.setattr(commands.KnowledgeAsksV1, "ask", succeeded_report)
    monkeypatch.setattr(
        commands,
        "_read_committed_answer_for_human_v1",
        lambda _report: None,
    )
    monkeypatch.setattr(
        commands,
        "write_knowledge_ask_human_buffer_v1",
        lambda _buffer: (_ for _ in ()).throw(
            AssertionError("no-output candidate must not write Human stdout")
        ),
    )
    monkeypatch.setattr(
        commands,
        "write_knowledge_ask_json_buffer_v1",
        lambda _buffer: (_ for _ in ()).throw(
            AssertionError("no-output candidate must not write JSON stdout")
        ),
    )
    monkeypatch.setattr(commands.os, "_exit", hard_exit)

    with pytest.raises(_HardExit):
        commands.run_ask(question="?", json_output=False, cli_patch=())

    assert events == ["ask", "snapshot", "seal", "release", "exit:1"]


def test_json_cap_failure_exits_only_after_release_without_starting_a_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _HardExit(BaseException):
        pass

    class _CancellationV1:
        def snapshot_v1(self) -> CancellationSnapshotV1:
            events.append("snapshot")
            return CancellationSnapshotV1(
                phase="accepting",
                generation=0,
                observed_monotonic_ns=None,
                accepted_in_flight=0,
                publication_ready=False,
                sealed_candidate_token=0,
            )

        def conditional_seal_v1(self, **_kwargs: int) -> bool:
            events.append("seal")
            return True

        def release_v1(self) -> None:
            events.append("release")

    def blocked_report(
        _question: str,
        **_kwargs: object,
    ) -> KnowledgeAskReportV1:
        events.append("ask")
        return KnowledgeAskReportV1(
            outcome="blocked",
            result=None,
            reason="invalid_question",
        )

    def hard_exit(code: int) -> None:
        events.append(f"exit:{code}")
        raise _HardExit

    monkeypatch.setattr(
        commands,
        "activate_knowledge_ask_cancellation_v1",
        _CancellationV1,
    )
    monkeypatch.setattr(commands.KnowledgeAsksV1, "ask", blocked_report)
    monkeypatch.setattr(commands, "_ASK_JSON_OUTPUT_CAP", 1)
    monkeypatch.setattr(
        commands,
        "write_knowledge_ask_json_buffer_v1",
        lambda _buffer: (_ for _ in ()).throw(
            AssertionError("no-output candidate must not start JSON stdout")
        ),
    )
    monkeypatch.setattr(
        commands,
        "write_knowledge_ask_human_buffer_v1",
        lambda _buffer: (_ for _ in ()).throw(
            AssertionError("no-output candidate must not start Human stdout")
        ),
    )
    monkeypatch.setattr(commands.os, "_exit", hard_exit)

    with pytest.raises(_HardExit):
        commands.run_ask(question="?", json_output=True, cli_patch=())

    assert events == ["ask", "snapshot", "seal", "release", "exit:1"]


def test_prepared_json_candidate_binds_the_complete_generation_and_payload() -> None:
    report = KnowledgeAskReportV1(
        outcome="blocked",
        result=None,
        reason="invalid_question",
    )

    unbound = commands._prepare_knowledge_ask_presentation_v1(
        report,
        json_output=True,
        answer_markdown_bytes=None,
    )
    candidate = commands._bind_knowledge_ask_presentation_v1(
        unbound,
        expected_generation=7,
        candidate_token=11,
    )

    assert candidate.expected_generation == 7
    assert candidate.candidate_token == 11
    assert candidate.byte_length == len(candidate.buffer)
    assert candidate.envelope is not None


def test_json_cap_failure_forms_a_sealable_no_output_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = KnowledgeAskReportV1(
        outcome="blocked",
        result=None,
        reason="invalid_question",
    )
    monkeypatch.setattr(commands, "_ASK_JSON_OUTPUT_CAP", 1)

    candidate = commands._prepare_knowledge_ask_presentation_v1(
        report,
        json_output=True,
        answer_markdown_bytes=None,
    )

    assert candidate.disposition == "no_output_presentation_failure"
    assert candidate.failure_kind == "stdout_cap_exceeded"
    assert candidate.envelope is not None
    assert candidate.buffer is None
    assert candidate.byte_length is None
    assert candidate.json_output is True


def test_json_canonical_serialization_failure_forms_a_no_output_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = KnowledgeAskReportV1(
        outcome="blocked",
        result=None,
        reason="invalid_question",
    )
    monkeypatch.setattr(
        commands.json,
        "dumps",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("forced canonical serialization failure")
        ),
    )

    candidate = commands._prepare_knowledge_ask_presentation_v1(
        report,
        json_output=True,
        answer_markdown_bytes=None,
    )

    assert candidate.disposition == "no_output_presentation_failure"
    assert candidate.failure_kind == "canonical_serialization_failed"
    assert candidate.envelope is not None
    assert candidate.buffer is None
    assert candidate.byte_length is None


def test_json_unknown_serialization_fault_escapes_without_a_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = KnowledgeAskReportV1(
        outcome="blocked",
        result=None,
        reason="invalid_question",
    )
    monkeypatch.setattr(
        commands.json,
        "dumps",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("outside typed serialization seam")
        ),
    )

    with pytest.raises(RuntimeError, match="outside typed serialization seam"):
        commands._prepare_knowledge_ask_presentation_v1(
            report,
            json_output=True,
            answer_markdown_bytes=None,
        )


@pytest.mark.parametrize(
    ("boundary", "expected_kind"),
    (
        ("renderer", "human_semantic_render_rejected"),
        ("encode", "human_utf8_encode_failed"),
        ("bytes", "human_semantic_bytes_rejected"),
        ("cap", "human_semantic_bytes_too_large"),
    ),
)
def test_human_typed_pre_io_rejections_form_no_output_candidates(
    boundary: str,
    expected_kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = KnowledgeAskReportV1(
        outcome="blocked",
        result=None,
        reason="invalid_question",
    )
    if boundary == "renderer":
        monkeypatch.setattr(
            commands,
            "_render_knowledge_ask_human_text_v1",
            lambda *_args, **_kwargs: commands._HumanSemanticTextRejectedV1(),
            raising=False,
        )
    elif boundary == "encode":
        monkeypatch.setattr(
            commands,
            "_render_knowledge_ask_human_text_v1",
            lambda *_args, **_kwargs: commands._HumanSemanticTextReadyV1(text="\ud800"),
            raising=False,
        )
    elif boundary == "bytes":
        monkeypatch.setattr(
            commands,
            "_validate_knowledge_ask_human_bytes_v1",
            lambda *_args, **_kwargs: commands._HumanSemanticBytesRejectedV1(),
            raising=False,
        )
    else:
        monkeypatch.setattr(commands, "_ASK_HUMAN_OUTPUT_CAP", 1)

    candidate = commands._prepare_knowledge_ask_presentation_v1(
        report,
        json_output=False,
        answer_markdown_bytes=None,
    )

    assert candidate.disposition == "no_output_presentation_failure"
    assert candidate.failure_kind == expected_kind
    assert candidate.envelope is None
    assert candidate.buffer is None
    assert candidate.byte_length is None
    assert candidate.json_output is False


def test_human_unknown_renderer_fault_escapes_without_a_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = KnowledgeAskReportV1(
        outcome="blocked",
        result=None,
        reason="invalid_question",
    )
    monkeypatch.setattr(
        commands,
        "_render_knowledge_ask_human_text_v1",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("outside typed Human renderer seam")
        ),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="outside typed Human renderer seam"):
        commands._prepare_knowledge_ask_presentation_v1(
            report,
            json_output=False,
            answer_markdown_bytes=None,
        )


@pytest.mark.parametrize("json_output", (False, True))
def test_unrepresentable_diagnostic_projection_blocks_both_presenters(
    json_output: bool,
) -> None:
    report = replace(
        _failed_overflow_report_v1(),
        orphan_recovered_count=9_223_372_036_854_775_808,
    )

    candidate = commands._prepare_knowledge_ask_presentation_v1(
        report,
        json_output=json_output,
        answer_markdown_bytes=None,
    )

    assert candidate.disposition == "no_output_presentation_failure"
    assert candidate.failure_kind == "diagnostic_projection_unrepresentable"
    assert candidate.diagnostics is None
    assert candidate.envelope is None
    assert candidate.buffer is None
    assert candidate.byte_length is None
    assert candidate.json_output is json_output


def test_unclassified_presentation_failure_does_not_seal_or_hard_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CancellationV1:
        def snapshot_v1(self) -> CancellationSnapshotV1:
            return CancellationSnapshotV1(
                phase="accepting",
                generation=0,
                observed_monotonic_ns=None,
                accepted_in_flight=0,
                publication_ready=False,
                sealed_candidate_token=0,
            )

        def conditional_seal_v1(self, **_kwargs: int) -> bool:
            raise AssertionError("presentation failure must not seal")

        def release_v1(self) -> None:
            raise AssertionError("presentation failure must not release")

    def blocked_report(
        _question: str,
        **_kwargs: object,
    ) -> KnowledgeAskReportV1:
        return KnowledgeAskReportV1(
            outcome="blocked",
            result=None,
            reason="invalid_question",
        )

    def fail_presentation(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("forced presentation failure")

    hard_exits: list[int] = []
    monkeypatch.setattr(
        commands,
        "activate_knowledge_ask_cancellation_v1",
        _CancellationV1,
    )
    monkeypatch.setattr(commands.KnowledgeAsksV1, "ask", blocked_report)
    monkeypatch.setattr(
        commands,
        "_prepare_knowledge_ask_presentation_v1",
        fail_presentation,
    )
    monkeypatch.setattr(commands.os, "_exit", hard_exits.append)

    with pytest.raises(RuntimeError, match="forced presentation failure"):
        commands.run_ask(question="?", json_output=True, cli_patch=())

    assert hard_exits == []


def test_command_seals_only_after_the_domain_resources_have_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    domain_resources_owned = True

    class _CancellationV1:
        phase = "accepting"
        sealed_token = 0

        def snapshot_v1(self) -> CancellationSnapshotV1:
            assert domain_resources_owned is False
            return CancellationSnapshotV1(
                phase=self.phase,  # type: ignore[arg-type]
                generation=0,
                observed_monotonic_ns=None,
                accepted_in_flight=0,
                publication_ready=False,
                sealed_candidate_token=self.sealed_token,
            )

        def conditional_seal_v1(
            self,
            *,
            expected_generation: int,
            candidate_token: int,
        ) -> bool:
            assert domain_resources_owned is False
            assert expected_generation == 0
            self.phase = "sealed"
            self.sealed_token = candidate_token
            return True

        def release_v1(self) -> None:
            assert domain_resources_owned is False
            self.phase = "released"

    bridge = _CancellationV1()

    def ask_after_resources_return(
        _question: str,
        **kwargs: object,
    ) -> KnowledgeAskReportV1:
        nonlocal domain_resources_owned
        assert "report_sealer" not in kwargs
        domain_resources_owned = False
        return KnowledgeAskReportV1(
            outcome="blocked",
            result=None,
            reason="invalid_question",
        )

    monkeypatch.setattr(
        commands,
        "activate_knowledge_ask_cancellation_v1",
        lambda: bridge,
    )
    monkeypatch.setattr(commands.KnowledgeAsksV1, "ask", ask_after_resources_return)
    written: list[bytes] = []
    monkeypatch.setattr(
        commands,
        "write_knowledge_ask_json_buffer_v1",
        written.append,
    )

    assert commands.run_ask(question="?", json_output=True, cli_patch=()) == 2
    assert len(written) == 1
    assert bridge.phase == "released"


def test_human_presentation_does_not_inherit_the_json_binary_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CancellationV1:
        def snapshot_v1(self) -> CancellationSnapshotV1:
            return CancellationSnapshotV1(
                phase="accepting",
                generation=0,
                observed_monotonic_ns=None,
                accepted_in_flight=0,
                publication_ready=False,
                sealed_candidate_token=0,
            )

        def conditional_seal_v1(self, **_kwargs: int) -> bool:
            return True

        def release_v1(self) -> None:
            return None

    def blocked_report(
        _question: str,
        **_kwargs: object,
    ) -> KnowledgeAskReportV1:
        return KnowledgeAskReportV1(
            outcome="blocked",
            result=None,
            reason="invalid_question",
        )

    json_writes: list[bytes] = []
    human_writes: list[bytes] = []
    monkeypatch.setattr(
        commands,
        "activate_knowledge_ask_cancellation_v1",
        _CancellationV1,
    )
    monkeypatch.setattr(commands.KnowledgeAsksV1, "ask", blocked_report)
    monkeypatch.setattr(
        commands,
        "write_binary_buffer_v1",
        lambda buffer, **_kwargs: json_writes.append(buffer),
    )
    monkeypatch.setattr(
        commands,
        "write_knowledge_ask_human_buffer_v1",
        human_writes.append,
        raising=False,
    )

    assert commands.run_ask(question="?", json_output=False, cli_patch=()) == 2
    assert json_writes == []
    assert len(human_writes) == 1


def test_json_presentation_uses_the_dedicated_fd1_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CancellationV1:
        def snapshot_v1(self) -> CancellationSnapshotV1:
            return CancellationSnapshotV1(
                phase="accepting",
                generation=0,
                observed_monotonic_ns=None,
                accepted_in_flight=0,
                publication_ready=False,
                sealed_candidate_token=0,
            )

        def conditional_seal_v1(self, **_kwargs: int) -> bool:
            return True

        def release_v1(self) -> None:
            return None

    def blocked_report(
        _question: str,
        **_kwargs: object,
    ) -> KnowledgeAskReportV1:
        return KnowledgeAskReportV1(
            outcome="blocked",
            result=None,
            reason="invalid_question",
        )

    generic_writes: list[bytes] = []
    json_writes: list[bytes] = []
    monkeypatch.setattr(
        commands,
        "activate_knowledge_ask_cancellation_v1",
        _CancellationV1,
    )
    monkeypatch.setattr(commands.KnowledgeAsksV1, "ask", blocked_report)
    monkeypatch.setattr(
        commands,
        "write_binary_buffer_v1",
        lambda buffer, **_kwargs: generic_writes.append(buffer),
    )
    monkeypatch.setattr(
        commands,
        "write_knowledge_ask_json_buffer_v1",
        json_writes.append,
        raising=False,
    )

    assert commands.run_ask(question="?", json_output=True, cli_patch=()) == 2
    assert generic_writes == []
    assert len(json_writes) == 1


def test_json_fd1_writer_advances_only_by_completed_short_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_calls: list[tuple[int, int]] = []
    writes: list[bytes] = []
    monkeypatch.setattr(
        presentation.msvcrt,
        "setmode",
        lambda fd, mode: setup_calls.append((fd, mode)),
    )

    def short_write(fd: int, value: memoryview) -> int:
        assert fd == 1
        writes.append(bytes(value))
        return min(2, len(value))

    monkeypatch.setattr(presentation.os, "write", short_write)

    presentation.write_knowledge_ask_json_buffer_v1(b"abcdef\n")

    assert setup_calls == [(1, presentation.os.O_BINARY)]
    assert writes == [b"abcdef\n", b"cdef\n", b"ef\n", b"\n"]


@pytest.mark.parametrize("invalid_count", (True, None, 0, -1, 5))
def test_json_fd1_writer_hard_exits_on_an_invalid_completed_count(
    invalid_count: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _HardExit(BaseException):
        pass

    monkeypatch.setattr(presentation.msvcrt, "setmode", lambda _fd, _mode: 0)
    monkeypatch.setattr(
        presentation.os,
        "write",
        lambda _fd, _value: invalid_count,
    )

    def hard_exit(code: int) -> None:
        assert code == 1
        raise _HardExit

    monkeypatch.setattr(presentation.os, "_exit", hard_exit)

    with pytest.raises(_HardExit):
        presentation.write_knowledge_ask_json_buffer_v1(b"abc\n")


def test_json_fd1_writer_distinguishes_io_from_other_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _HardExit(BaseException):
        pass

    monkeypatch.setattr(presentation.msvcrt, "setmode", lambda _fd, _mode: 0)

    def hard_exit(_code: int) -> None:
        raise _HardExit

    monkeypatch.setattr(presentation.os, "_exit", hard_exit)
    monkeypatch.setattr(
        presentation.os,
        "write",
        lambda _fd, _value: (_ for _ in ()).throw(BrokenPipeError()),
    )
    with pytest.raises(_HardExit):
        presentation.write_knowledge_ask_json_buffer_v1(b"abc\n")

    monkeypatch.setattr(
        presentation.os,
        "write",
        lambda _fd, _value: (_ for _ in ()).throw(RuntimeError("outside seam")),
    )
    with pytest.raises(RuntimeError, match="outside seam"):
        presentation.write_knowledge_ask_json_buffer_v1(b"abc\n")


def test_human_writer_does_not_translate_io_failure_to_hard_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hard_exits: list[int] = []
    monkeypatch.setattr(presentation.msvcrt, "setmode", lambda _fd, _mode: 0)
    monkeypatch.setattr(
        presentation.os,
        "write",
        lambda _fd, _value: (_ for _ in ()).throw(BrokenPipeError()),
    )
    monkeypatch.setattr(presentation.os, "_exit", hard_exits.append)

    with pytest.raises(BrokenPipeError):
        presentation.write_knowledge_ask_human_buffer_v1(b"human\n")

    assert hard_exits == []
