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

from backend.rag.chain import run_rag_chain

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
    """Handler untuk command /start. Menampilkan pesan selamat datang."""
    user = update.effective_user
    welcome_message = (
        f"Halo, {user.first_name}! 👋\n\n"
        "Saya adalah *Asisten Resmi ICICoS 2026* 🎓\n\n"
        "Saya siap membantu menjawab pertanyaan Anda seputar:\n"
        "• Panduan Submission Paper (Under Development)\n"
        "• Prosedur Pembayaran Registrasi (Under Development)\n"
        "• Jadwal & Timeline Konferensi (Under Development)\n"
        "• Dan informasi resmi lainnya (Under Development)\n\n"
        "Silakan ketik pertanyaan Anda langsung di sini!"
    )
    await update.message.reply_text(welcome_message, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk command /help."""
    help_text = (
        "📚 *Cara Menggunakan Bot ICICoS 2026:*\n\n"
        "Cukup ketik pertanyaan Anda dalam Bahasa Indonesia atau Inggris.\n\n"
        "*Contoh pertanyaan:*\n"
        "• _Bagaimana cara melakukan pembayaran registrasi?_\n"
        "• _Apa format paper yang diterima?_\n"
        "• _Kapan batas waktu submission?_\n\n"
        "Jika bot tidak dapat menjawab, silakan hubungi panitia langsung."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


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
        # Jalankan pipeline RAG: retrieve dari ChromaDB → generate via LLM
        # run_rag_chain kini mengembalikan Tuple[str, float]
        answer, similarity_score = await run_rag_chain(user_query)

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
            "⚠️ Maaf, terjadi kesalahan teknis saat memproses pertanyaan Anda. "
            "Silakan coba lagi dalam beberapa saat, atau hubungi panitia ICICoS 2026 "
            "secara langsung jika masalah berlanjut."
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
