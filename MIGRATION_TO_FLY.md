# Migrate InspectPro to Fly.io (London)

Moving from Railway US → Fly.io London reduces API latency from ~130ms to ~5ms per round trip
for UK users. No cold starts. Cheaper than Railway.

Total time: about 1–2 hours.

---

## Why Fly.io London

| | Railway (current) | Fly.io London |
|---|---|---|
| Server location | US Central (GCP) | London Heathrow (LHR) |
| Round-trip from UK | ~130ms per request | ~5ms per request |
| Cold starts | Yes (on lower plans) | No (`min_machines_running = 1`) |
| Cost | ~$10–20/mo | ~$6–10/mo |

> **Photos are already in Cloudflare R2** — the database no longer contains base64 images so
> the pg_dump will be small (a few MB) and the import will be fast.

---

## Step 1 — Install flyctl

```powershell
# Windows (PowerShell)
iwr https://fly.io/install.ps1 -useb | iex
```

Then sign up / log in:
```bash
fly auth signup   # new account
fly auth login    # existing account
```

---

## Step 2 — Create the Fly app

From the backend directory:

```bash
cd C:\Projects\lmsoftware\lmsoftware\backend

fly apps create inspectpro-backend
```

If `inspectpro-backend` is taken, choose any name and update `app` in `fly.toml` to match.

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

**Save the credentials it prints — you only see the password once.**

Attach it to your app (automatically sets DATABASE_URL):
```bash
fly postgres attach inspectpro-db --app inspectpro-backend
```

---

## Step 4 — Migrate your data from Railway

**Export from Railway:**
```bash
pg_dump "postgresql+psycopg://postgres:POubnHVCnHbrtAKXXozcXCwQcQNxtnVl@gondola.proxy.rlwy.net:32664/railway" \
  --no-owner --no-acl -f inspectpro_backup.sql
```

Or use Railway dashboard → your Postgres service → Data tab → Export.

**Import into Fly Postgres:**
```bash
# Open a proxy to the Fly DB (runs in background)
fly proxy 5433:5432 --app inspectpro-db &

# Import the dump (replace <password> with what was printed in Step 3)
psql "postgres://postgres:<password>@localhost:5433/railway" < inspectpro_backup.sql
```

---

## Step 5 — Set environment variables

Copy these from your Railway backend service Variables tab and paste in your values:

```bash
fly secrets set \
  JWT_SECRET_KEY="lmsoftwareappdelpoyment" \
  OPENAI_API_KEY="your-openai-key" \
  ANTHROPIC_API_KEY="your-anthropic-key" \
  RESEND_API_KEY="your-resend-key" \
  CORS_ORIGINS="https://app.lminventories.co.uk" \
  APP_BASE_URL="https://app.lminventories.co.uk" \
  IDEALPOSTCODES_API_KEY="your-idealpostcodes-key" \
  RAILWAY_PUBLIC_DOMAIN="inspectpro-backend.fly.dev" \
  AWS_ACCESS_KEY_ID="5dde15529960c2cecb99443a8ee1de90" \
  AWS_SECRET_ACCESS_KEY="b56b0610b6220b37829d5c12199ae48121ae0ee69359db8e81a5daed189d1a16" \
  S3_BUCKET_NAME="inspectpro-photos" \
  S3_ENDPOINT_URL="https://f76077e4f8b1c27223deb9e1f703bbc7.r2.cloudflarestorage.com" \
  S3_PUBLIC_BASE_URL="https://pub-ba12a4933200471992f9b33f4c20ddff.r2.dev" \
  --app inspectpro-backend
```

> `DATABASE_URL` is set automatically by the `fly postgres attach` step — do not set it manually.
>
> `RAILWAY_PUBLIC_DOMAIN` controls the keep-alive ping scheduler. Setting it to your Fly app
> URL keeps the /health endpoint pinged every 8 minutes, which is harmless on Fly since
> there are no cold starts anyway.

---

## Step 6 — Deploy

```bash
cd C:\Projects\lmsoftware\lmsoftware\backend
fly deploy --app inspectpro-backend
```

First deploy takes ~3 minutes (building the Docker image). Subsequent deploys are ~60 seconds.

Check it's healthy:
```bash
fly status --app inspectpro-backend
fly logs --app inspectpro-backend
```

Test the health endpoint:
```bash
curl https://inspectpro-backend.fly.dev/health
# {"status": "ok"}
```

---

## Step 7 — Update the frontend API URL

In Railway (where your Vue frontend is deployed), update the environment variable:

```
EXPO_PUBLIC_API_URL=https://inspectpro-backend.fly.dev
```

And for the web frontend:
```
VITE_API_URL=https://inspectpro-backend.fly.dev
```

Redeploy the frontend after saving.

---

## Step 8 — Update the mobile app API URL (if hardcoded)

In `inspectpro-mobile-new/src/services/api.ts`, `BASE_URL` falls back to the Railway URL
if `EXPO_PUBLIC_API_URL` is not set. For a production mobile build, set this EAS secret:

```bash
eas secret:create --scope project --name EXPO_PUBLIC_API_URL \
  --value https://inspectpro-backend.fly.dev
```

Or update the fallback in `api.ts` directly:
```typescript
const BASE_URL = process.env.EXPO_PUBLIC_API_URL || 'https://inspectpro-backend.fly.dev'
```

---

## Step 9 — Point your custom domain (optional)

If you want `api.lminventories.co.uk` instead of `inspectpro-backend.fly.dev`:

```bash
fly certs add api.lminventories.co.uk --app inspectpro-backend
```

Fly prints the DNS record to add. It handles SSL automatically via Let's Encrypt.

---

## Rollback plan

Railway keeps running until you explicitly remove it. If anything goes wrong:

1. Revert `VITE_API_URL` on the frontend back to the Railway URL
2. Redeploy the frontend
3. You're back to Railway in under 2 minutes

---

## Ongoing management

```bash
fly status --app inspectpro-backend     # machine status
fly logs --app inspectpro-backend       # tail live logs
fly ssh console --app inspectpro-backend  # shell into the container
fly deploy --app inspectpro-backend     # redeploy after a push
```

Scale up if needed (e.g. large PDF generation causing memory pressure):
```bash
fly scale memory 1024 --app inspectpro-backend
fly scale count 2 --app inspectpro-backend   # two machines for redundancy
```
