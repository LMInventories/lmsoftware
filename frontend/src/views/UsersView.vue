<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '../services/api'
import { useToast } from '../composables/useToast'
import { useAuthStore } from '../stores/auth'
const authStore = useAuthStore()
const toast = useToast()

const users = ref([])
const loading = ref(true)
const showModal = ref(false)
const editingUser = ref(null)

const form = ref({
  name: '',
  email: '',
  phone: '',
  password: '',
  role: 'clerk',
  color: '#6366f1',
  typist_mode: null,
})

// Typist mode options — shown only when role = 'clerk'
const typistModeOptions = [
  { value: null,         label: 'None (manual only)' },
  { value: 'ai_instant', label: 'AI Instant — per-item mic, fills fields automatically' },
  { value: 'ai_room',    label: 'AI by Room — record whole room, AI transcribes' },
  { value: 'human',      label: 'Human Typist — audio synced to typist queue' },
]

const roles = [
  { value: 'admin', label: 'Admin' },
  { value: 'manager', label: 'Manager' },
  { value: 'clerk', label: 'Clerk' },
  { value: 'typist', label: 'Typist' }
]

const filters = ref({ search: '', role: '' })

const filteredUsers = computed(() => {
  let result = [...users.value]
  const s = filters.value.search.toLowerCase().trim()
  if (s) result = result.filter(u => u.name.toLowerCase().includes(s) || u.email.toLowerCase().includes(s))
  if (filters.value.role) result = result.filter(u => u.role === filters.value.role)
  return result.sort((a, b) => {
    const roleOrder = { admin: 1, manager: 2, clerk: 3, typist: 4 }
    return roleOrder[a.role] - roleOrder[b.role]
  })
})

async function fetchUsers() {
  loading.value = true
  try {
    const response = await api.getUsers()
    users.value = response.data
  } catch (error) {
    console.error('Failed to fetch users:', error)
    toast.error('Failed to load users')
  } finally {
    loading.value = false
  }
}

function openModal() {
  form.value = {
    name: '',
    email: '',
    phone: '',
    password: '',
    role: 'clerk',
    color: '#6366f1',
    typist_mode: null,
  }
  editingUser.value = null
  showModal.value = true
}

function editUser(user) {
  form.value = {
    name: user.name,
    email: user.email,
    phone: user.phone || '',
    password: '',
    role: user.role,
    color: user.color || '#6366f1',
    typist_mode: user.typist_mode || null,
  }
  editingUser.value = user
  showModal.value = true
}

async function handleSubmit() {
  try {
    if (editingUser.value) {
      // Update existing user
      await api.updateUser(editingUser.value.id, form.value)
      toast.success('User updated')
    } else {
      // Create new user
      if (!form.value.password) {
        toast.warning('Password is required for new users')
        return
      }
      await api.createUser(form.value)
      toast.success('User created')
    }
    showModal.value = false
    fetchUsers()
  } catch (error) {
    console.error('Failed to save user:', error)
    // Surface the actual server error message if available
    const msg = error.response?.data?.error || 'Failed to save user'
    toast.error(msg)
  }
}

async function deleteUser(id) {
  if (!confirm('Delete this user?')) return
  
  try {
    await api.deleteUser(id)
    toast.success('User deleted')
    fetchUsers()
  } catch (error) {
    console.error('Failed to delete user:', error)
    toast.error('Failed to delete user')
  }
}

function getRoleBadgeColor(role) {
  const colors = {
    admin: '#dc2626',
    manager: '#ea580c',
    clerk: '#2563eb',
    typist: '#7c3aed'
  }
  return colors[role] || '#64748b'
}

onMounted(() => {
  fetchUsers()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>Users</h1>
        <p class="subtitle">{{ filteredUsers.length }} of {{ users.length }} shown</p>
      </div>
      <button @click="openModal" class="btn-primary">+ New User</button>
    </div>

    <div class="filters-bar">
      <div class="filter-group">
        <label>Search</label>
        <input v-model="filters.search" type="text" placeholder="Name or email..." class="filter-input" />
      </div>
      <div class="filter-group">
        <label>Role</label>
        <select v-model="filters.role" class="filter-select">
          <option value="">All Roles</option>
          <option value="admin">Admin</option>
          <option value="manager">Manager</option>
          <option value="clerk">Clerk</option>
          <option value="typist">Typist</option>
        </select>
      </div>
      <button @click="filters = { search: '', role: '' }" class="btn-clear">Clear</button>
    </div>

    
    <button
      v-if="authStore.isAdmin || authStore.isManager"
      class="mobile-fab-add"
      @click="openModal"
      title="New User"
    >+</button>
    <div v-if="loading" class="loading">Loading...</div>

    <div v-else class="users-grid">
      <div v-for="user in filteredUsers" :key="user.id" class="user-card">
        <div class="card-top-bar" :style="{ background: getRoleBadgeColor(user.role) }"></div>
        <div class="card-body">
          <div class="user-identity">
            <div class="user-avatar" :style="{ background: user.color || getRoleBadgeColor(user.role) }">
              {{ user.name.split(' ').map(w => w[0]).slice(0,2).join('').toUpperCase() }}
            </div>
            <div class="user-name-block">
              <div class="user-name-row">
                <h3>{{ user.name }}</h3>
                <span
                  v-if="user.role === 'clerk' || user.role === 'typist'"
                  class="color-dot"
                  :style="{ backgroundColor: user.color }"
                  :title="`Calendar color: ${user.color}`"
                ></span>
              </div>
              <span class="role-badge" :style="{ backgroundColor: getRoleBadgeColor(user.role) }">{{ user.role }}</span>
            </div>
          </div>

          <div class="user-details">
            <div class="detail-row"><span class="detail-icon">✉</span>{{ user.email }}</div>
            <div v-if="user.phone" class="detail-row"><span class="detail-icon">✆</span>{{ user.phone }}</div>
            <div v-if="user.role === 'clerk' && user.typist_mode" class="detail-row">
              <span class="detail-icon"></span>
              <span class="typist-mode-pill" :class="'tm-' + user.typist_mode">
                {{ { ai_instant: 'AI Instant', ai_room: 'AI by Room', human: 'Human Typist' }[user.typist_mode] || user.typist_mode }}
              </span>
            </div>
            <div class="detail-row detail-muted"><span class="detail-icon"></span>Since {{ new Date(user.created_at).toLocaleDateString('en-GB', {day:'2-digit',month:'short',year:'numeric'}) }}</div>
          </div>
        </div>

        <div class="card-actions">
          <button @click="editUser(user)" class="btn-action btn-edit">Edit</button>
          <button @click="deleteUser(user.id)" class="btn-action btn-delete">Delete</button>
        </div>
      </div>

      <div v-if="filteredUsers.length === 0" class="empty-state">
        {{ users.length === 0 ? 'No users yet. Create your first user!' : 'No users match your filters.' }}
      </div>
    </div>

    <!-- Modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
      <div class="modal">
        <div class="modal-header">
          <h2>{{ editingUser ? 'Edit User' : 'New User' }}</h2>
          <button @click="showModal = false" class="btn-close">✕</button>
        </div>

        <form @submit.prevent="handleSubmit" class="modal-body">
          <div class="form-group">
            <label>Name *</label>
            <input v-model="form.name" type="text" required />
          </div>

          <div class="form-group">
            <label>Email *</label>
            <input v-model="form.email" type="email" required />
          </div>

          <div class="form-group">
            <label>Phone</label>
            <input v-model="form.phone" type="tel" />
          </div>

          <div class="form-group">
            <label>Role *</label>
            <select v-model="form.role" required>
              <option v-for="role in roles" :key="role.value" :value="role.value">
                {{ role.label }}
              </option>
            </select>
          </div>

          <!-- Color Picker (for clerks/typists) -->
          <div v-if="form.role === 'clerk' || form.role === 'typist'" class="form-group">
            <label>Calendar Color</label>
            <div class="color-picker-container">
              <input 
                v-model="form.color" 
                type="color" 
                class="color-input"
              />
              <span class="color-preview" :style="{ backgroundColor: form.color }"></span>
              <span class="color-value">{{ form.color }}</span>
            </div>
            <p class="helper-text">This color will be used in the calendar view to identify this {{ form.role }}'s inspections</p>
          </div>

          <!-- Typist mode — clerks only (admin-facing, not visible to clerks) -->
          <div v-if="form.role === 'clerk'" class="form-group">
            <label>Typist Mode</label>
            <select v-model="form.typist_mode">
              <option v-for="opt in typistModeOptions" :key="String(opt.value)" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
            <p class="helper-text">
              Controls the recording &amp; AI behaviour in the mobile app for this clerk.
              <br/><strong>AI Instant</strong> — mic next to each item, fills fields immediately.
              <br/><strong>AI by Room</strong> — records full room, AI fills all items at once.
              <br/><strong>Human Typist</strong> — audio synced to server, typist receives email &amp; types the report.
            </p>
          </div>

          <div class="form-group">
            <label>{{ editingUser ? 'Password (leave blank to keep current)' : 'Password *' }}</label>
            <input
              v-model="form.password"
              type="password"
              :required="!editingUser"
            />
          </div>

          <div class="modal-footer">
            <button type="button" @click="showModal = false" class="btn-secondary">Cancel</button>
            <button type="submit" class="btn-primary">
              {{ editingUser ? 'Update User' : 'Create User' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 1400px; }

.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
h1 { font-size: 21px; font-weight: 700; color: #0f172a; margin: 0 0 1px; }
.subtitle { font-size: 11px; color: #94a3b8; margin: 0; }

.btn-primary { padding: 7px 16px; background: #6366f1; color: white; border: none; border-radius: 7px; font-size: 13px; font-weight: 600; cursor: pointer; transition: background 0.15s; }
.btn-primary:hover { background: #4f46e5; }

/* Filters */
.filters-bar { display: flex; align-items: flex-end; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; background: white; border: 1px solid #e9ecef; border-radius: 9px; padding: 10px 14px; }
.filter-group { display: flex; flex-direction: column; gap: 4px; min-width: 140px; }
.filter-group label { font-size: 10px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.4px; }
.filter-select, .filter-input { padding: 6px 9px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 12px; background: white; color: #1e293b; font-family: inherit; }
.btn-clear { padding: 6px 12px; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 11px; font-weight: 600; color: #64748b; cursor: pointer; align-self: flex-end; }
.btn-clear:hover { background: #e2e8f0; }

.loading { text-align: center; padding: 60px; color: #94a3b8; font-size: 13px; }

/* Grid */
.users-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 8px; }

/* Card */
.user-card { background: white; border: 1px solid #e2e8f0; border-radius: 9px; overflow: hidden; transition: box-shadow 0.15s, transform 0.12s; display: flex; flex-direction: column; }
.user-card:hover { box-shadow: 0 3px 10px rgba(0,0,0,0.07); transform: translateY(-1px); }

.card-top-bar { height: 3px; flex-shrink: 0; }

.card-body { padding: 11px 13px 8px; flex: 1; }

.user-identity { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }

.user-avatar {
  width: 36px; height: 36px; border-radius: 8px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: white; letter-spacing: -0.5px;
}

.user-name-block { flex: 1; min-width: 0; }

.user-name-row { display: flex; align-items: center; gap: 6px; margin-bottom: 3px; }
h3 { font-size: 13px; font-weight: 700; color: #1e293b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.color-dot { width: 10px; height: 10px; border-radius: 50%; border: 1px solid rgba(0,0,0,0.1); flex-shrink: 0; }

.role-badge { display: inline-block; padding: 2px 8px; color: white; border-radius: 10px; font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }

.user-details { display: flex; flex-direction: column; gap: 3px; }
.detail-row { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #475569; }
.detail-icon { font-size: 10px; opacity: 0.6; flex-shrink: 0; }
.detail-muted { color: #94a3b8; font-size: 10px; }

.card-actions { display: flex; border-top: 1px solid #f1f5f9; }
.btn-action { flex: 1; padding: 7px 8px; border: none; background: transparent; font-size: 11px; font-weight: 600; cursor: pointer; transition: background 0.15s; border-right: 1px solid #f1f5f9; }
.btn-action:last-child { border-right: none; }
.btn-edit { color: #4338ca; }
.btn-edit:hover { background: #eef2ff; }
.btn-delete { color: #dc2626; }
.btn-delete:hover { background: #fef2f2; }

.empty-state { grid-column: 1 / -1; text-align: center; padding: 60px 20px; color: #94a3b8; font-size: 13px; }

/* Modal */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
.modal { background: white; border-radius: 12px; width: 100%; max-width: 460px; max-height: 92vh; overflow: hidden; display: flex; flex-direction: column; box-shadow: 0 20px 60px rgba(0,0,0,0.2); }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; border-bottom: 1px solid #f1f5f9; }
.modal-header h2 { font-size: 15px; font-weight: 700; color: #0f172a; }
.btn-close { background: none; border: none; font-size: 16px; color: #94a3b8; cursor: pointer; padding: 3px 7px; border-radius: 4px; }
.btn-close:hover { background: #f1f5f9; }
.modal-body { padding: 18px 20px; overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 14px; }

.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label { font-size: 11px; font-weight: 700; color: #374151; }
.form-group input, .form-group select { padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 13px; font-family: inherit; color: #1e293b; background: white; width: 100%; }
.form-group input:focus, .form-group select:focus { outline: none; border-color: #6366f1; box-shadow: 0 0 0 2px rgba(99,102,241,0.08); }

.color-picker-container { display: flex; align-items: center; gap: 10px; }
.color-input { width: 44px !important; height: 34px; padding: 2px !important; border: 1px solid #e2e8f0; border-radius: 6px; cursor: pointer; }
.color-preview { width: 34px; height: 34px; border-radius: 6px; border: 1px solid #e2e8f0; flex-shrink: 0; }
.color-value { font-family: monospace; font-size: 12px; color: #64748b; font-weight: 600; }
.helper-text { font-size: 11px; color: #64748b; line-height: 1.5; }

/* Typist mode pill on user cards */
.typist-mode-pill { display: inline-block; padding: 1px 7px; border-radius: 8px; font-size: 10px; font-weight: 700; }
.tm-ai_instant { background: #eef2ff; color: #4338ca; }
.tm-ai_room    { background: #f0fdf4; color: #166534; }
.tm-human      { background: #fff7ed; color: #9a3412; }

.modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 20px; border-top: 1px solid #f1f5f9; background: #f8fafc; }
.btn-secondary { padding: 7px 14px; background: white; color: #64748b; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; }
.btn-secondary:hover { background: #f8fafc; }

/* ══════════════════════════════════════
   MOBILE  ≤ 768px
══════════════════════════════════════ */
@media (max-width: 768px) {
  .page-header .btn-primary { display: none; }
  .mobile-fab-add { display: flex !important; }

  .filters-bar { flex-direction: column; padding: 10px 12px; gap: 8px; }
  .filter-group { min-width: 100%; }

  .users-grid { grid-template-columns: 1fr; gap: 8px; }

  .modal-overlay { align-items: flex-end; padding: 0; }
  .modal { border-radius: 20px 20px 0 0; max-width: 100%; max-height: 94vh; }
}


.mobile-fab-add {
  display: none;
  position: fixed;
  bottom: 76px; right: 18px;
  width: 52px; height: 52px;
  background: #6366f1; color: white;
  border: none; border-radius: 50%;
  font-size: 26px; line-height: 1;
  box-shadow: 0 4px 14px rgba(99,102,241,0.4);
  cursor: pointer; z-index: 150;
  align-items: center; justify-content: center;
  transition: transform 0.15s;
}
.mobile-fab-add:hover { transform: scale(1.07); }

</style>