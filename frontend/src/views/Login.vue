<script setup>
/**
   Login.vue
   Premium Login screen for the ICICoS 2026 Admin Panel.
   Validates credentials via POST /api/auth/login and stores session tokens.
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { loginUser } from '@/services/api'

const router = useRouter()

const email = ref('')
const password = ref('')
const isLoading = ref(false)
const errorMessage = ref('')

async function handleLogin() {
  if (!email.value.trim() || !password.value) {
    errorMessage.value = 'Email and password are required.'
    return
  }

  isLoading.value = true
  errorMessage.value = ''

  try {
    const { data } = await loginUser(email.value.trim(), password.value)
    
    if (data.access_token) {
      // Store session state
      localStorage.setItem('auth_token', data.access_token)
      localStorage.setItem('user_role', data.user.role)
      localStorage.setItem('user_email', data.user.email)
      
      // Redirect to Dashboard
      router.push({ name: 'DashboardOverview' })
    } else {
      errorMessage.value = 'Failed to retrieve access token.'
    }
  } catch (err) {
    console.error('[Login] Request error:', err)
    errorMessage.value =
      err.response?.data?.detail ??
      err.message ??
      'Invalid email or password.'
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen w-full flex items-center justify-center bg-slate-950 relative overflow-hidden px-4">
    <!-- Neon glow spots -->
    <div class="absolute -top-40 -left-40 w-96 h-96 rounded-full bg-indigo-500/10 blur-[128px]"></div>
    <div class="absolute -bottom-40 -right-40 w-96 h-96 rounded-full bg-violet-500/10 blur-[128px]"></div>
    <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full bg-blue-500/5 blur-[180px]"></div>

    <!-- Login Box Card -->
    <div class="w-full max-w-md bg-slate-900/60 border border-slate-800/80 backdrop-blur-xl rounded-3xl p-8 shadow-2xl relative z-10 transition-all">
      
      <!-- Brand Logo Header -->
      <div class="flex flex-col items-center text-center mb-8">
        <div class="w-12 h-12 rounded-2xl bg-gradient-to-tr from-indigo-500 to-violet-500 flex items-center justify-center shadow-lg shadow-indigo-500/20 mb-4 animate-pulse">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.2" stroke="white" class="w-6 h-6">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z" />
          </svg>
        </div>
        <h2 class="text-xl font-bold text-white tracking-tight">ICICoS 2026 Admin Panel</h2>
        <p class="text-xs text-slate-400 mt-1">Please sign in to manage the chatbot knowledge base</p>
      </div>

      <!-- Error message banner -->
      <div v-if="errorMessage" class="mb-5 bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs rounded-xl px-4 py-3 flex items-start gap-2.5">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 shrink-0 mt-0.5">
          <path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" />
        </svg>
        <span>{{ errorMessage }}</span>
      </div>

      <!-- Input Form -->
      <form @submit.prevent="handleLogin" class="space-y-5">
        <!-- Email Input -->
        <div class="space-y-1.5">
          <label for="email" class="block text-xs font-semibold text-slate-300">Email Address</label>
          <div class="relative">
            <input
              id="email"
              v-model="email"
              type="email"
              placeholder="e.g. icicos@live.undip.ac.id"
              class="w-full bg-slate-950/80 border border-slate-800 focus:border-indigo-500/80 focus:ring-2 focus:ring-indigo-500/20 text-white rounded-xl pl-4 pr-4 py-3 text-sm transition outline-none"
              required
            />
          </div>
        </div>

        <!-- Password Input -->
        <div class="space-y-1.5">
          <label for="password" class="block text-xs font-semibold text-slate-300">Password</label>
          <div class="relative">
            <input
              id="password"
              v-model="password"
              type="password"
              placeholder="••••••••"
              class="w-full bg-slate-950/80 border border-slate-800 focus:border-indigo-500/80 focus:ring-2 focus:ring-indigo-500/20 text-white rounded-xl pl-4 pr-4 py-3 text-sm transition outline-none"
              required
            />
          </div>
        </div>

        <!-- Submit Button -->
        <button
          type="submit"
          :disabled="isLoading"
          class="w-full bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-bold py-3 px-4 rounded-xl transition duration-150 shadow-lg shadow-indigo-600/15 disabled:opacity-40 disabled:cursor-wait flex items-center justify-center gap-2 mt-6"
        >
          <!-- Loading spinner -->
          <svg v-if="isLoading" class="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <span>{{ isLoading ? 'Signing In…' : 'Sign In' }}</span>
        </button>
      </form>

      <!-- Account Help Guidelines Box -->
      <div class="mt-8 pt-6 border-t border-slate-800/80 flex flex-col gap-3 text-[11px] text-slate-400">
        <p class="font-semibold text-slate-300">Demo Accounts Available:</p>
        <div class="flex flex-col gap-2 bg-slate-950/40 border border-slate-800/50 p-3 rounded-xl">
          <div>
            <span class="font-bold text-indigo-400">Admin Role:</span>
            <p class="font-mono mt-0.5">icicos@live.undip.ac.id / chatbot9.</p>
          </div>
          <div class="border-t border-slate-900/60 pt-2">
            <span class="font-bold text-indigo-400">Humas Role:</span>
            <p class="font-mono mt-0.5">cs.icicos@gmail.com / chatbot9.</p>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>
