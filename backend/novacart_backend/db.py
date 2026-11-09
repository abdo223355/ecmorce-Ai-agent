"""Database engine and session factory. DATABASE_URL picks PostgreSQL (Compose) or SQLite (tests)."""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DEFAULT_URL = "postgresql+psycopg://novacart:novacart@localhost:5432/novacart"


def sqlalchemy_url(url: str) -> str:
    """Hosts hand out 'postgres://...' or 'postgresql://...'; SQLAlchemy needs the driver we install (psycopg 3)."""
    for plain in ("postgres://", "postgresql://"):
        if url.startswith(plain):
            return "postgresql+psycopg://" + url[len(plain):]
    return url


def make_engine(url: str | None = None):
    url = sqlalchemy_url(url or os.getenv("DATABASE_URL", DEFAULT_URL))
    return create_engine(url, pool_pre_ping=True, future=True)


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
