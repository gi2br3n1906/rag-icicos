"""
workflow.py - LangGraph Agentic Workflow Orchestrator untuk ICICoS 2026 RAG Bot.

Ini adalah otak utama dari Bulletproof Agentic RAG. Menggantikan chain.py
yang menggunakan alur linear. Setiap langkah dimodelkan sebagai Node dalam
sebuah State Machine (Graf berarah).

Alur Utama (Late Routing - Parallel Retrieval):
  START
    └─► [node_rewrite_query]   : Reformulasi query menggunakan histori chat
          └─► [node_route]     : Parallel retrieval SOP & FAQ, routing berdasarkan skor
                ├─► [node_generate_sop] → [node_verify] → END  (SOP ditemukan)
                ├─► [node_generate_faq] → [node_verify] → END  (hanya FAQ ditemukan)
                └─► [node_fallback]                    → END  (tidak ada)

Pendekatan Late Routing (menggantikan LLM-based Router):
  - SOP dan FAQ diretrieval secara PARALEL di node_route menggunakan asyncio.gather.
  - Intent ditentukan secara deterministik berdasarkan similarity score (threshold 0.4):
    * SOP saja    → generate_sop
    * FAQ saja    → generate_faq
    * Keduanya    → generate_sop, has_both=True (bot lampirkan tombol "Show FAQ Answer")
    * Tidak ada   → fallback

State yang dibawa sepanjang workflow:
  - user_id               : ID user untuk mengambil histori dari DB
  - original_query        : Pertanyaan asli user (tidak dimodifikasi)
  - rewritten_query       : Pertanyaan setelah direformulasi
  - intent                : "SOP" | "FAQ" | "OTHER"
  - sop_doc               : Parent Document SOP hasil retrieval (primary/rank-1)
  - faq_docs              : FAQ chunk list hasil retrieval
  - has_both              : True jika query ditemukan di KEDUA database (SOP & FAQ)
  - other_sops            : List dict SOP relevan lainnya [{filename, score}, ...]
  - recommended_questions : List[str] pertanyaan lanjutan yang disarankan (max 3)
  - context_str           : String konteks untuk Verifier
  - answer                : Jawaban final
  - similarity_score      : Skor terbaik dari retrieval
  - db_session            : AsyncSession PostgreSQL (diinjeksikan dari luar)
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, StateGraph

from backend.rag.generator import (
    FALLBACK_RESPONSE,
    _dispatch,
    check_sop_answers_query,
    generate_faq_answer,
    generate_sop_answer,
)
from backend.rag.memory import format_history_for_prompt, get_recent_history
from backend.rag.query_rewriter import rewrite_query
from backend.rag.retriever import get_parent_document_by_filename, retrieve_faq, retrieve_sop
from backend.rag.verifier import verify_answer

logger = logging.getLogger(__name__)

# Threshold minimum similarity score agar retrieval dianggap relevan
RETRIEVAL_THRESHOLD = 0.4


# ---------------------------------------------------------------------------
# Greeting & Bot Identity Responses
# ---------------------------------------------------------------------------
GREETING_RESPONSE = (
    "Hello! 👋 I am the <b>Official Assistant of ICICoS 2026</b>.\n\n"
    "I am here to guide you through the official procedures and answer FAQs for "
    "the 9th International Conference on Informatics and Computational Sciences (ICICoS 2026).\n\n"
    "You can ask me about:\n"
    "• <b>Paper Submission Guidelines</b> (format, template, IEEE PDF eXpress, etc.)\n"
    "• <b>Registration & Payments</b> (fees, virtual account bank transfer, mBanking, etc.)\n"
    "• <b>Important Dates & Timeline</b>\n\n"
    "How can I help you today? 😊"
)

DEFAULT_RECOMMENDED_QUESTIONS = [
    "What is the registration payment procedure?",
    "How do I use IEEE PDF eXpress?",
    "What is the paper format guideline?"
]


def check_is_greeting_or_identity(query: str) -> bool:
    """
    Cek apakah query adalah salam (greeting), ucapan terima kasih, atau pertanyaan identitas bot.
    """
    # 1. Quick regex check first to save tokens
    q_lower = query.lower().strip().strip("?").strip("!").strip(".")
    greetings = {
        "hello", "hi", "halo", "hei", "hey", "p", "assalamualaikum", "selamat pagi", "selamat siang", "selamat sore", "selamat malam",
        "who are you", "siapa kamu", "siapa anda", "what are you", "what is your name", "siapa namamu", "siapa nama kamu", "bot",
        "thank you", "thanks", "terima kasih", "makasih", "suwun", "hatur nuhun"
    }
    if q_lower in greetings or any(g in q_lower for g in ["who are you", "siapa kamu", "siapa anda", "your name"]):
        return True

    # 2. Check via quick LLM prompt for typos or other variations (e.g. "wgo are you")
    prompt = f"""You are a query classifier. Determine if the user's input is a greeting (e.g. "hello", "hi"), a thank you (e.g. "thanks"), or a question asking about your identity/who you are (e.g. "who are you", "what is your role").
    
    Answer exactly with YES or NO.
    
    User input: "{query}"
    """
    try:
        res = _dispatch(prompt).strip().upper()
        return res.startswith("YES")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# State Schema — TypedDict yang mendefinisikan semua data yang mengalir
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    """Schema state yang dibawa oleh setiap node dalam workflow."""
    user_id: str
    original_query: str
    rewritten_query: str
    intent: str                     # "SOP" | "FAQ" | "OTHER"
    sop_doc: Optional[Document]
    faq_docs: List[Document]
    has_both: bool                  # True jika ditemukan di kedua database
    other_sops: List[Dict]          # SOP relevan lainnya selain rank-1
    recommended_questions: List[str]  # Pertanyaan lanjutan dari LLM
    context_str: str
    answer: str
    similarity_score: float
    db_session: Any                 # AsyncSession — tidak bisa di-type-hint ketat di TypedDict
    is_recommendation: bool         # True jika ini dari klik tombol saran


# ---------------------------------------------------------------------------
# Node Definitions
# ---------------------------------------------------------------------------

async def node_rewrite_query(state: AgentState) -> AgentState:
    """
    Node 1: Query Rewriter.
    Mengambil histori percakapan dari PostgreSQL dan mereformulasi pertanyaan
    user agar bebas dari kata ganti ambigu (tadi, itu, yang barusan, dll).
    """
    logger.info("[Workflow] ► Node: rewrite_query")
    db = state.get("db_session")

    history = []
    if db:
        history = await get_recent_history(state["user_id"], db)

    history_text = format_history_for_prompt(history)

    # Rewriting dijalankan di thread pool agar tidak block event loop
    rewritten = await asyncio.to_thread(
        rewrite_query, state["original_query"], history_text
    )

    return {**state, "rewritten_query": rewritten}


async def node_route(state: AgentState) -> AgentState:
    """
    Node 2: Parallel Retrieval + Late Routing.

    Menggantikan LLM-based Router dengan pendekatan deterministik:
    1. Retrieval SOP dan FAQ dijalankan secara PARALEL menggunakan asyncio.gather.
    2. Intent ditentukan berdasarkan similarity score dari hasil retrieval:
       - score_sop >= 0.4 DAN score_faq >= 0.4 → intent=SOP, has_both=True
       - Hanya score_sop >= 0.4                 → intent=SOP, has_both=False
       - Hanya score_faq >= 0.4                 → intent=FAQ, has_both=False
       - Tidak ada yang memenuhi threshold       → intent=OTHER
    3. other_sops diisi dari hasil retrieve_sop.

    Keuntungan: tidak ada mismatch klasifikasi karena routing didasarkan pada
    data yang benar-benar ada di database, bukan prediksi LLM.
    """
    logger.info("[Workflow] ► Node: route (Parallel Retrieval)")

    query = state["rewritten_query"]

    # Cek apakah query berupa greeting / identity query
    is_greeting = await asyncio.to_thread(check_is_greeting_or_identity, query)
    if is_greeting:
        logger.info("[Workflow] Mendeteksi greeting/identity query di Router. Bypass retrieval.")
        return {
            **state,
            "intent": "OTHER",
            "sop_doc": None,
            "faq_docs": [],
            "has_both": False,
            "other_sops": [],
            "similarity_score": 1.0,
            "context_str": "",
        }

    threshold = 0.3 if state.get("is_recommendation") else RETRIEVAL_THRESHOLD

    # Jalankan retrieval SOP dan FAQ secara paralel
    (sop_doc, score_sop, other_sops), (faq_docs, score_faq) = await asyncio.gather(
        asyncio.to_thread(retrieve_sop, query, threshold),
        asyncio.to_thread(retrieve_faq, query, threshold),
    )

    sop_available = sop_doc is not None and score_sop >= threshold
    faq_available = len(faq_docs) > 0 and score_faq >= threshold

    # Tentukan intent dan has_both secara deterministik
    if sop_available and faq_available:
        intent = "SOP"
        has_both = True
        similarity_score = score_sop
        context_str = sop_doc.page_content
        logger.info(
            f"[Workflow] Late Routing: BOTH found. "
            f"SOP score={score_sop:.4f}, FAQ score={score_faq:.4f} → intent=SOP, has_both=True"
        )
    elif sop_available:
        intent = "SOP"
        has_both = False
        similarity_score = score_sop
        context_str = sop_doc.page_content
        logger.info(f"[Workflow] Late Routing: SOP only. score={score_sop:.4f} → intent=SOP")
    elif faq_available:
        intent = "FAQ"
        has_both = False
        similarity_score = score_faq
        context_str = "\n\n---\n\n".join(d.page_content for d in faq_docs)
        logger.info(f"[Workflow] Late Routing: FAQ only. score={score_faq:.4f} → intent=FAQ")
    else:
        intent = "OTHER"
        has_both = False
        similarity_score = max(score_sop, score_faq)
        context_str = ""
        logger.info(
            f"[Workflow] Late Routing: Nothing found. "
            f"SOP={score_sop:.4f}, FAQ={score_faq:.4f} → fallback"
        )

    if other_sops:
        logger.info(
            f"[Workflow] Other relevant SOPs detected: "
            f"{[o['filename'] for o in other_sops]}"
        )

    return {
        **state,
        "intent": intent,
        "sop_doc": sop_doc,
        "faq_docs": faq_docs,
        "has_both": has_both,
        "other_sops": other_sops,
        "similarity_score": similarity_score,
        "context_str": context_str,
    }


async def _validate_other_sop(query: str, sop_info: Dict) -> Optional[Dict]:
    """
    Validasi apakah sebuah SOP kandidat benar-benar dapat menjawab query user.

    Menggunakan check_sop_answers_query() — binary YES/NO classifier yang
    mengirim prompt khusus ke LLM. Tidak menghasilkan jawaban (tidak seperti
    generate_sop_answer), sehingga tidak ada kasus LLM generate 'not available'
    yang terlewat oleh verifier.

    Dijalankan secara paralel untuk semua kandidat via asyncio.gather.
    """
    filename = sop_info.get("filename", "")
    try:
        sop_doc = await asyncio.to_thread(get_parent_document_by_filename, filename)
        if sop_doc is None:
            logger.warning(f"[Workflow] Validasi other_sop: '{filename}' tidak ditemukan di docstore.")
            return None

        is_relevant = await asyncio.to_thread(check_sop_answers_query, query, sop_doc)

        if not is_relevant:
            logger.info(f"[Workflow] Validasi other_sop: '{filename}' → GAGAL (binary check: NO).")
            return None

        logger.info(f"[Workflow] Validasi other_sop: '{filename}' → LULUS (binary check: YES).")
        return sop_info

    except Exception as exc:
        logger.error(f"[Workflow] Error saat validasi other_sop '{filename}': {exc}", exc_info=True)
        return None


async def node_generate_sop(state: AgentState) -> AgentState:
    """
    Node 3a: SOP Generator.
    Menghasilkan jawaban dari primary SOP dan memvalidasi other_sops secara paralel.

    Pre-generation binary check (NEW):
      Sebelum memanggil LLM untuk menghasilkan jawaban dari SOP primer, sistem
      menjalankan binary classifier (check_sop_answers_query) terlebih dahulu.

      - Jika SOP primer TIDAK relevan (classifier: NO) DAN has_both=True:
          → Pivot langsung ke FAQ generation. Tidak ada LLM call SOP yang sia-sia.
          → has_both di-set False agar tombol "Show FAQ" tidak double.
      - Jika SOP primer TIDAK relevan (classifier: NO) DAN has_both=False:
          → Langsung return FALLBACK_RESPONSE tanpa memanggil LLM sama sekali.
      - Jika SOP primer RELEVAN (classifier: YES):
          → Generate jawaban SOP + validasi other_sops secara paralel seperti biasa.

    Tujuan: mencegah verifier menyetujui jawaban SOP "tidak ditemukan" yang jujur
    tapi tidak berguna, yang akhirnya memblokir jawaban FAQ yang lebih relevan.
    """
    logger.info("[Workflow] ► Node: generate_sop")
    sop_doc = state.get("sop_doc")
    query = state["rewritten_query"]
    other_sops_candidates = state.get("other_sops", [])
    has_both = state.get("has_both", False)
    faq_docs = state.get("faq_docs", [])

    if not sop_doc:
        logger.warning("[Workflow] generate_sop dipanggil tanpa sop_doc. Trigger fallback.")
        return {**state, "answer": FALLBACK_RESPONSE, "recommended_questions": [], "other_sops": []}

    # --- Pre-generation binary check pada SOP primer ---
    primary_is_relevant = await asyncio.to_thread(check_sop_answers_query, query, sop_doc)

    if not primary_is_relevant:
        sop_name = sop_doc.metadata.get("source", "primary SOP")
        if has_both and faq_docs:
            # Pivot ke FAQ: SOP primer tidak relevan, tapi FAQ punya jawabannya
            logger.info(
                f"[Workflow] Primary SOP '{sop_name}' TIDAK relevan (binary: NO) & has_both=True. "
                "Pivot ke FAQ generation."
            )
            faq_answer, faq_follow_ups = await asyncio.to_thread(
                generate_faq_answer, query, faq_docs
            )
            faq_context_str = "\n\n---\n\n".join(d.page_content for d in faq_docs)
            return {
                **state,
                "answer": faq_answer,
                "recommended_questions": faq_follow_ups,
                "other_sops": [],
                "has_both": False,      # Jawaban FAQ sudah jadi utama; jangan tampilkan tombol FAQ lagi
                "intent": "FAQ",
                "context_str": faq_context_str,
            }
        else:
            # Tidak ada alternatif — langsung fallback tanpa LLM call
            logger.info(
                f"[Workflow] Primary SOP '{sop_name}' TIDAK relevan (binary: NO) & has_both=False. "
                "Return FALLBACK tanpa LLM call."
            )
            return {**state, "answer": FALLBACK_RESPONSE, "recommended_questions": [], "other_sops": []}

    # --- SOP relevan: generate jawaban + validasi other_sops secara paralel ---
    tasks = [asyncio.to_thread(generate_sop_answer, query, sop_doc)]
    for sop_info in other_sops_candidates:
        tasks.append(_validate_other_sop(query, sop_info))

    results = await asyncio.gather(*tasks)

    answer, follow_ups = results[0]
    validated_sops = [r for r in results[1:] if r is not None]

    if other_sops_candidates:
        logger.info(
            f"[Workflow] Validasi other_sops selesai: "
            f"{len(other_sops_candidates)} kandidat → {len(validated_sops)} lolos."
        )

    logger.info(f"[Workflow] SOP answer generated. Follow-ups: {follow_ups}")
    return {**state, "answer": answer, "recommended_questions": follow_ups, "other_sops": validated_sops}



async def node_generate_faq(state: AgentState) -> AgentState:
    """
    Node 3b: FAQ Generator.
    Menghasilkan jawaban singkat (maks 3 kalimat) menggunakan FAQ_SYSTEM_PROMPT.
    Juga mengekstrak pertanyaan lanjutan dari output LLM.
    """
    logger.info("[Workflow] ► Node: generate_faq")
    faq_docs = state.get("faq_docs", [])

    if not faq_docs:
        logger.warning("[Workflow] generate_faq dipanggil tanpa faq_docs. Trigger fallback.")
        return {**state, "answer": FALLBACK_RESPONSE, "recommended_questions": []}

    answer, follow_ups = await asyncio.to_thread(
        generate_faq_answer, state["rewritten_query"], faq_docs
    )

    logger.info(f"[Workflow] FAQ answer generated. Follow-ups: {follow_ups}")
    return {**state, "answer": answer, "recommended_questions": follow_ups}


async def node_verify(state: AgentState) -> AgentState:
    """
    Node 4: CRAG Verifier (Penjaga Gawang Terakhir).
    Mengevaluasi jawaban yang dihasilkan sebelum dikirim ke user.

    Logika Self-Healing:
      Jika jawaban SOP primer gagal verifikasi DAN state memiliki has_both=True
      (artinya FAQ database juga punya dokumen relevan), maka:
        1. Generate jawaban dari faq_docs.
        2. Verifikasi jawaban FAQ terhadap konteks FAQ.
        3. Jika lulus → kirim jawaban FAQ, set has_both=False (tombol FAQ tidak double).
        4. Jika juga gagal → baru kembalikan FALLBACK_RESPONSE.
    """
    logger.info("[Workflow] ► Node: verify")

    is_valid = await asyncio.to_thread(
        verify_answer,
        state["rewritten_query"],
        state.get("context_str", ""),
        state["answer"],
    )

    if not is_valid:
        # --- Self-Healing: Coba fallback ke FAQ jika tersedia ---
        has_both = state.get("has_both", False)
        faq_docs = state.get("faq_docs", [])

        if has_both and faq_docs:
            logger.info(
                "[Workflow] Verifikasi SOP GAGAL. Self-healing: mencoba generate jawaban dari FAQ..."
            )
            faq_answer, faq_follow_ups = await asyncio.to_thread(
                generate_faq_answer, state["rewritten_query"], faq_docs
            )

            # Bangun konteks FAQ untuk verifier
            faq_context_str = "\n\n---\n\n".join(d.page_content for d in faq_docs)

            faq_is_valid = await asyncio.to_thread(
                verify_answer,
                state["rewritten_query"],
                faq_context_str,
                faq_answer,
            )

            if faq_is_valid:
                logger.info(
                    "[Workflow] Self-healing berhasil: jawaban FAQ lulus verifikasi. "
                    "Mengganti jawaban SOP dengan jawaban FAQ."
                )
                return {
                    **state,
                    "answer": faq_answer,
                    "recommended_questions": faq_follow_ups,
                    "has_both": False,      # Jawaban FAQ sudah jadi jawaban utama; sembunyikan tombol FAQ
                    "intent": "FAQ",
                }
            else:
                logger.warning(
                    "[Workflow] Self-healing GAGAL: jawaban FAQ juga tidak lulus verifikasi. "
                    "Mengembalikan FALLBACK_RESPONSE."
                )
        else:
            logger.warning("[Workflow] Verifikasi GAGAL. Mengganti jawaban dengan fallback.")

        return {**state, "answer": FALLBACK_RESPONSE}

    return state



async def node_fallback(state: AgentState) -> AgentState:
    """
    Node Terminal: Fallback.
    Digunakan ketika intent = OTHER, atau ketika tidak ada dokumen relevan
    yang ditemukan di database.

    Jika query berupa greeting / identity check, berikan penjelasan yang ramah
    tentang identitas bot (GREETING_RESPONSE).
    """
    logger.info("[Workflow] ► Node: fallback")
    query = state["rewritten_query"]
    is_greeting = await asyncio.to_thread(check_is_greeting_or_identity, query)

    if is_greeting:
        logger.info("[Workflow] Fallback mendeteksi greeting/identity query. Mengirim GREETING_RESPONSE.")
        return {
            **state,
            "answer": GREETING_RESPONSE,
            "similarity_score": 1.0,
            "recommended_questions": DEFAULT_RECOMMENDED_QUESTIONS
        }

    return {**state, "answer": FALLBACK_RESPONSE, "similarity_score": 0.0, "recommended_questions": []}



# ---------------------------------------------------------------------------
# Edge Routing Functions
# ---------------------------------------------------------------------------

def route_after_router(state: AgentState) -> str:
    """Menentukan node selanjutnya setelah Parallel Retrieval."""
    intent = state.get("intent", "OTHER")
    if intent == "SOP":
        return "generate_sop"
    elif intent == "FAQ":
        return "generate_faq"
    return "fallback"


# ---------------------------------------------------------------------------
# Build & Compile the LangGraph Workflow
# ---------------------------------------------------------------------------

def build_workflow():
    """
    Merakit semua node dan edge menjadi satu LangGraph StateGraph yang terkompilasi.

    Returns:
        CompiledGraph yang siap dijalankan dengan .ainvoke().
    """
    graph = StateGraph(AgentState)

    # Daftarkan semua node
    graph.add_node("rewrite_query", node_rewrite_query)
    graph.add_node("route", node_route)
    graph.add_node("generate_sop", node_generate_sop)
    graph.add_node("generate_faq", node_generate_faq)
    graph.add_node("verify", node_verify)
    graph.add_node("fallback", node_fallback)

    # Alur: Entry point
    graph.set_entry_point("rewrite_query")
    graph.add_edge("rewrite_query", "route")

    # Alur: Setelah Router (bercabang)
    graph.add_conditional_edges(
        "route",
        route_after_router,
        {
            "generate_sop": "generate_sop",
            "generate_faq": "generate_faq",
            "fallback": "fallback",
        },
    )

    # Alur: Terminal nodes
    graph.add_edge("generate_sop", "verify")
    graph.add_edge("generate_faq", "verify")
    graph.add_edge("verify", END)
    graph.add_edge("fallback", END)

    return graph.compile()


# Instansiasi graf sekali saja saat modul di-import (singleton)
compiled_workflow = build_workflow()


# ---------------------------------------------------------------------------
# Public Entry Point: run_agentic_workflow()
# ---------------------------------------------------------------------------

async def run_agentic_workflow(
    query: str,
    user_id: str,
    db_session: Any = None,
    is_recommendation: bool = False,
) -> Tuple[str, float, bool, List[Dict], List[str]]:
    """
    Entry point utama untuk menjalankan seluruh Agentic Workflow.
    Dipanggil dari bot/handlers.py.

    Args:
        query             : Pertanyaan teks asli dari user.
        user_id           : ID user (Telegram user ID sebagai string).
        db_session        : AsyncSession PostgreSQL untuk mengambil histori chat.
        is_recommendation : True jika ini merupakan pertanyaan lanjutan yang disarankan.

    Returns:
        Tuple[str, float, bool, List[Dict], List[str]]:
          - str        : Jawaban final yang siap dikirim ke user.
          - float      : Similarity score tertinggi dari retrieval.
          - bool       : has_both — True jika ada jawaban di SOP & FAQ.
          - List[Dict] : other_sops — daftar SOP relevan lainnya.
          - List[str]  : recommended_questions — pertanyaan lanjutan yang disarankan.
    """
    logger.info(
        f"[Workflow] 🚀 Memulai Agentic Workflow untuk user '{user_id}': '{query[:80]}'"
    )

    initial_state: AgentState = {
        "user_id": user_id,
        "original_query": query,
        "rewritten_query": query,
        "intent": "OTHER",
        "sop_doc": None,
        "faq_docs": [],
        "has_both": False,
        "other_sops": [],
        "recommended_questions": [],
        "context_str": "",
        "answer": FALLBACK_RESPONSE,
        "similarity_score": 0.0,
        "db_session": db_session,
        "is_recommendation": is_recommendation,
    }

    try:
        final_state = await compiled_workflow.ainvoke(initial_state)
        answer = final_state.get("answer", FALLBACK_RESPONSE)
        score = final_state.get("similarity_score", 0.0)
        has_both = final_state.get("has_both", False)
        other_sops = final_state.get("other_sops", [])
        recommended_questions = final_state.get("recommended_questions", [])

        logger.info(
            f"[Workflow] ✅ Selesai. Score={score:.4f}, has_both={has_both}, "
            f"other_sops={len(other_sops)}, follow_ups={len(recommended_questions)}, "
            f"Panjang jawaban={len(answer)} karakter."
        )
        return answer, score, has_both, other_sops, recommended_questions

    except Exception as exc:
        logger.error(
            f"[Workflow] ❌ Error fatal pada Agentic Workflow: {exc}",
            exc_info=True,
        )
        return FALLBACK_RESPONSE, 0.0, False, [], []
