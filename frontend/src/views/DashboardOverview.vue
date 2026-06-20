<script setup>
/**
 * DashboardOverview.vue
 * Main dashboard page showing analytics stats and the chat log table.
 */
import { ref, onMounted } from 'vue'
import ChatLogsTable from '@/components/ChatLogsTable.vue'
import { getDashboardStats } from '@/services/api'

// Dynamic analytics from backend
const stats = ref([
  {
    id: 'total-sessions',
    label: 'Total Chat Sessions',
    value: '0',
    delta: 'Loading…',
    positive: true,
    icon: `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor" class="w-5 h-5"><path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 0 1-.825-.242m9.345-8.334a2.126 2.126 0 0 0-.476-.095 48.64 48.64 0 0 0-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0 0 11.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" /></svg>`,
    color: 'indigo',
  },
  {
    id: 'unique-users',
    label: 'Unique Users',
    value: '0',
    delta: 'Loading…',
    positive: true,
    icon: `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor" class="w-5 h-5"><path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" /></svg>`,
    color: 'blue',
  },
  {
    id: 'avg-similarity',
    label: 'Avg. Similarity Score',
    value: '0.00',
    delta: 'Loading…',
    positive: true,
    icon: `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor" class="w-5 h-5"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>`,
    color: 'emerald',
  },
  {
    id: 'active-docs',
    label: 'Active SOP Documents',
    value: '0',
    delta: 'Loading…',
    positive: true,
    icon: `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor" class="w-5 h-5"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" /></svg>`,
    color: 'violet',
  },
])

const colorMap = {
  indigo: { bg: 'bg-indigo-50', text: 'text-indigo-600', ring: 'ring-indigo-100' },
  blue: { bg: 'bg-blue-50', text: 'text-blue-600', ring: 'ring-blue-100' },
  emerald: { bg: 'bg-emerald-50', text: 'text-emerald-600', ring: 'ring-emerald-100' },
  violet: { bg: 'bg-violet-50', text: 'text-violet-600', ring: 'ring-violet-100' },
}

onMounted(async () => {
  try {
    const { data } = await getDashboardStats()
    stats.value[0].value = data.total_sessions.toString()
    stats.value[0].delta = 'Live from database'
    
    stats.value[1].value = data.unique_users.toString()
    stats.value[1].delta = 'From total chat logs'
    
    stats.value[2].value = data.avg_similarity.toFixed(2)
    stats.value[2].delta = 'Overall accuracy'
    
    stats.value[3].value = data.active_docs.toString()
    stats.value[3].delta = 'Indexed in ChromaDB'
  } catch (error) {
    console.error('Failed to fetch dashboard stats:', error)
    stats.value.forEach(s => s.delta = 'Failed to load data')
  }
})
</script>

<template>
  <div class="space-y-6">
    <!-- Page heading -->
    <div>
      <h1 class="text-2xl font-bold text-slate-900">Dashboard Overview</h1>
      <p class="text-sm text-slate-500 mt-1">
        Monitor the performance of the RAG system and author interaction history for ICICoS 2026.
      </p>
    </div>

    <!-- Stats Grid ─────────────────────────────────────────────────────────── -->
    <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
      <div
        v-for="stat in stats"
        :key="stat.id"
        :id="stat.id"
        class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 flex items-start gap-4 hover:shadow-md transition-shadow duration-200"
      >
        <!-- Icon -->
        <div
          :class="[
            'w-10 h-10 rounded-xl flex items-center justify-center ring-4 shrink-0',
            colorMap[stat.color].bg,
            colorMap[stat.color].text,
            colorMap[stat.color].ring,
          ]"
          v-html="stat.icon"
        ></div>

        <!-- Text -->
        <div>
          <p class="text-xs text-slate-500 font-medium">{{ stat.label }}</p>
          <p class="text-2xl font-bold text-slate-900 mt-0.5 leading-none">{{ stat.value }}</p>
          <p
            :class="[
              'text-xs mt-1.5 font-medium',
              stat.positive ? 'text-emerald-600' : 'text-red-500',
            ]"
          >
            {{ stat.delta }}
          </p>
        </div>
      </div>
    </div>

    <!-- Section divider -->
    <div class="flex items-center gap-3">
      <div class="flex-1 h-px bg-gray-100"></div>
      <span class="text-xs text-slate-400 font-semibold uppercase tracking-widest">Chat Logs</span>
      <div class="flex-1 h-px bg-gray-100"></div>
    </div>

    <!-- Chat Logs Table ─────────────────────────────────────────────────────── -->
    <ChatLogsTable />
  </div>
</template>
