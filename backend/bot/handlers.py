"""
handlers.py - Kumpulan handler utama untuk Telegram Bot ICICoS 2026.
Setiap fungsi di sini di-register ke Application di bot_runner.py.

Alur handle_message:
  Pesan masuk
    → Cek apakah pesan adalah tap dari ReplyKeyboard (FAQ / Explore SOP prefix)
    → Jika ya, arahkan ke sub-handler yang sesuai
    → Jika tidak, proses via RAG chain
    → Kirim 1 pesan jawaban + ReplyKeyboard terpadu (FAQ + SOP + follow-up)
    → Log ke PostgreSQL
"""
import asyncio
import logging
import re

from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
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
# Magic prefixes untuk tombol ReplyKeyboard bukan-pertanyaan
# ---------------------------------------------------------------------------
# Teks tombol ini di-detect di awal handle_message untuk routing ke sub-handler.
_FAQ_BTN_PREFIX = "📖 Show FAQ Answer"
_SOP_BTN_PREFIX = "🔍 Explore: "


def _build_reply_keyboard(
    has_both: bool,
    other_sops: list,
    recommended_questions: list,
    clarification_options: list | None = None,
) -> ReplyKeyboardMarkup | None:
    """
    Membangun SATU ReplyKeyboardMarkup terpadu berisi:
      - [Prioritas] Tombol pilihan cabang SOP jika ada klarifikasi yang dibutuhkan
      - [Opsional] Tombol FAQ (jika has_both=True)
      - [Opsional] Tombol Explore SOP lain yang SUDAH DIVALIDASI (satu per SOP)
      - Tombol pertanyaan lanjutan (max 3)

    Jika clarification_options ada, tampilkan tombol pilihan cabang sebagai baris pertama
    (prioritas tertinggi) agar user langsung bisa memilih tanpa mengetik.
    """
    buttons = []

    # [Prioritas] Tombol pilihan cabang SOP (jika ada klarifikasi)
    if clarification_options:
        for option in clarification_options:
            buttons.append([KeyboardButton(option)])

    # Tombol FAQ (jika ada jawaban dari koleksi WhatsApp FAQ)
    if has_both:
        buttons.append([KeyboardButton(_FAQ_BTN_PREFIX)])

    # Tombol Explore SOP lain — sudah dijamin relevan oleh workflow validator
    for sop in other_sops:
        filename = sop.get("filename", "")
        label = filename.replace(".pdf", "").replace("_", " ")
        buttons.append([KeyboardButton(f"{_SOP_BTN_PREFIX}{label}")])

    # Tombol pertanyaan lanjutan (hanya jika tidak ada clarification, agar tidak membingungkan)
    if not clarification_options:
        for q in recommended_questions[:3]:
            buttons.append([KeyboardButton(q)])

    if not buttons:
        return None

    placeholder = (
        "Choose an option above or type your answer..."
        if clarification_options
        else "Tap a suggestion or type your question..."
    )
    return ReplyKeyboardMarkup(
        buttons,
        one_time_keyboard=True,
        resize_keyboard=True,
        input_field_placeholder=placeholder,
    )


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /start command. Displays a welcome message."""
    user = update.effective_user
    welcome_message = (
        f"Hello, {user.first_name}! 👋\n"
        "I am the <b>Official Assistant of ICICoS 2026</b> 🎓\n\n"
        "Here is my role as your guide through the ICICoS 2026 submission and presentation procedures (SOP):\n\n"
        "1. <b>Official Assistant</b>: Supporting the 9th ICICoS 2026, organized by the Department of Informatics, Universitas Diponegoro.\n"
        "2. <b>Author Perspective</b>: Guiding you through all the procedural steps from paper submission up to the final presentation.\n"
        "3. <b>Step-by-Step Assistance</b>: Helping you navigate:\n"
        "   • <b>Peer Review Phase</b>\n"
        "   • <b>Pre-Conference Fulfillment</b> (IEEE PDF eXpress, Electronic Copyright Form, and registration payment)\n"
        "   • <b>Final Presentation Phase</b>\n\n"
        "Feel free to type your question directly — in English or Bahasa Indonesia! 😊"
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
      1. Cek processing lock — tolak jika query sebelumnya belum selesai.
      2. Cek apakah pesan adalah tap tombol ReplyKeyboard khusus (FAQ / Explore SOP).
      3. Jika bukan tombol khusus, jalankan RAG chain.
      4. Kirim 1 pesan jawaban + ReplyKeyboard terpadu (tanpa bubble tambahan).
      5. Simpan log ke PostgreSQL.
    """
    user = update.effective_user
    user_query = update.message.text or ""

    # --- Processing lock: cegah double-tap kirim dua jawaban ---
    if context.user_data.get("is_processing"):
        await update.message.reply_text(
            "⏳ <i>Please wait, I'm still processing your previous message...</i>",
            parse_mode=ParseMode.HTML,
        )
        return
    context.user_data["is_processing"] = True

    try:
        # --- Routing: tombol FAQ atau Explore SOP ---
        if user_query == _FAQ_BTN_PREFIX:
            await _handle_show_faq(update, context, user)
            return

        if user_query.startswith(_SOP_BTN_PREFIX):
            # Cari filename dari user_data berdasarkan label tombol
            label_clicked = user_query[len(_SOP_BTN_PREFIX):]
            stored_sops: list = context.user_data.get("other_sops", [])
            filename = next(
                (s["filename"] for s in stored_sops
                 if s["filename"].replace(".pdf", "").replace("_", " ") == label_clicked),
                None,
            )
            if filename:
                await _handle_show_sop(update, context, user, filename)
            else:
                await update.message.reply_text(
                    "⚠️ This document is no longer available in the current session. "
                    "Please ask your question again."
                )
            return

        # --- Normal RAG flow ---
        logger.info(f"[Bot] Pesan masuk dari user {user.id} (@{user.username}): '{user_query}'")

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )

        answer: str = ""
        similarity_score: float = 0.0
        has_both: bool = False
        other_sops: list = []
        recommended_questions: list = []
        clarification_question: str | None = None
        clarification_options: list = []

        try:
            from backend.api.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db_session:
                (
                    answer,
                    similarity_score,
                    has_both,
                    other_sops,
                    recommended_questions,
                    clarification_question,
                    clarification_options,
                ) = await run_agentic_workflow(
                    query=user_query,
                    user_id=str(user.id),
                    db_session=db_session,
                )

            logger.info(
                f"[Bot] Jawaban di-generate untuk user {user.id}. "
                f"Score: {similarity_score:.4f}, has_both={has_both}, "
                f"other_sops={len(other_sops)}, rec_qs={len(recommended_questions)}, "
                f"clarification={'YES' if clarification_question else 'NO'}, "
                f"Panjang: {len(answer)} karakter."
            )

        except Exception as exc:
            logger.error(f"[Bot] Error saat memproses query dari user {user.id}: {exc}", exc_info=True)
            answer = (
                "⚠️ Sorry, a technical error occurred while processing your question. "
                "Please try again in a moment, or contact the ICICoS 2026 organizing committee."
            )

        is_fallback = (answer == FALLBACK_RESPONSE)

        # Simpan konteks sesi untuk routing tombol berikutnya
        if not is_fallback:
            context.user_data["other_sops"] = other_sops
            context.user_data["last_query"] = user_query
        else:
            context.user_data["other_sops"] = []
            context.user_data["last_query"] = None

        # Format jawaban: Markdown LLM → HTML Telegram (tanpa teks noise tambahan)
        formatted_answer = format_llm_output(answer)

        # Satu ReplyKeyboard terpadu (Clarification Buttons / FAQ / Explore / Follow-up)
        reply_kb = _build_reply_keyboard(
            has_both=has_both if not is_fallback else False,
            other_sops=other_sops if not is_fallback else [],
            recommended_questions=recommended_questions if not is_fallback else [],
            clarification_options=clarification_options if not is_fallback else [],
        )

        from telegram.error import BadRequest
        try:
            await update.message.reply_text(
                formatted_answer,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_kb if reply_kb else ReplyKeyboardRemove(),
            )
        except BadRequest as e:
            logger.warning(f"[Bot] Gagal parse HTML ({e}), fallback ke plain text.")
            await update.message.reply_text(
                answer,
                reply_markup=reply_kb if reply_kb else ReplyKeyboardRemove(),
            )

        # Kirim bubble klarifikasi jika SOP bercabang
        if clarification_question and not is_fallback:
            logger.info(f"[Bot] Mengirim pertanyaan klarifikasi ke user {user.id}: '{clarification_question}'")
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, action=ChatAction.TYPING
            )
            await asyncio.sleep(0.5)  # Jeda singkat agar pesan pertama muncul dulu
            await update.message.reply_text(
                f"🤔 {clarification_question}",
                parse_mode=ParseMode.HTML,
            )

        # Log ke database (fire-and-forget)
        await _log_chat_to_db(
            user_id=str(user.id),
            query=user_query,
            answer=formatted_answer,
            similarity_score=similarity_score,
        )

    finally:
        context.user_data["is_processing"] = False



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
    """Sub-handler: Ambil dokumen SOP berdasarkan nama file dan tampilkan ringkasan."""
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
                    f"⚠️ <i>Could not load document <b>{filename}</b>. "
                    "Please contact the organizing committee if this persists.</i>"
                ),
                parse_mode=ParseMode.HTML,
            )
            return

        label = filename.replace(".pdf", "").replace("_", " ")
        sop_answer, _ = await asyncio.to_thread(
            generate_sop_answer, last_query or f"What does {filename} cover?", sop_doc
        )
        formatted_sop = format_llm_output(sop_answer)

        logger.info(
            f"[SOP-Explore] SOP answer dari '{filename}' untuk user {user.id}. "
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
            logger.warning(f"[SOP-Explore] Gagal parse HTML ({e}), fallback ke plain text.")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📄 From: {label}\n\n{sop_answer}",
            )

    except Exception as exc:
        logger.error(f"[SOP-Explore] Error saat generate SOP '{filename}': {exc}", exc_info=True)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Sorry, a technical error occurred while loading this document.",
        )
    finally:
        context.user_data["is_processing"] = False


async def _handle_recommended_question(update, context, user, idx: int):
    """Legacy stub — rec: buttons no longer generated. Kept for safety if old messages still exist."""
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⚠️ This suggestion is from an older session. Please type your question directly.",
    )
