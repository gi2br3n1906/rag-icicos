<script setup>
/**
 * ChatLogsTable.vue
 * Displays a paginated table of author chat logs with similarity score badges.
 * Data is fetched from GET /api/chat-logs via the centralized Axios service.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { getChatLogs, clearAllChatLogs } from '@/services/api'


// ─── Remote data state ───────────────────────────────────────────────────────
const logs = ref([])
const isLoading = ref(false)
const fetchError = ref(null)
const isResetting = ref(false)

async function handleResetLogs() {
  const count = logs.value.length
  if (count === 0) {
    alert('Tidak ada log chat untuk di-reset.')
    return
  }

  const confirmFirst = confirm(`Apakah Anda yakin ingin menghapus seluruh ${count} log percakapan?`)
  if (!confirmFirst) return

  const confirmSecond = confirm('TINDAKAN INI PERMANEN: Semua riwayat log chat dan memori ingatan Telegram Bot untuk SEMUA user akan dihapus total. Lanjutkan?')
  if (!confirmSecond) return

  isResetting.value = true
  try {
    const { data } = await clearAllChatLogs()
    alert(data?.message ?? 'Seluruh log percakapan berhasil di-reset.')
    logs.value = []
  } catch (err) {
    console.error('[ChatLogsTable] Failed to reset chat logs:', err)
    alert(err.response?.data?.detail ?? 'Gagal menghapus log percakapan.')
  } finally {
    isResetting.value = false
  }
}

async function fetchLogs() {
  isLoading.value = true
  fetchError.value = null
  try {
    const { data } = await getChatLogs()
    // Normalize: accept either a plain array or { data: [...] } envelope
    logs.value = Array.isArray(data) ? data : (data?.data ?? [])
  } catch (err) {
    console.error('[ChatLogsTable] Failed to fetch chat-logs:', err)
    fetchError.value =
      err.response?.data?.detail ??
      err.message ??
      'Failed to load data. Check backend connection.'
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchLogs)

// Reset to page 1 whenever new data arrives
watch(logs, () => { currentPage.value = 1 })

// ─── Similarity badge helpers ─────────────────────────────────────────────────
function scoreBadgeClass(score) {
  if (score > 0.7) return 'bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300'
  if (score >= 0.4) return 'bg-amber-100 text-amber-700 ring-1 ring-amber-300'
  return 'bg-red-100 text-red-600 ring-1 ring-red-300'
}

function scoreLabel(score) {
  if (score > 0.7) return 'High'
  if (score >= 0.4) return 'Medium'
  return 'Low'
}

// ─── Search / filter ──────────────────────────────────────────────────────────
const searchQuery = ref('')

const filteredLogs = computed(() => {
  const q = searchQuery.value.toLowerCase().trim()
  if (!q) return logs.value
  return logs.value.filter(
    (log) =>
      (log.userId ?? log.user_id ?? '').toLowerCase().includes(q) ||
      (log.query ?? log.question ?? '').toLowerCase().includes(q),
  )
})

// ─── Pagination ───────────────────────────────────────────────────────────────
const ITEMS_PER_PAGE = 5
const currentPage = ref(1)

const filteredTotalPages = computed(() =>
  Math.max(1, Math.ceil(filteredLogs.value.length / ITEMS_PER_PAGE)),
)

const displayedLogs = computed(() => {
  const start = (currentPage.value - 1) * ITEMS_PER_PAGE
  return filteredLogs.value.slice(start, start + ITEMS_PER_PAGE)
})

// Reset page when search changes
watch(searchQuery, () => { currentPage.value = 1 })

function prevPage() {
  if (currentPage.value > 1) currentPage.value--
}

function nextPage() {
  if (currentPage.value < filteredTotalPages.value) currentPage.value++
}

// ─── Field normalizer ─────────────────────────────────────────────────────────
// Backend might return snake_case or camelCase – handle both gracefully
function normField(log, camel, snake) {
  return log[camel] ?? log[snake] ?? ''
}

function formatDateTime(val) {
  if (!val) return ''
  try {
    const d = new Date(val)
    if (isNaN(d.getTime())) return val
    
    const day = String(d.getDate()).padStart(2, '0')
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    const month = months[d.getMonth()]
    const year = d.getFullYear()
    const hours = String(d.getHours()).padStart(2, '0')
    const minutes = String(d.getMinutes()).padStart(2, '0')
    
    return `${day} ${month} ${year}, ${hours}:${minutes}`
  } catch (e) {
    return val
  }
}

// ─── Expand/Collapse Answers ──────────────────────────────────────────────────
const expandedLogs = ref({})

function toggleExpand(id) {
  expandedLogs.value[id] = !expandedLogs.value[id]
}

function isExpanded(id) {
  return !!expandedLogs.value[id]
}

function shouldShowToggle(text) {
  if (!text) return false
  // Remove HTML tags to count actual text length
  const plainText = text.replace(/<[^>]*>/g, '')
  return plainText.length > 80
}

// Reset expanded states on page or search filter change
watch([currentPage, searchQuery], () => {
  expandedLogs.value = {}
})
</script>


<template>
  <div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
    <!-- Table header + search -->
    <div class="px-6 py-4 border-b border-gray-100 flex items-center justify-between gap-4 flex-wrap">
      <div>
        <h2 class="text-base font-semibold text-slate-800">Author Chat Log History</h2>
        <p class="text-xs text-slate-400 mt-0.5">
          <template v-if="isLoading">Loading data…</template>
          <template v-else-if="fetchError">–</template>
          <template v-else>{{ filteredLogs.length }} conversation session(s) found</template>
        </p>
      </div>

      <div class="flex items-center gap-3">
        <!-- Reset logs button -->
        <button
          @click="handleResetLogs"
          :disabled="isLoading || isResetting"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-600 hover:text-rose-700 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed transition"
          title="Hapus seluruh riwayat chat log & memori user"
        >
          <svg v-if="isResetting" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 animate-spin"><path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clip-rule="evenodd" /></svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5"><path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clip-rule="evenodd" /></svg>
          Reset Memory Logs
        </button>

        <!-- Refresh button -->
        <button
          id="chat-logs-refresh"
          @click="fetchLogs"
          :disabled="isLoading"
          class="p-2 rounded-lg text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 disabled:opacity-40 disabled:cursor-not-allowed transition"
          title="Refresh data"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            :class="['w-4 h-4', isLoading && 'animate-spin']"
          >
            <path
              fill-rule="evenodd"
              d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z"
              clip-rule="evenodd"
            />
          </svg>
        </button>


        <!-- Search input -->
        <div class="relative">
          <svg xmlns="http://www.w3.org/2000/svg" class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.197 5.197a7.5 7.5 0 0 0 10.606 10.606Z" />
          </svg>
          <input
            id="chat-log-search"
            v-model="searchQuery"
            type="text"
            placeholder="Search user or question…"
            class="pl-9 pr-4 py-2 text-sm bg-gray-50 border border-gray-200 rounded-lg w-60 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent transition"
          />
        </div>
      </div>
    </div>

    <!-- ── Error Banner ───────────────────────────────────────────────────── -->
    <div
      v-if="fetchError"
      class="mx-6 mt-4 flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5 shrink-0 mt-0.5">
        <path fill-rule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM8.28 7.22a.75.75 0 0 0-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 1 0 1.06 1.06L10 11.06l1.72 1.72a.75.75 0 1 0 1.06-1.06L11.06 10l1.72-1.72a.75.75 0 0 0-1.06-1.06L10 8.94 8.28 7.22Z" clip-rule="evenodd"/>
      </svg>
      <div>
        <p class="font-semibold">Failed to load chat logs</p>
        <p class="text-xs text-red-600 mt-0.5">{{ fetchError }}</p>
      </div>
      <button @click="fetchLogs" class="ml-auto text-xs text-red-600 hover:underline font-medium">Retry</button>
    </div>

    <!-- ── Skeleton loader ────────────────────────────────────────────────── -->
    <div v-if="isLoading" class="p-6 space-y-3">
      <div
        v-for="i in 5"
        :key="i"
        class="h-10 bg-slate-100 rounded-lg animate-pulse"
        :style="{ opacity: 1 - i * 0.15 }"
      ></div>
    </div>

    <!-- ── Data table ─────────────────────────────────────────────────────── -->
    <div v-else class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="bg-slate-50 border-b border-gray-100">
            <th class="text-left px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider w-36">
              Date / Time
            </th>
            <th class="text-left px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider w-28">
              User ID
            </th>
            <th class="text-left px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Author's Question
            </th>
            <th class="text-left px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Bot Answer
            </th>
            <th class="text-center px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider w-28">
              Similarity
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-50">
          <tr
            v-for="log in displayedLogs"
            :key="log.id"
            class="hover:bg-slate-50/60 transition-colors duration-100"
          >
            <!-- Timestamp -->
            <td class="px-5 py-3.5 text-slate-500 text-xs whitespace-nowrap font-mono">
              {{ formatDateTime(normField(log, 'timestamp', 'created_at')) }}
            </td>


            <!-- User ID -->
            <td class="px-5 py-3.5">
              <span class="inline-flex items-center gap-1.5">
                <span class="w-6 h-6 rounded-full bg-indigo-100 text-indigo-600 flex items-center justify-center text-xs font-bold">
                  {{ (normField(log, 'userId', 'user_id') || '?').charAt(0).toUpperCase() }}
                </span>
                <span class="text-slate-700 font-medium">
                  {{ normField(log, 'userId', 'user_id') }}
                </span>
              </span>
            </td>

            <!-- Question -->
            <td class="px-5 py-3.5 text-slate-600 max-w-xs">
              <p class="line-clamp-2">{{ log.query ?? log.question }}</p>
            </td>

            <!-- Bot Answer – renders <b> / <i> HTML from backend safely -->
            <td 
              class="px-5 py-3.5 text-slate-600 max-w-sm transition-colors duration-150"
              :class="{ 'cursor-pointer hover:bg-indigo-50/30': shouldShowToggle(log.answer) }"
              @click="shouldShowToggle(log.answer) && toggleExpand(log.id)"
            >
              <div class="relative">
                <!-- eslint-disable-next-line vue/no-v-html -->
                <div 
                  :class="[
                    'prose-sm text-slate-600 leading-relaxed transition-all duration-300',
                    isExpanded(log.id) ? 'line-clamp-none' : 'line-clamp-2'
                  ]" 
                  v-html="log.answer"
                ></div>
                
                <div 
                  v-if="shouldShowToggle(log.answer)"
                  class="mt-1.5 flex items-center gap-1 text-[11px] font-bold text-indigo-600 hover:text-indigo-800 transition-colors select-none"
                >
                  <span>{{ isExpanded(log.id) ? 'Collapse Answer' : 'Read Full Answer' }}</span>
                  <svg 
                    xmlns="http://www.w3.org/2000/svg" 
                    viewBox="0 0 20 20" 
                    fill="currentColor" 
                    :class="['w-3.5 h-3.5 transition-transform duration-200', isExpanded(log.id) ? 'rotate-180' : '']"
                  >
                    <path fill-rule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
                  </svg>
                </div>
              </div>
            </td>

            <!-- Similarity Score Badge -->
            <td class="px-5 py-3.5 text-center">
              <div class="flex flex-col items-center gap-1">
                <span
                  :class="[
                    'inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold',
                    scoreBadgeClass(normField(log, 'similarityScore', 'similarity_score')),
                  ]"
                >
                  {{ scoreLabel(normField(log, 'similarityScore', 'similarity_score')) }}
                </span>
                <span class="text-xs text-slate-400 font-mono">
                  {{ Number(normField(log, 'similarityScore', 'similarity_score')).toFixed(2) }}
                </span>
              </div>
            </td>
          </tr>

          <!-- Empty state -->
          <tr v-if="displayedLogs.length === 0 && !isLoading">
            <td colspan="5" class="px-5 py-12 text-center text-slate-400">
              <svg xmlns="http://www.w3.org/2000/svg" class="w-10 h-10 mx-auto mb-3 text-slate-300" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 0 1-.825-.242m9.345-8.334a2.126 2.126 0 0 0-.476-.095 48.64 48.64 0 0 0-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0 0 11.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
              </svg>
              <p class="text-sm font-medium">No conversation data found.</p>
              <p class="text-xs mt-1">
                {{ searchQuery ? 'Try a different search keyword.' : 'No author chat logs yet.' }}
              </p>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination controls -->
    <div class="px-6 py-3 border-t border-gray-100 flex items-center justify-between">
      <p class="text-xs text-slate-400">
        Page {{ currentPage }} of {{ filteredTotalPages }}
      </p>
      <div class="flex gap-2">
        <button
          id="chat-logs-prev"
          @click="prevPage"
          :disabled="currentPage === 1"
          class="px-3 py-1.5 text-xs rounded-lg border border-gray-200 text-slate-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          ← Prev
        </button>
        <button
          id="chat-logs-next"
          @click="nextPage"
          :disabled="currentPage >= filteredTotalPages"
          class="px-3 py-1.5 text-xs rounded-lg border border-gray-200 text-slate-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          Next →
        </button>
      </div>
    </div>
  </div>
</template>
