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
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NullObject,
    NumberObject,
)

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


def _write_form_pdf(
    path: Path,
    *,
    compressed_form: bool,
    bbox: tuple[int | float, int | float, int | float, int | float] = (
        0,
        0,
        12,
        12,
    ),
    matrix: tuple[int, int, int, int, int, int] | None = None,
    form_type: int | None = None,
    flate_array_length: int = 0,
) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    form = DecodedStreamObject()
    form.set_data(b"q 0 0 12 12 re f Q")
    form_values = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject(
                [
                    FloatObject(str(item))
                    if type(item) is float
                    else NumberObject(item)
                    for item in bbox
                ]
            ),
            NameObject("/Resources"): DictionaryObject(),
        }
    )
    if matrix is not None:
        form_values[NameObject("/Matrix")] = ArrayObject(
            [NumberObject(item) for item in matrix]
        )
    if form_type is not None:
        form_values[NameObject("/FormType")] = NumberObject(form_type)
    form.update(form_values)
    encoded_form = form.flate_encode() if compressed_form else form
    if flate_array_length:
        encoded_form[NameObject("/Filter")] = ArrayObject(
            [NameObject("/FlateDecode") for _index in range(flate_array_length)]
        )
        encoded_form[NameObject("/DecodeParms")] = ArrayObject([NullObject()])
    form_reference = writer._add_object(encoded_form)
    resources = DictionaryObject(
        {
            NameObject("/XObject"): DictionaryObject(
                {NameObject("/Fm0"): form_reference}
            )
        }
    )
    page[NameObject("/Resources")] = resources
    content = DecodedStreamObject()
    content.set_data(b"q /Fm0 Do Q")
    page[NameObject("/Contents")] = writer._add_object(content)
    with path.open("wb") as stream:
        writer.write(stream)


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


def test_native_page_ordinal_rejects_json_boolean_alias_for_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    data_root = tmp_path / "lit"
    data_root.mkdir()
    pdf_path = tmp_path / "native.pdf"
    write_text_pdf(
        pdf_path,
        "The first native page contains more than thirty two visible characters.",
        "The second native page also contains more than thirty two characters.",
    )
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
    assert _invoke(data_root, added.work_id).stage == "canonicalize"
    ocr_dir = (
        data_root
        / "works"
        / added.work_id
        / "sources"
        / added.source_id
        / "ocr"
    )
    current_path = ocr_dir / "current.json"
    current = json.loads(current_path.read_bytes())
    run_dir = ocr_dir / "runs" / current["run_id"]
    native_path = run_dir / "output" / "native_text.json"
    native = json.loads(native_path.read_bytes())
    native["pages"][1]["page_index"] = True
    native_path.write_bytes(resume._canonical_json_bytes(native))
    _rehash_run_and_current(run_dir, current_path)

    stopped = _invoke(data_root, added.work_id)

    assert (stopped.outcome, stopped.stage, stopped.reason) == (
        "failed",
        "ocr",
        "asset_integrity_lost",
    )


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
                raise ProbeOutputLimitExceeded(
                    stdout=b"x" * resume._OCR_OUTPUT_LIMIT
                )
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
        "middle_item",
        "middle_empty_block",
        "middle_missing_block_field",
        "content_shape",
        "content_payload",
        "content_bbox",
        "boolean_bbox",
        "missing_image_reference",
        "traversal_image_reference",
        "v2_payload",
        "model_shape",
        "model_item",
        "huge_dimension",
        "giant_integer",
        "deep_json",
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
        elif corruption == "middle_item":
            middle = json.loads((leaf / "source_middle.json").read_bytes())
            middle["pdf_info"][0]["para_blocks"] = [None]
            (leaf / "source_middle.json").write_bytes(json.dumps(middle).encode())
        elif corruption in {"middle_empty_block", "middle_missing_block_field"}:
            middle = json.loads((leaf / "source_middle.json").read_bytes())
            block = (
                {}
                if corruption == "middle_empty_block"
                else {
                    "bbox": [0, 0, 1, 1],
                    "index": 0,
                    "lines": [],
                    "type": "text",
                }
            )
            middle["pdf_info"][0]["para_blocks"] = [block]
            (leaf / "source_middle.json").write_bytes(json.dumps(middle).encode())
        elif corruption == "content_shape":
            (leaf / "source_content_list.json").write_bytes(
                b'[{"page_idx":0,"type":[]}]\n'
            )
        elif corruption == "content_payload":
            (leaf / "source_content_list.json").write_bytes(
                b'[{"bbox":[0,0,1,1],"page_idx":0,"type":"text"}]\n'
            )
        elif corruption == "content_bbox":
            (leaf / "source_content_list.json").write_bytes(
                b'[{"page_idx":0,"text":"missing bbox","type":"text"}]\n'
            )
        elif corruption == "boolean_bbox":
            (leaf / "source_content_list.json").write_bytes(
                b'[{"bbox":[false,0,1,1],"page_idx":0,'
                b'"text":"bad bbox","type":"text"}]\n'
            )
        elif corruption in {"missing_image_reference", "traversal_image_reference"}:
            image_path = (
                "images/missing.png"
                if corruption == "missing_image_reference"
                else "images/../forged.png"
            )
            (leaf / "source_content_list.json").write_bytes(
                json.dumps(
                    [
                        {
                            "bbox": [0, 0, 1, 1],
                            "image_caption": [],
                            "image_footnote": [],
                            "img_path": image_path,
                            "page_idx": 0,
                            "type": "image",
                        }
                    ]
                ).encode()
            )
        elif corruption == "v2_payload":
            (leaf / "source_content_list_v2.json").write_bytes(
                b'[[{"bbox":[0,0,1,1],"content":{"arbitrary":[]},'
                b'"type":"paragraph"}]]\n'
            )
        elif corruption == "model_shape":
            (leaf / "source_model.json").write_bytes(b"[{}]\n")
        elif corruption == "model_item":
            model = json.loads((leaf / "source_model.json").read_bytes())
            model[0]["layout_dets"] = [None]
            (leaf / "source_model.json").write_bytes(json.dumps(model).encode())
        elif corruption == "huge_dimension":
            (leaf / "source_middle.json").write_bytes(
                b'{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":'
                b'[{"discarded_blocks":[],"page_idx":0,"page_size":['
                + (b"9" * 4_000)
                + b',792],"para_blocks":[]}]}\n'
            )
        elif corruption == "giant_integer":
            (leaf / "source_content_list.json").write_bytes(
                b"[" + (b"9" * 5_000) + b"]\n"
            )
        elif corruption == "deep_json":
            (leaf / "source_content_list.json").write_bytes(
                (b"[" * 2_000) + (b"]" * 2_000) + b"\n"
            )
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


def test_provider_page_ordinals_reject_json_boolean_alias_for_one() -> None:
    middle = {
        "_backend": "pipeline",
        "_version_name": "3.4.4",
        "pdf_info": [
            {
                "discarded_blocks": [],
                "page_idx": 0,
                "page_size": [612, 792],
                "para_blocks": [],
            },
            {
                "discarded_blocks": [],
                "page_idx": True,
                "page_size": [612, 792],
                "para_blocks": [],
            },
        ],
    }
    model = [
        {
            "layout_dets": [],
            "page_info": {"height": 792, "page_no": 0, "width": 612},
        },
        {
            "layout_dets": [],
            "page_info": {"height": 792, "page_no": True, "width": 612},
        },
    ]

    with pytest.raises(RuntimeError) as middle_error:
        resume._validate_middle_document(middle)
    with pytest.raises(RuntimeError) as model_error:
        resume._validate_model_document(model, page_count=2)

    assert type(middle_error.value).__name__ == "_OcrOutputInvalidV1"
    assert type(model_error.value).__name__ == "_OcrOutputInvalidV1"


def test_middle_image_span_binds_bare_leaf_to_provider_inventory() -> None:
    span = {
        "bbox": [0, 0, 10, 10],
        "image_path": "asset.jpg",
        "type": "image",
    }

    assert resume._valid_middle_span_v1(span, {"images/asset.jpg"})
    for invalid in ("images/asset.jpg", "../asset.jpg", "missing.jpg"):
        changed = dict(span)
        changed["image_path"] = invalid
        assert not resume._valid_middle_span_v1(
            changed,
            {"images/asset.jpg"},
        )


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.01, 1.01])
def test_middle_image_span_rejects_invalid_optional_score(score: float) -> None:
    span = {
        "bbox": [0, 0, 10, 10],
        "image_path": "asset.jpg",
        "score": score,
        "type": "image",
    }

    assert not resume._valid_middle_span_v1(span, {"images/asset.jpg"})


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
        stderr = b"overflow-err"
        prefix = b"overflow-out"
        raise ProbeOutputLimitExceeded(
            stdout=prefix + b"x" * (resume._OCR_OUTPUT_LIMIT - len(prefix) - len(stderr)),
            stderr=stderr,
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
        stdout = (attempt_dir / "stdout.bin").read_bytes()
        stderr = (attempt_dir / "stderr.bin").read_bytes()
        assert stdout.startswith(expected_prefix + b"-out")
        assert stderr == expected_prefix + b"-err"
        if failure == "output_limit":
            assert len(stdout) + len(stderr) == resume._OCR_OUTPUT_LIMIT


@pytest.mark.parametrize("extra_byte", [False, True])
def test_historical_attempt_capture_enforces_combined_inclusive_limit(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
    extra_byte: bool,
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
    attempt_dir = run_dir / "attempts" / "1"
    (attempt_dir / "stdout.bin").write_bytes(b"a" * resume._OCR_OUTPUT_LIMIT)
    (attempt_dir / "stderr.bin").write_bytes(b"b" if extra_byte else b"")
    _rehash_run_and_current(run_dir, current_path)
    monkeypatch.setattr(
        resume,
        "_run_ocr_attempt_v1",
        lambda *_args: pytest.fail("historical success must not rerun OCR"),
    )

    stopped = _invoke(data_root, work_id)

    if extra_byte:
        assert (stopped.outcome, stopped.stage, stopped.reason) == (
            "failed",
            "ocr",
            "asset_integrity_lost",
        )
    else:
        assert stopped.stage == "canonicalize"


def test_historical_output_limit_outcome_requires_full_retained_capture(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())
    monkeypatch.setattr(
        resume,
        "_run_ocr_attempt_v1",
        lambda *_args: (_ for _ in ()).throw(
            ProbeOutputLimitExceeded(stdout=b"x" * resume._OCR_OUTPUT_LIMIT)
        ),
    )
    stopped = _invoke(data_root, work_id)
    assert stopped.reason == "ocr_failed"
    runs_dir = data_root / "works" / work_id / "sources" / source_id / "ocr" / "runs"
    run_dir = next(item for item in runs_dir.iterdir() if item.name != ".staging")
    with open_validated_data_root_v1(str(data_root)) as root:
        authority = resume._load_authority_or_stop(work_id, root)
        resume._load_run(run_dir, run_dir.name, authority)

    capture = run_dir / "attempts" / "1" / "stdout.bin"
    capture.write_bytes(b"x" * (resume._OCR_OUTPUT_LIMIT - 1))
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["assets"] = resume._asset_entries(run_dir)
    manifest_path.write_bytes(resume._canonical_json_bytes(manifest))

    with open_validated_data_root_v1(str(data_root)) as root:
        authority = resume._load_authority_or_stop(work_id, root)
        with pytest.raises(RuntimeError) as caught:
            resume._load_run(run_dir, run_dir.name, authority)

    assert type(caught.value).__name__ == "_RunInvalidV1"


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


def test_retry_revalidates_runtime_after_backoff_before_second_launch(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    runtime_checks = 0
    launches = 0

    def resolve() -> OcrRuntimeProfileV1:
        nonlocal runtime_checks
        runtime_checks += 1
        if runtime_checks == 3:
            raise resume.OcrRuntimeUnavailableV1
        return _runtime()

    def time_out_once(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        _output_root: Path,
    ) -> OcrAttemptResultV1:
        nonlocal launches
        launches += 1
        raise subprocess.TimeoutExpired(
            ("mineru",),
            900,
            output=b"first-out",
            stderr=b"first-err",
        )

    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", resolve)
    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", time_out_once)
    monkeypatch.setattr(resume.time, "sleep", lambda _seconds: None)

    stopped = _invoke(data_root, work_id)

    assert (stopped.outcome, stopped.stage, stopped.reason) == (
        "blocked",
        "ocr",
        "ocr_runtime_unavailable",
    )
    assert runtime_checks == 3
    assert launches == 1
    runs_dir = data_root / "works" / work_id / "sources" / source_id / "ocr" / "runs"
    run_dir = next(item for item in runs_dir.iterdir() if item.name != ".staging")
    assert json.loads((run_dir / "receipt.json").read_bytes())["attempt_count"] == 2
    assert json.loads(
        (run_dir / "attempts" / "2" / "receipt.json").read_bytes()
    )["outcome"] == "runtime_unavailable"


def test_first_attempt_launch_time_runtime_drift_is_audited_without_launch(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    runtime_checks = 0
    launches = 0

    def resolve() -> OcrRuntimeProfileV1:
        nonlocal runtime_checks
        runtime_checks += 1
        if runtime_checks == 2:
            raise resume.OcrRuntimeUnavailableV1
        return _runtime()

    def launch(*_args: object) -> OcrAttemptResultV1:
        nonlocal launches
        launches += 1
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", resolve)
    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", launch)

    stopped = _invoke(data_root, work_id)

    assert (stopped.outcome, stopped.stage, stopped.reason) == (
        "blocked",
        "ocr",
        "ocr_runtime_unavailable",
    )
    assert runtime_checks == 2
    assert launches == 0
    runs_dir = data_root / "works" / work_id / "sources" / source_id / "ocr" / "runs"
    run_dir = next(item for item in runs_dir.iterdir() if item.name != ".staging")
    assert json.loads((run_dir / "receipt.json").read_bytes())["attempt_count"] == 1
    assert json.loads(
        (run_dir / "attempts" / "1" / "receipt.json").read_bytes()
    )["outcome"] == "runtime_unavailable"


def test_runtime_revalidation_is_the_last_observable_step_before_each_launch(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, _source_id = scanned_source
    events: list[str] = []
    launches = 0
    real_budget = resume._enforce_ocr_artifact_budget_v1

    def resolve() -> OcrRuntimeProfileV1:
        events.append("runtime")
        return _runtime()

    def enforce_budget(stage: Path) -> None:
        events.append("budget")
        real_budget(stage)

    def launch(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        nonlocal launches
        events.append("launch")
        launches += 1
        if launches == 1:
            raise subprocess.TimeoutExpired(("mineru",), 900)
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", resolve)
    monkeypatch.setattr(resume, "_enforce_ocr_artifact_budget_v1", enforce_budget)
    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", launch)
    monkeypatch.setattr(resume.time, "sleep", lambda _seconds: None)

    assert _invoke(data_root, work_id).stage == "canonicalize"

    launch_indexes = [
        index for index, event in enumerate(events) if event == "launch"
    ]
    assert len(launch_indexes) == 2
    assert all(events[index - 1] == "runtime" for index in launch_indexes)


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


def test_current_temp_uuid_collision_preserves_foreign_marker(
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
    assert _invoke(data_root, work_id).stage == "canonicalize"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    (ocr_dir / "current.json").unlink()
    fixed = UUID("123e4567-e89b-42d3-a456-426614174004")
    marker = ocr_dir / f".current.json.{fixed.hex}.tmp"
    marker.write_bytes(b"foreign-marker")
    monkeypatch.setattr(resume.uuid, "uuid4", lambda: fixed)

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"
    assert marker.read_bytes() == b"foreign-marker"
    assert not (ocr_dir / "current.json").exists()
    assert calls == 1


def test_foreign_current_temp_is_classified_before_pointer_repair(
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
    assert _invoke(data_root, work_id).stage == "canonicalize"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    (ocr_dir / "current.json").unlink()
    foreign = ocr_dir / ".current.json.123e4567e89b42d3a456426614174005.tmp"
    foreign.write_bytes(b"foreign-marker")

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"
    assert foreign.read_bytes() == b"foreign-marker"
    assert not (ocr_dir / "current.json").exists()
    assert calls == 1


def test_multiple_valid_current_temps_are_ambiguous_recovery_evidence(
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
    assert _invoke(data_root, work_id).stage == "canonicalize"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    payload = (ocr_dir / "current.json").read_bytes()
    (ocr_dir / "current.json").unlink()
    first = ocr_dir / ".current.json.123e4567e89b42d3a456426614174006.tmp"
    second = ocr_dir / ".current.json.123e4567e89b42d3a456426614174007.tmp"
    first.write_bytes(payload)
    second.write_bytes(payload)

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"
    assert first.read_bytes() == payload
    assert second.read_bytes() == payload
    assert not (ocr_dir / "current.json").exists()
    assert calls == 1


def test_current_authority_drift_after_temp_write_preserves_temp_without_replace(
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
    (ocr_dir / "current.json").unlink()
    real_checkpoint = resume._fresh_authority_or_stop
    real_replace = resume.os.replace
    checkpoints = 0
    replace_calls = 0

    def drift_on_atomic_pre_replace(authority: object, root: object) -> object:
        nonlocal checkpoints
        checkpoints += 1
        if checkpoints == 3:
            raise ResumeStoppedV1(
                "failed",
                "data_root_integrity_lost",
                data_root="literature",
            )
        return real_checkpoint(authority, root)  # type: ignore[arg-type]

    def observe_replace(source: object, target: object) -> None:
        nonlocal replace_calls
        replace_calls += 1
        real_replace(source, target)  # type: ignore[arg-type]

    monkeypatch.setattr(resume, "_fresh_authority_or_stop", drift_on_atomic_pre_replace)
    monkeypatch.setattr(resume.os, "replace", observe_replace)

    with pytest.raises(ResumeStoppedV1) as caught:
        _invoke_unhandled(data_root, work_id)

    assert caught.value.reason == "data_root_integrity_lost"
    assert checkpoints == 3
    assert replace_calls == 0
    assert not (ocr_dir / "current.json").exists()
    assert len(tuple(ocr_dir.glob(".current.json.*.tmp"))) == 1


def test_uncertain_current_replace_preserves_evidence_and_recovers_next_time(
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
    assert _invoke(data_root, work_id).stage == "canonicalize"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    current_before = json.loads((ocr_dir / "current.json").read_bytes())
    (ocr_dir / "current.json").unlink()
    real_replace = resume.os.replace

    def fail_current_replace(source: object, target: object) -> None:
        if Path(target).name == "current.json":  # type: ignore[arg-type]
            raise OSError("injected uncertain replace")
        real_replace(source, target)  # type: ignore[arg-type]

    monkeypatch.setattr(resume.os, "replace", fail_current_replace)
    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"
    assert not (ocr_dir / "current.json").exists()
    evidence = tuple(ocr_dir.glob(".current.json.*.tmp"))
    assert len(evidence) == 1
    replacement_source_matched_evidence: list[bool] = []
    replacement_completed = False
    fail_readback_once = True
    real_read = resume._read_safe_bytes

    def observe_recovery_replace(source: object, target: object) -> None:
        nonlocal replacement_completed
        if Path(target).name == "current.json":  # type: ignore[arg-type]
            replacement_source_matched_evidence.append(
                Path(source).read_bytes() == evidence[0].read_bytes()  # type: ignore[arg-type]
            )
        real_replace(source, target)  # type: ignore[arg-type]
        if Path(target).name == "current.json":  # type: ignore[arg-type]
            replacement_completed = True

    def fail_recovery_readback_once(
        path: Path,
        *,
        limit: int = resume._MAX_INT64,
    ) -> bytes:
        nonlocal fail_readback_once
        if (
            path == ocr_dir / "current.json"
            and replacement_completed
            and fail_readback_once
        ):
            fail_readback_once = False
            raise resume._RunInvalidV1("injected recovery readback failure")
        return real_read(path, limit=limit)

    monkeypatch.setattr(resume.os, "replace", observe_recovery_replace)
    monkeypatch.setattr(resume, "_read_safe_bytes", fail_recovery_readback_once)

    with pytest.raises(RuntimeError) as recovery_error:
        _invoke_unhandled(data_root, work_id)

    assert type(recovery_error.value).__name__ == "_RecoveryCertaintyLostV1"
    assert evidence[0].read_bytes() == resume._canonical_json_bytes(current_before)
    assert tuple(ocr_dir.glob(".current.json.*.tmp")) == evidence

    recovered = _invoke(data_root, work_id)

    assert recovered.stage == "canonicalize"
    assert recovered.result is not None
    assert recovered.result.advanced_stages == ("ocr",)
    assert json.loads((ocr_dir / "current.json").read_bytes()) == current_before
    assert replacement_source_matched_evidence == [True, True]
    assert not tuple(ocr_dir.glob(".current.json.*.tmp"))
    assert calls == 1


def test_current_readback_failure_after_replace_preserves_temp_evidence(
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
    current = ocr_dir / "current.json"
    expected = current.read_bytes()
    current.unlink()
    real_replace = resume.os.replace
    real_read = resume._read_safe_bytes
    replacement_completed = False
    fail_readback_once = True

    def observe_replace(source: object, target: object) -> None:
        nonlocal replacement_completed
        real_replace(source, target)  # type: ignore[arg-type]
        if Path(target) == current:  # type: ignore[arg-type]
            replacement_completed = True

    def fail_current_readback(path: Path, *, limit: int = resume._MAX_INT64) -> bytes:
        nonlocal fail_readback_once
        if path == current and replacement_completed and fail_readback_once:
            fail_readback_once = False
            raise resume._RunInvalidV1("injected current readback failure")
        return real_read(path, limit=limit)

    monkeypatch.setattr(resume.os, "replace", observe_replace)
    monkeypatch.setattr(resume, "_read_safe_bytes", fail_current_readback)

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"
    evidence = tuple(ocr_dir.glob(".current.json.*.tmp"))
    assert len(evidence) == 1
    assert evidence[0].read_bytes() == expected
    assert current.read_bytes() == expected

    recovered = _invoke(data_root, work_id)

    assert recovered.result is not None
    assert recovered.result.advanced_stages == ("ocr",)
    assert not tuple(ocr_dir.glob(".current.json.*.tmp"))


def test_current_publish_does_not_require_hard_link_support(
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

    def reject_hard_link(*_args: object, **_kwargs: object) -> None:
        raise OSError("hard links are not supported")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)
    monkeypatch.setattr(resume.os, "link", reject_hard_link)

    stopped = _invoke(data_root, work_id)

    assert stopped.stage == "canonicalize"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    assert (ocr_dir / "current.json").is_file()
    assert not tuple(ocr_dir.glob(".current.json.*.tmp"))


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


def test_historical_attempt_ordinal_rejects_json_boolean_alias_for_one(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
    calls = 0
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())
    monkeypatch.setattr(resume.time, "sleep", lambda _seconds: None)

    def retry_then_succeed(
        _profile: OcrRuntimeProfileV1,
        _input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.TimeoutExpired(("mineru",), 900)
        _write_valid_mineru_output(output_root)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", retry_then_succeed)
    assert _invoke(data_root, work_id).stage == "canonicalize"
    ocr_dir = data_root / "works" / work_id / "sources" / source_id / "ocr"
    current_path = ocr_dir / "current.json"
    current = json.loads(current_path.read_bytes())
    run_dir = ocr_dir / "runs" / current["run_id"]
    receipt_path = run_dir / "attempts" / "1" / "receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["attempt"] = True
    receipt_path.write_bytes(resume._canonical_json_bytes(receipt))
    _rehash_run_and_current(run_dir, current_path)

    stopped = _invoke(data_root, work_id)

    assert (stopped.outcome, stopped.stage, stopped.reason) == (
        "failed",
        "ocr",
        "asset_integrity_lost",
    )


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


def test_partial_staging_with_formal_run_id_fail_stops_without_mutation(
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
    partial = runs_dir / ".staging" / current["run_id"]
    partial.mkdir()
    marker = partial / "partial.bin"
    marker.write_bytes(b"quarantine")

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"
    assert marker.read_bytes() == b"quarantine"
    assert current_path.read_bytes() == current_bytes
    assert (runs_dir / current["run_id"]).is_dir()


def test_staging_collision_precedes_corrupt_current_classification(
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
    current["manifest_sha256"] = "0" * 64
    current_path.write_bytes(resume._canonical_json_bytes(current))
    runs_dir = ocr_dir / "runs"
    partial = runs_dir / ".staging" / current["run_id"]
    partial.mkdir()
    marker = partial / "partial.bin"
    marker.write_bytes(b"quarantine")

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"
    assert marker.read_bytes() == b"quarantine"


def test_namespace_inventory_failure_is_not_a_handled_recovery_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    namespace = tmp_path / "runs"
    namespace.mkdir()
    real_scandir = resume.os.scandir

    def fail_inventory(path: object) -> object:
        if Path(path) == namespace:  # type: ignore[arg-type]
            raise OSError("injected inventory failure")
        return real_scandir(path)  # type: ignore[call-overload]

    monkeypatch.setattr(resume.os, "scandir", fail_inventory)

    with pytest.raises(RuntimeError) as caught:
        resume._snapshot_recovery_namespace_v1(namespace)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"


def test_recovery_namespace_snapshot_is_fixed_size_and_detects_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    namespace = tmp_path / "runs"
    namespace.mkdir()
    for index in range(128):
        (namespace / f"entry-{index:04d}").mkdir()

    before = resume._snapshot_recovery_namespace_v1(namespace)
    repeated = resume._snapshot_recovery_namespace_v1(namespace)
    names = [f"entry-{index:04d}" for index in range(128)]

    assert before == repeated
    assert resume._snapshot_recovery_name_stream_v1(
        iter(names)
    ) == resume._snapshot_recovery_name_stream_v1(reversed(names))
    assert before.entry_count == 128
    assert set(before.__dataclass_fields__) == {
        "entry_count",
        "sum_sha256",
        "xor_sha256",
    }

    (namespace / "entry-0000").rename(namespace / "entry-renamed")

    renamed = resume._snapshot_recovery_namespace_v1(namespace)
    assert renamed.entry_count == before.entry_count
    assert renamed != before

    (namespace / "entry-new").mkdir()

    assert resume._snapshot_recovery_namespace_v1(namespace) != renamed


def test_existing_staging_validation_failure_is_not_commit_failed(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, work_id, source_id = scanned_source
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
    staging.mkdir(parents=True)
    real_open = resume.open_validated_data_root_v1

    def reject_staging(path: str) -> object:
        if Path(path) == staging:
            raise windows_root.DataRootOpenErrorV1("unsafe")
        return real_open(path)

    monkeypatch.setattr(resume, "open_validated_data_root_v1", reject_staging)

    with pytest.raises(RuntimeError) as caught:
        _invoke_unhandled(data_root, work_id)

    assert type(caught.value).__name__ == "_RecoveryCertaintyLostV1"


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


def test_deeply_nested_staging_document_is_quarantined(
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
    partial = staging_dir / "ocrrun_123e4567-e89b-42d3-a456-426614174005"
    partial.mkdir(parents=True)
    (partial / "selection.json").write_bytes(
        (b"[" * 2_000) + (b"]" * 2_000)
    )
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


def test_deeply_nested_current_is_asset_integrity_lost(
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
    current_path.write_bytes((b"[" * 2_000) + (b"]" * 2_000))

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


def test_provider_artifact_scan_stops_at_first_namespace_entry_over_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = tmp_path / "provider"
    provider.mkdir()
    for name in ("a.bin", "b.bin", "c.bin"):
        (provider / name).write_bytes(b"x")
    real_scandir = resume.os.scandir
    requested: list[int] = []

    class GuardedScandir:
        def __init__(self, path: Path) -> None:
            self._inner = real_scandir(path)
            self._count = 0

        def __iter__(self) -> GuardedScandir:
            return self

        def __next__(self) -> object:
            self._count += 1
            requested.append(self._count)
            if self._count > 2:
                raise AssertionError("scanner consumed beyond the decisive entry")
            return next(self._inner)

        def close(self) -> None:
            self._inner.close()

    monkeypatch.setattr(resume.os, "scandir", GuardedScandir)
    monkeypatch.setattr(resume, "_OCR_ARTIFACT_FILE_COUNT_LIMIT", 1)
    monkeypatch.setattr(resume, "_OCR_ARTIFACT_NAMESPACE_ENTRY_LIMIT", 1)

    with pytest.raises(RuntimeError) as caught:
        resume._scan_ocr_artifact_tree(provider)

    assert type(caught.value).__name__ == "_OcrArtifactBudgetExceededV1"
    assert requested == [1, 2]


def test_provider_artifact_file_limit_does_not_count_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = tmp_path / "provider"
    nested = provider / "source" / "ocr"
    nested.mkdir(parents=True)
    (nested / "a.bin").write_bytes(b"a")
    (nested / "b.bin").write_bytes(b"b")
    monkeypatch.setattr(resume, "_OCR_ARTIFACT_FILE_COUNT_LIMIT", 2)
    monkeypatch.setattr(resume, "_OCR_ARTIFACT_NAMESPACE_ENTRY_LIMIT", 8)

    assert resume._scan_ocr_artifact_tree(provider) == (2, 2)


@pytest.mark.parametrize("over_limit", [False, True])
def test_private_ocr_input_is_gated_before_copy_or_parse(
    scanned_source: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
    over_limit: bool,
) -> None:
    data_root, work_id, source_id = scanned_source
    source_path = (
        data_root
        / "works"
        / work_id
        / "sources"
        / source_id
        / "original.pdf"
    )
    monkeypatch.setattr(
        resume,
        "_OCR_PDF_FILE_LIMIT",
        source_path.stat().st_size - int(over_limit),
    )
    monkeypatch.setattr(resume, "_resolve_ocr_runtime_v1", lambda: _runtime())

    def succeed(
        _profile: OcrRuntimeProfileV1,
        input_path: Path,
        output_root: Path,
    ) -> OcrAttemptResultV1:
        _write_valid_mineru_output(output_root, source_pdf=input_path)
        return OcrAttemptResultV1(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(resume, "_run_ocr_attempt_v1", succeed)
    if over_limit:
        monkeypatch.setattr(
            resume,
            "_copy_source_to_private_input",
            lambda *_args: pytest.fail("oversized source must not be copied"),
        )
        monkeypatch.setattr(
            resume,
            "_select_source_text_v1",
            lambda *_args: pytest.fail("oversized source must not be parsed"),
        )
        with pytest.raises(RuntimeError) as caught:
            _invoke_unhandled(data_root, work_id)
        assert type(caught.value).__name__ == "_OcrArtifactBudgetExceededV1"
        staging = source_path.parent / "ocr" / "runs" / ".staging"
        assert not tuple(staging.iterdir())
    else:
        assert _invoke(data_root, work_id).stage == "canonicalize"


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


def test_pdf_form_evidence_accepts_equivalent_flate_serialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    source = tmp_path / "source.pdf"
    rewritten = tmp_path / "rewritten.pdf"
    _write_form_pdf(source, compressed_form=False)
    _write_form_pdf(rewritten, compressed_form=True)

    assert source.read_bytes() != rewritten.read_bytes()
    assert resume._validate_pdf_output(source, page_count=1) == (
        resume._validate_pdf_output(rewritten, page_count=1)
    )


def test_pdf_form_evidence_accepts_nonzero_reversed_bbox_coordinates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    source = tmp_path / "source.pdf"
    rewritten = tmp_path / "rewritten.pdf"
    _write_form_pdf(
        source,
        compressed_form=False,
        bbox=(12, 12, 0, 0),
    )
    _write_form_pdf(
        rewritten,
        compressed_form=True,
        bbox=(12, 12, 0, 0),
    )

    assert resume._validate_pdf_output(source, page_count=1) == (
        resume._validate_pdf_output(rewritten, page_count=1)
    )


def test_pdf_form_evidence_normalizes_provider_coordinate_precision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    source = tmp_path / "source.pdf"
    rewritten = tmp_path / "rewritten.pdf"
    _write_form_pdf(
        source,
        compressed_form=False,
        bbox=(0, 0, 827.343, 446.457),
    )
    _write_form_pdf(
        rewritten,
        compressed_form=True,
        bbox=(0, 0, 827.34302, 446.457),
    )

    assert resume._validate_pdf_output(source, page_count=1) == (
        resume._validate_pdf_output(rewritten, page_count=1)
    )


@pytest.mark.parametrize(
    ("source_values", "rewritten_values"),
    [
        ({"bbox": (0, 0, 12, 12)}, {"bbox": (0, 0, 13, 12)}),
        (
            {"matrix": (1, 0, 0, 1, 0, 0)},
            {"matrix": (1, 0, 0, 1, 1, 0)},
        ),
    ],
)
def test_pdf_form_evidence_binds_bbox_and_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_values: dict[str, tuple[int, ...]],
    rewritten_values: dict[str, tuple[int, ...]],
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    source = tmp_path / "source.pdf"
    rewritten = tmp_path / "rewritten.pdf"
    _write_form_pdf(source, compressed_form=False, **source_values)  # type: ignore[arg-type]
    _write_form_pdf(rewritten, compressed_form=True, **rewritten_values)  # type: ignore[arg-type]

    assert resume._validate_pdf_output(source, page_count=1) != (
        resume._validate_pdf_output(rewritten, page_count=1)
    )


def test_pdf_form_rejects_non_version_one_form_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    invalid = tmp_path / "invalid-form.pdf"
    _write_form_pdf(invalid, compressed_form=False, form_type=2)

    with pytest.raises(RuntimeError) as caught:
        resume._validate_pdf_output(invalid, page_count=1)

    assert type(caught.value).__name__ == "_OcrOutputInvalidV1"


def test_pdf_form_accepts_single_flate_array_with_null_decode_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    direct = tmp_path / "direct.pdf"
    array = tmp_path / "array.pdf"
    _write_form_pdf(direct, compressed_form=True)
    _write_form_pdf(
        array,
        compressed_form=True,
        flate_array_length=1,
    )

    assert resume._validate_pdf_output(direct, page_count=1) == (
        resume._validate_pdf_output(array, page_count=1)
    )


def test_pdf_form_rejects_multiple_filter_array(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    invalid = tmp_path / "multiple-filters.pdf"
    _write_form_pdf(
        invalid,
        compressed_form=True,
        flate_array_length=2,
    )

    with pytest.raises(RuntimeError) as caught:
        resume._validate_pdf_output(invalid, page_count=1)

    assert type(caught.value).__name__ == "_OcrOutputInvalidV1"


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
