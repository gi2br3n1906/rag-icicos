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
from typing import List, Optional, Tuple

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System Prompt: Jalur SOP — Wajib Lengkap & Berurutan
# ---------------------------------------------------------------------------
SOP_SYSTEM_PROMPT = """You are the official procedural guide assistant of ICICoS 2026 (The 9th International Conference on Informatics and Computational Sciences), organized by the Department of Informatics, Universitas Diponegoro.

Your task is to explain the official SOP (Standard Operating Procedure) based on the provided document.

ABSOLUTE RULES FOR SOP ANSWERS:
1. Focus ONLY on answering the user's question. Extract and explain only the steps and information from the SOP document that are directly relevant to the query. Do NOT output unrelated parts of the SOP (e.g., if the user asks about getting the LoA, do not detail the receipt processing or unrelated branches).
2. Answer from the Author's point of view (perspective) only. Explain what actions the Author needs to take (e.g., fill out registration, make payment, upload proof of payment) and what the Author will receive.
3. Treat any committee actions mentioned in the context as a black box. Do NOT detail their internal workflows, tools, databases, spreadsheets, or decision gateways. Simply state the outcome from the Author's perspective (e.g., write "You will receive the LoA from the Secretary" instead of detailing how the Secretary checks spreadsheet statuses). Do NOT invent internal steps (such as "the committee will verify your submission") if they are not explicitly mentioned in the context, as your response must remain strictly grounded in the document.
4. ALWAYS respond in English, regardless of the language the user writes in.
5. Do NOT add generic greetings (e.g., "Hello", "Good morning") or polite sign-offs (e.g., "Hope this helps"). However, you MUST start with a single, concise introductory sentence explaining what the procedure is (e.g., "Here is the procedure to get the Letter of Acceptance (LoA):" or "To submit your proof of payment, follow these steps:").
6. Format the steps clearly as a numbered list using plain text (e.g., 1., 2., 3.).
7. Use bold <b>Step Title</b> for key step headers or terms.
8. If the SOP document is not provided or is empty, state that information is not available and suggest contacting the organizing committee.
9. TELEGRAM HTML FORMAT — Use ONLY: <b>, <i>, <u>, <s>, <code>, <pre>. NEVER use: <ul>, <ol>, <li>, <h1>-<h6>, <p>, or Markdown.
10. FOLLOW-UP QUESTIONS — After your main answer, append EXACTLY the following delimiter on its own line, followed by EXACTLY 3 short, relevant follow-up questions (one per line) in English that the user is likely to ask next. Crucially, these questions MUST be directly and fully answerable using ONLY the information present in the provided SOP Document. Do NOT suggest questions that cannot be answered by the document. Do NOT number the questions:
===FOLLOW_UP_QUESTIONS===
<question 1>
<question 2>
<question 3>

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
8. FOLLOW-UP QUESTIONS — After your main answer, append EXACTLY the following delimiter on its own line, followed by EXACTLY 3 short, relevant follow-up questions (one per line) in English that the user is likely to ask next. Crucially, these questions MUST be directly and fully answerable using ONLY the information present in the provided FAQ Context. Do NOT suggest questions that cannot be answered by the context. Do NOT number the questions:
===FOLLOW_UP_QUESTIONS===
<question 1>
<question 2>
<question 3>

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
# Helper: Parse follow-up questions dari output LLM
# ---------------------------------------------------------------------------
FOLLOW_UP_DELIMITER = "===FOLLOW_UP_QUESTIONS==="


def _parse_answer_and_followups(raw_output: str) -> Tuple[str, List[str]]:
    """
    Memisahkan jawaban utama dan daftar pertanyaan lanjutan dari output mentah LLM.

    Format yang diharapkan dari LLM:
        <main answer text>
        ===FOLLOW_UP_QUESTIONS===
        <question 1>
        <question 2>
        <question 3>

    Returns:
        Tuple: (answer_text, follow_up_questions_list)
        Jika delimiter tidak ditemukan, kembalikan semua sebagai jawaban utama
        dengan list kosong.
    """
    if FOLLOW_UP_DELIMITER in raw_output:
        parts = raw_output.split(FOLLOW_UP_DELIMITER, maxsplit=1)
        answer_text = parts[0].strip()
        followup_block = parts[1].strip()
        follow_ups = [
            q.strip() for q in followup_block.splitlines()
            if q.strip() and not q.strip().startswith("===")
        ][:3]  # Ambil maksimal 3 pertanyaan
        return answer_text, follow_ups

    logger.warning("[Generator] Delimiter follow-up tidak ditemukan di output LLM. Mengembalikan tanpa follow-ups.")
    return raw_output.strip(), []


# ---------------------------------------------------------------------------
# Public API: Specialized generators untuk workflow baru
# ---------------------------------------------------------------------------

def generate_sop_answer(query: str, sop_doc: Document) -> Tuple[str, List[str]]:
    """
    Menghasilkan jawaban untuk jalur SOP menggunakan SOP_SYSTEM_PROMPT.
    Jaminan: Seluruh isi SOP dikirimkan sebagai konteks — tidak ada langkah yang terlewat.

    Args:
        query  : Pertanyaan user (sudah direformulasi).
        sop_doc: Parent Document SOP utuh hasil ParentDocumentRetriever.

    Returns:
        Tuple: (answer_html, follow_up_questions) — jawaban berformat HTML Telegram
        dan daftar 0-3 pertanyaan lanjutan dalam bahasa Inggris.
    """
    context = _format_sop_context(sop_doc)
    prompt = SOP_SYSTEM_PROMPT.format(context=context, question=query)
    logger.info(f"[Generator-SOP] Mengirim SOP ({len(context):,} karakter) ke LLM.")
    raw = _dispatch(prompt)
    return _parse_answer_and_followups(raw)


def generate_faq_answer(query: str, faq_docs: List[Document]) -> Tuple[str, List[str]]:
    """
    Menghasilkan jawaban singkat untuk jalur FAQ menggunakan FAQ_SYSTEM_PROMPT.

    Args:
        query   : Pertanyaan user (sudah direformulasi).
        faq_docs: List chunk FAQ yang relevan dari ChromaDB.

    Returns:
        Tuple: (answer_html, follow_up_questions) — jawaban singkat berformat HTML Telegram
        dan daftar 0-3 pertanyaan lanjutan dalam bahasa Inggris.
    """
    context = _format_faq_context(faq_docs)
    prompt = FAQ_SYSTEM_PROMPT.format(context=context, question=query)
    logger.info(f"[Generator-FAQ] Mengirim {len(faq_docs)} FAQ chunk ke LLM.")
    raw = _dispatch(prompt)
    return _parse_answer_and_followups(raw)


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