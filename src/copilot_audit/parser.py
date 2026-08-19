from __future__ import annotations

import gzip
import json
import zlib
from base64 import b64encode
from dataclasses import dataclass
from io import BytesIO
from typing import Any

GZIP_MAGIC = b"\x1f\x8b"
MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ParsedItem:
    index: int
    value: dict[str, Any] | None
    payload_bytes: int
    parse_status: str
    raw_content: str
    raw_encoding: str


def _array_items(source_text: str, encoding_prefix: str) -> list[ParsedItem]:
    decoder = json.JSONDecoder()
    cursor = source_text.index("[") + 1
    items: list[ParsedItem] = []
    while True:
        while cursor < len(source_text) and source_text[cursor].isspace():
            cursor += 1
        if cursor >= len(source_text) or source_text[cursor] == "]":
            return items

        start = cursor
        value, cursor = decoder.raw_decode(source_text, cursor)
        raw_content = source_text[start:cursor]
        items.append(
            ParsedItem(
                len(items),
                value if isinstance(value, dict) else None,
                len(raw_content.encode()),
                "parsed" if isinstance(value, dict) else "invalid_record_type",
                raw_content,
                f"{encoding_prefix}utf-8-json-array-item",
            )
        )
        while cursor < len(source_text) and source_text[cursor].isspace():
            cursor += 1
        if cursor < len(source_text) and source_text[cursor] == ",":
            cursor += 1
            continue
        if cursor < len(source_text) and source_text[cursor] == "]":
            return items
        raise json.JSONDecodeError("Expected array delimiter", source_text, cursor)


def parse_blob(content: bytes) -> list[ParsedItem]:
    if len(content) > MAX_COMPRESSED_BYTES:
        return [
            ParsedItem(
                0,
                None,
                len(content),
                "blob_too_large",
                "",
                "not-captured:blob_too_large",
            )
        ]

    payload = content
    encoding_prefix = ""
    if content.startswith(GZIP_MAGIC):
        encoding_prefix = "gzip+"
        try:
            with gzip.GzipFile(fileobj=BytesIO(content)) as stream:
                payload = stream.read(MAX_DECOMPRESSED_BYTES + 1)
        except (gzip.BadGzipFile, EOFError, zlib.error):
            return [
                ParsedItem(
                    0,
                    None,
                    len(content),
                    "invalid_gzip",
                    b64encode(content).decode("ascii"),
                    "base64-invalid-gzip",
                )
            ]
        if len(payload) > MAX_DECOMPRESSED_BYTES:
            return [
                ParsedItem(
                    0,
                    None,
                    len(content),
                    "decompressed_payload_too_large",
                    "",
                    "not-captured:decompressed_payload_too_large",
                )
            ]

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return [
            ParsedItem(
                0,
                None,
                len(payload),
                "invalid_utf8",
                b64encode(payload).decode("ascii"),
                f"{encoding_prefix}base64",
            )
        ]

    try:
        root = json.loads(text)
    except json.JSONDecodeError:
        return _parse_json_lines(text, encoding_prefix)
    if isinstance(root, dict):
        return [
            ParsedItem(
                0,
                root,
                len(payload),
                "parsed",
                text,
                f"{encoding_prefix}utf-8-json",
            )
        ]
    if isinstance(root, list):
        return _array_items(text, encoding_prefix)
    return [
        ParsedItem(
            0,
            None,
            len(payload),
            "invalid_root_type",
            text,
            f"{encoding_prefix}utf-8-json",
        )
    ]


def _parse_json_lines(text: str, encoding_prefix: str) -> list[ParsedItem]:
    items: list[ParsedItem] = []
    for index, line in enumerate(text.splitlines()):
        encoded_size = len(line.encode("utf-8"))
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            items.append(
                ParsedItem(
                    index,
                    None,
                    encoded_size,
                    "invalid_json",
                    line,
                    f"{encoding_prefix}utf-8-text-jsonl-record",
                )
            )
            continue
        if not isinstance(value, dict):
            items.append(
                ParsedItem(
                    index,
                    None,
                    encoded_size,
                    "invalid_record_type",
                    line,
                    f"{encoding_prefix}utf-8-jsonl-record",
                )
            )
            continue
        items.append(
            ParsedItem(
                index,
                value,
                encoded_size,
                "parsed",
                line,
                f"{encoding_prefix}utf-8-jsonl-record",
            )
        )
    if not items:
        return [
            ParsedItem(
                0,
                None,
                len(text.encode()),
                "empty_payload",
                text,
                f"{encoding_prefix}utf-8-text",
            )
        ]
    return items
