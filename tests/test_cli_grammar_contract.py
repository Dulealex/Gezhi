from __future__ import annotations

import json
from pathlib import Path

import pytest
from launcher_support import SOURCE_ROOT, run_both_launchers

PARSER_FAILED_STDERR = b"gezhi: error: invalid command line\r\n"


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(("not-a-command",), id="unknown-command"),
        pytest.param(("Doctor",), id="wrong-case"),
        pytest.param(("-h",), id="short-help"),
        pytest.param(("--version", "doctor"), id="combined-version"),
        pytest.param(("doctor", "--help", "--json"), id="combined-help"),
        pytest.param(("doctor", "--json", "--json"), id="repeated-flag"),
        pytest.param(("doctor", "--json=true"), id="flag-with-value"),
        pytest.param(
            ("doctor", "--literature-data-root", r"D:\L"),
            id="root-option-after-command",
        ),
        pytest.param(("literature", "review", "cand_1"), id="missing-action"),
        pytest.param(
            ("literature", "review", "cand_1", "--accept", "--reject"),
            id="conflicting-actions",
        ),
        pytest.param(("knowledge", "ask"), id="missing-question"),
        pytest.param(("knowledge", "ask", "q", "extra"), id="extra-question"),
        pytest.param(("--literature-data-root", r"D:\L"), id="root-without-command"),
        pytest.param(
            (
                "--literature-data-root",
                r"D:\L",
                "--literature-data-root=D:\\Other",
                "doctor",
            ),
            id="repeated-root-option",
        ),
        pytest.param(
            ("literature", "add", "p.pdf", "--doi=a", "--doi", "b"),
            id="repeated-value-option",
        ),
        pytest.param(("--data-root", r"D:\Data", "doctor"), id="generic-root"),
        pytest.param(("knowledge", "ask", "q", "--timeout", "1"), id="timeout"),
        pytest.param(
            ("literature", "review", "cand_1", "--accept", "--note", "x"),
            id="review-note",
        ),
        pytest.param(("--install-completion",), id="completion-option"),
        pytest.param(("help",), id="help-command"),
        pytest.param(("status", "--doi", "x"), id="wrong-leaf-option"),
        pytest.param(("--json", "doctor"), id="leaf-option-at-root"),
    ],
)
def test_invalid_grammar_has_one_fixed_two_launcher_receipt(
    arguments: tuple[str, ...],
) -> None:
    results = run_both_launchers(arguments)

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [
        (2, b"", PARSER_FAILED_STDERR),
        (2, b"", PARSER_FAILED_STDERR),
    ]


def test_root_and_namespace_help_expose_the_frozen_route_inventory() -> None:
    root_results = run_both_launchers(("--help",))
    literature_results = run_both_launchers(("literature", "--help"))
    knowledge_results = run_both_launchers(("knowledge", "--help"))

    for result in root_results:
        assert (result.returncode, result.stderr) == (0, b"")
        for token in (b"doctor", b"status", b"literature", b"knowledge"):
            assert token in result.stdout
    for result in literature_results:
        assert (result.returncode, result.stderr) == (0, b"")
        for token in (b"add", b"resume", b"review"):
            assert token in result.stdout
    for result in knowledge_results:
        assert (result.returncode, result.stderr) == (0, b"")
        for token in (b"search", b"show", b"ask"):
            assert token in result.stdout


ROOT_OVERRIDE_SITE_CUSTOMIZE = r'''
import sys
import types


runtime = types.ModuleType("gezhi._doctor_runtime")


def observe_doctor(*, cli_patch):
    assert cli_patch == (
        ("literature.data_root", r" D:\L "),
        ("knowledge.data_root", "--help"),
    )
    return (
        ("configuration", "ready", None),
        ("core_python", "ready", None),
        ("core_dependencies", "ready", None),
        ("literature_data_root", "ready", None),
        ("knowledge_data_root", "ready", None),
        ("ocr_runtime", "ready", None),
        ("codex_runtime", "ready", None),
    )


runtime.observe_doctor = observe_doctor
sys.modules["gezhi._doctor_runtime"] = runtime
'''


def test_root_overrides_reach_doctor_as_exact_raw_strings(tmp_path: Path) -> None:
    (tmp_path / "sitecustomize.py").write_text(
        ROOT_OVERRIDE_SITE_CUSTOMIZE,
        encoding="utf-8",
    )

    results = run_both_launchers(
        (
            "--literature-data-root",
            r" D:\L ",
            "--knowledge-data-root",
            "--help",
            "doctor",
            "--json",
        ),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )

    for result in results:
        assert (result.returncode, result.stderr) == (0, b"")
        assert json.loads(result.stdout) == {
            "schema_version": "gezhi.cli_result.v1",
            "command": "doctor",
            "outcome": "succeeded",
            "result": {
                "schema_version": "gezhi.doctor_result.v1",
                "overall_status": "ready",
                "checks": [
                    {"id": "configuration", "status": "ready"},
                    {"id": "core_python", "status": "ready"},
                    {"id": "core_dependencies", "status": "ready"},
                    {"id": "literature_data_root", "status": "ready"},
                    {"id": "knowledge_data_root", "status": "ready"},
                    {"id": "ocr_runtime", "status": "ready"},
                    {"id": "codex_runtime", "status": "ready"},
                ],
            },
            "diagnostics": [],
        }
