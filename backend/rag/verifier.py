"""
verifier.py - Corrective RAG (CRAG) Evaluator untuk Agentic RAG Workflow.

Tanggung jawab:
  Menerima draf jawaban yang sudah di-generate dan mengevaluasinya terhadap
  dua kriteria:
    1. Relevansi    : Apakah konteks yang diambil dari DB benar-benar relevan
                      dengan pertanyaan user?
    2. Kelengkapan  : Untuk jalur SOP, apakah semua langkah dari sumber asli
                      tercermin dalam jawaban? Tidak ada yang terlewat?

Jika evaluasi GAGAL:
  - Jawaban draf dibuang.
  - Sistem mengembalikan sinyal "failed" dan workflow akan memicu FALLBACK_RESPONSE.

Ini adalah safety net terakhir sebelum jawaban dikirim ke user.
"""
import json
import logging
import os

import google.generativeai as genai

logger = logging.getLogger(__name__)

VERIFIER_PROMPT = """\
You are a quality control evaluator for an AI assistant's responses.

Your task is to evaluate whether the generated answer is:
1. **Grounded**: Does the answer ONLY use information from the provided context? (No hallucination)
2. **Complete** (for SOP answers): Does the answer include all steps/points from the context that are directly relevant to the user's question? (It should NOT include unrelated parts of the SOP).
3. **Relevant**: Does the answer actually address what the user asked?
4. **Author-Centric & Blackboxed**: Is the answer written from the Author's point of view? Does it treat the internal activities of the committee (Treasurer, Secretary, etc.) as a black box (summarized simply without detailing spreadsheet checks, decision gateways, or internal workflows)?

**Context (source of truth):**
{context}

**User's question:**
{question}

**Generated answer to evaluate:**
{answer}

Return a JSON object ONLY:
{{
  "is_valid": true | false,
  "reason": "Brief explanation of why it passed or failed"
}}

- Set "is_valid" to true ONLY if ALL criteria above are satisfied.
- Set "is_valid" to false if the answer hallucinates, misses important relevant steps, details internal committee workflows, or is off-topic.

JSON output:"""


def verify_answer(query: str, context: str, answer: str) -> bool:
    """
    Mengevaluasi kualitas draf jawaban sebelum dikirim ke user.

    Args:
        query  : Pertanyaan user (sudah direformulasi).
        context: String konteks mentah yang dikirim ke LLM Generator
                 (bisa berisi SOP utuh atau FAQ chunks).
        answer : Draf jawaban yang dihasilkan oleh Generator.

    Returns:
        True  → Jawaban lulus evaluasi, aman untuk dikirim ke user.
        False → Jawaban gagal evaluasi, trigger FALLBACK_RESPONSE.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        # Jika verifier tidak bisa berjalan, anggap valid (fail open)
        logger.warning("[Verifier] GEMINI_API_KEY tidak ditemukan. Melewati verifikasi (fail open).")
        return True

    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_FAST_MODEL", "gemini-2.0-flash")
    model = genai.GenerativeModel(model_name)

    # Batasi panjang konteks yang dikirim ke verifier agar hemat token
    truncated_context = context[:4000] if len(context) > 4000 else context

    prompt = VERIFIER_PROMPT.format(
        context=truncated_context,
        question=query,
        answer=answer,
    )

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )

        raw = response.text.strip()
        data = json.loads(raw)
        is_valid = bool(data.get("is_valid", True))
        reason = data.get("reason", "No reason provided.")

        if is_valid:
            logger.info(f"[Verifier] ✅ Jawaban LULUS verifikasi. Alasan: {reason}")
        else:
            logger.warning(f"[Verifier] ❌ Jawaban GAGAL verifikasi. Alasan: {reason}")

        return is_valid

    except (json.JSONDecodeError, KeyError) as parse_err:
        logger.error(f"[Verifier] Gagal mem-parse JSON verifikasi: {parse_err}. Fail open.")
        return True  # Fail open: jika verifier error, tetap lanjutkan
    except Exception as e:
        logger.error(f"[Verifier] Error tak terduga: {e}. Fail open.", exc_info=True)
        return True  # Fail open
