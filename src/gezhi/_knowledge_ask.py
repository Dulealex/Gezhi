from __future__ import annotations

import os
import re
import subprocess
import time
import unicodedata
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal, TypeAlias, cast

from gezhi._answer_terminal import (
    AnswerAttemptPublishV1,
    AnswerCommitFailedV1,
    AnswerCommitIndeterminateV1,
    AnswerManifestFailedV1,
    AnswerOrphanScanFailedV1,
    AnswerPublishRequestV1,
    AnswerRootIntegrityLostV1,
    AnswerStagingFailedV1,
    AnswerTargetConflictV1,
    publish_answer_v1,
    scan_answer_staging_v1,
)
from gezhi._configuration import ConfigurationError, resolve_configuration_v1
from gezhi._knowledge_registry import (
    SearchQueryInvalidV1,
    SearchQueryTooComplexV1,
    SearchQueryTooLargeV1,
    SearchTextV1,
    canonical_json_bytes_v1,
    normalize_search_query_v1,
)
from gezhi._knowledge_retrieval import (
    DataRootIntegrityLostV1 as RetrievalDataRootIntegrityLostV1,
)
from gezhi._knowledge_retrieval import (
    KnowledgeRetrievalV1,
    NonZeroCandidatesV1,
    ZeroCandidateRetrievalV1,
)
from gezhi._windows_data_root import (
    DataRootOpenErrorV1,
    open_validated_data_root_v1,
)
from gezhi._windows_ownership import (
    WriterOwnershipLifecycleErrorV1,
    try_acquire_knowledge_answer_writer_v1,
)

KnowledgeAskOutcomeV1: TypeAlias = Literal[
    "succeeded",
    "blocked",
    "failed",
    "interrupted",
]
KnowledgeAskReportSealerV1: TypeAlias = Callable[
    ["KnowledgeAskReportV1", bytes | None], "KnowledgeAskReportV1"
]
_PROJECT_ROOT = Path(r"E:\Gezhi")
_GIT_REVISION = re.compile(rb"^[0-9a-f]{40}\r?\n?$")
_ANSWER_ID = re.compile(
    r"^ans_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_EFFECTIVE_CONFIG = {
    "attempt_timeout_ms": 1_800_000,
    "attempt_window_limit_ms": 5_700_000,
    "retry_backoff_schedule_ms": [10_000, 30_000],
    "schema_version": "gezhi.knowledge_answerer_effective_config.v1",
}
_INSUFFICIENT_EVIDENCE = (
    "本次检索未找到与该问题匹配、且当前可参与检索的已审核 Candidate Knowledge，"
    "因此无法形成候选知识支持的回答。"
)
_GOVERNANCE_DISCLOSURE = (
    "> 治理说明：本结果为候选知识支持（Candidate-backed）；可用内容仅来自已审核但尚未晋升的 "
    "Candidate Knowledge，不代表已晋升知识、已验证事实或自动蕴含证明。"
)


class _ProvenanceUnavailableV1(RuntimeError):
    pass


def _canonical_json_file_v1(value: object) -> bytes:
    return canonical_json_bytes_v1(value) + b"\n"


def _new_answer_id_v1() -> str:
    answer_id = f"ans_{uuid.uuid4()}"
    if _ANSWER_ID.fullmatch(answer_id) is None or len(answer_id.encode("ascii")) != 40:
        raise RuntimeError("Answer ID generator returned an invalid identity")
    return answer_id


def _question_assets_v1(
    normalized: NormalizedQuestionV1,
) -> tuple[bytes, bytes, bytes]:
    question_bytes = _canonical_json_file_v1(
        {
            "question": normalized.question,
            "schema_version": "gezhi.question.v1",
        }
    )
    retrieval_query_bytes = _canonical_json_file_v1(
        {
            "normalized_text": normalized.retrieval_query.normalized_text,
            "schema_version": "gezhi.retrieval_query.v1",
            "trigram_atoms": list(normalized.retrieval_query.trigram_atoms),
            "unicode61_atoms": list(normalized.retrieval_query.unicode61_atoms),
        }
    )
    return (
        _canonical_json_file_v1(_EFFECTIVE_CONFIG),
        question_bytes,
        retrieval_query_bytes,
    )


def _question_block_v1(value: str) -> str:
    punctuation = frozenset(chr(codepoint) for codepoint in range(0x21, 0x30)) | (
        frozenset(chr(codepoint) for codepoint in range(0x3A, 0x41))
        | frozenset(chr(codepoint) for codepoint in range(0x5B, 0x61))
        | frozenset(chr(codepoint) for codepoint in range(0x7B, 0x7F))
    )
    tokens: list[str] = []
    at_line_start = True
    for character in value:
        if character == "\n":
            tokens.append("\\\n")
            at_line_start = True
        elif character == " " and at_line_start:
            tokens.append("&#32;")
        elif character == "\t":
            tokens.append("&#9;")
        elif character == "\u2028":
            tokens.append("&#8232;")
            at_line_start = False
        elif character == "\u2029":
            tokens.append("&#8233;")
            at_line_start = False
        elif character in punctuation:
            tokens.append("\\" + character)
            at_line_start = False
        else:
            tokens.append(character)
            at_line_start = False
    return "".join(tokens)


def _zero_candidate_answer_output_v1() -> dict[str, object]:
    return {
        "answer_status": "insufficient_evidence",
        "answer_units": [],
        "insufficiency_reason": "no_matching_candidates",
        "qualification_units": [],
        "schema_version": "gezhi.answer_output.v1",
    }


def _zero_candidate_answer_markdown_v1(question: str) -> bytes:
    return (
        "# 回答\n\n"
        + _GOVERNANCE_DISCLOSURE
        + "\n\n## 问题\n\n"
        + _question_block_v1(question)
        + "\n\n## 证据不足\n\n"
        + _INSUFFICIENT_EVIDENCE
        + "\n"
    ).encode("utf-8")


def _utc_now_milliseconds_v1() -> str:
    now = datetime.now(UTC)
    return (
        f"{now.year:04d}-{now.month:02d}-{now.day:02d}T"
        f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}."
        f"{now.microsecond // 1_000:03d}Z"
    )


@dataclass(frozen=True, slots=True)
class KnowledgeAskReportV1:
    outcome: KnowledgeAskOutcomeV1
    result: dict[str, object] | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class NormalizedQuestionV1:
    question: str
    retrieval_query: SearchTextV1


def normalize_question_v1(raw_question: str) -> NormalizedQuestionV1:
    if type(raw_question) is not str:
        raise SearchQueryInvalidV1("Question must be a string")
    if "\x00" in raw_question or any(
        unicodedata.category(character) == "Cs" for character in raw_question
    ):
        raise SearchQueryInvalidV1("Question contains an invalid scalar")
    canonical = unicodedata.normalize(
        "NFC",
        raw_question.replace("\r\n", "\n").replace("\r", "\n"),
    )
    if any(
        unicodedata.category(character) == "Cc" and character not in {"\t", "\n"}
        for character in canonical
    ):
        raise SearchQueryInvalidV1("Question contains an invalid control character")
    canonical = canonical.strip()
    if not canonical:
        raise SearchQueryInvalidV1("Question is empty")
    try:
        byte_length = len(canonical.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise SearchQueryInvalidV1("Question cannot be encoded") from error
    if len(canonical) > 2_000 or byte_length > 8_192:
        raise SearchQueryTooLargeV1("Question exceeds its size limit")
    return NormalizedQuestionV1(
        question=canonical,
        retrieval_query=normalize_search_query_v1(canonical),
    )


def _run_git_v1(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            [
                "git",
                "-c",
                "safe.directory=E:/Gezhi",
                "-C",
                str(_PROJECT_ROOT),
                *arguments,
            ],
            capture_output=True,
            check=False,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise _ProvenanceUnavailableV1("Git query could not run") from error


def _git_provenance_v1() -> dict[str, object]:
    revision_query = _run_git_v1("rev-parse", "--verify", "HEAD")
    if revision_query.returncode == 0:
        if _GIT_REVISION.fullmatch(revision_query.stdout) is None:
            raise _ProvenanceUnavailableV1("Git revision is invalid")
        revision = revision_query.stdout.rstrip(b"\r\n").decode("ascii")
        status_query = _run_git_v1(
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        )
        if status_query.returncode != 0:
            raise _ProvenanceUnavailableV1("Git status is unavailable")
        state = "dirty" if status_query.stdout else "clean"
        git: dict[str, object] = {"revision": revision, "state": state}
    else:
        repository_query = _run_git_v1("rev-parse", "--is-inside-work-tree")
        head_query = _run_git_v1("symbolic-ref", "-q", "HEAD")
        if (
            repository_query.returncode != 0
            or repository_query.stdout not in {b"true\n", b"true\r\n"}
            or head_query.returncode != 0
            or not head_query.stdout.startswith(b"refs/heads/")
        ):
            raise _ProvenanceUnavailableV1("Git repository state is unavailable")
        git = {"revision": None, "state": "unborn"}
    return {
        "codex_cli_version": "0.146.0",
        "git": git,
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "role_version": "knowledge_answerer_v1",
    }


def validate_knowledge_ask_report_v1(report: KnowledgeAskReportV1) -> None:
    if type(report) is not KnowledgeAskReportV1:
        raise TypeError("Knowledge ask report type is invalid")
    if report.outcome not in {"succeeded", "blocked", "failed", "interrupted"}:
        raise ValueError("Knowledge ask outcome is invalid")
    if report.outcome == "succeeded":
        if type(report.result) is not dict or report.reason is not None:
            raise ValueError("Knowledge ask success presence is invalid")
        if set(report.result) != {"answer_id", "answer_output"}:
            raise ValueError("Knowledge ask success result is not closed")
        answer_id = report.result["answer_id"]
        if type(answer_id) is not str or _ANSWER_ID.fullmatch(answer_id) is None:
            raise ValueError("Knowledge ask result identity is invalid")
        answer_output = report.result["answer_output"]
        if type(answer_output) is not dict:
            raise ValueError("Knowledge ask AnswerOutput is invalid")
        try:
            from gezhi._knowledge_answerer import AnswerOutputV1

            AnswerOutputV1.model_validate(answer_output, strict=True)
        except (ImportError, ValueError) as error:
            raise ValueError("Knowledge ask AnswerOutput is invalid") from error
        return
    if type(report.reason) is not str:
        raise ValueError("Knowledge ask non-success presence is invalid")
    committed_reasons = {
        ("blocked", "retrieval_view_too_large"),
        ("blocked", "codex_runtime_unavailable"),
        ("failed", "codex_process_failed"),
        ("failed", "answer_output_invalid"),
        ("failed", "answer_rendering_failed"),
        ("failed", "citation_link_construction_failed"),
        ("failed", "synthesis_input_invalid"),
    }
    if report.result is not None:
        if (
            (report.outcome, report.reason) not in committed_reasons
            or type(report.result) is not dict
            or set(report.result) != {"answer_id", "answer_output"}
            or type(report.result["answer_id"]) is not str
            or _ANSWER_ID.fullmatch(report.result["answer_id"]) is None
            or report.result["answer_output"] is not None
        ):
            raise ValueError("Knowledge ask committed stop receipt is invalid")
        return
    if (report.outcome, report.reason) not in {
        ("blocked", "invalid_question"),
        ("blocked", "question_too_large"),
        ("blocked", "question_too_complex"),
        ("blocked", "configuration_invalid"),
        ("blocked", "configuration_incompatible"),
        ("blocked", "provenance_unavailable"),
        ("blocked", "data_root_unavailable"),
        ("blocked", "data_root_unsafe"),
        ("blocked", "data_root_identity_unavailable"),
        ("blocked", "answer_writer_busy"),
        ("blocked", "answer_writer_coordination_unavailable"),
        ("failed", "pre_answer_formation_failed"),
        ("failed", "data_root_integrity_lost"),
        ("failed", "orphan_scan_failed"),
        ("failed", "answer_staging_failed"),
        ("failed", "answer_manifest_failed"),
        ("failed", "answer_target_conflict"),
        ("failed", "answer_commit_failed"),
    }:
        raise ValueError("Knowledge ask reason/outcome matrix is invalid")


def _failed_report_v1(reason: str) -> KnowledgeAskReportV1:
    report = KnowledgeAskReportV1(
        outcome="failed",
        result=None,
        reason=reason,
    )
    validate_knowledge_ask_report_v1(report)
    return report


def _seal_knowledge_ask_report_v1(
    report: KnowledgeAskReportV1,
    answer_markdown_bytes: bytes | None,
    report_sealer: KnowledgeAskReportSealerV1 | None,
) -> KnowledgeAskReportV1:
    validate_knowledge_ask_report_v1(report)
    if report_sealer is None:
        return report
    sealed = report_sealer(report, answer_markdown_bytes)
    validate_knowledge_ask_report_v1(sealed)
    if sealed != report:
        raise ValueError("Knowledge ask presentation seal changed command facts")
    return sealed


class KnowledgeAsksV1:
    @staticmethod
    def ask(
        question: str,
        *,
        cli_patch: tuple[tuple[str, str], ...],
        environ: Mapping[str, str] | None = None,
        report_sealer: KnowledgeAskReportSealerV1 | None = None,
    ) -> KnowledgeAskReportV1:
        if type(question) is not str or type(cli_patch) is not tuple:
            raise TypeError("Knowledge ask input is invalid")
        try:
            normalized = normalize_question_v1(question)
        except SearchQueryInvalidV1:
            return KnowledgeAskReportV1(
                outcome="blocked",
                result=None,
                reason="invalid_question",
            )
        except SearchQueryTooLargeV1:
            return KnowledgeAskReportV1(
                outcome="blocked",
                result=None,
                reason="question_too_large",
            )
        except SearchQueryTooComplexV1:
            return KnowledgeAskReportV1(
                outcome="blocked",
                result=None,
                reason="question_too_complex",
            )
        try:
            configuration = resolve_configuration_v1(
                trusted_project_root=_PROJECT_ROOT,
                cli_patch=cli_patch,
                environ=os.environ.copy() if environ is None else environ,
            )
        except ConfigurationError as error:
            return KnowledgeAskReportV1(
                outcome="blocked",
                result=None,
                reason=error.cause,
            )
        try:
            effective_config_bytes, question_bytes, retrieval_query_bytes = (
                _question_assets_v1(normalized)
            )
        except (TypeError, ValueError, UnicodeError):
            return _failed_report_v1("pre_answer_formation_failed")
        try:
            provenance = _git_provenance_v1()
        except _ProvenanceUnavailableV1:
            return KnowledgeAskReportV1(
                outcome="blocked",
                result=None,
                reason="provenance_unavailable",
            )
        try:
            _canonical_json_file_v1(provenance)
        except (TypeError, ValueError, UnicodeError):
            return _failed_report_v1("pre_answer_formation_failed")
        try:
            root = open_validated_data_root_v1(configuration.knowledge_data_root)
        except DataRootOpenErrorV1 as error:
            if error.cause == "identity_unavailable":
                reason = "data_root_identity_unavailable"
            elif error.status == "unsafe":
                reason = "data_root_unsafe"
            else:
                reason = "data_root_unavailable"
            return KnowledgeAskReportV1(
                outcome="blocked",
                result=None,
                reason=reason,
            )
        with root:
            identity = root.inspection.identity
            if identity is None:
                return KnowledgeAskReportV1(
                    outcome="blocked",
                    result=None,
                    reason="data_root_identity_unavailable",
                )
            try:
                owner = try_acquire_knowledge_answer_writer_v1(identity)
            except WriterOwnershipLifecycleErrorV1:
                return KnowledgeAskReportV1(
                    outcome="blocked",
                    result=None,
                    reason="answer_writer_coordination_unavailable",
                )
            if owner is None:
                return KnowledgeAskReportV1(
                    outcome="blocked",
                    result=None,
                    reason="answer_writer_busy",
                )
            with owner:
                try:
                    staging_scan = scan_answer_staging_v1(root, owner)
                except AnswerRootIntegrityLostV1:
                    return _failed_report_v1("data_root_integrity_lost")
                except AnswerOrphanScanFailedV1:
                    return _failed_report_v1("orphan_scan_failed")
                if staging_scan.status != "empty":
                    # T23 supplies the complete orphan inspection/recovery protocol.
                    # Until then, an existing staging entry cannot be bypassed safely.
                    return _failed_report_v1("orphan_scan_failed")

                answer_id = _new_answer_id_v1()
                started_monotonic_ns = time.monotonic_ns()
                started_at = _utc_now_milliseconds_v1()
                try:
                    retrieval = KnowledgeRetrievalV1.retrieve(
                        root,
                        normalized.retrieval_query,
                        question_asset_sha256=sha256(question_bytes).hexdigest(),
                        retrieval_query_asset_sha256=sha256(
                            retrieval_query_bytes
                        ).hexdigest(),
                    )
                except RetrievalDataRootIntegrityLostV1:
                    return _failed_report_v1("data_root_integrity_lost")
                if isinstance(retrieval, NonZeroCandidatesV1):
                    retrieval_audit_bytes = retrieval.retrieval_audit_bytes
                    if retrieval.measured_retrieval_view.status == "too_large":
                        terminal_status: KnowledgeAskOutcomeV1 = "blocked"
                        terminal_error: dict[str, object] | None = {
                            "code": "retrieval_view_too_large",
                            "stage": "retrieval",
                        }
                        prompt_bytes = None
                        schema_bytes = None
                        attempts: tuple[AnswerAttemptPublishV1, ...] = ()
                        answer_output = None
                        answer_output_bytes = None
                        answer_markdown_bytes = None
                        retrieval_view_bytes = None
                        del retrieval
                    else:
                        from gezhi._knowledge_answerer import (
                            KnowledgeAnswererInputInvalidV1,
                            answer_nonzero_v1,
                        )

                        canonical_root = root.inspection.canonical_path
                        if canonical_root is None:
                            return _failed_report_v1("data_root_integrity_lost")
                        try:
                            answerer = answer_nonzero_v1(
                                retrieval,
                                question_bytes=question_bytes,
                                knowledge_root=Path(canonical_root),
                                environ=(
                                    os.environ.copy() if environ is None else environ
                                ),
                            )
                        except KnowledgeAnswererInputInvalidV1:
                            terminal_status = "failed"
                            terminal_error = {
                                "code": "synthesis_input_invalid",
                                "stage": "synthesis",
                            }
                            prompt_bytes = None
                            schema_bytes = None
                            attempts = ()
                            answer_output = None
                            answer_output_bytes = None
                            answer_markdown_bytes = None
                        else:
                            terminal_status = answerer.status
                            terminal_error = answerer.error
                            prompt_bytes = answerer.prompt_bytes
                            schema_bytes = answerer.schema_bytes
                            attempts = tuple(
                                AnswerAttemptPublishV1(
                                    record=attempt.record,
                                    events_bytes=attempt.events_bytes,
                                    final_message_bytes=attempt.final_message_bytes,
                                )
                                for attempt in answerer.attempts
                            )
                            answer_output = answerer.answer_output
                            answer_output_bytes = answerer.answer_output_bytes
                            answer_markdown_bytes = answerer.answer_markdown_bytes
                        retrieval_view_bytes = retrieval.measured_retrieval_view.buffer
                elif type(retrieval) is ZeroCandidateRetrievalV1:
                    terminal_status = "succeeded"
                    terminal_error = None
                    prompt_bytes = None
                    schema_bytes = None
                    attempts = ()
                    answer_output = _zero_candidate_answer_output_v1()
                    answer_output_bytes = _canonical_json_file_v1(answer_output)
                    answer_markdown_bytes = _zero_candidate_answer_markdown_v1(
                        normalized.question
                    )
                    retrieval_view_bytes = retrieval.measured_retrieval_view.buffer
                    retrieval_audit_bytes = retrieval.retrieval_audit_bytes
                else:
                    raise TypeError("Knowledge retrieval verdict type is invalid")
                request = AnswerPublishRequestV1(
                    answer_id=answer_id,
                    started_at=started_at,
                    started_monotonic_ns=started_monotonic_ns,
                    provenance=provenance,
                    effective_config_bytes=effective_config_bytes,
                    question_bytes=question_bytes,
                    retrieval_query_bytes=retrieval_query_bytes,
                    retrieval_audit_bytes=retrieval_audit_bytes,
                    retrieval_view_bytes=retrieval_view_bytes,
                    status=terminal_status,
                    error=terminal_error,
                    prompt_bytes=prompt_bytes,
                    schema_bytes=schema_bytes,
                    attempts=attempts,
                    answer_output_bytes=answer_output_bytes,
                    answer_markdown_bytes=answer_markdown_bytes,
                )
                try:
                    committed = publish_answer_v1(root, owner, request)
                except AnswerRootIntegrityLostV1:
                    return _failed_report_v1("data_root_integrity_lost")
                except AnswerStagingFailedV1:
                    return _failed_report_v1("answer_staging_failed")
                except AnswerManifestFailedV1:
                    return _failed_report_v1("answer_manifest_failed")
                except AnswerTargetConflictV1:
                    return _failed_report_v1("answer_target_conflict")
                except AnswerCommitFailedV1:
                    return _failed_report_v1("answer_commit_failed")
                except AnswerCommitIndeterminateV1:
                    raise
                if (
                    committed.answer_id != answer_id
                    or committed.status != terminal_status
                    or committed.error != terminal_error
                    or committed.answer_output_bytes != answer_output_bytes
                    or committed.answer_markdown_bytes != answer_markdown_bytes
                ):
                    raise RuntimeError("Committed Answer proof differs")
                if terminal_status == "succeeded":
                    if answer_output is None:
                        raise RuntimeError("Succeeded Answer output is absent")
                    report_reason: str | None = None
                    report_output: dict[str, object] | None = answer_output
                else:
                    if terminal_error is None:
                        report_reason = "user_interrupted"
                    else:
                        report_reason = cast(str, terminal_error["code"])
                    report_output = None
                report = KnowledgeAskReportV1(
                    outcome=terminal_status,
                    result={
                        "answer_id": committed.answer_id,
                        "answer_output": report_output,
                    },
                    reason=report_reason,
                )
                return _seal_knowledge_ask_report_v1(
                    report,
                    committed.answer_markdown_bytes,
                    report_sealer,
                )


__all__ = [
    "KnowledgeAskReportSealerV1",
    "KnowledgeAskReportV1",
    "KnowledgeAsksV1",
    "NormalizedQuestionV1",
    "normalize_question_v1",
    "validate_knowledge_ask_report_v1",
]
