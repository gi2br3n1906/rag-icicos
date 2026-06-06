"""
retriever.py - Modul Retrieval: mencari chunk dokumen yang relevan dari ChromaDB.
Menggunakan similarity search untuk menemukan konteks terbaik untuk query user.
"""
import logging
import os
from typing import List, Tuple

from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

from backend.rag.ingestion import get_embeddings

logger = logging.getLogger(__name__)

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma_db")
TOP_K_RESULTS = int(os.getenv("RETRIEVER_TOP_K", "4"))
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.4"))


def get_vectorstore() -> Chroma:
    """Membuka koneksi ke ChromaDB yang sudah ada."""
    embeddings = get_embeddings()
    return Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=embeddings,
        collection_name="icicos_sop",
    )


def retrieve_context(query: str) -> Tuple[List[Document], float]:
    """
    Mengambil dokumen yang relevan dari ChromaDB berdasarkan query.

    Returns:
        Tuple berisi:
        - List[Document]: chunk dokumen yang relevan
        - float: skor similarity tertinggi (untuk menentukan apakah perlu fallback)
    """
    vectorstore = get_vectorstore()
    logger.info(f"Mencari konteks untuk query: '{query[:60]}...'")

    # Similarity search dengan skor untuk menentukan threshold fallback
    results_with_scores: List[Tuple[Document, float]] = (
        vectorstore.similarity_search_with_relevance_scores(query, k=TOP_K_RESULTS)
    )

    if not results_with_scores:
        logger.warning("Tidak ditemukan dokumen relevan di ChromaDB.")
        return [], 0.0

    docs = [doc for doc, _ in results_with_scores]
    best_score = max(score for _, score in results_with_scores)

    logger.info(
        f"Ditemukan {len(docs)} chunk relevan. Skor tertinggi: {best_score:.4f}"
    )
    return docs, best_score
