/**
 * server.js — Production static-file server with /api proxy.
 *
 * Required Railway env var:  BACKEND_URL=https://<your-flask-service>.railway.app
 */

import express   from 'express'
import httpProxy from 'http-proxy'
import { fileURLToPath } from 'url'
import { dirname, join }  from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))

const PORT        = process.env.PORT        || 3000
const BACKEND_URL = (process.env.BACKEND_URL || '').replace(/\/$/, '')

// Log clearly at startup so Railway logs show the config
console.log('=== server.js starting ===')
console.log('PORT        :', PORT)
console.log('BACKEND_URL :', BACKEND_URL || '(NOT SET)')

if (!BACKEND_URL) {
  console.error('ERROR: BACKEND_URL env var is not set on this service.')
  console.error('Set BACKEND_URL=https://<flask-service>.railway.app in Railway → frontend → Variables')
}

// ── Proxy ──────────────────────────────────────────────────────────────────────
const proxy = httpProxy.createProxyServer({
  target:       BACKEND_URL || 'http://localhost:5000',
  changeOrigin: true,
  proxyTimeout: 300_000,
  timeout:      300_000,
})

proxy.on('error', (err, req, res) => {
  console.error(`[proxy error] ${req.method} ${req.url} — ${err.code}: ${err.message}`)
  try {
    if (!res.headersSent) {
      res.writeHead(502, { 'Content-Type': 'text/plain' })
      res.end(`Proxy error: ${err.code} — ${err.message}\nBACKEND_URL=${BACKEND_URL || '(not set)'}`)
    }
  } catch (e) {
    console.error('[proxy error] failed to send error response:', e.message)
  }
})

proxy.on('proxyRes', (proxyRes, req) => {
  if (proxyRes.statusCode >= 500) {
    console.error(`[proxy] ${req.method} ${req.url} → ${proxyRes.statusCode}`)
  }
})

// ── Routes ────────────────────────────────────────────────────────────────────
const app = express()

// Forward /api/* to Flask — restore the /api prefix Express strips from req.url
app.use('/api', (req, res, next) => {
  req.url = '/api' + req.url
  proxy.web(req, res, {}, next)
})

// Serve built Vue SPA
app.use(express.static(join(__dirname, 'dist')))

// SPA fallback
app.get('*', (_req, res) => {
  res.sendFile(join(__dirname, 'dist', 'index.html'))
})

// Catch any unhandled Express errors and show them clearly
app.use((err, _req, res, _next) => {
  console.error('[express error]', err)
  if (!res.headersSent) res.status(500).send(`Express error: ${err.message}`)
})

app.listen(PORT, () => {
  console.log(`Frontend listening on :${PORT}`)
  console.log(`Proxying /api → ${BACKEND_URL || '(NOT SET)'}`)
})
