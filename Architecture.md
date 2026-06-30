# Master Architecture: ICICoS 2026 RAG Telegram Bot

## 1. System Overview
Layanan Telegram Bot berbasis Retrieval-Augmented Generation (RAG) untuk The 9th International Conference on Informatics and Computational Sciences (ICICoS 2026) oleh Departemen Informatika, Universitas Diponegoro. Sistem menjawab pertanyaan author otomatis dan akurat berdasarkan SOP resmi dan FAQ komunitas untuk menghindari halusinasi.

## 2. Core Components
1. **Telegram Bot Interface:** Antarmuka percakapan menggunakan Telegram Bot API, mendukung pesan teks biasa dan InlineKeyboard interaktif.
2. **Query Processing Module:** Normalisasi teks, penghilangan konteks ambigu dari histori chat, dan *Late Routing* berbasis similarity score.
3. **RAG Engine (Parallel Dual Retrieval):**
   - **Parallel Retriever:** Mencari di ChromaDB SOP dan FAQ secara bersamaan menggunakan `asyncio.gather`.
   - **Late Router:** Menentukan intent berdasarkan similarity score hasil retrieval (Threshold 0.4). Tidak menggunakan LLM untuk klasifikasi intent.
   - **Generator:** Menggunakan LLM (Gemini) untuk menghasilkan jawaban dari konteks yang ditemukan.
   - **Verifier:** CRAG Verifier memvalidasi jawaban sebelum dikirim ke user.
4. **Knowledge Base (SOP & FAQ):**
   - File PDF SOP yang di-chunk dan di-index ke ChromaDB (`icicos_sop` collection) menggunakan ParentDocumentRetriever.
   - FAQ komunitas dari WhatsApp chat log yang diproses LLM dan di-index ke ChromaDB (`icicos_faq` collection).
5. **Admin Dashboard:** Web antarmuka (Vue.js + Tailwind) untuk manajemen SOP, monitoring log, review FAQ, dan reset knowledge base.

## 3. Agentic Workflow (Late Routing)
```
START
  └─► [rewrite_query]   : Reformulasi query + terjemahan ke Inggris
        └─► [route]     : Parallel Retrieval (SOP + FAQ via asyncio.gather)
              │           Routing deterministik berdasarkan similarity score:
              ├─► [generate_sop] → [verify] → END  (SOP ≥ 0.4, or BOTH ≥ 0.4)
              │     * Jika has_both=True: lampirkan tombol "Show FAQ Answer"
              ├─► [generate_faq] → [verify] → END  (hanya FAQ ≥ 0.4)
              └─► [fallback]              → END  (tidak ada yang memenuhi threshold)
```

## 4. Interaksi Tombol FAQ (Callback Query)
Jika query ditemukan di **kedua** database (SOP & FAQ):
1. Bot mengirim jawaban SOP + tombol InlineKeyboard `[Show FAQ Answer]`.
2. Ketika tombol diklik, `CallbackQueryHandler` terpicu.
3. Bot mengambil query terakhir user dari PostgreSQL `chat_logs`.
4. Bot menjalankan FAQ retrieval + generation dan mengirim jawaban singkat FAQ.
5. Tombol dihapus dari pesan asli untuk mencegah klik ganda.

## 5. Directory Structure
```text
icicos-bot-system/
├── backend/
│   ├── main.py               # FastAPI entry point & Bot initiator
│   ├── bot/
│   │   ├── bot_runner.py     # Application + handler registration
│   │   └── handlers.py       # handle_message, handle_callback_query, commands
│   ├── rag/
│   │   ├── workflow.py       # LangGraph StateGraph (Late Routing + Parallel Retrieval)
│   │   ├── retriever.py      # retrieve_sop(), retrieve_faq()
│   │   ├── generator.py      # generate_sop_answer(), generate_faq_answer()
│   │   ├── verifier.py       # verify_answer() - CRAG Verifier
│   │   ├── query_rewriter.py # rewrite_query() - query normalization
│   │   ├── ingestion.py      # ingest_document() - PDF → ChromaDB pipeline
│   │   └── memory.py         # get_recent_history() - PostgreSQL chat history
│   ├── api/                  # REST API untuk Admin Dashboard
│   ├── data/                 # ChromaDB storage & Raw PDFs
│   └── requirements.txt
├── frontend/                 # Vue 3 + Tailwind Admin Panel
├── infrastructure/           # Nginx configs, init scripts
├── docker-compose.yml
└── .env
```