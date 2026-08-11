from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from gezhi import _codex_runtime as codex_runtime
from gezhi import _windows_data_root as windows_root
from gezhi._codex_runtime import (
    CodexRuntimeDescriptorErrorV1,
    CodexRuntimeResolutionErrorV1,
    FrozenCodexRuntimeV1,
    _freeze_test_codex_runtime_v1,
    _require_project_codex_runtime_v1,
    _require_test_codex_runtime_v1,
    resolve_codex_runtime_v1,
)
from tests.support.codex_runtime_fixture_v1 import (
    build_project_codex_runtime_fixture_v1,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CLI_VERSION = "0.146.0"
_NATIVE_VERSION = "0.146.0-win32-x64"
_MAIN_INTEGRITY = (
    "sha512-yG3sPWNda/2YAIQIDq9MrrjoCTIQ7rxYM5IasrG3VBcuhCLTkgeg/"
    "JzqmJq1V98RE4MJ5jCxDXXQlOjrditFRw=="
)
_NATIVE_INTEGRITY = (
    "sha512-b3lxMYeR0+IhstNo4JjX1P9cPc1xwVcCVkPd1lD1wpWPJ0SBhpIkP"
    "czwbu3ZRkJcdyl342+rgyf4DUrbZLdrGA=="
)
_OPTIONAL_DEPENDENCIES = {
    "@openai/codex-darwin-arm64": "npm:@openai/codex@0.146.0-darwin-arm64",
    "@openai/codex-darwin-x64": "npm:@openai/codex@0.146.0-darwin-x64",
    "@openai/codex-linux-arm64": "npm:@openai/codex@0.146.0-linux-arm64",
    "@openai/codex-linux-x64": "npm:@openai/codex@0.146.0-linux-x64",
    "@openai/codex-win32-arm64": "npm:@openai/codex@0.146.0-win32-arm64",
    "@openai/codex-win32-x64": "npm:@openai/codex@0.146.0-win32-x64",
}
_IDENTITY = {
    "identity_version": 1,
    "cli_package_name": "@openai/codex",
    "cli_version": _CLI_VERSION,
    "native_package_alias": "@openai/codex-win32-x64",
    "native_package_name": "@openai/codex",
    "native_package_version": _NATIVE_VERSION,
    "main_lock_integrity": _MAIN_INTEGRITY,
    "native_lock_integrity": _NATIVE_INTEGRITY,
    "optional_dependencies": _OPTIONAL_DEPENDENCIES,
    "executable_relative_parts": [
        "vendor",
        "x86_64-pc-windows-msvc",
        "bin",
        "codex.exe",
    ],
}


@pytest.fixture(autouse=True)
def _allow_pytest_temporary_short_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_versioned_identity_matches_package_lock_and_powershell_entry() -> None:
    runtime = _REPOSITORY_ROOT / "runtimes" / "codex"
    identity = json.loads(
        (runtime / "runtime-identity-v1.json").read_text(encoding="utf-8")
    )
    package = json.loads((runtime / "package.json").read_text(encoding="utf-8"))
    lock = json.loads(
        (runtime / "package-lock.json").read_text(encoding="utf-8")
    )
    packages = lock["packages"]

    assert identity == _IDENTITY
    assert package["dependencies"] == {
        identity["cli_package_name"]: identity["cli_version"]
    }
    assert packages[""]["dependencies"] == package["dependencies"]
    main_lock = packages["node_modules/@openai/codex"]
    assert main_lock["version"] == identity["cli_version"]
    assert main_lock["integrity"] == identity["main_lock_integrity"]
    assert (
        main_lock["optionalDependencies"]
        == identity["optional_dependencies"]
    )
    native_lock = packages["node_modules/@openai/codex-win32-x64"]
    assert native_lock["name"] == identity["native_package_name"]
    assert native_lock["version"] == identity["native_package_version"]
    assert native_lock["integrity"] == identity["native_lock_integrity"]

    script = (_REPOSITORY_ROOT / "tools" / "codex.ps1").read_text(
        encoding="utf-8"
    )
    assert "runtime-identity-v1.json" in script
    assert _CLI_VERSION not in script
    assert _NATIVE_VERSION not in script


def test_resolver_returns_one_sticky_native_identity_without_launching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = build_project_codex_runtime_fixture_v1(tmp_path)

    def forbidden_launch(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the static resolver must not launch a process")

    monkeypatch.setattr("subprocess.Popen", forbidden_launch)
    proof = resolve_codex_runtime_v1(tmp_path)

    assert Path(proof.executable_path) == executable
    assert Path(proof.project_root_path) == tmp_path
    assert proof.proof_kind == "project_pinned"
    assert proof.cli_version == "0.146.0"
    assert proof.native_package_version == "0.146.0-win32-x64"
    assert proof.executable_size == len(b"test-only-not-an-executable")
    assert proof.executable_sha256 == hashlib.sha256(
        b"test-only-not-an-executable"
    ).hexdigest()
    assert all(value > 0 for value in proof.executable_identity)
    assert _require_project_codex_runtime_v1(proof) is proof


def test_runtime_proof_is_sealed_and_test_proof_cannot_enter_production(
    tmp_path: Path,
) -> None:
    executable = build_project_codex_runtime_fixture_v1(tmp_path)

    with pytest.raises(TypeError, match="resolver or private test factory"):
        FrozenCodexRuntimeV1(  # type: ignore[call-arg]
            project_root_path=str(tmp_path),
            executable_path=str(executable),
            executable_identity=(1, 2),
            executable_size=3,
            cli_version=_CLI_VERSION,
            native_package_version=_NATIVE_VERSION,
            proof_kind="project_pinned",
        )

    project_proof = resolve_codex_runtime_v1(tmp_path)
    test_proof = _freeze_test_codex_runtime_v1(
        executable_path=project_proof.executable_path,
        executable_identity=project_proof.executable_identity,
        executable_size=project_proof.executable_size,
        executable_sha256=project_proof.executable_sha256,
    )

    assert test_proof.proof_kind == "test_double"
    assert _require_test_codex_runtime_v1(test_proof) is test_proof
    with pytest.raises(CodexRuntimeResolutionErrorV1, match="project-pinned"):
        _require_project_codex_runtime_v1(test_proof)
    with pytest.raises(CodexRuntimeResolutionErrorV1, match="test-double"):
        _require_test_codex_runtime_v1(project_proof)


def test_resolver_uses_one_held_project_root_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_project_codex_runtime_fixture_v1(tmp_path)
    opened: list[str] = []
    real_open = codex_runtime.open_validated_data_root_v1

    def observe_open(value: str) -> windows_root.ValidatedDataRootV1:
        opened.append(value)
        return real_open(value)

    monkeypatch.setattr(codex_runtime, "open_validated_data_root_v1", observe_open)

    resolve_codex_runtime_v1(tmp_path)

    assert opened == [str(tmp_path)]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda lock, _main, _native: lock["packages"][
                "node_modules/@openai/codex"
            ].__setitem__("integrity", "sha512-wrong"),
            "main lock identity",
        ),
        (
            lambda _lock, main, _native: main.__setitem__("name", "lookalike"),
            "installed main package identity",
        ),
        (
            lambda _lock, _main, native: native.__setitem__(
                "version", "0.146.1-win32-x64"
            ),
            "installed native package identity",
        ),
    ],
)
def test_resolver_rejects_descriptor_identity_drift(
    tmp_path: Path,
    mutate: object,
    message: str,
) -> None:
    build_project_codex_runtime_fixture_v1(tmp_path)
    runtime = tmp_path / "runtimes" / "codex"
    lock_path = runtime / "package-lock.json"
    main_path = runtime / "node_modules" / "@openai" / "codex" / "package.json"
    native_path = (
        runtime
        / "node_modules"
        / "@openai"
        / "codex-win32-x64"
        / "package.json"
    )
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    main = json.loads(main_path.read_text(encoding="utf-8"))
    native = json.loads(native_path.read_text(encoding="utf-8"))
    assert callable(mutate)
    mutate(lock, main, native)  # type: ignore[operator]
    _write_json(lock_path, lock)
    _write_json(main_path, main)
    _write_json(native_path, native)

    with pytest.raises(CodexRuntimeResolutionErrorV1, match=message):
        resolve_codex_runtime_v1(tmp_path)


def test_resolver_rejects_a_second_codex_executable_leaf(tmp_path: Path) -> None:
    executable = build_project_codex_runtime_fixture_v1(tmp_path)
    second = executable.parents[2] / "other" / "codex.exe"
    second.parent.mkdir()
    second.write_bytes(b"second")

    with pytest.raises(
        CodexRuntimeResolutionErrorV1,
        match="exactly one codex.exe",
    ):
        resolve_codex_runtime_v1(tmp_path)


def test_resolver_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    build_project_codex_runtime_fixture_v1(tmp_path)
    package = tmp_path / "runtimes" / "codex" / "package.json"
    package.write_text(
        '{"dependencies":{"@openai/codex":"0.146.0"},'
        '"dependencies":{"@openai/codex":"0.146.0"}}',
        encoding="utf-8",
    )

    with pytest.raises(
        CodexRuntimeResolutionErrorV1,
        match="duplicate JSON key",
    ):
        resolve_codex_runtime_v1(tmp_path)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_resolver_rejects_non_json_numeric_constants(
    tmp_path: Path,
    constant: str,
) -> None:
    build_project_codex_runtime_fixture_v1(tmp_path)
    package = tmp_path / "runtimes" / "codex" / "package.json"
    package.write_text(
        '{"dependencies":{"@openai/codex":"0.146.0"},'
        f'"untrusted":{constant}}}',
        encoding="utf-8",
    )

    with pytest.raises(CodexRuntimeDescriptorErrorV1, match="non-JSON"):
        resolve_codex_runtime_v1(tmp_path)


def test_resolver_closes_a_deep_json_recursion_failure(
    tmp_path: Path,
) -> None:
    build_project_codex_runtime_fixture_v1(tmp_path)
    package = tmp_path / "runtimes" / "codex" / "package.json"
    depth = 2_000
    package.write_text(
        '{"dependencies":' + ("[" * depth) + "0" + ("]" * depth) + "}",
        encoding="utf-8",
    )

    with pytest.raises(CodexRuntimeDescriptorErrorV1, match="malformed"):
        resolve_codex_runtime_v1(tmp_path)
