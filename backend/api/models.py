"""
models.py - Definisi tabel database menggunakan SQLAlchemy 2.0.

Format modern: Mapped[] + mapped_column() untuk type-safety penuh.

Tabel:
  - documents  : Riwayat file SOP yang di-ingest via dashboard admin.
  - chat_logs  : Riwayat percakapan author dengan Telegram Bot.
"""
import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.database import Base


class Document(Base):
    """
    Tabel: documents
    Mencatat setiap file SOP yang berhasil di-ingest ke dalam ChromaDB.
    Data ini digunakan oleh Admin Dashboard untuk menampilkan daftar
    dokumen aktif dan memungkinkan penghapusan atau re-ingesti.
    """
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    filename: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Nama file PDF/DOCX asli yang di-upload"
    )
    total_chunks: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Jumlah chunk yang berhasil disimpan ke ChromaDB"
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="success",
        comment="Status ingesti: 'success' atau 'failed'"
    )
    ingested_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        # server_default menggunakan fungsi SQL NOW() → konsisten di semua timezone
        server_default=func.now(),
        comment="Waktu ingesti dalam UTC"
    )

    def __repr__(self) -> str:
        return (
            f"<Document(id={self.id}, filename='{self.filename}', "
            f"chunks={self.total_chunks}, status='{self.status}')>"
        )


class ChatLog(Base):
    """
    Tabel: chat_logs
    Mencatat setiap interaksi author dengan Telegram Bot untuk keperluan
    monitoring kualitas jawaban RAG, debugging, dan analisis.
    """
    __tablename__ = "chat_logs"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    user_id: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="Telegram user ID pengirim pesan (sebagai string untuk fleksibilitas)"
    )
    query: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Pertanyaan asli dari user"
    )
    answer: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Jawaban yang dikirimkan bot ke user"
    )
    similarity_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="Skor similarity tertinggi dari retrieval (None jika fallback)"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Waktu percakapan dalam UTC"
    )

    def __repr__(self) -> str:
        return (
            f"<ChatLog(id={self.id}, user_id='{self.user_id}', "
            f"score={self.similarity_score}, created_at={self.created_at})>"
        )


class WhatsAppFAQ(Base):
    """
    Tabel: whatsapp_faqs
    Menyimpan pasangan tanya-jawab hasil ekstraksi chat WhatsApp
    sebelum disetujui (staging) dan setelah disetujui (ingested).
    """
    __tablename__ = "whatsapp_faqs"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    question: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Pertanyaan hasil ekstraksi/formulasi LLM"
    )
    answer: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Jawaban hasil ekstraksi/formulasi LLM"
    )
    category: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="Kategori FAQ (e.g. registrasi, pembayaran)"
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending",
        comment="Status review: 'pending', 'approved', 'rejected'"
    )
    source_file: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Nama file txt ekspor WA asal"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Waktu ekstraksi dalam UTC"
    )
    approved_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Waktu persetujuan/ingesti ke ChromaDB"
    )

    def __repr__(self) -> str:
        return (
            f"<WhatsAppFAQ(id={self.id}, status='{self.status}', "
            f"category='{self.category}', source='{self.source_file}')>"
        )

