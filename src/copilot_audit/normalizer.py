from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from .parser import ParsedItem
from .schema import AuditRecord, azure_timestamp
from .transform import RawPayload, RawTransform, apply_transform, identity_transform

_MAX_TEXT = 512
_MAX_TOOL_NAMES = 50
_MISSING = object()
# Keeps even worst-case JSON string escaping comfortably below the 750 KB batch cap.
RAW_CHUNK_MAX_BYTES = 64_000


def _lookup(event: dict[str, Any], paths: Iterable[tuple[str, ...]]) -> Any:
    for path in paths:
        current: Any = event
        for part in path:
            if not isinstance(current, dict) or part not in current:
                current = _MISSING
                break
            current = current[part]
        if current is not _MISSING and current is not None:
            return current
    return None


def _safe_text(value: Any, maximum: int = _MAX_TEXT) -> str:
    if isinstance(value, str | int | float | bool):
        return str(value)[:maximum]
    return ""


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _parse_time(value: Any, fallback: datetime) -> tuple[str, bool]:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return azure_timestamp(parsed), True
        except ValueError:
            pass
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            seconds = value / 1000 if abs(value) >= 100_000_000_000 else value
            return azure_timestamp(datetime.fromtimestamp(seconds, tz=UTC)), True
        except (OverflowError, OSError, ValueError):
            pass
    return azure_timestamp(fallback), False


def _parse_body(event: dict[str, Any]) -> tuple[dict[str, Any], str]:
    body = event.get("body")
    if isinstance(body, dict):
        return body, "parsed"
    if isinstance(body, str):
        try:
            nested = json.loads(body)
        except json.JSONDecodeError:
            return {}, "body_unparseable"
        if isinstance(nested, dict):
            return nested, "parsed"
        return {}, "body_invalid_type"
    if body is None:
        return {}, "parsed"
    return {}, "body_invalid_type"


def _tool_names(event: dict[str, Any], body: dict[str, Any]) -> list[str]:
    candidates = (
        _lookup(body, (("tool_names",), ("tools",), ("tool_calls",))),
        _lookup(event, (("tool_names",), ("tools",), ("tool_calls",))),
    )
    names: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, list):
            continue
        for item in candidate:
            value: Any = item
            if isinstance(item, dict):
                value = _lookup(item, (("name",), ("function", "name"), ("tool_name",)))
            name = _safe_text(value, 128)
            if name and name not in names:
                names.append(name)
            if len(names) >= _MAX_TOOL_NAMES:
                return names
    return names


def deterministic_event_id(source_blob: str, source_index: int) -> str:
    material = f"{source_blob}\n{source_index}".encode()
    return hashlib.sha256(material).hexdigest()


def _chunks(value: str, maximum_bytes: int = RAW_CHUNK_MAX_BYTES) -> list[str]:
    encoded = value.encode()
    if len(encoded) <= maximum_bytes:
        return [value]
    chunks: list[str] = []
    offset = 0
    while offset < len(encoded):
        end = min(offset + maximum_bytes, len(encoded))
        while end > offset:
            try:
                chunks.append(encoded[offset:end].decode())
                break
            except UnicodeDecodeError:
                end -= 1
        if end == offset:
            raise ValueError("Unable to split raw payload on a UTF-8 boundary")
        offset = end
    return chunks


def normalize_item(
    item: ParsedItem,
    source_blob: str,
    ingested_at: datetime,
    *,
    transform: RawTransform = identity_transform,
) -> list[AuditRecord]:
    event = item.value or {}
    body, body_status = _parse_body(event)
    timestamp, timestamp_valid = _parse_time(
        _lookup(event, (("@timestamp",), ("created_at",), ("timestamp",))),
        ingested_at,
    )

    statuses = [item.parse_status]
    if item.value is not None and body_status != "parsed":
        statuses.append(body_status)
    if item.value is not None and not timestamp_valid:
        statuses.append("timestamp_missing_or_invalid")

    transformed = apply_transform(
        RawPayload(item.raw_content, item.raw_encoding),
        transform,
    )
    chunks = _chunks(transformed.content)
    content_hash = hashlib.sha256(
        f"{transformed.encoding}\0{transformed.content}".encode()
    ).hexdigest()
    tools = _tool_names(event, body)
    event_id = deterministic_event_id(source_blob, item.index)
    records: list[AuditRecord] = []
    for chunk_index, chunk in enumerate(chunks):
        records.append(
            AuditRecord(
                TimeGenerated=timestamp,
                EventId=event_id,
                GitHubRequestId=_safe_text(
                    _lookup(
                        event,
                        (
                            ("github_request_id",),
                            ("request_id",),
                            ("request", "id"),
                            ("x-github-request-id",),
                        ),
                    )
                ),
                UserId=_safe_text(
                    _lookup(
                        event,
                        (("user_id",), ("actor_id",), ("actor", "id"), ("user", "id")),
                    )
                ),
                EnterpriseId=_safe_text(_lookup(event, (("enterprise_id",), ("enterprise", "id")))),
                EventType=_safe_text(_lookup(event, (("event_type",), ("action",), ("type",)))),
                Endpoint=_safe_text(
                    _lookup(
                        event,
                        (("endpoint",), ("request", "endpoint"), ("request", "path")),
                    )
                    or _lookup(body, (("endpoint",),))
                ),
                Model=_safe_text(
                    _lookup(event, (("model",), ("model_name",)))
                    or _lookup(body, (("model",), ("model_name",)))
                ),
                InteractionType=_safe_text(
                    _lookup(event, (("interaction_type",), ("interaction", "type")))
                    or _lookup(body, (("interaction_type",),))
                ),
                ToolNames=json.dumps(tools, separators=(",", ":")),
                StatusCode=_safe_int(
                    _lookup(
                        event,
                        (
                            ("status_code",),
                            ("response", "status_code"),
                            ("request", "status_code"),
                        ),
                    )
                ),
                SourceBlob=source_blob[:1024],
                SourceRecordIndex=item.index,
                PayloadBytes=item.payload_bytes,
                ParseStatus=";".join(statuses),
                IngestedAt=azure_timestamp(ingested_at),
                RawEvent=chunk,
                RawEncoding=transformed.encoding,
                RawContentHash=content_hash,
                RawChunkIndex=chunk_index,
                RawChunkCount=len(chunks),
            )
        )
    return records
