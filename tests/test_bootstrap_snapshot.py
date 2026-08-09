from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from types import ModuleType

import pytest

from gezhi import bootstrap
from gezhi._raw_argv import RawArgvPreflightVerdictV1


class _OneShotArgv(list[str]):
    iterations = 0

    def __iter__(self) -> Iterator[str]:
        self.iterations += 1
        if self.iterations > 1:
            raise AssertionError("sys.argv was read more than once")
        return super().__iter__()


class _PoisonedArgv(list[str]):
    def __iter__(self) -> Iterator[str]:
        raise AssertionError("sys.argv was read after preflight")


class _FakeCli(ModuleType):
    def __init__(self, run_cli: Callable[..., int]) -> None:
        super().__init__("gezhi._cli")
        self.run_cli = run_cli


def test_main_uses_one_snapshot_for_preflight_and_exact_cli_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The stable main() seam cannot expose its handoff directly. This narrow
    # spy substitutes only the two receivers while exercising main itself.
    process_argv = _OneShotArgv(["launcher", "alpha", "二", "omega"])
    preflight_inputs: list[tuple[str, ...]] = []
    cli_inputs: list[tuple[str, ...]] = []
    cli_descriptors: list[object] = []

    def evaluate(argv_snapshot: tuple[str, ...]) -> RawArgvPreflightVerdictV1:
        preflight_inputs.append(argv_snapshot)
        bootstrap.sys.argv = _PoisonedArgv(["poisoned"])
        return RawArgvPreflightVerdictV1.PASS

    def run_cli(arguments: tuple[str, ...], *, descriptor: object) -> int:
        cli_inputs.append(arguments)
        cli_descriptors.append(descriptor)
        return 73

    fake_cli = _FakeCli(run_cli)
    monkeypatch.setattr(bootstrap.sys, "argv", process_argv)
    monkeypatch.setattr(bootstrap.RawArgvPreflightV1, "evaluate", evaluate)
    monkeypatch.setitem(sys.modules, "gezhi._cli", fake_cli)

    assert bootstrap.main() == 73
    assert process_argv.iterations == 1
    assert preflight_inputs == [("launcher", "alpha", "二", "omega")]
    assert cli_inputs == [("alpha", "二", "omega")]
    assert len(cli_descriptors) == 1
