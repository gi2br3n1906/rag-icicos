"""
retriever.py - Modul Retrieval: pencarian dokumen terisolasi per tipe (SOP & FAQ).

Arsitektur Baru (Bulletproof Agentic RAG):
  - retrieve_sop()  : Gunakan ParentDocumentRetriever → Top-K=1 → kembalikan 1 SOP UTUH
                      Menjamin SOP tidak pernah bolong atau tercampur dengan SOP lain.
  - retrieve_faq()  : Pencarian vektor standar di koleksi FAQ (histori WhatsApp)
                      Top-K=4, mengembalikan beberapa chunk FAQ yang relevan.
"""
import logging
import os
from typing import List, Optional, Tuple

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain.retrievers import ParentDocumentRetriever
from langchain.storage import LocalFileStore
from langchain.storage._lc_store import create_kv_docstore
from langchain.text_splitter import RecursiveCharacterTextSplitter

from backend.rag.ingestion import get_embeddings, CHUNK_SIZE, CHUNK_OVERLAP

logger = logging.getLogger(__name__)

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma_db")
PARENT_STORE_DIR = os.getenv("PARENT_STORE_DIR", "./data/parent_store")
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.4"))


def _get_sop_vectorstore() -> Chroma:
    """Koneksi ke ChromaDB collection SOP (berisi child chunks)."""
    return Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=get_embeddings(),
        collection_name="icicos_sop",
    )


def _get_faq_vectorstore() -> Chroma:
    """Koneksi ke ChromaDB collection FAQ (berisi chunk histori WhatsApp)."""
    return Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=get_embeddings(),
        collection_name="icicos_faq",
    )


def retrieve_sop(query: str) -> Tuple[Optional[Document], float]:
    """
    Mengambil SATU dokumen SOP utuh menggunakan ParentDocumentRetriever.

    Alur:
      1. Cari child chunk yang relevan di ChromaDB (collection: icicos_sop).
      2. Dari chunk terbaik, ambil kembali parent document utuh dari LocalFileStore.
      3. Return (parent_doc, best_score). Jika tidak ditemukan → (None, 0.0).

    Jaminan: Selalu mengembalikan maksimal 1 dokumen SOP yang UTUH.
    Tidak ada kemungkinan 2 SOP berbeda tercampur dalam satu query.
    """
    logger.info(f"[Retriever-SOP] Mencari SOP untuk query: '{query[:60]}'")

    try:
        vectorstore = _get_sop_vectorstore()
        raw_store = LocalFileStore(PARENT_STORE_DIR)
        docstore = create_kv_docstore(raw_store)
        
        child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        parent_retriever = ParentDocumentRetriever(
            vectorstore=vectorstore,
            docstore=docstore,
            child_splitter=child_splitter,
        )

        # Cari skor child chunk dahulu untuk validasi threshold
        results_with_scores = vectorstore.similarity_search_with_relevance_scores(
            query, k=1
        )

        if not results_with_scores:
            logger.warning("[Retriever-SOP] Tidak ada child chunk yang cocok.")
            return None, 0.0

        best_score = results_with_scores[0][1]
        logger.info(f"[Retriever-SOP] Skor child chunk terbaik: {best_score:.4f}")

        if best_score < SIMILARITY_THRESHOLD:
            logger.warning(
                f"[Retriever-SOP] Skor {best_score:.4f} di bawah threshold {SIMILARITY_THRESHOLD}. Tidak ada SOP relevan."
            )
            return None, best_score

        # Gunakan ParentDocumentRetriever untuk mendapatkan dokumen utuh
        parent_docs = parent_retriever.invoke(query)

        if not parent_docs:
            logger.warning("[Retriever-SOP] Parent document tidak ditemukan di store.")
            return None, best_score

        # Ambil hanya 1 parent document teratas
        parent_doc = parent_docs[0]
        logger.info(
            f"[Retriever-SOP] ✅ Parent SOP ditemukan: '{parent_doc.metadata.get('source', '?')}' "
            f"({len(parent_doc.page_content):,} karakter)"
        )
        return parent_doc, best_score

    except Exception as e:
        if "ValidationError" in type(e).__name__ or "validation error" in str(e).lower():
            logger.error(
                "[Retriever-SOP] 🚨 CRITICAL: Database corruption detected in ChromaDB! "
                "Some documents in the 'icicos_sop' collection have null page content. "
                "To fix this, please run 'python poc_rag.py --reset' and re-ingest your documents, "
                "or trigger the POST /api/knowledge/reset endpoint. "
                f"Original error: {e}",
                exc_info=True
            )
        else:
            logger.error(f"[Retriever-SOP] Error saat retrieval: {e}", exc_info=True)
        return None, 0.0


def retrieve_faq(query: str) -> Tuple[List[Document], float]:
    """
    Mengambil beberapa FAQ chunk yang relevan dari ChromaDB (collection: icicos_faq).
    Menggunakan pencarian vektor standar dengan Top-K=4.

    Returns:
        Tuple berisi:
        - List[Document]: chunk FAQ yang relevan (bisa lebih dari satu)
        - float: skor similarity tertinggi
    """
    logger.info(f"[Retriever-FAQ] Mencari FAQ untuk query: '{query[:60]}'")

    try:
        vectorstore = _get_faq_vectorstore()
        results_with_scores = vectorstore.similarity_search_with_relevance_scores(
            query, k=4
        )

        if not results_with_scores:
            logger.warning("[Retriever-FAQ] Tidak ada FAQ yang cocok.")
            return [], 0.0

        docs = [doc for doc, _ in results_with_scores]
        best_score = max(score for _, score in results_with_scores)
        logger.info(f"[Retriever-FAQ] Ditemukan {len(docs)} FAQ chunk. Skor: {best_score:.4f}")
        return docs, best_score

    except Exception as e:
        if "ValidationError" in type(e).__name__ or "validation error" in str(e).lower():
            logger.error(
                "[Retriever-FAQ] 🚨 CRITICAL: Database corruption detected in ChromaDB! "
                "Some documents in the 'icicos_faq' collection have null page content. "
                "To fix this, please run 'python poc_rag.py --reset' and re-ingest your documents, "
                "or trigger the POST /api/knowledge/reset endpoint. "
                f"Original error: {e}",
                exc_info=True
            )
        else:
            logger.error(f"[Retriever-FAQ] Error saat retrieval: {e}", exc_info=True)
        return [], 0.0
