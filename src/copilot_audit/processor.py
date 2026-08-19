from __future__ import annotations

from datetime import datetime

from .parser import MAX_COMPRESSED_BYTES, ParsedItem, parse_blob
from .sanitizer import sanitize_item
from .schema import AuditRecord, utc_now

MAX_BLOB_BYTES = MAX_COMPRESSED_BYTES


def process_blob(
    content: bytes,
    source_blob: str,
    *,
    ingested_at: datetime | None = None,
) -> list[AuditRecord]:
    observed_at = ingested_at or utc_now()
    if len(content) > MAX_BLOB_BYTES:
        return metadata_failure(
            source_blob,
            payload_bytes=len(content),
            parse_status="blob_too_large",
            ingested_at=observed_at,
        )
    return [
        sanitize_item(item, source_blob=source_blob, ingested_at=observed_at)
        for item in parse_blob(content)
    ]


def metadata_failure(
    source_blob: str,
    *,
    payload_bytes: int,
    parse_status: str,
    ingested_at: datetime | None = None,
) -> list[AuditRecord]:
    observed_at = ingested_at or utc_now()
    item = ParsedItem(0, None, payload_bytes, parse_status)
    return [sanitize_item(item, source_blob=source_blob, ingested_at=observed_at)]
