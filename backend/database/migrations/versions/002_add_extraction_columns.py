"""add extraction columns to content_items

Revision ID: 002
Revises: 001
Create Date: 2026-06-11 20:50:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_items", sa.Column("extracted_entities", postgresql.JSONB, nullable=True))
    op.add_column("content_items", sa.Column("extracted_theses", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("content_items", "extracted_theses")
    op.drop_column("content_items", "extracted_entities")
