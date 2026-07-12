<script setup>
/**
 * DocumentManager.vue
 * Page for managing SOP documents used by the RAG chatbot.
 */
import DocumentUpload from '@/components/DocumentUpload.vue'
</script>

<template>
  <div class="space-y-6">
    <!-- Page heading -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold text-slate-900">Document Manager</h1>
        <p class="text-sm text-slate-500 mt-1">
          Upload and manage SOP documents used as the knowledge base for the ICICoS 2026 RAG chatbot.
        </p>
      </div>

      <!-- Info banner -->
      <div class="inline-flex self-start sm:self-auto shrink-0 items-center gap-2 bg-indigo-50 border border-indigo-100 text-indigo-700 text-xs font-medium px-4 py-2.5 rounded-xl">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 shrink-0">
          <path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-7-4a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM9 9a.75.75 0 0 0 0 1.5h.253a.25.25 0 0 1 .244.304l-.459 2.066A1.75 1.75 0 0 0 10.747 15H11a.75.75 0 0 0 0-1.5h-.253a.25.25 0 0 1-.244-.304l.459-2.066A1.75 1.75 0 0 0 9.253 9H9Z" clip-rule="evenodd" />
        </svg>
        PDF format only
      </div>
    </div>

    <!-- How it works callout -->
    <div class="bg-gradient-to-r from-slate-900 to-indigo-900 rounded-2xl p-5 text-white">
      <h2 class="text-sm font-semibold mb-3 flex items-center gap-2">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-indigo-300">
          <path d="M10.362 1.093a.75.75 0 0 0-.724 0L2.523 5.018 10 9.143l7.477-4.125-7.115-3.925ZM18 6.443l-7.25 3.998v8.777l6.862-3.783A.75.75 0 0 0 18 14.78V6.443Zm-8.75 12.775V10.44L2 6.443v8.339a.75.75 0 0 0 .388.656l6.862 3.783Z" />
        </svg>
        How the RAG Pipeline Works
      </h2>
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
        <div class="bg-white/10 rounded-xl p-3">
          <span class="text-indigo-300 font-bold text-lg">01</span>
          <p class="font-semibold mt-1">Upload PDF</p>
          <p class="text-slate-300 mt-0.5">Upload ICICoS SOP files into the system using the form below.</p>
        </div>
        <div class="bg-white/10 rounded-xl p-3">
          <span class="text-indigo-300 font-bold text-lg">02</span>
          <p class="font-semibold mt-1">Indexing & Embedding</p>
          <p class="text-slate-300 mt-0.5">The backend processes the document and converts it into vector embeddings.</p>
        </div>
        <div class="bg-white/10 rounded-xl p-3">
          <span class="text-indigo-300 font-bold text-lg">03</span>
          <p class="font-semibold mt-1">Chatbot Ready</p>
          <p class="text-slate-300 mt-0.5">Authors can now ask questions and the chatbot will answer based on the SOP.</p>
        </div>
      </div>
    </div>

    <!-- Document Upload Component -->
    <DocumentUpload />
  </div>
</template>
