"""
database.py - Setup Async Engine dan Session SQLAlchemy 2.0.

Menyediakan:
  - async_engine  : Koneksi async ke PostgreSQL via asyncpg
  - AsyncSessionLocal : Session factory untuk transaksi database
  - Base          : Deklarasi base class untuk semua ORM model
  - get_db()      : Async generator dependency untuk FastAPI endpoint
  - init_db()     : Helper inisialisasi tabel saat startup
"""
import logging

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from backend.api.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Async Engine
# pool_pre_ping=True → tes koneksi sebelum dipakai (handles stale connections)
# echo=True hanya saat development untuk melihat query SQL di log
# ---------------------------------------------------------------------------
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# ---------------------------------------------------------------------------
# Session Factory (SQLAlchemy 2.0 style)
# expire_on_commit=False → objek masih bisa diakses setelah commit
# ---------------------------------------------------------------------------
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Declarative Base (SQLAlchemy 2.0 style menggunakan DeclarativeBase)
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    """Base class untuk semua ORM model. Semua tabel diwarisi dari sini."""
    pass


# ---------------------------------------------------------------------------
# Dependency: get_db()
# Dipakai sebagai Depends(get_db) di endpoint FastAPI agar setiap request
# mendapatkan session baru yang otomatis di-commit atau di-rollback.
# ---------------------------------------------------------------------------
async def get_db() -> AsyncSession:
    """
    Async generator dependency untuk FastAPI.

    Pola penggunaan di endpoint:
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            result = await db.execute(...)

    Session otomatis di-close setelah request selesai (blok finally).
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Helper: init_db()
# Membuat semua tabel yang didefinisikan di models.py jika belum ada.
# Dipanggil satu kali saat startup aplikasi.
# ---------------------------------------------------------------------------
async def init_db() -> None:
    """
    Membuat semua tabel di database berdasarkan definisi ORM model.
    Aman dipanggil berulang kali (CREATE TABLE IF NOT EXISTS).
    """
    # Import di sini untuk menghindari circular import
    import backend.api.models  # noqa: F401 — pastikan model ter-register ke Base.metadata

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("✅ Database initialized — semua tabel siap digunakan.")
