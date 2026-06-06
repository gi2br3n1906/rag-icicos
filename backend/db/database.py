"""
database.py - Konfigurasi koneksi async PostgreSQL menggunakan SQLAlchemy + asyncpg.
"""
import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.models import Base

logger = logging.getLogger(__name__)

# Membaca URL database dari environment variable
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://user:password@localhost:5432/icicos_db",
)

# Membuat async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,       # Set True untuk debug query SQL
    pool_pre_ping=True,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Membuat semua tabel di database jika belum ada (development helper)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database initialized (tabel dibuat jika belum ada).")


async def get_db_session() -> AsyncSession:
    """Dependency injection untuk FastAPI endpoint yang membutuhkan DB session."""
    async with AsyncSessionLocal() as session:
        yield session
