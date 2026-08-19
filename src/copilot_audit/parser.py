from __future__ import annotations

import gzip
import json
import zlib
from collections.abc import Iterator
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


def _object_items(value: Any, payload_bytes: int) -> Iterator[ParsedItem]:
    if isinstance(value, dict):
        yield ParsedItem(0, value, payload_bytes, "parsed")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            encoded_size = len(
                json.dumps(item, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            )
            if isinstance(item, dict):
                yield ParsedItem(index, item, encoded_size, "parsed")
            else:
                yield ParsedItem(index, None, encoded_size, "invalid_record_type")
        return
    yield ParsedItem(0, None, payload_bytes, "invalid_root_type")


def parse_blob(content: bytes) -> list[ParsedItem]:
    if len(content) > MAX_COMPRESSED_BYTES:
        return [ParsedItem(0, None, len(content), "blob_too_large")]

    payload = content
    if content.startswith(GZIP_MAGIC):
        try:
            with gzip.GzipFile(fileobj=BytesIO(content)) as stream:
                payload = stream.read(MAX_DECOMPRESSED_BYTES + 1)
        except (gzip.BadGzipFile, EOFError, zlib.error):
            return [ParsedItem(0, None, len(content), "invalid_gzip")]
        if len(payload) > MAX_DECOMPRESSED_BYTES:
            return [
                ParsedItem(
                    0,
                    None,
                    len(content),
                    "decompressed_payload_too_large",
                )
            ]

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return [ParsedItem(0, None, len(payload), "invalid_utf8")]

    try:
        root = json.loads(text)
    except json.JSONDecodeError:
        return _parse_json_lines(text)
    return list(_object_items(root, len(payload)))


def _parse_json_lines(text: str) -> list[ParsedItem]:
    items: list[ParsedItem] = []
    for index, line in enumerate(text.splitlines()):
        encoded_size = len(line.encode("utf-8"))
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            items.append(ParsedItem(index, None, encoded_size, "invalid_json"))
            continue
        if not isinstance(value, dict):
            items.append(ParsedItem(index, None, encoded_size, "invalid_record_type"))
            continue
        items.append(ParsedItem(index, value, encoded_size, "parsed"))
    if not items:
        return [ParsedItem(0, None, len(text.encode("utf-8")), "empty_payload")]
    return items
