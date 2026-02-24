import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],

  server: {
    host: true,          // allow external access
    port: 3000,

    // ✅ Allow Cloudflare tunnel domain
    allowedHosts: [
      'lime-newsletter-sapphire-kingdom.trycloudflare.com'
    ],

    // ✅ Send API calls to Flask automatically
    proxy: {
      '/api': {
        target: 'http://localhost:5000', // your Flask server
        changeOrigin: true,
        secure: false
      }
    }
  }
})