"""
handlers.py - Kumpulan handler utama untuk Telegram Bot ICICoS 2026.
Setiap fungsi di sini di-register ke Application di bot_runner.py.

Alur handle_message:
  Pesan masuk
    → kirim "typing..."
    → RAG chain (retrieve + generate) → Tuple[answer, score]
    → format HTML (bold/italic)
    → kirim jawaban ke user
    → logging ke PostgreSQL (fire-and-forget, tidak crash bot jika gagal)
"""
import logging
import re

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from backend.rag.workflow import run_agentic_workflow

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

    Latar belakang: LLM (Gemini, OpenRouter, Ollama) mengembalikan teks
    dengan penanda Markdown standar. Telegram tidak merender Markdown
    secara otomatis — simbol muncul mentah di chat. Solusi: gunakan
    parse_mode=ParseMode.HTML dan konversi via regex sebelum dikirim.

    Args:
        text: String output mentah dari LLM.

    Returns:
        String dengan tag HTML siap dikirim ke Telegram.
    """
    # Langkah 1: Konversi **bold** → <b>bold</b>
    # (harus lebih dulu agar ** tidak dikira dua * italic)
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)

    # Langkah 2: Konversi *italic* → <i>italic</i>
    # Setelah bold selesai, semua * yang tersisa adalah penanda italic tunggal
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

    Lazy import digunakan agar modul database tidak di-load saat bot
    pertama kali startup (menjaga waktu inisialisasi tetap cepat).

    Args:
        user_id         : Telegram user ID sebagai string.
        query           : Pertanyaan asli dari user.
        answer          : Jawaban teks final (sudah di-format HTML).
        similarity_score: Skor retrieval tertinggi (0.0 jika fallback).
    """
    try:
        # Lazy import — modul database hanya diload saat fungsi ini pertama dipanggil
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
        # Log error tapi JANGAN re-raise — bot harus tetap berjalan
        logger.error(
            f"[DB Log] ❌ Gagal menyimpan chat log untuk user {user_id}: {db_exc}",
            exc_info=True,
        )


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
        "• Conference Schedule &amp; Timeline\n"
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
      2. Kirim sinyal ChatAction.TYPING agar muncul "sedang mengetik..."
         di sisi Telegram user selama proses RAG berlangsung.
      3. Jalankan RAG chain → mendapatkan Tuple[jawaban, similarity_score].
      4. Format jawaban dari Markdown LLM ke HTML Telegram.
      5. Kirim jawaban ke user.
      6. Simpan log percakapan ke PostgreSQL (fire-and-forget).
         Kegagalan logging tidak mengganggu pengiriman jawaban.
    """
    user = update.effective_user
    user_query = update.message.text

    logger.info(
        f"[Bot] Pesan masuk dari user {user.id} (@{user.username}): '{user_query}'"
    )

    # Kirim sinyal "typing..." ke Telegram — muncul selama RAG engine bekerja
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    # Nilai default jika RAG gagal total
    answer: str = ""
    similarity_score: float = 0.0

    try:
        # Import db session factory untuk diinjeksikan ke workflow
        from backend.api.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db_session:
            # Jalankan Agentic Workflow dengan memory dari PostgreSQL
            answer, similarity_score = await run_agentic_workflow(
                query=user_query,
                user_id=str(user.id),
                db_session=db_session,
            )

        logger.info(
            f"[Bot] Jawaban di-generate untuk user {user.id}. "
            f"Score: {similarity_score:.4f}, Panjang: {len(answer)} karakter."
        )

    except Exception as exc:
        # Log error secara lengkap untuk debugging, kirim pesan ramah ke user
        logger.error(
            f"[Bot] Error saat memproses query dari user {user.id}: {exc}",
            exc_info=True,
        )
        answer = (
            "⚠️ Sorry, a technical error occurred while processing your question. "
            "Please try again in a moment, or contact the ICICoS 2026 organizing committee "
            "directly if the problem persists."
        )

    # Format jawaban (bold/italic LLM → HTML Telegram)
    formatted_answer = format_llm_output(answer)

    from telegram.error import BadRequest

    # Kirim jawaban ke user dengan penanganan error tag HTML
    try:
        await update.message.reply_text(
            formatted_answer,
            parse_mode=ParseMode.HTML,
        )
    except BadRequest as e:
        logger.warning(f"[Bot] Gagal parse HTML ({e}), fallback ke plain text.")
        # Jika tag HTML rusak (contoh: <b><i>...</b>), fallback kirim text mentah tanpa parse_mode
        await update.message.reply_text(answer)

    # Simpan log ke database (fire-and-forget — tidak crash bot jika gagal)
    # Gunakan teks yang sudah terformat sebagai kolom 'answer' di DB
    await _log_chat_to_db(
        user_id=str(user.id),
        query=user_query,
        answer=formatted_answer,
        similarity_score=similarity_score,
    )
