<script setup>
/**
 * WhatsAppReview.vue
 * Dashboard page for uploading, distilling, reviewing, and approving FAQ pairs
 * extracted from WhatsApp chat logs before they are indexed into ChromaDB.
 */
import { ref, onMounted, onUnmounted } from 'vue'
import {
  uploadWhatsAppChat,
  getPendingFAQs,
  updatePendingFAQ,
  deletePendingFAQ,
  approveSingleFAQ,
  approveAllFAQs,
  exportFaqs
} from '@/services/api'

// --- State ---
const faqs = ref([])
const isFetching = ref(false)
const fetchError = ref(null)
const isExporting = ref(false)

const isDragging = ref(false)
const isUploading = ref(false)
const uploadProgress = ref(0)
const uploadError = ref(null)
const successMsg = ref(null)

// Polling state for background process
const isPolling = ref(false)
let pollInterval = null

// Editing state
const editingId = ref(null)
const editForm = ref({ question: '', answer: '', category: 'lainnya' })
const isSaving = ref(false)

// Loading actions
const processingId = ref(null)
const isProcessingAll = ref(false)

const categories = [
  { value: 'pembayaran', label: 'Pembayaran' },
  { value: 'registrasi', label: 'Registrasi' },
  { value: 'submisi_paper', label: 'Submisi Paper' },
  { value: 'tanggal_penting', label: 'Tanggal Penting' },
  { value: 'akomodasi', label: 'Akomodasi' },
  { value: 'lainnya', label: 'Lainnya' }
]

function getCategoryLabel(val) {
  return categories.find(c => c.value === val)?.label ?? val
}

// --- Fetch Pending FAQs ---
async function fetchPending() {
  isFetching.value = true
  fetchError.value = null
  try {
    const { data } = await getPendingFAQs()
    faqs.value = Array.isArray(data) ? data : (data?.data ?? [])
  } catch (err) {
    console.error('[WhatsAppReview] Failed to fetch pending list:', err)
    fetchError.value = err.response?.data?.detail ?? err.message ?? 'Failed to load pending FAQ list.'
  } finally {
    isFetching.value = false
  }
}

// --- Polling logic ---
function startPolling() {
  if (isPolling.value) return
  isPolling.value = true
  pollInterval = setInterval(async () => {
    try {
      const { data } = await getPendingFAQs()
      const newFaqs = Array.isArray(data) ? data : (data?.data ?? [])
      
      // Update state
      faqs.value = newFaqs
    } catch (err) {
      console.error('[WhatsAppReview] Polling error:', err)
    }
  }, 8000) // Poll every 8 seconds
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
  isPolling.value = false
}

onMounted(() => {
  fetchPending()
})

onUnmounted(() => {
  stopPolling()
})

// --- Drag & Drop ---
function onDragEnter(e) {
  e.preventDefault()
  isDragging.value = true
}
function onDragLeave(e) {
  e.preventDefault()
  if (!e.currentTarget.contains(e.relatedTarget)) {
    isDragging.value = false
  }
}
function onDragOver(e) {
  e.preventDefault()
}
function onDrop(e) {
  e.preventDefault()
  isDragging.value = false
  handleUpload(Array.from(e.dataTransfer.files))
}
function onFileInputChange(e) {
  handleUpload(Array.from(e.target.files))
  e.target.value = ''
}

// --- Upload handler ---
async function handleUpload(filesList) {
  if (!filesList || filesList.length === 0) return
  
  // Saring file hanya yang berekstensi .txt atau .zip
  const validFiles = filesList.filter(file => {
    const ext = file.name.split('.').pop().toLowerCase()
    return ext === 'txt' || ext === 'zip'
  })

  if (validFiles.length === 0) {
    uploadError.value = 'Only .txt or .zip WhatsApp chat export files are accepted.'
    return
  }

  uploadError.value = null
  successMsg.value = null
  isUploading.value = true
  uploadProgress.value = 0

  let successCount = 0
  for (const file of validFiles) {
    // Progress animation per file
    const startProgress = Math.round((successCount / validFiles.length) * 100)
    const targetProgress = Math.round(((successCount + 0.85) / validFiles.length) * 100)
    uploadProgress.value = startProgress

    const fileProgTimer = setInterval(() => {
      if (uploadProgress.value < targetProgress) {
        uploadProgress.value += 2
      }
    }, 150)

    try {
      await uploadWhatsAppChat(file)
      clearInterval(fileProgTimer)
      successCount++
      uploadProgress.value = Math.round((successCount / validFiles.length) * 100)
    } catch (err) {
      clearInterval(fileProgTimer)
      uploadProgress.value = 0
      const detail = err.response?.data?.detail ?? err.message ?? 'Failed to upload chat file.'
      uploadError.value = `Failed to upload "${file.name}": ${detail}`
      break // Stop on first error
    }
  }

  if (successCount > 0) {
    successMsg.value = `Successfully uploaded ${successCount} WhatsApp chat file(s)! Distillation/extraction is running in the background.`
    
    // Enable polling so new FAQs appear automatically
    startPolling()
    
    // Auto-stop polling after 5 minutes
    setTimeout(() => {
      stopPolling()
    }, 300000)

    // Muat data pending segera
    await fetchPending()
  }

  isUploading.value = false
}

// --- Action Handlers ---
function startEdit(faq) {
  editingId.value = faq.id
  editForm.value = {
    question: faq.question,
    answer: faq.answer,
    category: faq.category || 'lainnya'
  }
}

function cancelEdit() {
  editingId.value = null
}

async function saveEdit(id) {
  isSaving.value = true
  try {
    await updatePendingFAQ(id, {
      question: editForm.value.question,
      answer: editForm.value.answer,
      category: editForm.value.category
    })
    
    // Update local state
    const index = faqs.value.findIndex(f => f.id === id)
    if (index !== -1) {
      faqs.value[index].question = editForm.value.question
      faqs.value[index].answer = editForm.value.answer
      faqs.value[index].category = editForm.value.category
    }
    editingId.value = null
  } catch (err) {
    console.error('[WhatsAppReview] Failed to save edit:', err)
    alert(err.response?.data?.detail ?? 'Failed to save FAQ changes.')
  } finally {
    isSaving.value = false
  }
}

async function approveFaq(id) {
  processingId.value = id
  try {
    await approveSingleFAQ(id)
    // Remove from pending list
    faqs.value = faqs.value.filter(f => f.id !== id)
  } catch (err) {
    console.error('[WhatsAppReview] Failed to approve FAQ:', err)
    alert(err.response?.data?.detail ?? 'Failed to approve FAQ.')
  } finally {
    processingId.value = null
  }
}

async function rejectFaq(id) {
  if (!confirm('Reject and permanently delete this pending FAQ from the system?')) return
  processingId.value = id
  try {
    await deletePendingFAQ(id)
    faqs.value = faqs.value.filter(f => f.id !== id)
  } catch (err) {
    console.error('[WhatsAppReview] Failed to reject FAQ:', err)
    alert(err.response?.data?.detail ?? 'Failed to reject FAQ.')
  } finally {
    processingId.value = null
  }
}

async function approveAll() {
  if (!confirm(`Approve all ${faqs.value.length} pending FAQ(s) in bulk and ingest into RAG?`)) return
  isProcessingAll.value = true
  try {
    const { data } = await approveAllFAQs()
    alert(data?.message ?? 'All pending FAQs have been approved successfully.')
    faqs.value = []
    stopPolling()
  } catch (err) {
    console.error('[WhatsAppReview] Failed to approve all FAQs:', err)
    alert(err.response?.data?.detail ?? 'Failed to approve all FAQs.')
  } finally {
    isProcessingAll.value = false
  }
}

async function handleExport(status) {
  isExporting.value = true
  try {
    const response = await exportFaqs(status)
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `faq_export_${status}.pdf`)
    document.body.appendChild(link)
    link.click()
    link.remove()
  } catch (err) {
    console.error('[WhatsAppReview] Failed to export FAQs:', err)
    alert('Failed to export FAQs to PDF.')
  } finally {
    isExporting.value = false
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- Page Heading -->
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold text-slate-900">WhatsApp Chat Review</h1>
        <p class="text-sm text-slate-500 mt-1">
          Review and curate Q&amp;A pairs extracted from WhatsApp group/private chat logs before indexing them into the RAG knowledge base.
        </p>
      </div>

      <!-- Live badge/Refresh & Export -->
      <div class="flex items-center gap-3 shrink-0">
        
        <!-- Export PDF Dropdown -->
        <div class="relative group">
          <button
            :disabled="isExporting"
            class="text-xs text-slate-500 hover:text-slate-700 bg-white border border-gray-200 px-3 py-1.5 rounded-xl transition flex items-center gap-1 disabled:opacity-50"
          >
            <svg v-if="isExporting" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 animate-spin"><path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clip-rule="evenodd" /></svg>
            <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5"><path fill-rule="evenodd" d="M10 3a.75.75 0 0 1 .75.75v10.638l3.96-4.158a.75.75 0 1 1 1.08 1.04l-5.25 5.5a.75.75 0 0 1-1.08 0l-5.25-5.5a.75.75 0 1 1 1.08-1.04l3.96 4.158V3.75A.75.75 0 0 1 10 3Z" clip-rule="evenodd" /></svg>
            Export PDF
          </button>
          
          <div class="absolute right-0 mt-1 w-36 bg-white border border-gray-100 rounded-xl shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-10 py-1">
            <button @click="handleExport('all')" class="w-full text-left px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50 hover:text-indigo-600">Export All</button>
            <button @click="handleExport('pending')" class="w-full text-left px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50 hover:text-indigo-600">Export Pending</button>
            <button @click="handleExport('approved')" class="w-full text-left px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50 hover:text-indigo-600">Export Accepted</button>
          </div>
        </div>

        <button
          v-if="isPolling"
          @click="stopPolling"
          class="flex items-center gap-1.5 text-xs text-amber-600 font-medium bg-amber-50 border border-amber-200 px-3 py-1.5 rounded-xl hover:bg-amber-100/60 transition"
        >
          <span class="w-1.5 h-1.5 rounded-full bg-amber-500 animate-ping"></span>
          Auto-Refreshing… Stop
        </button>
        <button
          v-else
          @click="startPolling"
          class="text-xs text-slate-500 hover:text-indigo-600 bg-white border border-gray-200 px-3 py-1.5 rounded-xl transition"
        >
          Enable Live Sync
        </button>
      </div>
    </div>

    <!-- Banner Info / Cara Kerja -->
    <div class="bg-gradient-to-r from-slate-900 to-indigo-900 rounded-2xl p-5 text-white shadow-md">
      <h2 class="text-sm font-semibold mb-3 flex items-center gap-2">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-indigo-300">
          <path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-7-4a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM9 9a.75.75 0 0 0 0 1.5h.253a.25.25 0 0 1 .244.304l-.459 2.066A1.75 1.75 0 0 0 10.747 15H11a.75.75 0 0 0 0-1.5h-.253a.25.25 0 0 1-.244-.304l.459-2.066A1.75 1.75 0 0 0 9.253 9H9Z" clip-rule="evenodd" />
        </svg>
        Workflow Guide
      </h2>
      <div class="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs text-slate-300">
        <div class="bg-white/10 rounded-xl p-3">
          <span class="text-indigo-300 font-bold text-base">01. Upload</span>
          <p class="font-semibold text-white mt-1">Upload .txt / .zip</p>
          <p class="mt-0.5 leading-relaxed">Export chat history as a plain text file (.txt) or a zip archive (.zip).</p>
        </div>
        <div class="bg-white/10 rounded-xl p-3">
          <span class="text-indigo-300 font-bold text-base">02. Distill</span>
          <p class="font-semibold text-white mt-1">LLM Extraction</p>
          <p class="mt-0.5 leading-relaxed">Gemini extracts meaningful Q&amp;A pairs from the chat in the background and translates them to English.</p>
        </div>
        <div class="bg-white/10 rounded-xl p-3">
          <span class="text-indigo-300 font-bold text-base">03. Review</span>
          <p class="font-semibold text-white mt-1">Edit &amp; Categorize</p>
          <p class="mt-0.5 leading-relaxed">Review Q&amp;A cards below. Edit text, fix wording, or delete invalid entries.</p>
        </div>
        <div class="bg-white/10 rounded-xl p-3">
          <span class="text-indigo-300 font-bold text-base">04. Approve</span>
          <p class="font-semibold text-white mt-1">Commit to RAG</p>
          <p class="mt-0.5 leading-relaxed">Press Approve to create a vector embedding and store it in ChromaDB.</p>
        </div>
      </div>
    </div>

    <!-- ── Toasts / Alerts ── -->
    <Transition name="slide-down">
      <div v-if="successMsg" class="flex items-start gap-3 bg-emerald-50 border border-emerald-200 text-emerald-700 text-sm rounded-xl px-4 py-3 shadow-sm">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5 shrink-0 mt-0.5">
          <path fill-rule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm3.857-9.809a.75.75 0 0 0-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 1 0-1.06 1.061l2.5 2.5a.75.75 0 0 0 1.137-.089l4-5.5Z" clip-rule="evenodd" />
        </svg>
        <div class="flex-1">
          <p class="font-semibold">Sukses</p>
          <p class="text-xs text-emerald-600 mt-0.5 leading-relaxed">{{ successMsg }}</p>
        </div>
        <button @click="successMsg = null" class="text-emerald-400 hover:text-emerald-600 transition">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
            <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
          </svg>
        </button>
      </div>
    </Transition>

    <Transition name="slide-down">
      <div v-if="uploadError" class="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3 shadow-sm">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5 shrink-0 mt-0.5">
          <path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" />
        </svg>
        <div class="flex-1">
          <p class="font-semibold">Ekstraksi gagal</p>
          <p class="text-xs text-red-600 mt-0.5">{{ uploadError }}</p>
        </div>
        <button @click="uploadError = null" class="text-red-400 hover:text-red-600 transition">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
            <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
          </svg>
        </button>
      </div>
    </Transition>

    <!-- ── Dropzone File Upload ── -->
    <div
      id="whatsapp-dropzone"
      role="button"
      tabindex="0"
      :class="[
        'relative border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-all duration-200 select-none shadow-sm',
        isUploading
          ? 'border-indigo-400 bg-indigo-50/40 cursor-wait'
          : isDragging
          ? 'border-indigo-500 bg-indigo-50 shadow-md shadow-indigo-100'
          : 'border-slate-300 bg-white hover:border-indigo-400 hover:bg-slate-50/60',
      ]"
      @dragenter="onDragEnter"
      @dragleave="onDragLeave"
      @dragover="onDragOver"
      @drop="!isUploading && onDrop($event)"
      @click="!isUploading && $refs.fileInput.click()"
      @keydown.enter="!isUploading && $refs.fileInput.click()"
    >
      <input
        ref="fileInput"
        type="file"
        accept=".txt,.zip"
        multiple
        class="hidden"
        @change="onFileInputChange"
      />

      <div
        :class="[
          'flex flex-col items-center gap-3 transition-transform duration-200',
          isDragging ? 'scale-105' : 'scale-100',
        ]"
      >
        <div
          :class="[
            'w-12 h-12 rounded-xl flex items-center justify-center transition-colors duration-200',
            isDragging ? 'bg-indigo-100' : 'bg-slate-100',
          ]"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="1.5"
            :stroke="isDragging ? '#6366f1' : '#94a3b8'"
            class="w-6 h-6 transition-colors duration-200"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 18V6a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 6v3.75m-9-3.75h.008v.008H12V6Z" />
          </svg>
        </div>

        <div>
          <p
            :class="[
              'text-sm font-semibold transition-colors duration-200',
              isDragging ? 'text-indigo-600' : 'text-slate-700',
            ]"
          >
            <template v-if="isUploading">Uploading chat log…</template>
            <template v-else-if="isDragging">Drop your chat file here…</template>
            <template v-else>Drag &amp; drop WhatsApp chat file (.txt / .zip) or click to select</template>
          </p>
          <p class="text-xs text-slate-400 mt-1">Supports .txt (text only) or .zip (text + media) · Multiple files allowed</p>
        </div>
      </div>

      <!-- Upload Progress -->
      <div v-if="isUploading" class="mt-4 max-w-md mx-auto">
        <div class="flex items-center justify-between text-xs text-slate-500 mb-1">
          <span>Sending chat file to server…</span>
          <span>{{ Math.round(uploadProgress) }}%</span>
        </div>
        <div class="h-1.5 bg-slate-100 rounded-full overflow-hidden">
          <div
            class="h-full bg-indigo-500 rounded-full transition-all duration-300"
            :style="{ width: uploadProgress + '%' }"
          ></div>
        </div>
      </div>
    </div>

    <!-- ── Staging Review List ── -->
    <div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
      <!-- Header List -->
      <div class="px-6 py-4 border-b border-gray-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-50/40">
        <div>
          <h3 class="text-sm font-bold text-slate-800">Pending FAQ Review List</h3>
          <p class="text-xs text-slate-400 mt-0.5">
            <template v-if="isFetching">Loading FAQs…</template>
            <template v-else>{{ faqs.length }} Q&amp;A pair(s) awaiting admin verification</template>
          </p>
        </div>

        <div class="flex items-center gap-2">
          <!-- Refresh -->
          <button
            @click="fetchPending"
            :disabled="isFetching"
            class="p-2 rounded-lg border border-gray-200 text-slate-500 hover:text-indigo-600 hover:bg-slate-50 disabled:opacity-40 transition"
            title="Refresh daftar pending"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"
              :class="['w-4 h-4', isFetching && 'animate-spin']">
              <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clip-rule="evenodd" />
            </svg>
          </button>

          <!-- Approve All -->
          <button
            v-if="faqs.length > 0"
            @click="approveAll"
            :disabled="isProcessingAll"
            class="inline-flex items-center gap-1.5 text-xs bg-indigo-600 hover:bg-indigo-700 text-white font-semibold px-4 py-2 rounded-xl disabled:opacity-50 shadow-sm shadow-indigo-100 transition"
          >
            <svg v-if="isProcessingAll" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 animate-spin">
              <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clip-rule="evenodd" />
            </svg>
            <span v-else>Approve All ({{ faqs.length }})</span>
          </button>
        </div>
      </div>

      <!-- Fetch Error -->
      <div v-if="fetchError" class="m-6 flex items-center gap-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded-xl px-4 py-3 shadow-sm">
        <span class="flex-1">{{ fetchError }}</span>
        <button @click="fetchPending" class="font-bold underline hover:no-underline">Retry</button>
      </div>

      <!-- Skeleton Loader -->
      <div v-if="isFetching" class="p-6 space-y-4">
        <div v-for="i in 2" :key="i" class="border border-slate-100 rounded-xl p-4 space-y-3 animate-pulse">
          <div class="h-4 bg-slate-100 w-1/3 rounded"></div>
          <div class="h-3 bg-slate-100 w-2/3 rounded"></div>
          <div class="h-3 bg-slate-100 w-1/2 rounded"></div>
        </div>
      </div>

      <!-- FAQ Card List -->
      <div v-else-if="faqs.length > 0" class="divide-y divide-gray-100">
        <div
          v-for="faq in faqs"
          :key="faq.id"
          class="p-6 hover:bg-slate-50/40 transition-colors"
        >
          <!-- View Mode -->
          <div v-if="editingId !== faq.id" class="space-y-3">
            <div class="flex items-start justify-between gap-4">
              <!-- Category badge + source file -->
              <div class="flex flex-wrap items-center gap-2">
                <span class="inline-flex items-center text-xs font-semibold px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-100">
                  {{ getCategoryLabel(faq.category) }}
                </span>
                <span class="text-xxs text-slate-400 font-mono">
                  Source: {{ faq.source_file }}
                </span>
              </div>

              <!-- Item Actions -->
              <div class="flex items-center gap-1">
                <button
                  @click="startEdit(faq)"
                  :disabled="processingId === faq.id"
                  class="p-1.5 rounded-lg text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 transition"
                  title="Edit FAQ"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
                    <path d="m5.433 13.917 1.262-3.155A4 4 0 0 1 7.58 9.42l6.92-6.918a2.121 2.121 0 0 1 3 3l-6.92 6.918c-.383.383-.84.685-1.343.886l-3.154 1.262a.5.5 0 0 1-.65-.65Z" />
                    <path d="M3.5 5.75c0-.69.56-1.25 1.25-1.25H10A.75.75 0 0 0 10 3H4.75A2.75 2.75 0 0 0 2 5.75v9.5A2.75 2.75 0 0 0 4.75 18h9.5A2.75 2.75 0 0 0 17 15.25V10a.75.75 0 0 0-1.5 0v5.25c0 .69-.56 1.25-1.25 1.25h-9.5c-.69 0-1.25-.56-1.25-1.25v-9.5Z" />
                  </svg>
                </button>
                <button
                  @click="approveFaq(faq.id)"
                  :disabled="processingId === faq.id"
                  class="p-1.5 rounded-lg text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 transition"
                  title="Approve &amp; Ingest into RAG"
                >
                  <svg v-if="processingId === faq.id" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 animate-spin text-slate-400">
                    <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clip-rule="evenodd" />
                  </svg>
                  <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
                    <path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clip-rule="evenodd" />
                  </svg>
                </button>
                <button
                  @click="rejectFaq(faq.id)"
                  :disabled="processingId === faq.id"
                  class="p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition"
                  title="Reject &amp; Delete"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
                    <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clip-rule="evenodd" />
                  </svg>
                </button>
              </div>
            </div>

            <!-- Q&A Content -->
            <div class="space-y-2">
              <h4 class="text-sm font-semibold text-slate-800 flex items-start gap-2">
                <span class="text-indigo-500 font-bold shrink-0">Q:</span>
                <span>{{ faq.question }}</span>
              </h4>
              <p class="text-xs text-slate-600 bg-slate-50 border border-slate-100 rounded-xl p-3 leading-relaxed flex items-start gap-2">
                <span class="text-emerald-500 font-bold shrink-0">A:</span>
                <span class="whitespace-pre-line">{{ faq.answer }}</span>
              </p>
            </div>
          </div>

          <!-- Edit Mode -->
          <div v-else class="space-y-4 border border-indigo-100 bg-indigo-50/20 rounded-2xl p-4">
            <h4 class="text-xs font-bold text-indigo-700 uppercase tracking-wide">Edit FAQ Pair</h4>
            
            <!-- Category -->
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-2 items-center">
              <label class="text-xs font-semibold text-slate-600">Category:</label>
              <select
                v-model="editForm.category"
                class="col-span-2 text-xs bg-white border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500 text-slate-700"
              >
                <option v-for="cat in categories" :key="cat.value" :value="cat.value">
                  {{ cat.label }}
                </option>
              </select>
            </div>

            <!-- Question -->
            <div class="space-y-1">
              <label class="text-xs font-semibold text-slate-600">Question:</label>
              <input
                v-model="editForm.question"
                type="text"
                class="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-500 text-slate-700 font-medium"
              />
            </div>

            <!-- Answer -->
            <div class="space-y-1">
              <label class="text-xs font-semibold text-slate-600">Answer:</label>
              <textarea
                v-model="editForm.answer"
                rows="4"
                class="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-500 text-slate-600 leading-relaxed"
              ></textarea>
            </div>

            <!-- Edit Actions -->
            <div class="flex items-center justify-end gap-2">
              <button
                @click="cancelEdit"
                :disabled="isSaving"
                class="text-xs font-semibold text-slate-500 hover:text-slate-700 px-3 py-1.5 rounded-lg transition"
              >
                Cancel
              </button>
              <button
                @click="saveEdit(faq.id)"
                :disabled="isSaving"
                class="inline-flex items-center gap-1 text-xs bg-indigo-600 hover:bg-indigo-700 text-white font-semibold px-4 py-1.5 rounded-lg disabled:opacity-50 transition"
              >
                <svg v-if="isSaving" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 animate-spin">
                  <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clip-rule="evenodd" />
                </svg>
                <span>Save</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else-if="!isFetching" class="px-6 py-16 text-center text-slate-400">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-12 h-12 mx-auto mb-3 text-slate-300">
          <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.084.29.125.597.125.905v3a.75.75 0 0 1-1.5 0v-3a.75.75 0 0 0-.022-.178m-17.156-.178A.75.75 0 1 1 2.25 9.75M2.25 9.75a9.6 9.6 0 0 1 5.032-6.674m0 0a8.959 8.959 0 0 1 9.436 0m-9.436 0A9.18 9.18 0 0 0 3.361 7.5m13.208-4.424A9.18 9.18 0 0 1 20.639 7.5m0 0a8.96 8.96 0 0 1-2.28 5.766M2.25 9.75A9.6 9.6 0 0 0 4.5 15.5m0 0a8.96 8.96 0 0 0 8.01 4.5 8.96 8.96 0 0 0 8.01-4.5m-16.02 0a8.96 8.96 0 0 1 2.28-5.766" />
        </svg>
        <p class="text-sm font-medium">No pending FAQs to review.</p>
        <p class="text-xs text-slate-400 mt-1">Upload a WhatsApp chat file (.txt or .zip) above to start extracting new knowledge.</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.25s ease;
}
.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.text-xxs {
  font-size: 0.65rem;
}
</style>
