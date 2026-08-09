from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import pytest
from launcher_support import REPOSITORY_ROOT

from gezhi import _doctor_runtime as runtime
from gezhi import _windows_data_root as windows_root
from gezhi._bounded_probe import ProbeLifecycleError, ProbeUnavailableError
from gezhi._doctor_runtime import (
    probe_codex_runtime_v1,
    probe_core_environment_v1,
    probe_ocr_runtime_v1,
)


def _ready_root(
    identity: tuple[int, int],
    ancestors: tuple[tuple[int, int], ...],
) -> runtime.DataRootInspectionV1:
    return runtime.DataRootInspectionV1(
        status="ready",
        canonical_path=r"D:\canonical",
        identity=identity,
        ancestor_identities=ancestors,
    )


def _prepare_observer_project(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.toml").write_text(
        'config_version = "gezhi.config.v1"\n',
        encoding="utf-8",
    )
    literature_root = tmp_path / "data" / "literature"
    knowledge_root = tmp_path / "data" / "knowledge"
    literature_root.mkdir(parents=True)
    knowledge_root.mkdir()
    return literature_root, knowledge_root


def test_frozen_core_python_and_direct_dependencies_are_ready() -> None:
    assert probe_core_environment_v1() == ("ready", "ready")


def test_core_probe_blocks_drifted_project_entry_point_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_distribution = runtime.importlib.metadata.distribution
    malformed_distribution = SimpleNamespace(
        version="0.1.0",
        entry_points=(),
        read_text=lambda _name: (
            '{"url":"file:///E:/Gezhi","dir_info":{"editable":true}}'
        ),
    )
    monkeypatch.setattr(
        runtime.importlib.metadata,
        "distribution",
        lambda name: (
            malformed_distribution
            if name == "gezhi"
            else real_distribution(name)
        ),
    )

    assert probe_core_environment_v1() == ("ready", "blocked")


def test_core_probe_blocks_duplicate_global_console_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate = SimpleNamespace(value="gezhi.bootstrap:main")
    monkeypatch.setattr(
        runtime.importlib.metadata,
        "entry_points",
        lambda **_selection: (duplicate, duplicate),
    )

    assert probe_core_environment_v1() == ("ready", "blocked")


def test_core_probe_preserves_python_fact_when_dependency_inspection_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(_distribution: str) -> str:
        raise RuntimeError("metadata inspection fault")

    monkeypatch.setattr(runtime.importlib.metadata, "version", explode)

    assert probe_core_environment_v1() == ("ready", "failed")


def test_core_probe_classifies_an_import_timeout_as_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> object:
        raise runtime.subprocess.TimeoutExpired(("python",), 30)

    monkeypatch.setattr(runtime, "run_bounded_probe_v1", timeout)

    assert probe_core_environment_v1() == ("ready", "blocked")


def test_core_probe_classifies_an_unavailable_executable_as_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise ProbeUnavailableError("missing executable")

    monkeypatch.setattr(runtime, "run_bounded_probe_v1", unavailable)

    assert probe_core_environment_v1() == ("ready", "blocked")


def test_core_probe_reports_a_job_lifecycle_fault_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def lifecycle_fault(*_args: object, **_kwargs: object) -> object:
        raise ProbeLifecycleError("job invariant failed")

    monkeypatch.setattr(runtime, "run_bounded_probe_v1", lifecycle_fault)

    with pytest.raises(ProbeLifecycleError, match="job invariant failed"):
        runtime._probe_core_dependencies_v1()
    assert probe_core_environment_v1() == ("ready", "failed")


def test_project_locked_codex_identity_and_login_are_ready() -> None:
    assert probe_codex_runtime_v1(project_root=Path(r"E:\Gezhi")) == "ready"


def test_frozen_ocr_runtime_and_local_model_snapshot_are_ready() -> None:
    assert (
        probe_ocr_runtime_v1(
            project_root=REPOSITORY_ROOT,
            deployment_root=Path(r"E:\Gezhi"),
        )
        == "ready"
    )


def test_ocr_probe_environment_is_closed_over_provider_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINERU_MODEL_SOURCE", "modelscope")
    monkeypatch.setenv("MODELSCOPE_CACHE", r"D:\remote-cache")
    monkeypatch.setenv("MODELSCOPE_OFFLINE", "invented")
    monkeypatch.setenv("HF_HOME", r"D:\hf")
    monkeypatch.setenv("TRANSFORMERS_CACHE", r"D:\transformers")
    monkeypatch.setenv("NO_PROXY", "example.invalid")
    monkeypatch.setenv("UNRELATED", "preserved")
    config_path = Path(r"E:\Gezhi\.local\mineru\mineru.json")

    environment = runtime._ocr_probe_environment(config_path)

    assert environment["UNRELATED"] == "preserved"
    assert {
        name: environment.get(name)
        for name in (
            "MINERU_TOOLS_CONFIG_JSON",
            "MINERU_MODEL_SOURCE",
            "MINERU_DEVICE_MODE",
            "HF_HUB_OFFLINE",
            "TRANSFORMERS_OFFLINE",
            "NO_PROXY",
            "MODELSCOPE_CACHE",
            "MODELSCOPE_OFFLINE",
            "HF_HOME",
            "TRANSFORMERS_CACHE",
        )
    } == {
        "MINERU_TOOLS_CONFIG_JSON": str(config_path),
        "MINERU_MODEL_SOURCE": "local",
        "MINERU_DEVICE_MODE": "cuda",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "NO_PROXY": "127.0.0.1,localhost",
        "MODELSCOPE_CACHE": None,
        "MODELSCOPE_OFFLINE": None,
        "HF_HOME": None,
        "TRANSFORMERS_CACHE": None,
    }


def test_doctor_observer_composes_ready_checks_without_mutating_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.toml").write_text(
        'config_version = "gezhi.config.v1"\n',
        encoding="utf-8",
    )
    literature_root = tmp_path / "data" / "literature"
    knowledge_root = tmp_path / "data" / "knowledge"
    literature_root.mkdir(parents=True)
    knowledge_root.mkdir()
    monkeypatch.setattr(
        runtime,
        "probe_core_environment_v1",
        lambda: ("ready", "ready"),
    )
    monkeypatch.setattr(runtime, "probe_ocr_runtime_v1", lambda **_kwargs: "ready")
    monkeypatch.setattr(runtime, "probe_codex_runtime_v1", lambda **_kwargs: "ready")
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )

    observations = runtime._observe_doctor_v1(
        project_root=tmp_path,
        deployment_root=tmp_path,
        cli_patch=(
            ("literature.data_root", str(literature_root)),
            ("knowledge.data_root", str(knowledge_root)),
        ),
        environ={},
    )

    assert observations == (
        ("configuration", "ready", None),
        ("core_python", "ready", None),
        ("core_dependencies", "ready", None),
        ("literature_data_root", "ready", None),
        ("knowledge_data_root", "ready", None),
        ("ocr_runtime", "ready", None),
        ("codex_runtime", "ready", None),
    )


def test_doctor_observer_keeps_independent_checks_after_invalid_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime,
        "probe_core_environment_v1",
        lambda: ("blocked", "ready"),
    )
    monkeypatch.setattr(runtime, "probe_ocr_runtime_v1", lambda **_kwargs: "blocked")
    monkeypatch.setattr(runtime, "probe_codex_runtime_v1", lambda **_kwargs: "ready")

    observations = runtime._observe_doctor_v1(
        project_root=tmp_path,
        deployment_root=tmp_path,
        cli_patch=(),
        environ={},
    )

    assert observations == (
        ("configuration", "blocked", "configuration_invalid"),
        ("core_python", "blocked", "core_environment_unavailable"),
        ("core_dependencies", "ready", None),
        ("literature_data_root", "not_checked", None),
        ("knowledge_data_root", "not_checked", None),
        ("ocr_runtime", "blocked", "ocr_environment_unavailable"),
        ("codex_runtime", "ready", None),
    )


def test_doctor_observer_rejects_a_root_that_physically_equals_the_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.toml").write_text(
        'config_version = "gezhi.config.v1"\n',
        encoding="utf-8",
    )
    literature_value = r"D:\Literature"
    knowledge_value = r"Q:\Knowledge"
    project_identity = (7, 11)

    def inspect(value: str) -> runtime.DataRootInspectionV1:
        if value == str(tmp_path):
            return _ready_root(project_identity, ((7, 1), project_identity))
        if value == literature_value:
            return _ready_root(project_identity, ((7, 1), project_identity))
        return _ready_root((9, 13), ((9, 1), (9, 13)))

    class Capability:
        def __init__(self, value: str) -> None:
            self.inspection = inspect(value)

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(
        runtime,
        "open_validated_data_root_v1",
        lambda value: Capability(value),
    )
    monkeypatch.setattr(
        runtime,
        "probe_core_environment_v1",
        lambda: ("ready", "ready"),
    )
    monkeypatch.setattr(runtime, "probe_ocr_runtime_v1", lambda **_kwargs: "ready")
    monkeypatch.setattr(runtime, "probe_codex_runtime_v1", lambda **_kwargs: "ready")

    observations = runtime._observe_doctor_v1(
        project_root=tmp_path,
        deployment_root=tmp_path,
        cli_patch=(
            ("literature.data_root", literature_value),
            ("knowledge.data_root", knowledge_value),
        ),
        environ={},
    )

    assert observations[3:5] == (
        ("literature_data_root", "blocked", "data_root_unsafe"),
        ("knowledge_data_root", "ready", None),
    )


def test_data_root_observer_does_not_open_project_when_both_roots_are_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []

    def unavailable(value: str) -> object:
        opened.append(value)
        if value == str(tmp_path):
            raise AssertionError("project root must not be opened")
        raise runtime.DataRootOpenErrorV1("unavailable")

    monkeypatch.setattr(runtime, "open_validated_data_root_v1", unavailable)

    assert runtime._observe_data_roots_v1(
        project_root=tmp_path,
        literature_value=r"D:\MissingLiterature",
        knowledge_value=r"Q:\MissingKnowledge",
    ) == (
        ("literature_data_root", "blocked", "data_root_unavailable"),
        ("knowledge_data_root", "blocked", "data_root_unavailable"),
    )
    assert opened == [r"D:\MissingLiterature", r"Q:\MissingKnowledge"]


def test_data_root_settlement_fault_marks_every_opened_root_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Capability:
        def __init__(self, value: str) -> None:
            identity = {
                r"D:\Literature": (7, 11),
                r"Q:\Knowledge": (9, 13),
                str(tmp_path): (11, 17),
            }[value]
            self.inspection = _ready_root(identity, (identity,))
            self._value = value

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_exc: object) -> None:
            if self._value == str(tmp_path):
                raise RuntimeError("handle settlement failed")

    monkeypatch.setattr(
        runtime,
        "open_validated_data_root_v1",
        lambda value: Capability(value),
    )

    assert runtime._observe_data_roots_v1(
        project_root=tmp_path,
        literature_value=r"D:\Literature",
        knowledge_value=r"Q:\Knowledge",
    ) == (
        ("literature_data_root", "failed", "inspection_failed"),
        ("knowledge_data_root", "failed", "inspection_failed"),
    )


def test_malformed_project_codex_descriptor_is_an_inspection_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    literature_root, knowledge_root = _prepare_observer_project(tmp_path)
    codex_root = tmp_path / "runtimes" / "codex"
    codex_root.mkdir(parents=True)
    (codex_root / "package.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(
        runtime,
        "probe_core_environment_v1",
        lambda: ("ready", "ready"),
    )
    monkeypatch.setattr(runtime, "probe_ocr_runtime_v1", lambda **_kwargs: "ready")

    observations = runtime._observe_doctor_v1(
        project_root=tmp_path,
        deployment_root=tmp_path,
        cli_patch=(
            ("literature.data_root", str(literature_root)),
            ("knowledge.data_root", str(knowledge_root)),
        ),
        environ={},
    )

    assert observations[6] == ("codex_runtime", "failed", "inspection_failed")


def test_malformed_project_ocr_manifest_is_an_inspection_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    literature_root, knowledge_root = _prepare_observer_project(tmp_path)
    model_root = tmp_path / "models"
    model_root.mkdir()
    mineru_root = tmp_path / ".local" / "mineru"
    mineru_root.mkdir(parents=True)
    (mineru_root / "mineru.json").write_text(
        json.dumps(
            {
                "config_version": "1.3.2",
                "model-source": "modelscope",
                "models-dir": {"pipeline": str(model_root)},
                "llm-aided-config": {"title_aided": {"enable": False}},
            }
        ),
        encoding="utf-8",
    )
    manifest_root = tmp_path / "runtimes" / "ocr"
    manifest_root.mkdir(parents=True)
    (manifest_root / "model-manifest.v1.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runtime, "_validate_ocr_project_descriptors", lambda _root: None)
    monkeypatch.setattr(
        runtime,
        "probe_core_environment_v1",
        lambda: ("ready", "ready"),
    )
    monkeypatch.setattr(runtime, "probe_codex_runtime_v1", lambda **_kwargs: "ready")

    observations = runtime._observe_doctor_v1(
        project_root=tmp_path,
        deployment_root=tmp_path,
        cli_patch=(
            ("literature.data_root", str(literature_root)),
            ("knowledge.data_root", str(knowledge_root)),
        ),
        environ={},
    )

    assert observations[5] == ("ocr_runtime", "failed", "inspection_failed")


def test_malformed_ocr_lock_package_shape_is_an_inspection_failure(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtimes" / "ocr"
    runtime_root.mkdir(parents=True)
    (runtime_root / "pyproject.toml").write_text(
        "[project]\n"
        "dependencies = [\n"
        '  "mineru[pipeline]==3.4.4",\n'
        '  "six",\n'
        '  "torch==2.9.1",\n'
        '  "torchvision==0.24.1",\n'
        "]\n",
        encoding="utf-8",
    )
    (runtime_root / "uv.lock").write_text(
        'package = "not-an-array"\n',
        encoding="utf-8",
    )

    with pytest.raises(runtime.RuntimeDescriptorError, match="package table"):
        runtime._validate_ocr_project_descriptors(tmp_path)


def test_ocr_manifest_rejects_a_windows_drive_path_before_model_io(
    tmp_path: Path,
) -> None:
    manifest_root = tmp_path / "runtimes" / "ocr"
    manifest_root.mkdir(parents=True)
    (manifest_root / "model-manifest.v1.json").write_text(
        json.dumps(
            {
                "schema_version": "gezhi.ocr_model_manifest.v1",
                "model_id": "OpenDataLab/PDF-Extract-Kit-1.0",
                "source": "modelscope",
                "snapshot": "master",
                "file_count": 40,
                "total_bytes": 2_595_586_833,
                "files": [
                    {"path": "D:/outside.bin", "size": 1, "sha256": "0" * 64}
                ]
                * 40,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(runtime.RuntimeDescriptorError, match="path is unsafe"):
        runtime._read_ocr_model_manifest_v1(tmp_path)


def test_ocr_configuration_must_name_the_exact_local_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mineru_root = tmp_path / ".local" / "mineru"
    mineru_root.mkdir(parents=True)
    (mineru_root / "mineru.json").write_text(
        json.dumps(
            {
                "config_version": "1.3.2",
                "model-source": "modelscope",
                "models-dir": {"pipeline": str(tmp_path / "models")},
                "llm-aided-config": {"title_aided": {"enable": False}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )

    with pytest.raises(ValueError, match="exact frozen snapshot"):
        runtime._read_ocr_configuration_v1(tmp_path)
