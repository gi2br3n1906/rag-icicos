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
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
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
      console.warn('[API] 401 Unauthorized – redirecting to login.')
      localStorage.removeItem('auth_token')
      localStorage.removeItem('user_role')
      localStorage.removeItem('user_email')
      window.location.href = '/login'
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

/** DELETE /api/chat-logs (Reset all logs/user memory) */
export const clearAllChatLogs = () => api.delete('/api/chat-logs')


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

/** PUT /api/documents/:id/title */
export const updateDocumentTitle = (id, title) => api.put(`/api/documents/${id}/title`, { title })

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

/** GET /api/whatsapp/faqs (Filter status: all, pending, or approved) */
export const getFaqs = (status = 'all') => api.get('/api/whatsapp/faqs', {
  params: { status_filter: status },
})

/** POST /api/whatsapp/faqs (Create a new FAQ manually) */
export const createFaq = (payload) => api.post('/api/whatsapp/faqs', payload)

/** PUT /api/whatsapp/pending/:id */
export const updatePendingFAQ = (id, payload) => api.put(`/api/whatsapp/pending/${id}`, payload)
export const updateFAQ = updatePendingFAQ // alias umum

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

/** GET /api/whatsapp/export/json — download seluruh tabel FAQ sebagai file JSON */
export const exportFaqsJson = () => api.get('/api/whatsapp/export/json', {
  responseType: 'blob',
})

/** POST /api/whatsapp/import/json — upload file JSON FAQ untuk diimport ke database & ChromaDB */
export const importFaqsJson = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/api/whatsapp/import/json', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120_000, // 2 menit untuk proses embed ke ChromaDB
  })
}

/** POST /api/auth/login */
export const loginUser = (email, password) => api.post('/api/auth/login', { email, password })


/** POST /api/knowledge/reset — wipes ChromaDB and all DB records (destructive!) */
export const resetKnowledgeBase = () => api.post('/api/knowledge/reset')
