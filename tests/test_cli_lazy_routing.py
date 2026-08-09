from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from launcher_support import SOURCE_ROOT, run_both_launchers

FAKE_ADAPTERS = r'''
import json
import sys
import types


def emit(route, values):
    sys.stdout.buffer.write(
        json.dumps(
            {"route": route, "values": values},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
    )
    return 0


operations = types.ModuleType("gezhi._operations")
operations.run_doctor = lambda **values: emit("doctor", values)
operations.run_status = lambda **values: emit("status", values)
sys.modules["gezhi._operations"] = operations

literature = types.ModuleType("gezhi._literature_commands")
literature.run_add = lambda **values: emit("literature.add", values)
literature.run_resume = lambda **values: emit("literature.resume", values)
literature.run_review = lambda **values: emit("literature.review", values)
sys.modules["gezhi._literature_commands"] = literature

knowledge = types.ModuleType("gezhi._knowledge_commands")
knowledge.run_search = lambda **values: emit("knowledge.search", values)
knowledge.run_show = lambda **values: emit("knowledge.show", values)
knowledge.run_ask = lambda **values: emit("knowledge.ask", values)
sys.modules["gezhi._knowledge_commands"] = knowledge
'''


@pytest.mark.parametrize(
    ("suffix", "route", "expected_values"),
    [
        (
            ("doctor", "--json"),
            "doctor",
            {"json_output": True},
        ),
        (
            ("status", "--", "--json"),
            "status",
            {"work_id": "--json", "json_output": False},
        ),
        (
            (
                "literature",
                "add",
                "raw.pdf",
                "--citation",
                " raw citation ",
                "--doi",
                "--help",
                "--arxiv-id",
                "raw-arxiv",
                "--work-id",
                "raw-work",
                "--json",
            ),
            "literature.add",
            {
                "pdf_path": "raw.pdf",
                "work_id": "raw-work",
                "doi": "--help",
                "arxiv_id": "raw-arxiv",
                "citation": " raw citation ",
                "json_output": True,
            },
        ),
        (
            ("literature", "resume", "raw-work"),
            "literature.resume",
            {"work_id": "raw-work", "json_output": False},
        ),
        (
            ("literature", "review", "raw-candidate", "--defer", "--json"),
            "literature.review",
            {
                "candidate_id": "raw-candidate",
                "action": "defer",
                "note": None,
                "json_output": True,
            },
        ),
        (
            ("knowledge", "search", " raw query ", "--json"),
            "knowledge.search",
            {"query": " raw query ", "json_output": True},
        ),
        (
            ("knowledge", "show", "raw-candidate"),
            "knowledge.show",
            {"candidate_id": "raw-candidate", "json_output": False},
        ),
        (
            ("knowledge", "ask", "--", "--help"),
            "knowledge.ask",
            {"question": "--help", "json_output": False},
        ),
        (
            ("knowledge", "ask", ""),
            "knowledge.ask",
            {"question": "", "json_output": False},
        ),
    ],
)
def test_each_valid_route_hands_raw_values_to_only_its_adapter(
    tmp_path: Path,
    suffix: tuple[str, ...],
    route: str,
    expected_values: dict[str, object],
) -> None:
    (tmp_path / "sitecustomize.py").write_text(FAKE_ADAPTERS, encoding="utf-8")
    arguments = (
        "--literature-data-root= raw-L ",
        "--knowledge-data-root",
        " raw-K ",
        *suffix,
    )

    results = run_both_launchers(
        arguments,
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )

    expected_values = {
        "cli_patch": [
            ["literature.data_root", " raw-L "],
            ["knowledge.data_root", " raw-K "],
        ],
        **expected_values,
    }
    for result in results:
        assert (result.returncode, result.stderr) == (0, b"")
        assert json.loads(result.stdout) == {
            "route": route,
            "values": expected_values,
        }


BLOCK_ADAPTER_IMPORTS = r'''
import importlib.abc
import os
import sys


class BlockAdapters(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {
            "gezhi._operations",
            "gezhi._literature_commands",
            "gezhi._knowledge_commands",
        }:
            with open(os.environ["GEZHI_ADAPTER_IMPORT_MARKER"], "ab", buffering=0) as marker:
                marker.write(fullname.encode("ascii") + b"\n")
            raise RuntimeError("adapter import is forbidden on this path")
        return None


sys.meta_path.insert(0, BlockAdapters())
'''


@pytest.mark.parametrize(
    ("suffix", "returncode"),
    [
        ((), 0),
        (("--help",), 0),
        (("--version",), 0),
        (("literature",), 0),
        (("literature", "--help"), 0),
        (("knowledge",), 0),
        (("knowledge", "--help"), 0),
        (("doctor", "--help"), 0),
        (("status", "--help"), 0),
        (("literature", "add", "--help"), 0),
        (("literature", "resume", "--help"), 0),
        (("literature", "review", "--help"), 0),
        (("knowledge", "search", "--help"), 0),
        (("knowledge", "show", "--help"), 0),
        (("knowledge", "ask", "--help"), 0),
        (("doctor", "--json", "--json"), 2),
        (("unknown",), 2),
    ],
)
def test_meta_and_grammar_failure_paths_never_import_an_adapter(
    tmp_path: Path,
    suffix: tuple[str, ...],
    returncode: int,
) -> None:
    (tmp_path / "sitecustomize.py").write_text(
        BLOCK_ADAPTER_IMPORTS,
        encoding="utf-8",
    )
    marker = tmp_path / "adapter-imports.bin"

    results = run_both_launchers(
        suffix,
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
        environment_updates={"GEZHI_ADAPTER_IMPORT_MARKER": str(marker)},
    )

    assert [result.returncode for result in results] == [returncode, returncode]
    assert not marker.exists()


def test_selected_adapter_exit_exception_escapes_the_parser_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import typer

    from gezhi import _cli

    operations = types.ModuleType("gezhi._operations")

    def missing_adapter(name: str) -> object:
        if name == "run_doctor":
            raise typer.Exit(code=77)
        raise AttributeError(name)

    operations.__getattr__ = missing_adapter  # type: ignore[method-assign]
    monkeypatch.setitem(sys.modules, "gezhi._operations", operations)

    with pytest.raises(typer.Exit) as raised:
        _cli.run_cli(("doctor",))

    assert raised.value.exit_code == 77


def test_validated_descriptor_owner_drives_adapter_module_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _cli

    operations = types.ModuleType("test_descriptor_owned_operations")
    operations.run_doctor = lambda **_values: 41  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, operations.__name__, operations)
    monkeypatch.setitem(
        _cli._OWNER_MODULES,
        "operations",
        operations.__name__,
    )

    assert _cli.run_cli(("doctor",)) == 41


def test_graph_construction_fault_precedes_grammar_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _cli

    def explode(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("graph construction fault")

    monkeypatch.setattr(_cli, "_build_cli", explode)

    with pytest.raises(RuntimeError, match="graph construction fault"):
        _cli.run_cli(("unknown",))
