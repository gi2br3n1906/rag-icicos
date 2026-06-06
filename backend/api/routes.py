"""
routes.py - Router endpoint Admin Dashboard API ICICoS 2026.

Endpoint yang tersedia:
  GET  /api/documents          → Daftar semua dokumen SOP ter-ingest
  GET  /api/chat-logs          → Riwayat percakapan bot (analitik)
  POST /api/documents/upload   → Upload + ingest SOP baru via LLM pipeline
"""
import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.database import get_db
from backend.api.models import ChatLog, Document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Admin API"])

# Folder penyimpanan sementara file PDF yang di-upload
# Path relatif terhadap posisi backend/ dijalankan sebagai CWD
_DOCS_DIR = Path(__file__).resolve().parents[1] / "data" / "docs"


# ---------------------------------------------------------------------------
# Endpoint 1: GET /api/documents
# ---------------------------------------------------------------------------

@router.get(
    "/documents",
    summary="Daftar Dokumen SOP Ter-ingest",
    response_description="List semua dokumen SOP diurutkan terbaru",
)
async def list_documents(
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Mengambil seluruh daftar file SOP yang pernah di-ingest ke ChromaDB,
    diurutkan berdasarkan tanggal ingesti terbaru (DESC).
    """
    result = await db.execute(
        select(Document).order_by(Document.ingested_at.desc())
    )
    documents = result.scalars().all()

    return [
        {
            "id": doc.id,
            "filename": doc.filename,
            "total_chunks": doc.total_chunks,
            "status": doc.status,
            "ingested_at": doc.ingested_at.isoformat() if doc.ingested_at else None,
        }
        for doc in documents
    ]


# ---------------------------------------------------------------------------
# Endpoint 2: GET /api/chat-logs
# ---------------------------------------------------------------------------

@router.get(
    "/chat-logs",
    summary="Riwayat Percakapan Bot",
    response_description="Seluruh log chat diurutkan terbaru untuk analitik dashboard",
)
async def get_chat_logs(
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Mengambil seluruh riwayat percakapan antara user dan bot dari tabel
    `chat_logs`, diurutkan berdasarkan waktu terbaru (DESC).
    Digunakan untuk halaman monitoring dan analitik di Admin Dashboard.
    """
    result = await db.execute(
        select(ChatLog).order_by(ChatLog.created_at.desc())
    )
    logs = result.scalars().all()

    return [
        {
            "id": log.id,
            "user_id": log.user_id,
            "query": log.query,
            "answer": log.answer,
            "similarity_score": log.similarity_score,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


# ---------------------------------------------------------------------------
# Endpoint 3: POST /api/documents/upload
# ---------------------------------------------------------------------------

@router.post(
    "/documents/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Upload & Ingest Dokumen SOP Baru",
    response_description="Status ingesti beserta jumlah chunk yang berhasil disimpan",
)
async def upload_document(
    file: UploadFile = File(..., description="File PDF SOP yang akan di-ingest"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Menerima upload file PDF, menjalankan pipeline LLM-Assisted Ingestion
    (Gemini Vision → Chunking → ChromaDB), lalu mencatat hasilnya ke database.

    Alur:
      1. Validasi tipe file (hanya PDF).
      2. Simpan file sementara ke backend/data/docs/.
      3. Jalankan ingest_document() — pipeline Gemini + ChromaDB.
      4. Catat record baru ke tabel `documents` (filename, chunks, status).
      5. Kembalikan ringkasan hasil ingesti.
      6. Hapus file sementara jika ingesti gagal (cleanup).
    """
    # --- [VALIDASI] Hanya terima file PDF ---
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hanya file PDF yang didukung. Pastikan ekstensi file adalah .pdf",
        )

    # --- [SIMPAN] File sementara ke disk ---
    _DOCS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = _DOCS_DIR / file.filename

    try:
        logger.info(f"[Upload] Menyimpan file '{file.filename}' ke {file_path}")
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except OSError as io_exc:
        logger.error(f"[Upload] Gagal menyimpan file ke disk: {io_exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal menyimpan file ke server: {io_exc}",
        )
    finally:
        await file.close()

    # --- [INGEST] Jalankan pipeline LLM-Assisted (lazy import) ---
    # Lazy import agar modul RAG berat tidak di-load saat API startup
    try:
        from backend.rag.ingestion import ingest_document  # noqa: PLC0415

        logger.info(f"[Upload] Memulai pipeline ingesti untuk '{file.filename}'...")
        total_chunks = await asyncio.to_thread(ingest_document, str(file_path))
        logger.info(
            f"[Upload] ✅ Ingesti berhasil: {total_chunks} chunk dari '{file.filename}'"
        )

    except Exception as ingest_exc:
        # Cleanup file jika ingesti gagal agar tidak memenuhi disk
        logger.error(
            f"[Upload] ❌ Pipeline ingesti gagal untuk '{file.filename}': {ingest_exc}",
            exc_info=True,
        )
        if file_path.exists():
            file_path.unlink()
            logger.info(f"[Upload] File sementara '{file.filename}' dihapus (cleanup).")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Proses ingesti dokumen gagal: {str(ingest_exc)}",
        )

    # --- [DB] Catat hasil ingesti ke tabel documents ---
    try:
        new_doc = Document(
            filename=file.filename,
            total_chunks=total_chunks,
            status="success",
        )
        db.add(new_doc)
        await db.commit()
        await db.refresh(new_doc)
        logger.info(
            f"[Upload] Record dokumen ID={new_doc.id} berhasil disimpan ke database."
        )

    except Exception as db_exc:
        logger.error(
            f"[Upload] Gagal menyimpan record ke database: {db_exc}", exc_info=True
        )
        # Ingesti sudah berhasil, jadi kembalikan partial success
        return {
            "status": "partial_success",
            "message": "Ingesti ke ChromaDB berhasil, tetapi gagal mencatat ke database.",
            "filename": file.filename,
            "total_chunks": total_chunks,
            "document_id": None,
        }

    return {
        "status": "success",
        "message": f"Dokumen '{file.filename}' berhasil di-ingest dan dicatat.",
        "filename": file.filename,
        "total_chunks": total_chunks,
        "document_id": new_doc.id,
        "ingested_at": new_doc.ingested_at.isoformat() if new_doc.ingested_at else None,
    }
