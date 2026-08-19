from __future__ import annotations

from typing import Any

import pytest

from copilot_audit.ingestion import batches, upload_records


class RecordingClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[list[dict[str, Any]]] = []
        self.error = error

    def upload_batch(
        self,
        rule_id: str,
        stream_name: str,
        logs: list[dict[str, Any]],
    ) -> None:
        assert rule_id == "dcr-immutable"
        assert stream_name == "Custom-GitHubCopilotAudit"
        self.calls.append(logs)
        if self.error:
            raise self.error


def test_batches_by_record_count() -> None:
    records = [{"EventId": str(index)} for index in range(5)]

    result = list(batches(records, max_records=2, max_bytes=10_000))

    assert [len(batch) for batch in result] == [2, 2, 1]


def test_batches_by_encoded_byte_size() -> None:
    records = [{"EventId": "x" * 30}, {"EventId": "y" * 30}]

    result = list(batches(records, max_records=10, max_bytes=60))

    assert [len(batch) for batch in result] == [1, 1]


def test_ingestion_error_propagates_for_platform_retry() -> None:
    client = RecordingClient(RuntimeError("synthetic transient failure"))

    with pytest.raises(RuntimeError, match="synthetic transient failure"):
        upload_records(
            client,
            "dcr-immutable",
            "Custom-GitHubCopilotAudit",
            [{"EventId": "one"}],
        )


def test_uploads_each_batch_once() -> None:
    client = RecordingClient()
    records = [{"EventId": str(index)} for index in range(501)]

    uploaded = upload_records(
        client,
        "dcr-immutable",
        "Custom-GitHubCopilotAudit",
        records,
    )

    assert uploaded == 501
    assert [len(call) for call in client.calls] == [500, 1]


def test_single_oversized_record_fails_without_truncation() -> None:
    raw = "complete-synthetic-payload"

    with pytest.raises(ValueError, match="was not truncated"):
        list(
            batches(
                [{"RawEvent": raw}],
                max_records=10,
                max_bytes=10,
            )
        )

    assert raw == "complete-synthetic-payload"
