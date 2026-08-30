"""Strict event and usage projection shared by the Knowledge writer and validator."""

from __future__ import annotations

import json

KNOWLEDGE_ATTEMPT_EVENTS_CAP_V1 = 16_777_216
_INT64_MAX = 9_223_372_036_854_775_807


def _reject_duplicate_pairs_v1(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("JSON object contains a duplicate key")
        value[key] = item
    return value


def _reject_constant_v1(_value: str) -> object:
    raise ValueError("JSON number must not be a non-standard constant")


class _JsonFloatTokenV1:
    __slots__ = ()


_JSON_FLOAT_TOKEN_V1 = _JsonFloatTokenV1()


def _mark_json_float_v1(_value: str) -> _JsonFloatTokenV1:
    return _JSON_FLOAT_TOKEN_V1


def parse_knowledge_attempt_events_v1(
    payload: bytes,
) -> tuple[tuple[dict[str, object], ...], bool]:
    """Parse one complete formal events asset without salvaging valid prefixes."""
    if payload.startswith(b"\xef\xbb\xbf"):
        return (), False
    try:
        payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return (), False
    if not payload:
        return (), True
    raw_records: list[bytes] = []
    start = 0
    while True:
        boundary = payload.find(b"\n", start)
        if boundary < 0:
            if start < len(payload):
                raw_records.append(payload[start:])
            break
        raw_records.append(payload[start:boundary])
        start = boundary + 1
        if start == len(payload):
            break
    records: list[dict[str, object]] = []
    completed_count = 0
    try:
        for raw_record in raw_records:
            if not raw_record:
                raise ValueError("Codex event record is empty")
            text = raw_record.decode("utf-8", errors="strict")
            value = json.loads(
                text,
                strict=True,
                object_pairs_hook=_reject_duplicate_pairs_v1,
                parse_float=_mark_json_float_v1,
                parse_constant=_reject_constant_v1,
            )
            if type(value) is not dict:
                raise ValueError("Codex event root is not an object")
            if value.get("type") == "turn.completed":
                completed_count += 1
                if completed_count > 1:
                    raise ValueError("Codex events contain duplicate completion")
            records.append(value)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return (), False
    return tuple(records), True


def project_knowledge_attempt_usage_v1(
    events: bytes,
    records: tuple[dict[str, object], ...],
    *,
    events_valid: bool,
) -> tuple[int | None, int | None, int | None, int | None]:
    """Project the four frozen usage fields from already parsed formal events."""
    if len(events) == KNOWLEDGE_ATTEMPT_EVENTS_CAP_V1 or not events_valid:
        return None, None, None, None
    completed = next(
        (record for record in records if record.get("type") == "turn.completed"),
        None,
    )
    usage = None if completed is None else completed.get("usage")
    if type(usage) is not dict:
        return None, None, None, None
    projected: list[int | None] = []
    for name in (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    ):
        value = usage.get(name)
        projected.append(
            value if type(value) is int and 0 <= value <= _INT64_MAX else None
        )
    return projected[0], projected[1], projected[2], projected[3]
