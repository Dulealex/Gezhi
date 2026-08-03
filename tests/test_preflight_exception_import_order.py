from __future__ import annotations

from launcher_support import run_python_script

PREFLIGHT_EXCEPTION_PRESERVED = b"PREFLIGHT_EXCEPTION_PRESERVED"
PREFLIGHT_EXCEPTION_SCRIPT = r"""
import sys

from gezhi import bootstrap


project_modules_before = {
    name for name in sys.modules if name == "gezhi" or name.startswith("gezhi.")
}


class PreflightSentinelError(RuntimeError):
    pass


class ExplodingString(str):
    def __len__(self):
        raise PreflightSentinelError


sys.argv = ["gezhi", ExplodingString("payload")]
try:
    bootstrap.main()
except PreflightSentinelError:
    project_modules_after = {
        name
        for name in sys.modules
        if name == "gezhi" or name.startswith("gezhi.")
    }
    assert project_modules_after == project_modules_before
    assert not any(name == "typer" or name.startswith("typer.") for name in sys.modules)
    assert not any(name == "rich" or name.startswith("rich.") for name in sys.modules)
else:
    raise AssertionError("preflight exception was mapped or swallowed")

sys.stdout.buffer.write(b"PREFLIGHT_EXCEPTION_PRESERVED")
"""


def test_preflight_exception_propagates_without_loading_post_pass_modules() -> None:
    result = run_python_script(PREFLIGHT_EXCEPTION_SCRIPT)

    assert result.returncode == 0
    assert PREFLIGHT_EXCEPTION_PRESERVED in result.stdout
