<script setup>
/**
 * AccountSettings.vue
 * Page for changing passwords (both Admin and Humas) and managing user accounts (Admin only).
 */
import { ref, computed, onMounted } from 'vue'
import { changePassword, getUsers, createUser, deleteUser } from '@/services/api'

// Role details from session
const currentUserEmail = computed(() => localStorage.getItem('user_email') || '')
const currentUserRole = computed(() => localStorage.getItem('user_role') || 'humas')
const isAdmin = computed(() => currentUserRole.value === 'admin')

const activeTab = ref('profile') // 'profile' | 'users'

// --- Change Password State ---
const currentPassword = ref('')
const newPassword = ref('')
const confirmNewPassword = ref('')
const isChangingPwd = ref(false)
const changePwdError = ref('')
const changePwdSuccess = ref('')

async function handlePasswordChange() {
  if (!currentPassword.value || !newPassword.value || !confirmNewPassword.value) {
    changePwdError.value = 'All fields are required.'
    return
  }

  if (newPassword.value !== confirmNewPassword.value) {
    changePwdError.value = 'New passwords do not match.'
    return
  }

  if (newPassword.value.length < 6) {
    changePwdError.value = 'New password must be at least 6 characters long.'
    return
  }

  isChangingPwd.value = true
  changePwdError.value = ''
  changePwdSuccess.value = ''

  try {
    await changePassword(currentPassword.value, newPassword.value)
    changePwdSuccess.value = 'Password successfully updated!'
    currentPassword.value = ''
    newPassword.value = ''
    confirmNewPassword.value = ''
  } catch (err) {
    console.error('[Settings] Password change failed:', err)
    changePwdError.value = err.response?.data?.detail ?? 'Failed to update password. Check current password.'
  } finally {
    isChangingPwd.value = false
  }
}

// --- User Management State (Admin only) ---
const usersList = ref([])
const isFetchingUsers = ref(false)
const usersError = ref('')

// Add user modal/form
const showAddModal = ref(false)
const newEmail = ref('')
const newPwd = ref('')
const newRole = ref('humas')
const isCreatingUser = ref(false)
const createUserError = ref('')

async function loadUsers() {
  if (!isAdmin.value) return
  isFetchingUsers.value = true
  usersError.value = ''
  try {
    const { data } = await getUsers()
    usersList.value = data
  } catch (err) {
    console.error('[Settings] Failed to fetch users:', err)
    usersError.value = err.response?.data?.detail ?? 'Failed to load user accounts list.'
  } finally {
    isFetchingUsers.value = false
  }
}

async function handleCreateUser() {
  if (!newEmail.value.trim() || !newPwd.value) {
    createUserError.value = 'Email and password are required.'
    return
  }

  isCreatingUser.value = true
  createUserError.value = ''

  try {
    await createUser(newEmail.value.trim(), newPwd.value, newRole.value)
    showAddModal.value = false
    newEmail.value = ''
    newPwd.value = ''
    newRole.value = 'humas'
    // Refresh user list
    await loadUsers()
    alert('User successfully created!')
  } catch (err) {
    console.error('[Settings] User creation failed:', err)
    createUserError.value = err.response?.data?.detail ?? 'Failed to create new user.'
  } finally {
    isCreatingUser.value = false
  }
}

async function handleDeleteUser(userId, email) {
  if (!isAdmin.value) return
  
  if (email === currentUserEmail.value) {
    alert('You cannot delete your own logged-in admin account.')
    return
  }

  const check = confirm(`Are you sure you want to permanently delete the user account "${email}"?`)
  if (!check) return

  try {
    await deleteUser(userId)
    usersList.value = usersList.value.filter(u => u.id !== userId)
    alert('User successfully deleted.')
  } catch (err) {
    console.error('[Settings] Delete failed:', err)
    alert(err.response?.data?.detail ?? 'Failed to delete user.')
  }
}

onMounted(() => {
  if (isAdmin.value) {
    loadUsers()
  }
})
</script>

<template>
  <div class="space-y-6 max-w-4xl">
    <!-- Page Heading -->
    <div>
      <h1 class="text-2xl font-bold text-slate-900">Account Settings</h1>
      <p class="text-sm text-slate-500 mt-1">
        Manage your profile settings, security password, and user accounts.
      </p>
    </div>

    <!-- Tab switcher (Only shown if admin, humas can only access profile) -->
    <div v-if="isAdmin" class="flex items-center gap-1.5 bg-slate-100 p-1 rounded-xl self-start inline-flex">
      <button
        @click="activeTab = 'profile'"
        :class="[
          'px-4 py-2 text-xs font-semibold rounded-lg transition-all duration-200',
          activeTab === 'profile' ? 'bg-white text-indigo-600 shadow-sm' : 'text-slate-500 hover:text-slate-800'
        ]"
      >
        My Profile
      </button>
      <button
        @click="activeTab = 'users'"
        :class="[
          'px-4 py-2 text-xs font-semibold rounded-lg transition-all duration-200',
          activeTab === 'users' ? 'bg-white text-indigo-600 shadow-sm' : 'text-slate-500 hover:text-slate-800'
        ]"
      >
        User Accounts ({{ usersList.length }})
      </button>
    </div>

    <!-- ── Profile Tab (Change Password) ────────────────────────────────────── -->
    <div v-if="activeTab === 'profile' || !isAdmin" class="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm max-w-xl">
      <h2 class="text-base font-semibold text-slate-800 mb-5">Change Security Password</h2>

      <!-- Success / Error alert -->
      <div v-if="changePwdSuccess" class="mb-4 bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs rounded-xl px-4 py-3">
        {{ changePwdSuccess }}
      </div>
      <div v-if="changePwdError" class="mb-4 bg-red-50 border border-red-200 text-red-700 text-xs rounded-xl px-4 py-3">
        {{ changePwdError }}
      </div>

      <form @submit.prevent="handlePasswordChange" class="space-y-4">
        <!-- Logged in details -->
        <div class="grid grid-cols-2 gap-4 pb-4 border-b border-gray-100">
          <div>
            <span class="text-xs text-slate-400 block font-medium">Logged in as</span>
            <span class="text-sm font-semibold text-slate-800 font-mono">{{ currentUserEmail }}</span>
          </div>
          <div>
            <span class="text-xs text-slate-400 block font-medium">Role</span>
            <span class="inline-block px-2.5 py-0.5 mt-0.5 rounded-full text-xxs font-bold uppercase bg-indigo-50 border border-indigo-100 text-indigo-700">
              {{ currentUserRole }}
            </span>
          </div>
        </div>

        <div>
          <label for="cur-pwd" class="block text-xs font-semibold text-slate-500 mb-1">Current Password</label>
          <input
            id="cur-pwd"
            v-model="currentPassword"
            type="password"
            placeholder="Enter current password"
            class="w-full border border-gray-200 rounded-lg px-3.5 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent transition"
            required
          />
        </div>

        <div>
          <label for="new-pwd" class="block text-xs font-semibold text-slate-500 mb-1">New Password</label>
          <input
            id="new-pwd"
            v-model="newPassword"
            type="password"
            placeholder="At least 6 characters"
            class="w-full border border-gray-200 rounded-lg px-3.5 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent transition"
            required
          />
        </div>

        <div>
          <label for="conf-pwd" class="block text-xs font-semibold text-slate-500 mb-1">Confirm New Password</label>
          <input
            id="conf-pwd"
            v-model="confirmNewPassword"
            type="password"
            placeholder="Re-enter new password"
            class="w-full border border-gray-200 rounded-lg px-3.5 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent transition"
            required
          />
        </div>

        <button
          type="submit"
          :disabled="isChangingPwd"
          class="inline-flex items-center gap-1.5 text-xs bg-indigo-600 hover:bg-indigo-700 text-white font-semibold px-5 py-2.5 rounded-xl disabled:opacity-40 transition shadow-sm"
        >
          <svg v-if="isChangingPwd" class="animate-spin h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          Update Password
        </button>
      </form>
    </div>

    <!-- ── User Management Tab (Admin only) ──────────────────────────────────── -->
    <div v-if="activeTab === 'users' && isAdmin" class="bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      <!-- Header inside card -->
      <div class="px-6 py-4 border-b border-gray-100 flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 class="text-base font-semibold text-slate-800">System Users</h2>
          <p class="text-xs text-slate-400 mt-0.5">Admin and Humas accounts allowed to access dashboard API</p>
        </div>
        <button
          @click="showAddModal = true"
          class="inline-flex items-center gap-1.5 text-xs bg-indigo-600 hover:bg-indigo-700 text-white font-semibold px-4 py-2 rounded-xl transition duration-150 shadow-sm shadow-indigo-100"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4"><path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" /></svg>
          Add New User
        </button>
      </div>

      <!-- Error / loading state -->
      <div v-if="usersError" class="m-6 bg-red-50 border border-red-200 text-red-700 text-xs rounded-xl px-4 py-3">
        {{ usersError }}
      </div>

      <!-- Users Table -->
      <div class="overflow-x-auto w-full">
        <table class="w-full text-sm min-w-[600px]">
          <thead>
            <tr class="bg-slate-50 border-b border-gray-100 text-slate-500 font-semibold text-xs uppercase tracking-wider">
              <th class="text-left px-5 py-3 w-12">ID</th>
              <th class="text-left px-5 py-3">Email Address</th>
              <th class="text-left px-5 py-3 w-28">Role</th>
              <th class="text-left px-5 py-3 w-40">Created At</th>
              <th class="text-center px-5 py-3 w-20">Actions</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-50 text-slate-700">
            <tr v-if="isFetchingUsers" class="animate-pulse">
              <td colspan="5" class="px-5 py-12 text-center text-slate-400">Loading accounts list…</td>
            </tr>
            <tr v-else-if="usersList.length === 0">
              <td colspan="5" class="px-5 py-12 text-center text-slate-400">No user accounts found.</td>
            </tr>
            <tr v-else v-for="user in usersList" :key="user.id" class="hover:bg-slate-50/50 transition-colors">
              <td class="px-5 py-3 text-slate-400 font-mono text-xs">{{ user.id }}</td>
              <td class="px-5 py-3 font-semibold font-mono text-xs">
                {{ user.email }}
                <span v-if="user.email === currentUserEmail" class="text-[9px] bg-slate-100 border text-slate-600 rounded px-1 ml-1.5 font-bold uppercase select-none">You</span>
              </td>
              <td class="px-5 py-3">
                <span
                  :class="[
                    'inline-block px-2 py-0.5 rounded-full text-xxs font-bold uppercase',
                    user.role === 'admin' ? 'bg-indigo-50 border border-indigo-100 text-indigo-700' : 'bg-slate-50 border border-slate-200 text-slate-600'
                  ]"
                >
                  {{ user.role }}
                </span>
              </td>
              <td class="px-5 py-3 text-slate-400 text-xs font-mono">
                <!-- Simple formatter -->
                {{ user.created_at ? user.created_at.slice(0,10) + ' ' + user.created_at.slice(11,16) : '—' }}
              </td>
              <td class="px-5 py-3 text-center">
                <button
                  @click="handleDeleteUser(user.id, user.email)"
                  :disabled="user.email === currentUserEmail"
                  class="p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 disabled:opacity-30 disabled:cursor-not-allowed transition"
                  title="Delete user"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
                    <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clip-rule="evenodd"/>
                  </svg>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ── Add User Modal Form ── -->
    <div v-if="showAddModal && isAdmin" class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <!-- Backdrop -->
      <div @click="showAddModal = false" class="fixed inset-0 bg-slate-950/40 backdrop-blur-sm"></div>
      
      <!-- Modal Content Card -->
      <div class="relative bg-white border border-gray-200 rounded-3xl p-6 w-full max-w-md shadow-2xl z-10 transition-transform">
        <div class="flex items-center justify-between mb-4 pb-3 border-b border-gray-100">
          <h3 class="font-bold text-slate-800 text-sm md:text-base">Register New Account</h3>
          <button @click="showAddModal = false" class="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5"><path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" /></svg>
          </button>
        </div>

        <div v-if="createUserError" class="mb-4 bg-red-50 border border-red-200 text-red-700 text-xs rounded-xl px-4 py-3">
          {{ createUserError }}
        </div>

        <form @submit.prevent="handleCreateUser" class="space-y-4">
          <div>
            <label for="new-email" class="block text-xs font-semibold text-slate-500 mb-1">Email Address</label>
            <input
              id="new-email"
              v-model="newEmail"
              type="email"
              placeholder="e.g. humas_staf@gmail.com"
              class="w-full border border-gray-200 rounded-lg px-3.5 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent transition"
              required
            />
          </div>

          <div>
            <label for="new-pwd" class="block text-xs font-semibold text-slate-500 mb-1">Security Password</label>
            <input
              id="new-pwd"
              v-model="newPwd"
              type="password"
              placeholder="At least 6 characters"
              class="w-full border border-gray-200 rounded-lg px-3.5 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent transition"
              required
            />
          </div>

          <div>
            <label for="new-role" class="block text-xs font-semibold text-slate-500 mb-1">Authority Role</label>
            <select
              id="new-role"
              v-model="newRole"
              class="w-full border border-gray-200 bg-white rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent transition"
            >
              <option value="humas">Humas (Read-only Dashboard)</option>
              <option value="admin">Admin (Full System Privilege)</option>
            </select>
          </div>

          <button
            type="submit"
            :disabled="isCreatingUser"
            class="w-full bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-bold py-2.5 px-4 rounded-xl transition duration-150 shadow-sm disabled:opacity-40 disabled:cursor-wait flex items-center justify-center gap-2 mt-6"
          >
            <svg v-if="isCreatingUser" class="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <span>{{ isCreatingUser ? 'Creating Account…' : 'Register User' }}</span>
          </button>
        </form>
      </div>
    </div>

  </div>
</template>
