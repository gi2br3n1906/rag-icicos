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
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.retrievers import ParentDocumentRetriever
from langchain.storage import LocalFileStore
from langchain.storage._lc_store import create_kv_docstore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfigurasi Embedding
# ---------------------------------------------------------------------------
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"  # 768 dim — upgraded dari e5-small (384 dim)
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma_db")
EXTRACTED_TEXT_DIR = os.getenv("EXTRACTED_TEXT_DIR", "./data/extracted_text")
PARENT_STORE_DIR = os.getenv("PARENT_STORE_DIR", "./data/parent_store")

# ---------------------------------------------------------------------------
# Konfigurasi Chunking
# ---------------------------------------------------------------------------
CHUNK_SIZE = 512    # Ukuran chunk dalam karakter (sesuai permintaan)
CHUNK_OVERLAP = 50  # Overlap antar chunk untuk menjaga konteks antar-batas

# ---------------------------------------------------------------------------
# Prompt instruksi untuk Gemini (LLM-Assisted Ingestion)
# ---------------------------------------------------------------------------
GEMINI_CONVERSION_PROMPT = (
    "You are a business process analysis expert for the ICICoS 2026 conference. "
    "Carefully examine this BPMN/Flowchart diagram document. "
    "Your task is to convert all visual flow diagrams in this document into a "
    "linear, structured narrative text written entirely in English. "
    "State the SOP name, the actors involved, and the sequence of steps clearly "
    "from start to finish, including any business rules or deadlines (SLA) "
    "if they are indicated in the diagram. "
    "The output MUST be in English only, even if the source document is in Bahasa Indonesia."
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

def get_parent_document_retriever() -> ParentDocumentRetriever:
    """Menginisialisasi ParentDocumentRetriever dengan docstore yang sudah dikonfigurasi.
    
    LocalFileStore hanya bisa menyimpan bytes, sehingga perlu dibungkus dengan
    create_kv_docstore yang menangani serialisasi Document <-> bytes secara otomatis.
    """
    vectorstore = Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=get_embeddings(),
        collection_name="icicos_sop",
    )
    # Buat direktori parent_store jika belum ada
    Path(PARENT_STORE_DIR).mkdir(parents=True, exist_ok=True)
    
    # LocalFileStore menyimpan bytes ke disk.
    # create_kv_docstore membungkusnya agar bisa menyimpan/membaca objek Document secara transparan.
    raw_store = LocalFileStore(PARENT_STORE_DIR)
    docstore = create_kv_docstore(raw_store)
    
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    
    return ParentDocumentRetriever(
        vectorstore=vectorstore,
        docstore=docstore,
        child_splitter=child_splitter,
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
    from google.generativeai.client import FileServiceClient, GENAI_API_DISCOVERY_URL
    import googleapiclient.discovery
    import googleapiclient.http
    import httplib2

    # Monkey patch FileServiceClient._setup_discovery_api untuk mengatasi bug validasi
    # API key format baru (AQ.Ab...) pada endpoint discovery public Google.
    def patched_setup_discovery_api(self, metadata=()):
        api_key = self._client_options.api_key
        if api_key is None:
            raise ValueError(
                "Invalid operation: Uploading to the File API requires an API key. Please provide a valid API key."
            )

        # Ambil dokumen discovery tanpa parameter key (endpoint ini publik, key tidak wajib untuk metadata)
        # Bypas error validasi format key baru "AQ.Ab..." di filter proxy discovery Google.
        uri = f"{GENAI_API_DISCOVERY_URL}?version=v1beta"
        
        request = googleapiclient.http.HttpRequest(
            http=httplib2.Http(),
            postproc=lambda resp, content: (resp, content),
            uri=uri,
            headers=dict(metadata),
        )
        response, content = request.execute()
        request.http.close()

        discovery_doc = content.decode("utf-8")
        self._discovery_api = googleapiclient.discovery.build_from_document(
            discovery_doc, developerKey=api_key
        )

    # Terapkan monkey patch secara dinamis
    FileServiceClient._setup_discovery_api = patched_setup_discovery_api

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
        with open(path, "rb") as f:
            uploaded_file = genai.upload_file(
                path=f,
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
# 3. Fungsi Utama: Orkestrasi Full Pipeline Ingesti (Parent-Child)
# ===========================================================================

def ingest_document(pdf_path: str) -> int:
    """
    Pipeline ingesti lengkap (LLM-Assisted) dengan Parent-Child Retriever:
      PDF visual → Gemini 1.5 Flash → teks naratif
        → simpan naratif penuh (Parent) di Local Store
        → potong menjadi chunk kecil (Child) → embed → simpan ke ChromaDB

    Args:
        pdf_path: Path ke file PDF SOP (bisa berupa diagram BPMN visual).

    Returns:
        Jumlah dokumen (1 parent) yang berhasil disimpan.

    Raises:
        ValueError: Jika GEMINI_API_KEY tidak tersedia.
        FileNotFoundError: Jika file tidak ditemukan.
        RuntimeError: Jika Gemini gagal memproses file.
    """
    path = Path(pdf_path)
    logger.info(
        "=" * 60 + "\n"
        f"[Ingesti] Memulai pipeline LLM-Assisted (Parent-Child) untuk: '{path.name}'\n"
        + "=" * 60
    )

    # --- [TAHAP 1] Konversi PDF visual → teks naratif via Gemini ---
    logger.info("[Ingesti] TAHAP 1/3: Konversi diagram via Google Gemini 1.5 Flash")
    clean_text = convert_pdf_to_structured_text(pdf_path)

    # --- [TAHAP 1b] Simpan hasil ekstraksi ke .txt untuk review manual ---
    save_extracted_text(source_pdf_name=path.name, text=clean_text)

    # --- [TAHAP 2] Menyiapkan Parent Document ---
    logger.info("[Ingesti] TAHAP 2/3: Menyiapkan Parent Document utuh")
    parent_doc = Document(
        page_content=clean_text,
        metadata={
            "source": path.name,
            "ingestion_method": "gemini_llm_assisted_parent_child",
            "kategori_dokumen": "SOP" # Penanda SOP untuk metadata filtering nanti
        }
    )

    # --- [TAHAP 3] Embedding + simpan ke ChromaDB & Local Store ---
    logger.info(
        f"[Ingesti] TAHAP 3/3: Memproses chunk (Child) ke ChromaDB dan menyimpan teks utuh (Parent) ke {PARENT_STORE_DIR}"
    )
    retriever = get_parent_document_retriever()
    
    # Menyimpan dokumen. ids digunakan agar jika di-ingest ulang, dokumen lamanya tertimpa (update).
    retriever.add_documents([parent_doc], ids=[path.name])

    logger.info(
        "=" * 60 + "\n"
        f"[Ingesti] ✅ SELESAI. Dokumen SOP '{path.name}' berhasil di-ingest "
        f"menggunakan pola Parent-Child.\n"
        + "=" * 60
    )
    return 1


# ===========================================================================
# 5. Utilitas: Reset Knowledge Base
# ===========================================================================

def clear_knowledge_base() -> None:
    """
    Menghapus seluruh isi ChromaDB — both collections:
      - 'icicos_sop'  : Parent-Child chunks dari dokumen SOP
      - 'icicos_faq'  : FAQ chunks dari histori WhatsApp

    Fungsi ini berguna untuk mereset knowledge base sebelum proses ingesti
    ulang (re-ingest) semua dokumen SOP dari awal, menghindari duplikasi data
    embedding di dalam vector store.

    Catatan: Operasi ini bersifat destruktif dan tidak dapat di-undo.
    """
    logger.info("[Reset] Memulai proses penghapusan seluruh ChromaDB collections...")

    embeddings = get_embeddings()

    # Hapus collection SOP (berisi child chunks + parent-child mapping)
    sop_store = Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=embeddings,
        collection_name="icicos_sop",
    )
    sop_store.delete_collection()
    logger.info("[Reset] Collection 'icicos_sop' berhasil dihapus.")

    # Hapus collection FAQ (berisi chunk histori WhatsApp yang diapprove)
    try:
        faq_store = Chroma(
            persist_directory=CHROMA_PERSIST_DIR,
            embedding_function=embeddings,
            collection_name="icicos_faq",
        )
        faq_store.delete_collection()
        logger.info("[Reset] Collection 'icicos_faq' berhasil dihapus.")
    except Exception as e:
        # Collection mungkin belum dibuat jika belum ada FAQ yang di-approve
        logger.warning(f"[Reset] Collection 'icicos_faq' tidak dapat dihapus (mungkin belum ada): {e}")

    logger.info("[Reset] ✅ Seluruh ChromaDB collections berhasil di-wipe bersih.")


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
