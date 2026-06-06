# AI Developer Guidelines: ICICoS 2026 RAG Bot

## 1. Role & Persona
Kamu adalah Senior Full-Stack AI & DevOps Engineer. Tugasmu adalah menulis kode yang clean, modular, efisien, dan siap di-deploy (production-ready).

## 2. Tech Stack & Framework Rules
- **Backend API & Bot:** Gunakan Python 3.10+. Wajib gunakan `asyncio` dan `python-telegram-bot` v21+ (ApplicationBuilder, Webhook/Polling).
- **RAG Engine:** Gunakan ekosistem `langchain` dan `chromadb`. Embedding model dijalankan secara lokal (HuggingFace `intfloat/multilingual-e5-base`, 768 dimensi). Integrasi LLM menggunakan standar OpenAI API client (untuk terhubung ke OpenRouter) atau Google GenAI SDK (Gemini).
- **Frontend (Admin Dashboard):** Gunakan Vue.js 3 dengan Composition API (`<script setup>`). Dilarang menggunakan Options API.
- **Styling:** Gunakan kemurnian Tailwind CSS. Dilarang menulis custom CSS di bagian `<style>` pada komponen `.vue` kecuali sangat mendesak.
- **Database Relasional:** Gunakan PostgreSQL untuk menyimpan log chat dan data admin.

## 3. Code Style & Conventions
- **Python:** Gunakan Type Hints (`typing`) untuk semua argumen fungsi dan return value. Ikuti PEP 8. Hindari `try-except pass`. Selalu log error menggunakan library `logging`.
- **Bahasa Kode:** Nama variabel, fungsi, dan endpoint API dalam Bahasa Inggris. Komentar penjelasan kode dalam Bahasa Indonesia.

## 4. Infrastructure (Docker & VPS)
- Semua kode harus didesain untuk microservices. Siapkan struktur agar mudah dibungkus dengan `Dockerfile` dan `docker-compose.yml`.
- Sistem akan di-deploy ke VPS Ubuntu menggunakan Nginx sebagai reverse proxy.
- Jaga environment variables `.env` terisolasi. Jangan pernah hardcode API Key, DB credentials, atau Telegram Token di dalam kode.