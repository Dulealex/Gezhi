from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

SEARCH_PROJECTION_SCHEMA_VERSION = "gezhi.candidate_search_projection.v1"

SEARCH_PROJECTION_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE registry_search_meta (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        schema_version TEXT NOT NULL CHECK (
            schema_version = 'gezhi.candidate_search_projection.v1'
        ),
        registry_generation INTEGER NOT NULL CHECK (registry_generation >= 0)
    ) STRICT
    """,
    """
    CREATE VIRTUAL TABLE candidate_search_unicode USING fts5(
        candidate_id UNINDEXED,
        statement_text,
        source_terms_text,
        descriptor_text,
        work_title,
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE VIRTUAL TABLE candidate_search_trigram USING fts5(
        candidate_id UNINDEXED,
        statement_text,
        source_terms_text,
        descriptor_text,
        work_title,
        tokenize='trigram case_sensitive 0'
    )
    """,
)

_TECHNICAL_PUNCTUATION = frozenset("+#._/-")


@dataclass(frozen=True, slots=True)
class SearchTextV1:
    normalized_text: str
    unicode61_atoms: tuple[str, ...]
    trigram_atoms: tuple[str, ...]


class SearchQueryInvalidV1(ValueError):
    pass


class SearchQueryTooLargeV1(ValueError):
    pass


class SearchQueryTooComplexV1(ValueError):
    pass


def canonical_json_bytes_v1(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def decode_canonical_json_blob_v1(value: object) -> object:
    if type(value) is not bytes:
        raise ValueError("Registry JSON value is not an immutable byte string")
    try:
        decoded = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Registry JSON value is invalid") from error
    if canonical_json_bytes_v1(decoded) != value:
        raise ValueError("Registry JSON value is not canonical")
    return decoded


def _is_han(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2FA1F
        or 0x30000 <= codepoint <= 0x323AF
    )


def _base_search_text(value: str) -> str:
    normalized = unicodedata.normalize(
        "NFKC",
        value.replace("\r\n", "\n").replace("\r", "\n"),
    ).casefold()
    characters: list[str] = []
    for character in normalized:
        category = unicodedata.category(character)
        if category[0] in {"C", "Z"}:
            characters.append(" ")
        else:
            characters.append(character)
    return " ".join("".join(characters).split())


def _tokenizable_search_text(value: str) -> str:
    characters = [
        character
        if unicodedata.category(character)[0] in {"L", "N"}
        or character in _TECHNICAL_PUNCTUATION
        else " "
        for character in value
    ]
    return " ".join("".join(characters).split())


def _search_runs(value: str) -> tuple[tuple[bool, str], ...]:
    runs: list[tuple[bool, str]] = []
    for token in value.split():
        start = 0
        while start < len(token):
            han = _is_han(token[start])
            end = start + 1
            while end < len(token) and _is_han(token[end]) == han:
                end += 1
            runs.append((han, token[start:end]))
            start = end
    return tuple(runs)


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values), key=lambda item: item.encode("utf-8")))


def _unicode_atoms(value: str) -> tuple[str, ...]:
    atoms: list[str] = []
    for han, run in _search_runs(value):
        if han:
            atoms.extend(run[index : index + 2] for index in range(len(run) - 1))
        elif run:
            atoms.append(run)
    return _ordered_unique(atoms)


def _trigram_atoms(value: str) -> tuple[str, ...]:
    atoms: list[str] = []
    for han, run in _search_runs(value):
        if han:
            atoms.extend(run[index : index + 3] for index in range(len(run) - 2))
        elif len(run) >= 3:
            atoms.append(run)
    return _ordered_unique(atoms)


def _search_text_from_normalized_v1(normalized: str) -> SearchTextV1:
    atom_text = _tokenizable_search_text(normalized)
    searchable_characters = [
        character
        for character in atom_text
        if unicodedata.category(character)[0] in {"L", "N"}
    ]
    if (
        not normalized
        or not searchable_characters
        or (len(searchable_characters) == 1 and _is_han(searchable_characters[0]))
    ):
        raise SearchQueryInvalidV1("Query contains no searchable text")
    unicode_atoms = _unicode_atoms(atom_text)
    trigram_atoms = _trigram_atoms(atom_text)
    if len(unicode_atoms) > 128 or len(trigram_atoms) > 128:
        raise SearchQueryTooComplexV1("Query has too many search atoms")
    if not unicode_atoms and not trigram_atoms:
        raise SearchQueryInvalidV1("Query contains no search atoms")
    return SearchTextV1(normalized, unicode_atoms, trigram_atoms)


def validate_normalized_search_text_v1(value: object) -> SearchTextV1:
    if type(value) is not str or _base_search_text(value) != value:
        raise SearchQueryInvalidV1("SearchText is not canonical")
    return _search_text_from_normalized_v1(value)


def normalize_search_query_v1(raw_query: str) -> SearchTextV1:
    if type(raw_query) is not str:
        raise SearchQueryInvalidV1("Query must be a string")
    if "\x00" in raw_query or any(
        unicodedata.category(character) == "Cs" for character in raw_query
    ):
        raise SearchQueryInvalidV1("Query contains an invalid scalar")
    canonical = unicodedata.normalize(
        "NFC",
        raw_query.replace("\r\n", "\n").replace("\r", "\n"),
    )
    if any(
        unicodedata.category(character) == "Cc" and character not in {"\t", "\n"}
        for character in canonical
    ):
        raise SearchQueryInvalidV1("Query contains an invalid control character")
    canonical = canonical.strip()
    if not canonical:
        raise SearchQueryInvalidV1("Query is empty")
    try:
        byte_length = len(canonical.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise SearchQueryInvalidV1("Query cannot be encoded") from error
    if len(canonical) > 2_000 or byte_length > 8_192:
        raise SearchQueryTooLargeV1("Query exceeds its size limit")
    normalized = _base_search_text(canonical)
    return _search_text_from_normalized_v1(normalized)


def _joined_search_values(values: Iterable[str]) -> str:
    return " ".join(filter(None, (_base_search_text(value) for value in values)))


def _unicode_projection(value: str) -> str:
    projected: list[str] = []
    for han, run in _search_runs(_tokenizable_search_text(value)):
        if not han:
            projected.append(run)
            continue
        seen: set[str] = set()
        for index in range(len(run) - 1):
            window = run[index : index + 2]
            if window not in seen:
                seen.add(window)
                projected.append(window)
    return " ".join(projected)


def search_document_fields_v1(
    candidate: dict[str, object],
    citation: dict[str, object],
    descriptor_snapshots: list[object],
) -> tuple[tuple[str, str, str, str], tuple[str, str, str, str]]:
    payload = cast(dict[str, object], candidate["payload"])
    statement = cast(dict[str, object], payload["statement"])
    statement_text = _base_search_text(cast(str, statement["text"]))
    source_terms_text = _joined_search_values(
        cast(list[str], statement["source_terms"])
    )
    descriptor_values: list[str] = []
    for raw_snapshot in descriptor_snapshots:
        snapshot = cast(dict[str, object], raw_snapshot)
        descriptor_payload = cast(dict[str, object], snapshot["payload"])
        value = cast(dict[str, object], descriptor_payload["value"])
        if descriptor_payload["kind"] == "method":
            descriptor_values.append(cast(str, value["text"]))
        else:
            descriptor_values.append(cast(str, value["label"]))
        descriptor_values.extend(cast(list[str], value["source_terms"]))
    descriptor_text = _joined_search_values(descriptor_values)
    title = citation["title"]
    work_title = "" if title is None else _base_search_text(cast(str, title))
    trigram_fields = (
        statement_text,
        source_terms_text,
        descriptor_text,
        work_title,
    )
    unicode_fields = tuple(_unicode_projection(value) for value in trigram_fields)
    return cast(tuple[str, str, str, str], unicode_fields), trigram_fields


def replace_active_search_document_v1(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
    candidate: dict[str, object],
    citation: dict[str, object],
    descriptor_snapshots: list[object],
) -> None:
    unicode_fields, trigram_fields = search_document_fields_v1(
        candidate,
        citation,
        descriptor_snapshots,
    )
    for table, fields in (
        ("candidate_search_unicode", unicode_fields),
        ("candidate_search_trigram", trigram_fields),
    ):
        connection.execute(
            f"DELETE FROM {table} WHERE candidate_id = ?", (candidate_id,)
        )
        connection.execute(
            f"INSERT INTO {table}(candidate_id, statement_text, source_terms_text, "
            "descriptor_text, work_title) VALUES (?, ?, ?, ?, ?)",
            (candidate_id, *fields),
        )


def remove_search_document_v1(
    connection: sqlite3.Connection,
    *,
    candidate_id: str,
) -> None:
    connection.execute(
        "DELETE FROM candidate_search_unicode WHERE candidate_id = ?",
        (candidate_id,),
    )
    connection.execute(
        "DELETE FROM candidate_search_trigram WHERE candidate_id = ?",
        (candidate_id,),
    )


def bind_search_projection_generation_v1(connection: sqlite3.Connection) -> None:
    connection.execute(
        "UPDATE registry_search_meta "
        "SET registry_generation = ("
        "SELECT generation FROM registry_meta WHERE singleton = 1"
        ") WHERE singleton = 1"
    )


def fts_literal_query_v1(atoms: tuple[str, ...]) -> str:
    return " OR ".join('"' + atom.replace('"', '""') + '"' for atom in atoms)


__all__ = [
    "SEARCH_PROJECTION_SCHEMA_STATEMENTS",
    "SEARCH_PROJECTION_SCHEMA_VERSION",
    "SearchQueryInvalidV1",
    "SearchQueryTooComplexV1",
    "SearchQueryTooLargeV1",
    "SearchTextV1",
    "bind_search_projection_generation_v1",
    "canonical_json_bytes_v1",
    "decode_canonical_json_blob_v1",
    "fts_literal_query_v1",
    "normalize_search_query_v1",
    "remove_search_document_v1",
    "replace_active_search_document_v1",
    "search_document_fields_v1",
    "validate_normalized_search_text_v1",
]
