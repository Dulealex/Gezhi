from __future__ import annotations

from pathlib import Path

import pytest
from launcher_support import REPOSITORY_ROOT

from gezhi._configuration import ConfigurationError, resolve_configuration_v1


def test_configuration_selects_the_first_present_value_for_each_leaf(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "default.toml").write_text(
        'config_version = "gezhi.config.v1"\n'
        "[literature]\n"
        'data_root = "D:\\\\L-default"\n'
        "[knowledge]\n"
        'data_root = "D:\\\\K-default"\n',
        encoding="utf-8",
    )
    (config_root / "local.toml").write_text(
        'config_version = "gezhi.config.v1"\n'
        "[knowledge]\n"
        'data_root = "D:\\\\K-local"\n',
        encoding="utf-8",
    )

    resolved = resolve_configuration_v1(
        trusted_project_root=tmp_path,
        cli_patch=(("knowledge.data_root", r"D:\K-cli"),),
        environ={"GEZHI_LITERATURE_DATA_ROOT": r"D:\L-env"},
    )

    assert (
        resolved.literature_data_root,
        resolved.knowledge_data_root,
    ) == (r"D:\L-env", r"D:\K-cli")


def test_configuration_rejects_an_invalid_lower_priority_source(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "default.toml").write_text(
        'config_version = "gezhi.config.v1"\n',
        encoding="utf-8",
    )
    (config_root / "local.toml").write_text(
        'config_version = "gezhi.config.v1"\n'
        "[literature]\n"
        'unknown = "must-not-be-masked"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError):
        resolve_configuration_v1(
            trusted_project_root=tmp_path,
            cli_patch=(
                ("literature.data_root", r"D:\L-cli"),
                ("knowledge.data_root", r"D:\K-cli"),
            ),
            environ={},
        )


def test_configuration_rejects_lexically_nested_context_roots(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "default.toml").write_text(
        'config_version = "gezhi.config.v1"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError):
        resolve_configuration_v1(
            trusted_project_root=tmp_path,
            cli_patch=(
                ("literature.data_root", r"D:\Research"),
                ("knowledge.data_root", r"d:/research/knowledge"),
            ),
            environ={},
        )


def test_configuration_rejects_a_project_internal_root_outside_data(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "default.toml").write_text(
        'config_version = "gezhi.config.v1"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError):
        resolve_configuration_v1(
            trusted_project_root=tmp_path,
            cli_patch=(
                ("literature.data_root", str(tmp_path / "data" / "literature")),
                ("knowledge.data_root", str(tmp_path / "other" / "knowledge")),
            ),
            environ={},
        )


def test_repository_default_configuration_activates_the_built_in_roots() -> None:
    resolved = resolve_configuration_v1(
        trusted_project_root=REPOSITORY_ROOT,
        cli_patch=(),
        environ={},
    )

    assert (
        resolved.literature_data_root,
        resolved.knowledge_data_root,
    ) == (
        r"E:\Gezhi\data\literature",
        r"E:\Gezhi\data\knowledge",
    )


def test_configuration_requires_the_versioned_default_document(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError):
        resolve_configuration_v1(
            trusted_project_root=tmp_path,
            cli_patch=(
                ("literature.data_root", r"D:\L"),
                ("knowledge.data_root", r"D:\K"),
            ),
            environ={},
        )


@pytest.mark.parametrize(
    "environ",
    [
        {"GEZHI_UNKNOWN": "value"},
        {
            "GEZHI_LITERATURE_DATA_ROOT": r"D:\L",
            "gezhi_literature_data_root": r"D:\Other",
        },
    ],
)
def test_configuration_rejects_unknown_or_case_duplicate_environment_names(
    tmp_path: Path,
    environ: dict[str, str],
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.toml").write_text(
        'config_version = "gezhi.config.v1"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError):
        resolve_configuration_v1(
            trusted_project_root=tmp_path,
            cli_patch=(
                ("literature.data_root", r"D:\L"),
                ("knowledge.data_root", r"D:\K"),
            ),
            environ=environ,
        )


def test_configuration_rejects_empty_selected_root_and_extended_alias_overlap(
    tmp_path: Path,
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.toml").write_text(
        'config_version = "gezhi.config.v1"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError):
        resolve_configuration_v1(
            trusted_project_root=tmp_path,
            cli_patch=(
                ("literature.data_root", ""),
                ("knowledge.data_root", r"D:\K"),
            ),
            environ={},
        )
    with pytest.raises(ConfigurationError):
        resolve_configuration_v1(
            trusted_project_root=tmp_path,
            cli_patch=(
                ("literature.data_root", r"D:\Research"),
                ("knowledge.data_root", r"\\?\d:\research\.\knowledge"),
            ),
            environ={},
        )


def test_configuration_leaves_ads_namespaces_for_the_consuming_gate(
    tmp_path: Path,
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.toml").write_text(
        'config_version = "gezhi.config.v1"\n',
        encoding="utf-8",
    )

    resolved = resolve_configuration_v1(
        trusted_project_root=tmp_path,
        cli_patch=(
            ("literature.data_root", r"D:\Root:stream"),
            ("knowledge.data_root", r"D:\Root:stream\child"),
        ),
        environ={},
    )

    assert (
        resolved.literature_data_root,
        resolved.knowledge_data_root,
    ) == (r"D:\Root:stream", r"D:\Root:stream\child")


@pytest.mark.parametrize(
    ("literature", "knowledge"),
    [
        pytest.param(r"D:\Root\NUL", r"D:\Root\NUL\child", id="dos-device"),
        pytest.param(r"D:\Root\name.", r"D:\Root\name.\child", id="trailing-dot"),
        pytest.param(r"D:\Root\*", r"D:\Root\*\child", id="wildcard"),
        pytest.param(r"D:\..\Root", r"D:\..\Root\child", id="above-volume"),
    ],
)
def test_configuration_leaves_unsupported_local_components_for_the_consuming_gate(
    tmp_path: Path,
    literature: str,
    knowledge: str,
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.toml").write_text(
        'config_version = "gezhi.config.v1"\n',
        encoding="utf-8",
    )

    resolved = resolve_configuration_v1(
        trusted_project_root=tmp_path,
        cli_patch=(
            ("literature.data_root", literature),
            ("knowledge.data_root", knowledge),
        ),
        environ={},
    )

    assert (resolved.literature_data_root, resolved.knowledge_data_root) == (
        literature,
        knowledge,
    )


@pytest.mark.parametrize(
    ("document", "expected_cause"),
    [
        pytest.param(
            'config_version = "not-a-generation"\n',
            "configuration_invalid",
            id="grammar-invalid",
        ),
        pytest.param(
            'config_version = "gezhi.config.v2"\nunknown = true\n',
            "configuration_incompatible",
            id="unsupported-wins-before-fields",
        ),
    ],
)
def test_configuration_error_preserves_the_closed_typed_cause(
    tmp_path: Path,
    document: str,
    expected_cause: str,
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.toml").write_text(
        document,
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as raised:
        resolve_configuration_v1(
            trusted_project_root=tmp_path,
            cli_patch=(),
            environ={},
        )

    assert raised.value.cause == expected_cause


def test_each_reducible_root_keeps_its_project_boundary_when_the_other_is_not(
    tmp_path: Path,
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.toml").write_text(
        'config_version = "gezhi.config.v1"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as raised:
        resolve_configuration_v1(
            trusted_project_root=tmp_path,
            cli_patch=(
                ("literature.data_root", r"\\server\share"),
                ("knowledge.data_root", str(tmp_path)),
            ),
            environ={},
        )

    assert raised.value.cause == "configuration_invalid"
