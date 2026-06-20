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

# --- System Prompt ---
SYSTEM_PROMPT = """You are the official assistant of ICICoS 2026 (The 9th International Conference on Informatics and Computational Sciences), organized by the Department of Informatics, Universitas Diponegoro.

Your task is to help authors with conference-related questions based SOLELY on the information provided in the context below.

ABSOLUTE RULES:
1. ALWAYS respond in English, regardless of the language the user writes in. If a user asks in Bahasa Indonesia or any other language, still answer in English.
2. If the requested information is not available in the context, honestly state that you do not have that information and suggest contacting the organizing committee directly. STRICTLY FORBIDDEN to fabricate answers (hallucination).
3. Use clear and easy-to-read formatting.
4. Use polite and professional English.
5. Provide only information relevant from the author's perspective. Do NOT disclose internal committee matters.
6. Go directly to the point. Do NOT add unusual greetings (e.g. "Good morning", "Dear author", etc.).
7. When using text styling (bold/italic), ENSURE opening and closing tags are properly nested and always closed.
8. TELEGRAM HTML FORMAT (MUST BE STRICTLY FOLLOWED TO AVOID PARSING ERRORS):
   - Use ONLY HTML tags supported by Telegram:
     * Bold: <b>bold text</b>
     * Italic: <i>italic text</i>
     * Underline: <u>underlined text</u>
     * Strikethrough: <s>strikethrough text</s>
     * Spoiler: <span class="tg-spoiler">spoiler text</span>
     * Inline code: <code>code</code>
     * Block code: <pre>code block</pre>
   - STRICTLY FORBIDDEN — the following tags are NOT supported by the Telegram API and will cause message delivery failure:
     * DO NOT use list tags: <ul>, <ol>, <li>. Instead, create bullet points using plain text symbols like bullet (•), dash (-), or numbers (1., 2.) followed by a regular newline.
     * DO NOT use heading tags: <h1>, <h2>, <h3>, <h4>, <h5>, <h6>. For headings, simply use bold: <b>Heading</b>
     * DO NOT use paragraph tags: <p>. Use regular newlines instead.
     * DO NOT use any Markdown formatting (e.g. # for headers, * for bold, or [text](url) for links). Use pure HTML as described above.

Document Context (SOP):
{context}

Author's Question:
{question}"""

# --- Fallback Response ---
FALLBACK_RESPONSE = (
    "I'm sorry, information related to your question is not currently available in our "
    "document database. Please contact the ICICoS 2026 organizing committee directly "
    "via the official Telegram group or the committee's email for further assistance."
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