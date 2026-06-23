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
You are a query reformulation assistant. Your ONLY task is to rewrite the user's latest message into a single, self-contained question.

Rules:
1. Read the conversation history to understand context.
2. Replace ALL vague references (like "that", "it", "tadi", "itu", "yang barusan", "yang tadi") with explicit and concrete descriptions from the conversation history.
3. Output ONLY the rewritten question as a single sentence. NO explanations, NO preambles, NO extra text.
4. If the latest message is already self-contained and clear (no ambiguous references), output it UNCHANGED.
5. Output language must match the original language of the latest user message.

Examples:
History: User: "What is the fee for international author?" -> Assistant: "It is $150."
Latest: "how about local?"
Rewritten: How about the fee for local author?

History: User: "Cara daftar ICICoS gimana?" -> Assistant: "Bisa via website."
Latest: "terus bayarnya ke mana?"
Rewritten: Terus bayar pendaftaran ICICoS ke mana?

Conversation History:
{history}

Latest User Message: {query}

Rewritten standalone question:"""


def rewrite_query(query: str, history_text: str) -> str:
    """
    Menyusun ulang pertanyaan user menggunakan konteks histori percakapan.

    Jika histori kosong (percakapan pertama), pertanyaan dikembalikan apa adanya.

    Args:
        query       : Pesan terbaru dari user.
        history_text: Histori percakapan terformat dari memory.format_history_for_prompt().

    Returns:
        String pertanyaan yang sudah direformulasi menjadi kalimat mandiri.
    """
    # Jika tidak ada histori, langsung kembalikan query asli
    if not history_text.strip():
        logger.info("[Rewriter] Tidak ada histori. Query dikembalikan apa adanya.")
        return query

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("[Rewriter] GEMINI_API_KEY tidak ditemukan. Query dikembalikan apa adanya.")
        return query

    genai.configure(api_key=api_key)

    # Gunakan model yang ringan dan cepat untuk tugas rewriting ini
    model_name = os.getenv("GEMINI_FAST_MODEL", "gemini-2.0-flash")
    model = genai.GenerativeModel(
        model_name,
        system_instruction="You are a strict query reformulation bot. Output ONLY the rewritten question as a single sentence. NO explanations, NO markdown, NO preambles like 'Context: '. If no rewrite is needed, output the original query verbatim."
    )

    prompt = QUERY_REWRITER_PROMPT.format(history=history_text, query=query)

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.0,   # Deterministik — tidak ada variasi
                max_output_tokens=256,  # Cukup untuk satu kalimat pertanyaan
            ),
        )
        rewritten = response.text.strip()

        if not rewritten:
            logger.warning("[Rewriter] Output kosong dari LLM. Kembalikan query asli.")
            return query

        logger.info(f"[Rewriter] Query asli   : '{query}'")
        logger.info(f"[Rewriter] Query hasil  : '{rewritten}'")
        return rewritten

    except Exception as e:
        logger.error(f"[Rewriter] Gagal mereformulasi query: {e}", exc_info=True)
        return query  # Fallback: kembalikan query asli jika LLM error
