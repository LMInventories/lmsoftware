/**
 * server.js — Production static-file server with /api proxy.
 *
 * Uses the `http-proxy` package (mature, handles chunked encoding /
 * hop-by-hop headers automatically) to forward /api/* to Flask.
 *
 * Required Railway env var:  BACKEND_URL=https://<your-flask-service>.railway.app
 */

import express    from 'express'
import httpProxy  from 'http-proxy'
import { fileURLToPath } from 'url'
import { dirname, join }  from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))

const PORT        = process.env.PORT        || 3000
const BACKEND_URL = (process.env.BACKEND_URL || '').replace(/\/$/, '')

if (!BACKEND_URL) {
  console.error('⚠️  BACKEND_URL env var is not set.')
  console.error('   Set BACKEND_URL=https://<your-flask-service>.railway.app in Railway.')
}

const proxy = httpProxy.createProxyServer({
  target:       BACKEND_URL || 'http://localhost:5000',
  changeOrigin: true,
  proxyTimeout: 300_000,
  timeout:      300_000,
})

proxy.on('error', (err, req, res) => {
  console.error(`[proxy] ${req.method} ${req.url} →`, err.message)
  if (!res.headersSent) {
    res.writeHead(502, { 'Content-Type': 'text/plain' })
  }
  res.end(`Backend unavailable: ${err.message}`)
})

const app = express()

// Forward /api/* to Flask.  http-proxy preserves the full path including /api.
app.use('/api', (req, res) => {
  // Express strips the /api prefix from req.url; put it back so Flask sees /api/...
  req.url = '/api' + req.url
  proxy.web(req, res)
})

// Serve the built Vue SPA
app.use(express.static(join(__dirname, 'dist')))

// SPA fallback — let Vue Router handle all non-file routes
app.get('*', (_req, res) => {
  res.sendFile(join(__dirname, 'dist', 'index.html'))
})

app.listen(PORT, () => {
  console.log(`Frontend on :${PORT}`)
  console.log(`API proxy  → ${BACKEND_URL || '(NOT SET — set BACKEND_URL)'}`)
})
