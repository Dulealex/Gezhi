from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from gezhi import _windows_data_root as windows_root
from gezhi._codex_role_plan import (
    CODEX_DISABLED_FEATURES_V1,
    CodexRolePlanErrorV1,
    FrozenCodexAttemptWorkspaceV1,
    _freeze_test_double_launch_v1,
    _require_codex_launch_plan_v1,
    freeze_codex_attempt_workspace_v1,
    freeze_codex_role_launch_v1,
    quote_windows_argv_v1,
)
from gezhi._codex_runtime import resolve_codex_runtime_v1
from tests.support.codex_runtime_fixture_v1 import (
    build_project_codex_runtime_fixture_v1,
)


@pytest.fixture(autouse=True)
def _allow_pytest_temporary_short_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )


def _create_attempt_root(path: Path) -> None:
    path.mkdir(parents=True)
    for name in ("captures", "sqlite", "temporary", "working"):
        (path / name).mkdir()


def _paths(tmp_path: Path) -> dict[str, Path]:
    project = tmp_path / "project"
    project.mkdir()
    executable = build_project_codex_runtime_fixture_v1(project)
    schema = project / "schemas" / "role-output-v1.json"
    schema.parent.mkdir()
    schema.write_text("{}", encoding="utf-8")

    attempt = tmp_path / "attempt"
    _create_attempt_root(attempt)
    literature = tmp_path / "literature-authoritative"
    knowledge = tmp_path / "knowledge-authoritative"
    codex_home = tmp_path / "codex-home"
    for path in (literature, knowledge, codex_home):
        path.mkdir()
    return {
        "project": project,
        "executable": executable,
        "attempt": attempt,
        "working": attempt / "working",
        "codex_home": codex_home,
        "temporary": attempt / "temporary",
        "sqlite_home": attempt / "sqlite",
        "capture_parent": attempt / "captures",
        "capture": attempt / "captures" / "01",
        "staging": attempt / "captures" / ".01.codex-stage",
        "literature": literature,
        "knowledge": knowledge,
        "schema": schema,
    }


def _workspace(
    paths: dict[str, Path],
    *,
    role: str = "literature_reader_v1",
) -> FrozenCodexAttemptWorkspaceV1:
    if role == "literature_reader_v1":
        return freeze_codex_attempt_workspace_v1(
            role="literature_reader_v1",
            attempt_root=paths["attempt"],
            attempt_ordinal=1,
            literature_authoritative_root=paths["literature"],
        )
    return freeze_codex_attempt_workspace_v1(
        role="knowledge_answerer_v1",
        attempt_root=paths["attempt"],
        attempt_ordinal=1,
        knowledge_authoritative_root=paths["knowledge"],
    )


def _freeze(
    tmp_path: Path,
    *,
    environment: dict[str, str] | None = None,
    existing_shared_deadline_monotonic_ns: object = None,
):
    paths = _paths(tmp_path)
    source = {
        "SystemRoot": os.environ["SystemRoot"],
        "CODEX_API_KEY": "secret-test-key",
        "UNRELATED_SECRET": "must-not-be-inherited",
    }
    if environment is not None:
        source = environment
    plan = freeze_codex_role_launch_v1(
        runtime=resolve_codex_runtime_v1(paths["project"]),
        role="literature_reader_v1",
        prompt=b"prompt bytes\x00stay-on-stdin",
        attempt_ordinal=1,
        workspace=_workspace(paths),
        schema_path=paths["schema"],
        codex_home=paths["codex_home"],
        source_environment=source,
        existing_shared_deadline_monotonic_ns=(
            existing_shared_deadline_monotonic_ns  # type: ignore[arg-type]
        ),
    )
    return plan, paths


def test_role_plan_freezes_exact_locked_codex_invocation(tmp_path: Path) -> None:
    plan, paths = _freeze(tmp_path)
    final_spool = paths["staging"] / ".final_message.spool"
    expected = (
        str(paths["executable"]),
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--skip-git-repo-check",
        "--model",
        "gpt-5.6-sol",
        "--sandbox",
        "read-only",
        "--cd",
        str(paths["working"]),
        "--output-schema",
        str(paths["schema"]),
        "--output-last-message",
        str(final_spool),
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
        *(item for feature in CODEX_DISABLED_FEATURES_V1 for item in ("--disable", feature)),
        "-",
    )

    assert plan.argv == expected
    assert plan.quoted_command_line == quote_windows_argv_v1(expected)
    assert b"prompt bytes" not in plan.quoted_command_line.encode("utf-8")
    assert plan.prompt == b"prompt bytes\x00stay-on-stdin"
    assert plan.model == "gpt-5.6-sol"
    assert plan.reasoning_effort == "high"
    assert plan.timeout_ns == 1_800_000_000_000
    assert plan.shared_window_ns == 5_700_000_000_000
    assert plan.capture_profile == "literature"


def test_role_environment_is_a_sorted_closed_allowlist(tmp_path: Path) -> None:
    plan, paths = _freeze(tmp_path)
    entries = tuple(item for item in plan.environment_block.split("\0") if item)

    assert entries == tuple(sorted(entries, key=str.casefold))
    assert entries == (
        "CODEX_API_KEY=secret-test-key",
        f"CODEX_HOME={paths['codex_home']}",
        f"CODEX_SQLITE_HOME={paths['sqlite_home']}",
        f"SystemRoot={os.environ['SystemRoot']}",
        f"TEMP={paths['temporary']}",
        f"TMP={paths['temporary']}",
    )
    assert plan.environment_block.endswith("\0\0")
    assert "UNRELATED_SECRET" not in plan.environment_block
    assert "PATH=" not in plan.environment_block.upper()
    assert "secret-test-key" not in repr(plan)


def test_sealed_workspace_cannot_be_cloned_with_replaced_facts(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    workspace = _workspace(paths)

    with pytest.raises(TypeError, match="can only be created by its builder"):
        replace(workspace, attempt_root=str(paths["literature"]))


def test_sealed_launch_plan_cannot_be_cloned_with_replaced_facts(
    tmp_path: Path,
) -> None:
    plan, paths = _freeze(tmp_path)
    replacements = (
        {"argv": (plan.executable_path, "exec", "--dangerous")},
        {"environment_block": "PATH=C:\\untrusted\0\0"},
        {"schema_path": str(paths["literature"] / "forged.json")},
    )

    for changes in replacements:
        with pytest.raises(TypeError, match="can only be created by a role builder"):
            replace(plan, **changes)


@pytest.mark.parametrize(
    "argv",
    [
        ("plain.exe", ""),
        (r"C:\Program Files\codex.exe", "a b", 'a"b', "tail\\"),
        ("x.exe", "tab\there", r"before\\\"after"),
    ],
)
def test_windows_quoting_round_trips_with_command_line_to_argv(
    argv: tuple[str, ...],
) -> None:
    import ctypes

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    command_line_to_argv = shell32.CommandLineToArgvW
    command_line_to_argv.argtypes = [
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_int),
    ]
    command_line_to_argv.restype = ctypes.POINTER(ctypes.c_wchar_p)
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    count = ctypes.c_int()
    parsed = command_line_to_argv(quote_windows_argv_v1(argv), ctypes.byref(count))
    assert parsed
    try:
        assert tuple(parsed[index] for index in range(count.value)) == argv
    finally:
        assert local_free(parsed) in {None, 0}


def test_role_plan_rejects_case_colliding_environment_names(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    with pytest.raises(CodexRolePlanErrorV1, match="case-colliding"):
        freeze_codex_role_launch_v1(
            runtime=resolve_codex_runtime_v1(paths["project"]),
            role="knowledge_answerer_v1",
            prompt=b"question",
            attempt_ordinal=1,
            workspace=_workspace(paths, role="knowledge_answerer_v1"),
            schema_path=paths["schema"],
            codex_home=paths["codex_home"],
            source_environment={
                "SystemRoot": os.environ["SystemRoot"],
                "HTTPS_PROXY": "https://one.invalid",
                "https_proxy": "https://two.invalid",
            },
        )


def test_role_plan_rejects_a_workspace_sealed_for_another_role(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)

    with pytest.raises(CodexRolePlanErrorV1, match="workspace role does not match"):
        freeze_codex_role_launch_v1(
            runtime=resolve_codex_runtime_v1(paths["project"]),
            role="knowledge_answerer_v1",
            prompt=b"question",
            attempt_ordinal=1,
            workspace=_workspace(paths),
            schema_path=paths["schema"],
            codex_home=paths["codex_home"],
            source_environment={"SystemRoot": os.environ["SystemRoot"]},
        )


def test_role_plan_rejects_an_attempt_workspace_inside_the_project(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    inside_attempt = paths["project"] / "attempt"
    _create_attempt_root(inside_attempt)
    workspace = freeze_codex_attempt_workspace_v1(
        role="literature_reader_v1",
        attempt_root=inside_attempt,
        attempt_ordinal=1,
        literature_authoritative_root=paths["literature"],
    )

    with pytest.raises(CodexRolePlanErrorV1, match="outside the project root"):
        freeze_codex_role_launch_v1(
            runtime=resolve_codex_runtime_v1(paths["project"]),
            role="literature_reader_v1",
            prompt=b"prompt",
            attempt_ordinal=1,
            workspace=workspace,
            schema_path=paths["schema"],
            codex_home=paths["codex_home"],
            source_environment={"SystemRoot": os.environ["SystemRoot"]},
        )


@pytest.mark.parametrize(
    "deadline",
    [float("nan"), float("inf"), float("-inf"), 1.0, True, -1],
)
def test_role_plan_rejects_non_integer_or_negative_shared_deadlines(
    tmp_path: Path,
    deadline: object,
) -> None:
    with pytest.raises(CodexRolePlanErrorV1, match="shared deadline is invalid"):
        _freeze(
            tmp_path,
            existing_shared_deadline_monotonic_ns=deadline,
        )


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), float("-inf")])
def test_test_double_plan_rejects_non_finite_timeout(
    tmp_path: Path,
    timeout: float,
) -> None:
    working = tmp_path / "working"
    temporary = tmp_path / "temporary"
    captures = tmp_path / "captures"
    for path in (working, temporary, captures):
        path.mkdir()
    with pytest.raises(CodexRolePlanErrorV1, match="test timeout is invalid"):
        _freeze_test_double_launch_v1(
            executable=Path(sys.executable),
            arguments=("-c", "pass"),
            prompt=b"prompt",
            attempt_ordinal=1,
            working_directory=working,
            capture_directory=captures / "01",
            staging_directory=captures / ".01.codex-stage",
            temporary_directory=temporary,
            source_environment={"SystemRoot": os.environ["SystemRoot"]},
            timeout_seconds=timeout,
            capture_profile="literature",
        )


def test_test_double_plan_rejects_a_runtime_with_a_forged_seal(
    tmp_path: Path,
) -> None:
    working = tmp_path / "working"
    temporary = tmp_path / "temporary"
    captures = tmp_path / "captures"
    for path in (working, temporary, captures):
        path.mkdir()
    plan = _freeze_test_double_launch_v1(
        executable=Path(sys.executable),
        arguments=("-c", "pass"),
        prompt=b"prompt",
        attempt_ordinal=1,
        working_directory=working,
        capture_directory=captures / "01",
        staging_directory=captures / ".01.codex-stage",
        temporary_directory=temporary,
        source_environment={"SystemRoot": os.environ["SystemRoot"]},
        timeout_seconds=10,
        capture_profile="literature",
    )
    object.__setattr__(plan.runtime, "_proof_seal", object())

    with pytest.raises(TypeError, match="runtime proof is invalid"):
        _require_codex_launch_plan_v1(plan, target_kind="test_double")


def test_attempt_workspace_rejects_an_unexpected_immediate_entry(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    (paths["attempt"] / "AGENTS.md").write_text("untrusted", encoding="utf-8")

    with pytest.raises(CodexRolePlanErrorV1, match="contain only"):
        _workspace(paths)


def test_literature_workspace_does_not_probe_the_knowledge_root(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    workspace = freeze_codex_attempt_workspace_v1(
        role="literature_reader_v1",
        attempt_root=paths["attempt"],
        attempt_ordinal=1,
        literature_authoritative_root=paths["literature"],
    )

    assert workspace.literature_authoritative_root
    assert workspace.literature_authoritative_root_identity is not None
    assert workspace.knowledge_authoritative_root == ""
    assert workspace.knowledge_authoritative_root_identity is None


def test_knowledge_workspace_does_not_probe_the_literature_root(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    workspace = freeze_codex_attempt_workspace_v1(
        role="knowledge_answerer_v1",
        attempt_root=paths["attempt"],
        attempt_ordinal=1,
        knowledge_authoritative_root=paths["knowledge"],
    )

    assert workspace.knowledge_authoritative_root
    assert workspace.knowledge_authoritative_root_identity is not None
    assert workspace.literature_authoritative_root == ""
    assert workspace.literature_authoritative_root_identity is None


def test_attempt_workspace_rejects_overlap_with_authoritative_data(
    tmp_path: Path,
) -> None:
    literature = tmp_path / "literature-authoritative"
    literature.mkdir()
    attempt = literature / "attempt"
    _create_attempt_root(attempt)

    with pytest.raises(CodexRolePlanErrorV1, match="physically isolated"):
        freeze_codex_attempt_workspace_v1(
            role="literature_reader_v1",
            attempt_root=attempt,
            attempt_ordinal=1,
            literature_authoritative_root=literature,
        )
