"""
main.py - Entry point utama aplikasi ICICoS 2026 RAG Bot.
Menginisialisasi FastAPI app dan Telegram Bot sekaligus.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv(override=True)

# Setup logging dasar
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: jalankan bot saat startup, bersihkan saat shutdown."""
    logger.info("🚀 ICICoS RAG Bot Backend starting up...")
    yield
    logger.info("🛑 ICICoS RAG Bot Backend shutting down...")


app = FastAPI(
    title="ICICoS 2026 RAG Bot API",
    description="Backend API dan Telegram Bot untuk ICICoS 2026 Conference Assistant.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["Health"])
async def health_check():
    """Endpoint health check untuk monitoring dan Docker healthcheck."""
    return {"status": "ok", "service": "icicos-rag-bot"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
