"""initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ENUM types
    for type_sql in [
        "DO $$ BEGIN CREATE TYPE source_type AS ENUM ('sec_13f','website','youtube','rss','twitter','custom'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        "DO $$ BEGIN CREATE TYPE content_type AS ENUM ('filing','article','video','newsletter','website_page','custom'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        "DO $$ BEGIN CREATE TYPE processing_status AS ENUM ('pending','processing','completed','failed','skipped'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        "DO $$ BEGIN CREATE TYPE entity_type AS ENUM ('company','ticker','person','theme','sector','macro_theme'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        "DO $$ BEGIN CREATE TYPE sentiment AS ENUM ('bullish','bearish','neutral','mixed'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        "DO $$ BEGIN CREATE TYPE conviction_level AS ENUM ('high','medium','low','unknown'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        "DO $$ BEGIN CREATE TYPE portfolio_change_type AS ENUM ('new_position','increased','decreased','closed','unchanged'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        "DO $$ BEGIN CREATE TYPE report_type AS ENUM ('investor_report','daily_digest','event_report'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        "DO $$ BEGIN CREATE TYPE alert_type AS ENUM ('new_filing','new_company_mention','new_thesis','high_conviction','portfolio_change','daily_digest_ready'); EXCEPTION WHEN duplicate_object THEN null; END $$",
        "DO $$ BEGIN CREATE TYPE alert_severity AS ENUM ('low','medium','high','critical'); EXCEPTION WHEN duplicate_object THEN null; END $$",
    ]:
        op.execute(type_sql)

    # users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String, nullable=False),
        sa.Column("full_name", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_users_email", "users", ["email"])

    # investors
    op.create_table(
        "investors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("description", sa.String, nullable=True),
        sa.Column("cik_number", sa.String, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_investors_user_id", "investors", ["user_id"])
    op.create_index("idx_investors_cik", "investors", ["cik_number"], postgresql_where=sa.text("cik_number IS NOT NULL"))
    op.create_index("idx_investors_active", "investors", ["user_id", "is_active"])

    # sources
    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("investor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", postgresql.ENUM(name="source_type", create_type=False), nullable=False),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("label", sa.String, nullable=True),
        sa.Column("config", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_frequency_hours", sa.Integer, nullable=False, server_default="24"),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_sources_investor_id", "sources", ["investor_id"])
    op.create_index("idx_sources_type", "sources", ["source_type"])
    op.create_index("idx_sources_active_check", "sources", ["is_active", "last_checked_at"], postgresql_where=sa.text("is_active = TRUE"))

    # content_items
    op.create_table(
        "content_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("investor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_type", postgresql.ENUM(name="content_type", create_type=False), nullable=False),
        sa.Column("title", sa.String, nullable=True),
        sa.Column("url", sa.String, nullable=True),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("cleaned_text", sa.Text, nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String, nullable=False),
        sa.Column("processing_status", postgresql.ENUM(name="processing_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("processing_error", sa.Text, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("content_hash", name="unique_content_hash"),
    )
    op.create_index("idx_content_source_id", "content_items", ["source_id"])
    op.create_index("idx_content_investor_id", "content_items", ["investor_id"])
    op.create_index("idx_content_status", "content_items", ["processing_status"], postgresql_where=sa.text("processing_status IN ('pending', 'processing')"))
    op.create_index("idx_content_published", "content_items", ["investor_id", "published_at"])
    op.create_index("idx_content_type", "content_items", ["investor_id", "content_type"])

    # extracted_mentions
    op.create_table(
        "extracted_mentions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("investor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", postgresql.ENUM(name="entity_type", create_type=False), nullable=False),
        sa.Column("entity_name", sa.String, nullable=False),
        sa.Column("ticker_symbol", sa.String, nullable=True),
        sa.Column("sentiment", postgresql.ENUM(name="sentiment", create_type=False), nullable=True),
        sa.Column("conviction_level", postgresql.ENUM(name="conviction_level", create_type=False), nullable=True),
        sa.Column("context_snippet", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_mentions_content", "extracted_mentions", ["content_item_id"])
    op.create_index("idx_mentions_investor", "extracted_mentions", ["investor_id"])
    op.create_index("idx_mentions_ticker", "extracted_mentions", ["ticker_symbol"], postgresql_where=sa.text("ticker_symbol IS NOT NULL"))
    op.create_index("idx_mentions_entity", "extracted_mentions", ["entity_type", "entity_name"])

    # portfolio_changes
    op.create_table(
        "portfolio_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("investor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticker_symbol", sa.String, nullable=False),
        sa.Column("company_name", sa.String, nullable=True),
        sa.Column("cusip", sa.String, nullable=True),
        sa.Column("change_type", postgresql.ENUM(name="portfolio_change_type", create_type=False), nullable=False),
        sa.Column("shares_previous", sa.BigInteger, server_default="0"),
        sa.Column("shares_current", sa.BigInteger, nullable=False),
        sa.Column("value_usd", sa.BigInteger, nullable=True),
        sa.Column("percent_of_portfolio", sa.Numeric(6, 3), nullable=True),
        sa.Column("filing_period", sa.String, nullable=False),
        sa.Column("report_date", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_portfolio_investor", "portfolio_changes", ["investor_id"])
    op.create_index("idx_portfolio_ticker", "portfolio_changes", ["ticker_symbol"])
    op.create_index("idx_portfolio_period", "portfolio_changes", ["investor_id", "filing_period"])
    op.create_index("idx_portfolio_change", "portfolio_changes", ["change_type"])

    # reports
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("investor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investors.id", ondelete="SET NULL"), nullable=True),
        sa.Column("report_type", postgresql.ENUM(name="report_type", create_type=False), nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("content_markdown", sa.Text, nullable=False),
        sa.Column("source_item_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_reports_user_id", "reports", ["user_id"])
    op.create_index("idx_reports_investor_id", "reports", ["investor_id"], postgresql_where=sa.text("investor_id IS NOT NULL"))
    op.create_index("idx_reports_type", "reports", ["user_id", "report_type"])
    op.create_index("idx_reports_generated", "reports", ["user_id", "generated_at"])
    op.create_index("idx_reports_unread", "reports", ["user_id", "is_read"], postgresql_where=sa.text("is_read = FALSE"))

    # alerts
    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("investor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investors.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.id", ondelete="SET NULL"), nullable=True),
        sa.Column("alert_type", postgresql.ENUM(name="alert_type", create_type=False), nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("severity", postgresql.ENUM(name="alert_severity", create_type=False), nullable=False, server_default="medium"),
        sa.Column("score", sa.Integer, nullable=False, server_default="50"),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("email_sent", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name="chk_score_range"),
    )
    op.create_index("idx_alerts_user_unread", "alerts", ["user_id", "is_read", "created_at"])
    op.create_index("idx_alerts_investor", "alerts", ["investor_id"], postgresql_where=sa.text("investor_id IS NOT NULL"))
    op.create_index("idx_alerts_type", "alerts", ["alert_type"])
    op.create_index("idx_alerts_severity", "alerts", ["user_id", "severity"], postgresql_where=sa.text("is_read = FALSE"))


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("reports")
    op.drop_table("portfolio_changes")
    op.drop_table("extracted_mentions")
    op.drop_table("content_items")
    op.drop_table("sources")
    op.drop_table("investors")
    op.drop_table("users")
    for t in ["alert_severity","alert_type","report_type","portfolio_change_type",
              "conviction_level","sentiment","entity_type","processing_status",
              "content_type","source_type"]:
        op.execute(f"DROP TYPE IF EXISTS {t}")
