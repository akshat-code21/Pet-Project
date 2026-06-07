import uuid
from collections.abc import AsyncGenerator

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from supabase import create_client

from app.config import get_settings
from database.connection import get_db
from models.user import User

logger = structlog.get_logger()
settings = get_settings()
bearer_scheme = HTTPBearer()

# Single shared Supabase client for token verification
_supabase = create_client(settings.supabase_url, settings.supabase_service_key)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Let Supabase verify the JWT — works with any algorithm (HS256, RS256, ES256)
    # regardless of how the project is configured. No local crypto needed.
    try:
        resp = _supabase.auth.get_user(token)
        if not resp.user:
            raise credentials_exception
        user_id: str = resp.user.id
    except Exception as e:
        logger.warning("JWT validation failed", error=str(e))
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        # Supabase verified this user but they don't have a local row yet
        # (e.g. signed up via Supabase dashboard or email confirmation flow
        # before the local sync happened). Auto-provision them so they can use
        # the API immediately without having to go through /auth/signup again.
        try:
            user = User(
                id=uuid.UUID(user_id),
                email=resp.user.email or "",
                full_name=(resp.user.user_metadata or {}).get("full_name"),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            logger.info("Auto-provisioned local user", user_id=user_id, email=user.email)
        except Exception as e:
            logger.error("Failed to auto-provision user", user_id=user_id, error=str(e))
            raise credentials_exception

    return user


# Re-export get_db so routers only import from deps
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db():
        yield session
