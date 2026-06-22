"""
memory.py - Session Memory Manager untuk Agentic RAG Workflow.

Fungsi utama:
  get_recent_history() → Mengambil N pesan terakhir dari tabel chat_logs
                         berdasarkan user_id, diurutkan dari yang terlama ke terbaru.

Pemanfaatan:
  Memory ini digunakan oleh Query Rewriter untuk memahami konteks percakapan
  sebelum melakukan reformulasi pertanyaan yang ambigu (misal: "yang tadi itu
  gimana?") menjadi pertanyaan mandiri yang utuh.

Database: PostgreSQL via SQLAlchemy Async (memanfaatkan ChatLog model yang sudah ada).
"""
import logging
from typing import List

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Jumlah pesan terakhir yang diambil sebagai konteks memori
SESSION_MEMORY_WINDOW = 6  # 3 giliran percakapan (user + bot = 2 msg per giliran)


async def get_recent_history(user_id: str, db: AsyncSession) -> List[dict]:
    """
    Mengambil N pesan terakhir dari percakapan user dengan bot.

    Memanfaatkan tabel chat_logs yang sudah ada. Setiap row mengandung
    pasangan query (dari user) + answer (dari bot) dalam satu record,
    sehingga kita membongkarnya menjadi daftar pesan bergantian.

    Args:
        user_id: Telegram user ID sebagai string (primary key pencarian).
        db     : AsyncSession dari PostgreSQL (disuntikkan dari LangGraph node).

    Returns:
        List of dicts dengan format:
        [
          {"role": "user", "content": "...pertanyaan user..."},
          {"role": "assistant", "content": "...jawaban bot..."},
          ...
        ]
        Diurutkan dari pesan TERLAMA ke TERBARU (kronologis) agar mudah
        dimasukkan ke dalam prompt LLM.
    """
    from backend.api.models import ChatLog

    try:
        # Ambil N/2 record terakhir (karena 1 record = 1 giliran user+bot)
        n_records = SESSION_MEMORY_WINDOW // 2
        stmt = (
            select(ChatLog)
            .where(ChatLog.user_id == user_id)
            .order_by(desc(ChatLog.created_at))
            .limit(n_records)
        )
        result = await db.execute(stmt)
        logs = result.scalars().all()

        if not logs:
            logger.info(f"[Memory] Tidak ada histori chat ditemukan untuk user {user_id}.")
            return []

        # Balik urutan agar kronologis (terlama dulu)
        logs = list(reversed(logs))

        # Susun sebagai daftar pesan bergantian user/assistant
        messages = []
        for log in logs:
            messages.append({"role": "user", "content": log.query})
            messages.append({"role": "assistant", "content": log.answer})

        logger.info(
            f"[Memory] ✅ Ditemukan {len(logs)} record histori untuk user {user_id}. "
            f"Total {len(messages)} pesan sebagai konteks memori."
        )
        return messages

    except Exception as e:
        logger.error(f"[Memory] Gagal mengambil histori chat: {e}", exc_info=True)
        return []


def format_history_for_prompt(history: List[dict]) -> str:
    """
    Mengubah list pesan histori menjadi string yang bisa dimasukkan ke prompt LLM.

    Format output:
      User: <pesan user>
      Assistant: <jawaban bot>
      User: <pesan user berikutnya>
      ...

    Args:
        history: List dict dari get_recent_history().

    Returns:
        String teks percakapan yang sudah diformat.
    """
    if not history:
        return ""

    lines = []
    for msg in history:
        role = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{role}: {msg['content']}")

    return "\n".join(lines)
