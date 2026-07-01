"""
handlers.py - Kumpulan handler utama untuk Telegram Bot ICICoS 2026.
Setiap fungsi di sini di-register ke Application di bot_runner.py.

Alur handle_message:
  Pesan masuk
    → kirim "typing..."
    → RAG chain (retrieve + generate) → Tuple[answer, score, has_both, other_sops, rec_questions]
    → format HTML (bold/italic)
    → kirim jawaban ke user dengan tombol inline:
        * "Show FAQ Answer" (jika has_both=True)
        * Tombol SOP lain (jika other_sops tidak kosong)
        * Tombol pertanyaan lanjutan (jika recommended_questions tidak kosong)
    → logging ke PostgreSQL (fire-and-forget, tidak crash bot jika gagal)
"""
import asyncio
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from backend.rag.workflow import run_agentic_workflow
from backend.rag.generator import FALLBACK_RESPONSE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: Format Output LLM → HTML Telegram
# ---------------------------------------------------------------------------

def format_llm_output(text: str) -> str:
    """
    Mengkonversi format Markdown standar output LLM menjadi tag HTML
    yang dikenali Telegram.

    Urutan konversi (urutan PENTING):
      1. **bold** → <b>bold</b>  (diproses lebih dulu agar ** tidak
         dikira dua token italic)
      2. *italic* → <i>italic</i>

    Args:
        text: String output mentah dari LLM.

    Returns:
        String dengan tag HTML siap dikirim ke Telegram.
    """
    # Langkah 1: Konversi **bold** → <b>bold</b>
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)

    # Langkah 2: Konversi *italic* → <i>italic</i>
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)

    return text


# ---------------------------------------------------------------------------
# Helper: Logging percakapan ke PostgreSQL
# ---------------------------------------------------------------------------

async def _log_chat_to_db(
    user_id: str,
    query: str,
    answer: str,
    similarity_score: float,
) -> None:
    """
    Menyimpan satu record percakapan ke tabel `chat_logs` di PostgreSQL.

    Fungsi ini bersifat fire-and-forget — kegagalan logging TIDAK boleh
    menghentikan atau menginterupsi pengiriman jawaban ke user Telegram.

    Args:
        user_id         : Telegram user ID sebagai string.
        query           : Pertanyaan asli dari user.
        answer          : Jawaban teks final (sudah di-format HTML).
        similarity_score: Skor retrieval tertinggi (0.0 jika fallback).
    """
    try:
        from backend.api.database import AsyncSessionLocal
        from backend.api.models import ChatLog

        new_log = ChatLog(
            user_id=user_id,
            query=query,
            answer=answer,
            similarity_score=float(similarity_score),
        )

        async with AsyncSessionLocal() as session:
            session.add(new_log)
            await session.commit()

        logger.info(
            f"[DB Log] ✅ Chat log berhasil disimpan untuk user {user_id}. "
            f"Score: {similarity_score:.4f}"
        )

    except Exception as db_exc:
        logger.error(
            f"[DB Log] ❌ Gagal menyimpan chat log untuk user {user_id}: {db_exc}",
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Helper: Build inline keyboard dengan tombol SOP, FAQ, dan follow-up questions
# ---------------------------------------------------------------------------

def _build_inline_keyboard(
    has_both: bool,
    other_sops: list,
    recommended_questions: list,
) -> InlineKeyboardMarkup | None:
    """
    Membangun InlineKeyboardMarkup secara dinamis berdasarkan konten yang tersedia.

    Layout:
      - Baris 1: Tombol "Show FAQ Answer" (jika has_both=True)
      - Baris 2+: Satu tombol per SOP relevan lainnya
      - Baris terakhir: Tombol pertanyaan lanjutan (satu per baris, max 3)

    Returns:
        InlineKeyboardMarkup atau None jika tidak ada tombol yang perlu ditampilkan.
    """
    rows = []

    # --- Baris 1: FAQ shortcut ---
    if has_both:
        rows.append([InlineKeyboardButton("📖 Show FAQ Answer", callback_data="show_faq")])

    # --- Baris 2+: SOP lain yang relevan ---
    for idx, sop in enumerate(other_sops):
        filename = sop.get("filename", "")
        label = filename.replace(".pdf", "").replace("_", " ")
        # Gunakan indeks pendek (sop:0, sop:1) agar aman dari batas 64-byte Telegram.
        # Filename asli disimpan di context.user_data["other_sops"].
        rows.append([
            InlineKeyboardButton(
                f"🔍 Explore: {label}",
                callback_data=f"sop:{idx}"
            )
        ])

    # --- Baris pertanyaan lanjutan ---
    for idx, question in enumerate(recommended_questions[:3]):
        # Label tombol bisa hingga 200 karakter (batas Telegram).
        # Batas 64-byte hanya berlaku untuk callback_data (sudah aman: "rec:0" dll).
        rows.append([
            InlineKeyboardButton(f"❓ {question}", callback_data=f"rec:{idx}")
        ])

    if not rows:
        return None

    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /start command. Displays a welcome message."""
    user = update.effective_user
    welcome_message = (
        f"Hello, {user.first_name}! 👋\n\n"
        "I am the <b>Official Assistant of ICICoS 2026</b> 🎓\n"
        "(The 9th International Conference on Informatics and Computational Sciences)\n\n"
        "I am here to help you with questions about:\n"
        "• Paper Submission Guidelines\n"
        "• Registration Payment Procedures\n"
        "• Conference Schedule & Timeline\n"
        "• And other official conference information\n\n"
        "Feel free to type your question directly — in English or Bahasa Indonesia!"
    )
    await update.message.reply_text(welcome_message, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /help command."""
    help_text = (
        "📚 <b>How to Use the ICICoS 2026 Bot:</b>\n\n"
        "Simply type your question in English or Bahasa Indonesia.\n\n"
        "<b>Example questions:</b>\n"
        "• <i>How do I complete the registration payment?</i>\n"
        "• <i>What paper format is accepted?</i>\n"
        "• <i>What is the submission deadline?</i>\n"
        "• <i>Where can I find the paper template?</i>\n\n"
        "If the bot cannot answer your question, please contact the organizing committee directly."
    )
    await update.message.reply_text(help_text, parse_mode="HTML")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /reset command. Clears the user's chat history from the database."""
    user = update.effective_user

    try:
        from backend.api.database import AsyncSessionLocal
        from backend.api.models import ChatLog
        from sqlalchemy import delete

        async with AsyncSessionLocal() as session:
            stmt = delete(ChatLog).where(ChatLog.user_id == str(user.id))
            await session.execute(stmt)
            await session.commit()

        logger.info(f"[Bot] Histori chat di-reset untuk user {user.id}")
        await update.message.reply_text(
            "✅ <b>Your chat history has been cleared!</b>\n"
            "I have forgotten our previous conversation context. We can start fresh!",
            parse_mode="HTML"
        )
    except Exception as exc:
        logger.error(f"[Bot] Gagal mereset histori untuk user {user.id}: {exc}", exc_info=True)
        await update.message.reply_text("⚠️ Sorry, I encountered an error while trying to reset your chat history.")


# ---------------------------------------------------------------------------
# Message Handler Utama
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler utama untuk pesan teks dari user.

    Alur:
      1. Catat query ke log.
      2. Kirim sinyal ChatAction.TYPING.
      3. Jalankan RAG chain → mendapatkan Tuple[jawaban, score, has_both, other_sops, rec_qs].
      4. Simpan recommended_questions di context.user_data untuk diambil callback handler.
      5. Format jawaban dari Markdown LLM ke HTML Telegram.
      6. Bangun InlineKeyboardMarkup secara dinamis.
      7. Kirim jawaban ke user.
      8. Simpan log percakapan ke PostgreSQL (fire-and-forget).
    """
    user = update.effective_user
    user_query = update.message.text

    logger.info(
        f"[Bot] Pesan masuk dari user {user.id} (@{user.username}): '{user_query}'"
    )

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    answer: str = ""
    similarity_score: float = 0.0
    has_both: bool = False
    other_sops: list = []
    recommended_questions: list = []

    try:
        from backend.api.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db_session:
            answer, similarity_score, has_both, other_sops, recommended_questions = (
                await run_agentic_workflow(
                    query=user_query,
                    user_id=str(user.id),
                    db_session=db_session,
                )
            )

        logger.info(
            f"[Bot] Jawaban di-generate untuk user {user.id}. "
            f"Score: {similarity_score:.4f}, has_both={has_both}, "
            f"other_sops={len(other_sops)}, rec_qs={len(recommended_questions)}, "
            f"Panjang: {len(answer)} karakter."
        )

    except Exception as exc:
        logger.error(
            f"[Bot] Error saat memproses query dari user {user.id}: {exc}",
            exc_info=True,
        )
        answer = (
            "⚠️ Sorry, a technical error occurred while processing your question. "
            "Please try again in a moment, or contact the ICICoS 2026 organizing committee "
            "directly if the problem persists."
        )

    is_fallback = (answer == FALLBACK_RESPONSE)

    # Simpan konteks rekomendasi di sesi user agar bisa diakses callback handler
    if not is_fallback:
        context.user_data["rec_queries"] = recommended_questions
        context.user_data["other_sops"] = other_sops  # simpan list agar sop:<idx> callback bisa akses filename
        context.user_data["last_query"] = user_query
    else:
        context.user_data["rec_queries"] = []
        context.user_data["other_sops"] = []
        context.user_data["last_query"] = None

    # Format jawaban (bold/italic LLM → HTML Telegram)
    formatted_answer = format_llm_output(answer)

    # Tambahkan penanda jika ada SOP/FAQ lain yang tersedia
    extra_info_parts = []
    if not is_fallback:
        if has_both:
            extra_info_parts.append(
                "💡 <i>A short community FAQ answer is also available for this topic.</i>"
            )
        if other_sops:
            names = ", ".join(
                s["filename"].replace(".pdf", "").replace("_", " ")
                for s in other_sops
            )
            extra_info_parts.append(
                f"🔍 <i>Related document available: {names}. Content may differ from this answer.</i>"
            )

    if extra_info_parts:
        formatted_answer += "\n\n" + "\n".join(extra_info_parts)

    # Bangun keyboard tombol inline
    reply_markup = _build_inline_keyboard(
        has_both if not is_fallback else False,
        other_sops if not is_fallback else [],
        recommended_questions if not is_fallback else []
    )

    from telegram.error import BadRequest

    try:
        await update.message.reply_text(
            formatted_answer,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except BadRequest as e:
        logger.warning(f"[Bot] Gagal parse HTML ({e}), fallback ke plain text.")
        await update.message.reply_text(answer, reply_markup=reply_markup)

    # Simpan log ke database (fire-and-forget)
    await _log_chat_to_db(
        user_id=str(user.id),
        query=user_query,
        answer=formatted_answer,
        similarity_score=similarity_score,
    )


# ---------------------------------------------------------------------------
# Callback Query Handler — Tombol Inline Keyboard
# ---------------------------------------------------------------------------

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler untuk aksi InlineKeyboard (callback_query) dari Telegram.

    Menangani tiga jenis callback data:
      - "show_faq"          → Tampilkan jawaban singkat dari koleksi FAQ WhatsApp.
      - "show_sop:<fname>"  → Ambil & tampilkan jawaban dari SOP alternatif secara instan.
      - "rec:<idx>"         → Ambil pertanyaan lanjutan, tampilkan label, proses via RAG.
    """
    query = update.callback_query
    user = query.from_user
    data = query.data or ""

    # Wajib dipanggil segera untuk menghilangkan spinner loading di tombol Telegram
    await query.answer()

    # --- Hapus tombol dari pesan asli untuk mencegah klik ganda ---
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as edit_exc:
        logger.warning(f"[Callback] Gagal menghapus reply_markup: {edit_exc}")

    # ───────────────────────────────────────────
    # 1. Callback: show_faq
    # ───────────────────────────────────────────
    if data == "show_faq":
        logger.info(f"[Callback] User {user.id} mengklik 'Show FAQ Answer'.")
        await _handle_show_faq(update, context, user)

    # ───────────────────────────────────────────
    # 2. Callback: sop:<idx> (show SOP by index)
    # ───────────────────────────────────────────
    elif data.startswith("sop:") or data.startswith("show_sop:"):
        # Support both old show_sop:<filename> and new sop:<idx> format
        if data.startswith("sop:"):
            try:
                sop_idx = int(data[len("sop:"):])
            except ValueError:
                logger.warning(f"[Callback] SOP index tidak valid: '{data}'")
                return
            stored_sops: list = context.user_data.get("other_sops", [])
            if sop_idx >= len(stored_sops):
                logger.warning(f"[Callback] SOP index {sop_idx} di luar batas (total: {len(stored_sops)}).")
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="⚠️ This document suggestion is no longer available. Please ask your question again.",
                )
                return
            filename = stored_sops[sop_idx].get("filename", "")
        else:
            # Legacy fallback: callback data langsung berisi filename
            filename = data[len("show_sop:"):]

        logger.info(f"[Callback] User {user.id} mengklik 'Explore SOP: {filename}'.")
        await _handle_show_sop(update, context, user, filename)

    # ───────────────────────────────────────────
    # 3. Callback: rec:<idx>
    # ───────────────────────────────────────────
    elif data.startswith("rec:"):
        try:
            idx = int(data[len("rec:"):])
        except ValueError:
            logger.warning(f"[Callback] Index rekomendasi tidak valid: '{data}'")
            return
        logger.info(f"[Callback] User {user.id} mengklik rekomendasi #{idx}.")
        await _handle_recommended_question(update, context, user, idx)

    else:
        logger.warning(f"[Callback] Callback data tidak dikenali: '{data}'")


async def _handle_show_faq(update, context, user):
    """Sub-handler: Ambil dan tampilkan jawaban dari koleksi FAQ."""
    last_query = context.user_data.get("last_query")

    if not last_query:
        # Fallback: ambil query terakhir dari DB
        try:
            from backend.api.database import AsyncSessionLocal
            from backend.api.models import ChatLog
            from sqlalchemy import select, desc

            async with AsyncSessionLocal() as session:
                stmt = (
                    select(ChatLog.query)
                    .where(ChatLog.user_id == str(user.id))
                    .order_by(desc(ChatLog.created_at))
                    .limit(1)
                )
                result = await session.execute(stmt)
                last_query = result.scalar_one_or_none()
        except Exception as db_exc:
            logger.error(f"[Callback-FAQ] Gagal mengambil query dari DB: {db_exc}", exc_info=True)

    if not last_query:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Sorry, I could not retrieve your previous question to generate the FAQ answer.",
        )
        return

    try:
        from backend.rag.retriever import retrieve_faq
        from backend.rag.generator import generate_faq_answer, FALLBACK_RESPONSE

        faq_docs, faq_score = await asyncio.to_thread(retrieve_faq, last_query)

        if not faq_docs:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    "ℹ️ <i>No specific FAQ entry was found for this topic. "
                    "The SOP answer above should cover everything you need!</i>"
                ),
                parse_mode=ParseMode.HTML,
            )
            return

        faq_answer, _ = await asyncio.to_thread(generate_faq_answer, last_query, faq_docs)
        formatted_faq = format_llm_output(faq_answer)

        logger.info(
            f"[Callback-FAQ] FAQ answer di-generate untuk user {user.id}. "
            f"Score: {faq_score:.4f}, Panjang: {len(faq_answer)} karakter."
        )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"📖 <b>FAQ Version:</b>\n\n{formatted_faq}",
            parse_mode=ParseMode.HTML,
        )

    except Exception as exc:
        logger.error(f"[Callback-FAQ] Error saat generate FAQ: {exc}", exc_info=True)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Sorry, a technical error occurred while fetching the FAQ answer.",
        )


async def _handle_show_sop(update, context, user, filename: str):
    """Sub-handler: Ambil dokumen SOP berdasarkan nama file dan tampilkan jawaban."""
    last_query = context.user_data.get("last_query", "")

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    try:
        from backend.rag.retriever import get_parent_document_by_filename
        from backend.rag.generator import generate_sop_answer, FALLBACK_RESPONSE

        sop_doc = await asyncio.to_thread(get_parent_document_by_filename, filename)

        if sop_doc is None:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    f"⚠️ <i>Could not load the document <b>{filename}</b>. "
                    "It may have been removed or re-indexed. "
                    "Please contact the organizing committee if this persists.</i>"
                ),
                parse_mode=ParseMode.HTML,
            )
            return

        label = filename.replace(".pdf", "").replace("_", " ")
        sop_answer, _ = await asyncio.to_thread(
            generate_sop_answer, last_query or f"What does {filename} say?", sop_doc
        )
        formatted_sop = format_llm_output(sop_answer)

        logger.info(
            f"[Callback-SOP] SOP answer dari '{filename}' di-generate untuk user {user.id}. "
            f"Panjang: {len(sop_answer)} karakter."
        )

        from telegram.error import BadRequest
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📄 <b>From: {label}</b>\n\n{formatted_sop}",
                parse_mode=ParseMode.HTML,
            )
        except BadRequest as e:
            logger.warning(f"[Callback-SOP] Gagal parse HTML ({e}), fallback ke plain text.")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📄 From: {label}\n\n{sop_answer}",
            )

    except Exception as exc:
        logger.error(f"[Callback-SOP] Error saat generate SOP '{filename}': {exc}", exc_info=True)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Sorry, a technical error occurred while loading the SOP document.",
        )


async def _handle_recommended_question(update, context, user, idx: int):
    """
    Sub-handler: Proses pertanyaan lanjutan yang dipilih user.

    Alur:
      1. Ambil teks pertanyaan dari context.user_data["rec_queries"][idx].
      2. Kirim pesan label di obrolan agar percakapan terlihat runtut.
      3. Proses pertanyaan tersebut melalui RAG workflow secara otomatis.
    """
    rec_queries: list = context.user_data.get("rec_queries", [])

    if idx >= len(rec_queries):
        logger.warning(f"[Callback-Rec] Index {idx} di luar batas (total: {len(rec_queries)}).")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ This suggested question is no longer available. Please type your question.",
        )
        return

    selected_question = rec_queries[idx]
    logger.info(f"[Callback-Rec] User {user.id} memilih pertanyaan #{idx}: '{selected_question}'")

    # Kirim label pertanyaan terpilih agar percakapan terlihat logis
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"❓ <b>Suggested Question:</b>\n<i>{selected_question}</i>",
        parse_mode=ParseMode.HTML,
    )

    # Kirim sinyal "typing..." agar user tahu bot sedang memproses
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    # Proses pertanyaan melalui RAG workflow
    try:
        from backend.api.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db_session:
            answer, score, has_both, other_sops, new_rec_qs = await run_agentic_workflow(
                query=selected_question,
                user_id=str(user.id),
                db_session=db_session,
                is_recommendation=True,
            )

        is_fallback = (answer == FALLBACK_RESPONSE)

        # Update state rekomendasi untuk kemungkinan klik tombol berikutnya
        if not is_fallback:
            context.user_data["rec_queries"] = new_rec_qs
            context.user_data["other_sops"] = other_sops
            context.user_data["last_query"] = selected_question
        else:
            context.user_data["rec_queries"] = []
            context.user_data["other_sops"] = []
            context.user_data["last_query"] = None

        formatted_answer = format_llm_output(answer)

        # Tambahkan penanda untuk SOP/FAQ lain jika ada
        extra_info_parts = []
        if not is_fallback:
            if has_both:
                extra_info_parts.append(
                    "💡 <i>A short community FAQ answer is also available for this topic.</i>"
                )
            if other_sops:
                names = ", ".join(
                    s["filename"].replace(".pdf", "").replace("_", " ")
                    for s in other_sops
                )
                extra_info_parts.append(
                    f"📑 <i>This topic also appears in: {names}.</i>"
                )
        if extra_info_parts:
            formatted_answer += "\n\n" + "\n".join(extra_info_parts)

        reply_markup = _build_inline_keyboard(
            has_both if not is_fallback else False,
            other_sops if not is_fallback else [],
            new_rec_qs if not is_fallback else []
        )

        from telegram.error import BadRequest
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=formatted_answer,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        except BadRequest as e:
            logger.warning(f"[Callback-Rec] Gagal parse HTML ({e}), fallback ke plain text.")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=answer,
                reply_markup=reply_markup,
            )

        # Log ke database
        await _log_chat_to_db(
            user_id=str(user.id),
            query=selected_question,
            answer=formatted_answer,
            similarity_score=score,
        )

    except Exception as exc:
        logger.error(
            f"[Callback-Rec] Error saat memproses pertanyaan rekomendasi: {exc}",
            exc_info=True,
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Sorry, a technical error occurred while processing this question.",
        )
