# -*- coding: utf-8 -*-
"""Authenticated ingest for redacted MetaRouter routing events."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mcpgateway.db import get_db, RoutingRecord
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission

MAX_ROUTING_EVENT_BYTES = 32 * 1024
Name = Annotated[str, Field(min_length=1, max_length=255)]


class RoutingAttemptCreate(BaseModel):
    """One redacted provider attempt."""

    model_config = ConfigDict(extra="forbid")

    provider: Name
    pool: Name
    model: Name
    used_fallback: bool
    outcome: Literal[
        "missing_credentials",
        "transport_error",
        "retryable_status",
        "response",
        "invalid_response",
        "stream_interrupted",
    ]
    latency_ms: float = Field(ge=0)
    http_status: int | None = Field(default=None, ge=100, le=599)


class RoutingTokenUsage(BaseModel):
    """Provider-returned token counters only."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class RoutingRecordCreate(BaseModel):
    """Strict MetaRouter v3 routing event contract."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    request_id: str = Field(min_length=36, max_length=36, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    request_type: str = Field(min_length=1, max_length=100)
    provider: Name | None = None
    pool: Name | None = None
    model: Name | None = None
    used_fallback: bool
    attempt_count: int = Field(ge=0, le=16)
    attempts: list[RoutingAttemptCreate] = Field(max_length=16)
    http_status: int = Field(ge=100, le=599)
    outcome: Literal["success", "upstream_error", "routing_exhausted", "stream_interrupted"]
    latency_ms: float = Field(ge=0)
    token_usage: RoutingTokenUsage | None = None
    timestamp: AwareDatetime
    streaming: bool

    @model_validator(mode="after")
    def validate_attempt_count(self) -> "RoutingRecordCreate":
        """Keep the declared count and bounded attempt list consistent."""

        if self.attempt_count != len(self.attempts):
            raise ValueError("attempt_count must match attempts length")
        if self.outcome != "routing_exhausted" and not all((self.provider, self.pool, self.model)):
            raise ValueError("completed routing events require provider, pool, and model")
        return self


class RoutingRecordRead(BaseModel):
    """Persisted routing record response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_version: int
    request_id: str
    request_type: str
    provider: str | None
    pool: str | None
    model: str | None
    used_fallback: bool
    attempt_count: int
    attempts: list[dict]
    http_status: int
    outcome: str
    latency_ms: float
    token_usage: dict[str, int | None] | None
    timestamp: datetime
    streaming: bool
    created_at: datetime


async def enforce_routing_event_size(request: Request) -> None:
    """Reject event bodies larger than the narrow ingest contract allows."""

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_ROUTING_EVENT_BYTES:
                raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Routing event too large")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Content-Length") from exc
    if len(await request.body()) > MAX_ROUTING_EVENT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Routing event too large")


router = APIRouter(prefix="/telemetry", tags=["Telemetry"])


@router.post(
    "/routing-records",
    response_model=RoutingRecordRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_routing_event_size)],
)
@require_permission("admin.system_config")
async def create_routing_record(
    payload: RoutingRecordCreate,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> RoutingRecord:
    """Validate and persist one redacted MetaRouter routing event."""

    record = RoutingRecord(
        schema_version=payload.schema_version,
        request_id=payload.request_id,
        request_type=payload.request_type,
        provider=payload.provider,
        pool=payload.pool,
        model=payload.model,
        used_fallback=payload.used_fallback,
        attempt_count=payload.attempt_count,
        attempts=[attempt.model_dump(mode="json") for attempt in payload.attempts],
        http_status=payload.http_status,
        outcome=payload.outcome,
        latency_ms=payload.latency_ms,
        token_usage=payload.token_usage.model_dump(mode="json", exclude_none=True) if payload.token_usage else None,
        timestamp=payload.timestamp,
        streaming=payload.streaming,
    )
    db.add(record)
    try:
        db.commit()
        db.refresh(record)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Routing event already exists") from exc
    return record
