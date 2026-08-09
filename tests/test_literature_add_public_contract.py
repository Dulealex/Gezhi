from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest
from launcher_support import SOURCE_ROOT, launcher_commands, run_launcher


@pytest.fixture
def add_workspace() -> Iterator[tuple[Path, Path]]:
    container = Path(r"E:\Gezhi\data")
    container.mkdir(parents=True, exist_ok=True)
    while True:
        base = container / ("t" + uuid.uuid4().hex[:7])
        try:
            base.mkdir()
        except FileExistsError:
            continue
        break
    data_root = base / "lit"
    data_root.mkdir()
    pdf_path = base / "paper.pdf"
    try:
        yield data_root, pdf_path
    finally:
        resolved_base = base.resolve(strict=True)
        assert resolved_base.parent == container.resolve(strict=True)
        assert resolved_base.name.startswith("t") and len(resolved_base.name) == 8
        shutil.rmtree(resolved_base)


def _canonical_json_bytes(value: object) -> bytes:
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


def _run_add(
    data_root: Path,
    pdf_path: Path | str,
    *options: str,
    json_output: bool = True,
    launcher_index: int = 1,
) -> subprocess.CompletedProcess[bytes]:
    arguments = (
        "--literature-data-root",
        str(data_root),
        "literature",
        "add",
        str(pdf_path),
        *options,
        *(("--json",) if json_output else ()),
    )
    return run_launcher(launcher_commands(arguments)[launcher_index])


def _json_result(
    completed: subprocess.CompletedProcess[bytes],
) -> dict[str, object]:
    document = json.loads(completed.stdout)
    assert document["outcome"] == "succeeded"
    assert document["diagnostics"] == []
    return document["result"]


@pytest.mark.parametrize("launcher_index", [0, 1])
def test_public_add_commits_pdf_manifest_active_source_and_catalog(
    add_workspace: tuple[Path, Path],
    launcher_index: int,
) -> None:
    data_root, pdf_path = add_workspace
    pdf_bytes = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
    pdf_path.write_bytes(pdf_bytes)
    arguments = (
        "--literature-data-root",
        str(data_root),
        "literature",
        "add",
        str(pdf_path),
        "--doi",
        "10.1234/Example",
        "--citation",
        "  Example citation  ",
        "--json",
    )
    command = launcher_commands(arguments)[launcher_index]

    completed = run_launcher(command)

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stderr == b""
    assert completed.stdout.endswith(b"\n")
    envelope = json.loads(completed.stdout)
    assert envelope["command"] == "literature.add"
    assert envelope["outcome"] == "succeeded"
    assert envelope["diagnostics"] == []
    result = envelope["result"]
    assert result["schema_version"] == "gezhi.literature_add_result.v1"
    assert result["disposition"] == "created_work"
    assert result["active_source_changed"] is True

    source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    assert result["source_sha256"] == source_sha256
    assert result["source_id"] == "src_" + source_sha256[:24]
    work_dir = data_root / "works" / result["work_id"]
    source_dir = work_dir / "sources" / result["source_id"]
    assert (source_dir / "original.pdf").read_bytes() == pdf_bytes

    source_document = json.loads((source_dir / "source.json").read_bytes())
    assert source_document == {
        "byte_length": len(pdf_bytes),
        "media_type": "application/pdf",
        "schema_version": "gezhi.literature_source.v1",
        "source_id": result["source_id"],
        "source_sha256": source_sha256,
        "work_id": result["work_id"],
    }
    source_bytes = _canonical_json_bytes(source_document)
    assert (source_dir / "source.json").read_bytes() == source_bytes

    manifest_bytes = (source_dir / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    assert manifest == {
        "assets": [
            {
                "byte_length": len(pdf_bytes),
                "media_type": "application/pdf",
                "path": "original.pdf",
                "sha256": source_sha256,
            },
            {
                "byte_length": len(source_bytes),
                "media_type": "application/json",
                "path": "source.json",
                "schema_version": "gezhi.literature_source.v1",
                "sha256": hashlib.sha256(source_bytes).hexdigest(),
            },
        ],
        "schema_version": "gezhi.literature_source_manifest.v1",
        "source_id": result["source_id"],
        "source_sha256": source_sha256,
        "work_id": result["work_id"],
    }
    assert manifest_bytes == _canonical_json_bytes(manifest)

    active = json.loads((work_dir / "active_source.json").read_bytes())
    assert active == {
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "schema_version": "gezhi.literature_active_source.v1",
        "source_id": result["source_id"],
        "source_sha256": source_sha256,
        "work_id": result["work_id"],
    }

    with closing(sqlite3.connect(data_root / "catalog.sqlite3")) as database:
        source_row = database.execute(
            "SELECT source_id, source_sha256, work_id, byte_length, "
            "manifest_sha256 FROM sources"
        ).fetchone()
        work_row = database.execute(
            "SELECT work_id, active_source_id FROM works"
        ).fetchone()
        alias_rows = database.execute(
            "SELECT alias_kind, alias_value FROM work_aliases "
            "ORDER BY alias_kind, alias_value"
        ).fetchall()
    assert source_row == (
        result["source_id"],
        source_sha256,
        result["work_id"],
        len(pdf_bytes),
        hashlib.sha256(manifest_bytes).hexdigest(),
    )
    assert work_row == (result["work_id"], result["source_id"])
    assert alias_rows == [
        ("citation", "Example citation"),
        ("doi", "10.1234/Example"),
    ]


def test_duplicate_add_is_idempotent_and_does_not_copy_authority(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = add_workspace
    pdf_path.write_bytes(b"%PDF-1.7\nduplicate\n")

    first = _run_add(data_root, pdf_path)
    first_result = _json_result(first)
    source_path = (
        data_root
        / "works"
        / str(first_result["work_id"])
        / "sources"
        / str(first_result["source_id"])
        / "original.pdf"
    )
    original_identity = source_path.stat().st_ino
    original_manifest = source_path.with_name("manifest.json").read_bytes()

    second = _run_add(data_root, pdf_path)
    second_result = _json_result(second)

    assert second_result == {
        **first_result,
        "active_source_changed": False,
        "disposition": "reused_source",
    }
    assert source_path.stat().st_ino == original_identity
    assert source_path.with_name("manifest.json").read_bytes() == original_manifest
    official_sources = [
        entry
        for entry in source_path.parent.parent.iterdir()
        if entry.name != ".staging"
    ]
    assert official_sources == [source_path.parent]
    assert not tuple((data_root / "works" / ".staging").iterdir())


def test_explicit_work_adds_a_source_and_reactivates_an_old_source(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, first_pdf = add_workspace
    first_pdf.write_bytes(b"%PDF-1.7\nversion one\n")
    first = _json_result(_run_add(data_root, first_pdf))
    second_pdf = first_pdf.with_name("paper2.pdf")
    second_pdf.write_bytes(b"%PDF-1.7\nversion two\n")

    second = _json_result(
        _run_add(
            data_root,
            second_pdf,
            "--work-id",
            str(first["work_id"]),
        )
    )
    assert second["work_id"] == first["work_id"]
    assert second["disposition"] == "added_source"
    assert second["active_source_changed"] is True

    reactivated = _json_result(
        _run_add(
            data_root,
            first_pdf,
            "--work-id",
            str(first["work_id"]),
        )
    )
    assert reactivated["source_id"] == first["source_id"]
    assert reactivated["disposition"] == "reused_source"
    assert reactivated["active_source_changed"] is True
    active = json.loads(
        (
            data_root
            / "works"
            / str(first["work_id"])
            / "active_source.json"
        ).read_bytes()
    )
    assert active["source_id"] == first["source_id"]
    source_dirs = [
        item
        for item in (
            data_root / "works" / str(first["work_id"]) / "sources"
        ).iterdir()
        if item.name != ".staging"
    ]
    assert {item.name for item in source_dirs} == {
        first["source_id"],
        second["source_id"],
    }


def test_exact_doi_resolves_a_new_source_to_the_existing_work(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, first_pdf = add_workspace
    first_pdf.write_bytes(b"%PDF-1.7\ndoi version one\n")
    first = _json_result(
        _run_add(data_root, first_pdf, "--doi", "10.1000/Exact")
    )
    second_pdf = first_pdf.with_name("paper2.pdf")
    second_pdf.write_bytes(b"%PDF-1.7\ndoi version two\n")

    second = _json_result(
        _run_add(data_root, second_pdf, "--doi", "10.1000/Exact")
    )

    assert second["work_id"] == first["work_id"]
    assert second["disposition"] == "added_source"


def test_explicit_work_rejects_a_source_owned_by_another_work(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, first_pdf = add_workspace
    first_pdf.write_bytes(b"%PDF-1.7\nfirst work\n")
    first = _json_result(_run_add(data_root, first_pdf))
    second_pdf = first_pdf.with_name("paper2.pdf")
    second_pdf.write_bytes(b"%PDF-1.7\nsecond work\n")
    second = _json_result(_run_add(data_root, second_pdf))

    conflict = _run_add(
        data_root,
        first_pdf,
        "--work-id",
        str(second["work_id"]),
    )
    document = json.loads(conflict.stdout)

    assert first["work_id"] != second["work_id"]
    assert conflict.returncode == 2
    assert document == {
        "command": "literature.add",
        "diagnostics": [
            {"code": "literature.add.identity_conflict.v1", "context": {}}
        ],
        "outcome": "blocked",
        "result": None,
        "schema_version": "gezhi.cli_result.v1",
    }


def test_disagreeing_strong_aliases_require_identity_review(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, first_pdf = add_workspace
    first_pdf.write_bytes(b"%PDF-1.7\nDOI owner\n")
    _json_result(_run_add(data_root, first_pdf, "--doi", "10.1000/Owner"))
    second_pdf = first_pdf.with_name("paper2.pdf")
    second_pdf.write_bytes(b"%PDF-1.7\narXiv owner\n")
    _json_result(_run_add(data_root, second_pdf, "--arxiv-id", "2401.00001"))
    third_pdf = first_pdf.with_name("paper3.pdf")
    third_pdf.write_bytes(b"%PDF-1.7\nambiguous\n")

    blocked = _run_add(
        data_root,
        third_pdf,
        "--doi",
        "10.1000/Owner",
        "--arxiv-id",
        "2401.00001",
    )

    assert blocked.returncode == 2
    assert json.loads(blocked.stdout)["diagnostics"] == [
        {
            "code": "literature.add.identity_review_required.v1",
            "context": {},
        }
    ]


def test_weak_citation_never_auto_merges_a_new_source(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, first_pdf = add_workspace
    first_pdf.write_bytes(b"%PDF-1.7\nweak one\n")
    _json_result(
        _run_add(data_root, first_pdf, "--citation", "Same citation")
    )
    second_pdf = first_pdf.with_name("paper2.pdf")
    second_pdf.write_bytes(b"%PDF-1.7\nweak two\n")

    blocked = _run_add(
        data_root,
        second_pdf,
        "--citation",
        "Same citation",
    )

    assert blocked.returncode == 2
    assert json.loads(blocked.stdout)["diagnostics"] == [
        {
            "code": "literature.add.identity_review_required.v1",
            "context": {},
        }
    ]


@pytest.mark.parametrize(
    ("pdf_path", "options", "field"),
    [
        (r"relative\paper.pdf", (), "pdf_path"),
        (r"\\wsl.localhost\Ubuntu\paper.pdf", (), "pdf_path"),
        (r"E:\paper.pdf:stream", (), "pdf_path"),
        (None, ("--work-id", "bad"), "work_id"),
        (None, ("--doi", "doi:10.1000/x"), "doi"),
        (None, ("--arxiv-id", "2400.00001"), "arxiv_id"),
        (None, ("--citation", ""), "citation"),
    ],
)
def test_invalid_raw_input_is_blocked_before_any_official_work(
    add_workspace: tuple[Path, Path],
    pdf_path: str | None,
    options: tuple[str, ...],
    field: str,
) -> None:
    data_root, valid_pdf = add_workspace
    valid_pdf.write_bytes(b"%PDF-1.7\nvalid\n")

    completed = _run_add(data_root, pdf_path or valid_pdf, *options)

    assert completed.returncode == 2
    assert completed.stderr == b""
    assert json.loads(completed.stdout) == {
        "command": "literature.add",
        "diagnostics": [
            {
                "code": "literature.add.input_invalid.v1",
                "context": {"field": field},
            }
        ],
        "outcome": "blocked",
        "result": None,
        "schema_version": "gezhi.cli_result.v1",
    }
    works = data_root / "works"
    assert not works.exists() or not [
        entry for entry in works.iterdir() if entry.name != ".staging"
    ]


@pytest.mark.parametrize("payload", [b"", b"not a pdf", b"%PDF"])
def test_invalid_pdf_content_has_no_visible_success(
    add_workspace: tuple[Path, Path],
    payload: bytes,
) -> None:
    data_root, pdf_path = add_workspace
    pdf_path.write_bytes(payload)

    completed = _run_add(data_root, pdf_path)

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["diagnostics"] == [
        {
            "code": "literature.add.input_invalid.v1",
            "context": {"field": "pdf_content"},
        }
    ]
    works = data_root / "works"
    assert not [entry for entry in works.iterdir() if entry.name != ".staging"]
    assert not (data_root / "catalog.sqlite3").exists()


def test_missing_or_directory_pdf_is_pdf_unavailable(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = add_workspace

    for source in (pdf_path, pdf_path.parent):
        completed = _run_add(data_root, source)
        assert completed.returncode == 2
        assert json.loads(completed.stdout)["diagnostics"] == [
            {
                "code": "literature.add.pdf_unavailable.v1",
                "context": {},
            }
        ]


def test_pdf_reparse_point_is_never_followed(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, target = add_workspace
    target.write_bytes(b"%PDF-1.7\ntarget\n")
    link = target.with_name("link.pdf")
    try:
        os.symlink(target, link)
    except OSError as error:
        pytest.skip(f"Windows symlink creation unavailable: {error.winerror}")

    completed = _run_add(data_root, link)

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["diagnostics"] == [
        {"code": "literature.add.pdf_unavailable.v1", "context": {}}
    ]


def test_missing_explicit_work_is_blocked_without_official_source(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = add_workspace
    pdf_path.write_bytes(b"%PDF-1.7\nmissing work\n")
    missing = "wrk_123e4567-e89b-42d3-a456-426614174000"

    completed = _run_add(data_root, pdf_path, "--work-id", missing)

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["diagnostics"] == [
        {"code": "literature.add.work_not_found.v1", "context": {}}
    ]
    assert not [
        entry
        for entry in (data_root / "works").iterdir()
        if entry.name != ".staging"
    ]


def test_data_root_gates_precede_raw_domain_validation(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = add_workspace
    missing_root = data_root.with_name("gone")
    arguments = (
        "--literature-data-root",
        str(missing_root),
        "literature",
        "add",
        str(pdf_path),
        "--doi",
        "bad",
        "--json",
    )

    completed = run_launcher(launcher_commands(arguments)[1])

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["diagnostics"] == [
        {"code": "literature.add.data_root_unavailable.v1", "context": {}}
    ]


def test_configuration_gate_precedes_data_root_and_input_gates(
    add_workspace: tuple[Path, Path],
) -> None:
    _data_root, pdf_path = add_workspace
    arguments = (
        "--literature-data-root=",
        "literature",
        "add",
        str(pdf_path),
        "--doi",
        "bad",
        "--json",
    )

    completed = run_launcher(launcher_commands(arguments)[1])

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["diagnostics"] == [
        {"code": "literature.add.configuration_invalid.v1", "context": {}}
    ]


def test_valid_pdf_magic_does_not_depend_on_extension_or_page_parsing(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = add_workspace
    unusual = pdf_path.with_suffix(".bin")
    unusual.write_bytes(b"%PDF-this is intentionally not page parsed")

    completed = _run_add(data_root, unusual)

    assert completed.returncode == 0
    assert _json_result(completed)["disposition"] == "created_work"


def test_duplicate_can_append_alias_revision_without_rewriting_source(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = add_workspace
    pdf_path.write_bytes(b"%PDF-1.7\nalias revision\n")
    first = _json_result(_run_add(data_root, pdf_path))
    work_dir = data_root / "works" / str(first["work_id"])
    original = (
        work_dir / "sources" / str(first["source_id"]) / "original.pdf"
    )
    original_identity = original.stat().st_ino

    second = _json_result(
        _run_add(
            data_root,
            pdf_path,
            "--doi",
            "10.1000/Appended",
            "--citation",
            "Appended citation",
        )
    )
    third = _json_result(
        _run_add(
            data_root,
            pdf_path,
            "--doi",
            "10.1000/Appended",
            "--citation",
            "Appended citation",
        )
    )

    assert second["disposition"] == third["disposition"] == "reused_source"
    assert second["active_source_changed"] is False
    assert original.stat().st_ino == original_identity
    revisions = tuple((work_dir / "identity" / "revisions").iterdir())
    assert len(revisions) == 2
    with closing(sqlite3.connect(data_root / "catalog.sqlite3")) as database:
        assert database.execute(
            "SELECT alias_kind, alias_value FROM work_aliases "
            "ORDER BY alias_kind, alias_value"
        ).fetchall() == [
            ("citation", "Appended citation"),
            ("doi", "10.1000/Appended"),
        ]


def test_catalog_is_rebuilt_from_authoritative_assets_when_corrupted(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = add_workspace
    pdf_path.write_bytes(b"%PDF-1.7\nrebuild catalog\n")
    first = _json_result(_run_add(data_root, pdf_path, "--doi", "10.1000/Rebuild"))
    (data_root / "catalog.sqlite3").write_bytes(b"not sqlite")

    retried = _run_add(data_root, pdf_path, "--doi", "10.1000/Rebuild")

    assert retried.returncode == 0
    result = _json_result(retried)
    assert result["work_id"] == first["work_id"]
    assert result["disposition"] == "reused_source"
    with closing(sqlite3.connect(data_root / "catalog.sqlite3")) as database:
        assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert database.execute("SELECT count(*) FROM works").fetchone() == (1,)
        assert database.execute("SELECT count(*) FROM sources").fetchone() == (1,)


def test_human_mode_uses_the_same_committed_result_without_ansi_or_cr(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = add_workspace
    payload = b"%PDF-1.7\nhuman\n"
    pdf_path.write_bytes(payload)

    completed = _run_add(data_root, pdf_path, json_output=False)

    assert completed.returncode == 0
    assert completed.stderr == b""
    assert b"\x1b" not in completed.stdout
    assert b"\r" not in completed.stdout
    lines = completed.stdout.decode().splitlines()
    assert lines[0:4] == [
        "Literature add：完成",
        "Active Source 已切换：是",
        "处理结果：created_work",
        "Schema：gezhi.literature_add_result.v1",
    ]
    assert lines[4] == "Source ID：src_" + hashlib.sha256(payload).hexdigest()[:24]
    assert lines[5] == "Source SHA-256：" + hashlib.sha256(payload).hexdigest()
    assert lines[6].startswith("Work ID：wrk_")
    assert lines[7] == "下一步：运行 gezhi literature resume " + lines[6][len("Work ID：") :]
    assert completed.stdout.endswith(b"\n")


def test_add_does_not_import_ocr_codex_knowledge_or_pdf_parser(
    add_workspace: tuple[Path, Path],
) -> None:
    data_root, pdf_path = add_workspace
    pdf_path.write_bytes(b"%PDF-1.7\nno unrelated runtime\n")
    site_root = pdf_path.parent / "site"
    site_root.mkdir()
    marker = site_root / "forbidden.txt"
    (site_root / "sitecustomize.py").write_text(
        "import importlib.abc\n"
        "import pathlib\n"
        f"marker = pathlib.Path({str(marker)!r})\n"
        "blocked = {'gezhi._doctor_runtime', 'gezhi._knowledge_commands', 'pypdf'}\n"
        "class Guard(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname in blocked:\n"
        "            marker.write_text(fullname, encoding='utf-8')\n"
        "            raise RuntimeError('forbidden import: ' + fullname)\n"
        "        return None\n"
        "import sys\n"
        "sys.meta_path.insert(0, Guard())\n",
        encoding="utf-8",
    )
    arguments = (
        "--literature-data-root",
        str(data_root),
        "literature",
        "add",
        str(pdf_path),
        "--json",
    )

    completed = run_launcher(
        launcher_commands(arguments)[1],
        pythonpath_roots=(site_root, SOURCE_ROOT),
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert not marker.exists()
