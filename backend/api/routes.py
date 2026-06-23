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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status, BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.database import get_db
from backend.api.models import ChatLog, Document, WhatsAppFAQ

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
# Endpoint 3: GET /api/stats
# ---------------------------------------------------------------------------

@router.get(
    "/stats",
    summary="Statistik Dashboard",
    response_description="Data analitik untuk dashboard (total sesi, pengguna unik, dll)",
)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Menghitung statistik utama untuk ditampilkan di bagian atas Dashboard Admin.
    """
    # 1. Total Sesi Chat
    total_sessions_result = await db.execute(select(func.count(ChatLog.id)))
    total_sessions = total_sessions_result.scalar_one_or_none() or 0

    # 2. Pengguna Unik (Count distinct user_id)
    unique_users_result = await db.execute(select(func.count(func.distinct(ChatLog.user_id))))
    unique_users = unique_users_result.scalar_one_or_none() or 0

    # 3. Rata-rata Similarity Score
    avg_sim_result = await db.execute(select(func.avg(ChatLog.similarity_score)))
    avg_similarity = avg_sim_result.scalar_one_or_none() or 0.0

    # 4. Dokumen SOP Aktif (Status == 'success')
    active_docs_result = await db.execute(
        select(func.count(Document.id)).where(Document.status == "success")
    )
    active_docs = active_docs_result.scalar_one_or_none() or 0

    return {
        "total_sessions": total_sessions,
        "unique_users": unique_users,
        "avg_similarity": round(avg_similarity, 2),
        "active_docs": active_docs,
    }


# ---------------------------------------------------------------------------
# Endpoint 4: POST /api/documents/upload
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
            import gc
            import time

            # Paksa garbage collection untuk melepaskan file handle Python yang mungkin masih tertahan
            gc.collect()

            max_retries = 5
            for i in range(max_retries):
                try:
                    file_path.unlink()
                    logger.info(f"[Upload] File sementara '{file.filename}' berhasil dihapus (cleanup).")
                    break
                except PermissionError as perm_err:
                    if i == max_retries - 1:
                        logger.error(
                            f"[Upload] Gagal menghapus file sementara '{file.filename}' setelah {max_retries} percobaan: {perm_err}"
                        )
                    else:
                        logger.warning(
                            f"[Upload] File '{file.filename}' masih terkunci (percobaan {i+1}/{max_retries}). Menunggu..."
                        )
                        time.sleep(0.5)
                        gc.collect()

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


# ---------------------------------------------------------------------------
# Endpoint 5: DELETE /api/documents/{document_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/documents/{document_id}",
    summary="Hapus Dokumen SOP",
    response_description="Status penghapusan dokumen dari database dan ChromaDB",
)
async def delete_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Menghapus dokumen SOP tertentu berdasarkan ID.
    Menghapus record dari database PostgreSQL dan menghapus seluruh embedding
    terkait dari ChromaDB.
    """
    # 1. Cari dokumen di database
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dokumen dengan ID {document_id} tidak ditemukan.",
        )

    filename = document.filename

    # 2. Hapus embedding dari ChromaDB (dijalankan di thread terpisah agar non-blocking)
    try:
        def sync_delete_chroma(fname: str):
            from langchain_chroma import Chroma
            from backend.rag.ingestion import get_embeddings, CHROMA_PERSIST_DIR
            
            embeddings = get_embeddings()
            vector_store = Chroma(
                persist_directory=CHROMA_PERSIST_DIR,
                embedding_function=embeddings,
                collection_name="icicos_sop",
            )
            vector_store.delete(where={"source": fname})

        logger.info(f"[Delete] Menghapus embedding untuk file '{filename}' dari ChromaDB...")
        await asyncio.to_thread(sync_delete_chroma, filename)
        logger.info(f"[Delete] Embedding untuk file '{filename}' berhasil dihapus.")
    except Exception as chroma_exc:
        logger.error(
            f"[Delete] Gagal menghapus embedding ChromaDB untuk '{filename}': {chroma_exc}",
            exc_info=True,
        )

    # 3. Hapus record dari database
    try:
        await db.delete(document)
        await db.commit()
        logger.info(f"[Delete] Dokumen ID={document_id} berhasil dihapus dari database.")
    except Exception as db_exc:
        logger.error(
            f"[Delete] Gagal menghapus record dokumen dari database: {db_exc}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal menghapus dokumen dari database: {str(db_exc)}",
        )

    return {
        "status": "success",
        "message": f"Dokumen '{filename}' berhasil dihapus dari sistem.",
        "document_id": document_id,
    }


# ---------------------------------------------------------------------------
# Endpoint 6: GET /api/documents/{document_id}/chunks
# ---------------------------------------------------------------------------

@router.get(
    "/documents/{document_id}/chunks",
    summary="Lihat Chunk Dokumen",
    response_description="Daftar potongan teks (chunks) dari dokumen SOP di ChromaDB",
)
async def get_document_chunks(
    document_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Mengambil isi raw dari chunk yang tersimpan di ChromaDB untuk dokumen tertentu.
    Hanya mengambil chunk berukuran kecil dari koleksi icicos_sop.
    """
    # 1. Cari dokumen di database
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dokumen dengan ID {document_id} tidak ditemukan.",
        )

    filename = document.filename

    # 2. Query ke ChromaDB secara asinkron
    try:
        def sync_get_chunks(fname: str):
            from langchain_chroma import Chroma
            from backend.rag.ingestion import get_embeddings, CHROMA_PERSIST_DIR
            
            embeddings = get_embeddings()
            vector_store = Chroma(
                persist_directory=CHROMA_PERSIST_DIR,
                embedding_function=embeddings,
                collection_name="icicos_sop",
            )
            # Dapatkan semua chunk yang memiliki source == filename
            results = vector_store.get(where={"source": fname})
            return results

        logger.info(f"[View Chunks] Mengambil chunk untuk file '{filename}' dari ChromaDB...")
        chroma_data = await asyncio.to_thread(sync_get_chunks, filename)
        
        chunks = []
        if chroma_data and "documents" in chroma_data and chroma_data["documents"]:
            for i in range(len(chroma_data["documents"])):
                chunks.append({
                    "id": chroma_data["ids"][i] if "ids" in chroma_data else str(i),
                    "content": chroma_data["documents"][i],
                    "metadata": chroma_data["metadatas"][i] if "metadatas" in chroma_data else {}
                })
                
        return {
            "status": "success",
            "document_id": document_id,
            "filename": filename,
            "total_chunks": len(chunks),
            "chunks": chunks
        }
    except Exception as chroma_exc:
        logger.error(
            f"[View Chunks] Gagal mengambil chunk ChromaDB untuk '{filename}': {chroma_exc}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal mengambil chunk dari ChromaDB: {str(chroma_exc)}",
        )


# ---------------------------------------------------------------------------
# Pydantic Schemas untuk WhatsApp FAQ
# ---------------------------------------------------------------------------
from pydantic import BaseModel

class FAQUpdateSchema(BaseModel):
    question: str
    answer: str
    category: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoint 6: POST /api/whatsapp/upload
# ---------------------------------------------------------------------------

async def run_distillation_task(file_path: Path):
    """Fungsi pembantu latar belakang untuk menjalankan distilasi asinkron."""
    from backend.api.database import AsyncSessionLocal
    from backend.rag.whatsapp_distill import process_whatsapp_chat_distillation
    
    logger.info(f"[BgTask] Memulai background task distilasi chat WA untuk: {file_path.name}")
    async with AsyncSessionLocal() as session:
        try:
            total = await process_whatsapp_chat_distillation(file_path, session)
            logger.info(f"[BgTask] Distilasi selesai. {total} FAQ disimpan ke staging.")
        except Exception as exc:
            logger.error(f"[BgTask] Distilasi gagal: {exc}", exc_info=True)
        finally:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"[BgTask] File sementara '{file_path.name}' berhasil dibersihkan.")


@router.post(
    "/whatsapp/upload",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload & Distill Chat Log WhatsApp",
    response_description="Status upload chat log yang diterima untuk diproses",
)
async def upload_whatsapp_chat(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="File .txt atau .zip ekspor chat log WhatsApp"),
) -> Dict[str, Any]:
    """
    Menerima unggahan file .txt atau .zip ekspor chat WhatsApp, lalu memprosesnya
    secara asinkron di background menggunakan LLM untuk mengekstrak Q&A.
    """
    ext = Path(file.filename).suffix.lower() if file.filename else ""
    if ext not in [".txt", ".zip"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hanya mendukung file .txt atau .zip hasil ekspor chat WhatsApp.",
        )

    # Simpan sementara ke folder data/docs/
    _DOCS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = _DOCS_DIR / file.filename

    try:
        logger.info(f"[Upload WA] Menyimpan file '{file.filename}' ke {file_path}")
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except OSError as io_exc:
        logger.error(f"[Upload WA] Gagal menyimpan file ke disk: {io_exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal menyimpan file chat ke server: {io_exc}",
        )
    finally:
        await file.close()

    # Daftarkan proses distilasi ke BackgroundTasks FastAPI
    background_tasks.add_task(run_distillation_task, file_path)

    return {
        "status": "processing",
        "message": f"File '{file.filename}' berhasil diunggah dan sedang diekstrak di latar belakang. Silakan cek halaman review beberapa saat lagi.",
        "filename": file.filename,
    }


# ---------------------------------------------------------------------------
# Endpoint 7: GET /api/whatsapp/pending
# ---------------------------------------------------------------------------

@router.get(
    "/whatsapp/pending",
    summary="Daftar Q&A Pending untuk Review",
    response_description="List Q&A WhatsApp yang statusnya pending review",
)
async def get_pending_faqs(
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Mengambil semua data tanya-jawab hasil ekstraksi WhatsApp yang berstatus 'pending',
    diurutkan berdasarkan waktu pembuatan terbaru (DESC).
    """
    result = await db.execute(
        select(WhatsAppFAQ)
        .where(WhatsAppFAQ.status == "pending")
        .order_by(WhatsAppFAQ.created_at.desc())
    )
    faqs = result.scalars().all()

    return [
        {
            "id": faq.id,
            "question": faq.question,
            "answer": faq.answer,
            "category": faq.category,
            "status": faq.status,
            "source_file": faq.source_file,
            "created_at": faq.created_at.isoformat() if faq.created_at else None,
        }
        for faq in faqs
    ]


# ---------------------------------------------------------------------------
# Endpoint 8: PUT /api/whatsapp/pending/{faq_id}
# ---------------------------------------------------------------------------

@router.put(
    "/whatsapp/pending/{faq_id}",
    summary="Edit Data FAQ Pending",
    response_description="Data FAQ hasil perbaruan",
)
async def update_pending_faq(
    faq_id: int,
    payload: FAQUpdateSchema,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Mengubah konten (pertanyaan, jawaban, atau kategori) dari item FAQ pending.
    """
    result = await db.execute(
        select(WhatsAppFAQ).where(WhatsAppFAQ.id == faq_id)
    )
    faq = result.scalar_one_or_none()
    if not faq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"FAQ dengan ID {faq_id} tidak ditemukan.",
        )

    faq.question = payload.question.strip()
    faq.answer = payload.answer.strip()
    if payload.category:
        faq.category = payload.category.strip()

    await db.commit()
    await db.refresh(faq)

    return {
        "status": "success",
        "message": "FAQ berhasil diperbarui.",
        "faq": {
            "id": faq.id,
            "question": faq.question,
            "answer": faq.answer,
            "category": faq.category,
        },
    }


# ---------------------------------------------------------------------------
# Endpoint 9: DELETE /api/whatsapp/pending/{faq_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/whatsapp/pending/{faq_id}",
    summary="Tolak/Hapus FAQ",
    response_description="Status penghapusan",
)
async def delete_pending_faq(
    faq_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Menolak/menghapus item FAQ dari staging review.
    Jika FAQ sudah pernah di-approve (di ChromaDB), kita juga menghapus dari ChromaDB.
    """
    result = await db.execute(
        select(WhatsAppFAQ).where(WhatsAppFAQ.id == faq_id)
    )
    faq = result.scalar_one_or_none()
    if not faq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"FAQ dengan ID {faq_id} tidak ditemukan.",
        )

    # Jika berstatus approved, hapus juga dari ChromaDB
    if faq.status == "approved":
        try:
            def sync_delete_faq(fid: int):
                from langchain_chroma import Chroma
                from backend.rag.ingestion import get_embeddings, CHROMA_PERSIST_DIR
                
                embeddings = get_embeddings()
                vector_store = Chroma(
                    persist_directory=CHROMA_PERSIST_DIR,
                    embedding_function=embeddings,
                    collection_name="icicos_sop",
                )
                vector_store.delete(where={"faq_id": fid})

            logger.info(f"[Delete FAQ] Menghapus FAQ ID={faq_id} dari ChromaDB...")
            await asyncio.to_thread(sync_delete_faq, faq_id)
        except Exception as chroma_exc:
            logger.error(f"[Delete FAQ] Gagal menghapus FAQ ID={faq_id} dari Chroma: {chroma_exc}", exc_info=True)

    await db.delete(faq)
    await db.commit()

    return {
        "status": "success",
        "message": f"FAQ ID {faq_id} berhasil dihapus dari sistem.",
        "faq_id": faq_id,
    }


# ---------------------------------------------------------------------------
# Endpoint 10: POST /api/whatsapp/pending/{faq_id}/approve
# ---------------------------------------------------------------------------

@router.post(
    "/whatsapp/pending/{faq_id}/approve",
    summary="Approve FAQ Tunggal ke ChromaDB",
    response_description="Status persetujuan dan ingesti",
)
async def approve_single_faq(
    faq_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Menyetujui item FAQ pending, menyimpannya ke ChromaDB (RAG),
    dan mengubah status di database menjadi 'approved'.
    """
    result = await db.execute(
        select(WhatsAppFAQ).where(WhatsAppFAQ.id == faq_id)
    )
    faq = result.scalar_one_or_none()
    if not faq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"FAQ dengan ID {faq_id} tidak ditemukan.",
        )

    if faq.status == "approved":
        return {
            "status": "success",
            "message": "FAQ ini sudah disetujui sebelumnya.",
            "faq_id": faq_id,
        }

    # 1. Ingest ke ChromaDB
    try:
        def sync_embed_faq(fid: int, q: str, a: str, src: str, cat: str):
            from langchain_chroma import Chroma
            from langchain_core.documents import Document
            from backend.rag.ingestion import get_embeddings, CHROMA_PERSIST_DIR
            
            content = f"Pertanyaan: {q}\nJawaban: {a}"
            doc = Document(
                page_content=content,
                metadata={
                    "source": src,
                    "faq_id": fid,
                    "type": "whatsapp_faq",
                    "category": cat,
                    "ingestion_method": "whatsapp_distillation"
                }
            )
            embeddings = get_embeddings()
            Chroma.from_documents(
                documents=[doc],
                embedding=embeddings,
                persist_directory=CHROMA_PERSIST_DIR,
                collection_name="icicos_faq"  # ✅ Koleksi terpisah dari SOP
            )

        logger.info(f"[Approve FAQ] Memulai ingesti FAQ ID={faq_id} ke ChromaDB...")
        await asyncio.to_thread(sync_embed_faq, faq.id, faq.question, faq.answer, faq.source_file, faq.category)
        logger.info(f"[Approve FAQ] FAQ ID={faq_id} berhasil di-ingest.")
    except Exception as chroma_exc:
        logger.error(f"[Approve FAQ] Gagal melakukan ingesti ke ChromaDB untuk FAQ ID={faq_id}: {chroma_exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal melakukan ingesti RAG: {str(chroma_exc)}",
        )

    # 2. Update status di database
    import datetime
    faq.status = "approved"
    faq.approved_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()

    return {
        "status": "success",
        "message": f"FAQ '{faq.question[:30]}...' berhasil disetujui dan masuk ke database RAG.",
        "faq_id": faq_id,
    }


# ---------------------------------------------------------------------------
# Endpoint 11: POST /api/whatsapp/approve-all
# ---------------------------------------------------------------------------

@router.post(
    "/whatsapp/approve-all",
    summary="Approve Semua FAQ Pending Secara Masal",
    response_description="Jumlah FAQ yang berhasil disetujui",
)
async def approve_all_faqs(
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Menyetujui seluruh item FAQ berstatus 'pending', melakukan ingesti masal
    ke ChromaDB, dan menandai semuanya sebagai 'approved'.
    """
    result = await db.execute(
        select(WhatsAppFAQ).where(WhatsAppFAQ.status == "pending")
    )
    pending_faqs = result.scalars().all()

    if not pending_faqs:
        return {
            "status": "success",
            "message": "Tidak ada FAQ pending untuk disetujui.",
            "total_approved": 0,
        }

    # Persiapkan list data untuk dikirim ke ChromaDB secara efisien
    faqs_data = [
        {
            "id": faq.id,
            "question": faq.question,
            "answer": faq.answer,
            "category": faq.category,
            "source_file": faq.source_file,
        }
        for faq in pending_faqs
    ]

    # 1. Ingest bulk ke ChromaDB
    try:
        def sync_embed_faqs_bulk(items: List[Dict[str, Any]]):
            from langchain_chroma import Chroma
            from langchain_core.documents import Document
            from backend.rag.ingestion import get_embeddings, CHROMA_PERSIST_DIR
            
            docs = [
                Document(
                    page_content=f"Pertanyaan: {item['question']}\nJawaban: {item['answer']}",
                    metadata={
                        "source": item['source_file'],
                        "faq_id": item['id'],
                        "type": "whatsapp_faq",
                        "category": item['category'],
                        "ingestion_method": "whatsapp_distillation"
                    }
                )
                for item in items
            ]
            
            embeddings = get_embeddings()
            Chroma.from_documents(
                documents=docs,
                embedding=embeddings,
                persist_directory=CHROMA_PERSIST_DIR,
                collection_name="icicos_faq"  # ✅ Koleksi terpisah dari SOP
            )

        logger.info(f"[Approve FAQ Bulk] Memulai ingesti {len(faqs_data)} FAQ ke ChromaDB...")
        await asyncio.to_thread(sync_embed_faqs_bulk, faqs_data)
        logger.info("[Approve FAQ Bulk] Seluruh FAQ berhasil di-ingest.")
    except Exception as chroma_exc:
        logger.error(f"[Approve FAQ Bulk] Gagal melakukan ingesti masal ke ChromaDB: {chroma_exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal melakukan ingesti RAG masal: {str(chroma_exc)}",
        )

    # 2. Update status semua di database
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    for faq in pending_faqs:
        faq.status = "approved"
        faq.approved_at = now

    await db.commit()

    return {
        "status": "success",
        "message": f"Berhasil menyetujui dan meng-ingest {len(pending_faqs)} FAQ ke database RAG.",
        "total_approved": len(pending_faqs),
    }


# ---------------------------------------------------------------------------
# Endpoint 12: POST /api/knowledge/reset
# ---------------------------------------------------------------------------

@router.post(
    "/knowledge/reset",
    summary="Reset Entire Knowledge Base",
    response_description="Status of the full knowledge base wipe",
)
async def reset_knowledge_base(
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Performs a full reset of the RAG knowledge base:
      1. Wipes the ChromaDB 'icicos_sop' collection (all embeddings).
      2. Deletes all WhatsAppFAQ records from PostgreSQL (all statuses).
      3. Deletes all Document records from PostgreSQL.

    This is a destructive, irreversible operation intended for use before
    re-ingesting all SOP documents with the updated (English) ingestion pipeline.
    """
    # 1. Wipe ChromaDB collection
    try:
        def sync_clear_chroma():
            from backend.rag.ingestion import clear_knowledge_base
            clear_knowledge_base()

        logger.info("[Reset] Starting ChromaDB collection wipe...")
        await asyncio.to_thread(sync_clear_chroma)
        logger.info("[Reset] ChromaDB collection wiped successfully.")
    except Exception as chroma_exc:
        logger.error(f"[Reset] Failed to wipe ChromaDB: {chroma_exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to wipe ChromaDB: {str(chroma_exc)}",
        )

    # 2. Wipe LocalFileStore (Parent Document Store — new in Agentic RAG)
    try:
        import os
        from backend.rag.ingestion import PARENT_STORE_DIR
        parent_store_path = Path(PARENT_STORE_DIR)
        if parent_store_path.exists():
            shutil.rmtree(parent_store_path)
            logger.info(f"[Reset] Parent store directory '{PARENT_STORE_DIR}' wiped successfully.")
        else:
            logger.info("[Reset] Parent store directory does not exist yet — skipping.")
    except Exception as store_exc:
        logger.warning(f"[Reset] Failed to wipe parent store: {store_exc}. Continuing...")

    # 3. Delete all WhatsAppFAQ records
    try:
        from sqlalchemy import delete as sa_delete
        await db.execute(sa_delete(WhatsAppFAQ))
        logger.info("[Reset] All WhatsAppFAQ records deleted from PostgreSQL.")
    except Exception as faq_exc:
        logger.error(f"[Reset] Failed to delete WhatsAppFAQ records: {faq_exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ChromaDB wiped, but failed to delete FAQ records: {str(faq_exc)}",
        )

    # 4. Delete all Document records and commit
    try:
        from sqlalchemy import delete as sa_delete
        await db.execute(sa_delete(Document))
        await db.commit()
        logger.info("[Reset] All Document records deleted from PostgreSQL.")
    except Exception as doc_exc:
        logger.error(f"[Reset] Failed to delete Document records: {doc_exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ChromaDB & FAQs wiped, but failed to delete Document records: {str(doc_exc)}",
        )

    logger.info("[Reset] ✅ Full knowledge base reset complete.")
    return {
        "status": "success",
        "message": (
            "Knowledge base has been fully reset. ChromaDB collection, parent document store, "
            "and all document/FAQ records deleted from the database. You may now re-ingest documents."
        ),
    }



