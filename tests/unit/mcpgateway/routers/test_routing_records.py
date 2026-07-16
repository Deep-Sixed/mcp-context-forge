from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi import HTTPException
from pydantic import ValidationError
import pytest
from starlette.requests import Request

from mcpgateway.routers.routing_records import (
    create_routing_record,
    enforce_routing_event_size,
    MAX_ROUTING_EVENT_BYTES,
    RoutingRecordCreate,
)


def valid_event() -> dict:
    return {
        "schema_version": 1,
        "request_id": "123e4567-e89b-42d3-a456-426614174000",
        "request_type": "controlled",
        "provider": "primary",
        "pool": "primary",
        "model": "primary-model",
        "used_fallback": False,
        "attempt_count": 1,
        "attempts": [
            {
                "provider": "primary",
                "pool": "primary",
                "model": "primary-model",
                "used_fallback": False,
                "outcome": "response",
                "latency_ms": 12.5,
                "http_status": 200,
            }
        ],
        "http_status": 200,
        "outcome": "success",
        "latency_ms": 14.0,
        "token_usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        "timestamp": "2026-07-13T09:00:00Z",
        "streaming": False,
    }


def test_event_schema_accepts_redacted_contract() -> None:
    event = RoutingRecordCreate.model_validate(valid_event())
    assert event.provider == "primary"
    assert event.attempt_count == 1


@pytest.mark.parametrize("forbidden_field", ["prompt", "messages", "response_body", "authorization", "provider_key"])
def test_event_schema_rejects_sensitive_or_unknown_fields(forbidden_field: str) -> None:
    payload = valid_event()
    payload[forbidden_field] = "must-not-be-stored"
    with pytest.raises(ValidationError, match=forbidden_field):
        RoutingRecordCreate.model_validate(payload)


def test_event_schema_rejects_incorrect_attempt_count() -> None:
    payload = valid_event()
    payload["attempt_count"] = 2
    with pytest.raises(ValidationError, match="attempt_count"):
        RoutingRecordCreate.model_validate(payload)


def test_event_schema_rejects_unknown_schema_version() -> None:
    payload = valid_event()
    payload["schema_version"] = 2
    with pytest.raises(ValidationError, match="schema_version"):
        RoutingRecordCreate.model_validate(payload)


@pytest.mark.parametrize("attempt_outcome", ["invalid_response", "stream_interrupted"])
def test_event_schema_accepts_terminal_attempt_outcomes(attempt_outcome: str) -> None:
    payload = valid_event()
    payload["attempts"][0]["outcome"] = attempt_outcome
    event = RoutingRecordCreate.model_validate(payload)
    assert event.attempts[0].outcome == attempt_outcome


def test_ingest_requires_admin_system_config_permission() -> None:
    assert create_routing_record._required_permission == "admin.system_config"
    assert hasattr(create_routing_record, "__wrapped__")


@pytest.mark.asyncio
async def test_ingest_rejects_oversized_body() -> None:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/telemetry/routing-records",
        "headers": [(b"content-length", str(MAX_ROUTING_EVENT_BYTES + 1).encode())],
    }
    request = Request(scope)
    with pytest.raises(HTTPException) as exc_info:
        await enforce_routing_event_size(request)
    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_ingest_persists_only_validated_fields() -> None:
    payload = RoutingRecordCreate.model_validate(valid_event())
    db = MagicMock()

    def refresh(record) -> None:
        record.id = "record-id"
        record.created_at = datetime.now(timezone.utc)

    db.refresh.side_effect = refresh
    record = await create_routing_record.__wrapped__(payload=payload, db=db, _user={"email": "admin@example.com"})

    db.add.assert_called_once_with(record)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(record)
    assert record.request_id == payload.request_id
    assert record.schema_version == 1
    assert record.token_usage == {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}
    assert not hasattr(record, "prompt")
    assert not hasattr(record, "response_body")
