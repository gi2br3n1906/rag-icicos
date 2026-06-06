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
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  timeout: 15_000,
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

/** POST /api/documents/upload  (multipart/form-data) */
export const uploadDocument = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/api/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/** DELETE /api/documents/:id */
export const deleteDocument = (id) => api.delete(`/api/documents/${id}`)
