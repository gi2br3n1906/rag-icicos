"""
config.py - Manajemen konfigurasi terpusat menggunakan pydantic-settings.
Semua environment variables dibaca dari sini. JANGAN hardcode nilai apapun.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Konfigurasi aplikasi. Nilai dibaca otomatis dari file .env
    atau environment variables sistem.
    """
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- Telegram ---
    telegram_bot_token: str = ""

    # --- LLM Provider ---
    llm_provider: str = "gemini"              # "openrouter" | "gemini" | "ollama"
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.1-8b-instruct:free"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "granite4.1:3b"

    # --- Database ---
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/icicos_db"

    # --- RAG / ChromaDB ---
    chroma_persist_dir: str = "./data/chroma_db"
    retriever_top_k: int = 4
    similarity_threshold: float = 0.4

    # --- Application ---
    app_env: str = "development"              # "development" atau "production"
    log_level: str = "INFO"


# Singleton instance - impor dari sini di seluruh aplikasi
settings = Settings()
