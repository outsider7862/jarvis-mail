# Jarvis Mail

AI email assistant for service businesses (agencies, contractors, consultants).
Connects Gmail/Outlook, classifies every incoming email (business lead, invoice,
meeting, customer support, newsletter, spam, phishing, other), and surfaces what
actually needs attention — via a web dashboard now, an Android app later.

Got an idea or found a bug? Add it to [`FEATURES.md`](./FEATURES.md) rather than
mentioning it in passing — that's the shared backlog for this project.

## Architecture decision (merged from LeadPilot + the Jarvis Mail spec)

- **Delivery + storage: hosted, not desktop.** Postgres + a FastAPI backend, not
  SQLite + a desktop UI framework. This was the right call once an Android release
  was on the table — a local-only desktop app would mean rebuilding the backend
  again for mobile. One hosted API now serves both the web dashboard and, later,
  the Android app, with no backend rework needed to add the second client.
- **Scope: broadened from lead-only to full classification**, per the Jarvis Mail
  spec — every email gets a category, priority, summary, action item, and deadline,
  not just leads. Business-lead detection is now one category among seven, with its
  own extended detail table (`leads`) for the fields specific to a sales inquiry.

## What's built so far

- FastAPI backend, async SQLAlchemy models: `User`, `ConnectedAccount`, `RawEmail`,
  `EmailAnalysis` (the core classification record), `Lead` (extended detail, only
  created when `is_business_lead` is true)
- **Auth for your own users** — Supabase Auth. The dashboard/Android app logs
  in against Supabase directly and sends the session JWT as `Authorization:
  Bearer <token>`; this API verifies it and resolves/creates the local `User` row.
  All `/api/leads` and `/api/analyses` endpoints now require this — no more
  trusting a client-supplied `user_id`, and lookups are scoped to the
  authenticated user's own records (404, not 403, on someone else's data, so
  existence isn't leaked)
- Composio integration: connect Gmail/Outlook, create real-time webhook triggers,
  verify webhook signatures
- Light prefilter — only drops true mail-system noise (bounces, read receipts)
- OpenAI classification service using the Responses API + a broadened structured
  schema (`EmailAnalysisExtraction`) covering all 7 categories plus lead detail
- Webhook pipeline: email arrives -> light filter -> classify -> store analysis
  (+ lead detail if applicable) -> flag for notification if high priority / lead /
  meeting / phishing
- API: list/search analyses (by category, priority, sender, keyword), update
  status (read/actioned/dismissed), morning brief aggregation, pending
  notifications feed, leads list + confirm/reject
- Test suite (24 tests) covering prefilter, schemas, webhook signature, model
  relationships, extraction service logic, and JWT verification — all isolated
  from real API keys/DB. CI runs this on every push/PR.

## Not built yet

- Web dashboard frontend
- Android app (backend is ready for it — same JSON API, no rework needed)
- Deployment config
- Real push notifications (currently a pollable "pending notifications" endpoint)
- Background job queue — processing currently runs inline via FastAPI
  `BackgroundTasks`, fine for pilot volume, swap for Celery/arq before real scale

## Setup

### 1. Prerequisites
- Python 3.11+
- A Postgres database (Supabase free tier is the fastest way to get one)
- A Composio account + API key (composio.dev)
- An OpenAI API key

### 2. Install (Windows / PowerShell)

```powershell
cd jarvis_mail
py -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# fill in .env with real DATABASE_URL, COMPOSIO_API_KEY, OPENAI_API_KEY
py scripts\init_db.py
uvicorn app.main:app --reload
```

(macOS/Linux: `python3 -m venv venv`, `source venv/bin/activate`, same rest.)

Visit http://localhost:8000/docs for interactive API docs.

### 3. Run the tests

Everything except `extraction.py` and `composio_client.py` (which call real
external APIs) is unit-tested in isolation — no database, no real API keys
needed. `tests/conftest.py` sets placeholder env vars automatically.

```powershell
pip install -r requirements-dev.txt
pytest -v
```

CI runs this automatically on every push/PR via `.github/workflows/tests.yml`.

### 4. Connect a Gmail/Outlook account and create a trigger

One-time setup per connected inbox — see `app/services/composio_client.py` for
`start_gmail_connection()` / `start_outlook_connection()` and
`create_new_email_trigger()`. For local testing, expose your webhook with ngrok
and set that URL as your Composio webhook endpoint.

## Important notes

- **Real-time vs polling triggers**: use webhook-delivered triggers, not polling —
  Composio now enforces a 15-minute minimum interval on polling triggers, too slow
  for "new lead just landed."
- **Nothing auto-confirms.** Every lead lands as `status=pending`; every analysis
  lands as `status=new`. The dashboard is where a human reviews these — don't wire
  anything downstream (auto-replies, auto-emailing a client) to unreviewed items.
- **Phishing flag is a heuristic aid, not a security product.** It tells the user
  "look closer at this one," it should never be the sole thing standing between a
  user and a real phishing email. Say this explicitly in the UI copy when you build
  the dashboard.
- **Cost control**: the LLM now runs on nearly everything (see prefilter.py for
  why). Watch OpenAI spend once you're past a handful of pilot inboxes — consider
  a cheaper/faster model for the classification pass if volume grows.
