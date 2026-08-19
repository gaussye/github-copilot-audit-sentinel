from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator, MutableMapping
from typing import Any, Protocol

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.monitor.ingestion import LogsIngestionClient

MAX_BATCH_RECORDS = 500
MAX_BATCH_BYTES = 750_000


class LogsClient(Protocol):
    def upload_batch(
        self,
        rule_id: str,
        stream_name: str,
        logs: list[dict[str, Any]],
    ) -> None: ...


class AzureLogsClient:
    def __init__(self, client: LogsIngestionClient) -> None:
        self._client = client

    def upload_batch(
        self,
        rule_id: str,
        stream_name: str,
        logs: list[dict[str, Any]],
    ) -> None:
        payload: list[MutableMapping[str, Any]] = [dict(record) for record in logs]
        self._client.upload(rule_id=rule_id, stream_name=stream_name, logs=payload)


def batches(
    records: Iterable[dict[str, Any]],
    max_records: int = MAX_BATCH_RECORDS,
    max_bytes: int = MAX_BATCH_BYTES,
) -> Iterator[list[dict[str, Any]]]:
    current: list[dict[str, Any]] = []
    current_bytes = 2
    for record in records:
        record_bytes = len(
            json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
        if record_bytes > max_bytes:
            raise ValueError("A sanitized record exceeds the ingestion batch byte limit")
        if current and (
            len(current) >= max_records or current_bytes + record_bytes + 1 > max_bytes
        ):
            yield current
            current = []
            current_bytes = 2
        current.append(record)
        current_bytes += record_bytes + 1
    if current:
        yield current


def build_client(endpoint: str, *, local_development: bool = False) -> AzureLogsClient:
    credential = (
        DefaultAzureCredential()
        if local_development or os.getenv("AZURE_FUNCTIONS_ENVIRONMENT") == "Development"
        else ManagedIdentityCredential()
    )
    return AzureLogsClient(LogsIngestionClient(endpoint=endpoint, credential=credential))


def upload_records(
    client: LogsClient,
    rule_id: str,
    stream_name: str,
    records: Iterable[dict[str, Any]],
) -> int:
    uploaded = 0
    for batch in batches(records):
        client.upload_batch(rule_id, stream_name, batch)
        uploaded += len(batch)
    return uploaded
