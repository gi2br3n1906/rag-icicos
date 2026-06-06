"""
config.py - Manajemen konfigurasi database untuk Admin API.

Membaca DATABASE_URL dari environment variable / file .env di root project.
Menggunakan pydantic-settings agar type-safe dan gagal cepat jika variabel wajib
tidak ditemukan saat startup.
"""
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Cari file .env di root project (dua level di atas backend/api/)
_ROOT_DIR = Path(__file__).resolve().parents[2]
_ENV_FILE = _ROOT_DIR / ".env"


class APISettings(BaseSettings):
    """
    Konfigurasi untuk Admin Dashboard API.
    Semua nilai dibaca dari environment variable atau file .env root project.
    """
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",         # Abaikan variabel lain di .env yang tidak relevan
    )

    # Koneksi database — wajib menggunakan skema asyncpg
    database_url: str = (
        "postgresql+asyncpg://icicos_admin:icicos_password_local@localhost:5432/icicos_db"
    )

    # Mode aplikasi — menentukan apakah SQL echo diaktifkan
    app_env: str = "development"

    @property
    def sql_echo(self) -> bool:
        """Aktifkan logging query SQL hanya saat mode development."""
        return self.app_env.lower() == "development"


# Singleton — impor dari sini di seluruh modul api/
settings = APISettings()
