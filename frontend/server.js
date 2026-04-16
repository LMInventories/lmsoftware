/**
 * server.js — Production static-file server with /api proxy.
 *
 * Required Railway env var:  BACKEND_URL=https://<your-flask-service>.railway.app
 * (must include https://)
 */

import express   from 'express'
import httpProxy from 'http-proxy'
import { fileURLToPath } from 'url'
import { dirname, join }  from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))

const PORT = process.env.PORT || 3000

// Normalise BACKEND_URL — add https:// if the user forgot it
let BACKEND_URL = (process.env.BACKEND_URL || '').trim().replace(/\/$/, '')
if (BACKEND_URL && !BACKEND_URL.startsWith('http')) {
  BACKEND_URL = 'https://' + BACKEND_URL
}

console.log('=== server.js starting ===')
console.log('PORT        :', PORT)
console.log('BACKEND_URL :', BACKEND_URL || '(NOT SET — will fail)')

// ── Proxy ──────────────────────────────────────────────────────────────────────
const proxy = httpProxy.createProxyServer({ changeOrigin: true, proxyTimeout: 300_000 })

proxy.on('error', (err, req, res) => {
  console.error(`[proxy error] ${req.method} ${req.url} — ${err.code}: ${err.message}`)
  try {
    if (!res.headersSent) {
      res.writeHead(502, { 'Content-Type': 'text/plain' })
      res.end(`Proxy error (${err.code}): ${err.message}\nBACKEND_URL=${BACKEND_URL || 'not set'}`)
    }
  } catch (_) {}
})

proxy.on('proxyRes', (proxyRes, req) => {
  if (proxyRes.statusCode >= 400) {
    console.log(`[proxy] ${req.method} ${req.url} → ${proxyRes.statusCode}`)
  }
})

// ── Routes ────────────────────────────────────────────────────────────────────
const app = express()

// Forward /api/* to Flask.
// Express strips the /api prefix from req.url inside this middleware, so we
// restore it before forwarding so Flask sees the full /api/... path.
app.use('/api', (req, res) => {
  if (!BACKEND_URL) {
    res.status(503).send('BACKEND_URL is not set on this service.')
    return
  }
  req.url = '/api' + req.url
  proxy.web(req, res, { target: BACKEND_URL })
})

// Serve built Vue SPA
app.use(express.static(join(__dirname, 'dist')))

// SPA fallback — let Vue Router handle everything else
app.get('*', (_req, res) => {
  res.sendFile(join(__dirname, 'dist', 'index.html'))
})

app.listen(PORT, () => {
  console.log(`Listening on :${PORT}, proxying /api → ${BACKEND_URL}`)
})
