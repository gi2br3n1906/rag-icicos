# Linux VPS Deployment & Migration Guide (Ubuntu/Debian)

This document provides a step-by-step guide to deploying the ICICoS 2026 RAG Bot application onto a Linux VPS (Ubuntu 22.04 LTS recommended) and migrating database/files from the old Windows PC server.

---

## 1. Architecture Overview

On the new VPS, the application is deployed in a **hybrid setup** for optimal performance and stability:
* **Database (PostgreSQL 15 & pgAdmin 4)**: Runs inside Docker containers for isolated persistence.
* **Backend API (FastAPI/Uvicorn)**: Runs on the host Python 3.10+ virtual env, daemonized via **Systemd** (Port 8000).
* **Telegram Bot Poller**: Runs on the host Python 3.10+ virtual env, daemonized via **Systemd**.
* **Frontend Dashboard (Vue.js / Vite)**: Built into static HTML/JS/CSS assets and served directly by **Nginx** (Port 80 / 443 with SSL).

```
                  ┌──────────────────────────────────────────┐
                  │                 Linux VPS                │
                  │                                          │
                  │               Nginx (80/443)             │
                  │               /            \             │
                  │     (Static HTML/JS)     (Proxy /api)    │
                  │             |                |           │
                  │      Frontend Dist     Backend API (8000)│
                  │                        (FastAPI/Uvicorn) │
                  │                          /           \   │
                  │              Telegram Bot             \  │
                  │              (Systemd Daemon)          \ │
                  │                                         \│
                  │             ChromaDB (Embedded)      Postgres (Docker)
                  └──────────────────────────────────────────┘
```

---

## 2. Server Preparation & Installation

Run the following commands on your fresh Ubuntu VPS to update packages and install core dependencies.

### Step A: Update OS & Install Basic Tools
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install git curl build-essential libpq-dev software-properties-common -y
```

### Step B: Install Python 3.10+ and venv
```bash
sudo apt install python3 python3-pip python3-venv -y
```

### Step C: Install Node.js (v18+) & NPM
```bash
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install nodejs -y
```

### Step D: Install Docker & Docker Compose
```bash
# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

# Install Docker packages:
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y

# Verify Docker installation
sudo docker run hello-world
```

### Step E: Install Nginx & Certbot (SSL)
```bash
sudo apt install nginx certbot python3-certbot-nginx -y
```

---

## 3. Clone Repository & Setup Directory

We will configure the application directory under `/var/www/rag-icicos`.

```bash
# Clone the repository
sudo git clone https://github.com/gi2br3n1906/rag-icicos.git /var/www/rag-icicos

# Set ownership to your standard user (replace 'ubuntu' with your actual VPS username)
sudo chown -R ubuntu:ubuntu /var/www/rag-icicos
cd /var/www/rag-icicos
```

---

## 4. Run Relational Database (Docker Compose)

The repository contains a `docker-compose.yml` file configuring PostgreSQL 15 and pgAdmin.

### Step A: Setup Environment Variables
Create the `.env` file in the root directory:
```bash
cp .env.example .env
nano .env
```
Ensure you set secure values for:
* `DB_USER`
* `DB_PASSWORD`
* `DB_NAME`
* `PGADMIN_EMAIL`
* `PGADMIN_PASSWORD`
* `GEMINI_API_KEY` (or other LLM credentials)
* `TELEGRAM_BOT_TOKEN`

### Step B: Start Database Service
```bash
# Spin up PostgreSQL and pgAdmin containers in detached mode
sudo docker compose up -d

# Verify containers are running
sudo docker compose ps
```

---

## 5. Backend Deployment (Systemd Daemons)

We run the FastAPI API and the Telegram Bot as system services so they auto-restart on crashes or OS reboots.

### Step A: Setup Python Virtual Environment
```bash
cd /var/www/rag-icicos

# Create virtual environment
python3 -m venv venv

# Activate and install backend dependencies
source venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt
deactivate
```

### Step B: Create API Server Systemd Service
Create the service configuration file:
```bash
sudo nano /etc/systemd/system/icicos-backend.service
```
Paste the following configuration:
```ini
[Unit]
Description=ICICoS RAG Backend API Server
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/var/www/rag-icicos
EnvironmentFile=/var/www/rag-icicos/.env
ExecStart=/var/www/rag-icicos/venv/bin/python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Step C: Create Telegram Bot Systemd Service
Create the service configuration file:
```bash
sudo nano /etc/systemd/system/icicos-bot.service
```
Paste the following configuration:
```ini
[Unit]
Description=ICICoS Telegram Bot Poller Daemon
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/var/www/rag-icicos
EnvironmentFile=/var/www/rag-icicos/.env
ExecStart=/var/www/rag-icicos/venv/bin/python -m backend.bot.bot_runner
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Step D: Enable & Start Services
```bash
# Reload systemd configuration
sudo systemctl daemon-reload

# Enable services to run on startup
sudo systemctl enable icicos-backend.service
sudo systemctl enable icicos-bot.service

# Start the services
sudo systemctl start icicos-backend.service
sudo systemctl start icicos-bot.service

# Verify statuses
sudo systemctl status icicos-backend.service
sudo systemctl status icicos-bot.service
```

---

## 6. Frontend Build & Deployment

We compile the Vue 3 dashboard into static resources to be served by Nginx.

### Step A: Install Node Dependencies & Build
Create the frontend configuration if needed (ensure `VITE_API_BASE_URL` in `.env` is set correctly, or leave empty if using Nginx reverse proxy routing).
```bash
cd /var/www/rag-icicos/frontend

# Install packages
npm install

# Build static assets (generates files in /var/www/rag-icicos/frontend/dist)
npm run build
```

---

## 7. Nginx Setup & SSL (HTTPS)

Configure Nginx to serve the compiled frontend, reverse proxy api calls to Uvicorn, and redirect HTTP to HTTPS.

### Step A: Configure Server Block
Remove default configuration and create a new site config:
```bash
sudo rm /etc/nginx/sites-enabled/default
sudo nano /etc/nginx/sites-available/rag-icicos
```
Paste the following block (replace `yourdomain.com` with your actual domain name or IP address):
```nginx
server {
    listen 80;
    server_name yourdomain.com; # Replace with your domain or IP

    # Root folder containing Vue.js built static files
    root /var/www/rag-icicos/frontend/dist;
    index index.html;

    # Serve static frontend SPA files
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Reverse proxy API requests to FastAPI
    location /api {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        
        # Increase timeouts for long-running LLM processes
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
    }

    # Enable client maximum body size (for document uploads)
    client_max_body_size 50M;
}
```

### Step B: Enable Configuration & Test Nginx
```bash
# Link to sites-enabled
sudo ln -s /etc/nginx/sites-available/rag-icicos /etc/nginx/sites-enabled/

# Test configuration syntax
sudo nginx -t

# Restart Nginx service
sudo systemctl restart nginx
```

### Step C: Configure Let's Encrypt SSL (HTTPS)
If you have a domain pointed to the VPS, install SSL automatically with Certbot:
```bash
sudo certbot --nginx -d yourdomain.com
```
Follow the interactive prompts to enable SSL redirection.

---

## 8. Migration Steps from Windows to Linux VPS

To transfer all your hard-earned data, chats, and curated FAQs to the new server:

### Option A: Using Dashboard UI (Recommended for FAQs)
If you only need to migrate the Curated/Approved FAQs:
1. **On Windows PC**: Open the Dashboard and navigate to the **WhatsApp Chat Review** page. Click **Export DB** to download `faq_database_export.json`.
2. Copy the raw PDF SOP files from your local system to `/var/www/rag-icicos/backend/data/docs` on the Linux VPS.
3. **On Linux VPS**: Open the Admin Dashboard, click **Reset Knowledge Base** to clear it, and upload all PDF SOP files.
4. Go to **WhatsApp Chat Review**, click **Import DB** and upload `faq_database_export.json`.
5. The system will automatically write them to PostgreSQL and embed them to ChromaDB!

### Option B: Database Dump & File Rsync (Complete Database Clone)
If you want to migrate all historical records (including bot chat logs and users):

#### 1. Export database from Windows:
In the Windows Command Prompt or PowerShell (where PostgreSQL is running):
```powershell
pg_dump -U postgres -d postgres -h localhost -p 5432 -F c -b -v -f icicos_db_backup.dump
```

#### 2. Copy Backup File and Document Folder to Linux:
Use `scp` or a SFTP client (like FileZilla) to copy the dump file and PDF documents from Windows to the VPS:
```bash
# Copy DB dump
scp icicos_db_backup.dump ubuntu@your-vps-ip:/home/ubuntu/

# Copy uploaded documents (PDFs)
scp -r "d:\Coding\Project Kerjaan\RAG-ICICOS\backend\data\docs" ubuntu@your-vps-ip:/var/www/rag-icicos/backend/data/
```

#### 3. Restore Database on Linux Host:
Because PostgreSQL is running inside a Docker container, we copy the dump file into the container and execute `pg_restore`:
```bash
# Copy dump file into Docker Postgres container
sudo docker cp /home/ubuntu/icicos_db_backup.dump icicos_postgres:/tmp/

# Execute restore inside the container
# Note: Ensure the db user/password matches what you set in .env on the VPS
sudo docker exec -it icicos_postgres pg_restore -U postgres -d postgres -v /tmp/icicos_db_backup.dump --clean
```

#### 4. Run Vector Re-Ingestion (Optional)
If you copied the documents and restored PostgreSQL, but need to re-verify/re-populate ChromaDB on the VPS:
1. Log in to the Admin Dashboard.
2. Go to **Document Manager**.
3. Re-upload or re-verify documents. Alternatively, copy the `backend/data/chroma_db` folder from Windows directly to the VPS if you want to skip re-indexing:
```bash
scp -r "d:\Coding\Project Kerjaan\RAG-ICICOS\backend\data\chroma_db" ubuntu@your-vps-ip:/var/www/rag-icicos/backend/data/
```

---

## 9. Useful Operations & Logs

Here are common commands for managing the services on the Linux VPS:

```bash
# Restart Backend API
sudo systemctl restart icicos-backend.service

# Read Backend API Logs (real-time)
journalctl -u icicos-backend.service -f

# Restart Telegram Bot
sudo systemctl restart icicos-bot.service

# Read Telegram Bot Logs
journalctl -u icicos-bot.service -f

# Restart Nginx
sudo systemctl restart nginx

# Inspect Nginx Error Logs
sudo tail -f /var/log/nginx/error.log
```

---

## 10. Public Exposure via Cloudflare Tunnel (Optional/Intranet VPS)

Jika VPS Anda diletakkan di dalam **intranet kampus (seperti LAN Universitas Diponegoro)** yang berada di belakang NAT/Firewall dan **tidak memiliki IP Publik**, Anda tidak bisa menggunakan Certbot biasa karena port 80/443 tidak bisa diakses dari luar.

Solusi terbaik adalah menggunakan **Cloudflare Tunnel (`cloudflared`)**. Tunnels bekerja dengan membuat koneksi keluar (*outbound*) yang aman dari VPS ke jaringan Cloudflare, sehingga Anda **tidak perlu membuka port masuk** (*inbound*) apa pun pada firewall kampus.

### Keuntungan:
* Tidak butuh IP Publik atau konfigurasi Port Forwarding di router kampus.
* Otomatis mendapatkan SSL/HTTPS gratis dari Cloudflare (tidak perlu Certbot di host).
* Melindungi server asli dari serangan DDoS secara langsung.

---

### Langkah A: Install `cloudflared` pada Debian 12

Jalankan perintah berikut di terminal VPS untuk memasang repositori resmi Cloudflare dan mendownload package-nya:

```bash
# Buat direktori keyring jika belum ada
sudo mkdir -p --mode=0755 /usr/share/keyrings

# Unduh GPG Key Cloudflare
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null

# Daftarkan repositori cloudflared (Debian Bookworm)
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared bookworm main' | sudo tee /etc/apt/sources.list.d/cloudflared.list

# Update package list & install
sudo apt update
sudo apt install cloudflared -y
```

---

### Langkah B: Buat Tunnel di Cloudflare Dashboard (Dashboard-Managed)

Metode ini adalah yang termudah karena semua konfigurasi routing dan domain dikelola langsung dari web browser:

1. Masuk ke **[Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/)**.
2. Pilih menu **Networks** -> **Tunnels** di sidebar kiri.
3. Klik tombol **Create a Tunnel**.
4. Pilih **Cloudflare** (Connector) -> klik **Next**.
5. Beri nama tunnel Anda (misalnya: `icicos-vps-undip`) -> klik **Save tunnel**.
6. Cloudflare akan menampilkan beberapa tab perintah instalasi. Pilih tab **Debian (amd64)**.
7. Di bagian bawah, Anda akan melihat baris perintah dengan **token** unik. Salin perintah tersebut, misalnya:
   ```bash
   sudo cloudflared service install eyJhIjoiY2... (token Anda)
   ```
8. **Paste dan jalankan perintah tersebut di terminal VPS Anda**. Perintah ini otomatis mendaftarkan dan menjalankan `cloudflared` sebagai system service di Linux yang akan menyala otomatis jika VPS reboot.
9. Kembali ke browser. Status di Cloudflare Dashboard akan berubah menjadi **Active** (Connected) -> klik **Next**.

---

### Langkah C: Konfigurasikan Routing Domain (Public Hostname)

Sekarang, hubungkan domain Anda ke web server Nginx lokal di dalam VPS:

1. Di tab **Public Hostname**, klik **Add a public hostname**.
2. Isi kolom domain yang Anda miliki di Cloudflare:
   * **Subdomain**: `icicos` (atau kosongkan jika ingin domain utama)
   * **Domain**: `domainanda.com`
   * **Path**: (kosongkan)
3. Di kolom **Service** (tujuan lokal di dalam VPS):
   * **Type**: `HTTP`
   * **URL**: `localhost:80` (karena Nginx kita berjalan di port 80 host)
4. Klik **Save hostname**.

---

### Langkah D: Verifikasi Koneksi
* Buka domain Anda (misalnya `https://icicos.domainanda.com`) dari HP atau komputer luar.
* Cloudflare akan otomatis mengamankan koneksi dengan HTTPS (SSL) dan meneruskan lalu lintasnya secara aman lewat tunnel menuju Nginx port 80 di dalam VPS lokal Anda.
* Uji coba login ke Admin Dashboard dan kirim chat ke bot Telegram untuk memastikan semua komponen berjalan lancar!

