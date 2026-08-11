from __future__ import annotations

import hashlib
import math
import ntpath
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Literal, Self, TypeAlias, TypeVar, cast

from gezhi._codex_runtime import (
    CodexRuntimeResolutionErrorV1,
    FrozenCodexRuntimeV1,
    _freeze_test_codex_runtime_v1,
    _require_project_codex_runtime_v1,
    _require_test_codex_runtime_v1,
)
from gezhi._windows_data_root import (
    DataRootLifecycleErrorV1,
    DataRootOpenErrorV1,
    FileIdentity,
    open_validated_data_root_v1,
    open_validated_local_file_v1,
    validate_relative_parts_v1,
)

CodexRoleV1: TypeAlias = Literal[
    "literature_reader_v1",
    "knowledge_answerer_v1",
]
CaptureProfileV1: TypeAlias = Literal["literature", "knowledge"]

CODEX_MODEL_V1 = "gpt-5.6-sol"
CODEX_REASONING_EFFORT_V1 = "high"
CODEX_ATTEMPT_TIMEOUT_SECONDS_V1 = 1_800
CODEX_SHARED_WINDOW_SECONDS_V1 = 5_700
CODEX_ATTEMPT_TIMEOUT_NS_V1 = CODEX_ATTEMPT_TIMEOUT_SECONDS_V1 * 1_000_000_000
CODEX_SHARED_WINDOW_NS_V1 = CODEX_SHARED_WINDOW_SECONDS_V1 * 1_000_000_000
_ATTEMPT_ROOT_ENTRIES_V1 = ("captures", "sqlite", "temporary", "working")

# This order is part of Codex Role Invocation v1. Every entry exists in the
# project-pinned Codex 0.146.0 feature registry and removes a model-facing tool
# or an extension discovery path. Provider transport and auth remain enabled.
CODEX_DISABLED_FEATURES_V1 = (
    "apps",
    "auth_elicitation",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "code_mode_host",
    "computer_use",
    "goals",
    "hooks",
    "image_generation",
    "in_app_browser",
    "multi_agent",
    "plugins",
    "request_permissions_tool",
    "skill_mcp_dependency_install",
    "skill_search",
    "shell_tool",
    "tool_call_mcp_elicitation",
    "tool_suggest",
    "workspace_dependencies",
)

_OPTIONAL_ENVIRONMENT_NAMES = (
    "ALL_PROXY",
    "CODEX_ACCESS_TOKEN",
    "CODEX_API_KEY",
    "CODEX_CA_CERTIFICATE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
)
_PLAN_SEAL_V1 = object()
_WORKSPACE_SEAL_V1 = object()


class CodexRolePlanErrorV1(ValueError):
    """The immutable role launch plan could not be formed safely."""


@dataclass(frozen=True, slots=True, init=False)
class FrozenCodexAttemptWorkspaceV1:
    attempt_root: str
    attempt_root_identity: FileIdentity
    working_directory: str
    working_directory_identity: FileIdentity
    temporary_directory: str
    temporary_directory_identity: FileIdentity
    sqlite_home: str
    sqlite_home_identity: FileIdentity
    capture_parent: str
    capture_parent_identity: FileIdentity
    capture_directory: str
    staging_directory: str
    literature_authoritative_root: str
    literature_authoritative_root_identity: FileIdentity
    knowledge_authoritative_root: str
    knowledge_authoritative_root_identity: FileIdentity
    attempt_ordinal: int
    _workspace_seal: object = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def __new__(cls, *_args: object, **_kwargs: object) -> Self:
        raise TypeError(
            "FrozenCodexAttemptWorkspaceV1 can only be created by its builder"
        )


@dataclass(frozen=True, slots=True, init=False)
class FrozenCodexLaunchPlanV1:
    role: CodexRoleV1
    capture_profile: CaptureProfileV1
    runtime: FrozenCodexRuntimeV1
    executable_path: str
    argv: tuple[str, ...]
    quoted_command_line: str
    command_line_sha256: str
    environment_block: str = field(repr=False)
    environment_names: tuple[str, ...]
    attempt_root: str
    attempt_root_identity: FileIdentity | None
    attempt_root_entries: tuple[str, ...]
    working_directory: str
    working_directory_identity: FileIdentity
    working_directory_entries: tuple[str, ...]
    codex_home: str
    codex_home_identity: FileIdentity | None
    codex_home_entries: tuple[str, ...] | None
    temporary_directory: str
    temporary_directory_identity: FileIdentity
    temporary_directory_entries: tuple[str, ...]
    sqlite_home: str
    sqlite_home_identity: FileIdentity | None
    sqlite_home_entries: tuple[str, ...]
    capture_parent: str
    capture_parent_identity: FileIdentity
    capture_parent_entries: tuple[str, ...]
    literature_authoritative_root: str
    literature_authoritative_root_identity: FileIdentity | None
    knowledge_authoritative_root: str
    knowledge_authoritative_root_identity: FileIdentity | None
    schema_path: str
    schema_identity: FileIdentity | None
    schema_size: int | None
    schema_sha256: str | None
    capture_directory: str
    staging_directory: str
    events_staging_path: str
    final_spool_path: str | None
    prompt: bytes = field(repr=False)
    attempt_ordinal: int
    model: str = CODEX_MODEL_V1
    reasoning_effort: str = CODEX_REASONING_EFFORT_V1
    timeout_ns: int = CODEX_ATTEMPT_TIMEOUT_NS_V1
    shared_window_ns: int = CODEX_SHARED_WINDOW_NS_V1
    existing_shared_deadline_monotonic_ns: int | None = None
    target_kind: Literal["production_codex", "test_double"] = "production_codex"
    _plan_seal: object = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def __new__(cls, *_args: object, **_kwargs: object) -> Self:
        raise TypeError(
            "FrozenCodexLaunchPlanV1 can only be created by a role builder"
        )


_SealedValueV1 = TypeVar("_SealedValueV1")


def _materialize_sealed_value_v1(
    cls: type[_SealedValueV1],
    *,
    seal_name: str,
    seal: object,
    facts: Mapping[str, object],
) -> _SealedValueV1:
    fact_names = tuple(
        item.name for item in fields(cast(Any, cls)) if item.name != seal_name
    )
    if set(facts) != set(fact_names):
        raise AssertionError(f"sealed {cls.__name__} facts are incomplete")
    value = object.__new__(cls)
    for name in fact_names:
        object.__setattr__(value, name, facts[name])
    object.__setattr__(value, seal_name, seal)
    return value


def _new_codex_attempt_workspace_v1(
    **facts: object,
) -> FrozenCodexAttemptWorkspaceV1:
    return _materialize_sealed_value_v1(
        FrozenCodexAttemptWorkspaceV1,
        seal_name="_workspace_seal",
        seal=_WORKSPACE_SEAL_V1,
        facts=facts,
    )


def _new_codex_launch_plan_v1(**facts: object) -> FrozenCodexLaunchPlanV1:
    return _materialize_sealed_value_v1(
        FrozenCodexLaunchPlanV1,
        seal_name="_plan_seal",
        seal=_PLAN_SEAL_V1,
        facts=facts,
    )


def _require_codex_launch_plan_v1(
    value: object,
    *,
    target_kind: Literal["production_codex", "test_double"],
) -> FrozenCodexLaunchPlanV1:
    if (
        type(value) is not FrozenCodexLaunchPlanV1
        or getattr(value, "_plan_seal", None) is not _PLAN_SEAL_V1
        or value.target_kind != target_kind
    ):
        raise TypeError(f"a sealed {target_kind} launch plan is required")
    if target_kind == "production_codex":
        try:
            _require_project_codex_runtime_v1(value.runtime)
        except CodexRuntimeResolutionErrorV1 as error:
            raise TypeError("the launch plan runtime proof is invalid") from error
        if (
            not value.attempt_root
            or value.attempt_root_identity is None
            or value.attempt_root_entries != _ATTEMPT_ROOT_ENTRIES_V1
            or not value.literature_authoritative_root
            or value.literature_authoritative_root_identity is None
            or not value.knowledge_authoritative_root
            or value.knowledge_authoritative_root_identity is None
        ):
            raise TypeError("the launch plan root proofs are invalid")
    else:
        try:
            _require_test_codex_runtime_v1(value.runtime)
        except CodexRuntimeResolutionErrorV1 as error:
            raise TypeError(
                "the test launch plan runtime proof is invalid"
            ) from error
    return value


def _quote_windows_argument(value: str) -> str:
    if "\0" in value:
        raise CodexRolePlanErrorV1("argv contains NUL")
    if value and not any(character in " \t\"" for character in value):
        return value
    pieces = ['"']
    backslashes = 0
    for character in value:
        if character == "\\":
            backslashes += 1
            continue
        if character == '"':
            pieces.append("\\" * (backslashes * 2 + 1))
            pieces.append('"')
            backslashes = 0
            continue
        pieces.append("\\" * backslashes)
        pieces.append(character)
        backslashes = 0
    pieces.append("\\" * (backslashes * 2))
    pieces.append('"')
    return "".join(pieces)


def quote_windows_argv_v1(argv: Sequence[str]) -> str:
    if not argv or any(type(item) is not str for item in argv):
        raise CodexRolePlanErrorV1("argv must be a non-empty string sequence")
    return " ".join(_quote_windows_argument(item) for item in argv)


def _canonical_directory_facts(
    path: Path,
    *,
    label: str,
    include_entries: bool = False,
) -> tuple[str, FileIdentity, tuple[str, ...]]:
    if not isinstance(path, Path) or not path.is_absolute():
        raise CodexRolePlanErrorV1(f"{label} must be an absolute pathlib.Path")
    try:
        with open_validated_data_root_v1(str(path)) as opened:
            canonical = opened.inspection.canonical_path
            identity = opened.inspection.identity
            entries = opened.relative_entry_names_v1() if include_entries else ()
    except (DataRootLifecycleErrorV1, DataRootOpenErrorV1) as error:
        raise CodexRolePlanErrorV1(f"{label} is not a trusted directory") from error
    if canonical is None or identity is None:
        raise CodexRolePlanErrorV1(f"{label} has incomplete identity facts")
    return canonical, identity, entries


def _canonical_directory(path: Path, *, label: str) -> str:
    canonical, _identity, _entries = _canonical_directory_facts(
        path,
        label=label,
    )
    return canonical


def _canonical_file_facts(
    path: Path,
    *,
    label: str,
) -> tuple[str, FileIdentity, int, str]:
    if not isinstance(path, Path) or not path.is_absolute():
        raise CodexRolePlanErrorV1(f"{label} must be an absolute pathlib.Path")
    try:
        with open_validated_local_file_v1(str(path)) as opened:
            if opened.size <= 0:
                raise CodexRolePlanErrorV1(f"{label} must not be empty")
            return (
                opened.canonical_path,
                opened.identity,
                opened.size,
                opened.sha256_v1(),
            )
    except (DataRootLifecycleErrorV1, DataRootOpenErrorV1) as error:
        raise CodexRolePlanErrorV1(f"{label} is not a trusted file") from error


def _canonical_file(path: Path, *, label: str) -> str:
    canonical, _identity, _size, _sha256 = _canonical_file_facts(
        path,
        label=label,
    )
    return canonical


def _future_private_paths(
    capture_directory: Path,
    staging_directory: Path,
) -> tuple[str, str]:
    if (
        not isinstance(capture_directory, Path)
        or not isinstance(staging_directory, Path)
        or not capture_directory.is_absolute()
        or not staging_directory.is_absolute()
        or capture_directory.parent != staging_directory.parent
    ):
        raise CodexRolePlanErrorV1(
            "capture and staging directories must be absolute siblings"
        )
    try:
        validate_relative_parts_v1((capture_directory.name,))
        validate_relative_parts_v1((staging_directory.name,))
    except ValueError as error:
        raise CodexRolePlanErrorV1("capture namespace is invalid") from error
    parent = _canonical_directory(capture_directory.parent, label="capture parent")
    capture = str(Path(parent) / capture_directory.name)
    staging = str(Path(parent) / staging_directory.name)
    if os.path.lexists(capture) or os.path.lexists(staging):
        raise CodexRolePlanErrorV1("capture namespace must be fresh")
    return capture, staging


def _source_environment(source: Mapping[str, str]) -> dict[str, str]:
    observed: dict[str, tuple[str, str]] = {}
    for name, value in source.items():
        if type(name) is not str or type(value) is not str:
            raise CodexRolePlanErrorV1("environment must contain strings")
        folded = name.casefold()
        if folded in observed:
            raise CodexRolePlanErrorV1(
                "source environment contains case-colliding names"
            )
        if not name or "=" in name or "\0" in name or "\0" in value:
            raise CodexRolePlanErrorV1("environment entry is invalid")
        observed[folded] = (name, value)
    return {folded: value for folded, (_name, value) in observed.items()}


def _environment_block(
    source: Mapping[str, str],
    *,
    codex_home: str,
    temporary_directory: str,
    sqlite_home: str,
) -> tuple[str, tuple[str, ...]]:
    indexed = _source_environment(source)
    system_root = indexed.get("systemroot")
    if not system_root or "\0" in system_root:
        raise CodexRolePlanErrorV1("SystemRoot is required")
    values = {
        "CODEX_HOME": codex_home,
        "CODEX_SQLITE_HOME": sqlite_home,
        "SystemRoot": system_root,
        "TEMP": temporary_directory,
        "TMP": temporary_directory,
    }
    for canonical_name in _OPTIONAL_ENVIRONMENT_NAMES:
        value = indexed.get(canonical_name.casefold())
        if value:
            values[canonical_name] = value
    names = tuple(sorted(values, key=str.casefold))
    entries = tuple(f"{name}={values[name]}" for name in names)
    if any("\0" in entry for entry in entries):
        raise CodexRolePlanErrorV1("environment value contains NUL")
    return "\0".join(entries) + "\0\0", names


def _base_argv(
    *,
    executable: str,
    working_directory: str,
    schema_path: str,
    final_spool_path: str | None,
) -> tuple[str, ...]:
    argv: list[str] = [
        executable,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--skip-git-repo-check",
        "--model",
        CODEX_MODEL_V1,
        "--sandbox",
        "read-only",
        "--cd",
        working_directory,
        "--output-schema",
        schema_path,
    ]
    if final_spool_path is not None:
        argv.extend(("--output-last-message", final_spool_path))
    argv.extend(
        (
            "--json",
            "--color",
            "never",
            "--config",
            'approval_policy="never"',
            "--config",
            'model_reasoning_effort="high"',
            "--config",
            'web_search="disabled"',
            "--config",
            "agents.enabled=false",
            "--config",
            "allow_login_shell=false",
            "--config",
            'shell_environment_policy.inherit="none"',
        )
    )
    for feature in CODEX_DISABLED_FEATURES_V1:
        argv.extend(("--disable", feature))
    argv.append("-")
    return tuple(argv)


def _paths_overlap(left: str, right: str) -> bool:
    try:
        common = ntpath.commonpath((left, right))
    except ValueError:
        return False
    return common.casefold() in {left.casefold(), right.casefold()}


def freeze_codex_attempt_workspace_v1(
    *,
    attempt_root: Path,
    attempt_ordinal: int,
    literature_authoritative_root: Path,
    knowledge_authoritative_root: Path,
) -> FrozenCodexAttemptWorkspaceV1:
    """Prove one closed, empty attempt namespace outside both data stores."""

    if type(attempt_ordinal) is not int or not 1 <= attempt_ordinal <= 999:
        raise CodexRolePlanErrorV1("attempt ordinal is invalid")
    expected_children = _ATTEMPT_ROOT_ENTRIES_V1
    try:
        with open_validated_data_root_v1(str(attempt_root)) as opened:
            canonical_attempt = opened.inspection.canonical_path
            attempt_identity = opened.inspection.identity
            children = opened.relative_entry_names_v1()
    except (DataRootLifecycleErrorV1, DataRootOpenErrorV1) as error:
        raise CodexRolePlanErrorV1("attempt root is not trusted") from error
    if (
        canonical_attempt is None
        or attempt_identity is None
        or children != expected_children
    ):
        raise CodexRolePlanErrorV1(
            "attempt root must contain only the frozen workspace directories"
        )
    child_paths: dict[str, str] = {}
    child_identities: dict[str, FileIdentity] = {}
    for name in expected_children:
        child = Path(canonical_attempt) / name
        try:
            with open_validated_data_root_v1(str(child)) as opened:
                canonical = opened.inspection.canonical_path
                identity = opened.inspection.identity
                entries = opened.relative_entry_names_v1()
        except (DataRootLifecycleErrorV1, DataRootOpenErrorV1) as error:
            raise CodexRolePlanErrorV1(
                f"attempt workspace directory is not trusted: {name}"
            ) from error
        if canonical is None or identity is None or entries:
            raise CodexRolePlanErrorV1(
                f"attempt workspace directory must be empty: {name}"
            )
        child_paths[name] = canonical
        child_identities[name] = identity
    literature, literature_identity, _literature_entries = (
        _canonical_directory_facts(
        literature_authoritative_root,
        label="Literature authoritative root",
        )
    )
    knowledge, knowledge_identity, _knowledge_entries = (
        _canonical_directory_facts(
        knowledge_authoritative_root,
        label="Knowledge authoritative root",
        )
    )
    if (
        _paths_overlap(literature, knowledge)
        or _paths_overlap(canonical_attempt, literature)
        or _paths_overlap(canonical_attempt, knowledge)
    ):
        raise CodexRolePlanErrorV1(
            "attempt workspace and authoritative roots must be physically isolated"
        )
    capture_parent = child_paths["captures"]
    capture = str(Path(capture_parent) / f"{attempt_ordinal:02d}")
    staging = str(Path(capture_parent) / f".{attempt_ordinal:02d}.codex-stage")
    return _new_codex_attempt_workspace_v1(
        attempt_root=canonical_attempt,
        attempt_root_identity=attempt_identity,
        working_directory=child_paths["working"],
        working_directory_identity=child_identities["working"],
        temporary_directory=child_paths["temporary"],
        temporary_directory_identity=child_identities["temporary"],
        sqlite_home=child_paths["sqlite"],
        sqlite_home_identity=child_identities["sqlite"],
        capture_parent=capture_parent,
        capture_parent_identity=child_identities["captures"],
        capture_directory=capture,
        staging_directory=staging,
        literature_authoritative_root=literature,
        literature_authoritative_root_identity=literature_identity,
        knowledge_authoritative_root=knowledge,
        knowledge_authoritative_root_identity=knowledge_identity,
        attempt_ordinal=attempt_ordinal,
    )


def _require_codex_attempt_workspace_v1(
    value: object,
) -> FrozenCodexAttemptWorkspaceV1:
    if (
        type(value) is not FrozenCodexAttemptWorkspaceV1
        or getattr(value, "_workspace_seal", None) is not _WORKSPACE_SEAL_V1
    ):
        raise CodexRolePlanErrorV1(
            "a sealed Codex attempt workspace proof is required"
        )
    return value


def freeze_codex_role_launch_v1(
    *,
    runtime: FrozenCodexRuntimeV1,
    role: CodexRoleV1,
    prompt: bytes,
    attempt_ordinal: int,
    workspace: FrozenCodexAttemptWorkspaceV1,
    schema_path: Path,
    codex_home: Path,
    source_environment: Mapping[str, str],
    existing_shared_deadline_monotonic_ns: int | None = None,
) -> FrozenCodexLaunchPlanV1:
    try:
        runtime = _require_project_codex_runtime_v1(runtime)
    except CodexRuntimeResolutionErrorV1 as error:
        raise CodexRolePlanErrorV1(
            "a sealed project Codex runtime proof is required"
        ) from error
    if role not in {"literature_reader_v1", "knowledge_answerer_v1"}:
        raise CodexRolePlanErrorV1("Codex role is invalid")
    if type(prompt) is not bytes or not prompt:
        raise CodexRolePlanErrorV1("prompt must be non-empty immutable bytes")
    if type(attempt_ordinal) is not int or not 1 <= attempt_ordinal <= 999:
        raise CodexRolePlanErrorV1("attempt ordinal is invalid")
    workspace = _require_codex_attempt_workspace_v1(workspace)
    if workspace.attempt_ordinal != attempt_ordinal:
        raise CodexRolePlanErrorV1("workspace attempt ordinal does not match")
    revalidated_workspace = freeze_codex_attempt_workspace_v1(
        attempt_root=Path(workspace.attempt_root),
        attempt_ordinal=workspace.attempt_ordinal,
        literature_authoritative_root=Path(
            workspace.literature_authoritative_root
        ),
        knowledge_authoritative_root=Path(
            workspace.knowledge_authoritative_root
        ),
    )
    if revalidated_workspace != workspace:
        raise CodexRolePlanErrorV1("attempt workspace identity changed")
    workspace = revalidated_workspace
    if (
        existing_shared_deadline_monotonic_ns is not None
        and (
            type(existing_shared_deadline_monotonic_ns) is not int
            or existing_shared_deadline_monotonic_ns < 0
        )
    ):
        raise CodexRolePlanErrorV1("shared deadline is invalid")
    executable = runtime.executable_path
    if not nt_path_is_absolute(executable):
        raise CodexRolePlanErrorV1("runtime executable path is not absolute")
    working = workspace.working_directory
    if _paths_overlap(runtime.project_root_path, workspace.attempt_root):
        raise CodexRolePlanErrorV1(
            "attempt workspace must be physically outside the project root"
        )
    schema, schema_identity, schema_size, schema_sha256 = _canonical_file_facts(
        schema_path,
        label="output schema",
    )
    codex_home_path, codex_home_identity, _codex_home_entries = (
        _canonical_directory_facts(
            codex_home,
            label="CODEX_HOME",
        )
    )
    if any(
        _paths_overlap(codex_home_path, forbidden)
        for forbidden in (
            runtime.project_root_path,
            workspace.attempt_root,
            workspace.literature_authoritative_root,
            workspace.knowledge_authoritative_root,
        )
    ):
        raise CodexRolePlanErrorV1(
            "CODEX_HOME must be isolated from project, attempt, and data roots"
        )
    temporary = workspace.temporary_directory
    sqlite = workspace.sqlite_home
    capture, staging = _future_private_paths(
        Path(workspace.capture_directory),
        Path(workspace.staging_directory),
    )
    events_staging = str(Path(staging) / ".events.capture")
    final_spool = str(Path(staging) / ".final_message.spool")
    environment_block, environment_names = _environment_block(
        source_environment,
        codex_home=codex_home_path,
        temporary_directory=temporary,
        sqlite_home=sqlite,
    )
    argv = _base_argv(
        executable=executable,
        working_directory=working,
        schema_path=schema,
        final_spool_path=final_spool,
    )
    quoted = quote_windows_argv_v1(argv)
    return _new_codex_launch_plan_v1(
        role=role,
        capture_profile=(
            "literature" if role == "literature_reader_v1" else "knowledge"
        ),
        runtime=runtime,
        executable_path=executable,
        argv=argv,
        quoted_command_line=quoted,
        command_line_sha256=hashlib.sha256(quoted.encode("utf-16-le")).hexdigest(),
        environment_block=environment_block,
        environment_names=environment_names,
        attempt_root=workspace.attempt_root,
        attempt_root_identity=workspace.attempt_root_identity,
        attempt_root_entries=_ATTEMPT_ROOT_ENTRIES_V1,
        working_directory=working,
        working_directory_identity=workspace.working_directory_identity,
        working_directory_entries=(),
        codex_home=codex_home_path,
        codex_home_identity=codex_home_identity,
        codex_home_entries=None,
        temporary_directory=temporary,
        temporary_directory_identity=workspace.temporary_directory_identity,
        temporary_directory_entries=(),
        sqlite_home=sqlite,
        sqlite_home_identity=workspace.sqlite_home_identity,
        sqlite_home_entries=(),
        capture_parent=str(Path(capture).parent),
        capture_parent_identity=workspace.capture_parent_identity,
        capture_parent_entries=(),
        literature_authoritative_root=workspace.literature_authoritative_root,
        literature_authoritative_root_identity=(
            workspace.literature_authoritative_root_identity
        ),
        knowledge_authoritative_root=workspace.knowledge_authoritative_root,
        knowledge_authoritative_root_identity=(
            workspace.knowledge_authoritative_root_identity
        ),
        schema_path=schema,
        schema_identity=schema_identity,
        schema_size=schema_size,
        schema_sha256=schema_sha256,
        capture_directory=capture,
        staging_directory=staging,
        events_staging_path=events_staging,
        final_spool_path=final_spool,
        prompt=prompt,
        attempt_ordinal=attempt_ordinal,
        model=CODEX_MODEL_V1,
        reasoning_effort=CODEX_REASONING_EFFORT_V1,
        timeout_ns=CODEX_ATTEMPT_TIMEOUT_NS_V1,
        shared_window_ns=CODEX_SHARED_WINDOW_NS_V1,
        existing_shared_deadline_monotonic_ns=existing_shared_deadline_monotonic_ns,
        target_kind="production_codex",
    )


def _freeze_test_double_launch_v1(
    *,
    executable: Path,
    arguments: Sequence[str],
    prompt: bytes,
    attempt_ordinal: int,
    working_directory: Path,
    capture_directory: Path,
    staging_directory: Path,
    temporary_directory: Path,
    source_environment: Mapping[str, str],
    timeout_seconds: float,
    capture_profile: str,
    existing_shared_deadline_monotonic_ns: int | None = None,
) -> FrozenCodexLaunchPlanV1:
    """Build a test-only plan; production composition never calls this seam."""

    if capture_profile not in {"literature", "knowledge"}:
        raise CodexRolePlanErrorV1("test capture profile is invalid")
    if type(prompt) is not bytes or not prompt:
        raise CodexRolePlanErrorV1("test prompt must be non-empty bytes")
    if type(attempt_ordinal) is not int or attempt_ordinal <= 0:
        raise CodexRolePlanErrorV1("test attempt ordinal is invalid")
    if (
        type(timeout_seconds) not in {int, float}
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise CodexRolePlanErrorV1("test timeout is invalid")
    if (
        existing_shared_deadline_monotonic_ns is not None
        and (
            type(existing_shared_deadline_monotonic_ns) is not int
            or existing_shared_deadline_monotonic_ns < 0
        )
    ):
        raise CodexRolePlanErrorV1("test shared deadline is invalid")
    (
        executable_path,
        executable_identity,
        executable_size,
        executable_sha256,
    ) = _canonical_file_facts(executable, label="test executable")
    working, working_identity, working_entries = _canonical_directory_facts(
        working_directory,
        label="working directory",
        include_entries=True,
    )
    temporary, temporary_identity, temporary_entries = (
        _canonical_directory_facts(
            temporary_directory,
            label="temporary directory",
            include_entries=True,
        )
    )
    capture_parent, capture_parent_identity, capture_parent_entries = (
        _canonical_directory_facts(
            capture_directory.parent,
            label="capture parent",
            include_entries=True,
        )
    )
    capture, staging = _future_private_paths(capture_directory, staging_directory)
    indexed = _source_environment(source_environment)
    system_root = indexed.get("systemroot")
    if not system_root:
        raise CodexRolePlanErrorV1("SystemRoot is required")
    environment_values = {
        "SystemRoot": system_root,
        "TEMP": temporary,
        "TMP": temporary,
    }
    environment_names = tuple(sorted(environment_values, key=str.casefold))
    environment_block = "\0".join(
        f"{name}={environment_values[name]}" for name in environment_names
    ) + "\0\0"
    argv = (executable_path, *tuple(arguments))
    quoted = quote_windows_argv_v1(argv)
    runtime = _freeze_test_codex_runtime_v1(
        executable_path=executable_path,
        executable_identity=executable_identity,
        executable_size=executable_size,
        executable_sha256=executable_sha256,
    )
    return _new_codex_launch_plan_v1(
        role=(
            "literature_reader_v1"
            if capture_profile == "literature"
            else "knowledge_answerer_v1"
        ),
        capture_profile=cast(CaptureProfileV1, capture_profile),
        runtime=runtime,
        executable_path=executable_path,
        argv=argv,
        quoted_command_line=quoted,
        command_line_sha256=hashlib.sha256(quoted.encode("utf-16-le")).hexdigest(),
        environment_block=environment_block,
        environment_names=environment_names,
        attempt_root="",
        attempt_root_identity=None,
        attempt_root_entries=(),
        working_directory=working,
        working_directory_identity=working_identity,
        working_directory_entries=working_entries,
        codex_home="",
        codex_home_identity=None,
        codex_home_entries=None,
        temporary_directory=temporary,
        temporary_directory_identity=temporary_identity,
        temporary_directory_entries=temporary_entries,
        sqlite_home="",
        sqlite_home_identity=None,
        sqlite_home_entries=(),
        capture_parent=capture_parent,
        capture_parent_identity=capture_parent_identity,
        capture_parent_entries=capture_parent_entries,
        literature_authoritative_root="",
        literature_authoritative_root_identity=None,
        knowledge_authoritative_root="",
        knowledge_authoritative_root_identity=None,
        schema_path="",
        schema_identity=None,
        schema_size=None,
        schema_sha256=None,
        capture_directory=capture,
        staging_directory=staging,
        events_staging_path=str(Path(staging) / ".events.capture"),
        final_spool_path=str(Path(staging) / ".final_message.spool"),
        prompt=prompt,
        attempt_ordinal=attempt_ordinal,
        model=CODEX_MODEL_V1,
        reasoning_effort=CODEX_REASONING_EFFORT_V1,
        timeout_ns=math.ceil(float(timeout_seconds) * 1_000_000_000),
        shared_window_ns=CODEX_SHARED_WINDOW_NS_V1,
        existing_shared_deadline_monotonic_ns=(
            existing_shared_deadline_monotonic_ns
        ),
        target_kind="test_double",
    )


def nt_path_is_absolute(value: str) -> bool:
    # pathlib.Path follows the host flavor, but keeping this helper explicit
    # makes the Windows-only contract visible and testable.
    return bool(value) and Path(value).is_absolute()
