from __future__ import annotations

import pytest

from gezhi import _knowledge_commands as commands
from gezhi._knowledge_ask import KnowledgeAskReportV1
from gezhi._knowledge_cancellation import CancellationSnapshotV1
from gezhi._presentation import CliJsonOutputTooLargeV1


def _failed_overflow_report_v1() -> KnowledgeAskReportV1:
    return KnowledgeAskReportV1(
        outcome="failed",
        result={
            "answer_id": "ans_550e8400-e29b-41d4-a716-446655440000",
            "answer_output": None,
        },
        reason="codex_process_failed",
        capture_overflow_channels=("final_message",),
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


def test_json_cap_failure_remains_outside_the_t22_sealed_candidate_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = KnowledgeAskReportV1(
        outcome="blocked",
        result=None,
        reason="invalid_question",
    )
    monkeypatch.setattr(commands, "_ASK_JSON_OUTPUT_CAP", 1)

    with pytest.raises(CliJsonOutputTooLargeV1):
        commands._prepare_knowledge_ask_presentation_v1(
            report,
            json_output=True,
            answer_markdown_bytes=None,
        )


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
        "write_binary_buffer_v1",
        lambda buffer, **_kwargs: written.append(buffer),
    )

    assert commands.run_ask(question="?", json_output=True, cli_patch=()) == 2
    assert len(written) == 1
    assert bridge.phase == "released"
