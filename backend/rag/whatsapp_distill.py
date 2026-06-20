import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any
import google.generativeai as genai
from sqlalchemy.ext.asyncio import AsyncSession
from backend.api.models import WhatsAppFAQ

logger = logging.getLogger(__name__)

# System prompt to extract and translate FAQ pairs from WhatsApp chat logs
WHATSAPP_DISTILL_PROMPT = """
You are an AI conversation analyst responsible for processing WhatsApp chat logs from the ICICoS 2026 conference public relations (humas) team.
Your primary task is to extract valid Question and Answer pairs from the provided chat log and output them in English.

EXTRACTION RULES:
1. Only extract questions about the conference (e.g. registration, payment, paper submission, templates, important dates, accommodation, etc.) that were asked by participants (authors) AND clearly/correctly answered by the PR team (Humas/Panitia).
2. Ignore off-topic messages, greetings/farewells only, casual chat, arguments, system messages (e.g. "You joined", "Link was shared"), or unanswered questions.
3. Reformulate the question and answer into clean, polite, formal language. Ensure the question is self-contained (replace vague pronouns like "this" or "that" with the actual document or process name being discussed).
4. IMPORTANT: The chat log may be in Bahasa Indonesia. You MUST translate both the question and the answer into English in your output. The final output must always be in English regardless of the source language.
5. Classify each Q&A into one of the following categories: 'pembayaran', 'registrasi', 'submisi_paper', 'tanggal_penting', 'akomodasi', or 'lainnya'.

Output format MUST be a JSON Array of objects with the following structure:
[
  {
    "question": "The clearly formulated question written in English",
    "answer": "The cleaned and formalized answer from Humas, written in English",
    "category": "appropriate_category"
  }
]
"""

def split_chat_lines(file_path: Path, lines_per_segment: int = 200) -> List[str]:
    """Membaca file chat .txt dan membaginya menjadi beberapa segment teks."""
    if not file_path.exists():
        raise FileNotFoundError(f"File chat tidak ditemukan: {file_path}")
        
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
        
    segments = []
    current_segment = []
    
    for line in lines:
        cleaned_line = line.strip()
        if not cleaned_line:
            continue
        current_segment.append(cleaned_line)
        if len(current_segment) >= lines_per_segment:
            segments.append("\n".join(current_segment))
            current_segment = []
            
    if current_segment:
        segments.append("\n".join(current_segment))
        
    return segments

async def distill_segment_to_qa(segment_text: str, source_filename: str) -> List[Dict[str, Any]]:
    """Mengirim satu segment chat ke Gemini untuk diekstrak menjadi Q&A JSON."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY tidak ditemukan di environment variables.")
        
    # Lazy import monkey patch if not already applied
    from google.generativeai.client import FileServiceClient, GENAI_API_DISCOVERY_URL
    import googleapiclient.discovery
    import googleapiclient.http
    import httplib2

    def patched_setup_discovery_api(self, metadata=()):
        api_key = self._client_options.api_key
        if api_key is None:
            raise ValueError("Invalid operation: Uploading to the File API requires an API key.")
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

    FileServiceClient._setup_discovery_api = patched_setup_discovery_api
    genai.configure(api_key=api_key)
    
    # Ambil model dari env, default ke gemini-2.5-flash jika tidak terdefinisi
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    model = genai.GenerativeModel(
        model_name,
        system_instruction=WHATSAPP_DISTILL_PROMPT
    )
    
    logger.info(f"[Distill] Mengirim segment chat ({len(segment_text.splitlines())} baris) ke model {model_name}...")
    
    try:
        response = model.generate_content(
            f"Ekstrak Q&A dari percakapan WA berikut:\n\n{segment_text}",
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        
        text_content = response.text.strip()
        data = json.loads(text_content)
        if not isinstance(data, list):
            logger.warning("[Distill] Output dari Gemini bukan JSON Array, mengabaikan...")
            return []
        return data
    except json.JSONDecodeError as decode_err:
        logger.error(f"[Distill] Gagal men-decode JSON dari respon Gemini: {decode_err}")
        return []
    except Exception as e:
        logger.error(f"[Distill] Gagal mengekstrak segment: {e}")
        return []

async def process_whatsapp_chat_distillation(
    file_path: Path,
    db: AsyncSession,
    lines_per_segment: int = 200
) -> int:
    """
    Orkestrator full pipeline untuk ekstraksi asinkron chat WA:
    Mendukung file input .txt (log chat langsung) atau .zip (log chat + media).
    
    Jika input adalah .zip:
      1. Ekstrak zip ke folder temp.
      2. Cari file chat .txt di dalamnya (biasanya '_chat.txt' atau mengandung kata 'chat'/'percakapan').
      3. Cari file .pdf lain di dalamnya untuk didaftarkan ke RAG (opsional).
      4. Proses file chat .txt utama ke pipeline distilasi.
      5. Bersihkan folder temp.
    
    Returns:
        Jumlah FAQ baru yang berhasil diekstrak dan disimpan.
    """
    import zipfile
    import tempfile
    import shutil

    source_filename = file_path.name
    temp_dir_path = None
    target_txt_path = file_path
    
    # 1. Penanganan khusus jika file input berupa ZIP
    if file_path.suffix.lower() == ".zip":
        logger.info(f"[Distill] Mendeteksi file ZIP. Mengekstrak file '{source_filename}'...")
        temp_dir = tempfile.mkdtemp(prefix="wa_distill_")
        temp_dir_path = Path(temp_dir)
        
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir_path)
            
            # Cari file chat log (.txt) di dalam zip
            all_files = list(temp_dir_path.glob("**/*"))
            txt_files = [f for f in all_files if f.is_file() and f.suffix.lower() == ".txt"]
            
            # Cari file PDF lain untuk di-ingest as-is (opsional)
            pdf_files = [f for f in all_files if f.is_file() and f.suffix.lower() == ".pdf"]
            if pdf_files:
                logger.info(f"[Distill] Ditemukan {len(pdf_files)} file PDF tambahan di dalam ZIP. Meng-ingest dokumen...")
                from backend.rag.ingestion import ingest_document
                from backend.api.models import Document as DBDoc
                
                # Ingest setiap PDF pendukung langsung ke ChromaDB & DB
                for pdf_f in pdf_files:
                    try:
                        # Pindahkan ke folder data/docs agar konsisten
                        dest_dir = file_path.parent
                        dest_path = dest_dir / pdf_f.name
                        shutil.copy2(pdf_f, dest_path)
                        
                        logger.info(f"[Distill] Meng-ingest PDF pendukung: '{pdf_f.name}'...")
                        total_chunks = await asyncio.to_thread(ingest_document, str(dest_path))
                        
                        new_doc = DBDoc(
                            filename=pdf_f.name,
                            total_chunks=total_chunks,
                            status="success",
                        )
                        db.add(new_doc)
                        logger.info(f"[Distill] PDF pendukung '{pdf_f.name}' berhasil di-ingest ({total_chunks} chunks).")
                    except Exception as pdf_exc:
                        logger.error(f"[Distill] Gagal meng-ingest PDF pendukung '{pdf_f.name}': {pdf_exc}")

            if not txt_files:
                raise ValueError("Tidak ditemukan file log chat (.txt) di dalam file ZIP.")
                
            # Strategi pencarian file chat utama:
            # 1. Cari yang bernama '_chat.txt' (format iOS)
            # 2. Cari yang mengandung kata 'chat'
            # 3. Fallback: ambil file .txt pertama
            target_txt_path = None
            for tf in txt_files:
                if tf.name == "_chat.txt":
                    target_txt_path = tf
                    break
            
            if not target_txt_path:
                for tf in txt_files:
                    if "chat" in tf.name.lower():
                        target_txt_path = tf
                        break
                        
            if not target_txt_path:
                target_txt_path = txt_files[0]
                
            logger.info(f"[Distill] Menemukan file log chat utama di ZIP: '{target_txt_path.name}'")
            
        except Exception as zip_err:
            logger.error(f"[Distill] Gagal memproses file ZIP: {zip_err}")
            if temp_dir_path and temp_dir_path.exists():
                shutil.rmtree(temp_dir_path)
            raise

    # 2. Proses distilasi chat log utama (.txt)
    logger.info(f"[Distill] Memulai ekstraksi chat WA dari file: '{target_txt_path.name}'")
    
    try:
        segments = split_chat_lines(target_txt_path, lines_per_segment)
        logger.info(f"[Distill] File dibagi menjadi {len(segments)} segment untuk diekstrak.")
        
        total_extracted = 0
        
        for idx, segment in enumerate(segments):
            logger.info(f"[Distill] Memproses segment {idx + 1}/{len(segments)}...")
            qa_pairs = await distill_segment_to_qa(segment, source_filename)
            
            if not qa_pairs:
                continue
                
            # Simpan Q&A pairs ke PostgreSQL database
            for pair in qa_pairs:
                question = pair.get("question", "").strip()
                answer = pair.get("answer", "").strip()
                category = pair.get("category", "lainnya").strip()
                
                if not question or not answer:
                    continue
                    
                new_faq = WhatsAppFAQ(
                    question=question,
                    answer=answer,
                    category=category,
                    status="pending",
                    source_file=source_filename
                )
                db.add(new_faq)
                total_extracted += 1
                
            # Commit bertahap per segment agar data tidak hilang jika ada error di tengah jalan
            await db.commit()
            logger.info(f"[Distill] Berhasil menyimpan {len(qa_pairs)} Q&A dari segment {idx + 1}.")
            
        logger.info(f"[Distill] Selesai memproses '{source_filename}'. Total {total_extracted} Q&A pending disimpan.")
        return total_extracted
        
    except Exception as exc:
        logger.error(f"[Distill] Terjadi kesalahan dalam proses distill chat WA: {exc}", exc_info=True)
        await db.rollback()
        raise
    finally:
        # Cleanup temporary extracted directory jika ada
        if temp_dir_path and temp_dir_path.exists():
            shutil.rmtree(temp_dir_path)
            logger.info(f"[Distill] Folder sementara ZIP '{temp_dir_path.name}' berhasil dibersihkan.")

