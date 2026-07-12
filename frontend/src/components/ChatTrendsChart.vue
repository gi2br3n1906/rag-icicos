<script setup>
/**
 * ChatTrendsChart.vue
 * Renders a premium, interactive SVG-based area-line chart showing total chat trends.
 * Supports toggle filters: Hourly, Daily, Weekly, and Monthly.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { getChatTrends } from '@/services/api'

const activeRange = ref('daily') // 'hourly' | 'daily' | 'weekly' | 'monthly'
const trendsData = ref([])
const isLoading = ref(false)
const fetchError = ref('')

// Tooltip state for interactive hovering
const hoveredIndex = ref(null)
const tooltipX = ref(0)
const tooltipY = ref(0)
const tooltipContent = ref({ label: '', value: 0 })

// Chart geometry settings
const width = 800
const height = 160
const padding = { top: 15, right: 25, bottom: 25, left: 40 }

const chartWidth = computed(() => width - padding.left - padding.right)
const chartHeight = computed(() => height - padding.top - padding.bottom)

// Fetch data from backend API
async function loadTrends() {
  isLoading.value = true
  fetchError.value = ''
  try {
    const { data } = await getChatTrends(activeRange.value)
    trendsData.value = data
  } catch (err) {
    console.error('[TrendsChart] Error loading trends:', err)
    fetchError.value = err.response?.data?.detail ?? 'Failed to load chart trends.'
  } finally {
    isLoading.value = false
  }
}

// Reload trends when timeframe selection updates
watch(activeRange, () => {
  hoveredIndex.value = null
  loadTrends()
})

// Calculate values bounds
const maxValue = computed(() => {
  if (trendsData.value.length === 0) return 10
  const max = Math.max(...trendsData.value.map(d => d.value))
  return max === 0 ? 10 : Math.ceil(max * 1.1) // 10% padding on top
})

// Map points to SVG coordinates
const points = computed(() => {
  if (trendsData.value.length === 0) return []
  const len = trendsData.value.length
  
  return trendsData.value.map((item, index) => {
    // X distributed evenly
    const x = padding.left + (index / (len - 1 || 1)) * chartWidth.value
    // Y mapped linearly
    const ratio = item.value / maxValue.value
    const y = height - padding.bottom - ratio * chartHeight.value
    return { x, y, label: item.label, value: item.value }
  })
})

// Generate SVG Path string for the line
const linePath = computed(() => {
  const pts = points.value
  if (pts.length === 0) return ''
  return pts.reduce((path, p, i) => {
    return i === 0 ? `M ${p.x} ${p.y}` : `${path} L ${p.x} ${p.y}`
  }, '')
})

// Generate SVG Path string for the shaded gradient area under the line
const areaPath = computed(() => {
  const pts = points.value
  if (pts.length === 0) return ''
  const startX = pts[0].x
  const endX = pts[pts.length - 1].x
  const bottomY = height - padding.bottom
  
  let path = `M ${startX} ${bottomY}`
  pts.forEach(p => {
    path += ` L ${p.x} ${p.y}`
  })
  path += ` L ${endX} ${bottomY} Z`
  return path
})

// Y-axis gridlines tick values
const yTicks = computed(() => {
  const ticks = []
  const step = maxValue.value / 4
  for (let i = 0; i <= 4; i++) {
    ticks.push(Math.round(step * i))
  }
  return ticks
})

// Track mouse positioning to highlight closest point
function handleMouseMove(event) {
  if (points.value.length === 0) return
  
  const svg = event.currentTarget
  const rect = svg.getBoundingClientRect()
  
  // Calculate relative X coordinate inside SVG viewBox coordinates
  const clientX = event.clientX - rect.left
  const svgX = (clientX / rect.width) * width
  
  // Find closest data point index based on X distance
  let closestIndex = 0
  let minDistance = Infinity
  
  points.value.forEach((p, idx) => {
    const dist = Math.abs(p.x - svgX)
    if (dist < minDistance) {
      minDistance = dist
      closestIndex = idx
    }
  })
  
  hoveredIndex.value = closestIndex
  
  const activePt = points.value[closestIndex]
  // Align tooltip
  tooltipX.value = activePt.x
  tooltipY.value = activePt.y - 12
  tooltipContent.value = { label: activePt.label, value: activePt.value }
}

function handleMouseLeave() {
  hoveredIndex.value = null
}

onMounted(() => {
  loadTrends()
})
</script>

<template>
  <div class="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm space-y-4">
    <!-- Header with controls -->
    <div class="flex items-center justify-between gap-4 flex-wrap">
      <div>
        <h2 class="text-base font-semibold text-slate-800">Chat Activity Trends</h2>
        <p class="text-xs text-slate-400 mt-0.5">Interaction volume history over the selected timeframe</p>
      </div>

      <!-- Timeframe Toggle Switch -->
      <div class="flex items-center gap-1 bg-slate-100 p-1 rounded-xl">
        <button
          v-for="range in ['hourly', 'daily', 'weekly', 'monthly']"
          :key="range"
          @click="activeRange = range"
          :class="[
            'px-3 py-1.5 text-xxs font-bold uppercase rounded-lg transition-all duration-150',
            activeRange === range ? 'bg-white text-indigo-600 shadow-sm' : 'text-slate-500 hover:text-slate-800'
          ]"
        >
          {{ range }}
        </button>
      </div>
    </div>

    <!-- Error state banner -->
    <div v-if="fetchError" class="bg-red-50 border border-red-200 text-red-700 text-xs rounded-xl px-4 py-3 flex items-center justify-between">
      <span>{{ fetchError }}</span>
      <button @click="loadTrends" class="underline font-semibold hover:text-red-900">Retry</button>
    </div>

    <!-- Skeleton Loading state -->
    <div v-else-if="isLoading" class="h-60 w-full bg-slate-50 rounded-xl animate-pulse flex items-center justify-center text-slate-300 text-xs">
      Loading chat activity data…
    </div>

    <!-- Main Chart Container -->
    <div v-else class="relative w-full overflow-hidden select-none">
      <svg
        :viewBox="`0 0 ${width} ${height}`"
        class="w-full h-auto overflow-visible"
        @mousemove="handleMouseMove"
        @mouseleave="handleMouseLeave"
      >
        <!-- Definitions for custom gradient gradients and drop glows -->
        <defs>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#4f46e5" stop-opacity="0.22" />
            <stop offset="100%" stop-color="#4f46e5" stop-opacity="0.0" />
          </linearGradient>
          
          <filter id="lineGlow" x="-10%" y="-10%" width="120%" height="120%">
            <feDropShadow dx="0" dy="4" stdDeviation="4" flood-color="#6366f1" flood-opacity="0.25" />
          </filter>
        </defs>

        <!-- Horizontal grid lines & Y labels -->
        <g class="text-slate-400">
          <g v-for="(tick, idx) in yTicks" :key="idx">
            <!-- Line Y position -->
            <line
              :x1="padding.left"
              :y1="height - padding.bottom - (tick / maxValue) * chartHeight"
              :x2="width - padding.right"
              :y2="height - padding.bottom - (tick / maxValue) * chartHeight"
              stroke="#f1f5f9"
              stroke-width="1.2"
            />
            <!-- Y label value -->
            <text
              :x="padding.left - 12"
              :y="height - padding.bottom - (tick / maxValue) * chartHeight + 4"
              text-anchor="end"
              class="text-[10px] font-mono font-medium fill-slate-400"
            >
              {{ tick }}
            </text>
          </g>
        </g>

        <!-- X labels (Show every label or skip if crowded for hourly) -->
        <g class="text-slate-400">
          <g v-for="(pt, idx) in points" :key="idx">
            <!-- Skip alternate labels on hourly to prevent overlapping text -->
            <text
              v-if="activeRange !== 'hourly' || idx % 2 === 0"
              :x="pt.x"
              :y="height - padding.bottom + 18"
              text-anchor="middle"
              class="text-[9px] font-semibold fill-slate-400"
            >
              {{ pt.label }}
            </text>
          </g>
        </g>

        <!-- Shaded Area beneath the line path -->
        <path
          v-if="points.length > 0"
          :d="areaPath"
          fill="url(#areaGrad)"
        />

        <!-- Main Trend Line Path -->
        <path
          v-if="points.length > 0"
          :d="linePath"
          fill="none"
          stroke="#4f46e5"
          stroke-width="2.5"
          stroke-linecap="round"
          stroke-linejoin="round"
          filter="url(#lineGlow)"
        />

        <!-- Active Hover indicator line -->
        <line
          v-if="hoveredIndex !== null && points[hoveredIndex]"
          :x1="points[hoveredIndex].x"
          :y1="padding.top"
          :x2="points[hoveredIndex].x"
          :y2="height - padding.bottom"
          stroke="#cbd5e1"
          stroke-dasharray="4 4"
          stroke-width="1.2"
        />

        <!-- Data point dot circles on hover -->
        <g>
          <circle
            v-for="(pt, idx) in points"
            :key="idx"
            :cx="pt.x"
            :cy="pt.y"
            :r="hoveredIndex === idx ? 5 : 3"
            :fill="hoveredIndex === idx ? '#4f46e5' : '#ffffff'"
            :stroke="hoveredIndex === idx ? '#ffffff' : '#6366f1'"
            :stroke-width="hoveredIndex === idx ? 2 : 1.5"
            class="transition-all duration-100 pointer-events-none"
          />
        </g>
      </svg>

      <!-- Floating interactive HTML tooltip (absolutely positioned) -->
      <div
        v-if="hoveredIndex !== null"
        class="absolute pointer-events-none bg-slate-950/95 text-white text-xxs font-medium px-2.5 py-1.5 rounded-lg shadow-xl border border-slate-800 transition-all duration-75 flex flex-col gap-0.5 whitespace-nowrap"
        :style="{
          left: `${(tooltipX / width) * 100}%`,
          top: `${(tooltipY / height) * 100}%`,
          transform: 'translate(-50%, -100%)'
        }"
      >
        <span class="text-slate-400 font-semibold uppercase text-[9px] tracking-wide">{{ tooltipContent.label }}</span>
        <span class="font-mono text-xs font-bold text-indigo-400">{{ tooltipContent.value }} message(s)</span>
      </div>
    </div>
  </div>
</template>
