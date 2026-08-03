from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import typer
from typer.core import TyperGroup


class _SnapshotOnlyTyperGroup(TyperGroup):
    def _main_shell_completion(
        self,
        ctx_args: MutableMapping[str, Any],
        prog_name: str,
        complete_var: str | None = None,
    ) -> None:
        return None


def _root() -> None:
    return None


def _build_cli() -> typer.Typer:
    return typer.Typer(
        cls=_SnapshotOnlyTyperGroup,
        callback=_root,
        invoke_without_command=True,
        no_args_is_help=False,
        add_completion=False,
    )


def run_cli(arguments: tuple[str, ...]) -> int:
    app = _build_cli()
    app(
        args=arguments,
        prog_name="gezhi",
        windows_expand_args=False,
        standalone_mode=False,
    )
    return 0
