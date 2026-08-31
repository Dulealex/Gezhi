from __future__ import annotations

import os
from contextlib import ExitStack
from pathlib import Path

from gezhi._configuration import ConfigurationError, resolve_configuration_v1
from gezhi._knowledge_status import (
    KnowledgeStatusProjectionFailedV1,
    project_knowledge_status_v1,
)
from gezhi._literature_status import (
    LiteratureStatusProjectionFailedV1,
    project_literature_overall_status_v1,
    project_literature_work_status_v1,
)
from gezhi._windows_data_root import (
    DataRootOpenErrorV1,
    ValidatedDataRootV1,
    data_root_does_not_physically_contain_project,
    data_roots_are_physically_isolated,
    open_validated_data_root_v1,
)
from gezhi._work_id import is_work_id_v1

_PROJECT_ROOT = Path(r"E:\Gezhi")
_ZERO_RECOVERY = {
    "staging_count": 0,
    "orphaned_count": 0,
    "quarantined_count": 0,
    "inconsistent_count": 0,
}


def _unavailable(availability: str) -> dict[str, object]:
    return {"availability": availability, "recovery": dict(_ZERO_RECOVERY)}


def _root_state(error: DataRootOpenErrorV1) -> str:
    return "unsafe" if error.status == "unsafe" else "unavailable"


def _open_context_root(
    stack: ExitStack,
    value: str,
) -> tuple[ValidatedDataRootV1 | None, str]:
    try:
        return stack.enter_context(open_validated_data_root_v1(value)), "ready"
    except DataRootOpenErrorV1 as error:
        return None, _root_state(error)


def _validate_root_relationships(
    stack: ExitStack,
    literature: ValidatedDataRootV1 | None,
    knowledge: ValidatedDataRootV1 | None,
) -> tuple[bool, bool]:
    opened = tuple(root for root in (literature, knowledge) if root is not None)
    if not opened:
        return True, True
    project = stack.enter_context(open_validated_data_root_v1(str(_PROJECT_ROOT)))
    safe = []
    for root in (literature, knowledge):
        safe.append(
            True
            if root is None
            else data_root_does_not_physically_contain_project(
                root.inspection,
                project.inspection,
            )
        )
    if literature is not None and knowledge is not None:
        isolated = data_roots_are_physically_isolated(
            literature.inspection,
            knowledge.inspection,
        )
        if not isolated:
            return False, False
    return safe[0], safe[1]


def _blocked_for_roots(states: tuple[tuple[str, str], ...]) -> dict[str, object]:
    facts: list[dict[str, object]] = []
    for state in ("unsafe", "unavailable"):
        contexts = [context for context, observed in states if observed == state]
        if contexts:
            facts.append(
                {
                    "reason": "data_root_" + state,
                    "contexts": contexts,
                }
            )
    if not facts:
        raise RuntimeError("a blocked root state is required")
    primary = facts[0]
    observation: dict[str, object] = {"kind": "blocked", **primary}
    if len(facts) > 1:
        observation["supplemental"] = facts[1:]
    return observation


def _observe_status_v1(
    *,
    project_root: Path,
    cli_patch: tuple[tuple[str, str], ...],
    environ: dict[str, str],
    work_id: str | None,
) -> dict[str, object]:
    try:
        configuration = resolve_configuration_v1(
            trusted_project_root=project_root,
            cli_patch=cli_patch,
            environ=environ,
        )
    except ConfigurationError:
        return {"kind": "blocked", "reason": "configuration_invalid"}
    except Exception:  # noqa: BLE001 - unexpected resolver faults fail closed.
        return {"kind": "failed"}
    if work_id is not None and not is_work_id_v1(work_id):
        return {"kind": "blocked", "reason": "invalid_work_id"}

    try:
        with ExitStack() as stack:
            literature, literature_state = _open_context_root(
                stack, configuration.literature_data_root
            )
            knowledge, knowledge_state = _open_context_root(
                stack, configuration.knowledge_data_root
            )
            literature_safe, knowledge_safe = _validate_root_relationships(
                stack,
                literature,
                knowledge,
            )
            if not literature_safe:
                literature = None
                literature_state = "unsafe"
            if not knowledge_safe:
                knowledge = None
                knowledge_state = "unsafe"

            states = (
                ("literature", literature_state),
                ("knowledge", knowledge_state),
            )
            if work_id is not None:
                if literature is None:
                    return _blocked_for_roots(states)
                literature_projection = project_literature_work_status_v1(
                    literature,
                    work_id,
                    include_intake_staging=True,
                )
                if literature_projection is None:
                    return {
                        "kind": "blocked",
                        "reason": "work_not_found",
                        "work_id": work_id,
                    }
                knowledge_projection = (
                    _unavailable(knowledge_state)
                    if knowledge is None
                    else project_knowledge_status_v1(knowledge, work_id=work_id)
                )
                literature_projection.pop("_status", None)
                return {
                    "kind": "work",
                    "work_id": work_id,
                    "literature": literature_projection,
                    "knowledge": knowledge_projection,
                }

            if literature is None and knowledge is None:
                return _blocked_for_roots(states)
            literature_projection = (
                _unavailable(literature_state)
                if literature is None
                else project_literature_overall_status_v1(literature)
            )
            knowledge_projection = (
                _unavailable(knowledge_state)
                if knowledge is None
                else project_knowledge_status_v1(knowledge, work_id=None)
            )
            return {
                "kind": "overall",
                "literature": literature_projection,
                "knowledge": knowledge_projection,
            }
    except (
        DataRootOpenErrorV1,
        KnowledgeStatusProjectionFailedV1,
        LiteratureStatusProjectionFailedV1,
        OSError,
    ):
        return {"kind": "failed"}
    except Exception:  # noqa: BLE001 - the observation surface is closed.
        return {"kind": "failed"}


def observe_status(
    *,
    cli_patch: tuple[tuple[str, str], ...],
    work_id: str | None,
) -> dict[str, object]:
    return _observe_status_v1(
        project_root=_PROJECT_ROOT,
        cli_patch=cli_patch,
        environ=os.environ.copy(),
        work_id=work_id,
    )
