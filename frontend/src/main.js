import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import axios from 'axios'

import App from './App.vue'
import './assets/main.css'

// ─── Axios global configuration ────────────────────────────────────────────
axios.defaults.headers.common['Content-Type'] = 'application/json'

// Optional: request interceptor (e.g., attach auth token in the future)
axios.interceptors.request.use((config) => {
  // const token = localStorage.getItem('token')
  // if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Optional: response interceptor (e.g., handle 401 globally)
axios.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      console.warn('[Axios] Unauthorized – redirect to login when ready.')
    }
    return Promise.reject(error)
  }
)

// ─── Vue Router ────────────────────────────────────────────────────────────
const routes = [
  {
    path: '/',
    redirect: '/dashboard',
  },
  {
    path: '/dashboard',
    name: 'DashboardOverview',
    component: () => import('./views/DashboardOverview.vue'),
    meta: { title: 'Dashboard – ICICoS 2026 Admin' },
  },
  {
    path: '/documents',
    name: 'DocumentManager',
    component: () => import('./views/DocumentManager.vue'),
    meta: { title: 'Document Manager – ICICoS 2026 Admin' },
  },
  {
    path: '/whatsapp-review',
    name: 'WhatsAppReview',
    component: () => import('./views/WhatsAppReview.vue'),
    meta: { title: 'WhatsApp Review – ICICoS 2026 Admin' },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Update document title on each navigation
router.afterEach((to) => {
  document.title = to.meta.title ?? 'ICICoS 2026 Admin'
})

// ─── Mount ─────────────────────────────────────────────────────────────────
const app = createApp(App)
app.use(router)

// Expose axios via globalProperties for Options API fallback
app.config.globalProperties.$axios = axios

app.mount('#app')
