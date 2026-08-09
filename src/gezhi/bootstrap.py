from __future__ import annotations

import msvcrt
import os
import sys

from gezhi._raw_argv import RawArgvPreflightV1, RawArgvPreflightVerdictV1

_RESOURCE_LIMIT_STDERR = b"gezhi: error: command-line input exceeds safety limits\r\n"
_CLI_BOOTSTRAP_FAILED_STDERR = b"gezhi: error: cli bootstrap failed\r\n"


def _present_resource_limit_exceeded() -> None:
    _present_fixed_stderr(_RESOURCE_LIMIT_STDERR)


def _present_cli_bootstrap_failed() -> None:
    _present_fixed_stderr(_CLI_BOOTSTRAP_FAILED_STDERR)


def _present_fixed_stderr(buffer: bytes) -> None:
    try:
        msvcrt.setmode(2, os.O_BINARY)
    except OSError:
        return

    payload = memoryview(buffer)
    offset = 0
    while offset < len(payload):
        requested = len(payload) - offset
        try:
            count = os.write(2, payload[offset:])
        except OSError:
            return
        if type(count) is not int or not 1 <= count <= requested:
            return
        offset += count


def main() -> int:
    argv_snapshot = tuple(sys.argv)
    verdict = RawArgvPreflightV1.evaluate(argv_snapshot)
    if verdict is RawArgvPreflightVerdictV1.RESOURCE_LIMIT_EXCEEDED:
        _present_resource_limit_exceeded()
        return 2

    from gezhi._cli_bootstrap import (
        BootstrapPrerequisiteProbeV1,
        BootstrapPrerequisiteVerdictV1,
        StaticCommandGraphDescriptorValidatorV1,
        StaticCommandGraphVerdictV1,
        static_command_graph_descriptor_v1,
    )

    prerequisite_verdict = BootstrapPrerequisiteProbeV1.evaluate()
    if (
        prerequisite_verdict
        is BootstrapPrerequisiteVerdictV1.ESSENTIAL_UNAVAILABLE
    ):
        _present_cli_bootstrap_failed()
        return 1
    if prerequisite_verdict is not BootstrapPrerequisiteVerdictV1.ESSENTIAL_READY:
        raise TypeError("CLI prerequisite probe returned an invalid verdict")

    descriptor = static_command_graph_descriptor_v1()
    graph_verdict = StaticCommandGraphDescriptorValidatorV1.evaluate(descriptor)
    if graph_verdict is StaticCommandGraphVerdictV1.GRAPH_DESCRIPTOR_INVALID:
        _present_cli_bootstrap_failed()
        return 1
    if graph_verdict is not StaticCommandGraphVerdictV1.GRAPH_DESCRIPTOR_VALID:
        raise TypeError("CLI graph validator returned an invalid verdict")

    from gezhi._cli import run_cli

    return run_cli(argv_snapshot[1:], descriptor=descriptor)
