# Master Architecture: ICICoS 2026 RAG Telegram Bot

## 1. System Overview
Layanan Telegram Bot berbasis Retrieval-Augmented Generation (RAG) untuk The 9th International Conference on Informatics and Computational Sciences (ICICoS 2026) oleh Departemen Informatika, Universitas Diponegoro[cite: 1]. Sistem menjawab pertanyaan author otomatis dan akurat berdasarkan SOP resmi untuk menghindari halusinasi[cite: 1].

## 2. Core Components
1. **Telegram Bot Interface:** Antarmuka percakapan menggunakan Telegram Bot API[cite: 1].
2. **Query Processing Module:** Normalisasi teks, deteksi bahasa (Indonesia/Inggris), dan routing query[cite: 1].
3. **RAG Engine:** 
   - Retriever: ChromaDB + Multilingual Embedding[cite: 1].
   - Generator: LLM via OpenRouter/Gemini[cite: 1].
4. **Knowledge Base (SOP):** File PDF/DOCX yang di-chunk dan di-index[cite: 1].
5. **Admin Dashboard:** Web antarmuka (Vue.js + Tailwind) untuk manajemen SOP dan monitoring log[cite: 1].

## 3. Directory Structure Target
```text
icicos-bot-system/
├── backend/
│   ├── main.py               # FastAPI entry point & Bot initiator
│   ├── bot/                  # Telegram handlers
│   ├── rag/                  # PDF Ingestion, Retrieval, LLM Chain
│   ├── api/                  # REST API untuk Admin Dashboard
│   ├── data/                 # ChromaDB storage & Raw PDFs
│   └── requirements.txt
├── frontend/                 # Vue 3 + Tailwind Admin Panel
├── infrastructure/           # Nginx configs, init scripts
├── docker-compose.yml
└── .env