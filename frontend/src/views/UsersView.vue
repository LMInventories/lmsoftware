<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '../services/api'
import { useToast } from '../composables/useToast'
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
  color: '#6366f1'
})

const roles = [
  { value: 'admin', label: 'Admin' },
  { value: 'manager', label: 'Manager' },
  { value: 'clerk', label: 'Clerk' },
  { value: 'typist', label: 'Typist' }
]

const filteredUsers = computed(() => {
  return users.value.sort((a, b) => {
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
    color: '#6366f1'
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
    color: user.color || '#6366f1'
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
      <h1>👥 Users</h1>
      <button @click="openModal" class="btn-primary">➕ New User</button>
    </div>

    <div v-if="loading" class="loading">Loading...</div>

    <div v-else class="users-grid">
      <div v-for="user in filteredUsers" :key="user.id" class="user-card">
        <div class="user-header">
          <div class="user-info">
            <div class="user-name-row">
              <h3>{{ user.name }}</h3>
              <span 
                v-if="user.role === 'clerk' || user.role === 'typist'"
                class="color-dot" 
                :style="{ backgroundColor: user.color }"
                :title="`Calendar color: ${user.color}`"
              ></span>
            </div>
            <span 
              class="role-badge" 
              :style="{ backgroundColor: getRoleBadgeColor(user.role) }"
            >
              {{ user.role }}
            </span>
          </div>
        </div>

        <div class="user-details">
          <p>📧 {{ user.email }}</p>
          <p v-if="user.phone">📱 {{ user.phone }}</p>
          <p class="user-created">Created: {{ new Date(user.created_at).toLocaleDateString('en-GB') }}</p>
        </div>

        <div class="user-actions">
          <button @click="editUser(user)" class="btn-edit">Edit</button>
          <button @click="deleteUser(user.id)" class="btn-delete">Delete</button>
        </div>
      </div>

      <div v-if="users.length === 0" class="empty-state">
        No users yet. Create your first user!
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
.page {
  max-width: 1400px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
}

.page-header h1 {
  font-size: 32px;
  font-weight: 700;
  color: #1e293b;
}

.btn-primary {
  padding: 12px 24px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary:hover {
  background: #4f46e5;
}

.loading {
  text-align: center;
  padding: 60px;
  color: #64748b;
}

.users-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.user-card {
  background: white;
  padding: 24px;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.user-header {
  margin-bottom: 16px;
}

.user-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.user-name-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-card h3 {
  font-size: 20px;
  font-weight: 600;
  color: #1e293b;
}

.color-dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px #cbd5e1;
  flex-shrink: 0;
}

.role-badge {
  display: inline-block;
  padding: 4px 12px;
  color: white;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  width: fit-content;
}

.user-details {
  margin-bottom: 16px;
}

.user-details p {
  font-size: 14px;
  color: #64748b;
  margin: 6px 0;
}

.user-created {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 12px;
}

.user-actions {
  display: flex;
  gap: 12px;
}

.btn-edit {
  flex: 1;
  padding: 10px 20px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.btn-edit:hover {
  background: #4f46e5;
}

.btn-delete {
  flex: 1;
  padding: 10px 20px;
  background: #fee2e2;
  color: #991b1b;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.btn-delete:hover {
  background: #fecaca;
}

.empty-state {
  grid-column: 1 / -1;
  text-align: center;
  padding: 60px 20px;
  color: #64748b;
}

/* Modal styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal {
  background: white;
  border-radius: 12px;
  width: 100%;
  max-width: 500px;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24px;
  border-bottom: 1px solid #e5e7eb;
}

.modal-header h2 {
  font-size: 20px;
  font-weight: 600;
}

.btn-close {
  background: none;
  border: none;
  font-size: 24px;
  cursor: pointer;
  padding: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
}

.btn-close:hover {
  background: #f1f5f9;
}

.modal-body {
  padding: 24px;
  overflow-y: auto;
  flex: 1;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
  color: #475569;
  font-size: 14px;
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: #6366f1;
}

.color-picker-container {
  display: flex;
  align-items: center;
  gap: 12px;
}

.color-input {
  width: 60px !important;
  height: 40px;
  padding: 4px !important;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  cursor: pointer;
}

.color-preview {
  width: 40px;
  height: 40px;
  border-radius: 6px;
  border: 2px solid #cbd5e1;
}

.color-value {
  font-family: monospace;
  font-size: 14px;
  color: #64748b;
  font-weight: 600;
}

.helper-text {
  margin-top: 6px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 20px 24px;
  border-top: 1px solid #e5e7eb;
  background: #f8fafc;
}

.btn-secondary {
  padding: 10px 20px;
  background: white;
  color: #64748b;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
  font-size: 14px;
}

.btn-secondary:hover {
  background: #f1f5f9;
}
</style>
