from __future__ import annotations

import json
from pathlib import Path
from typing import cast

_REPOSITORY_RUNTIME_ROOT = (
    Path(__file__).resolve().parents[2] / "runtimes" / "codex"
)
_DESCRIPTOR_NAMES = (
    "runtime-identity-v1.json",
    "package.json",
    "package-lock.json",
)
_EXECUTABLE_BYTES = b"test-only-not-an-executable"


def _read_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise AssertionError(f"fixture descriptor is not an object: {path.name}")
    return cast(dict[str, object], value)


def _required_string(parent: dict[str, object], key: str) -> str:
    value = parent.get(key)
    if type(value) is not str or not value:
        raise AssertionError(f"fixture identity field is invalid: {key}")
    return value


def _package_parts(value: str) -> tuple[str, ...]:
    parts = tuple(value.split("/"))
    if len(parts) != 2 or any(not part for part in parts):
        raise AssertionError("fixture package name is invalid")
    return parts


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def build_project_codex_runtime_fixture_v1(root: Path) -> Path:
    """Build a complete runtime tree proved by the production resolver."""

    if not root.is_absolute():
        raise ValueError("fixture root must be absolute")
    runtime = root / "runtimes" / "codex"
    runtime.mkdir(parents=True, exist_ok=True)
    for name in _DESCRIPTOR_NAMES:
        (runtime / name).write_bytes(
            (_REPOSITORY_RUNTIME_ROOT / name).read_bytes()
        )

    identity = _read_json_object(runtime / "runtime-identity-v1.json")
    cli_package_name = _required_string(identity, "cli_package_name")
    cli_version = _required_string(identity, "cli_version")
    native_package_alias = _required_string(identity, "native_package_alias")
    native_package_name = _required_string(identity, "native_package_name")
    native_package_version = _required_string(
        identity,
        "native_package_version",
    )
    optional_dependencies = identity.get("optional_dependencies")
    executable_parts = identity.get("executable_relative_parts")
    if type(optional_dependencies) is not dict:
        raise AssertionError("fixture optional dependencies are invalid")
    if type(executable_parts) is not list or any(
        type(part) is not str or not part for part in executable_parts
    ):
        raise AssertionError("fixture executable path is invalid")

    installed = runtime / "node_modules"
    main = installed.joinpath(*_package_parts(cli_package_name))
    _write_json(
        main / "package.json",
        {
            "name": cli_package_name,
            "version": cli_version,
            "optionalDependencies": optional_dependencies,
        },
    )
    native = installed.joinpath(*_package_parts(native_package_alias))
    _write_json(
        native / "package.json",
        {
            "name": native_package_name,
            "version": native_package_version,
        },
    )
    executable = native.joinpath(
        *(cast(str, part) for part in executable_parts)
    )
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(_EXECUTABLE_BYTES)
    return executable
