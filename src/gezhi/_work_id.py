from __future__ import annotations

import re
from typing import TypeGuard

_WORK_ID_V1 = re.compile(
    r"^wrk_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.ASCII,
)


def is_work_id_v1(value: object) -> TypeGuard[str]:
    """Return whether ``value`` is the frozen canonical Work identity."""

    return type(value) is str and _WORK_ID_V1.fullmatch(value) is not None
