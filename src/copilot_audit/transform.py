from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RawPayload:
    content: str
    encoding: str


RawTransform = Callable[[RawPayload], RawPayload]


def identity_transform(payload: RawPayload) -> RawPayload:
    """Return the complete payload unchanged."""
    return payload


def apply_transform(
    payload: RawPayload,
    transform: RawTransform = identity_transform,
) -> RawPayload:
    transformed = transform(payload)
    if not isinstance(transformed, RawPayload):
        raise TypeError("Raw transform must return RawPayload")
    if not transformed.encoding or len(transformed.encoding) > 128:
        raise ValueError("Raw transform encoding must contain 1-128 characters")
    return transformed


def delete_top_level_fields(fields: Iterable[str]) -> RawTransform:
    """Build an explicit opt-in policy that deletes JSON object fields."""
    field_set = frozenset(fields)

    def transform(payload: RawPayload) -> RawPayload:
        value: Any = json.loads(payload.content)
        if not isinstance(value, dict):
            raise ValueError("Field-deletion policy requires a JSON object")
        transformed = {key: item for key, item in value.items() if key not in field_set}
        return RawPayload(
            json.dumps(transformed, separators=(",", ":"), ensure_ascii=False),
            "transformed-json:deleted-top-level-fields",
        )

    return transform


def configured_transform() -> RawTransform:
    """Resolve the explicit raw transform policy; identity is the secure default."""
    policy = os.getenv("RAW_TRANSFORM_POLICY", "identity")
    if policy == "identity":
        return identity_transform
    if policy == "delete-top-level-fields":
        fields = [
            field.strip()
            for field in os.environ.get("RAW_TRANSFORM_DELETE_FIELDS", "").split(",")
            if field.strip()
        ]
        if not fields:
            raise ValueError("delete-top-level-fields requires RAW_TRANSFORM_DELETE_FIELDS")
        return delete_top_level_fields(fields)
    raise ValueError(f"Unknown RAW_TRANSFORM_POLICY: {policy}")
