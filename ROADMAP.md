# Project Roadmap & Milestones

Sistem ini memiliki tenggat waktu rilis yang ketat untuk mendukung batch submisi 3 dan hari pelaksanaan konferensi (12 Agustus 2026)[cite: 1]. Saat ini kita berada di awal Juni 2026. Prioritaskan tugas sesuai fase berikut:

## Fase 1: Eksperimen Awal (15-21 Juni 2026)[cite: 1]
- [ ] Setup virtual environment dan repository.
- [ ] Proof-of-Concept (PoC) RAG sederhana (script Python membaca 1 file PDF SOP Pembayaran, chunking, dan query ke LLM).
- [ ] Testing respon dasar Telegram Bot API.

## Fase 2: Pengembangan Core (22 Juni - 5 Juli 2026)[cite: 1]
- [ ] Implementasi pipeline RAG penuh (ChromaDB terintegrasi).
- [ ] Implementasi Bot Handler lengkap (multi-turn conversation manager).
- [ ] Pembuatan API Backend (FastAPI/Express) untuk dashboard.
- [ ] Pembuatan Frontend Dashboard (Vue.js) untuk upload SOP.

## Fase 3: Integrasi SOP & Edge Case (6-10 Juli 2026)[cite: 1]
- [ ] Ingesti seluruh dokumen SOP resmi ICICoS.
- [ ] Penyesuaian Prompt Engineering (System Prompt) agar strict tidak halusinasi.
- [ ] Handling pertanyaan out-of-scope (Fallback mechanism).

## Fase 4 & 5: Deployment & Release (11-18 Juli 2026)[cite: 1]
- [ ] Containerization menggunakan Docker.
- [ ] Setup Nginx, Cloudflare Tunnels (jika perlu), dan SSL di VPS Ubuntu.
- [ ] **18 Juli 2026: DEADLINE RILIS VERSI 1.0 (Live untuk Author Batch 3)[cite: 1].**