"""
workflow.py - LangGraph Agentic Workflow Orchestrator untuk ICICoS 2026 RAG Bot.

Ini adalah otak utama dari Bulletproof Agentic RAG. Menggantikan chain.py
yang menggunakan alur linear. Setiap langkah dimodelkan sebagai Node dalam
sebuah State Machine (Graf berarah).

Alur Utama:
  START
    └─► [node_rewrite_query]   : Reformulasi query menggunakan histori chat
          └─► [node_route]     : Klasifikasi intent (SOP / FAQ / OTHER)
                ├─► [node_ask_clarification]  : (jika ambigu) Kirim pertanyaan klarifikasi
                ├─► [node_retrieve_sop]       : (SOP) Ambil 1 Parent Document utuh
                │     └─► [node_generate_sop] → [node_verify] → END
                ├─► [node_retrieve_faq]       : (FAQ) Ambil FAQ chunks relevan
                │     └─► [node_generate_faq] → [node_verify] → END
                └─► [node_fallback]           : (OTHER / no result) Pesan fallback
                      └─► END

State yang dibawa sepanjang workflow:
  - user_id         : ID user untuk mengambil histori dari DB
  - original_query  : Pertanyaan asli user (tidak dimodifikasi)
  - rewritten_query : Pertanyaan setelah direformulasi
  - intent          : "SOP" | "FAQ" | "OTHER"
  - is_ambiguous    : Apakah perlu klarifikasi?
  - clarification   : Pertanyaan klarifikasi yang akan dikirim ke user
  - sop_doc         : Parent Document SOP hasil retrieval
  - faq_docs        : FAQ chunk list hasil retrieval
  - context_str     : String konteks untuk Verifier
  - answer          : Jawaban final
  - similarity_score: Skor terbaik dari retrieval
  - db_session      : AsyncSession PostgreSQL (diinjeksikan dari luar)
"""
import asyncio
import logging
from functools import partial
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, StateGraph

from backend.rag.generator import (
    FALLBACK_RESPONSE,
    generate_faq_answer,
    generate_sop_answer,
)
from backend.rag.memory import format_history_for_prompt, get_recent_history
from backend.rag.query_rewriter import rewrite_query
from backend.rag.retriever import retrieve_faq, retrieve_sop
from backend.rag.router import RouteResult, classify_intent
from backend.rag.verifier import verify_answer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State Schema — TypedDict yang mendefinisikan semua data yang mengalir
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    """Schema state yang dibawa oleh setiap node dalam workflow."""
    user_id: str
    original_query: str
    rewritten_query: str
    intent: str
    is_ambiguous: bool
    clarification: Optional[str]
    sop_doc: Optional[Document]
    faq_docs: List[Document]
    context_str: str
    answer: str
    similarity_score: float
    db_session: Any  # AsyncSession — tidak bisa di-type-hint ketat di TypedDict


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
    Node 2: Intent Router.
    Mengklasifikasikan pertanyaan (sudah direformulasi) menjadi SOP / FAQ / OTHER
    dan mendeteksi apakah diperlukan klarifikasi lebih lanjut.
    """
    logger.info("[Workflow] ► Node: route")

    result: RouteResult = await asyncio.to_thread(
        classify_intent, state["rewritten_query"]
    )

    return {
        **state,
        "intent": result.intent,
        "is_ambiguous": result.is_ambiguous,
        "clarification": result.clarification_question,
    }


async def node_ask_clarification(state: AgentState) -> AgentState:
    """
    Node 3a: Clarification Request.
    Jika pertanyaan SOP terlalu ambigu, bot mengembalikan pertanyaan klarifikasi
    ke user tanpa melakukan pencarian database sama sekali.
    """
    logger.info("[Workflow] ► Node: ask_clarification (Ambigu terdeteksi)")
    clarification_msg = state.get("clarification") or (
        "Your question covers multiple scenarios. Could you please clarify which "
        "specific procedure or participant category you are asking about?"
    )
    return {**state, "answer": clarification_msg, "similarity_score": 0.0}


async def node_retrieve_sop(state: AgentState) -> AgentState:
    """
    Node 3b: SOP Retrieval.
    Mengambil SATU dokumen SOP utuh menggunakan ParentDocumentRetriever.
    Jaminan: Tidak ada cross-contamination antar SOP.
    """
    logger.info("[Workflow] ► Node: retrieve_sop")

    sop_doc, score = await asyncio.to_thread(
        retrieve_sop, state["rewritten_query"]
    )

    context_str = sop_doc.page_content if sop_doc else ""

    return {**state, "sop_doc": sop_doc, "similarity_score": score, "context_str": context_str}


async def node_retrieve_faq(state: AgentState) -> AgentState:
    """
    Node 3c: FAQ Retrieval.
    Mengambil beberapa FAQ chunk yang relevan dari koleksi histori WhatsApp.
    """
    logger.info("[Workflow] ► Node: retrieve_faq")

    faq_docs, score = await asyncio.to_thread(
        retrieve_faq, state["rewritten_query"]
    )

    context_str = "\n\n---\n\n".join(d.page_content for d in faq_docs) if faq_docs else ""

    return {**state, "faq_docs": faq_docs, "similarity_score": score, "context_str": context_str}


async def node_generate_sop(state: AgentState) -> AgentState:
    """
    Node 4a: SOP Generator.
    Menghasilkan jawaban langkah-demi-langkah yang lengkap menggunakan SOP_SYSTEM_PROMPT.
    """
    logger.info("[Workflow] ► Node: generate_sop")
    sop_doc = state.get("sop_doc")

    if not sop_doc:
        logger.warning("[Workflow] generate_sop dipanggil tanpa sop_doc. Trigger fallback.")
        return {**state, "answer": FALLBACK_RESPONSE}

    answer = await asyncio.to_thread(
        generate_sop_answer, state["rewritten_query"], sop_doc
    )

    return {**state, "answer": answer}


async def node_generate_faq(state: AgentState) -> AgentState:
    """
    Node 4b: FAQ Generator.
    Menghasilkan jawaban singkat (maks 3 kalimat) menggunakan FAQ_SYSTEM_PROMPT.
    """
    logger.info("[Workflow] ► Node: generate_faq")
    faq_docs = state.get("faq_docs", [])

    if not faq_docs:
        logger.warning("[Workflow] generate_faq dipanggil tanpa faq_docs. Trigger fallback.")
        return {**state, "answer": FALLBACK_RESPONSE}

    answer = await asyncio.to_thread(
        generate_faq_answer, state["rewritten_query"], faq_docs
    )

    return {**state, "answer": answer}


async def node_verify(state: AgentState) -> AgentState:
    """
    Node 5: CRAG Verifier (Penjaga Gawang Terakhir).
    Mengevaluasi jawaban yang dihasilkan sebelum dikirim ke user.
    Jika gagal → jawaban diganti dengan FALLBACK_RESPONSE.
    """
    logger.info("[Workflow] ► Node: verify")

    is_valid = await asyncio.to_thread(
        verify_answer,
        state["rewritten_query"],
        state.get("context_str", ""),
        state["answer"],
    )

    if not is_valid:
        logger.warning("[Workflow] Verifikasi GAGAL. Mengganti jawaban dengan fallback.")
        return {**state, "answer": FALLBACK_RESPONSE}

    return state


async def node_fallback(state: AgentState) -> AgentState:
    """
    Node Terminal: Fallback.
    Digunakan ketika intent = OTHER, atau ketika tidak ada dokumen relevan
    yang ditemukan di database.
    """
    logger.info("[Workflow] ► Node: fallback")
    return {**state, "answer": FALLBACK_RESPONSE, "similarity_score": 0.0}


# ---------------------------------------------------------------------------
# Edge Routing Functions
# ---------------------------------------------------------------------------

def route_after_router(state: AgentState) -> str:
    """
    Menentukan node selanjutnya setelah Router menentukan intent.
    """
    intent = state.get("intent", "OTHER")
    is_ambiguous = state.get("is_ambiguous", False)

    if intent == "OTHER":
        logger.info("[Workflow] Edge: OTHER → fallback")
        return "fallback"

    if intent == "SOP" and is_ambiguous:
        logger.info("[Workflow] Edge: SOP (ambigu) → ask_clarification")
        return "ask_clarification"

    if intent == "SOP":
        logger.info("[Workflow] Edge: SOP (jelas) → retrieve_sop")
        return "retrieve_sop"

    # Default: FAQ
    logger.info("[Workflow] Edge: FAQ → retrieve_faq")
    return "retrieve_faq"


def route_after_retrieve_sop(state: AgentState) -> str:
    """
    Setelah retrieval SOP, cek apakah dokumen berhasil ditemukan.
    """
    if state.get("sop_doc") is None:
        logger.info("[Workflow] Edge: SOP doc tidak ditemukan → fallback")
        return "fallback"
    return "generate_sop"


def route_after_retrieve_faq(state: AgentState) -> str:
    """
    Setelah retrieval FAQ, cek apakah ada chunk yang relevan.
    """
    if not state.get("faq_docs"):
        logger.info("[Workflow] Edge: FAQ docs tidak ditemukan → fallback")
        return "fallback"
    return "generate_faq"


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
    graph.add_node("ask_clarification", node_ask_clarification)
    graph.add_node("retrieve_sop", node_retrieve_sop)
    graph.add_node("retrieve_faq", node_retrieve_faq)
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
            "fallback": "fallback",
            "ask_clarification": "ask_clarification",
            "retrieve_sop": "retrieve_sop",
            "retrieve_faq": "retrieve_faq",
        },
    )

    # Alur: SOP path
    graph.add_conditional_edges(
        "retrieve_sop",
        route_after_retrieve_sop,
        {
            "fallback": "fallback",
            "generate_sop": "generate_sop",
        },
    )
    graph.add_edge("generate_sop", "verify")

    # Alur: FAQ path
    graph.add_conditional_edges(
        "retrieve_faq",
        route_after_retrieve_faq,
        {
            "fallback": "fallback",
            "generate_faq": "generate_faq",
        },
    )
    graph.add_edge("generate_faq", "verify")

    # Alur: Terminal nodes
    graph.add_edge("verify", END)
    graph.add_edge("ask_clarification", END)
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
) -> tuple[str, float]:
    """
    Entry point utama untuk menjalankan seluruh Agentic Workflow.
    Dipanggil dari bot/handlers.py sebagai pengganti run_rag_chain().

    Args:
        query     : Pertanyaan teks asli dari user.
        user_id   : ID user (Telegram user ID sebagai string).
        db_session: AsyncSession PostgreSQL untuk mengambil histori chat.
                    Opsional — jika None, Memory dinonaktifkan.

    Returns:
        Tuple[str, float]:
          - str  : Jawaban final yang siap dikirim ke user.
          - float: Similarity score tertinggi dari retrieval (0.0 jika fallback).
    """
    logger.info(
        f"[Workflow] 🚀 Memulai Agentic Workflow untuk user '{user_id}': '{query[:80]}'"
    )

    initial_state: AgentState = {
        "user_id": user_id,
        "original_query": query,
        "rewritten_query": query,  # Default: sama dengan asli (akan di-update Rewriter)
        "intent": "FAQ",
        "is_ambiguous": False,
        "clarification": None,
        "sop_doc": None,
        "faq_docs": [],
        "context_str": "",
        "answer": FALLBACK_RESPONSE,
        "similarity_score": 0.0,
        "db_session": db_session,
    }

    try:
        final_state = await compiled_workflow.ainvoke(initial_state)
        answer = final_state.get("answer", FALLBACK_RESPONSE)
        score = final_state.get("similarity_score", 0.0)

        logger.info(
            f"[Workflow] ✅ Selesai. Score={score:.4f}, "
            f"Panjang jawaban={len(answer)} karakter."
        )
        return answer, score

    except Exception as exc:
        logger.error(
            f"[Workflow] ❌ Error fatal pada Agentic Workflow: {exc}",
            exc_info=True,
        )
        return FALLBACK_RESPONSE, 0.0
