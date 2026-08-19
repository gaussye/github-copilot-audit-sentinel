from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backfill.py"
spec = importlib.util.spec_from_file_location("backfill", SCRIPT)
assert spec and spec.loader
backfill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backfill)


def test_backfill_requires_bounded_selection() -> None:
    with pytest.raises(SystemExit):
        backfill.parse_args([])


def test_backfill_is_dry_run_by_default() -> None:
    args = backfill.parse_args(["--blob", "one.json.log.gz"])

    assert args.execute is False
    assert args.max_blobs == 100


def test_backfill_rejects_oversized_date_window() -> None:
    with pytest.raises(SystemExit):
        backfill.parse_args(["--start", "2026-01-01T00:00:00Z", "--end", "2026-03-01T00:00:00Z"])


def test_selection_honors_date_suffix_and_count_bound() -> None:
    class Container:
        def list_blobs(self, name_starts_with: str) -> list[SimpleNamespace]:
            assert name_starts_with == "audit/"
            return [
                SimpleNamespace(
                    name="audit/a.json.log.gz",
                    last_modified=datetime(2026, 8, 2, tzinfo=UTC),
                ),
                SimpleNamespace(
                    name="audit/ignore.txt",
                    last_modified=datetime(2026, 8, 2, tzinfo=UTC),
                ),
                SimpleNamespace(
                    name="audit/b.json.log.gz",
                    last_modified=datetime(2026, 8, 3, tzinfo=UTC),
                ),
            ]

    args = backfill.parse_args(
        [
            "--start",
            "2026-08-01T00:00:00Z",
            "--end",
            "2026-08-10T00:00:00Z",
            "--prefix",
            "audit/",
            "--max-blobs",
            "1",
        ]
    )

    assert backfill.select_blob_names(Container(), args) == ["audit/a.json.log.gz"]


def test_backfill_rejects_non_audit_blob_suffix() -> None:
    with pytest.raises(SystemExit):
        backfill.parse_args(["--blob", "arbitrary.txt"])


def test_backfill_does_not_download_oversized_blob() -> None:
    class OversizedBlob:
        def get_blob_properties(self) -> SimpleNamespace:
            return SimpleNamespace(size=backfill.MAX_BLOB_BYTES + 1)

        def download_blob(self) -> None:
            raise AssertionError("oversized blob must not be downloaded")

    records = backfill.read_backfill_blob(
        OversizedBlob(),
        "oversized.json.log.gz",
    )

    assert len(records) == 1
    assert records[0].ParseStatus == "blob_too_large"
