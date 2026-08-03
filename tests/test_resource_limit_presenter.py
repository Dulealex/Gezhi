from __future__ import annotations

import pytest

from gezhi import bootstrap

RESOURCE_LIMIT_STDERR = b"gezhi: error: command-line input exceeds safety limits\r\n"


def test_presenter_retries_with_each_exact_remaining_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[bytes] = []
    returned_counts = iter((7, 13, len(RESOURCE_LIMIT_STDERR) - 20))

    def write(fd: int, remaining: bytes | memoryview) -> int:
        assert fd == 2
        requested.append(bytes(remaining))
        return next(returned_counts)

    setmode_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        bootstrap.msvcrt,
        "setmode",
        lambda fd, mode: setmode_calls.append((fd, mode)),
    )
    monkeypatch.setattr(bootstrap.os, "write", write)

    bootstrap._present_resource_limit_exceeded()

    assert setmode_calls == [(2, bootstrap.os.O_BINARY)]
    assert requested == [
        RESOURCE_LIMIT_STDERR,
        RESOURCE_LIMIT_STDERR[7:],
        RESOURCE_LIMIT_STDERR[20:],
    ]


@pytest.mark.parametrize(
    "failing_operation",
    ["setmode", "first-write", "partial-write"],
)
def test_presenter_treats_direct_os_errors_as_completed_failure(
    monkeypatch: pytest.MonkeyPatch,
    failing_operation: str,
) -> None:
    write_requests: list[bytes] = []

    def fail() -> int:
        raise OSError("endpoint failure")

    def setmode(fd: int, mode: int) -> int:
        assert (fd, mode) == (2, bootstrap.os.O_BINARY)
        if failing_operation == "setmode":
            return fail()
        return mode

    def write(fd: int, remaining: bytes | memoryview) -> int:
        assert fd == 2
        write_requests.append(bytes(remaining))
        if failing_operation == "partial-write" and len(write_requests) == 1:
            return 5
        return fail()

    monkeypatch.setattr(bootstrap.msvcrt, "setmode", setmode)
    monkeypatch.setattr(bootstrap.os, "write", write)

    bootstrap._present_resource_limit_exceeded()

    expected_requests = {
        "setmode": [],
        "first-write": [RESOURCE_LIMIT_STDERR],
        "partial-write": [
            RESOURCE_LIMIT_STDERR,
            RESOURCE_LIMIT_STDERR[5:],
        ],
    }
    assert write_requests == expected_requests[failing_operation]


@pytest.mark.parametrize("invalid_count", [True, None, 0, -1, 57])
def test_presenter_stops_after_an_invalid_write_count(
    monkeypatch: pytest.MonkeyPatch,
    invalid_count: object,
) -> None:
    write_requests: list[bytes] = []

    def write(fd: int, remaining: bytes | memoryview) -> object:
        assert fd == 2
        write_requests.append(bytes(remaining))
        return invalid_count

    monkeypatch.setattr(bootstrap.msvcrt, "setmode", lambda fd, mode: mode)
    monkeypatch.setattr(
        bootstrap.os,
        "write",
        write,
    )

    bootstrap._present_resource_limit_exceeded()

    assert write_requests == [RESOURCE_LIMIT_STDERR]


def test_presenter_does_not_swallow_non_os_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(fd: int, mode: int) -> int:
        raise RuntimeError("unexpected implementation failure")

    monkeypatch.setattr(bootstrap.msvcrt, "setmode", fail)

    with pytest.raises(RuntimeError, match="unexpected implementation failure"):
        bootstrap._present_resource_limit_exceeded()
