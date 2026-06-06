"""
poc_rag.py - Script Proof-of-Concept Fase 1
Mendemonstrasikan pipeline RAG end-to-end secara sederhana:
  1. Baca 1 file PDF SOP
  2. Chunking
  3. Embed + simpan ke ChromaDB
  4. Query dengan pertanyaan contoh
  5. Generate jawaban via LLM

Cara penggunaan:
  # Jalankan pipeline PoC penuh:
  python poc_rag.py <path_ke_file_pdf_sop>

  # Reset (wipe) seluruh knowledge base ChromaDB:
  python poc_rag.py --reset
"""

import os
import ssl

# Memaksa Python mengabaikan verifikasi SSL lokal yang korup (khusus untuk testing lokal)
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

    
import logging
import sys
from pathlib import Path

import argparse

from dotenv import load_dotenv

# Muat .env sebelum import modul lain
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    # --- Parsing argumen CLI ---
    parser = argparse.ArgumentParser(
        description="ICICoS 2026 RAG Bot - Proof-of-Concept CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Contoh:\n"
            "  python poc_rag.py ./data/docs/sop_pembayaran.pdf  # Jalankan pipeline PoC\n"
            "  python poc_rag.py --reset                         # Wipe ChromaDB collection"
        ),
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",           # Opsional jika --reset dipakai
        help="Path ke file PDF SOP yang akan di-ingest.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Hapus (wipe) seluruh isi ChromaDB knowledge base, lalu keluar.",
    )
    args = parser.parse_args()

    # --- Handler: --reset flag ---
    if args.reset:
        print("=" * 60)
        print("  [!] RESET KNOWLEDGE BASE")
        print("=" * 60)
        print("\n[*] Menghapus seluruh embedding dari ChromaDB...")
        from rag.ingestion import clear_knowledge_base
        clear_knowledge_base()
        print("\n[OK] ChromaDB collection berhasil di-wipe bersih.")
        print("     Jalankan pipeline ingesti ulang untuk mengisi knowledge base.")
        sys.exit(0)

    # --- Validasi: pdf_path wajib jika bukan --reset ---
    if not args.pdf_path:
        parser.error(
            "Argumen 'pdf_path' wajib diisi jika tidak menggunakan flag --reset.\n"
            "  Contoh: python poc_rag.py ./data/docs/sop_pembayaran.pdf"
        )

    pdf_path = args.pdf_path

    print("=" * 60)
    print("  ICICoS 2026 RAG Bot - Fase 1 Proof-of-Concept")
    print("=" * 60)

    # --- LANGKAH 1: Ingesti Dokumen ---
    print(f"\n[1/3] Meng-ingest dokumen: {pdf_path}")
    from rag.ingestion import ingest_document, EXTRACTED_TEXT_DIR
    from pathlib import Path
    total_chunks = ingest_document(pdf_path)
    print(f"[OK] Berhasil: {total_chunks} chunk tersimpan di ChromaDB.")
    # Tunjukkan lokasi file hasil ekstraksi
    stem = Path(pdf_path).stem.replace(" ", "_")
    extracted_path = Path(EXTRACTED_TEXT_DIR) / f"{stem}_extracted.txt"
    if extracted_path.exists():
        print(f"[OK] Teks ekstraksi Gemini disimpan di: {extracted_path.resolve()}\n")

    # --- LANGKAH 2: Retrieve ---
    test_query = "Bagaimana cara melakukan registrasi ICICoS 2026?"
    print(f"[2/3] Test Retrieval untuk query:\n   '{test_query}'")
    from rag.retriever import retrieve_context
    docs, score = retrieve_context(test_query)
    print(f"[OK] Ditemukan {len(docs)} chunk relevan. Skor tertinggi: {score:.4f}\n")

    if docs:
        print("--- Contoh chunk pertama yang ditemukan ---")
        print(docs[0].page_content[:300] + "...")
        print("-" * 40)

    # --- LANGKAH 3: Generate ---
    print(f"\n[3/3] Generating jawaban via LLM...")
    if not docs or score < 0.4:
        print("[!] Skor rendah - menggunakan Fallback Response.")
        from rag.generator import FALLBACK_RESPONSE
        answer = FALLBACK_RESPONSE
    else:
        from rag.generator import generate_answer
        answer = generate_answer(test_query, docs)

    print("\n" + "=" * 60)
    print("  JAWABAN BOT:")
    print("=" * 60)
    print(answer)
    print("=" * 60)
    print("\n[OK] PoC Fase 1 selesai! Pipeline RAG berjalan dengan baik.")


if __name__ == "__main__":
    main()
