from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
from dataclasses import dataclass
from enum import Enum, auto


class BootstrapPrerequisiteVerdictV1(Enum):
    ESSENTIAL_READY = auto()
    ESSENTIAL_UNAVAILABLE = auto()


class StaticCommandGraphVerdictV1(Enum):
    GRAPH_DESCRIPTOR_VALID = auto()
    GRAPH_DESCRIPTOR_INVALID = auto()


@dataclass(frozen=True, slots=True)
class StaticCommandRouteV1:
    path: tuple[str, ...]
    owner: str
    operands: tuple[tuple[str, bool], ...]
    value_options: tuple[str, ...]
    flags: tuple[str, ...]
    exactly_one_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StaticCommandGraphV1:
    root_value_options: tuple[str, ...]
    meta_options: tuple[str, ...]
    routes: tuple[StaticCommandRouteV1, ...]


_CANONICAL_GRAPH = StaticCommandGraphV1(
    root_value_options=(
        "--literature-data-root",
        "--knowledge-data-root",
    ),
    meta_options=("--help", "--version"),
    routes=(
        StaticCommandRouteV1(("doctor",), "operations", (), (), ("--json",)),
        StaticCommandRouteV1(
            ("status",),
            "operations",
            (("work_id", False),),
            (),
            ("--json",),
        ),
        StaticCommandRouteV1(
            ("literature", "add"),
            "literature",
            (("pdf_path", True),),
            ("--work-id", "--doi", "--arxiv-id", "--citation"),
            ("--json",),
        ),
        StaticCommandRouteV1(
            ("literature", "resume"),
            "literature",
            (("work_id", True),),
            (),
            ("--json",),
        ),
        StaticCommandRouteV1(
            ("literature", "review"),
            "literature",
            (("candidate_id", True),),
            (),
            ("--accept", "--reject", "--defer", "--json"),
            exactly_one_flags=("--accept", "--reject", "--defer"),
        ),
        StaticCommandRouteV1(
            ("knowledge", "search"),
            "knowledge",
            (("query", True),),
            (),
            ("--json",),
        ),
        StaticCommandRouteV1(
            ("knowledge", "show"),
            "knowledge",
            (("candidate_id", True),),
            (),
            ("--json",),
        ),
        StaticCommandRouteV1(
            ("knowledge", "ask"),
            "knowledge",
            (("question", True),),
            (),
            ("--json",),
        ),
    ),
)


class BootstrapPrerequisiteProbeV1:
    @staticmethod
    def evaluate() -> BootstrapPrerequisiteVerdictV1:
        if (
            sys.implementation.name != "cpython"
            or sys.version_info[:3] != (3, 11, 15)
        ):
            return BootstrapPrerequisiteVerdictV1.ESSENTIAL_UNAVAILABLE
        for module_name, distribution_name, expected_version in (
            ("typer", "typer", "0.27.0"),
            ("rich", "rich", "15.0.0"),
        ):
            if importlib.util.find_spec(module_name) is None:
                return BootstrapPrerequisiteVerdictV1.ESSENTIAL_UNAVAILABLE
            try:
                installed_version = importlib.metadata.version(distribution_name)
            except importlib.metadata.PackageNotFoundError:
                return BootstrapPrerequisiteVerdictV1.ESSENTIAL_UNAVAILABLE
            if installed_version != expected_version:
                return BootstrapPrerequisiteVerdictV1.ESSENTIAL_UNAVAILABLE
        return BootstrapPrerequisiteVerdictV1.ESSENTIAL_READY


def static_command_graph_descriptor_v1() -> StaticCommandGraphV1:
    return _CANONICAL_GRAPH


def _is_exact_string_tuple(value: object) -> bool:
    return type(value) is tuple and all(type(item) is str for item in value)


def _route_shape_is_exact(route: StaticCommandRouteV1) -> bool:
    if not _is_exact_string_tuple(route.path):
        return False
    if type(route.owner) is not str:
        return False
    if type(route.operands) is not tuple:
        return False
    for operand in route.operands:
        if (
            type(operand) is not tuple
            or len(operand) != 2
            or type(operand[0]) is not str
            or type(operand[1]) is not bool
        ):
            return False
    return (
        _is_exact_string_tuple(route.value_options)
        and _is_exact_string_tuple(route.flags)
        and _is_exact_string_tuple(route.exactly_one_flags)
    )


class StaticCommandGraphDescriptorValidatorV1:
    @staticmethod
    def evaluate(descriptor: object) -> StaticCommandGraphVerdictV1:
        if type(descriptor) is not StaticCommandGraphV1:
            return StaticCommandGraphVerdictV1.GRAPH_DESCRIPTOR_INVALID
        if not _is_exact_string_tuple(descriptor.root_value_options):
            return StaticCommandGraphVerdictV1.GRAPH_DESCRIPTOR_INVALID
        if not _is_exact_string_tuple(descriptor.meta_options):
            return StaticCommandGraphVerdictV1.GRAPH_DESCRIPTOR_INVALID
        if type(descriptor.routes) is not tuple:
            return StaticCommandGraphVerdictV1.GRAPH_DESCRIPTOR_INVALID
        if any(type(route) is not StaticCommandRouteV1 for route in descriptor.routes):
            return StaticCommandGraphVerdictV1.GRAPH_DESCRIPTOR_INVALID
        if any(not _route_shape_is_exact(route) for route in descriptor.routes):
            return StaticCommandGraphVerdictV1.GRAPH_DESCRIPTOR_INVALID
        if descriptor != _CANONICAL_GRAPH:
            return StaticCommandGraphVerdictV1.GRAPH_DESCRIPTOR_INVALID
        return StaticCommandGraphVerdictV1.GRAPH_DESCRIPTOR_VALID
