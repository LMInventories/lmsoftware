# Migrate InspectPro to Fly.io (London)

Moving from Railway US → Fly.io London reduces API latency from ~130ms to ~5ms per round trip.
Total time: about 1–2 hours including database migration.

---

## Why Fly.io London

| | Railway (current) | Fly.io London |
|---|---|---|
| Server location | US Central (GCP) | London Heathrow (LHR) |
| Round-trip from UK | ~130ms per request | ~5ms per request |
| Cold starts | Yes (on lower plans) | No (`min_machines_running = 1`) |
| Cost | ~$10–20/mo | ~$7–15/mo |

---

## Step 1 — Install flyctl

```bash
# macOS
brew install flyctl

# Windows (PowerShell)
iwr https://fly.io/install.ps1 -useb | iex

# Linux
curl -L https://fly.io/install.sh | sh
```

Then sign up / log in:
```bash
fly auth signup   # new account
# or
fly auth login    # existing account
```

---

## Step 2 — Create the Fly app

From the `backend/` directory:

```bash
cd lmsoftware/backend

# This registers the app name on Fly — does NOT deploy yet
fly apps create inspectpro-backend
```

If `inspectpro-backend` is taken, choose any name and update `fly.toml` accordingly.

---

## Step 3 — Create the Postgres database in London

```bash
fly postgres create \
  --name inspectpro-db \
  --region lhr \
  --initial-cluster-size 1 \
  --vm-size shared-cpu-1x \
  --volume-size 10
```

This creates a managed Postgres instance in London and gives you a connection string.
**Save the credentials it prints — you'll need them.**

Attach it to your app (auto-sets DATABASE_URL):
```bash
fly postgres attach inspectpro-db --app inspectpro-backend
```

---

## Step 4 — Migrate your data from Railway

1. **Export from Railway** (in Railway dashboard → your Postgres service → Data tab → Export):
   - Or via CLI: `pg_dump $RAILWAY_DB_URL > inspectpro_backup.sql`

2. **Import to Fly Postgres**:
```bash
# Get a proxy to the Fly DB
fly proxy 5433:5432 --app inspectpro-db &

# Import the dump
psql postgres://postgres:<password>@localhost:5433/inspectpro_backend < inspectpro_backup.sql
```

---

## Step 5 — Set environment variables

```bash
fly secrets set \
  JWT_SECRET_KEY="your-secret-key-here" \
  ANTHROPIC_API_KEY="your-anthropic-key" \
  OPENAI_API_KEY="your-openai-key" \
  RESEND_API_KEY="your-resend-key" \
  CORS_ORIGINS="https://app.lminventories.co.uk" \
  RAILWAY_PUBLIC_DOMAIN="inspectpro-backend.fly.dev" \
  --app inspectpro-backend
```

(DATABASE_URL is already set by the `fly postgres attach` step above.)

---

## Step 6 — Deploy

```bash
fly deploy --app inspectpro-backend
```

First deploy takes ~3 minutes (building the Docker image). Subsequent deploys are faster.

Check it's running:
```bash
fly status --app inspectpro-backend
fly logs --app inspectpro-backend
```

Test the health endpoint:
```bash
curl https://inspectpro-backend.fly.dev/health
# Should return: {"status": "ok"}
```

---

## Step 7 — Update the frontend API URL

In Railway (or wherever your Vue frontend is hosted), update the environment variable:

```
VITE_API_URL=https://inspectpro-backend.fly.dev
```

Redeploy the frontend.

---

## Step 8 — Point your custom domain (optional)

If you want `api.lminventories.co.uk` instead of `inspectpro-backend.fly.dev`:

```bash
fly certs add api.lminventories.co.uk --app inspectpro-backend
```

Follow the DNS instructions it gives you. Fly handles SSL automatically.

---

## Rollback plan

Railway stays running until you explicitly remove it. If anything goes wrong:
1. Revert `VITE_API_URL` on the frontend to the Railway URL
2. Redeploy frontend
3. You're back to Railway instantly

---

## Ongoing management

```bash
fly status          # see machine status
fly logs            # tail live logs  
fly ssh console     # SSH into the container
fly scale count 2   # run 2 machines for redundancy
```

Scale memory if large photo syncs cause OOM:
```bash
fly scale memory 1024 --app inspectpro-backend
```
