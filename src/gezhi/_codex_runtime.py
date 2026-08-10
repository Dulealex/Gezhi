from __future__ import annotations

import json
import ntpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Self, TypeAlias, cast

from gezhi._windows_data_root import (
    DataRootLifecycleErrorV1,
    DataRootOpenErrorV1,
    FileIdentity,
    ValidatedDataRootV1,
    open_validated_data_root_v1,
)

_DESCRIPTOR_LIMIT_BYTES = 1_048_576
_OPTIONAL_PLATFORM_SUFFIXES = {
    "@openai/codex-darwin-arm64": "darwin-arm64",
    "@openai/codex-darwin-x64": "darwin-x64",
    "@openai/codex-linux-arm64": "linux-arm64",
    "@openai/codex-linux-x64": "linux-x64",
    "@openai/codex-win32-arm64": "win32-arm64",
    "@openai/codex-win32-x64": "win32-x64",
}
_RUNTIME_PARTS = ("runtimes", "codex")
_IDENTITY_PARTS = ("runtime-identity-v1.json",)
_PACKAGE_PARTS = ("package.json",)
_LOCK_PARTS = ("package-lock.json",)
_INSTALLED_NATIVE_PARTS = ("package.json",)
_EXECUTABLE_WITHIN_NATIVE = (
    "vendor",
    "x86_64-pc-windows-msvc",
    "bin",
    "codex.exe",
)
_IDENTITY_FIELDS = {
    "identity_version",
    "cli_package_name",
    "cli_version",
    "native_package_alias",
    "native_package_name",
    "native_package_version",
    "main_lock_integrity",
    "native_lock_integrity",
    "optional_dependencies",
    "executable_relative_parts",
}
_PROOF_SEAL_V1 = object()

JsonObject: TypeAlias = dict[str, object]
RuntimeProofKindV1: TypeAlias = Literal["project_pinned", "test_double"]


class CodexRuntimeResolutionErrorV1(RuntimeError):
    """The project-pinned Codex runtime did not prove its frozen identity."""


class CodexRuntimeDescriptorErrorV1(CodexRuntimeResolutionErrorV1):
    """A present runtime descriptor does not satisfy its closed JSON shape."""


class _RuntimeDescriptorMalformed(ValueError):
    pass


class _DuplicateJsonKey(_RuntimeDescriptorMalformed):
    pass


@dataclass(frozen=True, slots=True)
class _RuntimeIdentityV1:
    cli_package_name: str
    cli_version: str
    native_package_alias: str
    native_package_name: str
    native_package_version: str
    main_lock_integrity: str
    native_lock_integrity: str
    optional_dependencies: tuple[tuple[str, str], ...]
    executable_relative_parts: tuple[str, ...]


@dataclass(frozen=True, slots=True, init=False)
class FrozenCodexRuntimeV1:
    project_root_path: str
    executable_path: str
    executable_identity: FileIdentity
    executable_size: int
    executable_sha256: str
    cli_version: str
    native_package_version: str
    proof_kind: RuntimeProofKindV1
    _proof_seal: object = field(repr=False, compare=False)

    def __new__(cls, *_args: object, **_kwargs: object) -> Self:
        raise TypeError(
            "FrozenCodexRuntimeV1 can only be created by the resolver "
            "or private test factory"
        )


def _new_runtime_proof_v1(
    *,
    project_root_path: str,
    executable_path: str,
    executable_identity: FileIdentity,
    executable_size: int,
    executable_sha256: str,
    cli_version: str,
    native_package_version: str,
    proof_kind: RuntimeProofKindV1,
) -> FrozenCodexRuntimeV1:
    if (
        type(project_root_path) is not str
        or type(executable_path) is not str
        or not executable_path
        or not ntpath.isabs(executable_path)
        or type(executable_identity) is not tuple
        or len(executable_identity) != 2
        or any(type(item) is not int or item <= 0 for item in executable_identity)
        or type(executable_size) is not int
        or executable_size <= 0
        or type(executable_sha256) is not str
        or len(executable_sha256) != 64
        or any(character not in "0123456789abcdef" for character in executable_sha256)
        or type(cli_version) is not str
        or not cli_version
        or type(native_package_version) is not str
        or not native_package_version
        or proof_kind not in {"project_pinned", "test_double"}
        or (
            proof_kind == "project_pinned"
            and (not project_root_path or not ntpath.isabs(project_root_path))
        )
        or (proof_kind == "test_double" and project_root_path != "")
    ):
        raise ValueError("Codex runtime proof facts are invalid")
    proof = object.__new__(FrozenCodexRuntimeV1)
    object.__setattr__(proof, "project_root_path", project_root_path)
    object.__setattr__(proof, "executable_path", executable_path)
    object.__setattr__(proof, "executable_identity", executable_identity)
    object.__setattr__(proof, "executable_size", executable_size)
    object.__setattr__(proof, "executable_sha256", executable_sha256)
    object.__setattr__(proof, "cli_version", cli_version)
    object.__setattr__(proof, "native_package_version", native_package_version)
    object.__setattr__(proof, "proof_kind", proof_kind)
    object.__setattr__(proof, "_proof_seal", _PROOF_SEAL_V1)
    return proof


def _freeze_test_codex_runtime_v1(
    *,
    executable_path: str,
    executable_identity: FileIdentity,
    executable_size: int,
    executable_sha256: str,
) -> FrozenCodexRuntimeV1:
    """Form the only non-production runtime proof used by executable doubles."""

    return _new_runtime_proof_v1(
        project_root_path="",
        executable_path=executable_path,
        executable_identity=executable_identity,
        executable_size=executable_size,
        executable_sha256=executable_sha256,
        cli_version="test-double-v1",
        native_package_version="test-double-v1",
        proof_kind="test_double",
    )


def _require_project_codex_runtime_v1(
    value: object,
) -> FrozenCodexRuntimeV1:
    """Return a resolver-sealed production proof or reject the boundary."""

    if type(value) is not FrozenCodexRuntimeV1:
        raise CodexRuntimeResolutionErrorV1(
            "a sealed project-pinned Codex runtime proof is required"
        )
    if (
        getattr(value, "_proof_seal", None) is not _PROOF_SEAL_V1
        or value.proof_kind != "project_pinned"
    ):
        raise CodexRuntimeResolutionErrorV1(
            "a sealed project-pinned Codex runtime proof is required"
        )
    return value


def _require_test_codex_runtime_v1(value: object) -> FrozenCodexRuntimeV1:
    """Return a private executable-double proof or reject the boundary."""

    if type(value) is not FrozenCodexRuntimeV1:
        raise CodexRuntimeResolutionErrorV1(
            "a sealed test-double Codex runtime proof is required"
        )
    if (
        getattr(value, "_proof_seal", None) is not _PROOF_SEAL_V1
        or value.proof_kind != "test_double"
    ):
        raise CodexRuntimeResolutionErrorV1(
            "a sealed test-double Codex runtime proof is required"
        )
    return value


def _object_without_duplicates(
    pairs: list[tuple[str, object]],
) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise _RuntimeDescriptorMalformed(f"non-JSON numeric constant: {value}")


def _read_json_object(
    root: ValidatedDataRootV1,
    parts: tuple[str, ...],
) -> JsonObject:
    with root.open_relative_file_v1(parts) as descriptor:
        try:
            raw = descriptor.read_bytes_v1(limit=_DESCRIPTOR_LIMIT_BYTES)
        except ValueError as error:
            raise _RuntimeDescriptorMalformed(
                "runtime descriptor exceeds its read limit"
            ) from error
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except _RuntimeDescriptorMalformed:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise _RuntimeDescriptorMalformed("runtime descriptor is malformed") from error
    if type(value) is not dict:
        raise _RuntimeDescriptorMalformed(
            "runtime descriptor is not a JSON object"
        )
    return value


def _required_string(parent: JsonObject, key: str) -> str:
    value = parent.get(key)
    if type(value) is not str or not value or "\0" in value:
        raise _RuntimeDescriptorMalformed(
            f"runtime identity field is malformed: {key}"
        )
    return value


def _parse_runtime_identity(value: JsonObject) -> _RuntimeIdentityV1:
    if (
        set(value) != _IDENTITY_FIELDS
        or type(value.get("identity_version")) is not int
        or value.get("identity_version") != 1
    ):
        raise _RuntimeDescriptorMalformed("runtime identity shape is invalid")
    cli_package_name = _required_string(value, "cli_package_name")
    cli_version = _required_string(value, "cli_version")
    native_package_alias = _required_string(value, "native_package_alias")
    native_package_name = _required_string(value, "native_package_name")
    native_package_version = _required_string(value, "native_package_version")
    main_lock_integrity = _required_string(value, "main_lock_integrity")
    native_lock_integrity = _required_string(value, "native_lock_integrity")
    optional_value = value.get("optional_dependencies")
    executable_value = value.get("executable_relative_parts")
    if (
        cli_package_name != "@openai/codex"
        or native_package_alias != "@openai/codex-win32-x64"
        or native_package_name != cli_package_name
        or native_package_version != f"{cli_version}-win32-x64"
        or not main_lock_integrity.startswith("sha512-")
        or not native_lock_integrity.startswith("sha512-")
    ):
        raise _RuntimeDescriptorMalformed("runtime identity values are invalid")
    if type(optional_value) is not dict or type(executable_value) is not list:
        raise _RuntimeDescriptorMalformed("runtime identity values are invalid")
    optional_object = cast(dict[object, object], optional_value)
    executable_items = cast(list[object], executable_value)
    if any(type(part) is not str for part in executable_items):
        raise _RuntimeDescriptorMalformed("runtime identity values are invalid")
    optional_dependencies: dict[str, str] = {}
    for name, item in optional_object.items():
        if type(name) is not str or type(item) is not str:
            raise _RuntimeDescriptorMalformed("runtime identity closure is invalid")
        optional_dependencies[cast(str, name)] = cast(str, item)
    expected_optional = {
        name: f"npm:@openai/codex@{cli_version}-{suffix}"
        for name, suffix in _OPTIONAL_PLATFORM_SUFFIXES.items()
    }
    executable_parts = tuple(cast(str, part) for part in executable_items)
    if (
        optional_dependencies != expected_optional
        or executable_parts != _EXECUTABLE_WITHIN_NATIVE
    ):
        raise _RuntimeDescriptorMalformed("runtime identity closure is invalid")
    return _RuntimeIdentityV1(
        cli_package_name=cli_package_name,
        cli_version=cli_version,
        native_package_alias=native_package_alias,
        native_package_name=native_package_name,
        native_package_version=native_package_version,
        main_lock_integrity=main_lock_integrity,
        native_lock_integrity=native_lock_integrity,
        optional_dependencies=tuple(sorted(optional_dependencies.items())),
        executable_relative_parts=executable_parts,
    )


def _required_object(parent: JsonObject, key: str) -> JsonObject:
    value = parent.get(key)
    if type(value) is not dict:
        raise _RuntimeDescriptorMalformed(
            f"runtime descriptor field is malformed: {key}"
        )
    return value


def _validate_descriptors(
    runtime_root: ValidatedDataRootV1,
    native_root: ValidatedDataRootV1,
    identity: _RuntimeIdentityV1,
) -> None:
    package = _read_json_object(runtime_root, _PACKAGE_PARTS)
    lock = _read_json_object(runtime_root, _LOCK_PARTS)
    installed_main = _read_json_object(
        runtime_root,
        (
            "node_modules",
            *identity.cli_package_name.split("/"),
            "package.json",
        ),
    )
    installed_native = _read_json_object(native_root, _INSTALLED_NATIVE_PARTS)
    dependency = {identity.cli_package_name: identity.cli_version}
    optional_dependencies = dict(identity.optional_dependencies)

    if package.get("dependencies") != dependency:
        raise ValueError("project package dependency identity is invalid")
    if lock.get("lockfileVersion") != 3:
        raise ValueError("Codex lockfile version is invalid")
    packages = _required_object(lock, "packages")
    root_lock = _required_object(packages, "")
    main_lock = _required_object(
        packages,
        f"node_modules/{identity.cli_package_name}",
    )
    native_lock = _required_object(
        packages,
        f"node_modules/{identity.native_package_alias}",
    )
    if root_lock.get("dependencies") != dependency:
        raise ValueError("root lock dependency identity is invalid")
    if (
        main_lock.get("version") != identity.cli_version
        or main_lock.get("integrity") != identity.main_lock_integrity
        or main_lock.get("optionalDependencies") != optional_dependencies
    ):
        raise ValueError("main lock identity is invalid")
    if (
        native_lock.get("name") != identity.native_package_name
        or native_lock.get("version") != identity.native_package_version
        or native_lock.get("integrity") != identity.native_lock_integrity
    ):
        raise ValueError("native lock identity is invalid")
    if (
        installed_main.get("name") != identity.cli_package_name
        or installed_main.get("version") != identity.cli_version
        or installed_main.get("optionalDependencies") != optional_dependencies
    ):
        raise ValueError("installed main package identity is invalid")
    if (
        installed_native.get("name") != identity.native_package_name
        or installed_native.get("version") != identity.native_package_version
    ):
        raise ValueError("installed native package identity is invalid")


def _resolve_executable(
    native_root: ValidatedDataRootV1,
    identity: _RuntimeIdentityV1,
) -> tuple[str, FileIdentity, int, str]:
    candidates = tuple(
        path
        for path in native_root.relative_file_paths_v1()
        if ntpath.basename(path).casefold() == "codex.exe"
    )
    expected = "/".join(identity.executable_relative_parts)
    if len(candidates) != 1 or candidates[0].casefold() != expected.casefold():
        raise ValueError(
            "native package must contain exactly one codex.exe at the frozen path"
        )
    with native_root.open_relative_file_v1(
        identity.executable_relative_parts
    ) as executable:
        if executable.size <= 0:
            raise ValueError("native Codex executable is empty")
        return (
            executable.canonical_path,
            executable.identity,
            executable.size,
            executable.sha256_v1(),
        )


def resolve_codex_runtime_v1(project_root: Path) -> FrozenCodexRuntimeV1:
    """Prove the pinned native runtime without launching it or consulting PATH."""

    if not isinstance(project_root, Path) or not project_root.is_absolute():
        raise CodexRuntimeResolutionErrorV1(
            "project root must be an absolute pathlib.Path"
    )
    try:
        with open_validated_data_root_v1(str(project_root)) as project:
            canonical_project_root = project.inspection.canonical_path
            if canonical_project_root is None:
                raise ValueError("project root has no canonical path")
            with project.open_relative_data_root_v1(_RUNTIME_PARTS) as runtime_root:
                runtime_identity = _parse_runtime_identity(
                    _read_json_object(runtime_root, _IDENTITY_PARTS)
                )
                with runtime_root.open_relative_data_root_v1(
                    (
                        "node_modules",
                        *runtime_identity.native_package_alias.split("/"),
                    )
                ) as native_root:
                    _validate_descriptors(
                        runtime_root,
                        native_root,
                        runtime_identity,
                    )
                    executable_path, executable_identity, size, sha256 = (
                        _resolve_executable(native_root, runtime_identity)
                    )
    except _RuntimeDescriptorMalformed as error:
        raise CodexRuntimeDescriptorErrorV1(str(error)) from error
    except (
        DataRootLifecycleErrorV1,
        DataRootOpenErrorV1,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        raise CodexRuntimeResolutionErrorV1(str(error)) from error
    return _new_runtime_proof_v1(
        project_root_path=canonical_project_root,
        executable_path=executable_path,
        executable_identity=executable_identity,
        executable_size=size,
        executable_sha256=sha256,
        cli_version=runtime_identity.cli_version,
        native_package_version=runtime_identity.native_package_version,
        proof_kind="project_pinned",
    )
