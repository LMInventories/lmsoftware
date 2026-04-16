/**
 * server.js — Production static-file server with /api proxy.
 *
 * Replaces `serve -s dist` so that /api/* requests are forwarded to the
 * Flask backend instead of falling through to index.html.
 *
 * Required Railway env var:  BACKEND_URL=https://<your-backend>.railway.app
 */

import express from 'express'
import { createProxyMiddleware } from 'http-proxy-middleware'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))

const PORT        = process.env.PORT        || 3000
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:5000'

const app = express()

// ── Forward all /api requests to Flask ────────────────────────────────────────
app.use(
  '/api',
  createProxyMiddleware({
    target:       BACKEND_URL,
    changeOrigin: true,
    // Allow large photo uploads / PDF downloads
    proxyTimeout: 300_000,
    timeout:      300_000,
  })
)

// ── Serve the built Vue SPA ───────────────────────────────────────────────────
app.use(express.static(join(__dirname, 'dist')))

// SPA fallback — let Vue Router handle all non-file routes
app.get('*', (_req, res) => {
  res.sendFile(join(__dirname, 'dist', 'index.html'))
})

app.listen(PORT, () => {
  console.log(`Frontend on :${PORT}  →  API proxied to ${BACKEND_URL}`)
})
