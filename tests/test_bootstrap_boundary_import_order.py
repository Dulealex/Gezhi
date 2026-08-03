from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PYTHON_EXE = Path(sys.executable)
CONSOLE_EXE = PYTHON_EXE.with_name("gezhi.exe")
RESOURCE_LIMIT_STDERR = b"gezhi: error: command-line input exceeds safety limits\r\n"
POST_PREFLIGHT_SENTINEL = b"POST_PREFLIGHT_IMPORT_BLOCKED:gezhi._cli"
SITE_CUSTOMIZE = """
import importlib.abc
import sys


class _PostPreflightImportBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = (
            fullname == "gezhi._cli"
            or fullname == "typer"
            or fullname.startswith("typer.")
            or fullname == "rich"
            or fullname.startswith("rich.")
        )
        if blocked:
            raise RuntimeError(f"POST_PREFLIGHT_IMPORT_BLOCKED:{fullname}")
        return None


sys.meta_path.insert(0, _PostPreflightImportBlocker())
"""


def _launcher_commands(arguments: tuple[str, ...]) -> tuple[list[str], list[str]]:
    return (
        [str(CONSOLE_EXE), *arguments],
        [str(PYTHON_EXE), "-m", "gezhi", *arguments],
    )


def _run_with_import_blocker(
    command: list[str],
    blocker_root: Path,
) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(blocker_root), str(SOURCE_ROOT)))
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("arguments", "resource_rejected"),
    [
        pytest.param(("",) * 127, False, id="count-limit-minus-one"),
        pytest.param(("",) * 128, False, id="count-limit"),
        pytest.param(("",) * 129, True, id="count-limit-plus-one"),
        pytest.param(("a" * 8191,), False, id="item-limit-minus-one"),
        pytest.param(("a" * 8192,), False, id="item-limit"),
        pytest.param(("a" * 8193,), True, id="item-limit-plus-one"),
        pytest.param(
            ("a" * 8192, "b" * 8191),
            False,
            id="aggregate-limit-minus-one",
        ),
        pytest.param(
            ("a" * 8192, "b" * 8192),
            False,
            id="aggregate-limit",
        ),
        pytest.param(
            ("a" * 8192, "b" * 8192, "c"),
            True,
            id="aggregate-limit-plus-one",
        ),
    ],
)
def test_real_launchers_cross_preflight_at_each_inclusive_boundary(
    tmp_path: Path,
    arguments: tuple[str, ...],
    resource_rejected: bool,
) -> None:
    (tmp_path / "sitecustomize.py").write_text(
        SITE_CUSTOMIZE,
        encoding="utf-8",
    )
    results = [
        _run_with_import_blocker(command, tmp_path)
        for command in _launcher_commands(arguments)
    ]

    if resource_rejected:
        assert [
            (result.returncode, result.stdout, result.stderr) for result in results
        ] == [
            (2, b"", RESOURCE_LIMIT_STDERR),
            (2, b"", RESOURCE_LIMIT_STDERR),
        ]
    else:
        for result in results:
            assert result.returncode == 1
            assert result.stdout == b""
            assert POST_PREFLIGHT_SENTINEL in result.stderr
