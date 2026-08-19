from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import function_app

SOURCE_ACCOUNT_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/synthetic-rg/providers/Microsoft.Storage/storageAccounts/"
    "ypycopilottest"
)
SOURCE_BLOB_URL = (
    "https://ypycopilottest.blob.core.windows.net/"
    "github-copilot-audit-log/2026/08/synthetic.json.log.gz"
)
SOURCE_SUBJECT = (
    "/blobServices/default/containers/github-copilot-audit-log/blobs/2026/08/synthetic.json.log.gz"
)


class FakeEvent:
    def __init__(
        self,
        *,
        event_type: str = "Microsoft.Storage.BlobCreated",
        topic: str = SOURCE_ACCOUNT_ID,
        subject: str = SOURCE_SUBJECT,
        url: str = SOURCE_BLOB_URL,
    ) -> None:
        self.event_type = event_type
        self.topic = topic
        self.subject = subject
        self._data = {"url": url}

    def get_json(self) -> dict[str, str]:
        return self._data


class FakeBlobClient:
    def get_blob_properties(self) -> SimpleNamespace:
        return SimpleNamespace(size=2)

    def download_blob(self) -> Any:
        return SimpleNamespace(readall=lambda: b"{}")


@pytest.fixture(autouse=True)
def function_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_STORAGE_ACCOUNT_RESOURCE_ID", SOURCE_ACCOUNT_ID)
    monkeypatch.setenv("SOURCE_STORAGE_ACCOUNT_NAME", "ypycopilottest")
    monkeypatch.setenv("SOURCE_CONTAINER_NAME", "github-copilot-audit-log")
    monkeypatch.setenv("LOGS_INGESTION_ENDPOINT", "https://synthetic.invalid")
    monkeypatch.setenv("DCR_IMMUTABLE_ID", "dcr-synthetic")
    monkeypatch.setenv("DCR_STREAM_NAME", "Custom-Synthetic_CL")


def test_valid_event_downloads_only_validated_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_process(content: bytes, source_blob: str, **kwargs: object) -> list[object]:
        captured["content"] = content
        captured["source_blob"] = source_blob
        return []

    monkeypatch.setattr(function_app, "build_source_blob_client", lambda url: FakeBlobClient())
    monkeypatch.setattr(function_app, "process_blob", fake_process)
    monkeypatch.setattr(function_app, "build_client", lambda endpoint: object())
    monkeypatch.setattr(function_app, "upload_records", lambda *args: 0)

    function_app.process_blob_upload(FakeEvent())  # type: ignore[arg-type]

    assert captured == {
        "content": b"{}",
        "source_blob": "2026/08/synthetic.json.log.gz",
    }


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        (FakeEvent(event_type="Microsoft.Storage.BlobDeleted"), "unexpected_event_type"),
        (FakeEvent(topic=f"{SOURCE_ACCOUNT_ID}-other"), "unexpected_topic"),
        (
            FakeEvent(
                url=(
                    "https://unapproved.blob.core.windows.net/"
                    "github-copilot-audit-log/synthetic.json.log.gz"
                )
            ),
            "unexpected_blob_url",
        ),
        (
            FakeEvent(
                url=(
                    "https://ypycopilottest.blob.core.windows.net/"
                    "other-container/synthetic.json.log.gz"
                )
            ),
            "unexpected_container",
        ),
        (
            FakeEvent(
                url=(
                    "https://ypycopilottest.blob.core.windows.net/"
                    "github-copilot-audit-log/synthetic.txt"
                )
            ),
            "unexpected_blob_name",
        ),
        (
            FakeEvent(
                subject=(
                    "/blobServices/default/containers/github-copilot-audit-log/"
                    "blobs/other.json.log.gz"
                )
            ),
            "subject_url_mismatch",
        ),
        (FakeEvent(url=f"{SOURCE_BLOB_URL}?comp=metadata"), "unexpected_blob_url"),
    ],
)
def test_rejects_unapproved_event_sources(event: FakeEvent, reason: str) -> None:
    with pytest.raises(function_app.AuditEventValidationError) as caught:
        function_app.resolve_blob_event(event)  # type: ignore[arg-type]

    assert caught.value.reason == reason


def test_rejected_event_never_builds_blob_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_client(url: str) -> object:
        raise AssertionError("rejected event must not create a Blob client")

    monkeypatch.setattr(function_app, "build_source_blob_client", unexpected_client)

    function_app.process_blob_upload(  # type: ignore[arg-type]
        FakeEvent(event_type="Microsoft.Storage.BlobDeleted")
    )


def test_download_error_propagates_without_sensitive_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailedBlobClient:
        def get_blob_properties(self) -> None:
            raise RuntimeError("synthetic sensitive response")

    monkeypatch.setattr(
        function_app,
        "build_source_blob_client",
        lambda url: FailedBlobClient(),
    )

    with pytest.raises(function_app.AuditProcessingError) as caught:
        function_app.process_blob_upload(FakeEvent())  # type: ignore[arg-type]

    assert "synthetic sensitive response" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_processing_error_does_not_leak_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_safely(content: bytes, source_blob: str, **kwargs: object) -> list[object]:
        raise ValueError("sensitive source payload")

    monkeypatch.setattr(function_app, "build_source_blob_client", lambda url: FakeBlobClient())
    monkeypatch.setattr(function_app, "process_blob", fail_safely)

    with pytest.raises(function_app.AuditProcessingError) as caught:
        function_app.process_blob_upload(FakeEvent())  # type: ignore[arg-type]

    assert "sensitive source payload" not in str(caught.value)
    assert caught.value.__cause__ is None
