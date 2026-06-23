"""
router.py - Intent Router & Metadata Extractor untuk Agentic RAG Workflow.

Tanggung jawab:
  Menerima pertanyaan user (yang sudah direformulasi) dan menentukan:
    1. intent      : Apakah pertanyaan ini butuh SOP, FAQ, atau keduanya?
    2. is_ambiguous: Apakah metadata SOP-nya tidak cukup untuk memilih SOP yang tepat?
                     Jika True, workflow akan meminta klarifikasi ke user SEBELUM
                     melakukan pencarian ke database.
    3. metadata    : Informasi tambahan untuk mempersempit pencarian SOP.

Aturan Bisnis:
  - SOP   → Harus dijawab dengan alur LENGKAP dan BERURUTAN. Tidak boleh bolong.
  - FAQ   → Dijawab singkat dan padat. Maksimal 2-3 kalimat.
  - OTHER → Di luar konteks ICICoS. Bot menjawab tidak tahu / suruh hubungi CP.
"""
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, Optional

import google.generativeai as genai

logger = logging.getLogger(__name__)


@dataclass
class RouteResult:
    """Hasil klasifikasi intent dari LLM Router."""
    intent: str                            # "SOP" | "FAQ" | "OTHER"
    is_ambiguous: bool = False             # True jika perlu klarifikasi ke user
    clarification_question: Optional[str] = None  # Pertanyaan klarifikasi ke user
    metadata: Dict[str, str] = field(default_factory=dict)  # Filter metadata SOP


ROUTER_PROMPT = """\
You are an intelligent intent classification system for ICICoS 2026 conference chatbot.

Analyze the user's question and return a JSON object describing the routing decision.

**Intent definitions:**
- "SOP" : The user is asking about a PROCEDURE, STEP-BY-STEP GUIDE, or PROCESS flow (e.g., how to register, how to pay, submission steps, refund procedure). These MUST be answered with complete, ordered steps from the official SOP document.
- "FAQ" : The user is asking a factual, informational question with a SHORT answer (e.g., deadlines, fees, contact info, simple yes/no questions).
- "OTHER": The question is off-topic, a greeting, or completely unrelated to ICICoS 2026.

**Ambiguity rule (CRITICAL for SOP only):**
**Ambiguity rule (CRITICAL for SOP only):**
If intent is "SOP" but the question is too vague/general to identify WHICH specific SOP to use (e.g., "how to register?" without specifying participant category like local/international, author/non-author), set "is_ambiguous" to true and provide a "clarification_question" ALWAYS IN ENGLISH.

**Output format (JSON only, no other text):**
{{
  "intent": "SOP" | "FAQ" | "OTHER",
  "is_ambiguous": true | false,
  "clarification_question": "string or null",
  "metadata": {{
    "topik": "keyword of the main topic (e.g., registrasi, pembayaran, submisi, refund)",
    "kategori_peserta": "lokal | internasional | all (if not specified)",
    "tipe_peserta": "pemakalah | non-pemakalah | all (if not specified)"
  }}
}}

User question: {query}

JSON output:"""


def classify_intent(query: str) -> RouteResult:
    """
    Mengklasifikasikan intent pertanyaan user menggunakan Gemini.

    Args:
        query: Pertanyaan user yang sudah direformulasi oleh Query Rewriter.

    Returns:
        RouteResult berisi intent, is_ambiguous, clarification_question, dan metadata.
        Jika LLM gagal, fallback ke intent FAQ agar sistem tidak crash.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("[Router] GEMINI_API_KEY tidak ditemukan. Fallback ke FAQ.")
        return RouteResult(intent="FAQ")

    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_FAST_MODEL", "gemini-2.0-flash")
    model = genai.GenerativeModel(model_name)

    prompt = ROUTER_PROMPT.format(query=query)

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

        intent = data.get("intent", "FAQ").upper()
        if intent not in ("SOP", "FAQ", "OTHER"):
            intent = "FAQ"

        is_ambiguous = bool(data.get("is_ambiguous", False))
        clarification_question = data.get("clarification_question")
        metadata = data.get("metadata", {})

        result = RouteResult(
            intent=intent,
            is_ambiguous=is_ambiguous,
            clarification_question=clarification_question if is_ambiguous else None,
            metadata=metadata,
        )

        logger.info(
            f"[Router] ✅ Klasifikasi selesai. "
            f"Intent={result.intent}, Ambiguous={result.is_ambiguous}, "
            f"Metadata={result.metadata}"
        )
        return result

    except (json.JSONDecodeError, KeyError) as parse_err:
        logger.error(f"[Router] Gagal mem-parse JSON dari LLM: {parse_err}. Fallback ke FAQ.")
        return RouteResult(intent="FAQ")
    except Exception as e:
        logger.error(f"[Router] Error tak terduga: {e}. Fallback ke FAQ.", exc_info=True)
        return RouteResult(intent="FAQ")
