from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, TypeAlias

from gezhi._bounded_probe import (
    ProbeOutputLimitExceeded,
    ProbeUnavailableError,
    run_bounded_probe_v1,
)
from gezhi._configuration import ConfigurationError, resolve_configuration_v1
from gezhi._windows_data_root import (
    DataRootInspectionV1,
    DataRootOpenErrorV1,
    data_root_does_not_physically_contain_project,
    data_roots_are_physically_isolated,
    normalize_local_path_v1,
    open_validated_data_root_v1,
    validate_relative_parts_v1,
)

ProbeStatus: TypeAlias = Literal["ready", "blocked", "failed"]


class RuntimeDescriptorError(RuntimeError):
    """A project-owned runtime descriptor cannot be inspected coherently."""


class RuntimeUnavailableError(RuntimeError):
    """A required runtime file cannot be read as an expected capability fact."""

_CORE_DEPENDENCIES = (
    ("feedparser", "6.0.14", "feedparser"),
    ("httpx", "0.28.1", "httpx"),
    ("pydantic", "2.13.4", "pydantic"),
    ("pydantic-settings", "2.14.2", "pydantic_settings"),
    ("pypdf", "6.14.2", "pypdf"),
    ("rapidfuzz", "3.14.5", "rapidfuzz"),
    ("rich", "15.0.0", "rich"),
    ("tenacity", "9.1.4", "tenacity"),
    ("typer", "0.27.0", "typer"),
)
_CODEX_EXECUTABLE_PARTS = (
    "runtimes",
    "codex",
    "node_modules",
    "@openai",
    "codex-win32-x64",
    "vendor",
    "x86_64-pc-windows-msvc",
    "bin",
    "codex.exe",
)
_OCR_PYTHON_PARTS = (
    "runtimes",
    "ocr",
    ".venv",
    "Scripts",
    "python.exe",
)
_OCR_MINERU_PARTS = (
    "runtimes",
    "ocr",
    ".venv",
    "Scripts",
    "mineru.exe",
)


@dataclass(frozen=True, slots=True)
class FrozenOcrExecutionRuntimeV1:
    executable_path: str
    environment: tuple[tuple[str, str], ...]


def probe_core_environment_v1() -> tuple[ProbeStatus, ProbeStatus]:
    python_status: ProbeStatus = (
        "ready"
        if sys.implementation.name == "cpython"
        and sys.version_info[:3] == (3, 11, 15)
        else "blocked"
    )

    try:
        dependency_status = _probe_core_dependencies_v1()
    except Exception:  # noqa: BLE001 - preserve the independent Python fact.
        dependency_status = "failed"
    return python_status, dependency_status


def _probe_core_dependencies_v1() -> ProbeStatus:

    for distribution, expected_version, _module in _CORE_DEPENDENCIES:
        try:
            actual_version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            return "blocked"
        if actual_version != expected_version:
            return "blocked"

    try:
        project_distribution = importlib.metadata.distribution("gezhi")
    except importlib.metadata.PackageNotFoundError:
        return "blocked"
    project_entry_points = tuple(
        entry_point
        for entry_point in project_distribution.entry_points
        if entry_point.group == "console_scripts" and entry_point.name == "gezhi"
    )
    if (
        project_distribution.version != "0.1.0"
        or len(project_entry_points) != 1
        or project_entry_points[0].value != "gezhi.bootstrap:main"
    ):
        return "blocked"
    all_project_entry_points = tuple(
        importlib.metadata.entry_points(
            group="console_scripts",
            name="gezhi",
        )
    )
    if (
        len(all_project_entry_points) != 1
        or all_project_entry_points[0].value != "gezhi.bootstrap:main"
    ):
        return "blocked"
    direct_url_text = project_distribution.read_text("direct_url.json")
    if direct_url_text is None:
        return "blocked"
    try:
        direct_url = json.loads(direct_url_text)
    except (json.JSONDecodeError, TypeError):
        return "blocked"
    if direct_url != {
        "url": "file:///E:/Gezhi",
        "dir_info": {"editable": True},
    }:
        return "blocked"

    import_statement = ";".join(
        f"import {module}" for _distribution, _version, module in _CORE_DEPENDENCIES
    )
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = run_bounded_probe_v1(
            (sys.executable, "-I", "-B", "-c", import_statement),
            environment=environment,
            timeout_seconds=30,
            output_limit=0,
            creation_flags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (
        ProbeOutputLimitExceeded,
        ProbeUnavailableError,
        subprocess.TimeoutExpired,
    ):
        return "blocked"
    return (
        "ready"
        if completed.returncode == 0 and not completed.stdout and not completed.stderr
        else "blocked"
    )


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeUnavailableError("runtime descriptor is unavailable") from error
    value = json.loads(raw)
    if type(value) is not dict:
        raise ValueError("runtime descriptor is not an object")
    return value


def probe_codex_runtime_v1(*, project_root: Path) -> ProbeStatus:
    runtime_root = project_root / "runtimes" / "codex"
    try:
        package = _read_json_object(runtime_root / "package.json")
        lock = _read_json_object(runtime_root / "package-lock.json")
        packages = lock["packages"]
        if type(packages) is not dict:
            raise RuntimeDescriptorError("Codex lock package table is malformed")
        root_lock = packages[""]
        main_lock = packages["node_modules/@openai/codex"]
        native_lock = packages["node_modules/@openai/codex-win32-x64"]
        if not all(type(item) is dict for item in (root_lock, main_lock, native_lock)):
            raise RuntimeDescriptorError("Codex lock package entry is malformed")
        dependencies = root_lock["dependencies"]
        if type(dependencies) is not dict:
            raise RuntimeDescriptorError("Codex lock dependencies are malformed")
        if package.get("dependencies") != {"@openai/codex": "0.146.0"}:
            return "blocked"
        if dependencies != {"@openai/codex": "0.146.0"}:
            return "blocked"
        if main_lock.get("version") != "0.146.0":
            return "blocked"
        if native_lock.get("version") != "0.146.0-win32-x64":
            return "blocked"

        installed_root = runtime_root / "node_modules" / "@openai"
        installed_main = _read_json_object(installed_root / "codex" / "package.json")
        installed_native_root = installed_root / "codex-win32-x64"
        installed_native = _read_json_object(installed_native_root / "package.json")
        if installed_main.get("version") != "0.146.0":
            return "blocked"
        if installed_native.get("version") != "0.146.0-win32-x64":
            return "blocked"
        with (
            open_validated_data_root_v1(str(project_root)) as project,
            project.open_relative_file_v1(_CODEX_EXECUTABLE_PARTS) as executable,
        ):
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            version = run_bounded_probe_v1(
                (executable.canonical_path, "--version"),
                timeout_seconds=15,
                output_limit=4_096,
                creation_flags=creation_flags,
            )
            login = run_bounded_probe_v1(
                (executable.canonical_path, "login", "status"),
                timeout_seconds=15,
                output_limit=4_096,
                creation_flags=creation_flags,
            )
    except (
        DataRootOpenErrorV1,
        ProbeOutputLimitExceeded,
        ProbeUnavailableError,
        RuntimeUnavailableError,
        subprocess.TimeoutExpired,
    ):
        return "blocked"

    if (
        version.returncode != 0
        or version.stdout.strip() != b"codex-cli 0.146.0"
        or version.stderr
        or login.returncode != 0
        or (login.stdout + login.stderr).strip() != b"Logged in using ChatGPT"
    ):
        return "blocked"
    return "ready"


def _validate_ocr_project_descriptors(project_root: Path) -> None:
    runtime_root = project_root / "runtimes" / "ocr"
    try:
        pyproject = tomllib.loads(
            (runtime_root / "pyproject.toml").read_text("utf-8")
        )
    except OSError as error:
        raise RuntimeUnavailableError("OCR project descriptor is unavailable") from error
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise RuntimeDescriptorError("OCR project descriptor is malformed") from error
    project = pyproject.get("project")
    if type(project) is not dict or type(project.get("dependencies")) is not list:
        raise RuntimeDescriptorError("OCR project dependency table is malformed")
    if any(type(item) is not str for item in project["dependencies"]):
        raise RuntimeDescriptorError("OCR project dependency entry is malformed")
    if project["dependencies"] != [
        "mineru[pipeline]==3.4.4",
        "six",
        "torch==2.9.1",
        "torchvision==0.24.1",
    ]:
        raise ValueError("OCR project dependencies drifted")
    try:
        lock = tomllib.loads((runtime_root / "uv.lock").read_text("utf-8"))
    except OSError as error:
        raise RuntimeUnavailableError("OCR lock descriptor is unavailable") from error
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise RuntimeDescriptorError("OCR lock descriptor is malformed") from error
    package_table = lock.get("package")
    if type(package_table) is not list:
        raise RuntimeDescriptorError("OCR lock package table is malformed")
    packages: dict[str, str] = {}
    for package in package_table:
        if type(package) is not dict:
            raise RuntimeDescriptorError("OCR lock package entry is malformed")
        name = package.get("name")
        version = package.get("version")
        if type(name) is not str or type(version) is not str or name in packages:
            raise RuntimeDescriptorError("OCR lock package identity is malformed")
        packages[name] = version
    names = ("mineru", "six", "torch", "torchvision")
    if {name: packages.get(name) for name in names} != {
        "mineru": "3.4.4",
        "six": "1.17.0",
        "torch": "2.9.1+cu130",
        "torchvision": "0.24.1+cu130",
    }:
        raise ValueError("OCR lock identities drifted")


@dataclass(frozen=True, slots=True)
class _OcrModelManifestEntryV1:
    path: str
    parts: tuple[str, ...]
    size: int
    sha256: str


def _read_ocr_configuration_v1(deployment_root: Path) -> tuple[Path, Path]:
    config_parts = (".local", "mineru", "mineru.json")
    config_path = deployment_root.joinpath(*config_parts)
    expected_model_root = deployment_root.joinpath(
        ".local",
        "mineru",
        "models",
        "OpenDataLab--PDF-Extract-Kit-1.0",
        "snapshots",
        "master",
    )
    with (
        open_validated_data_root_v1(str(deployment_root)) as deployment,
        deployment.open_relative_file_v1(config_parts) as config_file,
    ):
        try:
            config = json.loads(
                config_file.read_bytes_v1(limit=65_536).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("MinerU config is malformed") from error
    if type(config) is not dict:
        raise ValueError("MinerU config is not an object")
    if config.get("config_version") != "1.3.2":
        raise ValueError("MinerU config version drifted")
    if config.get("model-source") != "modelscope":
        raise ValueError("MinerU model provenance drifted")
    model_dirs = config.get("models-dir")
    if type(model_dirs) is not dict or type(model_dirs.get("pipeline")) is not str:
        raise ValueError("MinerU model directory is invalid")
    llm_config = config.get("llm-aided-config")
    if type(llm_config) is not dict:
        raise ValueError("MinerU LLM config is invalid")
    title_config = llm_config.get("title_aided")
    if type(title_config) is not dict or title_config.get("enable") is not False:
        raise ValueError("MinerU LLM-aided mode is not disabled")

    observed_root = normalize_local_path_v1(model_dirs["pipeline"])
    expected_root = normalize_local_path_v1(str(expected_model_root))
    if (
        observed_root is None
        or expected_root is None
        or observed_root.casefold() != expected_root.casefold()
    ):
        raise ValueError("MinerU model root is not the exact frozen snapshot")
    return config_path, expected_model_root


def _read_ocr_model_manifest_v1(
    project_root: Path,
) -> tuple[_OcrModelManifestEntryV1, ...]:
    try:
        manifest = _read_json_object(
            project_root / "runtimes" / "ocr" / "model-manifest.v1.json"
        )
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
        raise RuntimeDescriptorError("OCR model manifest is malformed") from error
    if set(manifest) != {
        "schema_version",
        "model_id",
        "source",
        "snapshot",
        "file_count",
        "total_bytes",
        "files",
    }:
        raise RuntimeDescriptorError("OCR model manifest shape is invalid")
    if (
        manifest.get("schema_version") != "gezhi.ocr_model_manifest.v1"
        or manifest.get("model_id") != "OpenDataLab/PDF-Extract-Kit-1.0"
        or manifest.get("source") != "modelscope"
        or manifest.get("snapshot") != "master"
        or manifest.get("file_count") != 40
        or manifest.get("total_bytes") != 2_595_586_833
    ):
        raise ValueError("OCR model manifest identity drifted")
    entries = manifest.get("files")
    if type(entries) is not list or len(entries) != 40:
        raise RuntimeDescriptorError("OCR model manifest file set is invalid")

    frozen: list[_OcrModelManifestEntryV1] = []
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "size", "sha256"}:
            raise RuntimeDescriptorError("OCR model manifest entry is invalid")
        relative = entry["path"]
        size = entry["size"]
        digest = entry["sha256"]
        if (
            type(relative) is not str
            or type(size) is not int
            or size < 0
            or type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise RuntimeDescriptorError("OCR model manifest entry value is invalid")
        relative_path = PurePosixPath(relative)
        if (
            relative_path.is_absolute()
            or not relative_path.parts
            or ".." in relative_path.parts
            or "\\" in relative
        ):
            raise RuntimeDescriptorError("OCR model manifest path is unsafe")
        try:
            parts = validate_relative_parts_v1(tuple(relative_path.parts))
        except ValueError as error:
            raise RuntimeDescriptorError(
                "OCR model manifest path is unsafe"
            ) from error
        frozen.append(
            _OcrModelManifestEntryV1(
                path=relative,
                parts=parts,
                size=size,
                sha256=digest,
            )
        )

    expected_paths = tuple(item.path for item in frozen)
    if expected_paths != tuple(sorted(expected_paths)) or len(set(expected_paths)) != 40:
        raise RuntimeDescriptorError("OCR model manifest order is invalid")
    if sum(item.size for item in frozen) != 2_595_586_833:
        raise ValueError("OCR model manifest total drifted")
    return tuple(frozen)


def _validate_ocr_model_manifest(
    *,
    project_root: Path,
    deployment_root: Path,
) -> tuple[Path, Path]:
    entries = _read_ocr_model_manifest_v1(project_root)
    config_path, model_root = _read_ocr_configuration_v1(deployment_root)
    expected_paths = tuple(item.path for item in entries)
    with open_validated_data_root_v1(str(model_root)) as model:
        if model.relative_file_paths_v1() != expected_paths:
            raise ValueError("OCR model file set drifted")
        for entry in entries:
            with model.open_relative_file_v1(entry.parts) as model_file:
                if model_file.size != entry.size:
                    raise ValueError("OCR model file identity drifted")
                if model_file.sha256_v1() != entry.sha256:
                    raise ValueError("OCR model file hash drifted")
        if model.relative_file_paths_v1() != expected_paths:
            raise ValueError("OCR model file set drifted")
    return config_path, model_root


_OCR_PROBE_SCRIPT = """
import importlib.metadata as metadata
import json
import os
import sys
import mineru
import six
import torch
import torchvision

value = {
    "cuda_available": torch.cuda.is_available(),
    "cuda_build": torch.version.cuda,
    "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "mineru": metadata.version("mineru"),
    "profile": {
        name: os.environ.get(name)
        for name in (
            "MINERU_TOOLS_CONFIG_JSON",
            "MINERU_MODEL_SOURCE",
            "MINERU_DEVICE_MODE",
            "HF_HUB_OFFLINE",
            "TRANSFORMERS_OFFLINE",
            "NO_PROXY",
            "MODELSCOPE_CACHE",
            "MODELSCOPE_OFFLINE",
        )
    },
    "python": list(sys.version_info[:3]),
    "six": metadata.version("six"),
    "torch": torch.__version__,
    "torchvision": torchvision.__version__,
}
print(json.dumps(value, sort_keys=True, separators=(",", ":")))
"""

_OCR_POLICY_PREFIXES = (
    "mineru_",
    "modelscope_",
    "hf_",
    "huggingface_",
    "transformers_",
    "python",
)


def _ocr_probe_environment(config_path: Path) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not any(
            name.casefold().startswith(prefix) for prefix in _OCR_POLICY_PREFIXES
        )
    }
    environment.update(
        {
            "MINERU_TOOLS_CONFIG_JSON": str(config_path),
            "MINERU_MODEL_SOURCE": "local",
            "MINERU_DEVICE_MODE": "cuda",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "NO_PROXY": "127.0.0.1,localhost",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def probe_ocr_runtime_v1(
    *,
    project_root: Path,
    deployment_root: Path,
) -> ProbeStatus:
    try:
        _validate_ocr_project_descriptors(project_root)
        config_path, _model_root = _validate_ocr_model_manifest(
            project_root=project_root,
            deployment_root=deployment_root,
        )
        environment = _ocr_probe_environment(config_path)
        with (
            open_validated_data_root_v1(str(deployment_root)) as deployment,
            deployment.open_relative_file_v1(_OCR_PYTHON_PARTS) as ocr_python,
        ):
            completed = run_bounded_probe_v1(
                (
                    ocr_python.canonical_path,
                    "-I",
                    "-B",
                    "-c",
                    _OCR_PROBE_SCRIPT,
                ),
                environment=environment,
                timeout_seconds=60,
                output_limit=4_096,
                creation_flags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        if completed.returncode != 0 or completed.stderr:
            return "blocked"
        observed = json.loads(completed.stdout)
    except (
        DataRootOpenErrorV1,
        ProbeOutputLimitExceeded,
        ProbeUnavailableError,
        RuntimeUnavailableError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        subprocess.TimeoutExpired,
    ):
        return "blocked"

    expected = {
        "cuda_available": True,
        "cuda_build": "13.0",
        "device": "NVIDIA GeForce RTX 4090",
        "mineru": "3.4.4",
        "profile": {
            "HF_HUB_OFFLINE": "1",
            "MINERU_DEVICE_MODE": "cuda",
            "MINERU_MODEL_SOURCE": "local",
            "MINERU_TOOLS_CONFIG_JSON": str(config_path),
            "MODELSCOPE_CACHE": None,
            "MODELSCOPE_OFFLINE": None,
            "NO_PROXY": "127.0.0.1,localhost",
            "TRANSFORMERS_OFFLINE": "1",
        },
        "python": [3, 11, 15],
        "six": "1.17.0",
        "torch": "2.9.1+cu130",
        "torchvision": "0.24.1+cu130",
    }
    return "ready" if observed == expected else "blocked"


def resolve_ocr_execution_runtime_v1(
    *,
    project_root: Path,
    deployment_root: Path,
) -> FrozenOcrExecutionRuntimeV1:
    """Return the exact executable/profile only after the frozen probe passes."""

    if (
        probe_ocr_runtime_v1(
            project_root=project_root,
            deployment_root=deployment_root,
        )
        != "ready"
    ):
        raise RuntimeUnavailableError("the frozen OCR runtime is unavailable")
    try:
        config_path, _model_root = _read_ocr_configuration_v1(deployment_root)
        with (
            open_validated_data_root_v1(str(deployment_root)) as deployment,
            deployment.open_relative_file_v1(_OCR_MINERU_PARTS) as executable,
        ):
            executable_path = executable.canonical_path
    except (DataRootOpenErrorV1, OSError, ValueError) as error:
        raise RuntimeUnavailableError(
            "the frozen OCR executable is unavailable"
        ) from error
    environment = _ocr_probe_environment(config_path)
    return FrozenOcrExecutionRuntimeV1(
        executable_path=executable_path,
        environment=tuple(sorted(environment.items())),
    )


DoctorObservation = tuple[str, str, str | None]


def _capability_observation(
    check_id: str,
    status: object,
    blocked_reason: str,
) -> DoctorObservation:
    if status == "ready":
        return check_id, "ready", None
    if status == "blocked":
        return check_id, "blocked", blocked_reason
    return check_id, "failed", "inspection_failed"


def _data_root_observation(
    check_id: str,
    value: str,
    stack: ExitStack,
) -> tuple[DoctorObservation, DataRootInspectionV1 | None]:
    try:
        capability = stack.enter_context(open_validated_data_root_v1(value))
    except DataRootOpenErrorV1 as error:
        if error.status == "unsafe":
            return (check_id, "blocked", "data_root_unsafe"), None
        if error.status == "unavailable":
            return (check_id, "blocked", "data_root_unavailable"), None
        return (check_id, "failed", "inspection_failed"), None
    except Exception:  # noqa: BLE001 - contract classifies unexpected probe faults.
        return (check_id, "failed", "inspection_failed"), None
    return (check_id, "ready", None), capability.inspection


def _mark_ready_root_settlement_failed(
    observation: DoctorObservation,
) -> DoctorObservation:
    if observation[1] == "ready":
        return observation[0], "failed", "inspection_failed"
    return observation


def _mark_open_root_settlement_failed(
    observation: DoctorObservation,
    *,
    was_opened: bool,
) -> DoctorObservation:
    if was_opened:
        return observation[0], "failed", "inspection_failed"
    return observation


def _observe_data_roots_v1(
    *,
    project_root: Path,
    literature_value: str,
    knowledge_value: str,
) -> tuple[DoctorObservation, DoctorObservation]:
    literature_observation: DoctorObservation = (
        "literature_data_root",
        "failed",
        "inspection_failed",
    )
    knowledge_observation: DoctorObservation = (
        "knowledge_data_root",
        "failed",
        "inspection_failed",
    )
    literature_was_opened = False
    knowledge_was_opened = False
    try:
        with ExitStack() as stack:
            literature_observation, literature_inspection = (
                _data_root_observation(
                    "literature_data_root",
                    literature_value,
                    stack,
                )
            )
            knowledge_observation, knowledge_inspection = _data_root_observation(
                "knowledge_data_root",
                knowledge_value,
                stack,
            )
            literature_was_opened = literature_inspection is not None
            knowledge_was_opened = knowledge_inspection is not None
            if literature_was_opened or knowledge_was_opened:
                try:
                    project_capability = stack.enter_context(
                        open_validated_data_root_v1(str(project_root))
                    )
                except DataRootOpenErrorV1 as error:
                    project_inspection: DataRootInspectionV1 | None = (
                        DataRootInspectionV1(status=error.status)
                    )
                except Exception:  # noqa: BLE001 - classify probe faults.
                    project_inspection = None
                else:
                    project_inspection = project_capability.inspection
            else:
                project_inspection = DataRootInspectionV1(status="ready")

            ready_roots = (
                ("literature_data_root", literature_inspection),
                ("knowledge_data_root", knowledge_inspection),
            )
            if project_inspection is None:
                literature_observation = _mark_ready_root_settlement_failed(
                    literature_observation
                )
                knowledge_observation = _mark_ready_root_settlement_failed(
                    knowledge_observation
                )
            elif project_inspection.status != "ready":
                reason = (
                    "data_root_unsafe"
                    if project_inspection.status == "unsafe"
                    else "data_root_unavailable"
                )
                if literature_observation[1] == "ready":
                    literature_observation = (
                        "literature_data_root",
                        "blocked",
                        reason,
                    )
                if knowledge_observation[1] == "ready":
                    knowledge_observation = (
                        "knowledge_data_root",
                        "blocked",
                        reason,
                    )
            else:
                for check_id, inspection in ready_roots:
                    if inspection is None:
                        continue
                    try:
                        boundary_is_safe = (
                            data_root_does_not_physically_contain_project(
                                inspection,
                                project_inspection,
                            )
                        )
                    except Exception:  # noqa: BLE001 - classify probe faults.
                        observation: DoctorObservation = (
                            check_id,
                            "failed",
                            "inspection_failed",
                        )
                    else:
                        observation = (
                            (check_id, "ready", None)
                            if boundary_is_safe
                            else (check_id, "blocked", "data_root_unsafe")
                        )
                    if check_id == "literature_data_root":
                        literature_observation = observation
                    else:
                        knowledge_observation = observation

            if (
                literature_inspection is not None
                and knowledge_inspection is not None
                and literature_observation[1] == "ready"
                and knowledge_observation[1] == "ready"
            ):
                try:
                    physically_isolated = data_roots_are_physically_isolated(
                        literature_inspection,
                        knowledge_inspection,
                    )
                except Exception:  # noqa: BLE001 - classify probe faults.
                    literature_observation = (
                        "literature_data_root",
                        "failed",
                        "inspection_failed",
                    )
                    knowledge_observation = (
                        "knowledge_data_root",
                        "failed",
                        "inspection_failed",
                    )
                else:
                    if not physically_isolated:
                        literature_observation = (
                            "literature_data_root",
                            "blocked",
                            "data_root_unsafe",
                        )
                        knowledge_observation = (
                            "knowledge_data_root",
                            "blocked",
                            "data_root_unsafe",
                        )
    except Exception:  # noqa: BLE001 - handle settlement is part of the probe.
        literature_observation = _mark_open_root_settlement_failed(
            literature_observation,
            was_opened=literature_was_opened,
        )
        knowledge_observation = _mark_open_root_settlement_failed(
            knowledge_observation,
            was_opened=knowledge_was_opened,
        )
    return literature_observation, knowledge_observation


def _observe_doctor_v1(
    *,
    project_root: Path,
    deployment_root: Path,
    cli_patch: tuple[tuple[str, str], ...],
    environ: Mapping[str, str],
) -> tuple[tuple[str, str, str | None], ...]:
    try:
        configuration = resolve_configuration_v1(
            trusted_project_root=project_root,
            cli_patch=cli_patch,
            environ=environ,
        )
    except ConfigurationError:
        configuration_observation: DoctorObservation = (
            "configuration",
            "blocked",
            "configuration_invalid",
        )
        literature_observation: DoctorObservation = (
            "literature_data_root",
            "not_checked",
            None,
        )
        knowledge_observation: DoctorObservation = (
            "knowledge_data_root",
            "not_checked",
            None,
        )
    except Exception:  # noqa: BLE001 - contract classifies unexpected probe faults.
        configuration_observation = (
            "configuration",
            "failed",
            "inspection_failed",
        )
        literature_observation = (
            "literature_data_root",
            "not_checked",
            None,
        )
        knowledge_observation = (
            "knowledge_data_root",
            "not_checked",
            None,
        )
    else:
        configuration_observation = ("configuration", "ready", None)
        literature_observation, knowledge_observation = _observe_data_roots_v1(
            project_root=project_root,
            literature_value=configuration.literature_data_root,
            knowledge_value=configuration.knowledge_data_root,
        )

    try:
        core_python_status, core_dependencies_status = probe_core_environment_v1()
    except Exception:  # noqa: BLE001 - contract classifies unexpected probe faults.
        core_python_observation: DoctorObservation = (
            "core_python",
            "failed",
            "inspection_failed",
        )
        core_dependencies_observation: DoctorObservation = (
            "core_dependencies",
            "failed",
            "inspection_failed",
        )
    else:
        core_python_observation = _capability_observation(
            "core_python",
            core_python_status,
            "core_environment_unavailable",
        )
        core_dependencies_observation = _capability_observation(
            "core_dependencies",
            core_dependencies_status,
            "core_environment_unavailable",
        )

    ocr_status: object
    try:
        ocr_status = probe_ocr_runtime_v1(
            project_root=project_root,
            deployment_root=deployment_root,
        )
    except Exception:  # noqa: BLE001 - contract classifies unexpected probe faults.
        ocr_status = "failed"
    ocr_observation = _capability_observation(
        "ocr_runtime",
        ocr_status,
        "ocr_environment_unavailable",
    )

    codex_status: object
    try:
        codex_status = probe_codex_runtime_v1(project_root=project_root)
    except Exception:  # noqa: BLE001 - contract classifies unexpected probe faults.
        codex_status = "failed"
    codex_observation = _capability_observation(
        "codex_runtime",
        codex_status,
        "codex_environment_unavailable",
    )

    return (
        configuration_observation,
        core_python_observation,
        core_dependencies_observation,
        literature_observation,
        knowledge_observation,
        ocr_observation,
        codex_observation,
    )


def observe_doctor(
    *,
    cli_patch: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str, str | None], ...]:
    return _observe_doctor_v1(
        project_root=Path(r"E:\Gezhi"),
        deployment_root=Path(r"E:\Gezhi"),
        cli_patch=cli_patch,
        environ=os.environ.copy(),
    )
