"""
bot_runner.py - Inisialisasi dan menjalankan Telegram Bot menggunakan ApplicationBuilder.

Mode saat ini: Polling (untuk development lokal).
Mode Webhook akan diaktifkan di Fase 4 saat deploy ke VPS.

Cara menjalankan bot langsung:
  python backend/bot/bot_runner.py
"""
import logging
import os

from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from backend.bot.handlers import handle_message, help_command, start_command, reset_command

# Muat .env di awal — override=True WAJIB agar perubahan .env selalu
# menimpa env var yang mungkin sudah ada di shell/sistem dari sesi sebelumnya.
load_dotenv(override=True)

logger = logging.getLogger(__name__)


def create_application() -> Application:
    """
    Membuat dan mengkonfigurasi instance Telegram Application.

    Membaca TELEGRAM_BOT_TOKEN dari environment variable.
    Raise ValueError jika token tidak ditemukan agar gagal cepat (fail-fast).
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN tidak ditemukan di environment variables! "
            "Pastikan file .env sudah dikonfigurasi dengan benar."
        )

    # Membangun application menggunakan ApplicationBuilder (python-telegram-bot v21+)
    application = Application.builder().token(token).build()

    # Registrasi command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", reset_command))

    # Registrasi message handler (semua teks yang bukan command)
    # Filter: hanya pesan teks biasa, abaikan command (/start, /help, dll.)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("✅ Telegram Application berhasil dikonfigurasi dengan semua handler.")
    return application


def run_polling() -> None:
    """
    Menjalankan bot dalam mode polling (untuk development lokal).

    Catatan penting (python-telegram-bot v21+):
      Application.run_polling() sudah mengelola event loop-nya sendiri secara
      internal. Fungsi ini TIDAK boleh bersifat async / dibungkus asyncio.run(),
      karena akan menyebabkan konflik "This event loop is already running".
      Panggil langsung sebagai fungsi sinkron biasa.

    Bot akan terus aktif dan menunggu pesan masuk sampai dihentikan (Ctrl+C).
    """
    application = create_application()
    logger.info("🤖 Bot ICICoS 2026 berjalan dalam mode POLLING. Tekan Ctrl+C untuk berhenti.")
    application.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    # Entry point untuk menjalankan bot secara standalone dari terminal:
    #   cd backend && python -m bot.bot_runner
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    run_polling()
