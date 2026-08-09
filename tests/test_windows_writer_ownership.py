from __future__ import annotations

import queue
import subprocess
import threading

import pytest
from launcher_support import PYTHON_EXE, REPOSITORY_ROOT, subprocess_environment

from gezhi._windows_ownership import (
    WriterOwnershipLifecycleErrorV1,
    try_acquire_catalog_projection_v1,
    try_acquire_identity_intake_v1,
    try_acquire_work_writer_v1,
)

ROOT_IDENTITY = (123, 456)
WORK_ID = "wrk_123e4567-e89b-42d3-a456-426614174000"


def test_identity_intake_ownership_is_zero_wait_and_depth_one() -> None:
    first = try_acquire_identity_intake_v1(ROOT_IDENTITY)
    assert first is not None
    try:
        assert first.scope == "identity_intake"
        assert try_acquire_identity_intake_v1(ROOT_IDENTITY) is None
    finally:
        first.close()

    replacement = try_acquire_identity_intake_v1(ROOT_IDENTITY)
    assert replacement is not None
    replacement.close()


def test_work_writer_is_bound_to_root_identity_and_work_id() -> None:
    first = try_acquire_work_writer_v1(ROOT_IDENTITY, WORK_ID)
    assert first is not None
    try:
        assert first.scope == "work"
        assert first.work_id == WORK_ID
        assert try_acquire_work_writer_v1(ROOT_IDENTITY, WORK_ID) is None

        with pytest.raises(WriterOwnershipLifecycleErrorV1):
            try_acquire_work_writer_v1(
                ROOT_IDENTITY,
                "wrk_223e4567-e89b-42d3-a456-426614174000",
            )

        with pytest.raises(WriterOwnershipLifecycleErrorV1):
            try_acquire_work_writer_v1((123, 789), WORK_ID)
    finally:
        first.close()

    other_work = try_acquire_work_writer_v1(
        ROOT_IDENTITY,
        "wrk_223e4567-e89b-42d3-a456-426614174000",
    )
    assert other_work is not None
    other_work.close()

    other_root = try_acquire_work_writer_v1((123, 789), WORK_ID)
    assert other_root is not None
    other_root.close()


def test_catalog_projection_has_a_distinct_root_bound_scope() -> None:
    lease = try_acquire_catalog_projection_v1(ROOT_IDENTITY)
    assert lease is not None
    try:
        assert lease.scope == "catalog_projection"
        assert lease.work_id is None
        assert try_acquire_catalog_projection_v1(ROOT_IDENTITY) is None

        work = try_acquire_work_writer_v1(ROOT_IDENTITY, WORK_ID)
        assert work is not None
        work.close()
    finally:
        lease.close()


def test_named_mutex_blocks_another_thread_without_waiting() -> None:
    first = try_acquire_work_writer_v1(ROOT_IDENTITY, WORK_ID)
    assert first is not None
    observed: queue.Queue[object] = queue.Queue()

    def contend() -> None:
        observed.put(try_acquire_work_writer_v1(ROOT_IDENTITY, WORK_ID))

    thread = threading.Thread(target=contend)
    thread.start()
    thread.join(timeout=2)
    try:
        assert not thread.is_alive()
        assert observed.get_nowait() is None
    finally:
        first.close()


def test_global_named_mutex_blocks_another_process_without_waiting() -> None:
    source = (
        "import sys\n"
        "from gezhi._windows_ownership import try_acquire_work_writer_v1\n"
        f"lease = try_acquire_work_writer_v1({ROOT_IDENTITY!r}, {WORK_ID!r})\n"
        "assert lease is not None\n"
        "print('ready', flush=True)\n"
        "sys.stdin.buffer.read(1)\n"
        "lease.close()\n"
    )
    child = subprocess.Popen(
        [str(PYTHON_EXE), "-c", source],
        cwd=REPOSITORY_ROOT,
        env=subprocess_environment(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline() in {b"ready\n", b"ready\r\n"}
        assert try_acquire_work_writer_v1(ROOT_IDENTITY, WORK_ID) is None
        assert child.stdin is not None
        child.stdin.write(b"x")
        child.stdin.close()
        assert child.wait(timeout=5) == 0
        assert child.stderr is not None
        assert child.stderr.read() == b""
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)

    replacement = try_acquire_work_writer_v1(ROOT_IDENTITY, WORK_ID)
    assert replacement is not None
    replacement.close()


def test_writer_ownership_must_be_released_by_its_owner_thread() -> None:
    lease = try_acquire_work_writer_v1(ROOT_IDENTITY, WORK_ID)
    assert lease is not None
    observed: queue.Queue[BaseException | None] = queue.Queue()

    def release_from_wrong_thread() -> None:
        try:
            lease.close()
        except BaseException as error:  # noqa: BLE001 - exact lifecycle proof.
            observed.put(error)
        else:
            observed.put(None)

    thread = threading.Thread(target=release_from_wrong_thread)
    thread.start()
    thread.join(timeout=2)
    assert isinstance(observed.get_nowait(), RuntimeError)

    lease.close()


@pytest.mark.parametrize(
    "work_id",
    [
        "bad",
        "wrk_123E4567-E89B-42D3-A456-426614174000",
        "wrk_123e4567-e89b-52d3-a456-426614174000",
    ],
)
def test_work_writer_rejects_noncanonical_work_ids(work_id: str) -> None:
    with pytest.raises(ValueError):
        try_acquire_work_writer_v1(ROOT_IDENTITY, work_id)
