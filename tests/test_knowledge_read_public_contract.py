from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Literal

import pytest
from launcher_support import run_both_launchers
from support.knowledge_handoff_factory_v1 import (
    SyntheticHandoffV1,
    accepted_handoff_v1,
    withdrawn_handoff_v1,
)
from support.reviewed_handoff_witness_v1 import (
    ACCEPT_CANDIDATES_V1,
    ACCEPT_MANIFEST_V1,
    CANDIDATE_ID_V1,
    HANDOFF_ID_ACCEPT_V1,
    WITHDRAW_CANDIDATES_V1,
    WITHDRAW_MANIFEST_V1,
)


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


def _frozen_human_witness_v1(name: str) -> bytes:
    contract = (
        Path(__file__).parents[1]
        / "docs"
        / "contracts"
        / "knowledge-read-diagnostics-v1.md"
    ).read_text(encoding="utf-8")
    marker = f"#### {name}\n\n```text\n"
    assert contract.count(marker) == 1
    body, separator, _remainder = contract.partition(marker)[2].partition("\n```")
    assert separator == "\n```"
    return (body + "\n").encode("utf-8")


def _diagnostic_json_line(
    command: str,
    outcome: str,
    reason: str,
) -> bytes:
    return _canonical_json_line(
        {
            "command": command,
            "diagnostics": [{"code": f"{command}.{reason}.v1", "context": {}}],
            "outcome": outcome,
            "result": None,
            "schema_version": "gezhi.cli_result.v1",
        }
    )


def _search_json_line(
    *,
    query: str,
    items: list[dict[str, object]],
) -> bytes:
    return _canonical_json_line(
        {
            "command": "knowledge.search",
            "diagnostics": [],
            "outcome": "succeeded",
            "result": {
                "candidate_count": len(items),
                "items": items,
                "query": query,
                "result_kind": "candidate_backed",
                "schema_version": "gezhi.knowledge_search_result.v1",
            },
            "schema_version": "gezhi.cli_result.v1",
        }
    )


def _apply_handoff(root: Path, handoff: SyntheticHandoffV1) -> object:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import ReviewedHandoffBytesV1

    return KnowledgeIntakeAdapterV1(str(root)).apply(
        ReviewedHandoffBytesV1(
            manifest_bytes=handoff.manifest_bytes,
            candidates_bytes=handoff.candidates_bytes,
        )
    )


def _search_item(candidate: dict[str, object], rank: int) -> dict[str, object]:
    return {
        "candidate": candidate,
        "governance": {
            "intake_status": "active",
            "promotion_status": "not_promoted",
            "review_status": "accepted",
        },
        "rank": rank,
    }


def _show_json_line(
    *,
    content_record: dict[str, object],
    content_manifest: bytes,
    content_candidates: bytes,
    status_manifest: bytes,
    status_candidates: bytes,
) -> bytes:
    status_record = json.loads(status_candidates)
    content_receipt = content_record["review_receipt"]
    status_receipt = status_record["review_receipt"]
    assert type(content_receipt) is dict
    assert type(status_receipt) is dict
    status_action = status_record["action"]
    governance = {
        "intake_status": "active" if status_action == "accept" else "withdrawn",
        "promotion_status": "not_promoted",
        "review_status": status_receipt["review_status"],
    }
    result = {
        "candidate": content_record["candidate"],
        "citation": content_record["citation"],
        "content_import": {
            "action": "accept",
            "candidates_sha256": hashlib.sha256(content_candidates).hexdigest(),
            "handoff_id": json.loads(content_manifest)["handoff_id"],
            "manifest_sha256": hashlib.sha256(content_manifest).hexdigest(),
            "review_revision": content_receipt["review_revision"],
        },
        "descriptor_snapshots": content_record["descriptor_snapshots"],
        "evidence_snapshots": content_record["evidence_snapshots"],
        "governance": governance,
        "result_kind": "candidate_backed",
        "schema_version": "gezhi.knowledge_show_result.v1",
        "status_import": {
            "action": status_action,
            "candidates_sha256": hashlib.sha256(status_candidates).hexdigest(),
            "handoff_id": json.loads(status_manifest)["handoff_id"],
            "manifest_sha256": hashlib.sha256(status_manifest).hexdigest(),
            "review_revision": status_receipt["review_revision"],
        },
    }
    return _canonical_json_line(
        {
            "command": "knowledge.show",
            "diagnostics": [],
            "outcome": "succeeded",
            "result": result,
            "schema_version": "gezhi.cli_result.v1",
        }
    )


@pytest.fixture
def empty_knowledge_read_root() -> Iterator[Path]:
    container = Path(r"E:\Gezhi\data")
    container.mkdir(parents=True, exist_ok=True)
    base = container / ("t19-" + uuid.uuid4().hex[:12])
    knowledge_root = base / "knowledge"
    knowledge_root.mkdir(parents=True)
    try:
        yield knowledge_root
    finally:
        resolved = base.resolve(strict=True)
        assert resolved.parent == container.resolve(strict=True)
        assert resolved.name.startswith("t19-")
        shutil.rmtree(resolved)


@pytest.fixture
def knowledge_read_root(empty_knowledge_read_root: Path) -> Path:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    intake = KnowledgeIntakeAdapterV1(str(empty_knowledge_read_root))
    assert intake.apply(
        ReviewedHandoffBytesV1(
            manifest_bytes=ACCEPT_MANIFEST_V1,
            candidates_bytes=ACCEPT_CANDIDATES_V1,
        )
    ) == IntakeAppliedV1("active", "applied")
    return empty_knowledge_read_root


def test_search_returns_an_active_candidate_through_both_launchers(
    knowledge_read_root: Path,
) -> None:
    candidate = json.loads(ACCEPT_CANDIDATES_V1)["candidate"]
    expected = _search_json_line(
        query="source term",
        items=[
            {
                "candidate": candidate,
                "governance": {
                    "intake_status": "active",
                    "promotion_status": "not_promoted",
                    "review_status": "accepted",
                },
                "rank": 1,
            }
        ],
    )

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "source term",
            "--json",
        )
    )

    for result in results:
        assert result.returncode == 0
        assert result.stdout == expected
        assert result.stderr == b""


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("   ", "invalid_query"),
        ("+#._/-", "invalid_query"),
        ("文", "invalid_query"),
        ("valid\u000bquery", "invalid_query"),
        ("a" * 2_001, "query_too_large"),
        (
            " ".join(f"atom{index:03d}" for index in range(129)),
            "query_too_complex",
        ),
    ],
)
def test_search_rejects_invalid_queries_before_root_io(
    knowledge_read_root: Path,
    query: str,
    reason: str,
) -> None:
    missing_root = knowledge_read_root.with_name("missing-knowledge-root")
    assert not missing_root.exists()

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(missing_root),
            "knowledge",
            "search",
            query,
            "--json",
        )
    )

    expected = _diagnostic_json_line("knowledge.search", "blocked", reason)
    for result in results:
        assert result.returncode == 2
        assert result.stdout == expected
        assert result.stderr == b""


@pytest.mark.parametrize("query", ["\x00text", "\ud800text"])
def test_search_query_scalar_failures_use_the_narrow_domain_seam(query: str) -> None:
    from gezhi._knowledge_registry import (
        SearchQueryInvalidV1,
        normalize_search_query_v1,
    )

    with pytest.raises(SearchQueryInvalidV1):
        normalize_search_query_v1(query)


def test_search_normalizes_query_without_exposing_fts_syntax(
    knowledge_read_root: Path,
) -> None:
    candidate = json.loads(ACCEPT_CANDIDATES_V1)["candidate"]
    expected = _search_json_line(
        query="source:term or candidate_search_unicode:term",
        items=[
            {
                "candidate": candidate,
                "governance": {
                    "intake_status": "active",
                    "promotion_status": "not_promoted",
                    "review_status": "accepted",
                },
                "rank": 1,
            }
        ],
    )

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "  ＳＯＵＲＣＥ：ＴＥＲＭ OR candidate_search_unicode:term  ",
            "--json",
        )
    )

    for result in results:
        assert result.returncode == 0
        assert result.stdout == expected
        assert result.stderr == b""


def test_search_supports_the_128_atom_boundary_and_empty_results(
    knowledge_read_root: Path,
) -> None:
    query = " ".join(f"term{index:03d}" for index in range(128))
    expected = _search_json_line(query=query, items=[])

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            query,
            "--json",
        ),
        timeout=30.0,
    )

    for result in results:
        assert result.returncode == 0
        assert result.stdout == expected
        assert result.stderr == b""


def test_search_uses_candidate_id_ties_and_returns_at_most_twelve(
    knowledge_read_root: Path,
) -> None:
    from gezhi._literature_review import IntakeAppliedV1

    handoffs = [
        accepted_handoff_v1(
            ordinal=index + 100,
            statement_text="stable tie",
            source_terms=["stable tie"],
        )
        for index in range(13)
    ]
    for handoff in handoffs:
        assert _apply_handoff(knowledge_read_root, handoff) == IntakeAppliedV1(
            "active",
            "applied",
        )
    expected_candidates = sorted(
        (handoff.candidate for handoff in handoffs),
        key=lambda candidate: str(candidate["candidate_id"]).encode("ascii"),
    )[:12]
    expected = _search_json_line(
        query="stable tie",
        items=[
            _search_item(candidate, rank)
            for rank, candidate in enumerate(expected_candidates, start=1)
        ],
    )

    first = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "stable tie",
            "--json",
        ),
        timeout=30.0,
    )
    second = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "stable tie",
            "--json",
        ),
        timeout=30.0,
    )

    for result in (*first, *second):
        assert result.returncode == 0
        assert result.stdout == expected
        assert result.stderr == b""


@pytest.mark.parametrize("review_status", ["rejected", "deferred"])
def test_withdrawn_candidates_leave_search_and_a_later_accept_restores_them(
    knowledge_read_root: Path,
    review_status: str,
) -> None:
    from gezhi._literature_review import IntakeAppliedV1

    accepted = accepted_handoff_v1(
        ordinal=900 if review_status == "rejected" else 901,
        statement_text="governance token",
        source_terms=["governance token"],
    )
    withdrawn = withdrawn_handoff_v1(
        accepted,
        review_revision=2,
        review_status=review_status,
    )
    reaccepted = accepted_handoff_v1(
        ordinal=900 if review_status == "rejected" else 901,
        statement_text="governance token",
        source_terms=["governance token"],
        review_revision=3,
    )

    assert _apply_handoff(knowledge_read_root, accepted) == IntakeAppliedV1(
        "active",
        "applied",
    )
    expected_active = _search_json_line(
        query="governance token",
        items=[_search_item(accepted.candidate, 1)],
    )
    active = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "governance token",
            "--json",
        )
    )
    assert all(result.stdout == expected_active for result in active)

    assert _apply_handoff(knowledge_read_root, withdrawn) == IntakeAppliedV1(
        "withdrawn",
        "applied",
    )
    expected_withdrawn = _search_json_line(query="governance token", items=[])
    after_withdraw = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "governance token",
            "--json",
        )
    )
    for result in after_withdraw:
        assert result.returncode == 0
        assert result.stdout == expected_withdrawn
        assert result.stderr == b""

    assert _apply_handoff(knowledge_read_root, reaccepted) == IntakeAppliedV1(
        "active",
        "applied",
    )
    after_reaccept = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "governance token",
            "--json",
        )
    )
    for result in after_reaccept:
        assert result.returncode == 0
        assert result.stdout == expected_active
        assert result.stderr == b""


def test_rrf_uses_exact_fraction_scores_and_ascii_candidate_ties() -> None:
    from gezhi._knowledge_read import _rank_candidates_v1

    assert _rank_candidates_v1(
        (
            ("cand_000000000000000000000001", 1),
            ("cand_000000000000000000000002", 2),
            ("cand_000000000000000000000003", 3),
        ),
        (
            ("cand_000000000000000000000003", 1),
            ("cand_000000000000000000000002", 2),
        ),
    ) == (
        "cand_000000000000000000000003",
        "cand_000000000000000000000002",
        "cand_000000000000000000000001",
    )
    assert _rank_candidates_v1(
        (
            ("cand_000000000000000000000002", 1),
            ("cand_000000000000000000000001", 2),
        ),
        (
            ("cand_000000000000000000000001", 1),
            ("cand_000000000000000000000002", 2),
        ),
    ) == (
        "cand_000000000000000000000001",
        "cand_000000000000000000000002",
    )


@pytest.mark.parametrize(
    ("statement_text", "query"),
    [
        ("位姿估计", "位姿"),
        ("机器人定位", "机器人定位"),
        ("SL calibration", "SL"),
    ],
)
def test_search_supports_unicode_only_and_dual_branch_queries(
    knowledge_read_root: Path,
    statement_text: str,
    query: str,
) -> None:
    from gezhi._literature_review import IntakeAppliedV1

    ordinal = {
        "位姿估计": 1_001,
        "机器人定位": 1_002,
        "SL calibration": 1_003,
    }[statement_text]
    handoff = accepted_handoff_v1(
        ordinal=ordinal,
        statement_text=statement_text,
        source_terms=[statement_text],
    )
    assert _apply_handoff(knowledge_read_root, handoff) == IntakeAppliedV1(
        "active",
        "applied",
    )
    expected = _search_json_line(
        query=query.casefold(),
        items=[_search_item(handoff.candidate, 1)],
    )

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            query,
            "--json",
        )
    )

    for result in results:
        assert result.returncode == 0
        assert result.stdout == expected
        assert result.stderr == b""


def test_search_human_empty_result_matches_the_frozen_bytes(
    knowledge_read_root: Path,
) -> None:
    expected = (
        "Knowledge 候选搜索\n"
        "治理说明：以下结果仅为已审核但尚未晋升的 Candidate Knowledge，"
        "不代表已晋升知识、已验证事实或自动蕴含证明。\n"
        "Candidate 数量 [candidate_count]: 0\n"
        "候选项 [items]: []\n"
        '规范查询 [query]: "没有结果"\n'
        '结果种类 [result_kind]: "candidate_backed"\n'
        '架构版本 [schema_version]: "gezhi.knowledge_search_result.v1"\n'
    ).encode()

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "没有结果",
        )
    )

    for result in results:
        assert result.returncode == 0
        assert result.stdout == expected
        assert result.stderr == b""


def test_search_human_one_result_matches_the_frozen_bytes(
    knowledge_read_root: Path,
) -> None:
    expected = (
        "Knowledge 候选搜索\n"
        "治理说明：以下结果仅为已审核但尚未晋升的 Candidate Knowledge，"
        "不代表已晋升知识、已验证事实或自动蕴含证明。\n"
        "Candidate 数量 [candidate_count]: 1\n"
        "候选项 [items]:\n"
        "  -\n"
        "    Candidate [candidate]:\n"
        '      Candidate ID [candidate_id]: "cand_3a421e895f79e2c167e2ef4b"\n'
        "      Payload [payload]:\n"
        '        Candidate 类型 [candidate_type]: "claim"\n'
        '        Canonical 内容 SHA-256 [canonical_content_sha256]: "'
        + "c"
        * 64
        + '"\n'
        "        Descriptor 引用 [descriptor_refs]: []\n"
        '        架构版本 [schema_version]: "gezhi.candidate_payload.v1"\n'
        '        Source ID [source_id]: "src_bbbbbbbbbbbbbbbbbbbbbbbb"\n'
        '        Source SHA-256 [source_sha256]: "' + "b" * 64 + '"\n'
        "        陈述 [statement]:\n"
        "          证据指针 [evidence_pointers]:\n"
        "            -\n"
        '              Block ID [block_id]: "block-001"\n'
        '              Canonical 内容 SHA-256 [canonical_content_sha256]: "'
        + "c"
        * 64
        + '"\n'
        '              架构版本 [schema_version]: "gezhi.evidence_pointer.v1"\n'
        "          审核风险标记 [risk_flags]: []\n"
        "          来源术语 [source_terms]:\n"
        '            - "source term"\n'
        '          支持类型 [support_kind]: "direct"\n'
        '          文本 [text]: "示例结论"\n'
        '        Work ID [work_id]: "wrk_123e4567-e89b-42d3-a456-426614174000"\n'
        '      Payload SHA-256 [payload_sha256]: "'
        "3a421e895f79e2c167e2ef4b4f42ece44839ca487c11e6659870904f268eabf1"
        '"\n'
        '      架构版本 [schema_version]: "gezhi.candidate_knowledge.v1"\n'
        "    治理 [governance]:\n"
        '      接收状态 [intake_status]: "active"\n'
        '      晋升状态 [promotion_status]: "not_promoted"\n'
        '      审核状态 [review_status]: "accepted"\n'
        "    排名 [rank]: 1\n"
        '规范查询 [query]: "source term"\n'
        '结果种类 [result_kind]: "candidate_backed"\n'
        '架构版本 [schema_version]: "gezhi.knowledge_search_result.v1"\n'
    ).encode("utf-8")

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "source term",
        )
    )

    for result in results:
        assert result.returncode == 0
        assert result.stdout == expected
        assert result.stderr == b""


def test_search_human_blocked_uses_only_the_fixed_stderr_line(
    knowledge_read_root: Path,
) -> None:
    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "++",
        )
    )

    for result in results:
        assert result.returncode == 2
        assert result.stdout == b""
        assert result.stderr == "搜索内容无效；请提供包含可检索文字的查询。\n".encode()


@pytest.mark.parametrize(
    ("configured_root", "reason"),
    [
        (r"relative-knowledge-root", "data_root_unsafe"),
        (r"E:\Gezhi\data\missing-t19-knowledge", "data_root_unavailable"),
        (r"E:\Gezhi\data\literature", "configuration_invalid"),
    ],
)
def test_search_reports_configuration_and_root_gates(
    configured_root: str,
    reason: str,
) -> None:
    results = run_both_launchers(
        (
            "--knowledge-data-root",
            configured_root,
            "knowledge",
            "search",
            "valid query",
            "--json",
        )
    )

    expected = _diagnostic_json_line("knowledge.search", "blocked", reason)
    for result in results:
        assert result.returncode == 2
        assert result.stdout == expected
        assert result.stderr == b""


def test_search_reports_a_missing_registry_as_temporarily_unavailable(
    empty_knowledge_read_root: Path,
) -> None:
    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(empty_knowledge_read_root),
            "knowledge",
            "search",
            "valid query",
            "--json",
        )
    )

    expected = _diagnostic_json_line(
        "knowledge.search",
        "blocked",
        "registry_unavailable",
    )
    for result in results:
        assert result.returncode == 2
        assert result.stdout == expected
        assert result.stderr == b""


@pytest.mark.parametrize("registry_generation", ["base", "future"])
def test_search_reports_unsupported_registry_or_projection_generations(
    empty_knowledge_read_root: Path,
    registry_generation: str,
) -> None:
    from gezhi._knowledge_intake import _APPLICATION_ID, _BASE_SCHEMA_STATEMENTS

    registry_path = empty_knowledge_read_root / "registry.sqlite3"
    with closing(sqlite3.connect(registry_path)) as registry:
        registry.execute("PRAGMA foreign_keys = ON")
        if registry_generation == "base":
            for statement in _BASE_SCHEMA_STATEMENTS:
                registry.execute(statement)
            registry.execute(
                "INSERT INTO registry_meta(singleton, schema_version, generation) "
                "VALUES (1, 'gezhi.candidate_registry.v1', 0)"
            )
            registry.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
            registry.execute("PRAGMA user_version = 1")
        else:
            registry.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
            registry.execute("PRAGMA user_version = 2")
        registry.commit()

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(empty_knowledge_read_root),
            "knowledge",
            "search",
            "valid query",
            "--json",
        )
    )

    expected = _diagnostic_json_line(
        "knowledge.search",
        "blocked",
        "registry_incompatible",
    )
    for result in results:
        assert result.returncode == 2
        assert result.stdout == expected
        assert result.stderr == b""


@pytest.mark.parametrize(
    ("tamper", "reason"),
    [
        ("projection_generation", "registry_corrupt"),
        ("projection_membership", "registry_corrupt"),
        ("candidate_json", "retrieval_materialization_failed"),
    ],
)
def test_search_fails_closed_for_corrupt_registry_and_candidate_state(
    knowledge_read_root: Path,
    tamper: str,
    reason: str,
) -> None:
    registry_path = knowledge_read_root / "registry.sqlite3"
    with closing(sqlite3.connect(registry_path)) as registry:
        if tamper == "projection_generation":
            registry.execute(
                "UPDATE registry_search_meta SET registry_generation = 999"
            )
        elif tamper == "projection_membership":
            registry.execute("DELETE FROM candidate_search_unicode")
        else:
            registry.execute(
                "UPDATE candidate_content SET candidate_json = ?", (b"{}",)
            )
        registry.commit()

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "source term",
            "--json",
        )
    )

    expected = _diagnostic_json_line("knowledge.search", "failed", reason)
    for result in results:
        assert result.returncode == 1
        assert result.stdout == expected
        assert result.stderr == b""


def test_search_is_business_state_read_only(
    knowledge_read_root: Path,
) -> None:
    before = {
        path.relative_to(knowledge_read_root).as_posix(): path.read_bytes()
        for path in knowledge_read_root.rglob("*")
        if path.is_file()
    }

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "source term",
            "--json",
        )
    )

    after = {
        path.relative_to(knowledge_read_root).as_posix(): path.read_bytes()
        for path in knowledge_read_root.rglob("*")
        if path.is_file()
    }
    assert all(result.returncode == 0 for result in results)
    assert after == before


def test_exact_intake_replay_upgrades_a_t18_base_registry_projection(
    knowledge_read_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    registry_path = knowledge_read_root / "registry.sqlite3"
    with closing(sqlite3.connect(registry_path)) as registry:
        registry.execute("DROP TABLE candidate_search_unicode")
        registry.execute("DROP TABLE candidate_search_trigram")
        registry.execute("DROP TABLE registry_search_meta")
        registry.commit()

    blocked = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "source term",
            "--json",
        )
    )
    assert all(result.returncode == 2 for result in blocked)
    assert all(
        result.stdout
        == _diagnostic_json_line(
            "knowledge.search",
            "blocked",
            "registry_incompatible",
        )
        for result in blocked
    )

    replay = KnowledgeIntakeAdapterV1(str(knowledge_read_root)).apply(
        ReviewedHandoffBytesV1(
            manifest_bytes=ACCEPT_MANIFEST_V1,
            candidates_bytes=ACCEPT_CANDIDATES_V1,
        )
    )
    assert replay == IntakeAppliedV1("active", "unchanged")
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        assert registry.execute("SELECT generation FROM registry_meta").fetchone() == (
            1,
        )
        assert registry.execute(
            "SELECT registry_generation FROM registry_search_meta"
        ).fetchone() == (1,)

    restored = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "search",
            "source term",
            "--json",
        )
    )
    assert all(result.returncode == 0 for result in restored)


def test_show_returns_active_candidate_and_evidence_through_both_launchers(
    knowledge_read_root: Path,
) -> None:
    expected = _show_json_line(
        content_record=json.loads(ACCEPT_CANDIDATES_V1),
        content_manifest=ACCEPT_MANIFEST_V1,
        content_candidates=ACCEPT_CANDIDATES_V1,
        status_manifest=ACCEPT_MANIFEST_V1,
        status_candidates=ACCEPT_CANDIDATES_V1,
    )

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "show",
            CANDIDATE_ID_V1,
            "--json",
        )
    )

    for result in results:
        assert result.returncode == 0
        assert result.stdout == expected
        assert result.stderr == b""


def test_show_human_active_matches_the_frozen_bytes(
    knowledge_read_root: Path,
) -> None:
    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "show",
            CANDIDATE_ID_V1,
        )
    )

    expected = _frozen_human_witness_v1("show：active")
    for result in results:
        assert result.returncode == 0
        assert result.stdout == expected
        assert result.stderr == b""


def test_show_returns_withdrawn_candidate_for_historical_audit(
    knowledge_read_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    assert KnowledgeIntakeAdapterV1(str(knowledge_read_root)).apply(
        ReviewedHandoffBytesV1(
            manifest_bytes=WITHDRAW_MANIFEST_V1,
            candidates_bytes=WITHDRAW_CANDIDATES_V1,
        )
    ) == IntakeAppliedV1("withdrawn", "applied")
    expected = _show_json_line(
        content_record=json.loads(ACCEPT_CANDIDATES_V1),
        content_manifest=ACCEPT_MANIFEST_V1,
        content_candidates=ACCEPT_CANDIDATES_V1,
        status_manifest=WITHDRAW_MANIFEST_V1,
        status_candidates=WITHDRAW_CANDIDATES_V1,
    )

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "show",
            CANDIDATE_ID_V1,
            "--json",
        )
    )

    for result in results:
        assert result.returncode == 0
        assert result.stdout == expected
        assert result.stderr == b""


def test_show_human_withdrawn_matches_the_frozen_bytes(
    knowledge_read_root: Path,
) -> None:
    from gezhi._knowledge_intake import KnowledgeIntakeAdapterV1
    from gezhi._literature_review import IntakeAppliedV1, ReviewedHandoffBytesV1

    assert KnowledgeIntakeAdapterV1(str(knowledge_read_root)).apply(
        ReviewedHandoffBytesV1(
            manifest_bytes=WITHDRAW_MANIFEST_V1,
            candidates_bytes=WITHDRAW_CANDIDATES_V1,
        )
    ) == IntakeAppliedV1("withdrawn", "applied")
    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "show",
            CANDIDATE_ID_V1,
        )
    )

    expected = _frozen_human_witness_v1("show：withdrawn/rejected")
    for result in results:
        assert result.returncode == 0
        assert result.stdout == expected
        assert result.stderr == b""


def test_show_rejects_invalid_candidate_id_before_root_io(
    knowledge_read_root: Path,
) -> None:
    missing_root = knowledge_read_root.with_name("missing-show-root")
    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(missing_root),
            "knowledge",
            "show",
            "CAND_3A421E895F79E2C167E2EF4B",
            "--json",
        )
    )

    expected = _diagnostic_json_line(
        "knowledge.show",
        "blocked",
        "invalid_candidate_id",
    )
    for result in results:
        assert result.returncode == 2
        assert result.stdout == expected
        assert result.stderr == b""


def test_show_reports_a_well_formed_missing_candidate(
    knowledge_read_root: Path,
) -> None:
    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "show",
            "cand_000000000000000000000000",
            "--json",
        )
    )

    expected = _diagnostic_json_line(
        "knowledge.show",
        "blocked",
        "candidate_not_found",
    )
    for result in results:
        assert result.returncode == 2
        assert result.stdout == expected
        assert result.stderr == b""


def test_show_human_blocked_uses_only_the_fixed_stderr_line(
    knowledge_read_root: Path,
) -> None:
    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "show",
            "cand_000000000000000000000000",
        )
    )

    for result in results:
        assert result.returncode == 2
        assert result.stdout == b""
        assert result.stderr == "没有找到该 Candidate。\n".encode()


def test_show_does_not_require_the_search_projection(
    knowledge_read_root: Path,
) -> None:
    registry_path = knowledge_read_root / "registry.sqlite3"
    with closing(sqlite3.connect(registry_path)) as registry:
        registry.execute("DROP TABLE candidate_search_unicode")
        registry.execute("DROP TABLE candidate_search_trigram")
        registry.execute("DROP TABLE registry_search_meta")
        registry.commit()

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "show",
            CANDIDATE_ID_V1,
            "--json",
        )
    )

    assert all(result.returncode == 0 for result in results)


def test_show_reaccept_uses_the_latest_accept_for_content_and_status(
    knowledge_read_root: Path,
) -> None:
    from gezhi._literature_review import IntakeAppliedV1

    accepted = accepted_handoff_v1(
        ordinal=1_500,
        statement_text="restored candidate",
        source_terms=["restored candidate"],
    )
    withdrawn = withdrawn_handoff_v1(
        accepted,
        review_revision=2,
        review_status="rejected",
    )
    reaccepted = accepted_handoff_v1(
        ordinal=1_500,
        statement_text="restored candidate",
        source_terms=["restored candidate"],
        review_revision=3,
    )
    cases: tuple[tuple[SyntheticHandoffV1, Literal["active", "withdrawn"]], ...] = (
        (accepted, "active"),
        (withdrawn, "withdrawn"),
        (reaccepted, "active"),
    )
    for handoff, expected_status in cases:
        assert _apply_handoff(knowledge_read_root, handoff) == IntakeAppliedV1(
            expected_status,
            "applied",
        )
    expected = _show_json_line(
        content_record=json.loads(reaccepted.candidates_bytes),
        content_manifest=reaccepted.manifest_bytes,
        content_candidates=reaccepted.candidates_bytes,
        status_manifest=reaccepted.manifest_bytes,
        status_candidates=reaccepted.candidates_bytes,
    )

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "show",
            accepted.candidate_id,
            "--json",
        )
    )

    for result in results:
        assert result.returncode == 0
        assert result.stdout == expected
        assert result.stderr == b""


def test_show_supports_a_deferred_withdrawal(
    knowledge_read_root: Path,
) -> None:
    from gezhi._literature_review import IntakeAppliedV1

    accepted = accepted_handoff_v1(
        ordinal=1_510,
        statement_text="deferred candidate",
        source_terms=["deferred candidate"],
    )
    deferred = withdrawn_handoff_v1(
        accepted,
        review_revision=2,
        review_status="deferred",
    )
    assert _apply_handoff(knowledge_read_root, accepted) == IntakeAppliedV1(
        "active",
        "applied",
    )
    assert _apply_handoff(knowledge_read_root, deferred) == IntakeAppliedV1(
        "withdrawn",
        "applied",
    )
    expected = _show_json_line(
        content_record=json.loads(accepted.candidates_bytes),
        content_manifest=accepted.manifest_bytes,
        content_candidates=accepted.candidates_bytes,
        status_manifest=deferred.manifest_bytes,
        status_candidates=deferred.candidates_bytes,
    )

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "show",
            accepted.candidate_id,
            "--json",
        )
    )
    for result in results:
        assert result.returncode == 0
        assert result.stdout == expected
        assert result.stderr == b""


@pytest.mark.parametrize(
    ("tamper", "reason"),
    [
        ("registry_generation", "registry_corrupt"),
        ("candidate_json", "candidate_corrupt"),
        ("import_bytes", "evidence_corrupt"),
    ],
)
def test_show_fails_closed_for_corrupt_registry_candidate_or_evidence(
    knowledge_read_root: Path,
    tamper: str,
    reason: str,
) -> None:
    if tamper == "import_bytes":
        candidates_path = (
            knowledge_read_root / "imports" / HANDOFF_ID_ACCEPT_V1 / "candidates.jsonl"
        )
        candidates_path.write_bytes(candidates_path.read_bytes() + b" ")
    else:
        with closing(
            sqlite3.connect(knowledge_read_root / "registry.sqlite3")
        ) as registry:
            if tamper == "registry_generation":
                registry.execute("UPDATE registry_meta SET generation = 999")
            else:
                registry.execute(
                    "UPDATE candidate_content SET candidate_json = ?",
                    (b"{}",),
                )
            registry.commit()

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "show",
            CANDIDATE_ID_V1,
            "--json",
        )
    )

    expected = _diagnostic_json_line("knowledge.show", "failed", reason)
    for result in results:
        assert result.returncode == 1
        assert result.stdout == expected
        assert result.stderr == b""


def test_show_is_business_state_read_only(
    knowledge_read_root: Path,
) -> None:
    before = {
        path.relative_to(knowledge_read_root).as_posix(): path.read_bytes()
        for path in knowledge_read_root.rglob("*")
        if path.is_file()
    }

    results = run_both_launchers(
        (
            "--knowledge-data-root",
            str(knowledge_read_root),
            "knowledge",
            "show",
            CANDIDATE_ID_V1,
            "--json",
        )
    )

    after = {
        path.relative_to(knowledge_read_root).as_posix(): path.read_bytes()
        for path in knowledge_read_root.rglob("*")
        if path.is_file()
    }
    assert all(result.returncode == 0 for result in results)
    assert after == before


@pytest.mark.parametrize("command", ["search", "show"])
def test_read_commands_distinguish_a_root_identity_failure(
    monkeypatch: pytest.MonkeyPatch,
    command: Literal["search", "show"],
) -> None:
    import gezhi._knowledge_read as knowledge_read
    from gezhi._windows_data_root import DataRootOpenErrorV1

    class _Configuration:
        knowledge_data_root = r"E:\Gezhi\data\identity-unavailable"

    monkeypatch.setattr(
        knowledge_read,
        "resolve_configuration_v1",
        lambda **_arguments: _Configuration(),
    )

    def identity_unavailable(_value: str) -> object:
        raise DataRootOpenErrorV1(
            "unavailable",
            cause="identity_unavailable",
        )

    monkeypatch.setattr(
        knowledge_read,
        "open_validated_data_root_v1",
        identity_unavailable,
    )
    report = (
        knowledge_read.KnowledgeReadsV1.search("valid query", cli_patch=())
        if command == "search"
        else knowledge_read.KnowledgeReadsV1.show(CANDIDATE_ID_V1, cli_patch=())
    )

    expected_command: Literal["knowledge.search", "knowledge.show"] = (
        "knowledge.search" if command == "search" else "knowledge.show"
    )
    assert report == knowledge_read.KnowledgeReadReportV1(
        command=expected_command,
        outcome="blocked",
        result=None,
        reason="data_root_identity_unavailable",
    )


def test_intake_builds_a_generation_bound_search_projection(
    knowledge_read_root: Path,
) -> None:
    from gezhi._knowledge_intake import _expected_schema_rows, _schema_rows

    registry_path = knowledge_read_root / "registry.sqlite3"
    with closing(
        sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    ) as registry:
        registry.execute("PRAGMA foreign_keys = ON")
        assert _schema_rows(registry) == _expected_schema_rows()
        assert registry.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert registry.execute("PRAGMA foreign_key_check").fetchall() == []
        assert registry.execute(
            "SELECT schema_version, registry_generation FROM registry_search_meta"
        ).fetchone() == ("gezhi.candidate_search_projection.v1", 1)
        assert registry.execute("SELECT generation FROM registry_meta").fetchone() == (
            1,
        )
