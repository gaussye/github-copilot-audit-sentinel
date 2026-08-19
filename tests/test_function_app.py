from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import function_app


class FakeBlobClient:
    def get_blob_properties(self) -> SimpleNamespace:
        return SimpleNamespace(name="synthetic.json.log.gz", size=2)

    def download_blob(self) -> Any:
        return SimpleNamespace(readall=lambda: b"{}")


def test_function_boundary_redacts_sensitive_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_safely(content: bytes, source_blob: str) -> list[object]:
        raise ValueError("sensitive source payload")

    monkeypatch.setattr(function_app, "process_blob", fail_safely)

    with pytest.raises(function_app.AuditProcessingError) as caught:
        function_app.process_blob_upload(FakeBlobClient())

    assert "sensitive source payload" not in str(caught.value)
    assert caught.value.__cause__ is None
