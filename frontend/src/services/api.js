/**
 * src/services/api.js
 * Centralized Axios instance for all API calls.
 * Import this in composables or components instead of using axios directly.
 *
 * Usage:
 *   import api from '@/services/api'
 *   const { data } = await api.get('/chat-logs')
 */
import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 300_000, // Meningkatkan timeout default ke 5 menit untuk menghindari limit 15 detik pada operasi berat
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
})

// ─── Request interceptor ─────────────────────────────────────────────────────
api.interceptors.request.use(
  (config) => {
    // Attach Bearer token when authentication is implemented:
    // const token = localStorage.getItem('access_token')
    // if (token) config.headers.Authorization = `Bearer ${token}`
    return config
  },
  (error) => Promise.reject(error),
)

// ─── Response interceptor ────────────────────────────────────────────────────
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status

    if (status === 401) {
      console.warn('[API] 401 Unauthorized – implement redirect to login here.')
    } else if (status === 500) {
      console.error('[API] 500 Server error', error.response?.data)
    }

    return Promise.reject(error)
  },
)

export default api

// ─── Typed endpoint helpers (extend as needed) ────────────────────────────────

/** GET /api/chat-logs */
export const getChatLogs = (params = {}) => api.get('/api/chat-logs', { params })

/** GET /api/documents */
export const getDocuments = () => api.get('/api/documents')

/** GET /api/documents/:id/chunks */
export const getDocumentChunks = (id) => api.get(`/api/documents/${id}/chunks`)

/** POST /api/documents/upload  (multipart/form-data) */
export const uploadDocument = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/api/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180_000, // Override timeout ke 3 menit untuk proses ingesti dokumen yang memakan waktu lama
  })
}

/** DELETE /api/documents/:id */
export const deleteDocument = (id) => api.delete(`/api/documents/${id}`)

/** GET /api/stats */
export const getDashboardStats = () => api.get('/api/stats')

/** POST /api/whatsapp/upload (multipart/form-data) */
export const uploadWhatsAppChat = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/api/whatsapp/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300_000, // Override ke 5 menit karena proses LLM WA chat bisa lama
  })
}

/** GET /api/whatsapp/pending */
export const getPendingFAQs = () => api.get('/api/whatsapp/pending')

/** PUT /api/whatsapp/pending/:id */
export const updatePendingFAQ = (id, payload) => api.put(`/api/whatsapp/pending/${id}`, payload)

/** DELETE /api/whatsapp/pending/:id */
export const deletePendingFAQ = (id) => api.delete(`/api/whatsapp/pending/${id}`)

/** POST /api/whatsapp/pending/:id/approve */
export const approveSingleFAQ = (id) => api.post(`/api/whatsapp/pending/${id}/approve`)

/** POST /api/whatsapp/approve-all */
export const approveAllFAQs = () => api.post('/api/whatsapp/approve-all')

/** GET /api/whatsapp/export */
export const exportFaqs = (status) => api.get('/api/whatsapp/export', {
  params: { status_filter: status },
  responseType: 'blob', // Penting untuk file download
})

/** POST /api/knowledge/reset — wipes ChromaDB and all DB records (destructive!) */
export const resetKnowledgeBase = () => api.post('/api/knowledge/reset')
