"""
chain.py - RAG Chain: orkestrasi utama pipeline Retrieve → Generate.
Fungsi ini yang dipanggil oleh bot handler untuk menjawab query user.

Catatan arsitektur:
  retrieve_context() dan generate_answer() keduanya bersifat sinkron (blocking)
  karena memanggil model HuggingFace lokal dan HTTP request ke LLM provider.
  Keduanya dibungkus asyncio.to_thread() agar tidak memblokir event loop
  python-telegram-bot yang berjalan di thread yang sama.

Return value:
  Tuple[str, float] — (jawaban, similarity_score)
  score = 0.0 jika fallback dipicu (tidak ada dokumen relevan).
  Score ini diekspos ke caller (handler) untuk keperluan logging ke database.
"""
import asyncio
import logging
from functools import partial
from typing import Tuple

from backend.rag.generator import FALLBACK_RESPONSE, generate_answer
from backend.rag.retriever import SIMILARITY_THRESHOLD, retrieve_context

logger = logging.getLogger(__name__)


async def run_rag_chain(query: str) -> Tuple[str, float]:
    """
    Menjalankan pipeline RAG lengkap secara non-blocking (async-safe):
      1. Retrieve konteks dari ChromaDB (dijalankan di thread pool)
      2. Cek threshold similarity → fallback jika skor terlalu rendah
      3. Generate jawaban via LLM (dijalankan di thread pool)

    Menggunakan asyncio.to_thread() untuk fungsi-fungsi blocking agar
    event loop Telegram tidak terhenti selama proses berlangsung.

    Args:
        query: Pertanyaan teks dari user Telegram.

    Returns:
        Tuple[str, float]:
          - str  : Jawaban yang siap dikirim ke user.
          - float: Similarity score tertinggi dari retrieval.
                   Bernilai 0.0 jika tidak ada dokumen relevan (fallback).
    """
    logger.info(f"[Chain] Menjalankan RAG chain untuk query: '{query[:80]}'")

    # Langkah 1: Retrieve (blocking → dijalankan di thread terpisah)
    docs, best_score = await asyncio.to_thread(retrieve_context, query)

    # Langkah 2: Cek fallback (sesuai PROMPTS.md)
    if not docs or best_score < SIMILARITY_THRESHOLD:
        logger.warning(
            f"[Chain] Skor similarity terlalu rendah "
            f"({best_score:.4f} < {SIMILARITY_THRESHOLD}). "
            "Menggunakan fallback response."
        )
        # Kembalikan score aktual (bisa 0.0) untuk dicatat di database
        return FALLBACK_RESPONSE, best_score

    # Langkah 3: Generate (blocking → dijalankan di thread terpisah)
    # Menggunakan partial agar argumen docs bisa diteruskan ke to_thread
    answer = await asyncio.to_thread(partial(generate_answer, query, docs))

    logger.info(
        f"[Chain] ✅ RAG chain selesai. "
        f"Jawaban di-generate ({len(answer)} karakter), score={best_score:.4f}."
    )
    return answer, best_score
