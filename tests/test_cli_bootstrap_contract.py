from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from launcher_support import SOURCE_ROOT, run_both_launchers, run_python_script

BOOTSTRAP_FAILED_STDERR = b"gezhi: error: cli bootstrap failed\r\n"


def test_frozen_cli_prerequisites_and_static_graph_are_ready() -> None:
    from gezhi._cli_bootstrap import (
        BootstrapPrerequisiteProbeV1,
        BootstrapPrerequisiteVerdictV1,
        StaticCommandGraphDescriptorValidatorV1,
        StaticCommandGraphVerdictV1,
        static_command_graph_descriptor_v1,
    )

    descriptor = static_command_graph_descriptor_v1()

    assert (
        BootstrapPrerequisiteProbeV1.evaluate()
        is BootstrapPrerequisiteVerdictV1.ESSENTIAL_READY
    )
    assert (
        StaticCommandGraphDescriptorValidatorV1.evaluate(descriptor)
        is StaticCommandGraphVerdictV1.GRAPH_DESCRIPTOR_VALID
    )
    assert tuple(route.path for route in descriptor.routes) == (
        ("doctor",),
        ("status",),
        ("literature", "add"),
        ("literature", "resume"),
        ("literature", "review"),
        ("knowledge", "search"),
        ("knowledge", "show"),
        ("knowledge", "ask"),
    )


def test_stdlib_prerequisite_probe_does_not_import_typer_or_rich() -> None:
    result = run_python_script(
        "import sys; "
        "from gezhi._cli_bootstrap import BootstrapPrerequisiteProbeV1; "
        "BootstrapPrerequisiteProbeV1.evaluate(); "
        "assert 'typer' not in sys.modules; "
        "assert 'rich' not in sys.modules"
    )

    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")

def test_expected_missing_prerequisite_is_typed_but_probe_bug_escapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _cli_bootstrap as contract

    monkeypatch.setattr(contract.importlib.util, "find_spec", lambda _name: None)
    assert (
        contract.BootstrapPrerequisiteProbeV1.evaluate()
        is contract.BootstrapPrerequisiteVerdictV1.ESSENTIAL_UNAVAILABLE
    )

    def explode(_name: str) -> None:
        raise RuntimeError("probe bug")

    monkeypatch.setattr(contract.importlib.util, "find_spec", explode)
    with pytest.raises(RuntimeError, match="probe bug"):
        contract.BootstrapPrerequisiteProbeV1.evaluate()


def test_representable_static_graph_mismatch_is_typed() -> None:
    from gezhi._cli_bootstrap import (
        StaticCommandGraphDescriptorValidatorV1,
        StaticCommandGraphVerdictV1,
        static_command_graph_descriptor_v1,
    )

    descriptor = static_command_graph_descriptor_v1()

    assert (
        StaticCommandGraphDescriptorValidatorV1.evaluate(
            replace(descriptor, routes=descriptor.routes[:-1])
        )
        is StaticCommandGraphVerdictV1.GRAPH_DESCRIPTOR_INVALID
    )


def test_static_graph_validator_rejects_bool_like_integer_fields() -> None:
    from gezhi._cli_bootstrap import (
        StaticCommandGraphDescriptorValidatorV1,
        StaticCommandGraphVerdictV1,
        static_command_graph_descriptor_v1,
    )

    descriptor = static_command_graph_descriptor_v1()
    status_route = descriptor.routes[1]
    malformed_route = replace(
        status_route,
        operands=(("work_id", cast(Any, 0)),),
    )
    malformed = replace(
        descriptor,
        routes=(descriptor.routes[0], malformed_route, *descriptor.routes[2:]),
    )

    assert (
        StaticCommandGraphDescriptorValidatorV1.evaluate(malformed)
        is StaticCommandGraphVerdictV1.GRAPH_DESCRIPTOR_INVALID
    )


FAKE_BOOTSTRAP_MODULE = r'''
import enum
import sys
import types


module = types.ModuleType("gezhi._cli_bootstrap")


class BootstrapPrerequisiteVerdictV1(enum.Enum):
    ESSENTIAL_READY = enum.auto()
    ESSENTIAL_UNAVAILABLE = enum.auto()


class StaticCommandGraphVerdictV1(enum.Enum):
    GRAPH_DESCRIPTOR_VALID = enum.auto()
    GRAPH_DESCRIPTOR_INVALID = enum.auto()


class BootstrapPrerequisiteProbeV1:
    @staticmethod
    def evaluate():
        return BootstrapPrerequisiteVerdictV1.{prerequisite}


class StaticCommandGraphDescriptorValidatorV1:
    @staticmethod
    def evaluate(descriptor):
        return StaticCommandGraphVerdictV1.{graph}


def static_command_graph_descriptor_v1():
    return ()


module.BootstrapPrerequisiteVerdictV1 = BootstrapPrerequisiteVerdictV1
module.StaticCommandGraphVerdictV1 = StaticCommandGraphVerdictV1
module.BootstrapPrerequisiteProbeV1 = BootstrapPrerequisiteProbeV1
module.StaticCommandGraphDescriptorValidatorV1 = StaticCommandGraphDescriptorValidatorV1
module.static_command_graph_descriptor_v1 = static_command_graph_descriptor_v1
sys.modules["gezhi._cli_bootstrap"] = module
'''


@pytest.mark.parametrize(
    ("prerequisite", "graph"),
    [
        ("ESSENTIAL_UNAVAILABLE", "GRAPH_DESCRIPTOR_VALID"),
        ("ESSENTIAL_READY", "GRAPH_DESCRIPTOR_INVALID"),
    ],
)
def test_explicit_bootstrap_failure_has_fixed_two_launcher_receipt(
    tmp_path: Path,
    prerequisite: str,
    graph: str,
) -> None:
    (tmp_path / "sitecustomize.py").write_text(
        FAKE_BOOTSTRAP_MODULE.format(prerequisite=prerequisite, graph=graph),
        encoding="utf-8",
    )

    results = run_both_launchers(
        ("doctor", "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [
        (1, b"", BOOTSTRAP_FAILED_STDERR),
        (1, b"", BOOTSTRAP_FAILED_STDERR),
    ]
