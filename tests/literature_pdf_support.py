from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def write_text_pdf(path: Path, *page_texts: str) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    for text in page_texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_reference}
                )
            }
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(
            b"BT /F1 12 Tf 72 720 Td ("
            + escaped.encode("ascii")
            + b") Tj ET"
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    destination = BytesIO()
    writer.write(destination)
    payload = destination.getvalue()
    path.write_bytes(payload)
    return payload


def write_blank_pdf(path: Path) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    destination = BytesIO()
    writer.write(destination)
    payload = destination.getvalue()
    path.write_bytes(payload)
    return payload
