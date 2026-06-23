"""
query_rewriter.py - Contextual Query Rewriter untuk Agentic RAG Workflow.

Masalah yang diselesaikan:
  User sering mengirim pesan yang bergantung pada konteks percakapan sebelumnya.
  Contoh: "nah kalo skenario yang tadi, aku harus gimana?"
  Kata "tadi" tidak bisa diproses oleh Vector DB — ia tidak tahu "tadi" itu apa.

Solusi:
  LLM kecil membaca histori percakapan dan menyusun ulang pertanyaan menjadi
  kalimat mandiri yang utuh TANPA kata ganti rujukan (tadi, itu, dia, yang itu).

Output: string pertanyaan reformulasi yang siap diumpankan ke Router.
"""
import logging
import os

import google.generativeai as genai

logger = logging.getLogger(__name__)

QUERY_REWRITER_PROMPT = """\
You are a query reformulation assistant. Your ONLY task is to rewrite the user's latest message into a single, self-contained question based on the conversation history.

CRITICAL INSTRUCTIONS:
1. DO NOT answer the user's question. You are ONLY a rewriter.
2. DO NOT explain anything or add preambles.
3. Replace ALL vague references (like "that", "it", "tadi", "itu") with explicit descriptions from the history.
4. If the latest message is already self-contained, output it UNCHANGED (unless translation is needed).
5. TRANSLATE the final rewritten question to ENGLISH if the original message is in another language (e.g., Indonesian). ALL output MUST be in ENGLISH.

Conversation History:
{history}

Latest User Message: {query}
"""


def rewrite_query(query: str, history_text: str) -> str:
    """
    Menyusun ulang pertanyaan user menggunakan konteks histori percakapan.

    Jika histori kosong (percakapan pertama), pertanyaan dikembalikan apa adanya.

    Args:
        query       : Pesan terbaru dari user.
        history_text: Histori percakapan terformat dari memory.format_history_for_prompt().

    Returns:
        String pertanyaan yang sudah direformulasi (dan diterjemahkan ke bahasa Inggris) menjadi kalimat mandiri.
    """

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("[Rewriter] GEMINI_API_KEY tidak ditemukan. Query dikembalikan apa adanya.")
        return query

    genai.configure(api_key=api_key)

    # Gunakan model yang ringan dan cepat untuk tugas rewriting ini
    model_name = os.getenv("GEMINI_FAST_MODEL", "gemini-2.0-flash")
    model = genai.GenerativeModel(
        model_name,
        system_instruction="You are a strict query reformulation bot. Return your response in JSON format exactly as requested. Never answer the question."
    )

    prompt = QUERY_REWRITER_PROMPT.format(history=history_text, query=query)

    try:
        from typing_extensions import TypedDict
        
        class RewriteSchema(TypedDict):
            rewritten_query: str
            
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=RewriteSchema,
            ),
        )
        import json
        result_json = json.loads(response.text)
        rewritten = result_json.get("rewritten_query", "").strip()

        if not rewritten:
            logger.warning("[Rewriter] Output kosong dari LLM. Kembalikan query asli.")
            return query

        logger.info(f"[Rewriter] Query asli   : '{query}'")
        logger.info(f"[Rewriter] Query hasil  : '{rewritten}'")
        return rewritten

    except Exception as e:
        logger.error(f"[Rewriter] Gagal mereformulasi query: {e}", exc_info=True)
        return query  # Fallback: kembalikan query asli jika LLM error
