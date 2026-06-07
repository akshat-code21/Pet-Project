# 🏦 Hedge Fund Intelligence Platform

> AI-powered platform for monitoring hedge fund investors across SEC filings, websites, YouTube, and RSS feeds. Stop manually checking 10+ investor sources — get a synthesized intelligence briefing instead.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-blueviolet)](https://langchain-ai.github.io/langgraph/)
[![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?logo=supabase)](https://supabase.com)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python)](https://python.org)

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Tech Stack](#tech-stack)
3. [Project Structure](#project-structure)
4. [Quick Start](#quick-start)
5. [Environment Variables](#environment-variables)
6. [Running the Backend](#running-the-backend)
7. [API Endpoints Reference](#api-endpoints-reference)
8. [Testing All Endpoints](#testing-all-endpoints)
9. [Background Jobs](#background-jobs)
10. [Docs](#docs)

---

## What It Does

1. **Add investors** you want to track (e.g. Bill Ackman, David Einhorn)
2. **Attach sources** per investor — SEC EDGAR CIK, website URL, YouTube channel, RSS feed
3. **Background jobs** fetch new content on a schedule (SEC filings every 6h, YouTube every 6h, RSS every 2h, websites every 4h)
4. **AI pipeline** (LangGraph) processes each content item: cleans text → chunks → extracts entities/tickers/theses → generates embeddings → creates reports → scores alerts
5. **Reports** are generated per-investor (event-driven on new 13F) and as a daily digest at 07:00 UTC
6. **Alerts** are scored by severity; critical alerts trigger email via Resend
7. **Semantic search** across all ingested content via pgvector

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend API** | FastAPI 0.115 + Python 3.12 |
| **AI Agent** | LangGraph 0.2 + LangChain |
| **LLM** | OpenAI GPT-4o (reports) + GPT-4o-mini (extraction) |
| **Embeddings** | OpenAI `text-embedding-3-small` (1536 dims) |
| **Database** | Supabase PostgreSQL + pgvector |
| **ORM** | SQLAlchemy 2.0 async + Alembic |
| **Auth** | Supabase Auth (JWT) |
| **Scheduler** | APScheduler (AsyncIOScheduler) |
| **Email** | Resend |
| **Scraping** | httpx + trafilatura + Playwright (JS fallback) |
| **SEC Data** | EDGAR REST API (free) |
| **YouTube** | yt-dlp + `youtube-transcript-api` |
| **RSS** | LangChain RSSFeedLoader + feedparser |
| **Frontend** | Next.js 14 + shadcn/ui (Vercel) |

---

## Project Structure

```
Pet-Project/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app factory, CORS, lifespan, router registration
│   │   └── config.py        # Pydantic Settings (all env vars, type-validated)
│   ├── api/
│   │   ├── deps.py          # JWT auth dependency, get_session
│   │   ├── auth.py          # POST /signup, /login, /logout  GET /me
│   │   ├── investors.py     # CRUD + /sync trigger
│   │   ├── sources.py       # CRUD nested under /{investor_id}/sources
│   │   ├── content.py       # GET content items + portfolio changes per investor
│   │   ├── reports.py       # List, get, mark-read, generate reports
│   │   ├── alerts.py        # List, mark-read, mark-all-read alerts
│   │   ├── search.py        # POST semantic search via pgvector
│   │   └── admin.py         # Scheduler status + manual job trigger
│   ├── models/              # SQLAlchemy ORM (9 models matching DB schema)
│   ├── schemas/             # Pydantic request/response models (7 schema files)
│   ├── services/            # Business logic layer (investor, source, content, report, alert, email, vector)
│   ├── agents/
│   │   ├── pipeline.py      # LangGraph graph assembly (6 nodes)
│   │   ├── state.py         # PipelineState TypedDict
│   │   ├── nodes/           # normalizer, entity_extractor, thesis_extractor, embedder, report_generator, alert_checker
│   │   └── prompts/         # Prompt templates for entity/thesis/report generation
│   ├── ingestion/
│   │   ├── base_adapter.py  # Abstract BaseAdapter
│   │   ├── sec_adapter.py   # EDGAR 13F fetcher + XML parser
│   │   ├── loaders.py       # Website (4-tier), RSS, YouTube loaders
│   │   └── content_hasher.py # SHA-256 deduplication
│   ├── jobs/
│   │   ├── scheduler.py     # APScheduler setup (6 jobs)
│   │   ├── ingestion_job.py # Source ingestion orchestrator
│   │   ├── processing_job.py # LangGraph pipeline runner for pending items
│   │   └── digest_job.py    # Daily digest generator
│   ├── database/
│   │   ├── connection.py    # Async SQLAlchemy engine + session factory
│   │   ├── base.py          # Declarative base
│   │   └── migrations/      # Alembic migration files
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/                # Next.js 14 app (see docs/deployment.md)
├── docs/
│   ├── api.md               # Full API reference
│   ├── architecture.md      # Architecture decisions & data flow
│   └── deployment.md        # Railway + Vercel deployment guide
├── .env.example
└── IMPLEMENTATION_PLAN.md   # Detailed engineering spec
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- A [Supabase](https://supabase.com) project with `pgvector` extension enabled
- OpenAI API key
- Resend API key (for email alerts)

### 1. Clone and configure

```bash
git clone <repo-url>
cd Pet-Project
cp .env.example backend/.env
# Edit backend/.env and fill in all values (see Environment Variables below)
```

### 2. Install dependencies

```bash
cd backend
pip install -e ".[dev]"

# Install Playwright browser (for JS-heavy website scraping)
playwright install chromium
```

### 3. Run database migrations

```bash
cd backend
alembic upgrade head
```

### 4. Start the API

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API is live at `http://localhost:8000`  
Swagger UI: `http://localhost:8000/docs`

---

## Environment Variables

All variables are required unless marked optional.

| Variable | Description | Example |
|---|---|---|
| `SUPABASE_URL` | Supabase project URL | `https://xxxx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Supabase service role key (server-side only) | `eyJ...` |
| `SUPABASE_JWT_SECRET` | JWT secret from Supabase project settings | `super-secret` |
| `DATABASE_URL` | Supabase PostgreSQL connection string (asyncpg format) | `postgresql+asyncpg://postgres:pass@db.xxx.supabase.co:5432/postgres` |
| `OPENAI_API_KEY` | OpenAI API key for embeddings + LLM calls | `sk-...` |
| `RESEND_API_KEY` | Resend API key for email alerts | `re_...` |
| `FRONTEND_URL` | Frontend origin for CORS | `http://localhost:3000` |
| `APP_ENV` | `development` or `production` | `development` |
| `SCHEDULER_ENABLED` | Set `false` to disable background jobs (useful for testing) | `true` |

> **Note:** `YOUTUBE_API_KEY` is planned for Phase 2 YouTube channel discovery. The current implementation uses `yt-dlp` which requires no API key for channel listing.

---

## Running the Backend

```bash
# Development (with auto-reload)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Production (Railway uses this via Dockerfile)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

The app logs startup info via `structlog`:
```
INFO: Starting Hedge Fund Intelligence API  env=development
INFO: Scheduler started                     job_count=6
INFO: Application startup complete.
```

---

## API Endpoints Reference

Base URL: `http://localhost:8000/api/v1`  
Authentication: `Authorization: Bearer <supabase_jwt_token>`

### Health Check

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | ❌ | Returns `{"status": "ok"}` |

### Authentication

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/auth/signup` | ❌ | Register new user |
| `POST` | `/auth/login` | ❌ | Login, returns JWT tokens |
| `POST` | `/auth/logout` | ✅ | Invalidate session |
| `GET` | `/auth/me` | ✅ | Get current user profile |

### Investors

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/investors` | ✅ | List all tracked investors |
| `POST` | `/investors` | ✅ | Create new investor |
| `GET` | `/investors/{id}` | ✅ | Get investor details + stats |
| `PUT` | `/investors/{id}` | ✅ | Update investor |
| `DELETE` | `/investors/{id}` | ✅ | Delete investor (cascades) |
| `POST` | `/investors/{id}/sync` | ✅ | Trigger immediate sync for all sources |

### Sources

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/investors/{id}/sources` | ✅ | List sources for investor |
| `POST` | `/investors/{id}/sources` | ✅ | Add source to investor |
| `PUT` | `/investors/{id}/sources/{sid}` | ✅ | Update source (toggle active, frequency) |
| `DELETE` | `/investors/{id}/sources/{sid}` | ✅ | Remove source |

### Content

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/content/investors/{id}/content` | ✅ | List content items for investor |
| `GET` | `/content/investors/{id}/portfolio` | ✅ | Get 13F portfolio holdings/changes |

### Reports

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/reports` | ✅ | List reports (filterable) |
| `GET` | `/reports/{id}` | ✅ | Get full report with markdown |
| `PUT` | `/reports/{id}/read` | ✅ | Mark report as read |
| `POST` | `/reports/generate` | ✅ | Queue investor report generation |

### Alerts

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/alerts` | ✅ | List alerts (filterable by severity/investor) |
| `PUT` | `/alerts/{id}/read` | ✅ | Mark alert as read |
| `PUT` | `/alerts/read-all` | ✅ | Mark all alerts as read |

### Search

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/search` | ✅ | Semantic search across all ingested content |

### Admin

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/jobs/status` | ✅ | Scheduler status + pending item count |
| `POST` | `/admin/jobs/trigger` | ✅ | Manually trigger a scheduled job |

---

## Testing All Endpoints

> Replace `TOKEN` with your JWT from `/auth/login`. Replace UUIDs with actual IDs from your responses.

### Step 1 — Health check

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### Step 2 — Sign Up

```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "SecurePass123!",
    "full_name": "Test User"
  }'
```

### Step 3 — Login

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "SecurePass123!"
  }'
# Save the access_token from the response
export TOKEN="<access_token_here>"
```

### Step 4 — Get Current User

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

### Step 5 — Create an Investor

```bash
curl -X POST http://localhost:8000/api/v1/investors \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Bill Ackman",
    "description": "Pershing Square Capital Management",
    "cik_number": "0001336528"
  }'
# Save the returned investor id
export INVESTOR_ID="<investor_uuid>"
```

### Step 6 — List Investors

```bash
curl http://localhost:8000/api/v1/investors \
  -H "Authorization: Bearer $TOKEN"
```

### Step 7 — Get Investor Detail

```bash
curl http://localhost:8000/api/v1/investors/$INVESTOR_ID \
  -H "Authorization: Bearer $TOKEN"
```

### Step 8 — Update Investor

```bash
curl -X PUT http://localhost:8000/api/v1/investors/$INVESTOR_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description": "Pershing Square Capital Management - Updated"}'
```

### Step 9 — Add a Source (SEC 13F)

```bash
curl -X POST http://localhost:8000/api/v1/investors/$INVESTOR_ID/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "sec_13f",
    "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001336528&type=13F-HR",
    "label": "Ackman 13F Filings",
    "check_frequency_hours": 6,
    "config": {"cik_number": "0001336528"}
  }'
export SOURCE_ID="<source_uuid>"
```

### Step 10 — Add a YouTube Source

```bash
curl -X POST http://localhost:8000/api/v1/investors/$INVESTOR_ID/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "youtube",
    "url": "https://www.youtube.com/@PershingSquare",
    "label": "Pershing Square YouTube",
    "check_frequency_hours": 12
  }'
```

### Step 11 — Add an RSS Source

```bash
curl -X POST http://localhost:8000/api/v1/investors/$INVESTOR_ID/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "rss",
    "url": "https://acquirersmultiple.com/feed/",
    "label": "RSS Feed",
    "check_frequency_hours": 4
  }'
```

### Step 12 — List Sources for Investor

```bash
curl http://localhost:8000/api/v1/investors/$INVESTOR_ID/sources \
  -H "Authorization: Bearer $TOKEN"
```

### Step 13 — Update a Source

```bash
curl -X PUT http://localhost:8000/api/v1/investors/$INVESTOR_ID/sources/$SOURCE_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"is_active": true, "check_frequency_hours": 12}'
```

### Step 14 — Trigger Investor Sync

```bash
curl -X POST http://localhost:8000/api/v1/investors/$INVESTOR_ID/sync \
  -H "Authorization: Bearer $TOKEN"
# {"message":"sync queued","job_id":"<investor_uuid>"}
```

### Step 15 — List Content Items

```bash
curl "http://localhost:8000/api/v1/content/investors/$INVESTOR_ID/content?limit=20&offset=0" \
  -H "Authorization: Bearer $TOKEN"

# Filter by content type
curl "http://localhost:8000/api/v1/content/investors/$INVESTOR_ID/content?content_type=filing" \
  -H "Authorization: Bearer $TOKEN"
```

### Step 16 — Get Portfolio Changes (13F)

```bash
curl "http://localhost:8000/api/v1/content/investors/$INVESTOR_ID/portfolio" \
  -H "Authorization: Bearer $TOKEN"

# Filter by filing period
curl "http://localhost:8000/api/v1/content/investors/$INVESTOR_ID/portfolio?filing_period=2024-Q3" \
  -H "Authorization: Bearer $TOKEN"
```

### Step 17 — List Reports

```bash
# All reports
curl "http://localhost:8000/api/v1/reports?page=1&limit=20" \
  -H "Authorization: Bearer $TOKEN"

# Filter by investor
curl "http://localhost:8000/api/v1/reports?investor_id=$INVESTOR_ID&report_type=investor_report" \
  -H "Authorization: Bearer $TOKEN"

# Unread only
curl "http://localhost:8000/api/v1/reports?unread_only=true" \
  -H "Authorization: Bearer $TOKEN"
```

### Step 18 — Get a Specific Report

```bash
export REPORT_ID="<report_uuid>"
curl http://localhost:8000/api/v1/reports/$REPORT_ID \
  -H "Authorization: Bearer $TOKEN"
```

### Step 19 — Mark Report as Read

```bash
curl -X PUT http://localhost:8000/api/v1/reports/$REPORT_ID/read \
  -H "Authorization: Bearer $TOKEN"
```

### Step 20 — Generate a Report

```bash
curl -X POST http://localhost:8000/api/v1/reports/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"investor_id\": \"$INVESTOR_ID\", \"report_type\": \"investor_report\"}"
# HTTP 202 Accepted — report generation queued as background task
```

### Step 21 — List Alerts

```bash
# All alerts
curl "http://localhost:8000/api/v1/alerts?page=1&limit=20" \
  -H "Authorization: Bearer $TOKEN"

# Unread critical alerts only
curl "http://localhost:8000/api/v1/alerts?unread_only=true&severity=critical" \
  -H "Authorization: Bearer $TOKEN"

# By investor
curl "http://localhost:8000/api/v1/alerts?investor_id=$INVESTOR_ID" \
  -H "Authorization: Bearer $TOKEN"
```

### Step 22 — Mark Alert as Read

```bash
export ALERT_ID="<alert_uuid>"
curl -X PUT http://localhost:8000/api/v1/alerts/$ALERT_ID/read \
  -H "Authorization: Bearer $TOKEN"
```

### Step 23 — Mark All Alerts as Read

```bash
curl -X PUT http://localhost:8000/api/v1/alerts/read-all \
  -H "Authorization: Bearer $TOKEN"
```

### Step 24 — Semantic Search

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Ackman thesis on interest rates and real estate",
    "limit": 10
  }'

# Search within a specific investor
curl -X POST http://localhost:8000/api/v1/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"query\": \"high conviction technology positions\",
    \"investor_id\": \"$INVESTOR_ID\",
    \"limit\": 5
  }"
```

### Step 25 — Admin: Job Status

```bash
curl http://localhost:8000/api/v1/admin/jobs/status \
  -H "Authorization: Bearer $TOKEN"
```

### Step 26 — Admin: Trigger a Job

```bash
# Available job IDs: ingest_sec_13f, ingest_websites, ingest_rss, ingest_youtube, process_pending, daily_digest
curl -X POST http://localhost:8000/api/v1/admin/jobs/trigger \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"job": "process_pending"}'
```

### Step 27 — Logout

```bash
curl -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Authorization: Bearer $TOKEN"
```

### Step 28 — Delete Source

```bash
curl -X DELETE http://localhost:8000/api/v1/investors/$INVESTOR_ID/sources/$SOURCE_ID \
  -H "Authorization: Bearer $TOKEN"
# HTTP 204 No Content
```

### Step 29 — Delete Investor

```bash
curl -X DELETE http://localhost:8000/api/v1/investors/$INVESTOR_ID \
  -H "Authorization: Bearer $TOKEN"
# HTTP 204 No Content — cascades to sources, content_items, etc.
```

---

## Background Jobs

| Job ID | Schedule | Description |
|--------|----------|-------------|
| `ingest_sec_13f` | Daily at 06:00 UTC | Fetch new 13F filings from SEC EDGAR |
| `ingest_websites` | Every 4 hours | Scrape investor websites + newsletters |
| `ingest_rss` | Every 2 hours | Poll RSS/Atom feeds |
| `ingest_youtube` | Every 6 hours | Check for new YouTube videos + transcripts |
| `process_pending` | Every 5 minutes | Run LangGraph AI pipeline on pending content |
| `daily_digest` | Daily at 07:00 UTC | Generate daily digest reports for all users |

All jobs can be manually triggered via `POST /api/v1/admin/jobs/trigger`.

---

## Docs

- [`docs/api.md`](docs/api.md) — Complete API reference with all request/response schemas
- [`docs/architecture.md`](docs/architecture.md) — Architecture decisions, data flow, and component design
- [`docs/deployment.md`](docs/deployment.md) — Step-by-step Railway + Vercel deployment guide
- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — Full engineering specification

---

## Roadmap

- [x] Phase 1: Auth, investor CRUD, source management
- [x] Phase 2: SEC EDGAR, website, RSS, YouTube ingestion
- [x] Phase 3: LangGraph AI pipeline (entity/thesis extraction, embeddings)
- [x] Phase 4: Report generation, alerting, email delivery
- [ ] Phase 5: Frontend (Next.js) — in progress
- [ ] Phase 2 (future): Twitter/X monitoring, podcast processing, news aggregation
