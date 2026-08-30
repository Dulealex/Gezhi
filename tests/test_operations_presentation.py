from __future__ import annotations

from typing import Any, cast

import pytest

from gezhi import _presentation as presentation


class _ForcedProcessExit(RuntimeError):
    pass


def test_operations_human_and_json_caps_are_inclusive() -> None:
    assert len(presentation.operations_human_buffer("a" * 65_536)) == 65_536
    with pytest.raises(ValueError, match="byte limit"):
        presentation.operations_human_buffer("a" * 65_537)

    base = presentation.operations_json_buffer(
        command="doctor",
        outcome="succeeded",
        result={"value": ""},
        diagnostics=(),
    )
    exact_fill = 65_536 - len(base)
    assert (
        len(
            presentation.operations_json_buffer(
                command="doctor",
                outcome="succeeded",
                result={"value": "a" * exact_fill},
                diagnostics=(),
            )
        )
        == 65_536
    )
    with pytest.raises(ValueError, match="byte limit"):
        presentation.operations_json_buffer(
            command="doctor",
            outcome="succeeded",
            result={"value": "a" * (exact_fill + 1)},
            diagnostics=(),
        )


def test_shared_cli_json_writer_has_an_inclusive_caller_selected_cap() -> None:
    uncapped = presentation.cli_json_buffer_v1(
        command="knowledge.search",
        outcome="succeeded",
        result={"value": ""},
        diagnostics=(),
        output_cap=1_048_576,
    )
    exact_cap = len(uncapped)
    assert (
        presentation.cli_json_buffer_v1(
            command="knowledge.search",
            outcome="succeeded",
            result={"value": ""},
            diagnostics=(),
            output_cap=exact_cap,
        )
        == uncapped
    )
    with pytest.raises(presentation.CliJsonOutputTooLargeV1):
        presentation.cli_json_buffer_v1(
            command="knowledge.search",
            outcome="succeeded",
            result={"value": ""},
            diagnostics=(),
            output_cap=exact_cap - 1,
        )


def test_operations_json_writer_owns_the_exact_closed_outer() -> None:
    payload = presentation.operations_json_buffer(
        command="doctor",
        outcome="blocked",
        result={"schema_version": "gezhi.doctor_result.v1"},
        diagnostics=({"code": "example.v1", "context": {}},),
    )

    assert payload == (
        b'{"command":"doctor","diagnostics":[{"code":"example.v1",'
        b'"context":{}}],"outcome":"blocked","result":{"schema_version":'
        b'"gezhi.doctor_result.v1"},"schema_version":"gezhi.cli_result.v1"}\n'
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("command", "future.unregistered", id="command"),
        pytest.param("outcome", "partial", id="outcome"),
        pytest.param("result", [], id="result"),
        pytest.param("diagnostics", ({"code": "bad"},), id="diagnostics"),
    ],
)
def test_operations_json_writer_rejects_an_invalid_shared_outer_field(
    field: str,
    value: object,
) -> None:
    arguments: dict[str, object] = {
        "command": "doctor",
        "outcome": "succeeded",
        "result": None,
        "diagnostics": (),
    }
    arguments[field] = value

    with pytest.raises((TypeError, ValueError)):
        presentation.operations_json_buffer(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("present", "value"),
    [
        pytest.param(
            presentation.present_operations_human,
            "a" * 65_537,
            id="human-cap",
        ),
        pytest.param(
            presentation.present_operations_json,
            {
                "command": "doctor",
                "outcome": "succeeded",
                "result": {"value": "a" * 65_536},
                "diagnostics": (),
            },
            id="json-cap",
        ),
    ],
)
def test_operations_sealing_failure_terminates_without_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
    present: Any,
    value: object,
) -> None:
    monkeypatch.setattr(
        presentation,
        "write_operations_stdout",
        lambda _buffer: pytest.fail("a failed seal must not write stdout"),
    )

    def forced_exit(code: int) -> None:
        raise _ForcedProcessExit(code)

    monkeypatch.setattr(presentation.os, "_exit", forced_exit)

    with pytest.raises(_ForcedProcessExit, match="1"):
        if present is presentation.present_operations_json:
            present(**cast(dict[str, Any], value))
        else:
            present(value)


def test_operations_writer_retries_only_the_remaining_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setmode_calls: list[tuple[int, int]] = []
    writes: list[bytes] = []

    def setmode(fd: int, mode: int) -> int:
        setmode_calls.append((fd, mode))
        return mode

    def write(fd: int, value: Any) -> int:
        assert fd == 1
        observed = bytes(value)
        writes.append(observed)
        return min(3, len(observed))

    monkeypatch.setattr(presentation.msvcrt, "setmode", setmode)
    monkeypatch.setattr(presentation.os, "write", write)

    presentation.write_operations_stdout(b"abcdefgh")

    assert setmode_calls == [(1, presentation.os.O_BINARY)]
    assert writes == [b"abcdefgh", b"defgh", b"gh"]


@pytest.mark.parametrize("invalid_count", [0, -1, 4, None, True])
def test_operations_writer_invalid_count_terminates_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    invalid_count: object,
) -> None:
    monkeypatch.setattr(
        presentation.msvcrt,
        "setmode",
        lambda _fd, mode: mode,
    )
    monkeypatch.setattr(presentation.os, "write", lambda _fd, _value: invalid_count)

    def forced_exit(code: int) -> None:
        raise _ForcedProcessExit(code)

    monkeypatch.setattr(presentation.os, "_exit", forced_exit)

    with pytest.raises(_ForcedProcessExit, match="1"):
        presentation.write_operations_stdout(b"abc")
