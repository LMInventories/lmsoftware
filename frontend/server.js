/**
 * server.js — Production static-file server with /api proxy.
 *
 * Required Railway env var:  BACKEND_URL=https://<your-flask-service>.railway.app
 * (must include https://)
 */

import express   from 'express'
import httpProxy from 'http-proxy'
import http      from 'http'
import https     from 'https'
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

// ── Keep-alive agents ─────────────────────────────────────────────────────────
// Re-using existing TCP/TLS connections avoids a new TLS handshake for every
// request.  This matters especially for gallery photo endpoints: when the
// browser fires 6+ parallel /api/gallery/.../photo/<n> requests, each one
// previously needed its own TLS handshake to the Railway internal backend.
// Under Railway's private network that causes ETIMEDOUT for the slower ones.
// With keepAlive the handshake cost is paid once and sockets are reused.
const httpAgent  = new http.Agent ({ keepAlive: true, maxSockets: 20 })
const httpsAgent = new https.Agent({ keepAlive: true, maxSockets: 20 })

// ── Proxy ─────────────────────────────────────────────────────────────────────
const proxy = httpProxy.createProxyServer({
  changeOrigin: true,
  proxyTimeout: 300_000,   // 5 min wait for backend to respond
  // Use the appropriate keep-alive agent depending on BACKEND_URL scheme.
  // This is resolved lazily on first request so BACKEND_URL is already set.
})

// Attach the keep-alive agent on each request so we don't have to decide
// the scheme at startup time (BACKEND_URL might still be empty then).
proxy.on('proxyReq', (proxyReq, _req, _res, options) => {
  const isHttps = (options.target || '').toString().startsWith('https')
  if (!proxyReq.agent) {
    proxyReq.agent = isHttps ? httpsAgent : httpAgent
  }
})

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

// Serve built Vue SPA.
// Vite hashes all asset filenames (main.abc123.js) so they can be cached forever.
// Only index.html must stay uncached so the browser always gets the latest shell.
app.use(express.static(join(__dirname, 'dist'), {
  maxAge: '1y',          // cache hashed assets for a year
  etag:   true,
  setHeaders(res, filePath) {
    if (filePath.endsWith('index.html')) {
      // Never cache the SPA entry point
      res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate')
    }
  },
}))

// SPA fallback — let Vue Router handle everything else
app.get('*', (_req, res) => {
  res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate')
  res.sendFile(join(__dirname, 'dist', 'index.html'))
})

app.listen(PORT, () => {
  console.log(`Listening on :${PORT}, proxying /api → ${BACKEND_URL}`)
})
