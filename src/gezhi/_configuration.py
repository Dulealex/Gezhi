from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from gezhi._windows_data_root import normalize_local_path_v1

_CONFIG_VERSION = "gezhi.config.v1"
_BUILT_IN_DEFAULTS = {
    "literature.data_root": r"E:\Gezhi\data\literature",
    "knowledge.data_root": r"E:\Gezhi\data\knowledge",
}
_ENVIRONMENT_NAMES = {
    "gezhi_literature_data_root": "literature.data_root",
    "gezhi_knowledge_data_root": "knowledge.data_root",
}
_LEAF_NAMES = frozenset(_BUILT_IN_DEFAULTS)
_CONFIG_VERSION_GRAMMAR = re.compile(r"^gezhi\.config\.v[1-9][0-9]*$")

ConfigurationErrorCause: TypeAlias = Literal[
    "configuration_invalid",
    "configuration_incompatible",
]


class ConfigurationError(ValueError):
    """The invocation configuration cannot form a valid V1 snapshot."""

    def __init__(
        self,
        message: str,
        *,
        cause: ConfigurationErrorCause = "configuration_invalid",
    ) -> None:
        super().__init__(message)
        self.cause = cause


@dataclass(frozen=True, slots=True)
class ResolvedConfigurationV1:
    literature_data_root: str
    knowledge_data_root: str


def _toml_patch(path: Path, *, required: bool) -> dict[str, str]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        if not required:
            return {}
        raise ConfigurationError("required configuration is absent") from None
    except OSError as error:
        raise ConfigurationError("configuration is unreadable") from error

    try:
        document = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError("configuration is invalid") from error
    version = document.get("config_version")
    if type(version) is not str or _CONFIG_VERSION_GRAMMAR.fullmatch(version) is None:
        raise ConfigurationError("configuration version is invalid")
    if version != _CONFIG_VERSION:
        raise ConfigurationError(
            "configuration version is unsupported",
            cause="configuration_incompatible",
        )
    if set(document) - {"config_version", "literature", "knowledge"}:
        raise ConfigurationError("configuration contains an unknown field")

    patch: dict[str, str] = {}
    for context in ("literature", "knowledge"):
        table = document.get(context)
        if table is None:
            continue
        if type(table) is not dict or set(table) - {"data_root"}:
            raise ConfigurationError("configuration table is invalid")
        if "data_root" in table:
            value = table["data_root"]
            if type(value) is not str:
                raise ConfigurationError("configuration value is invalid")
            patch[f"{context}.data_root"] = value
    return patch


def _environment_patch(environ: Mapping[str, str]) -> dict[str, str]:
    patch: dict[str, str] = {}
    seen: set[str] = set()
    for name, value in environ.items():
        folded = name.casefold()
        if not folded.startswith("gezhi_"):
            continue
        leaf = _ENVIRONMENT_NAMES.get(folded)
        if leaf is None or folded in seen or type(value) is not str:
            raise ConfigurationError("environment configuration is invalid")
        seen.add(folded)
        patch[leaf] = value
    return patch


def _cli_patch(values: Sequence[tuple[str, str]]) -> dict[str, str]:
    patch: dict[str, str] = {}
    for leaf, value in values:
        if leaf not in _LEAF_NAMES or leaf in patch or type(value) is not str:
            raise ConfigurationError("CLI configuration is invalid")
        patch[leaf] = value
    return patch


def _normalized_local_namespace(value: str) -> str | None:
    normalized = normalize_local_path_v1(value)
    return None if normalized is None else normalized.casefold()


def _contains_or_equals(ancestor: str, candidate: str) -> bool:
    return candidate == ancestor or candidate.startswith(ancestor.rstrip("\\") + "\\")


def _validate_lexical_isolation(
    literature: str,
    knowledge: str,
    *,
    trusted_project_root: Path,
) -> None:
    literature_namespace = _normalized_local_namespace(literature)
    knowledge_namespace = _normalized_local_namespace(knowledge)
    if (
        literature_namespace is not None
        and knowledge_namespace is not None
        and (
            _contains_or_equals(literature_namespace, knowledge_namespace)
            or _contains_or_equals(knowledge_namespace, literature_namespace)
        )
    ):
        raise ConfigurationError("configured Data Roots overlap")
    project_namespace = _normalized_local_namespace(str(trusted_project_root))
    data_namespace = _normalized_local_namespace(str(trusted_project_root / "data"))
    if project_namespace is None or data_namespace is None:
        raise RuntimeError("trusted project root is not a local Windows path")
    for namespace in (literature_namespace, knowledge_namespace):
        if namespace is None:
            continue
        if _contains_or_equals(namespace, project_namespace):
            raise ConfigurationError("a Data Root contains the project root")
        if _contains_or_equals(project_namespace, namespace) and (
            namespace == data_namespace
            or not _contains_or_equals(data_namespace, namespace)
        ):
            raise ConfigurationError(
                "a project Data Root is outside the data container"
            )


def resolve_configuration_v1(
    *,
    trusted_project_root: Path,
    cli_patch: Sequence[tuple[str, str]],
    environ: Mapping[str, str],
) -> ResolvedConfigurationV1:
    sources = (
        _cli_patch(cli_patch),
        _environment_patch(environ),
        _toml_patch(trusted_project_root / "config" / "local.toml", required=False),
        _toml_patch(trusted_project_root / "config" / "default.toml", required=True),
        _BUILT_IN_DEFAULTS,
    )
    resolved: dict[str, str] = {}
    for leaf in _LEAF_NAMES:
        for source in sources:
            if leaf in source:
                resolved[leaf] = source[leaf]
                break
    if any(not resolved.get(leaf) for leaf in _LEAF_NAMES):
        raise ConfigurationError("resolved configuration is invalid")
    _validate_lexical_isolation(
        resolved["literature.data_root"],
        resolved["knowledge.data_root"],
        trusted_project_root=trusted_project_root,
    )
    return ResolvedConfigurationV1(
        literature_data_root=resolved["literature.data_root"],
        knowledge_data_root=resolved["knowledge.data_root"],
    )
