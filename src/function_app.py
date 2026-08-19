from __future__ import annotations

import logging
import os

import azure.functions as func
import azurefunctions.extensions.bindings.blob as blob

from copilot_audit.ingestion import build_client, upload_records
from copilot_audit.processor import MAX_BLOB_BYTES, metadata_failure, process_blob
from copilot_audit.transform import configured_transform

app = func.FunctionApp()
logger = logging.getLogger("copilot_audit")


class AuditProcessingError(RuntimeError):
    """Payload-safe failure propagated to the Functions retry policy."""


@app.blob_trigger(
    arg_name="source_blob_client",
    path="github-copilot-audit-log/{name}.json.log.gz",
    connection="SourceStorage",
    source=func.BlobSource.EVENT_GRID,
)
def process_blob_upload(source_blob_client: blob.BlobClient) -> None:
    properties = source_blob_client.get_blob_properties()
    source_blob = properties.name
    stage = "download"
    try:
        if properties.size > MAX_BLOB_BYTES:
            records = metadata_failure(
                source_blob,
                payload_bytes=properties.size,
                parse_status="blob_too_large",
            )
        else:
            content = source_blob_client.download_blob().readall()
            stage = "parse"
            records = process_blob(
                content,
                source_blob,
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
