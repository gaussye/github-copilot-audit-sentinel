from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from copilot_audit.ingestion import batches
from copilot_audit.normalizer import (
    RAW_CHUNK_MAX_BYTES,
    deterministic_event_id,
    normalize_item,
)
from copilot_audit.parser import ParsedItem
from copilot_audit.processor import MAX_BLOB_BYTES, process_blob
from copilot_audit.transform import (
    RawPayload,
    configured_transform,
    delete_top_level_fields,
    identity_transform,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 19, tzinfo=UTC)


def test_default_transform_is_identity() -> None:
    assert identity_transform(RawPayload("complete", "utf-8")) == RawPayload("complete", "utf-8")


def test_complete_outer_event_is_preserved_exactly_by_default() -> None:
    source = (FIXTURES / "object.json").read_text()

    record = process_blob(
        source.encode(),
        "audit/2026/08/synthetic.json.log.gz",
        ingested_at=NOW,
    )[0]

    assert record.RawEvent == source
    assert record.RawEncoding == "utf-8-json"
    assert record.RawChunkIndex == 0
    assert record.RawChunkCount == 1

    outer = json.loads(record.RawEvent)
    nested_body = json.loads(outer["body"])
    assert outer["headers"]["authorization"] == "Bearer SYNTHETIC-NOT-A-REAL-CREDENTIAL"
    assert outer["headers"]["x-synthetic-header"] == "retained"
    assert outer["ip_address"] == "192.0.2.10"
    assert outer["device_id"] == "synthetic-device"
    assert outer["session_id"] == "synthetic-session"
    assert outer["source_code"] == "print('synthetic source retained')"
    assert outer["future_unknown"]["new_field"] == "synthetic-unknown-value"
    assert nested_body["prompt"] == "synthetic prompt retained"
    assert nested_body["output"] == "synthetic model output retained"
    assert nested_body["tool_calls"][0]["function"]["arguments"]["prompt"] == (
        "synthetic tool argument retained"
    )


def test_normalized_metadata_is_still_available() -> None:
    record = process_blob(
        (FIXTURES / "object.json").read_bytes(),
        "audit/2026/08/synthetic.json.log.gz",
        ingested_at=NOW,
    )[0]

    assert record.Model == "synthetic-model"
    assert record.InteractionType == "chat"
    assert json.loads(record.ToolNames) == ["search"]


def test_unparseable_streaming_body_is_retained() -> None:
    raw = '{"body":"data: synthetic streamed response","action":"copilot.chat"}'
    item = ParsedItem(
        4,
        {"body": "data: synthetic streamed response", "action": "copilot.chat"},
        len(raw.encode()),
        "parsed",
        raw,
        "utf-8-json",
    )

    record = normalize_item(item, "synthetic.json.log.gz", NOW)[0]

    assert "body_unparseable" in record.ParseStatus
    assert record.RawEvent == raw
    assert "synthetic streamed response" in record.RawEvent


def test_malformed_record_retains_exact_raw_content() -> None:
    raw = "not-json synthetic raw content"
    item = ParsedItem(
        7,
        None,
        len(raw.encode()),
        "invalid_json",
        raw,
        "utf-8-text-jsonl-record",
    )

    record = normalize_item(item, "synthetic.json.log.gz", NOW)[0]

    assert record.EventType == ""
    assert record.UserId == ""
    assert record.PayloadBytes == len(raw.encode())
    assert record.ParseStatus == "invalid_json"
    assert record.RawEvent == raw


def test_explicit_transform_can_delete_configured_fields() -> None:
    raw = '{"keep":"visible","authorization":"synthetic-secret"}'
    item = ParsedItem(
        0,
        json.loads(raw),
        len(raw.encode()),
        "parsed",
        raw,
        "utf-8-json",
    )

    record = normalize_item(
        item,
        "synthetic.json.log.gz",
        NOW,
        transform=delete_top_level_fields(["authorization"]),
    )[0]

    assert json.loads(record.RawEvent) == {"keep": "visible"}
    assert record.RawEncoding == "transformed-json:deleted-top-level-fields"


def test_configured_transform_defaults_to_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAW_TRANSFORM_POLICY", raising=False)

    payload = RawPayload('{"authorization":"synthetic-secret"}', "utf-8-json")

    assert configured_transform()(payload) == payload


def test_large_raw_record_is_chunked_without_truncation() -> None:
    raw = json.dumps({"complete": "界" * 200_000}, ensure_ascii=False)

    records = process_blob(raw.encode(), "large.json.log.gz", ingested_at=NOW)

    assert len(records) > 1
    assert "".join(record.RawEvent for record in records) == raw
    assert [record.RawChunkIndex for record in records] == list(range(len(records)))
    assert {record.RawChunkCount for record in records} == {len(records)}
    assert len({record.RawContentHash for record in records}) == 1
    assert len(records[0].RawContentHash) == 64
    assert {record.EventId for record in records} == {
        deterministic_event_id("large.json.log.gz", 0)
    }
    assert all(len(record.RawEvent.encode()) <= RAW_CHUNK_MAX_BYTES for record in records)
    assert sum(len(batch) for batch in batches(record.to_log() for record in records)) == len(
        records
    )


def test_event_id_is_deterministic_and_index_sensitive() -> None:
    first = deterministic_event_id("folder/blob.json.log.gz", 3)

    assert first == deterministic_event_id("folder/blob.json.log.gz", 3)
    assert first != deterministic_event_id("folder/blob.json.log.gz", 4)
    assert first != deterministic_event_id("folder/other.json.log.gz", 3)


def test_epoch_millisecond_timestamp_is_preserved() -> None:
    raw = '{"@timestamp":1787099323000}'
    item = ParsedItem(
        0,
        {"@timestamp": 1_787_099_323_000},
        len(raw),
        "parsed",
        raw,
        "utf-8-json",
    )

    record = normalize_item(item, "synthetic.json.log.gz", NOW)[0]

    assert record.TimeGenerated == "2026-08-19T00:28:43Z"
    assert record.ParseStatus == "parsed"


def test_oversized_blob_has_explicit_non_capture_status() -> None:
    records = process_blob(
        b"x" * (MAX_BLOB_BYTES + 1),
        "oversized.json.log.gz",
        ingested_at=NOW,
    )

    assert len(records) == 1
    assert records[0].ParseStatus == "blob_too_large"
    assert records[0].PayloadBytes == MAX_BLOB_BYTES + 1
    assert records[0].RawEvent == ""
    assert records[0].RawEncoding == "not-captured:blob_too_large"


def test_log_schema_contains_raw_and_normalized_fields() -> None:
    record = process_blob(
        (FIXTURES / "object.json").read_bytes(),
        "synthetic.json.log.gz",
        ingested_at=NOW,
    )[0]

    assert set(record.to_log()) == {
        "TimeGenerated",
        "EventId",
        "GitHubRequestId",
        "UserId",
        "EnterpriseId",
        "EventType",
        "Endpoint",
        "Model",
        "InteractionType",
        "ToolNames",
        "StatusCode",
        "SourceBlob",
        "SourceRecordIndex",
        "PayloadBytes",
        "ParseStatus",
        "IngestedAt",
        "RawEvent",
        "RawEncoding",
        "RawContentHash",
        "RawChunkIndex",
        "RawChunkCount",
    }
