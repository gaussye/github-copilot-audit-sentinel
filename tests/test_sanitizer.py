from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from copilot_audit.parser import ParsedItem
from copilot_audit.processor import MAX_BLOB_BYTES, process_blob
from copilot_audit.sanitizer import deterministic_event_id, sanitize_item

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 19, tzinfo=UTC)


def test_nested_body_extracts_only_allowlisted_metadata() -> None:
    record = process_blob(
        (FIXTURES / "object.json").read_bytes(),
        "audit/2026/08/synthetic.json.log.gz",
        ingested_at=NOW,
    )[0]

    assert record.Model == "synthetic-model"
    assert record.InteractionType == "chat"
    assert json.loads(record.ToolNames) == ["search"]


def test_sensitive_values_never_leak_from_sanitized_record() -> None:
    record = process_blob(
        (FIXTURES / "object.json").read_bytes(),
        "audit/2026/08/synthetic.json.log.gz",
        ingested_at=NOW,
    )[0]
    serialized = json.dumps(record.to_log(), sort_keys=True)

    for forbidden in (
        "must-not-leak",
        "Bearer synthetic-secret",
        "192.0.2.10",
        "synthetic-device",
        "synthetic-session",
        "print(",
    ):
        assert forbidden not in serialized

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
    }


def test_unparseable_streaming_body_records_status_without_content() -> None:
    item = ParsedItem(
        4,
        {"body": "data: streamed secret content", "action": "copilot.chat"},
        29,
        "parsed",
    )

    record = sanitize_item(item, "synthetic.json.log.gz", NOW)

    assert "body_unparseable" in record.ParseStatus
    assert "streamed secret content" not in json.dumps(record.to_log())


def test_malformed_record_contains_metadata_only() -> None:
    item = ParsedItem(7, None, 123, "invalid_json")

    record = sanitize_item(item, "synthetic.json.log.gz", NOW)

    assert record.EventType == ""
    assert record.UserId == ""
    assert record.PayloadBytes == 123
    assert record.ParseStatus == "invalid_json"


def test_event_id_is_deterministic_and_index_sensitive() -> None:
    first = deterministic_event_id("folder/blob.json.log.gz", 3)

    assert first == deterministic_event_id("folder/blob.json.log.gz", 3)
    assert first != deterministic_event_id("folder/blob.json.log.gz", 4)
    assert first != deterministic_event_id("folder/other.json.log.gz", 3)


def test_epoch_millisecond_timestamp_is_preserved() -> None:
    item = ParsedItem(0, {"@timestamp": 1_787_099_323_000}, 42, "parsed")

    record = sanitize_item(item, "synthetic.json.log.gz", NOW)

    assert record.TimeGenerated == "2026-08-19T00:28:43Z"
    assert record.ParseStatus == "parsed"


def test_oversized_blob_produces_metadata_only_status() -> None:
    records = process_blob(
        b"x" * (MAX_BLOB_BYTES + 1),
        "oversized.json.log.gz",
        ingested_at=NOW,
    )

    assert len(records) == 1
    assert records[0].ParseStatus == "blob_too_large"
    assert records[0].PayloadBytes == MAX_BLOB_BYTES + 1
    assert records[0].EventType == ""
