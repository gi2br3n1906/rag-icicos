"""
main.py - Entry point FastAPI untuk ICICoS 2026 Admin Dashboard API.

Menginisialisasi aplikasi, middleware CORS, lifecycle events,
dan endpoint dasar termasuk health check dengan validasi koneksi database.

Cara menjalankan (dari folder backend/):
  uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
"""
import logging
from pathlib import Path

from dotenv import load_dotenv
# Secara eksplisit memuat .env agar os.getenv() di modul lain bisa membacanya
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=True)

from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.config import settings
from backend.api.database import get_db, init_db
from backend.api.routes import router as api_router, auth_router


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifecycle Manager (startup & shutdown)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Mengelola siklus hidup aplikasi FastAPI.

    Startup:
      - Membuat semua tabel database yang belum ada (idempotent).

    Shutdown:
      - Log pesan penghentian.
    """
    logger.info("🚀 ICICoS Admin API sedang startup...")
    await init_db()
    logger.info("✅ Semua tabel database siap.")
    yield
    logger.info("🛑 ICICoS Admin API sedang shutdown.")


# ---------------------------------------------------------------------------
# Inisialisasi FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="ICICoS 2026 Admin Dashboard API",
    description=(
        "REST API backend untuk Admin Dashboard ICICoS 2026. "
        "Mengelola ingesti dokumen SOP, monitoring log percakapan bot, "
        "dan manajemen knowledge base."
    ),
    version="0.1.0",
    docs_url="/api/docs",       # Swagger UI di /api/docs
    redoc_url="/api/redoc",     # ReDoc di /api/redoc
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# CORS Middleware
# Mengizinkan frontend Vue.js (localhost:3000 / 5173) mengakses API ini.
# Sesuaikan allowed_origins sebelum deploy ke production.
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",    # Vue.js dev server (Vite default)
        "http://localhost:5173",    # Vite alternatif port
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Include Routers
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(api_router)



# ---------------------------------------------------------------------------
# Health Check Endpoint
# ---------------------------------------------------------------------------
@app.get(
    "/api/health",
    tags=["System"],
    summary="Health Check dengan validasi koneksi database",
    response_description="Status kesehatan API dan koneksi database",
)
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Endpoint health check untuk monitoring dan Docker healthcheck.

    Melakukan query `SELECT 1` secara async ke PostgreSQL untuk memastikan
    koneksi database aktif. Mengembalikan 503 jika database tidak dapat
    dijangkau.
    """
    try:
        # Query tiruan sederhana untuk validasi koneksi database
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        logger.error(f"[Health] Koneksi database gagal: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(exc),
            },
        )

    return {
        "status": "healthy",
        "database": db_status,
        "environment": settings.app_env,
        "version": app.version,
    }
