from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zlib
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from literature_pdf_support import write_blank_pdf, write_text_pdf
from pypdf import PdfReader, PdfWriter

from gezhi import _literature_resume as resume
from gezhi import _windows_data_root as windows_root
from gezhi._bounded_probe import (
    BoundedProbeResultV1,
    ProbeOutputLimitExceeded,
    ProbeUnavailableError,
)
from gezhi._literature_intake import AddLocalPdfRequestV1, add_local_pdf
from gezhi._literature_resume import (
    OcrAttemptResultV1,
    OcrRuntimeProfileV1,
    ResumeStoppedV1,
    resume_work,
)
from gezhi._windows_data_root import open_validated_data_root_v1
from gezhi._windows_ownership import try_acquire_work_writer_v1


@pytest.fixture
def scanned_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Path, str, str]]:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    data_root = tmp_path / "lit"
    data_root.mkdir()
    pdf_path = tmp_path / "scan.pdf"
    write_blank_pdf(pdf_path)
    with open_validated_data_root_v1(str(data_root)) as root:
        added = add_local_pdf(
            AddLocalPdfRequestV1(
                pdf_path=str(pdf_path),
                work_id=None,
                doi=None,
                arxiv_id=None,
                citation=None,
            ),
            root=root,
        )
    yield data_root, added.work_id, added.source_id


def _runtime() -> OcrRuntimeProfileV1:
    return OcrRuntimeProfileV1(
        executable_path=r"E:\Gezhi\runtimes\ocr\.venv\Scripts\mineru.exe",
        environment=(("HF_HUB_OFFLINE", "1"),),
        profile_identity_sha256=resume.expected_ocr_profile_identity_sha256_v1(),
    )


def _write_valid_mineru_output(
    output_root: Path,
    *,
    source_pdf: Path | None = None,
) -> None:
    if source_pdf is None:
        source_pdf = output_root.parents[2] / "input" / "source.pdf"
    leaf = output_root / "source" / "ocr"
    images = leaf / "images"
    images.mkdir(parents=True)
    files = {
        "source.md": b"# OCR text\n",
        "source_content_list.json": b"[]\n",
        "source_content_list_v2.json": b"[[]]\n",
        "source_middle.json": (
            b'{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":'
            b'[{"discarded_blocks":[],"page_idx":0,"page_size":[612,792],'
            b'"para_blocks":[]}]}\n'
        ),
        "source_model.json": (
            b'[{"layout_dets":[],"page_info":'
            b'{"height":792,"page_no":0,"width":612}}]\n'
        ),
    }
    for name, payload in files.items():
        (leaf / name).write_bytes(payload)
    write_blank_pdf(leaf / "source_layout.pdf")
    shutil.copyfile(source_pdf, leaf / "source_origin.pdf")
    write_blank_pdf(leaf / "source_span.pdf")


def _rewrite_pdf_pages(source: Path, target: Path) -> None:
    with source.open("rb") as source_stream, target.open("wb") as target_stream:
        reader = PdfReader(source_stream, strict=True)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.add_metadata({"/Producer": "MinerU PDFium rewrite"})
        writer.write(target_stream)


def _invoke(data_root: Path, work_id: str) -> ResumeStoppedV1:
    with open_validated_data_root_v1(str(data_root)) as root, pytest.raises(
        ResumeStoppedV1
    ) as caught:
        resume_work(work_id, root=root)
    return caught.value


def _rehash_run_and_current(run_dir: Path, current_path: Path) -> None:
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["assets"] = resume._asset_entries(run_dir)
    manifest_bytes = resume._canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)
    current = json.loads(current_path.read_bytes())
    current["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    current_path.write_bytes(resume._canonical_json_bytes(current))


def _clone_success_run(source: Path, target: Path, run_id: str) -> Path:
    shutil.copytree(source, target)
    receipt_path = target / "receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["run_id"] = run_id
    receipt_path.write_bytes(resume._canonical_json_bytes(receipt))
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["run_id"] = run_id
    manifest["assets"] = resume._asset_entries(target)
    manifest_path.write_bytes(resume._canonical_json_bytes(manifest))
    return target


def _invoke_unhandled(data_root: Path, work_id: str) -> None:
    with open_validated_data_root_v1(str(data_root)) as root:
        resume_work(work_id, root=root)


def test_scanned_pdf_uses_frozen_profile_and_commits_auditable_attempt(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    observed: list[tuple[str, Path, Path]] = []
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        profile: OcrRuntimeProfileV1,
        input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        observed.append((profile.executable_path, input_path, output_root))
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)

    stopped = _invoke(data_root, work_id)

    assert (stopped.outcome, stopped.stage, stopped.reason) == (
        "blocked",
        "canonicalize",
        "canonical_prerequisite_unavailable",
    )
    assert stopped.result is not None
    assert stopped.result.advanced_stages == ("ocr",)
    assert len(observed) == 1
    assert observed[0][1].name == "source.pdf"
    current = json.loads(
        (
            data_root
            / "works"
            / work_id
            / "sources"
            / source_id
            / "ocr"
            / "current.json"
        ).read_bytes()
    )
    run_dir = (
        data_root
        / "works"
        / work_id
        / "sources"
        / source_id
        / "ocr"
        / "runs"
        / current["run_id"]
    )
    receipt = json.loads((run_dir / "receipt.json").read_bytes())
    assert receipt["method"] == "mineru_ocr"
    assert receipt["attempt_count"] == 1
    assert (run_dir / "attempts" / "1" / "stdout.bin").read_bytes() == b"ok"
    assert (run_dir / "attempts" / "1" / "stderr.bin").read_bytes() == b""
    assert (run_dir / "output" / "mineru" / "source" / "ocr" / "source.md").is_file()


def test_semantically_equivalent_rewritten_origin_is_accepted(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, _source_id = scanned_source
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        _profile: OcrRuntimeProfileV1,
        input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        _write_valid_mineru_output(output_root, source_pdf=input_path)
        origin = output_root / "source" / "ocr" / "source_origin.pdf"
        _rewrite_pdf_pages(input_path, origin)
        assert origin.read_bytes() != input_path.read_bytes()
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)

    stopped = _invoke(data_root, work_id)

    assert stopped.stage == "canonicalize"


def test_private_input_cannot_be_replaced_while_mineru_is_running(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, _source_id = scanned_source
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        _profile: OcrRuntimeProfileV1,
        input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        with pytest.raises(OSError):
            input_path.write_bytes(b"replacement")
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)

    stopped = _invoke(data_root, work_id)

    assert stopped.stage == "canonicalize"


def test_transient_failure_retries_once_with_fresh_output(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    calls = 0
    sleeps: list[float] = []
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())
    monkeypatch.setattr(resume.time, "sleep", sleeps.append)

    def retry_then_succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.TimeoutExpired(("mineru",), 900)
        assert not output_root.exists()
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"second", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", retry_then_succeed)

    stopped = _invoke(data_root, work_id)

    assert stopped.stage == "canonicalize"
    assert calls == 2
    assert sleeps == [10.0]
    current = json.loads(
        (
            data_root
            / "works"
            / work_id
            / "sources"
            / source_id
            / "ocr"
            / "current.json"
        ).read_bytes()
    )
    run_dir = (
        data_root
        / "works"
        / work_id
        / "sources"
        / source_id
        / "ocr"
        / "runs"
        / current["run_id"]
    )
    assert json.loads((run_dir / "receipt.json").read_bytes())["attempt_count"] == 2
    assert (run_dir / "attempts" / "1" / "receipt.json").is_file()
    assert (run_dir / "attempts" / "2" / "receipt.json").is_file()


@pytest.mark.parametrize(
    "failure",
    ["runtime", "timeout", "output_limit", "invalid_output"],
)
def test_ocr_failure_never_creates_success_current_or_canonical_asset(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    data_root, work_id, source_id = scanned_source
    if failure == "runtime":
        monkeypatch.setattr(
            resume,
            "_resolve_ocr_runtime_v1",
            lambda: (_ for _ in ()).throw(resume.OcrRuntimeUnavailableV1()),
        )
    else:
        monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

        def fail(
            _profile: OcrRuntimeProfileV1,
            _input_path: Path,
            output_root: Path,
        ) -> OcrAttemptResultV1:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(("mineru",), 900)
            if failure == "output_limit":
                raise ProbeOutputLimitExceeded
            output_root.mkdir(parents=True)
            return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

        monkeypatch.setattr(resume, "_run_ocr_attempt_v1", fail)
        monkeypatch.setattr(resume.time, "sleep", lambda _seconds: None)

    stopped = _invoke(data_root, work_id)

    expected = {
        "runtime": ("blocked", "ocr_runtime_unavailable"),
        "timeout": ("blocked", "ocr_transient_exhausted"),
        "output_limit": ("failed", "ocr_failed"),
        "invalid_output": ("failed", "ocr_failed"),
    }[failure]
    assert (stopped.outcome, stopped.stage, stopped.reason) == (
        expected[0],
        "ocr",
        expected[1],
    )
    assert stopped.result is not None
    assert stopped.result.advanced_stages == ()
    source_dir = data_root / "works" / work_id / "sources" / source_id
    assert not (source_dir / "ocr" / "current.json").exists()
    assert not (source_dir / "canonical").exists()
    assert not tuple((source_dir / "ocr" / "runs" / ".staging").iterdir())
    terminal_runs = [
        item
        for item in (source_dir / "ocr" / "runs").iterdir()
        if item.name != ".staging"
    ]
    assert len(terminal_runs) == 1
    assert json.loads((terminal_runs[0] / "receipt.json").read_bytes())["status"] == (
        "blocked" if expected[0] == "blocked" else "failed"
    )


@pytest.mark.parametrize(
    "corruption",
    [
        "truncated_pdf",
        "origin_mismatch",
        "middle_shape",
        "content_shape",
        "model_shape",
        "image_header",
    ],
)
def test_structurally_corrupt_provider_output_is_ocr_failed(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    data_root, work_id, source_id = scanned_source
    calls = 0
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def corrupt(
        _profile: OcrRuntimeProfileV1,
        input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        nonlocal calls
        calls += 1
        _write_valid_mineru_output(output_root, source_pdf=input_path)
        leaf = output_root / "source" / "ocr"
        if corruption == "truncated_pdf":
            (leaf / "source_layout.pdf").write_bytes(b"%PDF-")
        elif corruption == "origin_mismatch":
            write_text_pdf(leaf / "source_origin.pdf", "different source")
        elif corruption == "middle_shape":
            (leaf / "source_middle.json").write_bytes(
                b'{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[]}\n'
            )
        elif corruption == "content_shape":
            (leaf / "source_content_list.json").write_bytes(
                b'[{"page_idx":0,"type":[]}]\n'
            )
        elif corruption == "model_shape":
            (leaf / "source_model.json").write_bytes(b"[{}]\n")
        else:
            (leaf / "images" / "forged.png").write_bytes(b"not-a-png")
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", corrupt)

    stopped = _invoke(data_root, work_id)

    assert calls == 1
    assert (stopped.outcome, stopped.stage, stopped.reason) == (
        "failed",
        "ocr",
        "ocr_failed",
    )
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    assert not (ocr_dir / "current.json").exists()


@pytest.mark.parametrize("failure", ["timeout", "output_limit"])
def test_ocr_stop_preserves_bounded_stdout_and_stderr_capture(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    data_root, work_id, source_id = scanned_source
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())
    monkeypatch.setattr(resume.time, "sleep", lambda _seconds: None)

    def fail(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        _output_root: Path,
    ) -> OcrAttemptResultV1:
        if failure == "timeout":
            raise subprocess.TimeoutExpired(
                ("mineru",),
                900,
                output=b"timeout-out",
                stderr=b"timeout-err",
            )
        raise ProbeOutputLimitExceeded(
            stdout=b"overflow-out",
            stderr=b"overflow-err",
        )

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", fail)

    stopped = _invoke(data_root, work_id)

    assert stopped.stage == "ocr"
    runs_dir = data_root / "works" / work_id / "sources" / source_id / "ocr" / "runs"
    run_dir = next(entry for entry in runs_dir.iterdir() if entry.name != ".staging")
    attempts = 2 if failure == "timeout" else 1
    for attempt in range(1, attempts + 1):
        attempt_dir = run_dir / "attempts" / str(attempt)
        expected_prefix = b"timeout" if failure == "timeout" else b"overflow"
        assert (attempt_dir / "stdout.bin").read_bytes() == expected_prefix + b"-out"
        assert (attempt_dir / "stderr.bin").read_bytes() == expected_prefix + b"-err"


@pytest.mark.parametrize("first", ["timeout", "process_failed"])
def test_transient_then_runtime_unavailable_commits_a_valid_blocked_run(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
    first: str,
) -> None:
    data_root, work_id, source_id = scanned_source
    calls = 0
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())
    monkeypatch.setattr(resume.time, "sleep", lambda _seconds: None)

    def stop_on_second_attempt(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        _output_root: Path,
    ) -> OcrAttemptResultV1:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ProbeUnavailableError("runtime disappeared")
        if first == "timeout":
            raise subprocess.TimeoutExpired(
                ("mineru",),
                900,
                output=b"first-out",
                stderr=b"first-err",
            )
        return OcrAttemptResultV1(
            returncode=17,
            stdout=b"first-out",
            stderr=b"first-err",
        )

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", stop_on_second_attempt)

    stopped = _invoke(data_root, work_id)

    assert (stopped.outcome, stopped.stage, stopped.reason) == (
        "blocked",
        "ocr",
        "ocr_runtime_unavailable",
    )
    runs_dir = data_root / "works" / work_id / "sources" / source_id / "ocr" / "runs"
    run_dir = next(entry for entry in runs_dir.iterdir() if entry.name != ".staging")
    assert json.loads((run_dir / "receipt.json").read_bytes())["attempt_count"] == 2
    outcomes = [
        json.loads((run_dir / "attempts" / str(attempt) / "receipt.json").read_bytes())[
            "outcome"
        ]
        for attempt in (1, 2)
    ]
    assert outcomes == [
        "timed_out" if first == "timeout" else "process_failed",
        "runtime_unavailable",
    ]


def test_committed_success_without_current_repairs_pointer_without_rerun(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    calls = 0
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        nonlocal calls
        calls += 1
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)
    first = _invoke(data_root, work_id)
    assert first.stage == "canonicalize"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    current_before = json.loads((ocr_dir / "current.json").read_bytes())
    (ocr_dir / "current.json").unlink()

    second = _invoke(data_root, work_id)

    assert calls == 1
    assert second.result is not None
    assert second.result.advanced_stages == ("ocr",)
    assert json.loads((ocr_dir / "current.json").read_bytes()) == current_before


def test_same_source_and_profile_have_stable_input_fingerprint_after_failed_retry(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())
    monkeypatch.setattr(resume.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        resume,
        "_run_ocr_attempt_v1",
        lambda *_args: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(("mineru",), 900)
        ),
    )
    first = _invoke(data_root, work_id)
    assert first.reason == "ocr_transient_exhausted"
    runs_dir = data_root / "works" / work_id / "sources" / source_id / "ocr" / "runs"
    failed_run = next(item for item in runs_dir.iterdir() if item.name != ".staging")
    first_fingerprint = json.loads((failed_run / "input.json").read_bytes())[
        "input_fingerprint_sha256"
    ]

    def succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)
    second = _invoke(data_root, work_id)

    assert second.stage == "canonicalize"
    current = json.loads((runs_dir.parent / "current.json").read_bytes())
    success_input = json.loads(
        (runs_dir / current["run_id"] / "input.json").read_bytes()
    )
    assert success_input["input_fingerprint_sha256"] == first_fingerprint


def test_nonzero_mineru_exit_retries_once_without_reusing_partial_output(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, _source_id = scanned_source
    calls = 0
    sleeps: list[float] = []
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())
    monkeypatch.setattr(resume.time, "sleep", sleeps.append)

    def fail_then_succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        nonlocal calls
        calls += 1
        if calls == 1:
            output_root.mkdir(parents=True)
            (output_root / "partial.bin").write_bytes(b"partial")
            return OcrAttemptResultV1(
                returncode=17,
                stdout=b"first",
                stderr=b"transient",
            )
        assert not output_root.exists()
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"second", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", fail_then_succeed)

    stopped = _invoke(data_root, work_id)

    assert stopped.stage == "canonicalize"
    assert calls == 2
    assert sleeps == [10.0]


def test_complete_success_staging_orphan_is_recovered_without_rerun(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    calls = 0
    real_rename = resume.os.rename
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        nonlocal calls
        calls += 1
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    def fail_run_rename_once(source: object, target: object) -> None:
        source_path = Path(source)  # type: ignore[arg-type]
        target_path = Path(target)  # type: ignore[arg-type]
        if source_path.parent.name == ".staging" and target_path.parent.name == "runs":
            raise OSError("injected run rename failure")
        real_rename(source, target)  # type: ignore[arg-type]

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)
    monkeypatch.setattr(resume.os, "rename", fail_run_rename_once)

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"
    staging_dir = (
        data_root
        / "works"
        / work_id
        / "sources"
        / source_id
        / "ocr"
        / "runs"
        / ".staging"
    )
    assert len(tuple(staging_dir.iterdir())) == 1

    monkeypatch.setattr(resume.os, "rename", real_rename)
    second = _invoke(data_root, work_id)

    assert second.stage == "canonicalize"
    assert second.result is not None
    assert second.result.advanced_stages == ("ocr",)
    assert calls == 1
    assert not tuple(staging_dir.iterdir())


def test_two_complete_staging_successes_fail_stop_before_any_rename(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)
    assert _invoke(data_root, work_id).stage == "canonicalize"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    current_path = ocr_dir / "current.json"
    current = json.loads(current_path.read_bytes())
    runs_dir = ocr_dir / "runs"
    staging_dir = runs_dir / ".staging"
    first = staging_dir / current["run_id"]
    (runs_dir / current["run_id"]).rename(first)
    current_path.unlink()
    second_id = "ocrrun_123e4567-e89b-42d3-a456-426614174001"
    second = _clone_success_run(first, staging_dir / second_id, second_id)

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"
    assert {entry.name for entry in staging_dir.iterdir()} == {
        first.name,
        second.name,
    }
    assert not [entry for entry in runs_dir.iterdir() if entry.name != ".staging"]
    assert not current_path.exists()


def test_valid_current_still_classifies_matching_staging_success(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)
    assert _invoke(data_root, work_id).stage == "canonicalize"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    current_path = ocr_dir / "current.json"
    current_bytes = current_path.read_bytes()
    current = json.loads(current_bytes)
    runs_dir = ocr_dir / "runs"
    staged_id = "ocrrun_123e4567-e89b-42d3-a456-426614174002"
    staged = _clone_success_run(
        runs_dir / current["run_id"],
        runs_dir / ".staging" / staged_id,
        staged_id,
    )

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"
    assert staged.is_dir()
    assert (runs_dir / current["run_id"]).is_dir()
    assert current_path.read_bytes() == current_bytes


def test_formal_and_staging_run_id_collision_fail_stops_without_mutation(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)
    assert _invoke(data_root, work_id).stage == "canonicalize"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    current = json.loads((ocr_dir / "current.json").read_bytes())
    runs_dir = ocr_dir / "runs"
    staged = _clone_success_run(
        runs_dir / current["run_id"],
        runs_dir / ".staging" / current["run_id"],
        current["run_id"],
    )

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"
    assert staged.is_dir()
    assert (runs_dir / current["run_id"]).is_dir()


def test_uuid_collision_with_quarantined_staging_fail_stops_before_write(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    fixed = UUID("123e4567-e89b-42d3-a456-426614174003")
    stage = (
        data_root
        / "works"
        / work_id
        / "sources"
        / source_id
        / "ocr"
        / "runs"
        / ".staging"
        / f"ocrrun_{fixed}"
    )
    stage.mkdir(parents=True)
    marker = stage / "partial.bin"
    marker.write_bytes(b"quarantine")
    monkeypatch.setattr(resume.uuid, "uuid4", lambda: fixed)

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"
    assert tuple(stage.iterdir()) == (marker,)
    assert marker.read_bytes() == b"quarantine"


def test_recovery_rename_rechecks_root_before_mutation(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)
    assert _invoke(data_root, work_id).stage == "canonicalize"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    current = json.loads((ocr_dir / "current.json").read_bytes())
    runs_dir = ocr_dir / "runs"
    orphan = runs_dir / ".staging" / current["run_id"]
    (runs_dir / current["run_id"]).rename(orphan)
    (ocr_dir / "current.json").unlink()

    def reject_checkpoint(
        _authority: object,
        _root: object,
    ) -> None:
        raise ResumeStoppedV1(
            "failed",
            "data_root_integrity_lost",
            data_root="literature",
        )

    monkeypatch.setattr(resume, "_fresh_authority_or_stop", reject_checkpoint)

    with pytest.raises(ResumeStoppedV1) as caught:
        _invoke_unhandled(data_root, work_id)

    assert (caught.value.reason, caught.value.result) == (
        "data_root_integrity_lost",
        None,
    )
    assert orphan.is_dir()
    assert not (runs_dir / current["run_id"]).exists()


def test_new_staging_creation_rechecks_root_before_write(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source

    def reject_checkpoint(
        _authority: object,
        _root: object,
    ) -> None:
        raise ResumeStoppedV1(
            "failed",
            "data_root_integrity_lost",
            data_root="literature",
        )

    monkeypatch.setattr(resume, "_fresh_authority_or_stop", reject_checkpoint)
    monkeypatch.setattr(
        resume,
        "_select_source_text_v1",
        lambda _path: pytest.fail("selector must not run after root drift"),
    )

    with pytest.raises(ResumeStoppedV1) as caught:
        _invoke_unhandled(data_root, work_id)

    assert (caught.value.reason, caught.value.result) == (
        "data_root_integrity_lost",
        None,
    )
    staging = (
        data_root
        / "works"
        / work_id
        / "sources"
        / source_id
        / "ocr"
        / "runs"
        / ".staging"
    )
    assert not tuple(staging.iterdir())


def test_partial_staging_is_quarantined_and_never_used_as_success(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    staging_dir = (
        data_root
        / "works"
        / work_id
        / "sources"
        / source_id
        / "ocr"
        / "runs"
        / ".staging"
    )
    partial = staging_dir / "ocrrun_123e4567-e89b-42d3-a456-426614174000"
    partial.mkdir(parents=True)
    (partial / "partial.bin").write_bytes(b"do not reuse")
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)

    stopped = _invoke(data_root, work_id)

    assert stopped.stage == "canonicalize"
    assert partial.is_dir()
    assert (partial / "partial.bin").read_bytes() == b"do not reuse"
    current = json.loads((staging_dir.parent.parent / "current.json").read_bytes())
    assert current["run_id"] != partial.name


def test_corrupt_current_is_asset_integrity_lost_and_does_not_rerun(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)
    assert _invoke(data_root, work_id).stage == "canonicalize"
    current_path = (
        data_root
        / "works"
        / work_id
        / "sources"
        / source_id
        / "ocr"
        / "current.json"
    )
    current = json.loads(current_path.read_bytes())
    current["manifest_sha256"] = "0" * 64
    current_path.write_bytes(resume._canonical_json_bytes(current))
    monkeypatch.setattr(
        resume,
        "_run_ocr_attempt_v1",
        lambda *_args: pytest.fail("corrupt current must not rerun OCR"),
    )

    stopped = _invoke(data_root, work_id)

    assert (stopped.outcome, stopped.stage, stopped.reason) == (
        "failed",
        "ocr",
        "asset_integrity_lost",
    )


def test_unhashable_corrupt_selection_is_classified_as_asset_integrity_lost(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)
    assert _invoke(data_root, work_id).stage == "canonicalize"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    current = json.loads((ocr_dir / "current.json").read_bytes())
    selection_path = ocr_dir / "runs" / current["run_id"] / "selection.json"
    selection = json.loads(selection_path.read_bytes())
    selection["method"] = []
    selection_path.write_bytes(resume._canonical_json_bytes(selection))
    monkeypatch.setattr(
        resume,
        "_run_ocr_attempt_v1",
        lambda *_args: pytest.fail("corrupt selection must not rerun OCR"),
    )

    stopped = _invoke(data_root, work_id)

    assert (stopped.outcome, stopped.stage, stopped.reason) == (
        "failed",
        "ocr",
        "asset_integrity_lost",
    )


def test_semantically_forged_attempt_receipt_is_asset_integrity_lost(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)
    assert _invoke(data_root, work_id).stage == "canonicalize"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    current_path = ocr_dir / "current.json"
    current = json.loads(current_path.read_bytes())
    run_dir = ocr_dir / "runs" / current["run_id"]
    attempt_path = run_dir / "attempts" / "1" / "receipt.json"
    attempt = json.loads(attempt_path.read_bytes())
    attempt["outcome"] = "process_failed"
    attempt["returncode"] = 17
    attempt_path.write_bytes(resume._canonical_json_bytes(attempt))
    _rehash_run_and_current(run_dir, current_path)
    monkeypatch.setattr(
        resume,
        "_run_ocr_attempt_v1",
        lambda *_args: pytest.fail("forged success must not rerun OCR"),
    )

    stopped = _invoke(data_root, work_id)

    assert (stopped.outcome, stopped.stage, stopped.reason) == (
        "failed",
        "ocr",
        "asset_integrity_lost",
    )


def test_work_contention_blocks_before_native_selector_or_runtime_probe(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, _source_id = scanned_source
    monkeypatch.setattr(
        resume,
        "_select_source_text_v1",
        lambda _path: pytest.fail("selector must not run while Work is busy"),
    )
    with open_validated_data_root_v1(str(data_root)) as root:
        assert root.inspection.identity is not None
        owner = try_acquire_work_writer_v1(root.inspection.identity, work_id)
        assert owner is not None
        try:
            with pytest.raises(ResumeStoppedV1) as caught:
                resume_work(work_id, root=root)
        finally:
            owner.close()

    assert (caught.value.outcome, caught.value.reason, caught.value.result) == (
        "blocked",
        "work_busy",
        None,
    )


def test_provider_artifact_budget_accepts_exact_limits_and_rejects_sparse_overflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = tmp_path / "stage"
    provider = stage / "attempts" / "1" / "provider_output"
    provider.mkdir(parents=True)
    first = provider / "first.bin"
    first.write_bytes(b"a" * 8)
    second = provider / "second.bin"
    second.write_bytes(b"b" * 8)
    monkeypatch.setattr(resume, "_OCR_ARTIFACT_FILE_LIMIT", 16)
    monkeypatch.setattr(resume, "_OCR_ARTIFACT_AGGREGATE_LIMIT", 16)
    monkeypatch.setattr(resume, "_OCR_ARTIFACT_FILE_COUNT_LIMIT", 2)
    monkeypatch.setattr(resume, "_OCR_AUDIT_FREE_SPACE_RESERVE", 0)

    resume._enforce_ocr_artifact_budget_v1(stage)

    with second.open("r+b") as sparse:
        sparse.seek(16)
        sparse.write(b"x")
    with pytest.raises(RuntimeError) as caught:
        resume._enforce_ocr_artifact_budget_v1(stage)
    assert type(caught.value).__name__ == "_OcrArtifactBudgetExceededV1"


def test_provider_pdf_parser_accepts_exact_file_limit_and_rejects_limit_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    pdf_path = tmp_path / "provider.pdf"
    payload = write_blank_pdf(pdf_path)
    monkeypatch.setattr(resume, "_OCR_PDF_FILE_LIMIT", len(payload))

    resume._validate_pdf_output(pdf_path, page_count=1)

    monkeypatch.setattr(resume, "_OCR_PDF_FILE_LIMIT", len(payload) - 1)
    with pytest.raises(RuntimeError) as caught:
        resume._validate_pdf_output(pdf_path, page_count=1)
    assert type(caught.value).__name__ == "_OcrOutputInvalidV1"


def test_pdf_content_decode_accepts_exact_limit_and_rejects_overflow_or_tail(
) -> None:
    assert resume._bounded_flate_decode_v1(
        zlib.compress(b"x" * 16),
        limit=16,
    ) == b"x" * 16
    with pytest.raises(RuntimeError):
        resume._bounded_flate_decode_v1(
            zlib.compress(b"x" * 17),
            limit=16,
        )
    with pytest.raises(RuntimeError):
        resume._bounded_flate_decode_v1(
            zlib.compress(b"x") + b"trailing",
            limit=16,
        )


def test_partial_output_over_budget_fail_stops_before_retry_or_formal_commit(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    calls = 0
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())
    monkeypatch.setattr(resume, "_OCR_ARTIFACT_FILE_LIMIT", 16)
    monkeypatch.setattr(resume, "_OCR_ARTIFACT_AGGREGATE_LIMIT", 16)
    monkeypatch.setattr(resume, "_OCR_ARTIFACT_FILE_COUNT_LIMIT", 2)
    monkeypatch.setattr(resume, "_OCR_AUDIT_FREE_SPACE_RESERVE", 0)

    def overflow(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        nonlocal calls
        calls += 1
        output_root.mkdir(parents=True)
        with (output_root / "sparse.bin").open("wb") as sparse:
            sparse.seek(16)
            sparse.write(b"x")
        return OcrAttemptResultV1(returncode=17, stdout=b"", stderr=b"full")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", overflow)

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_OcrArtifactBudgetExceededV1"
    assert calls == 1
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    assert not (ocr_dir / "current.json").exists()
    assert not [
        entry for entry in (ocr_dir / "runs").iterdir() if entry.name != ".staging"
    ]
    assert len(tuple((ocr_dir / "runs" / ".staging").iterdir())) == 1


def test_low_free_space_fail_stops_before_mineru_launch(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())
    monkeypatch.setattr(
        resume.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=100, used=100, free=0),
    )
    monkeypatch.setattr(
        resume,
        "_run_ocr_attempt_v1",
        lambda *_args: pytest.fail("MinerU must not launch without audit reserve"),
    )

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_OcrArtifactBudgetExceededV1"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    assert not (ocr_dir / "current.json").exists()


def test_production_mineru_adapter_uses_exact_frozen_command_and_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def complete(command: object, **values: object) -> BoundedProbeResultV1:
        observed["command"] = command
        observed.update(values)
        return BoundedProbeResultV1(returncode=0, stdout=b"out", stderr=b"err")

    monkeypatch.setattr(resume, "run_bounded_probe_v1", complete)
    profile = OcrRuntimeProfileV1(
        executable_path=r"E:\Gezhi\runtimes\ocr\.venv\Scripts\mineru.exe",
        environment=(("HF_HUB_OFFLINE", "1"), ("MINERU_MODEL_SOURCE", "local")),
        profile_identity_sha256=resume.expected_ocr_profile_identity_sha256_v1(),
    )

    result = resume._run_ocr_attempt_v1(
        profile,
        Path(r"E:\data\input\source.pdf"),
        Path(r"E:\data\output"),
    )

    assert result == OcrAttemptResultV1(returncode=0, stdout=b"out", stderr=b"err")
    assert observed["command"] == (
        profile.executable_path,
        "-p",
        r"E:\data\input\source.pdf",
        "-o",
        r"E:\data\output",
        "-b",
        "pipeline",
        "-m",
        "ocr",
        "-l",
        "ch",
    )
    assert observed["environment"] == dict(profile.environment)
    assert observed["timeout_seconds"] == 900.0
    assert observed["output_limit"] == 1_048_576
    assert observed["creation_flags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
