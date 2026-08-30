from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from gezhi import _knowledge_answerer as answerer
from gezhi._codex_child_process import (
    AttemptTerminalEvidenceV1,
    CancellationObservationV1,
    CaptureEvidenceV1,
)


@pytest.mark.parametrize(
    ("value", "question_block", "expected"),
    [
        ("# 标题", False, r"\# 标题"),
        ("&quest;", False, r"\&quest\;"),
        ("[x](y)", False, r"\[x\]\(y\)"),
        ("    # x", False, "&#32;&#32;&#32;&#32;\\# x"),
        ("甲\n乙", False, "甲&#10;乙"),
        ("甲\n乙", True, "甲\\\n乙"),
    ],
)
def test_plain_text_to_commonmark_vectors_are_exact(
    value: str,
    question_block: bool,
    expected: str,
) -> None:
    assert answerer._plain_text_v1(value, question_block=question_block) == expected


def test_citation_targets_use_fixed_bases_and_single_entity_decoding() -> None:
    assert answerer._doi_link_v1("10.1000/x&quest;y/z?") == (
        r"[DOI：10\.1000\/x\&quest\;y\/z\?]"
        "(<https://doi.org/10.1000/x&amp;quest;y%2Fz%3F>)"
    )
    assert answerer._arxiv_link_v1("hep-th/9901001v2") == (
        r"[arXiv：hep\-th\/9901001v2]"
        "(<https://arxiv.org/abs/hep-th/9901001v2>)"
    )


def test_answer_output_schema_is_closed_and_versioned() -> None:
    schema_bytes = answerer.answer_output_schema_bytes_v1()
    schema = json.loads(schema_bytes)

    assert schema_bytes.endswith(b"\n")
    assert schema["$id"] == ("https://gezhi.local/schemas/answer-output-v1.schema.json")
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "schema_version",
        "answer_status",
        "answer_units",
        "qualification_units",
        "insufficiency_reason",
    ]
    assert set(schema["properties"]) == set(schema["required"])


@dataclass(slots=True)
class _CancellationAfterSynthesisV1:
    calls: int = 0

    def observed_at_monotonic_ns(self) -> int | None:
        self.calls += 1
        return None if self.calls == 1 else 101


@dataclass(slots=True)
class _ControlledCancellationV1:
    observation: int | None = None

    def observed_at_monotonic_ns(self) -> int | None:
        return self.observation


def _run_synthetic_clean_attempt_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    cancellation: CancellationObservationV1,
    parse_answer_output: Callable[..., tuple[dict[str, object], bytes]],
) -> answerer.KnowledgeAnswererVerdictV1:
    package_root = tmp_path / "g1234567"
    package_root.mkdir()
    attempt_root = package_root / "attempt"
    attempt_root.mkdir()
    package = answerer._AttemptPackageV1(
        root=package_root,
        attempt_root=attempt_root,
        schema_path=package_root / "schema.json",
    )
    capture = CaptureEvidenceV1(
        path=tmp_path / "unused",
        byte_length=0,
        sha256="0" * 64,
        overflow=False,
    )
    evidence = AttemptTerminalEvidenceV1(
        role="knowledge_answerer_v1",
        attempt_ordinal=1,
        commit_wall_time="2026-08-30T20:00:00.000Z",
        commit_monotonic_ns=1,
        provider_started_monotonic_ns=2,
        attempt_deadline_monotonic_ns=50,
        shared_deadline_monotonic_ns=100,
        capture_ready_monotonic_ns=99,
        exit_code=0,
        mechanical_outcome="clean",
        events=capture,
        final_message=capture,
        create_process_calls=1,
        stop_calls=0,
        resource_ledger_count=0,
        lifecycle_facts=(),
    )
    frozen_attempt = answerer.KnowledgeAnswerAttemptV1({}, b"", b"{}\n")
    monkeypatch.setattr(answerer, "_question_value_v1", lambda _value: "question")
    monkeypatch.setattr(
        answerer,
        "_view_candidates_v1",
        lambda _value: {"cand_" + "0" * 24: object()},
    )
    monkeypatch.setattr(answerer, "_effective_prompt_v1", lambda *_args: b"prompt\n")
    monkeypatch.setattr(
        answerer,
        "answer_output_schema_bytes_v1",
        lambda: b"{}\n",
    )
    monkeypatch.setattr(
        answerer,
        "_source_environment_v1",
        lambda _value: {"TEMP": str(tmp_path)},
    )
    monkeypatch.setattr(answerer, "_prepare_role_invocation_v1", object)
    monkeypatch.setattr(answerer, "_create_attempt_package_v1", lambda _root: package)
    monkeypatch.setattr(answerer, "_remove_attempt_package_v1", lambda *_args: None)
    monkeypatch.setattr(answerer, "_run_role_attempt_v1", lambda _request: evidence)
    monkeypatch.setattr(
        answerer,
        "_attempt_from_evidence_v1",
        lambda _evidence, **_kwargs: (frozen_attempt, None, ()),
    )
    monkeypatch.setattr(
        answerer,
        "_parse_answer_output_v1",
        parse_answer_output,
    )

    retrieval = SimpleNamespace(measured_retrieval_view=SimpleNamespace(buffer=b"{}\n"))
    return answerer.answer_nonzero_v1(
        retrieval,  # type: ignore[arg-type]
        question_bytes=b"{}\n",
        knowledge_root=tmp_path,
        cancellation=cancellation,
    )


def test_clean_attempt_closes_shared_deadline_before_validation_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    verdict = _run_synthetic_clean_attempt_v1(
        monkeypatch,
        tmp_path,
        cancellation=_CancellationAfterSynthesisV1(),
        parse_answer_output=lambda *_args: pytest.fail(
            "validation started after cancellation"
        ),
    )

    assert verdict.status == "interrupted"
    assert verdict.error is None
    assert len(verdict.attempts) == 1


def test_validation_failure_yields_to_cancellation_observed_before_it_locks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cancellation = _ControlledCancellationV1()

    def fail_validation(*_args: object) -> tuple[dict[str, object], bytes]:
        cancellation.observation = 101
        raise ValueError("invalid final output")

    verdict = _run_synthetic_clean_attempt_v1(
        monkeypatch,
        tmp_path,
        cancellation=cancellation,
        parse_answer_output=fail_validation,
    )

    assert verdict.status == "interrupted"
    assert verdict.error is None
    assert len(verdict.attempts) == 1


def test_render_completion_locks_before_a_later_cancellation_observation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cancellation = _ControlledCancellationV1()

    def complete_render(*_args: object) -> bytes:
        cancellation.observation = answerer.time.monotonic_ns() + 1_000_000_000
        return b"# answer\n"

    monkeypatch.setattr(answerer, "_render_answer_markdown_v1", complete_render)
    verdict = _run_synthetic_clean_attempt_v1(
        monkeypatch,
        tmp_path,
        cancellation=cancellation,
        parse_answer_output=lambda *_args: ({}, b"{}\n"),
    )

    assert verdict.status == "succeeded"
    assert verdict.error is None
    assert verdict.answer_markdown_bytes == b"# answer\n"


def _patch_answerer_pre_attempt_inputs_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> SimpleNamespace:
    monkeypatch.setattr(answerer, "_question_value_v1", lambda _value: "question")
    monkeypatch.setattr(
        answerer,
        "_view_candidates_v1",
        lambda _value: {"cand_" + "0" * 24: object()},
    )
    monkeypatch.setattr(answerer, "_effective_prompt_v1", lambda *_args: b"prompt\n")
    monkeypatch.setattr(answerer, "answer_output_schema_bytes_v1", lambda: b"{}\n")
    monkeypatch.setattr(
        answerer,
        "_source_environment_v1",
        lambda _value: {"TEMP": str(tmp_path)},
    )
    monkeypatch.setattr(answerer, "_prepare_role_invocation_v1", object)
    return SimpleNamespace(measured_retrieval_view=SimpleNamespace(buffer=b"{}\n"))


def test_launched_attempt_evidence_failure_preserves_the_private_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    retrieval = _patch_answerer_pre_attempt_inputs_v1(monkeypatch, tmp_path)
    package_root = tmp_path / "g1234567"
    attempt_root = package_root / "attempt"
    attempt_root.mkdir(parents=True)
    package = answerer._AttemptPackageV1(
        root=package_root,
        attempt_root=attempt_root,
        schema_path=package_root / "schema.json",
    )
    missing_capture = CaptureEvidenceV1(
        path=attempt_root / "missing-capture",
        byte_length=0,
        sha256="0" * 64,
        overflow=False,
    )
    evidence = AttemptTerminalEvidenceV1(
        role="knowledge_answerer_v1",
        attempt_ordinal=1,
        commit_wall_time="2026-08-30T20:00:00.000Z",
        commit_monotonic_ns=1,
        provider_started_monotonic_ns=2,
        attempt_deadline_monotonic_ns=50,
        shared_deadline_monotonic_ns=100,
        capture_ready_monotonic_ns=49,
        exit_code=0,
        mechanical_outcome="clean",
        events=missing_capture,
        final_message=missing_capture,
        create_process_calls=1,
        stop_calls=0,
        resource_ledger_count=0,
        lifecycle_facts=(),
    )
    monkeypatch.setattr(answerer, "_create_attempt_package_v1", lambda _root: package)
    monkeypatch.setattr(answerer, "_run_role_attempt_v1", lambda _request: evidence)

    with pytest.raises(answerer.KnowledgeAnswererUnsafeHoldErrorV1):
        answerer.answer_nonzero_v1(
            retrieval,  # type: ignore[arg-type]
            question_bytes=b"{}\n",
            knowledge_root=tmp_path,
        )

    assert package_root.is_dir()
    assert package.schema_path.read_bytes() == b"{}\n"


def test_launched_timeout_without_shared_deadline_preserves_the_private_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    retrieval = _patch_answerer_pre_attempt_inputs_v1(monkeypatch, tmp_path)
    package_root = tmp_path / "g1234567"
    attempt_root = package_root / "attempt"
    attempt_root.mkdir(parents=True)
    package = answerer._AttemptPackageV1(
        root=package_root,
        attempt_root=attempt_root,
        schema_path=package_root / "schema.json",
    )
    capture = CaptureEvidenceV1(
        path=attempt_root / "unused-capture",
        byte_length=0,
        sha256="0" * 64,
        overflow=False,
    )
    evidence = AttemptTerminalEvidenceV1(
        role="knowledge_answerer_v1",
        attempt_ordinal=1,
        commit_wall_time="2026-08-30T20:00:00.000Z",
        commit_monotonic_ns=1,
        provider_started_monotonic_ns=2,
        attempt_deadline_monotonic_ns=50,
        shared_deadline_monotonic_ns=None,
        capture_ready_monotonic_ns=49,
        exit_code=1,
        mechanical_outcome="timeout",
        events=capture,
        final_message=capture,
        create_process_calls=1,
        stop_calls=1,
        resource_ledger_count=0,
        lifecycle_facts=(),
    )
    frozen_attempt = answerer.KnowledgeAnswerAttemptV1({}, b"", b"")
    monkeypatch.setattr(answerer, "_create_attempt_package_v1", lambda _root: package)
    monkeypatch.setattr(answerer, "_run_role_attempt_v1", lambda _request: evidence)
    monkeypatch.setattr(
        answerer,
        "_attempt_from_evidence_v1",
        lambda _evidence, **_kwargs: (frozen_attempt, "timeout", ()),
    )

    with pytest.raises(answerer.KnowledgeAnswererUnsafeHoldErrorV1):
        answerer.answer_nonzero_v1(
            retrieval,  # type: ignore[arg-type]
            question_bytes=b"{}\n",
            knowledge_root=tmp_path,
        )

    assert package_root.is_dir()
    assert package.schema_path.read_bytes() == b"{}\n"


def test_attempt_workspace_formation_failure_is_input_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    retrieval = _patch_answerer_pre_attempt_inputs_v1(monkeypatch, tmp_path)
    monkeypatch.setattr(
        answerer,
        "_create_attempt_package_v1",
        lambda _root: (_ for _ in ()).throw(
            answerer.KnowledgeAnswererInputInvalidV1("workspace rejected")
        ),
    )

    with pytest.raises(answerer.KnowledgeAnswererInputInvalidV1):
        answerer.answer_nonzero_v1(
            retrieval,  # type: ignore[arg-type]
            question_bytes=b"{}\n",
            knowledge_root=tmp_path,
        )
