/**
 * server.js — Production static-file server with /api proxy.
 *
 * Replaces `serve -s dist` so that /api/* requests are forwarded to the
 * Flask backend instead of falling through to index.html.
 *
 * Required Railway env var:  BACKEND_URL=https://<your-backend>.railway.app
 *
 * Uses Node's built-in http/https modules to proxy — no external proxy
 * middleware, so there are no package compatibility issues.
 */

import express from 'express'
import http    from 'http'
import https   from 'https'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))

const PORT        = process.env.PORT        || 3000
const BACKEND_URL = (process.env.BACKEND_URL || '').replace(/\/$/, '')

if (!BACKEND_URL) {
  console.error('⚠️  BACKEND_URL env var is not set — /api requests will fail.')
  console.error('   Set BACKEND_URL=https://<your-flask-service>.railway.app in Railway.')
}

const app = express()

// ── Forward all /api/* requests to Flask ─────────────────────────────────────
app.use('/api', (req, res) => {
  if (!BACKEND_URL) {
    return res.status(503).send('BACKEND_URL is not configured on this service.')
  }

  const target   = new URL(BACKEND_URL)
  const isHttps  = target.protocol === 'https:'
  const driver   = isHttps ? https : http
  const fullPath = '/api' + req.url          // preserve /api prefix for Flask

  const options = {
    hostname: target.hostname,
    port:     target.port || (isHttps ? 443 : 80),
    path:     fullPath,
    method:   req.method,
    headers:  {
      ...req.headers,
      host: target.hostname,               // avoid sending frontend host header
    },
  }

  const proxyReq = driver.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers)
    proxyRes.pipe(res, { end: true })
  })

  proxyReq.setTimeout(300_000, () => {
    proxyReq.destroy()
    if (!res.headersSent) res.status(504).send('Backend request timed out.')
  })

  proxyReq.on('error', (err) => {
    console.error(`[proxy] ${req.method} ${fullPath} →`, err.message)
    if (!res.headersSent) res.status(502).send(`Backend unavailable: ${err.message}`)
  })

  req.pipe(proxyReq, { end: true })
})

// ── Serve the built Vue SPA ───────────────────────────────────────────────────
app.use(express.static(join(__dirname, 'dist')))

// SPA fallback — let Vue Router handle all non-file routes
app.get('*', (_req, res) => {
  res.sendFile(join(__dirname, 'dist', 'index.html'))
})

app.listen(PORT, () => {
  console.log(`Frontend on :${PORT}`)
  console.log(`API proxy → ${BACKEND_URL || '(NOT SET)'}`)
})
