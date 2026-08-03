from __future__ import annotations

from pathlib import Path

import pytest
from launcher_support import (
    RESOURCE_LIMIT_STDERR,
    SOURCE_ROOT,
    launcher_commands,
    run_launcher,
)

IMPORT_PROBE_ENV = "GEZHI_POST_PREFLIGHT_IMPORT_PROBE"
SITE_CUSTOMIZE = r"""
import importlib.abc
import os
import sys


class _PostPreflightImportBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = (
            fullname == "typer"
            or fullname.startswith("typer.")
            or fullname == "rich"
            or fullname.startswith("rich.")
        )
        if blocked:
            with open(os.environ["GEZHI_POST_PREFLIGHT_IMPORT_PROBE"], "ab", buffering=0) as probe:
                probe.write(fullname.encode("ascii") + b"\n")
            raise RuntimeError("post-preflight import blocked by acceptance probe")
        return None


sys.meta_path.insert(0, _PostPreflightImportBlocker())
"""


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
    (tmp_path / "sitecustomize.py").write_text(SITE_CUSTOMIZE, encoding="utf-8")

    for index, command in enumerate(launcher_commands(arguments)):
        marker = tmp_path / f"import-probe-{index}.bin"
        result = run_launcher(
            command,
            pythonpath_roots=(tmp_path, SOURCE_ROOT),
            environment_updates={IMPORT_PROBE_ENV: str(marker)},
        )

        if resource_rejected:
            assert (result.returncode, result.stdout, result.stderr) == (
                2,
                b"",
                RESOURCE_LIMIT_STDERR,
            )
            assert not marker.exists()
        else:
            assert marker.read_bytes() in {b"typer\n", b"rich\n"}
