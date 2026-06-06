"""
generator.py - Modul Generator: mengirim query + konteks ke LLM dan mendapatkan jawaban.
Mendukung tiga provider: OpenRouter, Google Gemini, dan Ollama Lokal.

System Prompt sesuai PROMPTS.md.
"""
import logging
import os
from typing import List

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# --- System Prompt (dari PROMPTS.md) ---
SYSTEM_PROMPT = """Kamu adalah asisten resmi ICICoS 2026 (The 9th International Conference on Informatics and Computational Sciences), diselenggarakan oleh Departemen Informatika Universitas Diponegoro.

Tugasmu adalah membantu author dengan pertanyaan seputar konferensi berdasarkan HANYA informasi yang diberikan dalam konteks di bawah ini.

ATURAN MUTLAK:
1. Jika informasi tidak tersedia dalam konteks, katakan dengan jujur bahwa kamu tidak memiliki informasi tersebut dan sarankan menghubungi panitia langsung. DILARANG KERAS MENGARANG JAWABAN (HALUSINASI).
2. Gunakan format yang mudah dibaca (bullet points jika perlu).
3. Gunakan Bahasa Indonesia yang sopan dan profesional.
4. Berikan informasi hanya yang dibutuhkan dari sudut pandang author saja, untuk urusan internal panitia tidak perlu diutarakan.
5. LANGSUNG berikan jawaban pada intinya tanpa menambahkan salam pembuka yang aneh (seperti "Selamat pagi", "Selamat hari", dll).
6. Saat menggunakan gaya teks (bold/italic), PASTIKAN tag pembuka dan penutup tidak bertumpuk secara salah, dan gunakan markdown yang rapi agar tidak error saat ditampilkan.

Konteks Dokumen (SOP):
{context}

Pertanyaan Author:
{question}"""

# --- Fallback Response (dari PROMPTS.md) ---
FALLBACK_RESPONSE = (
    "Mohon maaf, informasi terkait pertanyaan tersebut belum tersedia di database "
    "dokumen pedoman kami. Silakan hubungi panitia ICICoS 2026 melalui grup Telegram "
    "resmi atau email panitia untuk bantuan lebih lanjut."
)


def _format_context(docs: List[Document]) -> str:
    """Menggabungkan isi chunk dokumen menjadi satu string konteks."""
    return "\n\n---\n\n".join(
        f"[Halaman {doc.metadata.get('page', '?')}]\n{doc.page_content}" 
        for doc in docs
    )


def generate_answer_openrouter(query: str, docs: List[Document]) -> str:
    """
    Menghasilkan jawaban menggunakan OpenRouter (OpenAI-compatible API).
    Model default: meta-llama/llama-3.1-8b-instruct (gratis di OpenRouter).
    """
    from openai import OpenAI  # Lazy import - hanya jika provider ini dipilih

    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")

    if not api_key:
        raise ValueError("OPENROUTER_API_KEY tidak ditemukan di environment variables!")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    context = _format_context(docs)
    prompt = SYSTEM_PROMPT.format(context=context, question=query)

    logger.info(f"Mengirim query ke OpenRouter (model: {model})")
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,  # Suhu rendah untuk jawaban yang lebih faktual
    )
    return response.choices[0].message.content


def generate_answer_gemini(query: str, docs: List[Document]) -> str:
    """
    Menghasilkan jawaban menggunakan Google Gemini API.
    Model default: gemini-1.5-flash (cepat dan hemat quota).
    """
    import google.generativeai as genai  # Lazy import

    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    if not api_key:
        raise ValueError("GEMINI_API_KEY tidak ditemukan di environment variables!")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    context = _format_context(docs)
    prompt = SYSTEM_PROMPT.format(context=context, question=query)

    logger.info(f"Mengirim query ke Gemini (model: {model_name})")
    response = model.generate_content(prompt)
    return response.text


def generate_answer_ollama(query: str, docs: List[Document]) -> str:
    """
    Menghasilkan jawaban menggunakan Ollama lokal dengan memanfaatkan
    OpenAI-compatible endpoint bawaan Ollama.
    Model default: granite4.1:3b.
    """
    from openai import OpenAI  # Memanfaatkan library openai yang sudah ada

    # Default URL untuk OpenAI-compatible endpoint di Ollama lokal adalah /v1
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    model = os.getenv("OLLAMA_MODEL", "granite4.1:3b")

    # Ollama tidak mengecek API key, diisi string sembarang agar object client valid
    client = OpenAI(
        base_url=base_url,
        api_key="ollama_local",
    )

    context = _format_context(docs)
    prompt = SYSTEM_PROMPT.format(context=context, question=query)

    logger.info(f"Mengirim query ke Ollama Lokal (model: {model})")
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,  # Set ke 0.0 agar model ukuran kecil bener-bener nurut konteks SOP
    )
    return response.choices[0].message.content


def generate_answer(query: str, docs: List[Document]) -> str:
    """
    Fungsi utama generator. Memilih provider LLM berdasarkan environment variable.
    LLM_PROVIDER bisa diset ke 'openrouter', 'gemini', atau 'ollama'.
    """
    provider = os.getenv("LLM_PROVIDER", "openrouter").lower()

    # Log eksplisit agar mudah dicek di terminal mana provider yang aktif
    logger.info(f"[Generator] 🤖 LLM_PROVIDER aktif: '{provider}'")

    if provider == "gemini":
        return generate_answer_gemini(query, docs)
    elif provider == "ollama":
        return generate_answer_ollama(query, docs)
    else:
        return generate_answer_openrouter(query, docs)