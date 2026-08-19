from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobClient

from copilot_audit.ingestion import build_client, upload_records
from copilot_audit.processor import MAX_BLOB_BYTES, metadata_failure, process_blob
from copilot_audit.transform import configured_transform

app = func.FunctionApp()
logger = logging.getLogger("copilot_audit")


class AuditProcessingError(RuntimeError):
    """Payload-safe failure propagated to the Functions retry policy."""


class AuditEventValidationError(ValueError):
    """Permanent rejection with a payload-safe reason code."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Audit Event Grid event rejected")


@dataclass(frozen=True, slots=True)
class BlobEventTarget:
    url: str
    blob_name: str


def resolve_blob_event(event: func.EventGridEvent) -> BlobEventTarget:
    if event.event_type != "Microsoft.Storage.BlobCreated":
        raise AuditEventValidationError("unexpected_event_type")

    expected_topic = os.environ["SOURCE_STORAGE_ACCOUNT_RESOURCE_ID"].rstrip("/").lower()
    if not event.topic or event.topic.rstrip("/").lower() != expected_topic:
        raise AuditEventValidationError("unexpected_topic")

    data = event.get_json()
    if not isinstance(data, dict) or not isinstance(data.get("url"), str):
        raise AuditEventValidationError("missing_blob_url")

    url = data["url"]
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise AuditEventValidationError("invalid_blob_url") from error

    account_name = os.environ["SOURCE_STORAGE_ACCOUNT_NAME"].lower()
    container_name = os.environ["SOURCE_CONTAINER_NAME"]
    expected_host = f"{account_name}.blob.core.windows.net"
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != expected_host
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise AuditEventValidationError("unexpected_blob_url")

    decoded_path = unquote(parsed.path)
    path_prefix = f"/{container_name}/"
    if not decoded_path.startswith(path_prefix):
        raise AuditEventValidationError("unexpected_container")
    blob_name = decoded_path[len(path_prefix) :]
    if not blob_name or not blob_name.endswith(".json.log.gz"):
        raise AuditEventValidationError("unexpected_blob_name")

    subject_prefix = f"/blobServices/default/containers/{container_name}/blobs/"
    decoded_subject = unquote(event.subject or "")
    if not decoded_subject.startswith(subject_prefix):
        raise AuditEventValidationError("unexpected_subject")
    if decoded_subject[len(subject_prefix) :] != blob_name:
        raise AuditEventValidationError("subject_url_mismatch")

    return BlobEventTarget(url=url, blob_name=blob_name)


def build_source_blob_client(url: str) -> BlobClient:
    return BlobClient.from_blob_url(url, credential=DefaultAzureCredential())


@app.event_grid_trigger(arg_name="event")
def process_blob_upload(event: func.EventGridEvent) -> None:
    try:
        target = resolve_blob_event(event)
    except AuditEventValidationError as error:
        logger.warning("Audit Event Grid event rejected", extra={"reason": error.reason})
        return

    stage = "download"
    try:
        source_blob_client = build_source_blob_client(target.url)
        properties = source_blob_client.get_blob_properties()
        if properties.size > MAX_BLOB_BYTES:
            records = metadata_failure(
                target.blob_name,
                payload_bytes=properties.size,
                parse_status="blob_too_large",
            )
        else:
            content = source_blob_client.download_blob().readall()
            stage = "parse"
            records = process_blob(
                content,
                target.blob_name,
                transform=configured_transform(),
            )
        stage = "ingestion"
        client = build_client(os.environ["LOGS_INGESTION_ENDPOINT"])
        uploaded = upload_records(
            client,
            os.environ["DCR_IMMUTABLE_ID"],
            os.environ["DCR_STREAM_NAME"],
            (record.to_log() for record in records),
        )
        event_ids = {record.EventId for record in records}
        failed_event_ids = {record.EventId for record in records if record.ParseStatus != "parsed"}
        logger.info(
            "Audit blob processed",
            extra={
                "source_record_count": len(event_ids),
                "uploaded_chunk_count": uploaded,
                "parse_failure_count": len(failed_event_ids),
            },
        )
    except Exception as error:
        logger.error(
            "Audit blob processing failed",
            extra={"error_type": type(error).__name__, "stage": stage},
        )
        raise AuditProcessingError(
            "Audit processing failed; see safe error_type telemetry"
        ) from None
