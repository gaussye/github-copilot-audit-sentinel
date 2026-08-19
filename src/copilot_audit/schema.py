from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class AuditRecord:
    TimeGenerated: str
    EventId: str
    GitHubRequestId: str
    UserId: str
    EnterpriseId: str
    EventType: str
    Endpoint: str
    Model: str
    InteractionType: str
    ToolNames: str
    StatusCode: int
    SourceBlob: str
    SourceRecordIndex: int
    PayloadBytes: int
    ParseStatus: str
    IngestedAt: str

    def to_log(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> datetime:
    return datetime.now(UTC)


def azure_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
