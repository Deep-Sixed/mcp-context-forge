# -*- coding: utf-8 -*-
"""Add redacted MetaRouter routing telemetry records.

Revision ID: f3c7d9e1a2b4
Revises: e198602c3c1e
Create Date: 2026-07-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f3c7d9e1a2b4"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "e198602c3c1e"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create routing_records when absent."""

    inspector = sa.inspect(op.get_bind())
    if "routing_records" in inspector.get_table_names():
        return
    op.create_table(
        "routing_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("request_type", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=255), nullable=True),
        sa.Column("pool", sa.String(length=255), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("used_fallback", sa.Boolean(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.JSON(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("token_usage", sa.JSON(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("streaming", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="ck_routing_records_attempt_count"),
        sa.CheckConstraint("http_status >= 100 AND http_status <= 599", name="ck_routing_records_http_status"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_routing_records_latency_ms"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("ix_routing_records_request_id", "routing_records", ["request_id"], unique=True)
    op.create_index("ix_routing_records_request_type", "routing_records", ["request_type"], unique=False)
    op.create_index("ix_routing_records_provider", "routing_records", ["provider"], unique=False)
    op.create_index("ix_routing_records_pool", "routing_records", ["pool"], unique=False)
    op.create_index("ix_routing_records_model", "routing_records", ["model"], unique=False)
    op.create_index("ix_routing_records_http_status", "routing_records", ["http_status"], unique=False)
    op.create_index("ix_routing_records_outcome", "routing_records", ["outcome"], unique=False)
    op.create_index("ix_routing_records_timestamp", "routing_records", ["timestamp"], unique=False)
    op.create_index("idx_routing_records_provider_model", "routing_records", ["provider", "model"], unique=False)


def downgrade() -> None:
    """Drop routing_records when present."""

    inspector = sa.inspect(op.get_bind())
    if "routing_records" in inspector.get_table_names():
        op.drop_table("routing_records")
