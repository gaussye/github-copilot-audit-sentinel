from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobClient, BlobServiceClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from copilot_audit.ingestion import build_client, upload_records  # noqa: E402
from copilot_audit.processor import MAX_BLOB_BYTES, metadata_failure, process_blob  # noqa: E402
from copilot_audit.schema import AuditRecord  # noqa: E402
from copilot_audit.transform import configured_transform  # noqa: E402

MAX_WINDOW_DAYS = 31
HARD_MAX_BLOBS = 1_000


class BlobItem(Protocol):
    name: str
    last_modified: datetime


class BlobContainer(Protocol):
    def list_blobs(self, *, name_starts_with: str) -> Iterable[BlobItem]: ...


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded, dry-run-by-default replay of synthetic or authorized audit blobs."
    )
    parser.add_argument("--account", default="ypycopilottest")
    parser.add_argument("--container", default="github-copilot-audit-log")
    parser.add_argument("--start", type=_timestamp)
    parser.add_argument("--end", type=_timestamp)
    parser.add_argument("--blob", action="append", default=[])
    parser.add_argument("--prefix", default="")
    parser.add_argument("--max-blobs", type=int, default=100)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Ingest selected records. Without this flag the command is a dry-run.",
    )
    args = parser.parse_args(argv)
    if not args.blob and (args.start is None or args.end is None):
        parser.error("provide one or more --blob values or both --start and --end")
    if (args.start is None) != (args.end is None):
        parser.error("--start and --end must be supplied together")
    if args.start and args.end:
        if args.end <= args.start:
            parser.error("--end must be after --start")
        if args.end - args.start > timedelta(days=MAX_WINDOW_DAYS):
            parser.error(f"date range cannot exceed {MAX_WINDOW_DAYS} days")
    if not 1 <= args.max_blobs <= HARD_MAX_BLOBS:
        parser.error(f"--max-blobs must be between 1 and {HARD_MAX_BLOBS}")
    if len(args.blob) > args.max_blobs:
        parser.error("explicit --blob count exceeds --max-blobs")
    if any(not name.endswith(".json.log.gz") for name in args.blob):
        parser.error("every explicit --blob must end with .json.log.gz")
    return args


def select_blob_names(container: BlobContainer, args: argparse.Namespace) -> list[str]:
    if args.blob:
        names = list(dict.fromkeys(args.blob))
    else:
        names = []
        for item in container.list_blobs(name_starts_with=args.prefix):
            if len(names) >= args.max_blobs:
                break
            if item.name.endswith(".json.log.gz") and args.start <= item.last_modified < args.end:
                names.append(item.name)
    return names[: args.max_blobs]


def read_backfill_blob(blob_client: BlobClient, name: str) -> list[AuditRecord]:
    properties = blob_client.get_blob_properties()
    if properties.size > MAX_BLOB_BYTES:
        return metadata_failure(
            name,
            payload_bytes=properties.size,
            parse_status="blob_too_large",
        )
    return process_blob(
        blob_client.download_blob().readall(),
        name,
        transform=configured_transform(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    credential = DefaultAzureCredential()
    service = BlobServiceClient(
        f"https://{args.account}.blob.core.windows.net",
        credential=credential,
    )
    container = service.get_container_client(args.container)
    names = select_blob_names(container, args)
    print(f"Selected {len(names)} blob(s); execute={args.execute}")
    if not args.execute:
        for name in names:
            print(name)
        return 0

    client = build_client(
        os.environ["LOGS_INGESTION_ENDPOINT"],
        local_development=True,
    )
    for name in names:
        records = read_backfill_blob(container.get_blob_client(name), name)
        upload_records(
            client,
            os.environ["DCR_IMMUTABLE_ID"],
            os.environ["DCR_STREAM_NAME"],
            (record.to_log() for record in records),
        )
    print(f"Replayed {len(names)} blob(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
