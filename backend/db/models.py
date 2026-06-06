"""
models.py - Definisi model ORM SQLAlchemy untuk PostgreSQL.
Tabel: ChatLog - menyimpan riwayat percakapan user dengan bot.
"""
import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ChatLog(Base):
    """
    Tabel untuk menyimpan setiap interaksi user dengan bot.
    Berguna untuk monitoring, debugging, dan analisis kualitas jawaban.
    """
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    query = Column(Text, nullable=False)                    # Pertanyaan user
    response = Column(Text, nullable=False)                 # Jawaban bot
    similarity_score = Column(Float, nullable=True)         # Skor retrieval tertinggi
    is_fallback = Column(Integer, default=0)                # 1 jika menggunakan fallback
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def __repr__(self) -> str:
        return f"<ChatLog(id={self.id}, user={self.telegram_user_id}, query='{self.query[:30]}...')>"
