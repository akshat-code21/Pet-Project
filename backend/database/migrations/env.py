"""
Alembic migration environment.

Uses a synchronous SQLAlchemy engine so migrations work reliably against
Supabase (and any PostgreSQL). The runtime app uses asyncpg/asyncio; Alembic
does not need to.

URL resolution order:
  1. MIGRATION_DATABASE_URL env var  (preferred — direct connection, port 5432)
  2. DATABASE_URL with +asyncpg swapped out for plain postgresql://
     (fallback, works as long as you're on port 5432)
"""
import os
import re
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Load .env from the backend root (two levels up from this file)
try:
    from dotenv import load_dotenv
    #_env_path = Path(__file__).resolve().parents[3] / ".env"
    #load_dotenv(_env_path, override=False)
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on env vars being set externally

from database.base import Base

# Import all models so Alembic sees the full schema
import models.user  # noqa: F401
import models.investor  # noqa: F401
import models.source  # noqa: F401
import models.content_item  # noqa: F401
import models.extracted_mention  # noqa: F401
import models.portfolio_change  # noqa: F401
import models.report  # noqa: F401
import models.alert  # noqa: F401

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = Base.metadata


def _get_sync_url() -> str:
    """
    Return a psycopg2-compatible (synchronous) database URL.

    Priority:
      1. MIGRATION_DATABASE_URL  — set this to your Supabase direct URL
         (Settings → Database → Connection string → URI, port 5432)
      2. DATABASE_URL — strip the +asyncpg driver qualifier so SQLAlchemy
         uses psycopg2. Still requires port 5432 to work reliably.
    """
    url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL", "")

    if not url:
        raise RuntimeError(
            "Neither MIGRATION_DATABASE_URL nor DATABASE_URL is set. "
            "Add one to your .env file."
        )

    # Replace postgresql+asyncpg:// → postgresql:// (uses psycopg2)
    url = re.sub(r"^postgresql\+asyncpg://", "postgresql://", url)
    # Also handle postgres:// (some providers use this)
    url = re.sub(r"^postgres://", "postgresql://", url)

    return url


def run_migrations_offline() -> None:
    """Run without a live DB connection (generates SQL script)."""
    context.configure(
        url=_get_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run against a live connection."""
    sync_url = _get_sync_url()

    connectable = engine_from_config(
        {"sqlalchemy.url": sync_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # single connection, no pooling — safe for migrations
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
