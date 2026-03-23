# InspectPro — Project Context & Developer Handoff

> **For AI coding assistants.** Read this before making any changes.
> Last updated: March 2026

---

## 1. What Is InspectPro?

InspectPro is a SaaS platform for property inspection companies. It manages the full lifecycle of a property inspection: from job creation and assignment through to report completion, typist transcription, PDF generation, and client delivery.

The platform has three layers:
- **Web app** — admin/manager/clerk interface built in Vue.js
- **Backend API** — Flask/PostgreSQL REST API
- **Mobile app** — React Native/Expo companion for inspectors in the field

The product was previously branded "LM Inventories". Rebranding to InspectPro is in progress — some legacy references remain in URLs and variable names.

---

## 2. Tech Stack

### Backend
- **Framework:** Flask (Python), app factory pattern (`create_app()`)
- **Database:** PostgreSQL in production, accessed via SQLAlchemy
- **ORM:** SQLAlchemy with `psycopg[binary]` (v3) driver
- **Auth:** JWT via `flask-jwt-extended`
- **AI:** OpenAI Whisper (`whisper-1`) for transcription, Anthropic Claude (`claude-haiku-4-5`) for report filling, Claude Opus for photo classification
- **Email:** SMTP via `email_service.py` with fully inline table-based HTML (Outlook-compatible)
- **PDF:** ReportLab for server-side auto-generation
- **Deployment:** Render (free tier — cold starts expected; `DATABASE_URL` env var is critical)
- **Connection string format:** `postgresql+psycopg://` (not `postgresql://`)

### Frontend (Web)
- **Framework:** Vue.js 3 with Composition API (`<script setup>`)
- **Build tool:** Vite
- **HTTP:** Axios via `src/services/api.js`
- **Routing:** Vue Router, all desktop routes wrapped as children of `MainLayout`
- **Deployment:** Vercel
- **URL:** `https://app.lminventories.co.uk`

### Mobile
- **Framework:** React Native with Expo SDK 55
- **React Native version:** 0.83.2
- **React version:** 19.2.0
- **Navigation:** React Navigation v7 (Stack)
- **State:** Zustand v5 (global store), SQLite via `expo-sqlite` v15 (local persistence)
- **Audio:** `expo-audio` v55
- **Camera:** `expo-camera` v55 + `expo-media-library` v55
- **HTTP:** Axios
- **Build:** EAS Build (managed workflow)
- **Dev testing:** Expo Go (SDK 55)
- **Project path:** `C:\Projects\lmsoftware\inspectpro-mobile-new`

---

## 3. Repository & Deployment

| Layer | Repo/Source | Deployed At |
|---|---|---|
| Backend | `backend/` in monorepo | `https://lmsoftware.onrender.com` |
| Frontend | `frontend/` in monorepo | `https://app.lminventories.co.uk` |
| Mobile | Separate project, own git repo | EAS builds at expo.dev |

**Backend deploy:** `git push` to main → Render auto-deploys.
**Frontend deploy:** `git push` to main → Vercel auto-deploys.
**Mobile deploy:** `eas build --platform android --profile preview --clear-cache` → APK download link.

Critical env vars on Render:
- `DATABASE_URL` — PostgreSQL connection string (must be set or app falls back to ephemeral SQLite)
- `OPENAI_API_KEY` — Whisper transcription
- `ANTHROPIC_API_KEY` — Claude report fill + photo classification
- `JWT_SECRET_KEY`
- `SMTP_*` — email credentials

---

## 4. Domain Model

### User Roles
Four roles with distinct permissions:
- `admin` — full access to everything
- `manager` — manage inspections, clients, properties, users
- `clerk` — conduct inspections in the field (mobile app primary user)
- `typist` — transcribe completed inspection audio into report fields

### Typist Tiers
Stored on the User model as `typist_tier`:
- `human` — a real person does the typing
- `ai_instant` — AI transcribes item-by-item as the clerk records (per-item mic)
- `ai_processing` — AI processes a continuous full-room recording at sync time

`is_ai` boolean is kept in sync with `typist_tier` for backwards compatibility.

### Inspection Lifecycle
```
created → assigned → active → processing → review → complete
```
- **active** — clerk is in the field completing the report
- **processing** — typist (human or AI) fills description/condition fields from audio
- **review** — manager reviews completed report before marking complete
- **complete** — report finalised, PDF auto-generated and emailed

### Report Data Structure
Report content is stored as a JSON blob (`report_data`) on the Inspection model:

```json
{
  "<sectionKey>": {
    "<itemId>": {
      "description": "...",
      "condition": "...",
      "_photos": ["data:image/jpeg;base64,..."],
      "_subs": [{ "_sid": "...", "name": "...", "description": "...", "condition": "..." }]
    },
    "_overviewPhotos": ["data:image/jpeg;base64,..."],
    "_extra": [{ "_eid": "...", "name": "..." }]
  },
  "_roomOrder": ["42", "37", "51"],
  "_roomNames": { "42": "Master Bedroom", "37": "Kitchen/Diner" },
  "_customRooms": [{ "key": "custom_1234", "name": "Garage" }],
  "_recordings": [{ "id": "...", "audioB64": "...", "mimeType": "audio/m4a", "duration": 45, "createdAt": "...", "label": "...", "itemKey": "..." }]
}
```

**Section keys:**
- Template rooms: `String(section.id)` e.g. `"42"`
- Fixed sections: `fs_{secIdx}_{name_slug}` e.g. `"fs_0_keys"`
- Custom rooms: `custom_{timestamp}` e.g. `"custom_1711234567890"`
- Overview photos key: `_overviewPhotos` is at section level (not item level)
- AI photo reassign key: `_overviewPhotos` is reserved item key for the overview gallery

### Fixed Sections
System-wide sections present in every inspection regardless of template:
`keys`, `meter_readings`, `condition_summary`, `cleaning_summary`, `fire_door_safety`, `health_safety`, `smoke_alarms`

---

## 5. Architecture Patterns

### Backend
- **App factory:** `create_app()` in `app.py`, blueprints registered per feature area
- **Blueprint naming:** `routes/inspections.py` → `inspections_bp`, registered at `/api/inspections`
- **Permissions:** `permissions.py` module with role-based filtering functions
- **Email:** Always wrapped in `try/except` — email failures must never break API responses
- **Migrations:** No Alembic; schema changes done via raw SQL `ALTER TABLE` in `create_tables()`, safe to run repeatedly

### Frontend (Web)
- **API calls:** All via `src/services/api.js` Axios instance with JWT interceptor
- **Layout:** All desktop routes are children of `MainLayout` — hardcoded nav in `App.vue` bypasses layout
- **Reactive data:** Composition API `ref`/`computed` throughout
- **Report editing:** `EditReportView.vue` — complex state, `report_data` loaded/saved as JSON

### Mobile
- **Navigation:** React Navigation v7 Stack. All screens in `RootStackParamList` in `App.tsx`
- **⚠️ Navigation params:** Never pass functions as navigation params — React Navigation serialises params and functions break the stack. Use module-level stores instead (see `cameraStore.ts`)
- **Global state:** Zustand v5 stores in `src/stores/`
  - `authStore` — JWT token, user object
  - `inspectionStore` — active inspection, `report_data`, `setReportData()`
- **Local persistence:** SQLite via `expo-sqlite` v15 synchronous API (`openDatabaseSync`, `db.runSync`, `db.getAllSync`, `db.getFirstSync`)
- **Audio:** `expo-audio` v55 — `useAudioRecorder(preset)` hook, `record()` is synchronous (not async), `recorder.uri` is populated after `await recorder.stop()` resolves
- **Camera:** `expo-camera` v55 `CameraView` + `expo-media-library` v55. Photos saved to "InspectPro" gallery album AND to `documentDirectory`. Base64 read after copy.
- **Camera communication pattern:** `cameraStore.ts` module — `setCameraTarget(handler)` before navigating, `processPendingPhotos()` in `useFocusEffect` on return

---

## 6. Key Files Reference

### Backend
| File | Purpose |
|---|---|
| `app.py` | App factory, blueprint registration |
| `models.py` | SQLAlchemy models (User, Inspection, Property, Client, Template, Section, Item, SectionPreset, TranscriptionUsage) |
| `routes/inspections.py` | Inspection CRUD, status transitions, sync endpoint |
| `routes/transcribe.py` | Whisper transcription + Claude report fill + photo classification |
| `routes/templates.py` | Template/section/item CRUD with reorder normalisation |
| `routes/section_presets.py` | Section preset library CRUD |
| `routes/permissions.py` | Role-based access control helpers |
| `routes/email_notifications.py` | Transactional emails (welcome, typist assignment, etc.) |
| `pdf_generator.py` | ReportLab server-side PDF generation |

### Frontend (Web)
| File | Purpose |
|---|---|
| `src/services/api.js` | Axios instance, all API calls |
| `src/views/InspectionsView.vue` | Inspection list with custom multi-select dropdowns, calendar view |
| `src/views/EditReportView.vue` | Main report editing UI — loads `report_data`, sends audio to AI |
| `src/views/TemplateEditorView.vue` | Template section/item editor with drag reorder and preset save/overwrite/delete |
| `src/views/TemplatesSettings.vue` | Template list |
| `src/views/UsersView.vue` | User management with typist tier radio picker |
| `src/components/settings/TemplatePreviewModal.vue` | Template preview |

### Mobile
| File | Purpose |
|---|---|
| `App.tsx` | Navigation stack, `RootStackParamList` type |
| `src/services/api.ts` | Axios instance, all API calls including transcription |
| `src/services/database.ts` | SQLite v15 synchronous API wrapper |
| `src/services/cameraStore.ts` | Module-level store for camera→screen photo handoff |
| `src/stores/authStore.ts` | Zustand auth store |
| `src/stores/inspectionStore.ts` | Zustand inspection/report_data store |
| `src/screens/RoomInspectionScreen.tsx` | Per-item recording, AI transcription, photos, sub-items |
| `src/screens/RoomSelectionScreen.tsx` | Room list with reorder, rename, add from preset |
| `src/screens/CameraScreen.tsx` | Full-screen camera with gallery save |
| `src/screens/ItemGalleryScreen.tsx` | Photo gallery with lightbox, rotate, delete, AI reassign |
| `src/screens/SyncScreen.tsx` | Inspection sync back to server |
| `src/components/HumanTypistRecorder.tsx` | Persistent audio bar for human typist mode |
| `src/components/AudioRecorderWidget.tsx` | Per-item audio recorder for AI typist mode |
| `src/hooks/useAudioRecorder.ts` | expo-audio wrapper hook |

---

## 7. API Endpoint Reference

### Auth
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/forgot-password`

### Inspections
- `GET /api/inspections` — list (filtered by role)
- `GET /api/inspections/<id>` — detail with nested property/client/typist/inspector
- `PUT /api/inspections/<id>` — update (includes status transition + email triggers)
- `POST /api/inspections/<id>/sync` — mobile sync endpoint (accepts full `report_data`)

### Templates
- `GET /api/templates/<id>`
- `POST /api/templates/<id>/sections/<sid>/reorder`
- `POST /api/templates/<id>/sections/<sid>/items/<iid>/reorder`

### Fixed Sections
- `GET /api/fixed-sections`

### Section Presets
- `GET /api/section-presets`
- `POST /api/section-presets/from-section/<section_id>`
- `POST /api/section-presets/<id>/add-to-template/<template_id>`
- `PUT /api/section-presets/<id>`
- `DELETE /api/section-presets/<id>`

### Transcription
- `POST /api/transcribe/item` — Whisper + Claude per-item fill
- `POST /api/transcribe/classify-photo` — Claude vision photo → item classification
- `GET /api/transcribe/status` — check API key configuration
- `GET /api/transcribe/usage` — cost/usage stats

---

## 8. Inspection Workflow (Mobile)

```
Login → Fetch Inspections → Select → Download
  → RoomSelection → RoomInspection (per room)
    → Take photos (CameraScreen)
    → Record audio (AudioRecorderWidget or HumanTypistRecorder)
    → AI transcription fires automatically (AI typist mode)
  → SyncScreen → POST /api/inspections/<id>/sync
    → Status: active → processing (human typist) or review (AI instant typist)
```

**AI typist detection (mobile):**
```typescript
const typistIsAi = inspection.typist_is_ai === true
                || inspection.typist?.is_ai === true
                || typistName === 'ai typist'
                || typistName.startsWith('ai ')
const aiMode = typistIsAi || typistMode === 'ai_instant' || typistMode === 'ai_processing'
```

---

## 9. Naming Conventions

### Backend (Python)
- Snake_case everywhere: `inspection_id`, `report_data`, `typist_is_ai`
- Blueprint variables: `{feature}_bp`
- Model classes: PascalCase (`User`, `Inspection`, `SectionPreset`)
- Route functions: snake_case verbs (`get_inspection`, `update_inspection`)

### Frontend (Vue)
- Components: PascalCase files (`InspectionsView.vue`, `TemplateEditorView.vue`)
- Composable refs: camelCase (`showAddModal`, `selectedItems`)
- API calls: camelCase methods in `api.js` (`getInspections`, `updateInspection`)
- CSS classes: kebab-case (`.modal-overlay`, `.btn-primary`)

### Mobile (React Native / TypeScript)
- Screen files: PascalCase + `Screen` suffix (`RoomInspectionScreen.tsx`)
- Component files: PascalCase (`AudioRecorderWidget.tsx`)
- Store files: camelCase + `Store` suffix (`authStore.ts`, `cameraStore.ts`)
- Hooks: `use` prefix (`useAudioRecorder.ts`)
- Navigation route names: PascalCase matching screen name without `Screen` (`RoomInspection`, `ItemGallery`)
- SQLite columns: snake_case (`inspection_id`, `section_key`, `file_uri`)
- `report_data` keys: snake_case for items/sections, `_camelCase` prefix for metadata (`_photos`, `_overviewPhotos`, `_roomOrder`, `_recordings`)

---

## 10. Known Gotchas & Hard-Won Lessons

### Backend
- `DATABASE_URL` must be explicitly set on Render — without it, app silently uses ephemeral SQLite and all data is lost on redeploy
- Email calls must always be in `try/except` — never let email failure break an API response
- Template reorder: always normalise `order_index` before swapping — legacy data may have duplicate indices (all zero)
- `psycopg[binary]` v3 required for Python 3.14 compatibility; connection string must use `postgresql+psycopg://`

### Frontend (Web)
- All routes must be children of `MainLayout` — top-level routes bypass the nav sidebar
- `report_data` mutation order matters: capture any values needed by restore functions *before* deletion/reassignment steps
- FullCalendar custom toolbar: `headerToolbar: false` then build your own — the built-in toolbar is hard to customise

### Mobile
- **Never pass functions as React Navigation params** — use `cameraStore.ts` or similar module-level store instead
- `expo-sqlite` v15 is fully synchronous: `openDatabaseSync`, `db.runSync`, `db.getAllSync` — no callbacks or Promises
- `expo-audio` v55: `recorder.record()` is `void` (not async) — do not `await` it. `recorder.uri` is populated *after* `await recorder.stop()` resolves, not before
- Audio URI may take up to 1 second after `stop()` before being available — poll with 100ms intervals if needed
- Always copy files from Expo cache to `FileSystem.documentDirectory` immediately — the cache is unreliable across app restarts
- `useAudioRecorder(preset)` — pass preset at hook construction time, not to `prepareToRecordAsync`
- Zustand v4 is incompatible with React 19 — must use v5
- `expo-sqlite` v15 replaces `openDatabase` + `transaction` + `executeSql` pattern entirely
- SQLite race conditions: always read fresh from SQLite before writes to prevent stale state overwrites

---

## 11. Current State (March 2026)

### Working
- Web app: full inspection management, template editor, PDF export, email notifications
- Mobile: login, fetch/download inspections, room navigation, photos (via CameraScreen with gallery save), room reorder/rename, sync back to server, AI photo reassignment (parallel), item gallery
- AI typist: banner detection working; transcription wiring in progress
- Human typist: audio recording bar (`HumanTypistRecorder`) with per-clip playback and sync

### In Progress / Known Issues
- **AI typist transcription:** Banner shows correctly but `onRecordingComplete` callback from `AudioRecorderWidget` may not be receiving a valid URI from `stopRecording()`. Debug logging added — check adb logcat for `[AI Typist]` and `[useAudioRecorder]` prefixes
- **Camera 0.6× ultrawide:** `zoom: 0` on `CameraView` does not reliably switch to the ultrawide lens — device-dependent behaviour. True lens switching requires `getAvailableLensesAsync` (not yet implemented)

### Pending / Next Tasks
- AI typist: confirm URI is reaching `transcribeItem` and API call is succeeding (adb logcat test needed)
- Client portal frontend (backend email trigger exists, frontend login not yet built)
- Railway migration from Render (backend only; keep Vercel for frontend)
- EAS Update integration for JS-only patches without full rebuild
- Page load performance on Edit Report (Render cold start; may resolve on Railway)

---

## 12. File Structure

> `node_modules`, `.git`, and `__pycache__` omitted. The `android/` folder under `frontend/` is a legacy Capacitor wrapper and is not actively used.
> ⚠️ `CameraScreen.tsx` and `src/services/cameraStore.ts` are referenced in sections 5 and 6 but are **not present** in the current file system — they may have been deleted or not yet recreated.

```
lmsoftware/
├── package-lock.json
├── backend/
│   ├── app.py                            ← app factory, blueprint registration
│   ├── config.py
│   ├── models.py                         ← SQLAlchemy models
│   ├── permissions.py                    ← role-based access helpers
│   ├── email_notifications.py
│   ├── requirements.txt
│   ├── run.py
│   ├── runtime.txt
│   ├── init_db.py
│   ├── migrate.py
│   ├── migrate_photo_settings.py
│   ├── create_admin.py
│   ├── create_templates_tables.py
│   ├── reset_db.py
│   ├── test_import.py
│   ├── instance/
│   │   └── inventorybase.db              ← local dev SQLite (NOT used in prod)
│   ├── migrations/                       ← Alembic config (raw SQL used instead in practice)
│   │   ├── alembic.ini
│   │   ├── env.py
│   │   └── script.py.mako
│   └── routes/
│       ├── __init__.py
│       ├── actions.py
│       ├── address_lookup.py
│       ├── ai.py
│       ├── auth.py
│       ├── auth_reset.py
│       ├── clients.py
│       ├── dashboard.py
│       ├── email_notifications.py
│       ├── email_service.py
│       ├── fixed_sections.py
│       ├── inspections.py                ← inspection CRUD, status transitions, sync
│       ├── pdf_generator.py              ← ReportLab PDF generation
│       ├── pdf_import.py
│       ├── properties.py
│       ├── section_presets.py
│       ├── system_settings.py
│       ├── templates.py
│       ├── transcribe.py                 ← Whisper + Claude transcription + photo classify
│       └── users.py
├── frontend/                             ← Vue.js 3 web app
│   ├── index.html
│   ├── vite.config.js
│   ├── jsconfig.json
│   ├── vercel.json
│   ├── capacitor.config.json
│   ├── capacitor.config.ts
│   ├── package.json
│   ├── public/
│   │   ├── favicon.ico
│   │   └── ip-logo.png
│   ├── android/                          ← legacy Capacitor Android wrapper (not active)
│   └── src/
│       ├── App.vue
│       ├── AppSidebar.vue
│       ├── main.js
│       ├── config.js
│       ├── style.css
│       ├── assets/
│       │   ├── main.css
│       │   └── mobile.css
│       ├── components/
│       │   ├── CheckOutActionPicker.vue
│       │   ├── PdfExportModal.vue
│       │   ├── ToastContainer.vue
│       │   └── settings/
│       │       ├── ActionsSettings.vue
│       │       ├── EmailsSettings.vue
│       │       ├── GeneralSettings.vue
│       │       ├── ReportsSettings.vue
│       │       ├── TemplatePreviewModal.vue
│       │       ├── TemplatesSettings.vue
│       │       └── TranscriptionSettings.vue
│       ├── composables/
│       │   └── useToast.js
│       ├── layouts/
│       │   └── MainLayout.vue            ← all desktop routes must be children of this
│       ├── router/
│       │   ├── index.js
│       │   └── router_index.js
│       ├── services/
│       │   ├── api.js                    ← Axios instance, JWT interceptor, all API calls
│       │   ├── offline.js
│       │   └── sync.js
│       ├── stores/
│       │   ├── auth.js
│       │   └── counter.js
│       ├── views/
│       │   ├── ChangePasswordView.vue
│       │   ├── ClientsView.vue
│       │   ├── DashboardView.vue
│       │   ├── InspectionDetailView.vue
│       │   ├── InspectionReportView.vue
│       │   ├── InspectionsView.vue       ← inspection list, calendar view
│       │   ├── LoginView.vue
│       │   ├── PropertiesView.vue
│       │   ├── PropertyDetailView.vue
│       │   ├── ResetPasswordView.vue
│       │   ├── SettingsView.vue
│       │   ├── UsersView.vue
│       │   └── settings/
│       │       ├── FixedSectionsSettings.vue
│       │       ├── TemplateEditorView.vue    ← drag reorder, preset save/overwrite/delete
│       │       └── TemplatesView.vue
│       └── views-mobile/                 ← legacy Capacitor mobile views (superseded by inspectpro-mobile-new)
│           ├── MobileHome.vue
│           ├── MobileLogin.vue
│           ├── MobilePropertyView.vue
│           ├── MobileReportEditor.vue
│           └── MobileSectionTab.vue
└── inspectpro-mobile-new/                ← React Native / Expo mobile app (active)
    ├── App.tsx                           ← navigation stack, RootStackParamList
    ├── app.json
    ├── index.js
    ├── index.ts
    ├── tsconfig.json
    ├── package.json
    ├── assets/
    │   ├── icon.png
    │   ├── splash.png
    │   ├── splash-icon.png
    │   ├── adaptive-icon.png
    │   ├── favicon.png
    │   ├── android-icon-background.png
    │   ├── android-icon-foreground.png
    │   └── android-icon-monochrome.png
    └── src/
        ├── components/
        │   ├── AudioRecorderWidget.tsx   ← per-item recorder for AI typist mode
        │   ├── Header.tsx
        │   ├── HumanTypistRecorder.tsx   ← persistent audio bar for human typist mode
        │   ├── LocalBadge.tsx
        │   ├── StatusBadge.tsx
        │   └── SwipeableRow.tsx
        ├── hooks/
        │   └── useAudioRecorder.ts       ← expo-audio v55 wrapper
        ├── screens/
        │   ├── FetchInspectionsScreen.tsx
        │   ├── InspectionListScreen.tsx
        │   ├── ItemGalleryScreen.tsx     ← photo gallery, lightbox, rotate, delete, AI reassign
        │   ├── LoginScreen.tsx
        │   ├── PropertyOverviewScreen.tsx
        │   ├── RoomInspectionScreen.tsx  ← per-item recording, AI transcription, photos, sub-items
        │   ├── RoomSelectionScreen.tsx   ← room list with reorder, rename, add from preset
        │   └── SyncScreen.tsx            ← sync inspection back to server
        ├── services/
        │   ├── api.ts                    ← Axios instance, all API calls incl. transcription
        │   └── database.ts               ← SQLite v15 synchronous API wrapper
        ├── stores/
        │   ├── authStore.ts              ← Zustand: JWT token, user object
        │   └── inspectionStore.ts        ← Zustand: active inspection, report_data
        └── utils/
            └── theme.ts
```

---

## 13. Environment Setup

### Running Locally

**Backend:**
```bash
cd backend
pip install -r requirements.txt
flask run
```
Requires `.env` with `DATABASE_URL`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `JWT_SECRET_KEY`, `SMTP_*`

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```
Requires `.env.local` with `VITE_API_URL=http://localhost:5000`

**Mobile:**
```bash
cd inspectpro-mobile-new
npm install --legacy-peer-deps
npx expo start
```
Scan QR with Expo Go (SDK 55). API URL hardcoded in `src/services/api.ts` as `https://lmsoftware.onrender.com`

### Building Mobile APK
```bash
eas build --platform android --profile preview --clear-cache
```
Requires `eas.json`, valid EAS project ID in `app.json`, and EAS login.
