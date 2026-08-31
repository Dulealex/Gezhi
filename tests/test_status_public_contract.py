from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from launcher_support import SOURCE_ROOT, run_both_launchers

WORK_ID = "wrk_123e4567-e89b-42d3-a456-426614174000"


def _runtime_site_customize(observation: dict[str, object]) -> str:
    return (
        "import sys\n"
        "import types\n\n"
        'runtime = types.ModuleType("gezhi._status_runtime")\n\n'
        "def observe_status(*, cli_patch, work_id):\n"
        f"    return {observation!r}\n\n"
        "runtime.observe_status = observe_status\n"
        'sys.modules["gezhi._status_runtime"] = runtime\n'
    )


def _canonical_receipt(value: dict[str, object]) -> bytes:
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


def _recovery(
    *,
    staging: int = 0,
    orphaned: int = 0,
    quarantined: int = 0,
    inconsistent: int = 0,
) -> dict[str, int]:
    return {
        "staging_count": staging,
        "orphaned_count": orphaned,
        "quarantined_count": quarantined,
        "inconsistent_count": inconsistent,
    }


def _partial_work_observation() -> dict[str, object]:
    return {
        "kind": "work",
        "work_id": WORK_ID,
        "literature": {
            "availability": "ready",
            "stages": [
                {"stage": "ingest", "status": "succeeded"},
                {"stage": "ocr", "status": "succeeded"},
                {"stage": "canonicalize", "status": "pending"},
                {"stage": "read", "status": "pending"},
                {"stage": "review", "status": "pending"},
                {"stage": "handoff", "status": "pending"},
                {"stage": "knowledge_import", "status": "pending"},
            ],
            "review_counts": {
                "pending": 0,
                "accepted": 0,
                "rejected": 0,
                "deferred": 0,
            },
            "handoff_status": "none",
            "recovery": _recovery(),
        },
        "knowledge": {
            "availability": "unavailable",
            "recovery": _recovery(),
        },
    }


def test_partial_work_receipts_match_the_frozen_contract_through_both_launchers(
    tmp_path: Path,
) -> None:
    observation = _partial_work_observation()
    (tmp_path / "sitecustomize.py").write_text(
        _runtime_site_customize(observation),
        encoding="utf-8",
    )
    literature = cast(dict[str, object], observation["literature"])
    expected_result = {
        "schema_version": "gezhi.status_result.v1",
        "scope": "work",
        "work_id": WORK_ID,
        "status": "partial",
        "literature": {
            key: value for key, value in literature.items() if key != "recovery"
        },
        "knowledge": {"availability": "unavailable"},
        "recovery": _recovery(),
        "next_action": "repair_data_root",
    }
    diagnostics = [
        {
            "code": "operations.status.data_root_unavailable.v1",
            "context": {"contexts": ["knowledge"]},
        },
        {
            "code": "operations.status.projection_incomplete.v1",
            "context": {"contexts": ["knowledge"]},
        },
    ]
    expected_json = _canonical_receipt(
        {
            "schema_version": "gezhi.cli_result.v1",
            "command": "status",
            "outcome": "succeeded",
            "result": expected_result,
            "diagnostics": diagnostics,
        }
    )
    expected_human = (
        "格致状态：部分可用\n"
        f"范围：Work {WORK_ID}\n"
        "Literature：就绪\n"
        "阶段：ingest=完成；ocr=完成；canonicalize=待处理；read=待处理；"
        "review=待处理；handoff=待处理；knowledge_import=待处理\n"
        "审核：待审核=0；已接受=0；已拒绝=0；已暂缓=0\n"
        "交接：无\n"
        "Knowledge：不可用\n"
        "恢复风险：暂存=0；待恢复=0；已隔离=0；不一致=0\n"
        "下一步：在外部恢复或修复 Data Root 后重试。\n"
        "问题：一个或多个 Data Root 不可用。\n"
        "建议：在外部恢复已配置目录及访问权限后重试；本命令不会创建目录。\n"
        "问题：状态报告只覆盖了可验证的部分 Context。\n"
        "建议：先恢复不可用的 Context，再运行相同 status 命令。\n"
    ).encode()

    json_results = run_both_launchers(
        ("status", WORK_ID, "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )
    human_results = run_both_launchers(
        ("status", WORK_ID),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )

    assert [
        (result.returncode, result.stdout, result.stderr) for result in json_results
    ] == [(0, expected_json, b""), (0, expected_json, b"")]
    assert [
        (result.returncode, result.stdout, result.stderr) for result in human_results
    ] == [(0, expected_human, b""), (0, expected_human, b"")]


def test_empty_overall_is_a_successful_read_with_add_work_next_action(
    tmp_path: Path,
) -> None:
    observation: dict[str, object] = {
        "kind": "overall",
        "literature": {
            "availability": "ready",
            "work_count": 0,
            "work_status_counts": [],
            "pending_review_count": 0,
            "pending_handoff_count": 0,
            "recovery": _recovery(),
        },
        "knowledge": {
            "availability": "ready",
            "active_candidate_count": 0,
            "withdrawn_candidate_count": 0,
            "answer_status_counts": [],
            "recovery": _recovery(),
        },
    }
    (tmp_path / "sitecustomize.py").write_text(
        _runtime_site_customize(observation),
        encoding="utf-8",
    )
    literature = cast(dict[str, object], observation["literature"])
    knowledge = cast(dict[str, object], observation["knowledge"])
    expected_result = {
        "schema_version": "gezhi.status_result.v1",
        "scope": "overall",
        "status": "empty",
        "literature": {
            key: value for key, value in literature.items() if key != "recovery"
        },
        "knowledge": {
            key: value for key, value in knowledge.items() if key != "recovery"
        },
        "recovery": _recovery(),
        "next_action": "add_work",
    }
    expected = _canonical_receipt(
        {
            "schema_version": "gezhi.cli_result.v1",
            "command": "status",
            "outcome": "succeeded",
            "result": expected_result,
            "diagnostics": [],
        }
    )

    results = run_both_launchers(
        ("status", "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [(0, expected, b""), (0, expected, b"")]


def test_integrity_recovery_never_reports_success(tmp_path: Path) -> None:
    observation: dict[str, object] = {
        "kind": "overall",
        "literature": {
            "availability": "ready",
            "work_count": 1,
            "work_status_counts": [{"status": "succeeded", "count": 1}],
            "pending_review_count": 0,
            "pending_handoff_count": 0,
            "recovery": _recovery(staging=1),
        },
        "knowledge": {
            "availability": "ready",
            "active_candidate_count": 1,
            "withdrawn_candidate_count": 0,
            "answer_status_counts": [{"status": "succeeded", "count": 1}],
            "recovery": _recovery(),
        },
    }
    (tmp_path / "sitecustomize.py").write_text(
        _runtime_site_customize(observation),
        encoding="utf-8",
    )

    results = run_both_launchers(
        ("status", "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )
    receipts = [json.loads(result.stdout) for result in results]

    assert [result.returncode for result in results] == [0, 0]
    assert all(result.stderr == b"" for result in results)
    assert receipts[0] == receipts[1]
    assert receipts[0]["outcome"] == "succeeded"
    assert receipts[0]["result"]["status"] == "staging"
    assert receipts[0]["result"]["next_action"] == "inspect_recovery"
    assert receipts[0]["diagnostics"] == [
        {
            "code": "operations.status.integrity_attention.v1",
            "context": {"kinds": ["staging"], "count": 1},
        }
    ]


def test_unequal_work_counts_fail_the_observation_instead_of_normalizing(
    tmp_path: Path,
) -> None:
    observation: dict[str, object] = {
        "kind": "overall",
        "literature": {
            "availability": "ready",
            "work_count": 2,
            "work_status_counts": [{"status": "pending", "count": 1}],
            "pending_review_count": 0,
            "pending_handoff_count": 0,
            "recovery": _recovery(),
        },
        "knowledge": {
            "availability": "ready",
            "active_candidate_count": 0,
            "withdrawn_candidate_count": 0,
            "answer_status_counts": [],
            "recovery": _recovery(),
        },
    }
    (tmp_path / "sitecustomize.py").write_text(
        _runtime_site_customize(observation),
        encoding="utf-8",
    )
    expected = _canonical_receipt(
        {
            "schema_version": "gezhi.cli_result.v1",
            "command": "status",
            "outcome": "failed",
            "result": None,
            "diagnostics": [
                {
                    "code": "operations.status.observation_failed.v1",
                    "context": {},
                }
            ],
        }
    )

    results = run_both_launchers(
        ("status", "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [(1, expected, b""), (1, expected, b"")]


def test_work_count_checked_add_overflow_fails_the_observation(
    tmp_path: Path,
) -> None:
    observation: dict[str, object] = {
        "kind": "overall",
        "literature": {
            "availability": "ready",
            "work_count": 9_223_372_036_854_775_807,
            "work_status_counts": [
                {"status": "pending", "count": 9_223_372_036_854_775_807},
                {"status": "failed", "count": 1},
            ],
            "pending_review_count": 0,
            "pending_handoff_count": 0,
            "recovery": _recovery(),
        },
        "knowledge": {
            "availability": "ready",
            "active_candidate_count": 0,
            "withdrawn_candidate_count": 0,
            "answer_status_counts": [],
            "recovery": _recovery(),
        },
    }
    (tmp_path / "sitecustomize.py").write_text(
        _runtime_site_customize(observation),
        encoding="utf-8",
    )

    results = run_both_launchers(
        ("status", "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )
    receipts = [json.loads(result.stdout) for result in results]

    assert [result.returncode for result in results] == [1, 1]
    assert all(result.stderr == b"" for result in results)
    assert receipts[0] == receipts[1]
    assert receipts[0]["outcome"] == "failed"
    assert receipts[0]["result"] is None
    assert receipts[0]["diagnostics"] == [
        {"code": "operations.status.observation_failed.v1", "context": {}}
    ]


def test_recovery_priority_and_diagnostic_order_are_closed(
    tmp_path: Path,
) -> None:
    observation: dict[str, object] = {
        "kind": "overall",
        "literature": {
            "availability": "ready",
            "work_count": 1,
            "work_status_counts": [{"status": "succeeded", "count": 1}],
            "pending_review_count": 0,
            "pending_handoff_count": 0,
            "recovery": _recovery(staging=1, orphaned=1),
        },
        "knowledge": {
            "availability": "ready",
            "active_candidate_count": 1,
            "withdrawn_candidate_count": 0,
            "answer_status_counts": [{"status": "succeeded", "count": 1}],
            "recovery": _recovery(quarantined=1, inconsistent=1),
        },
    }
    (tmp_path / "sitecustomize.py").write_text(
        _runtime_site_customize(observation),
        encoding="utf-8",
    )

    results = run_both_launchers(
        ("status", "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )
    receipts = [json.loads(result.stdout) for result in results]

    assert [result.returncode for result in results] == [0, 0]
    assert all(result.stderr == b"" for result in results)
    assert receipts[0] == receipts[1]
    assert receipts[0]["result"]["status"] == "inconsistent"
    assert receipts[0]["result"]["next_action"] == "inspect_recovery"
    assert receipts[0]["diagnostics"] == [
        {
            "code": "operations.status.integrity_attention.v1",
            "context": {
                "kinds": ["staging", "orphaned", "quarantined", "inconsistent"],
                "count": 4,
            },
        }
    ]


def test_historical_failed_answer_does_not_fail_the_status_invocation(
    tmp_path: Path,
) -> None:
    observation: dict[str, object] = {
        "kind": "overall",
        "literature": {
            "availability": "ready",
            "work_count": 0,
            "work_status_counts": [],
            "pending_review_count": 0,
            "pending_handoff_count": 0,
            "recovery": _recovery(),
        },
        "knowledge": {
            "availability": "ready",
            "active_candidate_count": 0,
            "withdrawn_candidate_count": 0,
            "answer_status_counts": [{"status": "failed", "count": 1}],
            "recovery": _recovery(),
        },
    }
    (tmp_path / "sitecustomize.py").write_text(
        _runtime_site_customize(observation),
        encoding="utf-8",
    )

    results = run_both_launchers(
        ("status", "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )
    receipts = [json.loads(result.stdout) for result in results]

    assert [result.returncode for result in results] == [0, 0]
    assert all(result.stderr == b"" for result in results)
    assert receipts[0] == receipts[1]
    assert receipts[0]["outcome"] == "succeeded"
    assert receipts[0]["result"]["status"] == "failed"
    assert receipts[0]["result"]["next_action"] == "inspect_work"


def test_no_result_human_receipt_uses_only_the_closed_diagnostic(
    tmp_path: Path,
) -> None:
    (tmp_path / "sitecustomize.py").write_text(
        _runtime_site_customize({"kind": "blocked", "reason": "invalid_work_id"}),
        encoding="utf-8",
    )
    expected = (
        "格致状态：受阻\n问题：Work ID 无效。\n建议：使用完整的小写 wrk_ UUIDv4。\n"
    ).encode()

    results = run_both_launchers(
        ("status", "invalid"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [(2, expected, b""), (2, expected, b"")]


def test_no_result_root_primary_keeps_the_other_proved_root_fact(
    tmp_path: Path,
) -> None:
    observation: dict[str, object] = {
        "kind": "blocked",
        "reason": "data_root_unsafe",
        "contexts": ["literature"],
        "supplemental": [
            {"reason": "data_root_unavailable", "contexts": ["knowledge"]}
        ],
    }
    (tmp_path / "sitecustomize.py").write_text(
        _runtime_site_customize(observation),
        encoding="utf-8",
    )

    results = run_both_launchers(
        ("status", "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )
    receipts = [json.loads(result.stdout) for result in results]

    assert [result.returncode for result in results] == [2, 2]
    assert all(result.stderr == b"" for result in results)
    assert receipts[0] == receipts[1]
    assert receipts[0]["diagnostics"] == [
        {
            "code": "operations.status.data_root_unsafe.v1",
            "context": {"contexts": ["literature"]},
        },
        {
            "code": "operations.status.data_root_unavailable.v1",
            "context": {"contexts": ["knowledge"]},
        },
    ]
