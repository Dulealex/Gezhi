from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

_EVIDENCE_TEXT = "Deterministic OCR evidence supports the complete Gezhi workflow."


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _write_output_v1(source_pdf: Path, output_root: Path) -> None:
    leaf = output_root / "source" / "ocr"
    (leaf / "images").mkdir(parents=True)
    (leaf / "source.md").write_text(
        f"# Deterministic OCR\n\n{_EVIDENCE_TEXT}\n",
        encoding="utf-8",
        newline="\n",
    )
    (leaf / "source_content_list.json").write_bytes(_json_bytes([]))
    (leaf / "source_content_list_v2.json").write_bytes(
        _json_bytes(
            [
                [
                    {
                        "bbox": [72, 72, 540, 100],
                        "content": {
                            "paragraph_content": [
                                {"content": _EVIDENCE_TEXT, "type": "text"}
                            ]
                        },
                        "type": "paragraph",
                    }
                ]
            ]
        )
    )
    (leaf / "source_middle.json").write_bytes(
        _json_bytes(
            {
                "_backend": "pipeline",
                "_version_name": "3.4.4",
                "pdf_info": [
                    {
                        "discarded_blocks": [],
                        "page_idx": 0,
                        "page_size": [612, 792],
                        "para_blocks": [],
                    }
                ],
            }
        )
    )
    (leaf / "source_model.json").write_bytes(
        _json_bytes(
            [
                {
                    "layout_dets": [],
                    "page_info": {"height": 792, "page_no": 0, "width": 612},
                }
            ]
        )
    )
    for name in ("source_layout.pdf", "source_origin.pdf", "source_span.pdf"):
        shutil.copyfile(source_pdf, leaf / name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", dest="source_pdf", type=Path, required=True)
    parser.add_argument("-o", dest="output_root", type=Path, required=True)
    parser.add_argument("-b", dest="backend", required=True)
    parser.add_argument("-m", dest="method", required=True)
    parser.add_argument("-l", dest="language", required=True)
    arguments = parser.parse_args()
    if (arguments.backend, arguments.method, arguments.language) != (
        "pipeline",
        "ocr",
        "ch",
    ):
        parser.error("the OCR invocation profile differs from the fixture contract")
    marker = os.environ.get("T25_OCR_DOUBLE_MARKER")
    if marker:
        with Path(marker).open("ab", buffering=0) as target:
            target.write(b"invoked\n")
    scenario = os.environ.get("T25_OCR_DOUBLE_SCENARIO", "succeeded")
    if scenario == "invalid-output":
        arguments.output_root.mkdir(parents=True)
        sys.stdout.buffer.write(b'{"fixture":"gezhi.ocr.v1","status":"invalid"}\n')
        return
    if scenario != "succeeded":
        parser.error("the OCR fixture scenario is invalid")
    _write_output_v1(arguments.source_pdf, arguments.output_root)
    sys.stdout.buffer.write(b'{"fixture":"gezhi.ocr.v1","status":"succeeded"}\n')


if __name__ == "__main__":
    main()
