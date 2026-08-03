from __future__ import annotations

import pytest
from launcher_support import RESOURCE_LIMIT_STDERR

from gezhi import bootstrap


def _set_overlimit_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap.sys, "argv", ["gezhi", "x" * 8193])


@pytest.mark.parametrize(
    ("returned_counts", "expected_requests"),
    [
        pytest.param(
            (56,),
            [RESOURCE_LIMIT_STDERR],
            id="full-write",
        ),
        pytest.param(
            (7, 13, 36),
            [
                RESOURCE_LIMIT_STDERR,
                RESOURCE_LIMIT_STDERR[7:],
                RESOURCE_LIMIT_STDERR[20:],
            ],
            id="short-writes",
        ),
    ],
)
def test_main_writes_each_exact_remaining_suffix_and_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    returned_counts: tuple[int, ...],
    expected_requests: list[bytes],
) -> None:
    counts = iter(returned_counts)
    requested: list[bytes] = []
    setmode_calls: list[tuple[int, int]] = []

    def setmode(fd: int, mode: int) -> int:
        setmode_calls.append((fd, mode))
        return mode

    def write(fd: int, remaining: bytes | memoryview) -> int:
        assert fd == 2
        requested.append(bytes(remaining))
        return next(counts)

    _set_overlimit_argv(monkeypatch)
    monkeypatch.setattr(bootstrap.msvcrt, "setmode", setmode)
    monkeypatch.setattr(bootstrap.os, "write", write)

    assert bootstrap.main() == 2
    assert len(RESOURCE_LIMIT_STDERR) == 56
    assert setmode_calls == [(2, bootstrap.os.O_BINARY)]
    assert requested == expected_requests


@pytest.mark.parametrize(
    "failing_operation",
    ["setmode", "first-write", "partial-write"],
)
def test_main_returns_two_after_a_direct_os_error(
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

    _set_overlimit_argv(monkeypatch)
    monkeypatch.setattr(bootstrap.msvcrt, "setmode", setmode)
    monkeypatch.setattr(bootstrap.os, "write", write)

    assert bootstrap.main() == 2
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
def test_main_returns_two_after_an_invalid_write_count(
    monkeypatch: pytest.MonkeyPatch,
    invalid_count: object,
) -> None:
    write_requests: list[bytes] = []

    def write(fd: int, remaining: bytes | memoryview) -> object:
        assert fd == 2
        write_requests.append(bytes(remaining))
        return invalid_count

    _set_overlimit_argv(monkeypatch)
    monkeypatch.setattr(bootstrap.msvcrt, "setmode", lambda fd, mode: mode)
    monkeypatch.setattr(bootstrap.os, "write", write)

    assert bootstrap.main() == 2
    assert write_requests == [RESOURCE_LIMIT_STDERR]


@pytest.mark.parametrize("failing_operation", ["setmode", "write"])
def test_main_does_not_swallow_non_os_errors(
    monkeypatch: pytest.MonkeyPatch,
    failing_operation: str,
) -> None:
    def setmode(fd: int, mode: int) -> int:
        if failing_operation == "setmode":
            raise RuntimeError("unexpected setmode failure")
        return mode

    def write(fd: int, remaining: bytes | memoryview) -> int:
        raise RuntimeError("unexpected write failure")

    _set_overlimit_argv(monkeypatch)
    monkeypatch.setattr(bootstrap.msvcrt, "setmode", setmode)
    monkeypatch.setattr(bootstrap.os, "write", write)

    with pytest.raises(RuntimeError, match=f"unexpected {failing_operation} failure"):
        bootstrap.main()
