"""
generator.py - Modul Generator: mengirim query + konteks ke LLM dan mendapatkan jawaban.

Arsitektur Baru (Bulletproof Agentic RAG):
  - SOP_SYSTEM_PROMPT : Instruksi khusus untuk menjawab SOP — wajib lengkap & urut.
  - FAQ_SYSTEM_PROMPT : Instruksi khusus untuk menjawab FAQ — singkat & padat.
  - generate_sop_answer() : Generator untuk jalur SOP.
  - generate_faq_answer() : Generator untuk jalur FAQ.
  - generate_answer()     : Entry point lama (backward compat / direct call).

Mendukung tiga provider: OpenRouter, Google Gemini, dan Ollama Lokal.
"""
import logging
import os
from typing import List, Optional

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System Prompt: Jalur SOP — Wajib Lengkap & Berurutan
# ---------------------------------------------------------------------------
SOP_SYSTEM_PROMPT = """You are the official procedural guide assistant of ICICoS 2026 (The 9th International Conference on Informatics and Computational Sciences), organized by the Department of Informatics, Universitas Diponegoro.

Your ONLY task is to explain the official SOP (Standard Operating Procedure) based on the provided document.

ABSOLUTE RULES FOR SOP ANSWERS:
1. You MUST list ALL steps from the SOP document, in the EXACT order they appear. Skipping even ONE step is a critical failure.
2. ALWAYS respond in English, regardless of the language the user writes in.
3. Start directly with the steps. Do NOT add preambles like "Here are the steps" or greetings.
4. Format each step clearly as a numbered list using plain text (e.g., 1., 2., 3.).
5. Use bold <b>Step Title</b> for each step header if the SOP has named steps.
6. If the SOP document is not provided or is empty, state that information is not available and suggest contacting the organizing committee.
7. TELEGRAM HTML FORMAT — Use ONLY: <b>, <i>, <u>, <s>, <code>, <pre>. NEVER use: <ul>, <ol>, <li>, <h1>-<h6>, <p>, or Markdown.

SOP Document:
{context}

User's Question:
{question}"""

# ---------------------------------------------------------------------------
# System Prompt: Jalur FAQ — Singkat & Padat
# ---------------------------------------------------------------------------
FAQ_SYSTEM_PROMPT = """You are the official concise Q&A assistant of ICICoS 2026 (The 9th International Conference on Informatics and Computational Sciences).

Your task is to give a SHORT, DIRECT answer based on the FAQ context provided.

ABSOLUTE RULES FOR FAQ ANSWERS:
1. ALWAYS respond in English, regardless of the language the user writes in.
2. Keep your answer to a MAXIMUM of 3 short sentences. Be concise and to the point.
3. Do NOT explain procedures step-by-step. Give the direct answer only.
4. If the information is not in the context, state you don't have that information and suggest contacting the organizing committee.
5. STRICTLY FORBIDDEN to fabricate answers (hallucination).
6. Go directly to the point. Do NOT add greetings or sign-offs.
7. TELEGRAM HTML FORMAT — Use ONLY: <b>, <i>, <u>. NEVER use: <ul>, <ol>, <li>, or Markdown.

FAQ Context:
{context}

User's Question:
{question}"""

# ---------------------------------------------------------------------------
# Fallback Response
# ---------------------------------------------------------------------------
FALLBACK_RESPONSE = (
    "I'm sorry, information related to your question is not currently available in our "
    "document database. Please contact the ICICoS 2026 organizing committee directly "
    "via the official Telegram group or the committee's email for further assistance."
)


def _call_openrouter(prompt: str) -> str:
    """Panggil OpenRouter API dengan prompt yang sudah diformat."""
    from openai import OpenAI
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY tidak ditemukan di environment variables!")
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return response.choices[0].message.content


def _call_gemini(prompt: str) -> str:
    """Panggil Gemini API dengan prompt yang sudah diformat."""
    import google.generativeai as genai
    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    if not api_key:
        raise ValueError("GEMINI_API_KEY tidak ditemukan di environment variables!")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(prompt)
    return response.text


def _call_ollama(prompt: str) -> str:
    """Panggil Ollama lokal dengan prompt yang sudah diformat."""
    from openai import OpenAI
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    model = os.getenv("OLLAMA_MODEL", "granite4.1:3b")
    client = OpenAI(base_url=base_url, api_key="ollama_local")
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    return response.choices[0].message.content


def _dispatch(prompt: str) -> str:
    """Kirim prompt ke provider LLM yang aktif berdasarkan LLM_PROVIDER env var."""
    provider = os.getenv("LLM_PROVIDER", "openrouter").lower()
    logger.info(f"[Generator] 🤖 LLM_PROVIDER aktif: '{provider}'")
    if provider == "gemini":
        return _call_gemini(prompt)
    elif provider == "ollama":
        return _call_ollama(prompt)
    else:
        return _call_openrouter(prompt)


def _format_sop_context(doc: Document) -> str:
    """Format satu Parent Document SOP menjadi string konteks."""
    source = doc.metadata.get("source", "SOP Document")
    return f"[Source: {source}]\n\n{doc.page_content}"


def _format_faq_context(docs: List[Document]) -> str:
    """Gabungkan beberapa FAQ chunk menjadi satu string konteks."""
    return "\n\n---\n\n".join(
        f"[FAQ #{i+1}]\n{doc.page_content}"
        for i, doc in enumerate(docs)
    )


# ---------------------------------------------------------------------------
# Public API: Specialized generators untuk workflow baru
# ---------------------------------------------------------------------------

def generate_sop_answer(query: str, sop_doc: Document) -> str:
    """
    Menghasilkan jawaban untuk jalur SOP menggunakan SOP_SYSTEM_PROMPT.
    Jaminan: Seluruh isi SOP dikirimkan sebagai konteks — tidak ada langkah yang terlewat.

    Args:
        query  : Pertanyaan user (sudah direformulasi).
        sop_doc: Parent Document SOP utuh hasil ParentDocumentRetriever.

    Returns:
        String jawaban berformat HTML Telegram.
    """
    context = _format_sop_context(sop_doc)
    prompt = SOP_SYSTEM_PROMPT.format(context=context, question=query)
    logger.info(f"[Generator-SOP] Mengirim SOP ({len(context):,} karakter) ke LLM.")
    return _dispatch(prompt)


def generate_faq_answer(query: str, faq_docs: List[Document]) -> str:
    """
    Menghasilkan jawaban singkat untuk jalur FAQ menggunakan FAQ_SYSTEM_PROMPT.

    Args:
        query   : Pertanyaan user (sudah direformulasi).
        faq_docs: List chunk FAQ yang relevan dari ChromaDB.

    Returns:
        String jawaban singkat berformat HTML Telegram.
    """
    context = _format_faq_context(faq_docs)
    prompt = FAQ_SYSTEM_PROMPT.format(context=context, question=query)
    logger.info(f"[Generator-FAQ] Mengirim {len(faq_docs)} FAQ chunk ke LLM.")
    return _dispatch(prompt)


# ---------------------------------------------------------------------------
# Legacy: generate_answer() untuk backward compatibility
# ---------------------------------------------------------------------------

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

    context = "\n\n---\n\n".join(
        f"[Halaman {doc.metadata.get('page', '?')}]\n{doc.page_content}"
        for doc in docs
    )
    prompt = SOP_SYSTEM_PROMPT.format(context=context, question=query)

    logger.info(f"Mengirim query ke OpenRouter (model: {model})")
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return response.choices[0].message.content


def generate_answer_gemini(query: str, docs: List[Document]) -> str:
    """
    Menghasilkan jawaban menggunakan Google Gemini API.
    """
    import google.generativeai as genai  # Lazy import

    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    if not api_key:
        raise ValueError("GEMINI_API_KEY tidak ditemukan di environment variables!")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    context = "\n\n---\n\n".join(
        f"[Halaman {doc.metadata.get('page', '?')}]\n{doc.page_content}"
        for doc in docs
    )
    prompt = SOP_SYSTEM_PROMPT.format(context=context, question=query)

    logger.info(f"Mengirim query ke Gemini (model: {model_name})")
    response = model.generate_content(prompt)
    return response.text


def generate_answer_ollama(query: str, docs: List[Document]) -> str:
    """
    Menghasilkan jawaban menggunakan Ollama lokal.
    """
    from openai import OpenAI

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    model = os.getenv("OLLAMA_MODEL", "granite4.1:3b")

    client = OpenAI(base_url=base_url, api_key="ollama_local")

    context = "\n\n---\n\n".join(
        f"[Halaman {doc.metadata.get('page', '?')}]\n{doc.page_content}"
        for doc in docs
    )
    prompt = SOP_SYSTEM_PROMPT.format(context=context, question=query)

    logger.info(f"Mengirim query ke Ollama Lokal (model: {model})")
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    return response.choices[0].message.content


def generate_answer(query: str, docs: List[Document]) -> str:
    """
    Fungsi utama generator (legacy). Memilih provider LLM berdasarkan environment variable.
    LLM_PROVIDER bisa diset ke 'openrouter', 'gemini', atau 'ollama'.
    """
    provider = os.getenv("LLM_PROVIDER", "openrouter").lower()
    logger.info(f"[Generator] 🤖 LLM_PROVIDER aktif: '{provider}'")

    if provider == "gemini":
        return generate_answer_gemini(query, docs)
    elif provider == "ollama":
        return generate_answer_ollama(query, docs)
    else:
        return generate_answer_openrouter(query, docs)