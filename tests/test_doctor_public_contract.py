from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from launcher_support import SOURCE_ROOT, run_both_launchers, run_python_script

from gezhi import _doctor_runtime as doctor_runtime

DEPLOYMENT_ROOT = Path(r"E:\Gezhi")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_RUNTIME_IDENTITY = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "runtimes"
        / "codex"
        / "runtime-identity-v1.json"
    ).read_text(encoding="utf-8")
)
_CODEX_EXECUTABLE = DEPLOYMENT_ROOT.joinpath(
    "runtimes",
    "codex",
    "node_modules",
    *_RUNTIME_IDENTITY["native_package_alias"].split("/"),
    *_RUNTIME_IDENTITY["executable_relative_parts"],
)
_CORE_IMPORT_SCRIPT = ";".join(
    f"import {module}"
    for _distribution, _version, module in doctor_runtime._CORE_DEPENDENCIES
)


def _read_only_doctor_site_customize(marker: Path) -> str:
    ocr_python = DEPLOYMENT_ROOT.joinpath(*doctor_runtime._OCR_PYTHON_PARTS)
    codex_executable = _CODEX_EXECUTABLE
    return (
        "import os\n"
        "import pathlib\n"
        "import subprocess\n"
        "import sys\n\n"
        f"marker = pathlib.Path({str(marker)!r})\n"
        f"ocr_python = {str(ocr_python)!r}\n"
        f"codex_executable = {str(codex_executable)!r}\n"
        f"core_script = {_CORE_IMPORT_SCRIPT!r}\n"
        f"ocr_script = {doctor_runtime._OCR_PROBE_SCRIPT!r}\n"
        "real_popen = subprocess.Popen\n\n"
        "def normalize(value):\n"
        "    text = os.path.normcase(os.path.normpath(os.fspath(value)))\n"
        "    return text[4:] if text.startswith('\\\\?\\\\') else text\n\n"
        "allowed = {\n"
        "    (normalize(sys.executable), ('-I', '-B', '-c', core_script)),\n"
        "    (normalize(ocr_python), ('-I', '-B', '-c', ocr_script)),\n"
        "    (normalize(codex_executable), ('--version',)),\n"
        "    (normalize(codex_executable), ('login', 'status')),\n"
        "}\n\n"
        "def guarded_popen(command, *args, **kwargs):\n"
        "    try:\n"
        "        argv = ((command,) if isinstance(command, (str, bytes, os.PathLike))\n"
        "                else tuple(command))\n"
        "        key = (normalize(argv[0]), tuple(os.fspath(item) for item in argv[1:]))\n"
        "        explicit = kwargs.get('executable')\n"
        "        permitted = (key in allowed and not kwargs.get('shell', False)\n"
        "                     and (explicit is None or normalize(explicit) == key[0]))\n"
        "    except Exception:\n"
        "        permitted = False\n"
        "    if not permitted:\n"
        "        marker.write_text('prohibited', encoding='utf-8')\n"
        "        raise RuntimeError('prohibited doctor child')\n"
        "    return real_popen(command, *args, **kwargs)\n\n"
        "subprocess.Popen = guarded_popen\n"
    )

CONFIGURATION_BLOCKED_SITE_CUSTOMIZE = r'''
import sys
import types


runtime = types.ModuleType("gezhi._doctor_runtime")


def observe_doctor(*, cli_patch):
    return (
        ("configuration", "blocked", "configuration_invalid"),
        ("core_python", "ready", None),
        ("core_dependencies", "ready", None),
        ("literature_data_root", "not_checked", None),
        ("knowledge_data_root", "not_checked", None),
        ("ocr_runtime", "ready", None),
        ("codex_runtime", "ready", None),
    )


runtime.observe_doctor = observe_doctor
sys.modules["gezhi._doctor_runtime"] = runtime
'''

CONFIGURATION_BLOCKED_JSON = (
    b'{"command":"doctor","diagnostics":['
    b'{"code":"operations.doctor.configuration_invalid.v1","context":{}}'
    b'],"outcome":"blocked","result":{"checks":['
    b'{"id":"configuration","status":"blocked"},'
    b'{"id":"core_python","status":"ready"},'
    b'{"id":"core_dependencies","status":"ready"},'
    b'{"id":"literature_data_root","status":"not_checked"},'
    b'{"id":"knowledge_data_root","status":"not_checked"},'
    b'{"id":"ocr_runtime","status":"ready"},'
    b'{"id":"codex_runtime","status":"ready"}'
    b'],"overall_status":"blocked",'
    b'"schema_version":"gezhi.doctor_result.v1"},'
    b'"schema_version":"gezhi.cli_result.v1"}\n'
)

CONFIGURATION_BLOCKED_HUMAN = """格致 doctor：受阻
配置：受阻
核心 Python：就绪
核心依赖：就绪
Literature Data Root：未检查
Knowledge Data Root：未检查
OCR 运行时：就绪
Codex 运行时：就绪
问题：格致配置无效。
建议：检查版本化配置后重试；本命令不会修改配置。
""".encode()


def test_doctor_json_reports_configuration_blocked_through_both_launchers(
    tmp_path: Path,
) -> None:
    (tmp_path / "sitecustomize.py").write_text(
        CONFIGURATION_BLOCKED_SITE_CUSTOMIZE,
        encoding="utf-8",
    )

    results = run_both_launchers(
        ("doctor", "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [
        (2, CONFIGURATION_BLOCKED_JSON, b""),
        (2, CONFIGURATION_BLOCKED_JSON, b""),
    ]


def test_doctor_human_reports_configuration_blocked_through_both_launchers(
    tmp_path: Path,
) -> None:
    (tmp_path / "sitecustomize.py").write_text(
        CONFIGURATION_BLOCKED_SITE_CUSTOMIZE,
        encoding="utf-8",
    )

    results = run_both_launchers(
        ("doctor",),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [
        (2, CONFIGURATION_BLOCKED_HUMAN, b""),
        (2, CONFIGURATION_BLOCKED_HUMAN, b""),
    ]
READY_OBSERVATIONS = (
    ("configuration", "ready", None),
    ("core_python", "ready", None),
    ("core_dependencies", "ready", None),
    ("literature_data_root", "ready", None),
    ("knowledge_data_root", "ready", None),
    ("ocr_runtime", "ready", None),
    ("codex_runtime", "ready", None),
)

MULTIPLE_BLOCKERS_OBSERVATIONS = (
    ("configuration", "ready", None),
    ("core_python", "blocked", "core_environment_unavailable"),
    ("core_dependencies", "blocked", "core_environment_unavailable"),
    ("literature_data_root", "blocked", "data_root_unsafe"),
    ("knowledge_data_root", "blocked", "data_root_unavailable"),
    ("ocr_runtime", "blocked", "ocr_environment_unavailable"),
    ("codex_runtime", "blocked", "codex_environment_unavailable"),
)

INSPECTION_FAILED_OBSERVATIONS = (
    ("configuration", "ready", None),
    ("core_python", "failed", "inspection_failed"),
    ("core_dependencies", "blocked", "core_environment_unavailable"),
    ("literature_data_root", "blocked", "data_root_unsafe"),
    ("knowledge_data_root", "ready", None),
    ("ocr_runtime", "blocked", "ocr_environment_unavailable"),
    ("codex_runtime", "ready", None),
)

READY_JSON = (
    b'{"command":"doctor","diagnostics":[],"outcome":"succeeded",'
    b'"result":{"checks":['
    b'{"id":"configuration","status":"ready"},'
    b'{"id":"core_python","status":"ready"},'
    b'{"id":"core_dependencies","status":"ready"},'
    b'{"id":"literature_data_root","status":"ready"},'
    b'{"id":"knowledge_data_root","status":"ready"},'
    b'{"id":"ocr_runtime","status":"ready"},'
    b'{"id":"codex_runtime","status":"ready"}'
    b'],"overall_status":"ready",'
    b'"schema_version":"gezhi.doctor_result.v1"},'
    b'"schema_version":"gezhi.cli_result.v1"}\n'
)

READY_HUMAN = """格致 doctor：就绪
配置：就绪
核心 Python：就绪
核心依赖：就绪
Literature Data Root：就绪
Knowledge Data Root：就绪
OCR 运行时：就绪
Codex 运行时：就绪
下一步：冻结环境已就绪。
""".encode()

MULTIPLE_BLOCKERS_JSON = (
    b'{"command":"doctor","diagnostics":['
    b'{"code":"operations.doctor.data_root_unsafe.v1",'
    b'"context":{"contexts":["literature"]}},'
    b'{"code":"operations.doctor.codex_environment_unavailable.v1",'
    b'"context":{}},'
    b'{"code":"operations.doctor.core_environment_unavailable.v1",'
    b'"context":{"checks":["core_python","core_dependencies"]}},'
    b'{"code":"operations.doctor.data_root_unavailable.v1",'
    b'"context":{"contexts":["knowledge"]}},'
    b'{"code":"operations.doctor.ocr_environment_unavailable.v1",'
    b'"context":{}}],"outcome":"blocked","result":{"checks":['
    b'{"id":"configuration","status":"ready"},'
    b'{"id":"core_python","status":"blocked"},'
    b'{"id":"core_dependencies","status":"blocked"},'
    b'{"id":"literature_data_root","status":"blocked"},'
    b'{"id":"knowledge_data_root","status":"blocked"},'
    b'{"id":"ocr_runtime","status":"blocked"},'
    b'{"id":"codex_runtime","status":"blocked"}'
    b'],"overall_status":"blocked",'
    b'"schema_version":"gezhi.doctor_result.v1"},'
    b'"schema_version":"gezhi.cli_result.v1"}\n'
)

INSPECTION_FAILED_JSON = (
    b'{"command":"doctor","diagnostics":['
    b'{"code":"operations.doctor.inspection_failed.v1",'
    b'"context":{"checks":["core_python"]}},'
    b'{"code":"operations.doctor.core_environment_unavailable.v1",'
    b'"context":{"checks":["core_dependencies"]}},'
    b'{"code":"operations.doctor.data_root_unsafe.v1",'
    b'"context":{"contexts":["literature"]}},'
    b'{"code":"operations.doctor.ocr_environment_unavailable.v1",'
    b'"context":{}}],"outcome":"failed","result":{"checks":['
    b'{"id":"configuration","status":"ready"},'
    b'{"id":"core_python","status":"failed"},'
    b'{"id":"core_dependencies","status":"blocked"},'
    b'{"id":"literature_data_root","status":"blocked"},'
    b'{"id":"knowledge_data_root","status":"ready"},'
    b'{"id":"ocr_runtime","status":"blocked"},'
    b'{"id":"codex_runtime","status":"ready"}'
    b'],"overall_status":"failed",'
    b'"schema_version":"gezhi.doctor_result.v1"},'
    b'"schema_version":"gezhi.cli_result.v1"}\n'
)

INSPECTION_FAILED_HUMAN = """格致 doctor：检查失败
配置：就绪
核心 Python：检查失败
核心依赖：受阻
Literature Data Root：受阻
Knowledge Data Root：就绪
OCR 运行时：受阻
Codex 运行时：就绪
问题：doctor 无法完成只读检查。
建议：保留现场并检查格致实现或运行环境；不要让 doctor 自动修复。
问题：核心 Python 环境或依赖与冻结基线不一致。
建议：使用已批准的冻结环境恢复流程；不要在 doctor 中安装或升级。
问题：一个或多个 Data Root 不满足 Windows 安全边界。
建议：停止写入并在外部修复路径边界；本命令不会移动或创建目录。
问题：OCR 运行时与冻结基线不一致或不可用。
建议：使用已批准的 OCR 环境恢复流程；不要切换 CPU、在线模型或其他 OCR。
""".encode()


def _site_customize_for(observations: tuple[tuple[str, str, str | None], ...]) -> str:
    return (
        "import sys\n"
        "import types\n\n"
        'runtime = types.ModuleType("gezhi._doctor_runtime")\n\n'
        "def observe_doctor(*, cli_patch):\n"
        f"    return {observations!r}\n\n"
        "runtime.observe_doctor = observe_doctor\n"
        'sys.modules["gezhi._doctor_runtime"] = runtime\n'
    )


def test_doctor_ready_receipts_match_through_both_launchers(tmp_path: Path) -> None:
    (tmp_path / "sitecustomize.py").write_text(
        _site_customize_for(READY_OBSERVATIONS),
        encoding="utf-8",
    )

    json_results = run_both_launchers(
        ("doctor", "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )
    human_results = run_both_launchers(
        ("doctor",),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )

    assert [
        (result.returncode, result.stdout, result.stderr)
        for result in json_results
    ] == [(0, READY_JSON, b""), (0, READY_JSON, b"")]
    assert [
        (result.returncode, result.stdout, result.stderr)
        for result in human_results
    ] == [(0, READY_HUMAN, b""), (0, READY_HUMAN, b"")]


def test_doctor_aggregates_multiple_blockers_in_contract_order(
    tmp_path: Path,
) -> None:
    (tmp_path / "sitecustomize.py").write_text(
        _site_customize_for(MULTIPLE_BLOCKERS_OBSERVATIONS),
        encoding="utf-8",
    )

    results = run_both_launchers(
        ("doctor", "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [
        (2, MULTIPLE_BLOCKERS_JSON, b""),
        (2, MULTIPLE_BLOCKERS_JSON, b""),
    ]


def test_doctor_reports_inspection_failure_before_proved_blockers(
    tmp_path: Path,
) -> None:
    (tmp_path / "sitecustomize.py").write_text(
        _site_customize_for(INSPECTION_FAILED_OBSERVATIONS),
        encoding="utf-8",
    )

    results = run_both_launchers(
        ("doctor", "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [
        (1, INSPECTION_FAILED_JSON, b""),
        (1, INSPECTION_FAILED_JSON, b""),
    ]


def test_doctor_human_uses_the_same_failure_and_supplemental_order(
    tmp_path: Path,
) -> None:
    (tmp_path / "sitecustomize.py").write_text(
        _site_customize_for(INSPECTION_FAILED_OBSERVATIONS),
        encoding="utf-8",
    )

    results = run_both_launchers(
        ("doctor",),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
    )

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [
        (1, INSPECTION_FAILED_HUMAN, b""),
        (1, INSPECTION_FAILED_HUMAN, b""),
    ]


def _read_only_tree_snapshot(root: Path) -> tuple[tuple[object, ...], ...]:
    if not root.exists():
        return ((str(root), "absent"),)
    observed: list[tuple[object, ...]] = []

    def visit(current: Path) -> None:
        with os.scandir(current) as entries:
            for entry in sorted(entries, key=lambda item: item.name.casefold()):
                stat_result = entry.stat(follow_symlinks=False)
                attributes = getattr(stat_result, "st_file_attributes", 0)
                relative = Path(entry.path).relative_to(root).as_posix()
                is_directory = entry.is_dir(follow_symlinks=False)
                observed.append(
                    (
                        relative,
                        is_directory,
                        stat_result.st_size,
                        stat_result.st_mtime_ns,
                        attributes,
                    )
                )
                if is_directory and not attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                    visit(Path(entry.path))

    visit(root)
    return tuple(observed)


def _doctor_owned_state_snapshot() -> tuple[tuple[str, tuple[tuple[object, ...], ...]], ...]:
    roots = (
        DEPLOYMENT_ROOT / "config",
        DEPLOYMENT_ROOT / "data",
        DEPLOYMENT_ROOT / "runtimes",
        DEPLOYMENT_ROOT / ".venv",
        DEPLOYMENT_ROOT / ".local" / "mineru",
        SOURCE_ROOT,
    )
    return tuple((str(root), _read_only_tree_snapshot(root)) for root in roots)


def test_real_doctor_runtime_is_read_only_through_both_launchers(
    tmp_path: Path,
) -> None:
    prohibited_marker = tmp_path / "prohibited-child.txt"
    (tmp_path / "sitecustomize.py").write_text(
        _read_only_doctor_site_customize(prohibited_marker),
        encoding="utf-8",
    )
    before = _doctor_owned_state_snapshot()

    results = run_both_launchers(
        ("doctor", "--json"),
        pythonpath_roots=(tmp_path, SOURCE_ROOT),
        environment_updates={"PYTHONDONTWRITEBYTECODE": "1"},
        timeout=90,
    )

    after = _doctor_owned_state_snapshot()
    receipts = [json.loads(result.stdout) for result in results]
    assert results[0].stdout == results[1].stdout
    assert results[0].returncode == results[1].returncode
    assert all(result.stderr == b"" for result in results)
    assert all(
        set(receipt)
        == {"schema_version", "command", "outcome", "result", "diagnostics"}
        and receipt["schema_version"] == "gezhi.cli_result.v1"
        and receipt["command"] == "doctor"
        for receipt in receipts
    )
    assert results[0].returncode == {
        "succeeded": 0,
        "blocked": 2,
        "failed": 1,
    }[receipts[0]["outcome"]]
    assert before == after
    assert not prohibited_marker.exists()


@pytest.mark.parametrize(
    "prohibited_source",
    (
        "import subprocess,sys; subprocess.Popen([sys.executable,'-m','pip','--version'])",
        "import subprocess; subprocess.Popen(['uv.exe','sync'])",
        (
            "import subprocess; subprocess.Popen(["
            f"{str(_CODEX_EXECUTABLE)!r},"
            "'exec','semantic request'])"
        ),
    ),
)
def test_read_only_doctor_guard_rejects_mutating_or_semantic_children(
    tmp_path: Path,
    prohibited_source: str,
) -> None:
    marker = tmp_path / "prohibited-child.txt"
    (tmp_path / "sitecustomize.py").write_text(
        _read_only_doctor_site_customize(marker),
        encoding="utf-8",
    )

    result = run_python_script(
        prohibited_source,
        environment_updates={
            "PYTHONPATH": os.pathsep.join((str(tmp_path), str(SOURCE_ROOT)))
        },
    )

    assert result.returncode != 0
    assert marker.read_text(encoding="utf-8") == "prohibited"
