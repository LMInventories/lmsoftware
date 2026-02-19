<script setup>
import { ref } from 'vue'

const turnaroundTime = ref('24')
const typistNotes = ref('')
</script>

<template>
  <div class="settings-section">
    <h2>Transcription Settings</h2>
    <p class="section-description">
      Configure settings for human typists. These settings are sent when inspections move to 'Processing' status.
    </p>
    
    <div class="form-section">
      <div class="form-group">
        <label>Default Turnaround Time</label>
        <select v-model="turnaroundTime" class="input-field" disabled>
          <option value="6">6 hours (Rush)</option>
          <option value="24">24 hours (Standard)</option>
          <option value="72">72 hours (Economy)</option>
        </select>
        <p class="helper-text">Default expected completion time for typists</p>
      </div>
      
      <div class="form-group">
        <label>Default Notes for Typist</label>
        <textarea 
          v-model="typistNotes" 
          class="textarea-field" 
          rows="6" 
          placeholder="Enter any standard instructions or notes for typists..."
          disabled
        ></textarea>
        <p class="helper-text">These notes will be included with every inspection sent to processing</p>
      </div>
      
      <button class="btn-save" disabled>
        💾 Save Settings
      </button>
    </div>
    
    <p class="coming-soon">Full transcription configuration coming soon...</p>
  </div>
</template>

<style scoped>
.settings-section h2 {
  font-size: 24px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
}

.section-description {
  color: #64748b;
  font-size: 15px;
  margin-bottom: 32px;
}

.form-section {
  max-width: 600px;
}

.form-group {
  margin-bottom: 24px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
  color: #475569;
  font-size: 14px;
}

.input-field,
.textarea-field {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
  font-family: inherit;
}

.input-field:disabled,
.textarea-field:disabled {
  background: #f1f5f9;
  color: #94a3b8;
  cursor: not-allowed;
}

.helper-text {
  margin-top: 6px;
  font-size: 12px;
  color: #64748b;
}

.btn-save {
  padding: 12px 24px;
  background: #e5e7eb;
  color: #94a3b8;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: not-allowed;
  margin-bottom: 24px;
}

.coming-soon {
  text-align: center;
  color: #94a3b8;
  font-style: italic;
  margin-top: 32px;
}
</style>
