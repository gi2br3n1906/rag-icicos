"""
ingestion.py - Pipeline ingesti dokumen PDF ke dalam ChromaDB.

Alur kerja baru (LLM-Assisted Ingestion Layer):
  PDF visual (BPMN/Flowchart)
    ↓ [1] upload ke Google Gemini 1.5 Flash (multimodal)
    ↓ [2] Gemini mengembalikan teks naratif terstruktur
    ↓ [3] RecursiveCharacterTextSplitter memotong teks
    ↓ [4] HuggingFace Embedding (multilingual-e5-small)
    ↓ [5] Simpan ke ChromaDB lokal

Fungsi utilitas:
  clear_knowledge_base() → Menghapus seluruh isi ChromaDB collection (reset).

Latar belakang: PDF SOP ICICoS berupa diagram BPMN visual hasil ekspor Bizagi
Modeler. PDF Loader standar tidak dapat membaca urutan alur diagram secara
benar (teks acak-acakan). Gemini 1.5 Flash digunakan sebagai "penerjemah"
multimodal sebelum proses chunking.
"""

import logging
import os
import time
from pathlib import Path
from typing import List

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfigurasi Embedding
# ---------------------------------------------------------------------------
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"  # 768 dim — upgraded dari e5-small (384 dim)
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma_db")
EXTRACTED_TEXT_DIR = os.getenv("EXTRACTED_TEXT_DIR", "./data/extracted_text")

# ---------------------------------------------------------------------------
# Konfigurasi Chunking
# ---------------------------------------------------------------------------
CHUNK_SIZE = 512    # Ukuran chunk dalam karakter (sesuai permintaan)
CHUNK_OVERLAP = 50  # Overlap antar chunk untuk menjaga konteks antar-batas

# ---------------------------------------------------------------------------
# Prompt instruksi untuk Gemini (LLM-Assisted Ingestion)
# ---------------------------------------------------------------------------
GEMINI_CONVERSION_PROMPT = (
    "Kamu adalah pakar analis proses bisnis untuk konferensi ICICoS 2026. "
    "Perhatikan dokumen diagram BPMN/Flowchart ini dengan teliti. "
    "Tugasmu adalah mengubah seluruh diagram alir visual yang ada di dokumen ini "
    "menjadi bentuk teks naratif terstruktur yang linier. "
    "Sebutkan nama SOP, aktor yang terlibat, urutan langkahnya secara jelas "
    "dari awal sampai akhir, serta aturan bisnis atau batas waktu (SLA/Deadline) "
    "jika tertera di dalam diagram."
)


# ===========================================================================
# 1b. Helper: Simpan Teks Hasil Ekstraksi ke File untuk Review
# ===========================================================================

def save_extracted_text(source_pdf_name: str, text: str) -> Path:
    """
    Menyimpan teks naratif hasil konversi Gemini ke file .txt di folder
    EXTRACTED_TEXT_DIR agar bisa direview secara manual.

    Nama file output: <nama_pdf_tanpa_ekstensi>_extracted.txt
    Folder output   : ./data/extracted_text/ (bisa diubah via EXTRACTED_TEXT_DIR)

    Args:
        source_pdf_name: Nama file PDF asal (e.g. 'SOP-Bendahara.pdf').
        text           : Teks naratif hasil konversi Gemini.

    Returns:
        Path objek ke file .txt yang disimpan.
    """
    import datetime

    out_dir = Path(EXTRACTED_TEXT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Buat nama file: ganti spasi dengan underscore, buang ekstensi .pdf
    stem = Path(source_pdf_name).stem.replace(" ", "_")
    out_path = out_dir / f"{stem}_extracted.txt"

    # Header metadata agar mudah diidentifikasi saat review
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = (
        f"{'=' * 60}\n"
        f"  HASIL EKSTRAKSI GEMINI\n"
        f"  Sumber : {source_pdf_name}\n"
        f"  Waktu  : {timestamp}\n"
        f"  Panjang: {len(text):,} karakter\n"
        f"{'=' * 60}\n\n"
    )

    out_path.write_text(header + text, encoding="utf-8")
    logger.info(
        f"[Ekstraksi] ✅ Teks naratif disimpan ke: '{out_path}' "
        f"({len(text):,} karakter)"
    )
    return out_path


# ===========================================================================
# 1. Helper: Embedding Model
# ===========================================================================

def get_embeddings() -> HuggingFaceEmbeddings:
    """Menginisialisasi model embedding HuggingFace secara lokal (CPU)."""
    logger.info(f"Memuat embedding model lokal: {EMBEDDING_MODEL_NAME}")
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


# ===========================================================================
# 2. LLM-Assisted Layer: Konversi PDF Visual → Teks Naratif via Gemini
# ===========================================================================

def convert_pdf_to_structured_text(pdf_path: str) -> str:
    """
    Mengkonversi PDF berisi diagram BPMN/Flowchart visual menjadi teks
    naratif terstruktur menggunakan Google Gemini 1.5 Flash (multimodal).

    Alur:
      1. Validasi API key dan keberadaan file.
      2. Upload file PDF ke server Google Gemini.
      3. Tunggu file siap diproses (status ACTIVE).
      4. Kirim file + prompt instruksi ke model Gemini.
      5. Ekstrak teks dari respons.
      6. Hapus file dari server Gemini (menjaga privasi data).
      7. Kembalikan teks naratif murni.

    Args:
        pdf_path: Path absolut atau relatif ke file PDF.

    Returns:
        String teks naratif terstruktur hasil interpretasi Gemini.

    Raises:
        ValueError: Jika GEMINI_API_KEY tidak ditemukan di environment.
        FileNotFoundError: Jika file PDF tidak ditemukan di path yang diberikan.
        RuntimeError: Jika Gemini gagal memproses file.
    """
    # --- Lazy import: hanya diinisialisasi saat fungsi ini dipanggil ---
    import google.generativeai as genai  # noqa: PLC0415

    # [VALIDASI 1] Pastikan API key tersedia sebelum proses dimulai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY tidak ditemukan di environment variables. "
            "Pastikan file .env sudah dikonfigurasi dengan benar."
        )

    # [VALIDASI 2] Pastikan file PDF ada di disk
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"File PDF tidak ditemukan: {pdf_path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(
            f"LLM-Assisted Ingestion hanya mendukung format PDF. "
            f"File yang diberikan: '{path.suffix}'"
        )

    # Inisialisasi klien Gemini
    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODELS", "gemini-3.1-pro-preview")

    uploaded_file = None  # Referensi untuk blok finally (cleanup)

    try:
        # [LANGKAH 1] Upload file PDF ke server Google Gemini
        logger.info(
            f"[Gemini Upload] Mengunggah '{path.name}' ke server Google Gemini..."
        )
        uploaded_file = genai.upload_file(
            path=str(path),
            mime_type="application/pdf",
            display_name=path.name,
        )
        logger.info(
            f"[Gemini Upload] Berhasil. URI file: {uploaded_file.uri} | "
            f"Status awal: {uploaded_file.state.name}"
        )

        # [LANGKAH 2] Tunggu hingga file ACTIVE (Gemini memerlukan waktu pemrosesan)
        logger.info("[Gemini Upload] Menunggu file siap diproses (status: ACTIVE)...")
        max_wait_seconds = 120  # Batas tunggu maksimum 2 menit
        elapsed = 0
        poll_interval = 5       # Cek status setiap 5 detik

        while uploaded_file.state.name == "PROCESSING":
            if elapsed >= max_wait_seconds:
                raise RuntimeError(
                    f"File '{path.name}' masih dalam status PROCESSING setelah "
                    f"{max_wait_seconds} detik. Proses dibatalkan."
                )
            time.sleep(poll_interval)
            elapsed += poll_interval
            uploaded_file = genai.get_file(uploaded_file.name)
            logger.info(
                f"[Gemini Upload] Status: {uploaded_file.state.name} "
                f"(sudah {elapsed}s / maks {max_wait_seconds}s)"
            )

        if uploaded_file.state.name != "ACTIVE":
            raise RuntimeError(
                f"File '{path.name}' gagal diproses oleh Gemini. "
                f"Status akhir: {uploaded_file.state.name}"
            )

        logger.info(f"[Gemini Upload] File AKTIF dan siap diinterpretasi.")

        # [LANGKAH 3] Kirim file + prompt instruksi ke model Gemini
        logger.info(
            f"[Gemini Generate] Mengirim file ke model '{model_name}' "
            f"untuk konversi diagram → teks naratif..."
        )
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(
            [uploaded_file, GEMINI_CONVERSION_PROMPT],
            generation_config=genai.GenerationConfig(
                temperature=0.1,    # Suhu rendah: prioritaskan akurasi faktual
                max_output_tokens=8192,
            ),
        )

        # [LANGKAH 4] Ekstrak teks dari respons
        structured_text = response.text.strip()
        char_count = len(structured_text)
        logger.info(
            f"[Gemini Generate] ✅ Teks naratif berhasil diterima. "
            f"Total karakter: {char_count:,}"
        )

        if char_count < 50:
            logger.warning(
                "[Gemini Generate] ⚠️ Teks yang diterima sangat pendek. "
                "Kemungkinan diagram tidak terbaca optimal oleh model."
            )

        return structured_text

    finally:
        # [LANGKAH 5] Hapus file dari server Gemini (privasi data)
        # Blok finally memastikan cleanup SELALU terjadi, bahkan jika ada error.
        if uploaded_file is not None:
            try:
                genai.delete_file(uploaded_file.name)
                logger.info(
                    f"[Gemini Cleanup] File '{path.name}' berhasil dihapus "
                    f"dari server Google Gemini."
                )
            except Exception as cleanup_error:
                # Log error tapi jangan re-raise; proses utama lebih prioritas
                logger.error(
                    f"[Gemini Cleanup] Gagal menghapus file dari server Gemini: "
                    f"{cleanup_error}"
                )


# ===========================================================================
# 3. Chunking: Teks Naratif → Daftar Document LangChain
# ===========================================================================

def chunk_text_to_documents(
    clean_text: str,
    source_filename: str,
) -> List[Document]:
    """
    Memotong teks naratif murni menjadi chunk-chunk kecil dan mengkonversinya
    menjadi objek Document LangChain dengan metadata dasar.

    Args:
        clean_text: Teks naratif hasil konversi Gemini.
        source_filename: Nama file asal (untuk metadata chunk).

    Returns:
        List objek Document siap di-embed dan disimpan ke ChromaDB.
    """
    logger.info(
        f"[Chunking] Memulai pemotongan teks. "
        f"chunk_size={CHUNK_SIZE}, chunk_overlap={CHUNK_OVERLAP}"
    )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    # split_text() mengembalikan List[str] karena inputnya adalah string murni
    text_chunks: List[str] = splitter.split_text(clean_text)

    # Konversi setiap string chunk menjadi objek Document dengan metadata
    documents: List[Document] = [
        Document(
            page_content=chunk,
            metadata={
                "source": source_filename,      # Nama file asal
                "chunk_index": idx,             # Urutan chunk dalam dokumen
                "ingestion_method": "gemini_llm_assisted",  # Penanda metode ingesti
            },
        )
        for idx, chunk in enumerate(text_chunks)
    ]

    logger.info(f"[Chunking] ✅ Teks dipotong menjadi {len(documents)} chunk.")
    return documents


# ===========================================================================
# 4. Fungsi Utama: Orkestrasi Full Pipeline Ingesti
# ===========================================================================

def ingest_document(pdf_path: str) -> int:
    """
    Pipeline ingesti lengkap (LLM-Assisted):
      PDF visual → Gemini 1.5 Flash → teks naratif
        → chunking → embedding → ChromaDB

    Args:
        pdf_path: Path ke file PDF SOP (bisa berupa diagram BPMN visual).

    Returns:
        Jumlah chunk yang berhasil disimpan ke ChromaDB.

    Raises:
        ValueError: Jika GEMINI_API_KEY tidak tersedia.
        FileNotFoundError: Jika file tidak ditemukan.
        RuntimeError: Jika Gemini gagal memproses file.
    """
    path = Path(pdf_path)
    logger.info(
        "=" * 60 + "\n"
        f"[Ingesti] Memulai pipeline LLM-Assisted untuk: '{path.name}'\n"
        + "=" * 60
    )

    # --- [TAHAP 1] Konversi PDF visual → teks naratif via Gemini ---
    logger.info("[Ingesti] TAHAP 1/3: Konversi diagram via Google Gemini 1.5 Flash")
    clean_text = convert_pdf_to_structured_text(pdf_path)

    # --- [TAHAP 1b] Simpan hasil ekstraksi ke .txt untuk review manual ---
    save_extracted_text(source_pdf_name=path.name, text=clean_text)

    # --- [TAHAP 2] Chunking teks → List[Document] ---
    logger.info("[Ingesti] TAHAP 2/3: Pemotongan teks menjadi chunk")
    documents = chunk_text_to_documents(
        clean_text=clean_text,
        source_filename=path.name,
    )

    if not documents:
        logger.error(
            "[Ingesti] ❌ Tidak ada chunk yang dihasilkan. "
            "Pastikan Gemini berhasil mengekstrak teks dari dokumen."
        )
        return 0

    # --- [TAHAP 3] Embedding + simpan ke ChromaDB ---
    logger.info(
        f"[Ingesti] TAHAP 3/3: Embedding {len(documents)} chunk "
        f"dan menyimpan ke ChromaDB di '{CHROMA_PERSIST_DIR}'"
    )
    embeddings = get_embeddings()

    Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=CHROMA_PERSIST_DIR,
        collection_name="icicos_sop",
    )

    total_chunks = len(documents)
    logger.info(
        "=" * 60 + "\n"
        f"[Ingesti] ✅ SELESAI. {total_chunks} chunk dari '{path.name}' "
        f"berhasil disimpan ke ChromaDB.\n"
        + "=" * 60
    )
    return total_chunks


# ===========================================================================
# 5. Utilitas: Reset Knowledge Base
# ===========================================================================

def clear_knowledge_base() -> None:
    """
    Menghapus seluruh isi ChromaDB collection ('icicos_sop').

    Fungsi ini berguna untuk mereset knowledge base sebelum proses ingesti
    ulang (re-ingest) semua dokumen SOP dari awal, menghindari duplikasi data
    embedding di dalam vector store.

    Catatan: Operasi ini bersifat destruktif dan tidak dapat di-undo.
    ChromaDB akan menghapus seluruh embedding, dokumen, dan metadata
    yang tersimpan di dalam collection 'icicos_sop'.
    """
    logger.info("[Reset] Memulai proses penghapusan ChromaDB collection 'icicos_sop'...")

    embeddings = get_embeddings()

    # Inisialisasi objek Chroma menggunakan persist directory dan model yang sama
    # agar terhubung ke collection yang benar sebelum dihapus.
    vector_store = Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=embeddings,
        collection_name="icicos_sop",
    )

    # Hapus seluruh isi collection (semua embedding, dokumen, metadata)
    vector_store.delete_collection()

    logger.info("ChromaDB collection berhasil di-wipe bersih.")


# ===========================================================================
# 6. Entry Point (Standalone PoC)
# ===========================================================================

if __name__ == "__main__":
    # Skrip standalone untuk testing ingesti langsung dari terminal:
    #   python ingestion.py <path_ke_pdf>
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    if len(sys.argv) < 2:
        print("Usage: python ingestion.py <path_to_pdf>")
        print("Contoh: python ingestion.py ./data/docs/sop_pembayaran.pdf")
        sys.exit(1)

    pdf_path_arg = sys.argv[1]
    total = ingest_document(pdf_path_arg)
    print(f"\n✅ Berhasil meng-ingest {total} chunk dari: {pdf_path_arg}")
