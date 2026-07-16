# -*- coding: utf-8 -*-
"""Add an explicit schema version to MetaRouter routing records.

Revision ID: a6d4e2f9c8b1
Revises: f3c7d9e1a2b4
Create Date: 2026-07-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a6d4e2f9c8b1"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "f3c7d9e1a2b4"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Version existing and future redacted routing records."""

    op.add_column(
        "routing_records",
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_check_constraint("ck_routing_records_schema_version", "routing_records", "schema_version >= 1")
    op.alter_column("routing_records", "schema_version", server_default=None)


def downgrade() -> None:
    """Remove the routing-record schema version."""

    op.drop_constraint("ck_routing_records_schema_version", "routing_records", type_="check")
    op.drop_column("routing_records", "schema_version")
