<script setup>
// App.vue – Root component: wraps Sidebar + RouterView layout
import { ref } from 'vue'
import Sidebar from '@/components/Sidebar.vue'

const isSidebarOpen = ref(false)
</script>

<template>
  <div class="flex h-screen bg-gray-50 overflow-hidden">
    <!-- Sidebar Navigation Drawer -->
    <Sidebar :is-open="isSidebarOpen" @close="isSidebarOpen = false" />

    <!-- Backdrop overlay for mobile screen sizes when sidebar is open -->
    <Transition name="fade">
      <div 
        v-if="isSidebarOpen" 
        @click="isSidebarOpen = false"
        class="fixed inset-0 bg-black/40 z-40 md:hidden transition-opacity duration-200"
      ></div>
    </Transition>

    <!-- Main content area -->
    <div class="flex-1 flex flex-col overflow-hidden w-full">
      <!-- Top Header Bar -->
      <header class="bg-white border-b border-gray-200 px-4 md:px-6 py-3.5 md:py-4 flex items-center justify-between shadow-sm shrink-0">
        <div class="flex items-center gap-3">
          <!-- Mobile hamburger toggle button -->
          <button 
            @click="isSidebarOpen = true"
            class="md:hidden p-1.5 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 transition"
            title="Open menu"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor" class="w-6 h-6">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
            </svg>
          </button>

          <div>
            <h1 class="text-sm md:text-lg font-semibold text-slate-800 leading-tight">
              ICICoS 2026 – Admin Panel
            </h1>
            <p class="hidden sm:block text-[10px] md:text-xs text-slate-400 mt-0.5">
              International Conference on Informatics and Computing of Science
            </p>
          </div>
        </div>
        
        <div class="flex items-center gap-2.5 md:gap-3">
          <!-- Status indicator -->
          <span class="flex items-center gap-1.5 text-xs text-emerald-600 font-medium">
            <span class="w-1.5 md:w-2 h-1.5 md:h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            <span class="hidden xs:inline">System Online</span>
          </span>
          <!-- Admin avatar -->
          <div class="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-white text-xs font-bold shadow-sm">
            A
          </div>
        </div>
      </header>

      <!-- Scrollable Page Content -->
      <main class="flex-1 overflow-y-auto p-4 md:p-6 w-full">
        <RouterView v-slot="{ Component }">
          <Transition name="fade" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </main>
    </div>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>

