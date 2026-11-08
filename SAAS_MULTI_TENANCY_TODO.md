# SaaS Multi-Tenancy — Backburnered To-Do

**Status:** Deferred. Your call this session was "put multi-tenant SaaS on the backburner for
now — get InspectPro fully ready first" (Sept 2026). This file exists so that decision and the
groundwork behind it aren't lost between sessions. Nothing below is scheduled — it's a
starting checklist for whenever you pick this back up.

## The core problem, confirmed directly in code (2026-09-09)

InspectPro's entire data model is single-tenant today — there is no concept of "which
business does this row belong to" anywhere in the schema:

- `backend/models.py` — `User`, `Client`, `Property`, `Inspection`, `InspectionActivity`,
  `InspectionSignature` (and every other model) have **no** `org_id` / `tenant_id` /
  `company_id` column. Grepped for all three naming conventions — zero hits.
- `backend/routes/auth.py` — the JWT issued at login carries no org/tenant claim either.
- `backend/models.py`'s `SystemSetting` table (used for all app-wide config, including every
  OAuth integration's tokens) has a **database-level unique constraint on `key`** — a single
  global key/value store, not one scoped per business.

In short: right now there is implicitly exactly one "business" using this whole app. Real
multi-tenant SaaS means every one of those tables needs an owner, every query needs to filter
by it, and every piece of app-wide config (Google/Microsoft/Dropbox/Slack tokens, company
branding, report settings, etc.) needs to become per-tenant instead of global.

*Note: an earlier investigation this session flagged a second concrete blocker beyond
`SystemSetting`'s key uniqueness, but the specifics weren't preserved in what carried forward
to this file — re-audit before starting rather than trusting this list is complete.*

## What's already been built that reduces the eventual lift

- **OAuth integrations (Google, Microsoft, Dropbox, Slack)** — added 2026-09-01/03. Token
  storage was deliberately factored through `backend/services/oauth_tokens.py`
  (`save_tokens(prefix, ...)` / `load_tokens(prefix, ...)` / `clear_tokens(prefix, ...)`)
  rather than hardcoding `SystemSetting` key names inline in each `routes/<platform>.py` file.
  When multi-tenancy is built, migrating these to per-org credentials should mean changing what
  `prefix` gets passed in (e.g. `f'org_{org_id}_microsoft'` instead of `'microsoft'`) plus the
  storage schema itself — not rewriting the `/auth` → `/callback` → refresh flow logic in each
  platform's route file, which stays as-is.
- **Zapier API-key groundwork** (`backend/routes/zapier.py`) — currently one global key. Same
  shape of change applies: scope the key to an org instead of being global.

## Rough shape of the actual migration (needs a real audit, not just this list)

1. **Add an `Organization`/`Company` model** and an `org_id` FK on every tenant-scoped table
   (`User`, `Client`, `Property`, `Inspection`, and everything hanging off them).
2. **JWT**: add an org claim, and audit every route for implicit "there's only one business"
   assumptions — especially anything that does `Model.query.all()` / `.first()` without a
   `filter_by` clause.
3. **`SystemSetting`**: either add `org_id` to the composite uniqueness (`UNIQUE(org_id, key)`
   instead of `UNIQUE(key)`), or split app-wide config into a genuinely per-org table. Decide
   this before touching the OAuth integration prefixes, since it determines what `prefix`
   should actually encode.
4. **File storage isolation** — check `backend/utils/s3.py` / R2 usage for whether object keys
   already namespace by anything that could double as an org boundary, or whether that needs
   adding too.
5. **Billing/subscription** — not investigated at all yet; a real backlog item once the above
   is decided, not before.
6. **Permissions** (`backend/permissions.py`) — role checks (`admin`/`manager`/`clerk`/
   `typist`/`client`) currently have no org dimension; every role check will need an implicit
   "and belongs to the same org" alongside the role check.

## Suggested first step when you resume this

Don't trust this file as exhaustive — it's a snapshot from one read-through of `models.py` and
`auth.py`, not a full audit. Re-run a proper Explore pass across `backend/routes/*.py` and
`backend/models.py` specifically hunting for every place that would break under more than one
tenant, before committing to a migration plan.
