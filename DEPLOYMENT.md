# Deployment & Infrastructure Guide

Proyek ini dirancang untuk berjalan di atas VPS Linux (Ubuntu) dengan spesifikasi menengah. Sistem menggunakan pendekatan containerized agar mudah di-maintenance.

## 1. Docker Ecosystem
Sistem akan dibungkus dalam satu `docker-compose.yml` yang terdiri dari 3 service utama:
- `backend`: Menjalankan API Server dan Bot Polling/Webhook. Mengekspos port internal (misal: 8000).
- `frontend`: Menjalankan build statis Vue.js atau dev server. Mengekspos port internal (misal: 3000).
- `db`: PostgreSQL database untuk relasional data (log, user admin). Port 5432.

*(Catatan: ChromaDB berjalan secara lokal/embedded di dalam container `backend` dan menggunakan docker volume persisten).*

## 2. Nginx & Reverse Proxy
- Nginx akan diinstal langsung di host Ubuntu (atau via container terpisah).
- Berfungsi untuk menangani SSL (Let's Encrypt / Certbot).
- Trafik ke `admin.domain.com` di-routing ke container `frontend`.
- Trafik ke `api.domain.com` di-routing ke container `backend`.
- Webhook Telegram akan menerima trafik POST via endpoint spesifik (misal: `/webhook/telegram`) di Nginx dan diteruskan ke backend.

## 3. Data Persistence (Docker Volumes)
Pastikan hal berikut di-mount ke host agar data tidak hilang saat container restart:
- `/app/backend/data/chroma_db` (Vector storage)
- `/app/backend/data/docs` (Raw uploaded PDFs)
- `/var/lib/postgresql/data` (PostgreSQL data)

## 4. Continuous Integration / Development
Untuk fase development lokal, gunakan script run standar atau `docker-compose up --build`. Pastikan .env terkonfigurasi dengan benar sebelum build.