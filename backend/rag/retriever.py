"""
retriever.py - Modul Retrieval: pencarian dokumen terisolasi per tipe (SOP & FAQ).

Arsitektur Baru (Bulletproof Agentic RAG):
  - retrieve_sop()  : Gunakan ParentDocumentRetriever → kembalikan PRIMARY doc + OTHER relevant SOPs
                      Primary doc = rank-1 terbaik, other_sops = daftar dokumen relevan lainnya.
  - retrieve_faq()  : Pencarian vektor standar di koleksi FAQ (histori WhatsApp)
                      Top-K=4, mengembalikan beberapa chunk FAQ yang relevan.
  - get_parent_document_by_filename() : Ambil dokumen dari local store via nama file (instant, no vector search).
"""
import logging
import os
from typing import Dict, List, Optional, Tuple

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


def get_parent_document_by_filename(filename: str) -> Optional[Document]:
    """
    Mengambil dokumen SOP utuh secara INSTAN menggunakan nama file sebagai key.

    Digunakan ketika user mengklik tombol rekomendasi SOP lain sehingga tidak
    perlu menjalankan pencarian vektor ulang (zero latency retrieval).

    Args:
        filename: Nama file SOP (e.g. 'SOP-Virtual-Account.pdf').

    Returns:
        Document jika ditemukan, None jika tidak ada.
    """
    try:
        raw_store = LocalFileStore(PARENT_STORE_DIR)
        docstore = create_kv_docstore(raw_store)
        doc = docstore.mget([filename])
        if doc and doc[0] is not None:
            logger.info(f"[Retriever-Filename] ✅ Dokumen '{filename}' ditemukan di docstore.")
            return doc[0]
        logger.warning(f"[Retriever-Filename] Dokumen '{filename}' tidak ada di docstore.")
        return None
    except Exception as e:
        logger.error(f"[Retriever-Filename] Error saat mengambil dokumen '{filename}': {e}", exc_info=True)
        return None


def retrieve_sop(query: str, threshold: Optional[float] = None) -> Tuple[Optional[Document], float, List[Dict]]:
    """
    Mengambil dokumen SOP menggunakan ParentDocumentRetriever.

    Mengembalikan:
      - primary_doc   : Parent document terbaik (rank-1) berdasarkan score tertinggi.
      - primary_score : Similarity score tertinggi dari child chunk manapun.
      - other_sops    : List dict dokumen SOP relevan lainnya (skor >= threshold),
                        format: [{"filename": "SOP-VA.pdf", "score": 0.74}, ...].

    Jaminan: primary_doc selalu merupakan satu dokumen SOP yang UTUH.
    other_sops tidak mengandung dokumen yang sama dengan primary_doc.
    """
    logger.info(f"[Retriever-SOP] Mencari SOP untuk query: '{query[:60]}'")

    active_threshold = threshold if threshold is not None else SIMILARITY_THRESHOLD
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

        # Ambil top-K child chunks dengan skor (k=10 agar bisa deteksi beberapa SOP)
        results_with_scores = vectorstore.similarity_search_with_relevance_scores(
            query, k=10
        )

        if not results_with_scores:
            logger.warning("[Retriever-SOP] Tidak ada child chunk yang cocok.")
            return None, 0.0, []

        # --- Kelompokkan skor tertinggi per source (nama file) ---
        # Setiap child chunk memiliki metadata["source"] = nama file PDF asalnya.
        best_score_per_source: Dict[str, float] = {}
        for chunk_doc, score in results_with_scores:
            source = chunk_doc.metadata.get("source", "unknown")
            if source not in best_score_per_source or score > best_score_per_source[source]:
                best_score_per_source[source] = score

        # Filter hanya yang memenuhi threshold
        relevant_sources = {
            src: sc for src, sc in best_score_per_source.items()
            if sc >= active_threshold
        }

        if not relevant_sources:
            best_global_score = max(best_score_per_source.values()) if best_score_per_source else 0.0
            logger.warning(
                f"[Retriever-SOP] Tidak ada source yang melebihi threshold {active_threshold}. "
                f"Skor tertinggi: {best_global_score:.4f}"
            )
            return None, best_global_score, []

        # Urutkan berdasarkan skor tertinggi → primary doc = rank-1
        sorted_sources = sorted(relevant_sources.items(), key=lambda x: x[1], reverse=True)
        primary_filename, primary_score = sorted_sources[0]

        logger.info(
            f"[Retriever-SOP] Primary: '{primary_filename}' (score={primary_score:.4f}). "
            f"Total relevant sources: {len(sorted_sources)}"
        )

        # Ambil parent document untuk primary filename
        primary_doc_list = docstore.mget([primary_filename])
        if not primary_doc_list or primary_doc_list[0] is None:
            logger.warning(f"[Retriever-SOP] Parent doc untuk '{primary_filename}' tidak ada di store. Fallback ke retriever.")
            parent_docs = parent_retriever.invoke(query)
            primary_doc = parent_docs[0] if parent_docs else None
        else:
            primary_doc = primary_doc_list[0]

        if primary_doc is None:
            logger.warning("[Retriever-SOP] Primary parent document tidak dapat ditemukan.")
            return None, primary_score, []

        logger.info(
            f"[Retriever-SOP] ✅ Primary SOP: '{primary_filename}' "
            f"({len(primary_doc.page_content):,} karakter)"
        )

        # Build other_sops list (semua relevan selain primary)
        other_sops = [
            {"filename": src, "score": sc}
            for src, sc in sorted_sources[1:]  # Skip rank-1
        ]

        if other_sops:
            logger.info(
                f"[Retriever-SOP] Other SOPs ditemukan: "
                f"{[o['filename'] for o in other_sops]}"
            )

        return primary_doc, primary_score, other_sops

    except Exception as e:
        logger.error(f"[Retriever-SOP] Error saat retrieval: {e}", exc_info=True)
        return None, 0.0, []


def retrieve_faq(query: str, threshold: Optional[float] = None) -> Tuple[List[Document], float]:
    """
    Mengambil beberapa FAQ chunk yang relevan dari ChromaDB (collection: icicos_faq).
    Menggunakan pencarian vektor standar dengan Top-K=4.

    Returns:
        Tuple berisi:
        - List[Document]: chunk FAQ yang relevan (bisa lebih dari satu)
        - float: skor similarity tertinggi
    """
    logger.info(f"[Retriever-FAQ] Mencari FAQ untuk query: '{query[:60]}'")

    active_threshold = threshold if threshold is not None else SIMILARITY_THRESHOLD
    try:
        vectorstore = _get_faq_vectorstore()
        results_with_scores = vectorstore.similarity_search_with_relevance_scores(
            query, k=4
        )

        if not results_with_scores:
            logger.warning("[Retriever-FAQ] Tidak ada FAQ yang cocok.")
            return [], 0.0

        # Filter by active_threshold
        relevant_results = [(doc, score) for doc, score in results_with_scores if score >= active_threshold]
        if not relevant_results:
            best_global_score = max(score for _, score in results_with_scores)
            logger.warning(f"[Retriever-FAQ] Tidak ada FAQ melebihi threshold {active_threshold}. Skor tertinggi: {best_global_score:.4f}")
            return [], best_global_score

        docs = [doc for doc, _ in relevant_results]
        best_score = max(score for _, score in relevant_results)
        logger.info(f"[Retriever-FAQ] Ditemukan {len(docs)} FAQ chunk. Skor: {best_score:.4f}")
        return docs, best_score

    except Exception as e:
        logger.error(f"[Retriever-FAQ] Error saat retrieval: {e}", exc_info=True)
        return [], 0.0
