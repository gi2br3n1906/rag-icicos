<script setup>
/**
 * DocumentUpload.vue
 * Interactive drag-and-drop file uploader for SOP documents.
 * Fetches active documents from GET /api/documents and uploads via POST /api/documents/upload.
 * Also provides a "Reset Knowledge Base" button that calls POST /api/knowledge/reset.
 */
import { ref, onMounted } from 'vue'
import { getDocuments, uploadDocument, deleteDocument, resetKnowledgeBase } from '@/services/api'

// ─── Document list state ──────────────────────────────────────────────────────
const documents = ref([])
const isFetchingDocs = ref(false)
const fetchDocsError = ref(null)

async function fetchDocuments() {
  isFetchingDocs.value = true
  fetchDocsError.value = null
  try {
    const { data } = await getDocuments()
    // Accept plain array or { data: [...] } envelope
    documents.value = Array.isArray(data) ? data : (data?.data ?? [])
  } catch (err) {
    console.error('[DocumentUpload] Failed to fetch document list:', err)
    fetchDocsError.value =
      err.response?.data?.detail ??
      err.message ??
      'Failed to load document list.'
  } finally {
    isFetchingDocs.value = false
  }
}

onMounted(fetchDocuments)

// ─── Upload state ─────────────────────────────────────────────────────────────
const isDragging = ref(false)
const isUploading = ref(false)
const uploadProgress = ref(0)
const uploadError = ref(null)
const uploadSuccessMsg = ref(null)

// Auto-dismiss success toast after 4 s
let successTimer = null
function showSuccess(msg) {
  uploadSuccessMsg.value = msg
  clearTimeout(successTimer)
  successTimer = setTimeout(() => { uploadSuccessMsg.value = null }, 4000)
}

// ─── Drag & Drop handlers ─────────────────────────────────────────────────────
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
  handleFiles(Array.from(e.dataTransfer.files))
}

function onFileInputChange(e) {
  handleFiles(Array.from(e.target.files))
  e.target.value = '' // reset so same file can be re-selected
}

// ─── Core upload handler ──────────────────────────────────────────────────────
async function handleFiles(files) {
  const pdfFiles = files.filter((f) => f.type === 'application/pdf')

  if (pdfFiles.length === 0) {
    uploadError.value = 'Only PDF files are allowed.'
    return
  }

  uploadError.value = null
  uploadSuccessMsg.value = null
  isUploading.value = true
  uploadProgress.value = 0

  // Upload files sequentially to avoid overwhelming the server
  let successCount = 0
  for (const file of pdfFiles) {
    try {
      // Simulate incremental progress while real request is in-flight
      const progressInterval = startProgressSimulation()

      await uploadDocument(file)

      clearInterval(progressInterval)
      uploadProgress.value = Math.round(((successCount + 1) / pdfFiles.length) * 100)
      successCount++
    } catch (err) {
      clearProgressSimulation()
      const detail =
        err.response?.data?.detail ??
        err.message ??
        'An error occurred during upload.'
      uploadError.value = `Failed to upload "${file.name}": ${detail}`
      break // stop processing remaining files on first error
    }
  }

  isUploading.value = false
  uploadProgress.value = 0

  if (successCount > 0) {
    showSuccess(`${successCount} file(s) uploaded successfully. Document list updated.`)
    // Hot-reload document list after successful upload
    await fetchDocuments()
  }
}

// ─── Progress simulation (indeterminate feel while awaiting response) ──────────
let _progressInterval = null

function startProgressSimulation() {
  uploadProgress.value = 5
  _progressInterval = setInterval(() => {
    // Advance slowly up to 85% – final jump happens after response
    if (uploadProgress.value < 85) {
      uploadProgress.value += Math.random() * 8
    }
  }, 250)
  return _progressInterval
}

function clearProgressSimulation() {
  clearInterval(_progressInterval)
  _progressInterval = null
}

// ─── Delete handler ───────────────────────────────────────────────────────────
const deletingId = ref(null)

async function removeDocument(id) {
  if (!confirm('Remove this document from the RAG system?')) return

  deletingId.value = id
  try {
    await deleteDocument(id)
    // Optimistically remove from list immediately
    documents.value = documents.value.filter((d) => d.id !== id)
  } catch (err) {
    console.error('[DocumentUpload] Failed to delete document:', err)
    fetchDocsError.value =
      err.response?.data?.detail ?? err.message ?? 'Failed to delete document.'
    // Re-fetch to restore consistent state
    await fetchDocuments()
  } finally {
    deletingId.value = null
  }
}

// ─── Knowledge Base Reset ─────────────────────────────────────────────────────
const isResetting = ref(false)
const resetError = ref(null)
const resetSuccessMsg = ref(null)

async function handleReset() {
  if (
    !confirm(
      '⚠️ DANGER: This will permanently wipe the entire knowledge base:\n\n' +
      '• All ChromaDB embeddings will be deleted.\n' +
      '• All document records will be removed from the database.\n' +
      '• All WhatsApp FAQ records will be removed.\n\n' +
      'This action is IRREVERSIBLE. Proceed?'
    )
  ) return

  isResetting.value = true
  resetError.value = null
  resetSuccessMsg.value = null

  try {
    await resetKnowledgeBase()
    resetSuccessMsg.value = 'Knowledge base successfully reset. All embeddings and records have been wiped. You may now re-ingest documents.'
    documents.value = []
  } catch (err) {
    resetError.value =
      err.response?.data?.detail ?? err.message ?? 'Failed to reset knowledge base.'
  } finally {
    isResetting.value = false
  }
}

// ─── Field normalizer (camelCase ↔ snake_case) ─────────────────────────────────
function normDoc(doc, camel, snake, fallback = '–') {
  return doc[camel] ?? doc[snake] ?? fallback
}
</script>

<template>
  <div class="space-y-6">
    <!-- ── Toast: success ─────────────────────────────────────────────────── -->
    <Transition name="slide-down">
      <div
        v-if="uploadSuccessMsg"
        class="flex items-center gap-3 bg-emerald-50 border border-emerald-200 text-emerald-700 text-sm rounded-xl px-4 py-3"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5 shrink-0">
          <path fill-rule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm3.857-9.809a.75.75 0 0 0-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 1 0-1.06 1.061l2.5 2.5a.75.75 0 0 0 1.137-.089l4-5.5Z" clip-rule="evenodd" />
        </svg>
        <span>{{ uploadSuccessMsg }}</span>
      </div>
    </Transition>

    <!-- ── Toast: upload error ────────────────────────────────────────────── -->
    <Transition name="slide-down">
      <div
        v-if="uploadError"
        class="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5 shrink-0 mt-0.5">
          <path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" />
        </svg>
        <div class="flex-1">
          <p class="font-semibold">Upload failed</p>
          <p class="text-xs text-red-600 mt-0.5">{{ uploadError }}</p>
        </div>
        <button @click="uploadError = null" class="text-red-400 hover:text-red-600 transition">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
            <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
          </svg>
        </button>
      </div>
    </Transition>

    <!-- ── Dropzone ───────────────────────────────────────────────────────── -->
    <div
      id="document-dropzone"
      role="button"
      tabindex="0"
      :class="[
        'relative border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all duration-200 select-none',
        isUploading
          ? 'border-indigo-400 bg-indigo-50/40 cursor-wait'
          : isDragging
          ? 'border-indigo-500 bg-indigo-50 shadow-lg shadow-indigo-100'
          : 'border-slate-300 bg-white hover:border-indigo-400 hover:bg-slate-50/60',
      ]"
      @dragenter="onDragEnter"
      @dragleave="onDragLeave"
      @dragover="onDragOver"
      @drop="!isUploading && onDrop($event)"
      @click="!isUploading && $refs.fileInput.click()"
      @keydown.enter="!isUploading && $refs.fileInput.click()"
    >
      <!-- Hidden file input -->
      <input
        ref="fileInput"
        type="file"
        accept="application/pdf"
        multiple
        class="hidden"
        @change="onFileInputChange"
      />

      <!-- Icon + label -->
      <div
        :class="[
          'flex flex-col items-center gap-3 transition-transform duration-200',
          isDragging ? 'scale-105' : 'scale-100',
        ]"
      >
        <div
          :class="[
            'w-14 h-14 rounded-2xl flex items-center justify-center transition-colors duration-200',
            isDragging ? 'bg-indigo-100' : 'bg-slate-100',
          ]"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="1.5"
            :stroke="isDragging ? '#6366f1' : '#94a3b8'"
            class="w-7 h-7 transition-colors duration-200"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
          </svg>
        </div>

        <div>
          <p
            :class="[
              'text-sm font-semibold transition-colors duration-200',
              isDragging ? 'text-indigo-600' : 'text-slate-700',
            ]"
          >
            <template v-if="isUploading">Uploading, please wait…</template>
            <template v-else-if="isDragging">Drop files here…</template>
            <template v-else>Drag &amp; drop PDF files or click to select</template>
          </p>
          <p class="text-xs text-slate-400 mt-1">PDF files only • Max 20 MB per file</p>
        </div>
      </div>

      <!-- Upload progress bar -->
      <div v-if="isUploading" class="mt-5">
        <div class="flex items-center justify-between text-xs text-slate-500 mb-1">
          <span>Uploading to server…</span>
          <span>{{ Math.round(uploadProgress) }}%</span>
        </div>
        <div class="h-1.5 bg-slate-100 rounded-full overflow-hidden">
          <div
            class="h-full bg-indigo-500 rounded-full transition-all duration-300"
            :style="{ width: Math.min(uploadProgress, 100) + '%' }"
          ></div>
        </div>
      </div>
    </div>

    <!-- ── Active Documents List ───────────────────────────────────────────── -->
    <div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
      <!-- List header -->
      <div class="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
        <div>
          <h3 class="text-sm font-semibold text-slate-800">Active SOP Documents</h3>
          <p class="text-xs text-slate-400 mt-0.5">
            <template v-if="isFetchingDocs">Loading list…</template>
            <template v-else>{{ documents.length }} document(s) stored in the RAG system</template>
          </p>
        </div>
        <div class="flex items-center gap-2">
          <!-- Manual refresh -->
          <button
            id="docs-refresh"
            @click="fetchDocuments"
            :disabled="isFetchingDocs"
            class="p-1.5 rounded-lg text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 disabled:opacity-40 transition"
            title="Refresh document list"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"
              :class="['w-4 h-4', isFetchingDocs && 'animate-spin']">
              <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clip-rule="evenodd" />
            </svg>
          </button>

          <span class="inline-flex items-center gap-1.5 text-xs text-emerald-600 font-medium bg-emerald-50 px-2.5 py-1 rounded-full">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
            Active
          </span>
        </div>
      </div>

      <!-- Fetch error -->
      <div
        v-if="fetchDocsError"
        class="mx-6 mt-4 mb-2 flex items-center gap-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded-xl px-4 py-2.5"
      >
        <span class="flex-1">{{ fetchDocsError }}</span>
        <button @click="fetchDocuments" class="font-semibold underline hover:no-underline">Retry</button>
      </div>

      <!-- Skeleton loader -->
      <div v-if="isFetchingDocs" class="p-4 space-y-2">
        <div
          v-for="i in 3"
          :key="i"
          class="h-12 bg-slate-100 rounded-lg animate-pulse"
        ></div>
      </div>

      <!-- Document list -->
      <ul v-else class="divide-y divide-gray-50">
        <li
          v-for="doc in documents"
          :key="doc.id"
          class="flex items-center gap-4 px-6 py-3.5 hover:bg-slate-50/60 transition-colors group"
        >
          <!-- PDF icon -->
          <div class="shrink-0 w-9 h-9 rounded-xl bg-red-50 flex items-center justify-center">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#ef4444" class="w-5 h-5">
              <path d="M5.625 1.5c-1.036 0-1.875.84-1.875 1.875v17.25c0 1.035.84 1.875 1.875 1.875h12.75c1.035 0 1.875-.84 1.875-1.875V12.75A3.75 3.75 0 0 0 16.5 9h-1.875a1.875 1.875 0 0 1-1.875-1.875V5.25A3.75 3.75 0 0 0 9 1.5H5.625Z" />
              <path d="M12.971 1.816A5.23 5.23 0 0 1 14.25 5.25v1.875c0 .207.168.375.375.375H16.5a5.23 5.23 0 0 1 3.434 1.279 9.768 9.768 0 0 0-6.963-6.963Z" />
            </svg>
          </div>

          <!-- Doc info -->
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-slate-700 truncate">
              {{ normDoc(doc, 'name', 'filename') }}
            </p>
            <p class="text-xs text-slate-400 mt-0.5">
              {{ normDoc(doc, 'size', 'file_size') }}
              <template v-if="normDoc(doc, 'pages', 'page_count', null)">
                · {{ normDoc(doc, 'pages', 'page_count') }} pages
              </template>
              · Uploaded {{ normDoc(doc, 'uploadedAt', 'uploaded_at') }}
            </p>
          </div>

          <!-- Status badge -->
          <span class="shrink-0 inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
              <path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clip-rule="evenodd" />
            </svg>
            Ingested
          </span>

          <!-- Delete button (hover-reveal) -->
          <button
            :id="`delete-doc-${doc.id}`"
            @click="removeDocument(doc.id)"
            :disabled="deletingId === doc.id"
            class="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 disabled:cursor-wait"
            title="Remove document"
          >
            <!-- Spinner while deleting this item -->
            <svg v-if="deletingId === doc.id" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 animate-spin text-slate-400">
              <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clip-rule="evenodd" />
            </svg>
            <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
              <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clip-rule="evenodd" />
            </svg>
          </button>
        </li>

        <!-- Empty state -->
        <li v-if="documents.length === 0 && !isFetchingDocs" class="px-6 py-12 text-center text-slate-400">
          <svg xmlns="http://www.w3.org/2000/svg" class="w-10 h-10 mx-auto mb-3 text-slate-300" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
          </svg>
          <p class="text-sm font-medium">No documents uploaded yet.</p>
          <p class="text-xs mt-1">Upload SOP PDF files above to start building the knowledge base.</p>
        </li>
      </ul>
    </div>

    <!-- ── Danger Zone: Reset Knowledge Base ────────────────────────────────── -->
    <div class="bg-white rounded-2xl border border-red-200 shadow-sm overflow-hidden">
      <div class="px-6 py-4 border-b border-red-100 bg-red-50/40">
        <h3 class="text-sm font-semibold text-red-700">⚠️ Danger Zone</h3>
        <p class="text-xs text-red-500 mt-0.5">
          These actions are irreversible. Use with caution.
        </p>
      </div>

      <div class="px-6 py-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <p class="text-sm font-semibold text-slate-700">Reset Knowledge Base</p>
          <p class="text-xs text-slate-400 mt-0.5">
            Permanently wipes all ChromaDB embeddings, document records, and WhatsApp FAQ records. 
            Use this before re-ingesting documents in English.
          </p>
        </div>
        <button
          id="reset-knowledge-base"
          @click="handleReset"
          :disabled="isResetting"
          class="shrink-0 inline-flex items-center gap-2 text-xs bg-red-600 hover:bg-red-700 text-white font-semibold px-4 py-2.5 rounded-xl disabled:opacity-50 shadow-sm transition"
        >
          <svg v-if="isResetting" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 animate-spin">
            <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clip-rule="evenodd" />
          </svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
            <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clip-rule="evenodd" />
          </svg>
          <span>{{ isResetting ? 'Resetting…' : 'Reset Knowledge Base' }}</span>
        </button>
      </div>

      <!-- Reset success toast -->
      <Transition name="slide-down">
        <div v-if="resetSuccessMsg" class="mx-6 mb-4 flex items-center gap-3 bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs rounded-xl px-4 py-3">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 shrink-0">
            <path fill-rule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm3.857-9.809a.75.75 0 0 0-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 1 0-1.06 1.061l2.5 2.5a.75.75 0 0 0 1.137-.089l4-5.5Z" clip-rule="evenodd" />
          </svg>
          <span>{{ resetSuccessMsg }}</span>
        </div>
      </Transition>

      <!-- Reset error toast -->
      <Transition name="slide-down">
        <div v-if="resetError" class="mx-6 mb-4 flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded-xl px-4 py-3">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 shrink-0 mt-0.5">
            <path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" />
          </svg>
          <div class="flex-1">
            <p class="font-semibold">Reset failed</p>
            <p class="mt-0.5">{{ resetError }}</p>
          </div>
          <button @click="resetError = null" class="text-red-400 hover:text-red-600">✕</button>
        </div>
      </Transition>
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
</style>
