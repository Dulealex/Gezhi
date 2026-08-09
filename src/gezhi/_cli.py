from __future__ import annotations

import importlib
import msvcrt
import os
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from typing import Annotated, Any

import typer
from typer.core import TyperGroup

from gezhi._cli_bootstrap import (
    StaticCommandGraphV1,
    StaticCommandRouteV1,
    static_command_graph_descriptor_v1,
)

_PARSER_FAILED_STDERR = b"gezhi: error: invalid command line\r\n"


class _SnapshotOnlyTyperGroup(TyperGroup):
    def _main_shell_completion(
        self,
        ctx_args: MutableMapping[str, Any],
        prog_name: str,
        complete_var: str | None = None,
    ) -> None:
        return None


@dataclass(frozen=True, slots=True)
class _InvocationContextV1:
    cli_patch: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _SelectedInvocationV1:
    route: tuple[str, ...]
    cli_patch: tuple[tuple[str, str], ...]
    values: tuple[tuple[str, object], ...]


def _present_parser_failed() -> None:
    try:
        msvcrt.setmode(2, os.O_BINARY)
    except OSError:
        return
    payload = memoryview(_PARSER_FAILED_STDERR)
    offset = 0
    while offset < len(payload):
        remaining = len(payload) - offset
        try:
            count = os.write(2, payload[offset:])
        except OSError:
            return
        if type(count) is not int or not 1 <= count <= remaining:
            return
        offset += count


def _meta_invocations(descriptor: StaticCommandGraphV1) -> set[tuple[str, ...]]:
    values = {
        (),
        ("--help",),
        ("--version",),
        ("literature",),
        ("literature", "--help"),
        ("knowledge",),
        ("knowledge", "--help"),
    }
    values.update(route.path + ("--help",) for route in descriptor.routes)
    return values


def _match_value_option(
    token: str,
    names: tuple[str, ...],
) -> tuple[str, str] | None:
    for name in names:
        prefix = name + "="
        if token.startswith(prefix):
            return name, token[len(prefix) :]
    return None


def _route_after_root_options(
    arguments: tuple[str, ...],
    index: int,
    descriptor: StaticCommandGraphV1,
) -> tuple[StaticCommandRouteV1, int] | None:
    for route in sorted(descriptor.routes, key=lambda item: len(item.path), reverse=True):
        end = index + len(route.path)
        if arguments[index:end] == route.path:
            return route, end
    return None


def _leaf_arguments_are_valid(
    arguments: tuple[str, ...],
    index: int,
    route: StaticCommandRouteV1,
) -> bool:
    positionals: list[str] = []
    seen_options: set[str] = set()
    options_ended = False
    while index < len(arguments):
        token = arguments[index]
        if not options_ended and token == "--":
            options_ended = True
            index += 1
            continue
        if not options_ended and token.startswith("--"):
            if token in route.flags:
                if token in seen_options:
                    return False
                seen_options.add(token)
                index += 1
                continue
            if token in route.value_options:
                if token in seen_options or index + 1 >= len(arguments):
                    return False
                seen_options.add(token)
                index += 2
                continue
            matched = _match_value_option(token, route.value_options)
            if matched is None or matched[0] in seen_options:
                return False
            seen_options.add(matched[0])
            index += 1
            continue
        if not options_ended and token.startswith("-"):
            return False
        positionals.append(token)
        index += 1

    required_count = sum(required for _name, required in route.operands)
    if not required_count <= len(positionals) <= len(route.operands):
        return False
    if route.exactly_one_flags:
        selected = sum(flag in seen_options for flag in route.exactly_one_flags)
        if selected != 1:
            return False
    return True


def _grammar_is_valid(
    arguments: tuple[str, ...],
    descriptor: StaticCommandGraphV1,
) -> bool:
    meta_invocations = _meta_invocations(descriptor)
    if arguments in meta_invocations:
        return True

    index = 0
    seen_root_options: set[str] = set()
    while index < len(arguments):
        token = arguments[index]
        if token in descriptor.root_value_options:
            if token in seen_root_options or index + 1 >= len(arguments):
                return False
            seen_root_options.add(token)
            index += 2
            continue
        matched = _match_value_option(token, descriptor.root_value_options)
        if matched is not None:
            if matched[0] in seen_root_options:
                return False
            seen_root_options.add(matched[0])
            index += 1
            continue
        break

    if index >= len(arguments):
        return False
    selected = _route_after_root_options(arguments, index, descriptor)
    if selected is None:
        return False
    route, leaf_index = selected
    return _leaf_arguments_are_valid(arguments, leaf_index, route)


def _root(
    context: typer.Context,
    literature_data_root: Annotated[
        str | None,
        typer.Option("--literature-data-root"),
    ] = None,
    knowledge_data_root: Annotated[
        str | None,
        typer.Option("--knowledge-data-root"),
    ] = None,
    version: Annotated[bool, typer.Option("--version")] = False,
) -> None:
    patch: list[tuple[str, str]] = []
    if literature_data_root is not None:
        patch.append(("literature.data_root", literature_data_root))
    if knowledge_data_root is not None:
        patch.append(("knowledge.data_root", knowledge_data_root))
    context.obj = _InvocationContextV1(tuple(patch))
    if version:
        typer.echo("gezhi 0.1.0")
        return
    if context.invoked_subcommand is None:
        typer.echo(context.get_help())


def _namespace(context: typer.Context) -> None:
    if context.invoked_subcommand is None:
        typer.echo(context.get_help())


def _cli_patch(context: typer.Context) -> tuple[tuple[str, str], ...]:
    value = context.find_root().obj
    if type(value) is not _InvocationContextV1:
        raise RuntimeError("CLI invocation context is unavailable")
    return value.cli_patch


def _selected(
    context: typer.Context,
    route: tuple[str, ...],
    **values: object,
) -> _SelectedInvocationV1:
    return _SelectedInvocationV1(
        route=route,
        cli_patch=_cli_patch(context),
        values=tuple(values.items()),
    )


def _doctor(
    context: typer.Context,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> _SelectedInvocationV1:
    return _selected(context, ("doctor",), json_output=json_output)


def _status(
    context: typer.Context,
    work_id: Annotated[str | None, typer.Argument()] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> _SelectedInvocationV1:
    return _selected(
        context,
        ("status",),
        work_id=work_id,
        json_output=json_output,
    )


def _literature_add(
    context: typer.Context,
    pdf_path: Annotated[str, typer.Argument()],
    work_id: Annotated[str | None, typer.Option("--work-id")] = None,
    doi: Annotated[str | None, typer.Option("--doi")] = None,
    arxiv_id: Annotated[str | None, typer.Option("--arxiv-id")] = None,
    citation: Annotated[str | None, typer.Option("--citation")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> _SelectedInvocationV1:
    return _selected(
        context,
        ("literature", "add"),
        pdf_path=pdf_path,
        work_id=work_id,
        doi=doi,
        arxiv_id=arxiv_id,
        citation=citation,
        json_output=json_output,
    )


def _literature_resume(
    context: typer.Context,
    work_id: Annotated[str, typer.Argument()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> _SelectedInvocationV1:
    return _selected(
        context,
        ("literature", "resume"),
        work_id=work_id,
        json_output=json_output,
    )


def _literature_review(
    context: typer.Context,
    candidate_id: Annotated[str, typer.Argument()],
    accept: Annotated[bool, typer.Option("--accept")] = False,
    reject: Annotated[bool, typer.Option("--reject")] = False,
    defer: Annotated[bool, typer.Option("--defer")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> _SelectedInvocationV1:
    selected = tuple(
        action
        for action, enabled in (
            ("accept", accept),
            ("reject", reject),
            ("defer", defer),
        )
        if enabled
    )
    if len(selected) != 1:
        raise RuntimeError("validated review action is unavailable")
    return _selected(
        context,
        ("literature", "review"),
        candidate_id=candidate_id,
        action=selected[0],
        note=None,
        json_output=json_output,
    )


def _knowledge_search(
    context: typer.Context,
    query: Annotated[str, typer.Argument()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> _SelectedInvocationV1:
    return _selected(
        context,
        ("knowledge", "search"),
        query=query,
        json_output=json_output,
    )


def _knowledge_show(
    context: typer.Context,
    candidate_id: Annotated[str, typer.Argument()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> _SelectedInvocationV1:
    return _selected(
        context,
        ("knowledge", "show"),
        candidate_id=candidate_id,
        json_output=json_output,
    )


def _knowledge_ask(
    context: typer.Context,
    question: Annotated[str, typer.Argument()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> _SelectedInvocationV1:
    return _selected(
        context,
        ("knowledge", "ask"),
        question=question,
        json_output=json_output,
    )


@dataclass(frozen=True, slots=True)
class _RouteBindingV1:
    callback: Callable[..., object]
    function_name: str


_OWNER_MODULES = {
    "operations": "gezhi._operations",
    "literature": "gezhi._literature_commands",
    "knowledge": "gezhi._knowledge_commands",
}

_ROUTE_BINDINGS = {
    ("doctor",): _RouteBindingV1(
        _doctor,
        "run_doctor",
    ),
    ("status",): _RouteBindingV1(
        _status,
        "run_status",
    ),
    ("literature", "add"): _RouteBindingV1(
        _literature_add,
        "run_add",
    ),
    ("literature", "resume"): _RouteBindingV1(
        _literature_resume,
        "run_resume",
    ),
    ("literature", "review"): _RouteBindingV1(
        _literature_review,
        "run_review",
    ),
    ("knowledge", "search"): _RouteBindingV1(
        _knowledge_search,
        "run_search",
    ),
    ("knowledge", "show"): _RouteBindingV1(
        _knowledge_show,
        "run_show",
    ),
    ("knowledge", "ask"): _RouteBindingV1(
        _knowledge_ask,
        "run_ask",
    ),
}


def _invoke_selected(
    selection: _SelectedInvocationV1,
    descriptor: StaticCommandGraphV1,
) -> int:
    binding = _ROUTE_BINDINGS[selection.route]
    route = next(route for route in descriptor.routes if route.path == selection.route)
    module = importlib.import_module(_OWNER_MODULES[route.owner])
    adapter = getattr(module, binding.function_name)
    values = dict(selection.values)
    values["cli_patch"] = selection.cli_patch
    code = adapter(**values)
    if type(code) is not int:
        raise TypeError("command adapter returned an invalid exit code")
    return code


def _build_cli(descriptor: StaticCommandGraphV1 | None = None) -> typer.Typer:
    graph = descriptor or static_command_graph_descriptor_v1()
    app = typer.Typer(
        cls=_SnapshotOnlyTyperGroup,
        callback=_root,
        invoke_without_command=True,
        no_args_is_help=False,
        add_completion=False,
        pretty_exceptions_enable=False,
    )
    literature = typer.Typer(
        cls=_SnapshotOnlyTyperGroup,
        callback=_namespace,
        invoke_without_command=True,
        no_args_is_help=False,
        add_completion=False,
        pretty_exceptions_enable=False,
    )
    knowledge = typer.Typer(
        cls=_SnapshotOnlyTyperGroup,
        callback=_namespace,
        invoke_without_command=True,
        no_args_is_help=False,
        add_completion=False,
        pretty_exceptions_enable=False,
    )
    app.add_typer(literature, name="literature")
    app.add_typer(knowledge, name="knowledge")
    for route in graph.routes:
        callback = _ROUTE_BINDINGS[route.path].callback
        if len(route.path) == 1:
            app.command(name=route.path[0])(callback)
        elif route.path[0] == "literature":
            literature.command(name=route.path[1])(callback)
        elif route.path[0] == "knowledge":
            knowledge.command(name=route.path[1])(callback)
        else:
            raise RuntimeError("validated CLI route cannot be constructed")
    return app


def run_cli(
    arguments: tuple[str, ...],
    *,
    descriptor: StaticCommandGraphV1 | None = None,
) -> int:
    graph = descriptor or static_command_graph_descriptor_v1()
    app = _build_cli(descriptor) if descriptor is not None else _build_cli()
    if not _grammar_is_valid(arguments, graph):
        _present_parser_failed()
        return 2
    result = app(
        args=arguments,
        prog_name="gezhi",
        windows_expand_args=False,
        standalone_mode=False,
    )
    if result is None:
        return 0
    if arguments in _meta_invocations(graph) and type(result) is int and result == 0:
        return 0
    if type(result) is not _SelectedInvocationV1:
        raise TypeError("CLI returned an invalid selection")
    return _invoke_selected(result, graph)
