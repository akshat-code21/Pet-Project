# IMPLEMENTATION PLAN
## AI-Powered Hedge Fund Intelligence Platform

**Version:** 1.0 — MVP  
**Prepared for:** Claude Code Execution  
**Architecture Philosophy:** Modular monolith. Ship fast. Add complexity only when earned.

---

## 1. MVP Definition

### What Is Included

- User authentication (sign up, sign in, sign out) via Supabase Auth
- Investor management (create, update, delete tracked investors)
- Source management per investor (SEC 13F, website/newsletter URL, YouTube channel, RSS feed)
- Automated content ingestion from 4 source types: SEC EDGAR, websites/newsletters (via scraping + RSS), and YouTube
- AI-powered content processing: entity extraction, ticker extraction, thesis identification, conviction scoring
- Automated investor reports (per-investor, event-driven on new 13F filing)
- Daily digest report aggregating all investor activity
- In-app alert feed with severity scoring
- Email alerts for high-importance events via Resend
- Frontend: Dashboard, Investors, Investor Detail, Reports, Alerts, Settings pages
- Semantic search across all ingested content via pgvector

### What Is Excluded (MVP)

- Twitter/X monitoring (API cost prohibitive at ~$100+/month minimum; deferred)
- Podcast processing (complex audio pipeline; deferred)
- Cross-investor theme comparison (valuable but not MVP-critical)
- Real-time WebSocket updates (polling is sufficient for MVP)
- Multi-user organizations / team accounts
- Portfolio reconstruction or position tracking beyond 13F parsing
- Mobile application
- Browser extension
- Advanced chart visualizations of portfolio data
- Webhook integrations (Slack, Zapier, etc.)

### Core Value Proposition

> A user adds investors they track. The platform automatically monitors those investors across SEC filings, their websites, and YouTube. When new information appears, an AI pipeline extracts investment theses, mentioned companies, and conviction signals, then generates a structured intelligence report delivered as an in-app notification and email digest.

The user's job-to-be-done: **Stop manually checking 10+ investor sources. Get a synthesized intelligence briefing instead.**

### Assumptions

1. Users are sophisticated investors (fund analysts, family offices, independent researchers) comfortable reading structured markdown reports.
2. "Investors" being tracked are public figures with publicly available information — no private data.
3. SEC EDGAR is free and reliable; it is the anchor data source for portfolio changes.
4. YouTube transcripts are available via the `youtube-transcript-api` library for most investment-related channels.
5. Most investor letters and newsletters are published on public websites or via RSS feeds.
6. LLM costs (OpenAI GPT-4o-mini for extraction, GPT-4o for report generation) are acceptable at MVP scale (~$0.10–$0.50 per report).
7. A single server (Railway) can handle background job scheduling for the MVP load (< 100 investors, < 500 sources).

### Why These Features Were Selected

SEC 13F filings are the highest-signal data source — they represent legally required disclosures of actual portfolio holdings. Pairing them with the investor's own written commentary (letters, YouTube, newsletters) creates the complete intelligence picture: *what they hold* plus *why they think it*. This combination is the core differentiation. Everything else is additive.

---

## 2. User Journey

### Initial Setup

**Step 1 — Sign Up**
- User visits the platform and clicks "Sign Up"
- Enters email + password
- Supabase Auth sends confirmation email
- User confirms and is redirected to onboarding

**Step 2 — Onboarding (First Investor)**
- A guided prompt appears: "Add your first investor to monitor"
- User clicks "Add Investor"
- Form fields:
  - Name (e.g., "Bill Ackman")
  - Description (optional)
  - CIK number for SEC filings (optional; platform can search EDGAR by name)
- System auto-searches EDGAR for matching CIK if not provided

**Step 3 — Configure Sources**
- After investor is created, user is prompted to add sources
- Source form shows available types:
  - SEC 13F (auto-populated if CIK found)
  - Website URL (e.g., pershingas.com/letters)
  - YouTube channel URL
  - RSS / Newsletter URL
  - Custom URL
- User adds one or more sources and saves
- System immediately queues a background sync for the new investor

**Step 4 — First Sync**
- Background job runs within minutes
- Content is ingested, processed, and a first investor report is generated
- User receives an in-app notification: "First report for Bill Ackman is ready"

### Monitoring Workflow

**Trigger:** Scheduled background job runs (hourly for websites/YouTube, every 6 hours for SEC EDGAR)

1. Job scheduler (`APScheduler`) fires the ingestion job for a specific source
2. Source adapter fetches content from the external URL
3. Content hash is computed — if already seen, skip (deduplication)
4. Raw content is stored in `content_items` with `status = pending`
5. Job enqueues the LangGraph processing pipeline for that content item
6. Pipeline runs:
   - Normalize + clean text
   - Chunk into segments
   - Extract entities (companies, tickers, themes)
   - Extract investment theses and conviction signals
   - Generate and store embeddings
7. Processing results stored in `extracted_mentions` and `portfolio_changes`
8. Report generator checks if a new report should be created:
   - Event-triggered: new 13F filing → generate Investor Report immediately
   - Batch: daily at 07:00 UTC → generate Daily Digest
9. Alert scorer evaluates severity; alerts written to `alerts` table
10. High-severity alerts trigger email via Resend

### Consumption Workflow

**Dashboard Visit**
- User opens app and sees Dashboard
- Top panel: unread alerts (red badge count)
- Middle section: "Recent Reports" (last 5 reports, newest first)
- Bottom section: "Recent Activity" feed (last 20 content items processed)

**Investor Profile View**
- User clicks on "Ackman" in the Investors list
- Sees investor header: name, sources count, last updated timestamp
- Timeline tab: chronological feed of all processed content items
- Reports tab: all reports generated for this investor
- Portfolio tab: latest 13F holdings, changes from prior period
- Mentions tab: all extracted company/ticker mentions with sentiment

**Reading a Report**
- User clicks on a report card
- Full report opens in a rendered markdown view
- Sections: Executive Summary → Key Observations → Companies Discussed → Bullish Signals → Bearish Signals → Source Links
- User can click source links to open original content
- "Mark as read" clears the report badge

**Alert Handling**
- User visits Alerts page
- Sees feed sorted by severity (critical → high → medium → low)
- Clicks alert → sees detail view with relevant report link
- "Mark read" or "Mark all read" buttons

---

## 3. System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    USER'S BROWSER                           │
│              Next.js Frontend (Vercel)                      │
│     Dashboard / Investors / Reports / Alerts / Settings     │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTPS REST API
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                 FastAPI Backend (Railway)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   REST API   │  │  APScheduler │  │   LangGraph      │  │
│  │  (routers)   │  │  (jobs)      │  │   Pipeline       │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                    │            │
│  ┌──────▼─────────────────▼────────────────────▼─────────┐  │
│  │               Service Layer                           │  │
│  │  InvestorService / IngestionService / ReportService   │  │
│  └──────────────────────────┬────────────────────────────┘  │
│                             │                               │
│  ┌──────────────────────────▼────────────────────────────┐  │
│  │              Source Adapters                          │  │
│  │  SEC EDGAR │ WebScraper │ YouTube │ RSS/Newsletter    │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  Supabase (Managed)                         │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────┐  │
│  │  PostgreSQL    │  │   pgvector     │  │  Supabase    │  │
│  │  (all tables)  │  │  (embeddings)  │  │  Auth        │  │
│  └────────────────┘  └────────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
      ┌──────────┐  ┌─────────┐  ┌────────┐
      │  OpenAI  │  │ EDGAR   │  │ Resend │
      │  API     │  │ (free)  │  │ Email  │
      └──────────┘  └─────────┘  └────────┘
```

### Components

**Frontend — Next.js (Vercel)**
- App Router (Next.js 14+)
- Supabase Auth client-side session management
- REST calls to FastAPI backend
- Tailwind CSS + shadcn/ui for styling
- React Query for data fetching + caching

**Backend API — FastAPI (Railway)**
- RESTful JSON API with Pydantic v2 validation
- JWT-based auth via Supabase token verification
- Organized into routers: `auth`, `investors`, `sources`, `content`, `reports`, `alerts`, `search`, `admin`

**Agent Layer — LangGraph**
- Sequential pipeline graph, not a complex branching graph
- Nodes: collector → normalizer → entity_extractor → thesis_extractor → embedder → report_generator → alert_checker
- Runs synchronously within a background job (not as a separate service)
- Uses OpenAI GPT-4o-mini for extraction (fast + cheap), GPT-4o for report generation (quality)

**Ingestion Layer — Source Adapters**
- `SECEdgarAdapter`: fetches 13F filings from EDGAR REST API
- `WebScraperAdapter`: fetches pages via `httpx` + `BeautifulSoup`; falls back to `Playwright` for JS-heavy sites
- `YouTubeAdapter`: fetches video metadata via YouTube Data API v3; pulls transcripts via `youtube-transcript-api`
- `RSSAdapter`: parses RSS/Atom feeds via `feedparser`

**Processing Layer**
- Content cleaning (strip HTML, normalize whitespace, remove boilerplate)
- Chunking (sliding window, 1000 tokens, 200 token overlap)
- Embedding generation (OpenAI `text-embedding-3-small`, 1536 dimensions)

**Reporting Layer**
- `InvestorReportGenerator`: produces structured markdown report for a single investor
- `DailyDigestGenerator`: aggregates all investor activity into one digest
- `EventReportGenerator`: triggered by specific events (new 13F, new company mention)

**Database Layer — Supabase PostgreSQL + pgvector**
- Single Supabase project
- pgvector extension for semantic search
- SQLAlchemy 2.0 async ORM + Alembic migrations

### Data Flow

**Content Entry:**
`APScheduler job fires → Source Adapter fetches URL → Content hash check → Store raw in content_items (status=pending)`

**Content Processing:**
`pending content_item → LangGraph pipeline triggered → normalize → chunk → extract entities/tickers/theses → generate embeddings → store in content_chunks + extracted_mentions → update status=completed`

**Report Generation:**
`ReportService checks trigger conditions → assembles context from extracted_mentions for investor → LLM generates structured markdown → store in reports table → create alert record`

**Alert Generation:**
`AlertScorer evaluates new content_items + reports → computes severity score → writes to alerts table → if score >= 80 (HIGH): send email via Resend`

---

## 4. Repository Structure

```
hedge-fund-intelligence/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI app factory, middleware, lifespan
│   │   └── config.py                # Pydantic Settings (env vars)
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                  # Shared dependencies (get_db, get_current_user)
│   │   ├── auth.py                  # /auth endpoints
│   │   ├── investors.py             # /investors CRUD
│   │   ├── sources.py               # /sources CRUD
│   │   ├── content.py               # /content read endpoints
│   │   ├── reports.py               # /reports read + trigger endpoints
│   │   ├── alerts.py                # /alerts CRUD
│   │   ├── search.py                # /search semantic endpoint
│   │   └── admin.py                 # /admin job status + triggers
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py                  # User ORM model
│   │   ├── investor.py              # Investor ORM model
│   │   ├── source.py                # Source ORM model
│   │   ├── content_item.py          # ContentItem ORM model
│   │   ├── content_chunk.py         # ContentChunk ORM model (with vector)
│   │   ├── extracted_mention.py     # ExtractedMention ORM model
│   │   ├── portfolio_change.py      # PortfolioChange ORM model
│   │   ├── report.py                # Report ORM model
│   │   └── alert.py                 # Alert ORM model
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── investor.py              # Pydantic request/response schemas
│   │   ├── source.py
│   │   ├── content.py
│   │   ├── report.py
│   │   ├── alert.py
│   │   └── search.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── investor_service.py      # Business logic for investor management
│   │   ├── source_service.py        # Source CRUD + validation
│   │   ├── content_service.py       # Content storage + retrieval
│   │   ├── report_service.py        # Report generation orchestration
│   │   ├── alert_service.py         # Alert creation + scoring
│   │   ├── embedding_service.py     # OpenAI embedding calls
│   │   └── email_service.py         # Resend email delivery
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── pipeline.py              # LangGraph pipeline assembly + execution
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── normalizer.py        # Normalize + clean content
│   │   │   ├── entity_extractor.py  # Extract companies, tickers, people, themes
│   │   │   ├── thesis_extractor.py  # Extract investment theses + conviction
│   │   │   ├── embedder.py          # Generate + store embeddings
│   │   │   ├── report_generator.py  # Generate investor report markdown
│   │   │   └── alert_checker.py     # Score + create alerts
│   │   ├── prompts/
│   │   │   ├── entity_extraction.py # Prompt templates
│   │   │   ├── thesis_extraction.py
│   │   │   └── report_generation.py
│   │   └── state.py                 # LangGraph state definition (TypedDict)
│   │
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── base_adapter.py          # Abstract base class for source adapters
│   │   ├── sec_adapter.py           # SEC EDGAR 13F adapter
│   │   ├── web_adapter.py           # Generic website + newsletter scraper
│   │   ├── youtube_adapter.py       # YouTube video + transcript adapter
│   │   ├── rss_adapter.py           # RSS/Atom feed adapter
│   │   └── content_hasher.py        # SHA-256 deduplication logic
│   │
│   ├── jobs/
│   │   ├── __init__.py
│   │   ├── scheduler.py             # APScheduler setup + job definitions
│   │   ├── ingestion_job.py         # Run ingestion for all active sources
│   │   ├── processing_job.py        # Process pending content_items
│   │   └── digest_job.py            # Generate daily digest at 07:00 UTC
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py            # SQLAlchemy async engine + session factory
│   │   ├── base.py                  # Declarative base
│   │   └── migrations/
│   │       ├── env.py               # Alembic env
│   │       └── versions/            # Migration files
│   │
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_api/
│   │   ├── test_agents/
│   │   ├── test_ingestion/
│   │   └── test_services/
│   │
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── railway.toml                 # Railway deployment config
│
├── frontend/
│   ├── src/
│   │   ├── app/                     # Next.js App Router pages
│   │   │   ├── (auth)/
│   │   │   │   ├── login/page.tsx
│   │   │   │   └── signup/page.tsx
│   │   │   ├── (dashboard)/
│   │   │   │   ├── layout.tsx       # Sidebar + nav layout
│   │   │   │   ├── page.tsx         # Dashboard
│   │   │   │   ├── investors/
│   │   │   │   │   ├── page.tsx     # Investors list
│   │   │   │   │   ├── new/page.tsx # Add investor
│   │   │   │   │   └── [id]/
│   │   │   │   │       ├── page.tsx       # Investor detail
│   │   │   │   │       └── edit/page.tsx  # Edit investor
│   │   │   │   ├── reports/
│   │   │   │   │   ├── page.tsx     # Reports archive
│   │   │   │   │   └── [id]/page.tsx
│   │   │   │   ├── alerts/
│   │   │   │   │   └── page.tsx
│   │   │   │   └── settings/
│   │   │   │       └── page.tsx
│   │   │   └── layout.tsx           # Root layout
│   │   │
│   │   ├── components/
│   │   │   ├── ui/                  # shadcn/ui primitives
│   │   │   ├── layout/
│   │   │   │   ├── Sidebar.tsx
│   │   │   │   ├── TopNav.tsx
│   │   │   │   └── AlertBadge.tsx
│   │   │   ├── investors/
│   │   │   │   ├── InvestorCard.tsx
│   │   │   │   ├── InvestorForm.tsx
│   │   │   │   ├── SourceManager.tsx
│   │   │   │   └── TimelineFeed.tsx
│   │   │   ├── reports/
│   │   │   │   ├── ReportCard.tsx
│   │   │   │   └── ReportViewer.tsx
│   │   │   ├── alerts/
│   │   │   │   ├── AlertFeed.tsx
│   │   │   │   └── AlertItem.tsx
│   │   │   └── dashboard/
│   │   │       ├── ActivityFeed.tsx
│   │   │       └── StatCard.tsx
│   │   │
│   │   ├── hooks/
│   │   │   ├── useInvestors.ts
│   │   │   ├── useReports.ts
│   │   │   ├── useAlerts.ts
│   │   │   └── useSearch.ts
│   │   │
│   │   ├── lib/
│   │   │   ├── api.ts               # Axios/fetch wrapper for backend calls
│   │   │   ├── supabase.ts          # Supabase client init
│   │   │   └── utils.ts             # Date formatting, etc.
│   │   │
│   │   └── types/
│   │       ├── investor.ts
│   │       ├── report.ts
│   │       ├── alert.ts
│   │       └── api.ts
│   │
│   ├── package.json
│   ├── tailwind.config.ts
│   ├── next.config.ts
│   └── tsconfig.json
│
├── docs/
│   ├── api.md                       # API reference
│   ├── architecture.md              # Architecture decisions
│   └── deployment.md                # Railway + Vercel deployment guide
│
├── .env.example
├── .gitignore
└── README.md
```

**Folder Responsibilities:**
- `api/` — HTTP layer only. Thin routers that validate input and delegate to services.
- `models/` — SQLAlchemy ORM definitions. Database structure is the source of truth.
- `schemas/` — Pydantic models for request/response serialization. Separate from ORM.
- `services/` — All business logic. Services don't know about HTTP or the database schema directly; they use models.
- `agents/` — All LangGraph and LLM logic. Self-contained; can be tested independently.
- `ingestion/` — All external data fetching. Adapters are pure functions: URL in, structured content out.
- `jobs/` — Scheduling and job orchestration. Jobs call services and adapters; no business logic here.
- `database/` — Connection setup and migrations only.

---

## 5. Database Design

### Schema Overview

**Why each table exists:**
- `users`: Stores user profile data extending Supabase Auth. Required for user-specific data ownership.
- `investors`: The core entity. Each investor being tracked is a row here.
- `sources`: Each URL/feed/channel attached to an investor. Multiple sources per investor.
- `content_items`: Every piece of raw content fetched from any source. The raw data store.
- `content_chunks`: Chunked segments of content_items with vector embeddings. Enables semantic search.
- `extracted_mentions`: Structured AI-extracted entities (companies, tickers, themes) from content.
- `portfolio_changes`: Structured holdings changes parsed from 13F filings. Separate table for queryability.
- `reports`: Generated intelligence reports (investor, digest, event). Stored as markdown.
- `alerts`: Actionable notifications with severity scoring.

### SQL Schema

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────
-- USERS (extends Supabase auth.users)
-- ─────────────────────────────────────
CREATE TABLE users (
    id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email       TEXT NOT NULL,
    full_name   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_email ON users(email);

-- ─────────────────────────────────────
-- INVESTORS
-- ─────────────────────────────────────
CREATE TABLE investors (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    cik_number  TEXT,                -- SEC CIK identifier (10-digit padded)
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    last_synced_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_investors_user_id   ON investors(user_id);
CREATE INDEX idx_investors_cik       ON investors(cik_number) WHERE cik_number IS NOT NULL;
CREATE INDEX idx_investors_active    ON investors(user_id, is_active);

-- ─────────────────────────────────────
-- SOURCES
-- ─────────────────────────────────────
CREATE TYPE source_type AS ENUM (
    'sec_13f', 'website', 'youtube', 'rss', 'twitter', 'custom'
);

CREATE TABLE sources (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    investor_id           UUID NOT NULL REFERENCES investors(id) ON DELETE CASCADE,
    source_type           source_type NOT NULL,
    url                   TEXT NOT NULL,
    label                 TEXT,                -- Human-readable label, e.g. "Q4 2024 Letter"
    config                JSONB DEFAULT '{}',  -- Extra config: youtube_channel_id, rss_guid, etc.
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    last_checked_at       TIMESTAMPTZ,
    last_successful_at    TIMESTAMPTZ,
    check_frequency_hours INTEGER NOT NULL DEFAULT 24,
    consecutive_failures  INTEGER NOT NULL DEFAULT 0,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sources_investor_id    ON sources(investor_id);
CREATE INDEX idx_sources_type           ON sources(source_type);
CREATE INDEX idx_sources_active_check   ON sources(is_active, last_checked_at)
    WHERE is_active = TRUE;

-- ─────────────────────────────────────
-- CONTENT ITEMS
-- ─────────────────────────────────────
CREATE TYPE content_type AS ENUM (
    'filing', 'article', 'video', 'newsletter', 'website_page', 'custom'
);

CREATE TYPE processing_status AS ENUM (
    'pending', 'processing', 'completed', 'failed', 'skipped'
);

CREATE TABLE content_items (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id         UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    investor_id       UUID NOT NULL REFERENCES investors(id) ON DELETE CASCADE,
    content_type      content_type NOT NULL,
    title             TEXT,
    url               TEXT,
    raw_text          TEXT,            -- Original fetched text (HTML stripped)
    cleaned_text      TEXT,            -- Post-cleaning normalized text
    published_at      TIMESTAMPTZ,
    content_hash      TEXT NOT NULL,   -- SHA-256 of raw_text for deduplication
    processing_status processing_status NOT NULL DEFAULT 'pending',
    processing_error  TEXT,
    metadata          JSONB DEFAULT '{}',   -- e.g., video duration, filing period
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT unique_content_hash UNIQUE (content_hash)
);
CREATE INDEX idx_content_source_id    ON content_items(source_id);
CREATE INDEX idx_content_investor_id  ON content_items(investor_id);
CREATE INDEX idx_content_status       ON content_items(processing_status)
    WHERE processing_status IN ('pending', 'processing');
CREATE INDEX idx_content_published    ON content_items(investor_id, published_at DESC);
CREATE INDEX idx_content_type         ON content_items(investor_id, content_type);

-- ─────────────────────────────────────
-- CONTENT CHUNKS (for vector search)
-- ─────────────────────────────────────
CREATE TABLE content_chunks (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content_item_id  UUID NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    chunk_index      INTEGER NOT NULL,
    chunk_text       TEXT NOT NULL,
    embedding        VECTOR(1536),    -- OpenAI text-embedding-3-small
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunks_content_item ON content_chunks(content_item_id);
CREATE INDEX idx_chunks_embedding ON content_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ─────────────────────────────────────
-- EXTRACTED MENTIONS
-- ─────────────────────────────────────
CREATE TYPE entity_type AS ENUM (
    'company', 'ticker', 'person', 'theme', 'sector', 'macro_theme'
);

CREATE TYPE sentiment AS ENUM ('bullish', 'bearish', 'neutral', 'mixed');
CREATE TYPE conviction_level AS ENUM ('high', 'medium', 'low', 'unknown');

CREATE TABLE extracted_mentions (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content_item_id  UUID NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    investor_id      UUID NOT NULL REFERENCES investors(id) ON DELETE CASCADE,
    entity_type      entity_type NOT NULL,
    entity_name      TEXT NOT NULL,
    ticker_symbol    TEXT,            -- NULL if not a ticker mention
    sentiment        sentiment,
    conviction_level conviction_level,
    context_snippet  TEXT,           -- 1–3 sentence supporting quote
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_mentions_content     ON extracted_mentions(content_item_id);
CREATE INDEX idx_mentions_investor    ON extracted_mentions(investor_id);
CREATE INDEX idx_mentions_ticker      ON extracted_mentions(ticker_symbol)
    WHERE ticker_symbol IS NOT NULL;
CREATE INDEX idx_mentions_entity      ON extracted_mentions(entity_type, entity_name);

-- ─────────────────────────────────────
-- PORTFOLIO CHANGES (from 13F)
-- ─────────────────────────────────────
CREATE TYPE portfolio_change_type AS ENUM (
    'new_position', 'increased', 'decreased', 'closed', 'unchanged'
);

CREATE TABLE portfolio_changes (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    investor_id          UUID NOT NULL REFERENCES investors(id) ON DELETE CASCADE,
    content_item_id      UUID NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    ticker_symbol        TEXT NOT NULL,
    company_name         TEXT,
    cusip                TEXT,
    change_type          portfolio_change_type NOT NULL,
    shares_previous      BIGINT DEFAULT 0,
    shares_current       BIGINT NOT NULL,
    value_usd            BIGINT,           -- In thousands (SEC standard)
    percent_of_portfolio NUMERIC(6, 3),
    filing_period        TEXT NOT NULL,    -- e.g., "2024-Q3"
    report_date          DATE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_portfolio_investor   ON portfolio_changes(investor_id);
CREATE INDEX idx_portfolio_ticker     ON portfolio_changes(ticker_symbol);
CREATE INDEX idx_portfolio_period     ON portfolio_changes(investor_id, filing_period);
CREATE INDEX idx_portfolio_change     ON portfolio_changes(change_type);

-- ─────────────────────────────────────
-- REPORTS
-- ─────────────────────────────────────
CREATE TYPE report_type AS ENUM (
    'investor_report', 'daily_digest', 'event_report'
);

CREATE TABLE reports (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    investor_id      UUID REFERENCES investors(id) ON DELETE SET NULL,  -- NULL for digest
    report_type      report_type NOT NULL,
    title            TEXT NOT NULL,
    summary          TEXT,                -- 2–3 sentence TL;DR
    content_markdown TEXT NOT NULL,       -- Full report in markdown
    source_item_ids  UUID[] DEFAULT '{}', -- content_item IDs referenced
    is_read          BOOLEAN NOT NULL DEFAULT FALSE,
    period_start     TIMESTAMPTZ,
    period_end       TIMESTAMPTZ,
    generated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_reports_user_id      ON reports(user_id);
CREATE INDEX idx_reports_investor_id  ON reports(investor_id) WHERE investor_id IS NOT NULL;
CREATE INDEX idx_reports_type         ON reports(user_id, report_type);
CREATE INDEX idx_reports_generated    ON reports(user_id, generated_at DESC);
CREATE INDEX idx_reports_unread       ON reports(user_id, is_read)
    WHERE is_read = FALSE;

-- ─────────────────────────────────────
-- ALERTS
-- ─────────────────────────────────────
CREATE TYPE alert_type AS ENUM (
    'new_filing', 'new_company_mention', 'new_thesis',
    'high_conviction', 'portfolio_change', 'daily_digest_ready'
);

CREATE TYPE alert_severity AS ENUM ('low', 'medium', 'high', 'critical');

CREATE TABLE alerts (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    investor_id      UUID REFERENCES investors(id) ON DELETE SET NULL,
    content_item_id  UUID REFERENCES content_items(id) ON DELETE SET NULL,
    report_id        UUID REFERENCES reports(id) ON DELETE SET NULL,
    alert_type       alert_type NOT NULL,
    title            TEXT NOT NULL,
    summary          TEXT,
    severity         alert_severity NOT NULL DEFAULT 'medium',
    score            INTEGER NOT NULL DEFAULT 50 CHECK (score BETWEEN 0 AND 100),
    is_read          BOOLEAN NOT NULL DEFAULT FALSE,
    email_sent       BOOLEAN NOT NULL DEFAULT FALSE,
    metadata         JSONB DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_alerts_user_unread   ON alerts(user_id, is_read, created_at DESC);
CREATE INDEX idx_alerts_investor      ON alerts(investor_id) WHERE investor_id IS NOT NULL;
CREATE INDEX idx_alerts_type          ON alerts(alert_type);
CREATE INDEX idx_alerts_severity      ON alerts(user_id, severity)
    WHERE is_read = FALSE;
```

---

## 6. MVP Data Source Strategy

### Source Priority Matrix

| Source | Signal Quality | Difficulty | Cost | Reliability | MVP Phase |
|---|---|---|---|---|---|
| SEC EDGAR 13F | ★★★★★ | Low | Free | Very High | Phase 1 ✅ |
| Investor Websites / Letters | ★★★★☆ | Medium | Free | High | Phase 1 ✅ |
| RSS / Newsletter | ★★★★☆ | Low | Free | High | Phase 1 ✅ |
| YouTube | ★★★☆☆ | Medium | Free* | Medium | Phase 1 ✅ |
| Twitter/X | ★★★☆☆ | High | $100+/mo | Low | Phase 2 ❌ |
| News Aggregation | ★★☆☆☆ | Medium | Varies | Medium | Phase 2 ❌ |
| Podcasts | ★★☆☆☆ | Very High | High | Low | Future ❌ |

*YouTube Data API v3 has a free tier of 10,000 units/day which is sufficient for MVP.

### SEC 13F Filings

**Collection Approach:** Use the EDGAR REST APIs directly — no scraping needed.
- Company submissions API: `https://data.sec.gov/submissions/CIK{padded_cik}.json`
- Filing index: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=13F-HR&dateb=&owner=include&count=10&output=atom`
- Full filing XML: `https://www.sec.gov/Archives/edgar/data/{cik}/{accession_number_nodashes}/{filename}.xml`

**Update Detection:** Poll `data.sec.gov/submissions/{cik}.json` every 6 hours. The `filings.recent` object contains the 1,000 most recent filings. Compare the latest accession number against the last stored one. 13Fs are filed quarterly (within 45 days of quarter end), so missed polls are not a concern.

**Parsing Strategy:**
1. Download the `infotable.xml` file within the 13F filing package
2. Parse XML: each `<infoTable>` element represents one holding
3. Fields: `nameOfIssuer`, `cusip`, `value`, `shrsOrPrnAmt`, `investmentDiscretion`, `putCall`, `votingAuthority`
4. Compare against previous period's holdings (same investor, previous `filing_period`) to determine `change_type`
5. Store parsed results in `portfolio_changes` table

### YouTube

**Discovery Strategy:** User provides a YouTube channel URL or handle. Extract the channel ID using the YouTube Data API v3 `channels.list` endpoint. Then use `playlistItems.list` with the channel's `uploads` playlist ID to fetch recent videos.

**Transcript Acquisition:**
- Primary: `youtube-transcript-api` Python library — fetches auto-generated or manually uploaded captions for any public video. No API key required for this library; it calls YouTube's timedtext API.
- Fallback: If transcript unavailable, store video title + description only. Flag the item as `transcript_unavailable` in metadata.
- Rate limit conservatively: check for new videos daily; pull transcripts immediately when new video detected.

### X/Twitter

**Decision: Defer X/Twitter to Phase 2.**

The Twitter/X API v2 Basic tier costs $100/month and provides only 1 million tweet reads per month — sufficient but not free. Given the MVP goal of proving value cheaply, deferring Twitter eliminates $100/month in infrastructure cost. Most high-quality investors post longer-form content on their websites and YouTube anyway.

**Alternative for MVP:** If a user provides a Twitter URL as a "custom source," attempt scraping via `nitter.net` mirrors (public, no API key) with explicit ToS awareness. Treat this as best-effort only.

### Newsletters

**Collection Strategy:** Most investor newsletters are distributed via email, but nearly all also publish an HTML archive on their website. Users provide the newsletter archive URL. The `RSSAdapter` handles feeds from Substack, Ghost, Beehiiv (all produce standard RSS). For non-RSS newsletters, the `WebScraperAdapter` crawls the archive page and follows links to individual posts.

### Websites

**Scraping Strategy:**
1. First attempt: `httpx` async HTTP client + `BeautifulSoup4` HTML parser. Extract `<article>` or `<main>` content, strip navigation/footer boilerplate using `trafilatura` library (purpose-built for article extraction).
2. Fallback: If JavaScript rendering is required (SPA sites), use `Playwright` headless browser. Playwright is heavier — only invoke it when `httpx` returns empty or boilerplate content.
3. Rate limiting: `asyncio.sleep(2)` between requests to the same domain. Respect `robots.txt`.
4. Change detection: store `content_hash` of cleaned text. Only process if hash has changed.

### News Sources

**Decision: Defer to Phase 2.** General news aggregation adds noise without adding investor-specific signal. For MVP, focus exclusively on investor-authored content (their filings, their letters, their videos, their newsletters). News articles written *about* investors can be added in Phase 2 using a news API (NewsAPI.org, $49/month).

### MVP Phase 1 Source Summary

Include these 4 sources in Phase 1:
1. **SEC EDGAR 13F** — highest-value data, free, structured
2. **Websites** — captures investor letters, blog posts, investment memos
3. **RSS / Newsletters** — low-effort, high value for frequent publishers
4. **YouTube** — captures long-form interview content and conference talks

---

## 7. Content Ingestion Layer

### Source Adapters

Each adapter inherits from `BaseAdapter` and implements:
```
Input:  source (Source ORM model) + investor_id
Output: List[RawContentItem] — a dataclass with title, url, raw_text, published_at, metadata
```

**SECEdgarAdapter**
- Input: `source.config["cik_number"]`
- Processing:
  1. Fetch `data.sec.gov/submissions/CIK{cik}.json`
  2. Find filings of type `13F-HR` not yet in database
  3. Download XML filing from EDGAR archives
  4. Parse `infotable.xml` into holding records
  5. Compute `filing_period` from the cover page `periodOfReport` element
- Output: One `RawContentItem` per filing, with `content_type = 'filing'`, parsed holdings in `metadata`

**WebScraperAdapter**
- Input: `source.url` (e.g., "https://pershingas.com/investor-letters")
- Processing:
  1. GET request with `httpx` + User-Agent header
  2. Extract main content using `trafilatura.extract(html)`
  3. If content is empty or < 200 chars, retry with Playwright
  4. For archive pages: find all links matching content patterns (PDF links, article links) and process each
  5. For PDFs: download and extract text with `pdfplumber`
- Output: One `RawContentItem` per page/document discovered

**YouTubeAdapter**
- Input: `source.config["channel_id"]` or `source.url`
- Processing:
  1. Call YouTube Data API v3 `playlistItems.list` for channel's uploads playlist
  2. Filter to videos published since `source.last_checked_at`
  3. For each new video: call `youtube_transcript_api.get_transcript(video_id)`
  4. Concatenate transcript segments into full text
  5. Include video title, description, published date in metadata
- Output: One `RawContentItem` per video

**RSSAdapter**
- Input: `source.url` (RSS/Atom feed URL)
- Processing:
  1. `feedparser.parse(url)` to get feed entries
  2. Filter entries published since `source.last_checked_at`
  3. For each entry: extract title, link, `content` or `summary` field
  4. If `content` is HTML, run through `trafilatura.extract()`
  5. If entry has no meaningful text but has a link, delegate to WebScraperAdapter for full page
- Output: One `RawContentItem` per feed entry

### Content Discovery

**How new content is detected:**
- All detection is hash-based: compute SHA-256 of `raw_text` before storing. If hash exists in `content_items.content_hash`, skip silently. This handles duplicate discovery from multiple sources of the same content.
- For SEC filings: check accession number in source `config["last_accession"]`.
- For YouTube: check video ID in source `config["seen_video_ids"]` list.
- For RSS: filter by `entry.published_parsed > source.last_checked_at`.

**Scheduling (APScheduler):**
```
SEC EDGAR:   every 6 hours   (cron: 0 */6 * * *)
YouTube:     every 12 hours  (cron: 0 */12 * * *)
RSS feeds:   every 4 hours   (cron: 0 */4 * * *)
Websites:    every 24 hours  (cron: 0 8 * * *)   # Once daily at 08:00 UTC

Processing (pending content): every 30 minutes
Daily Digest generation:       07:00 UTC daily
```

**Failure Handling:**
- All adapter calls are wrapped in `tenacity.retry` with exponential backoff (3 retries, starting at 5s)
- Failed ingestion writes error to `sources.consecutive_failures` counter
- After 5 consecutive failures, source is marked `is_active = False` and an alert is created for the user
- All errors logged via `structlog` with source_id and investor_id for debugging
- Failed `content_items` are marked `status = 'failed'` with `processing_error` message
- Reprocessing can be triggered manually via `/api/v1/admin/jobs/trigger`

---

## 8. AI Agent Design

### LangGraph Pipeline State

```python
# agents/state.py
class PipelineState(TypedDict):
    content_item_id: str
    investor_id: str
    raw_text: str
    cleaned_text: str
    chunks: List[str]
    entities: List[ExtractedEntity]
    theses: List[InvestmentThesis]
    embeddings_stored: bool
    report_generated: bool
    alerts_created: List[str]
    error: Optional[str]
```

### LangGraph Workflow Diagram

```
                    ┌──────────────┐
                    │    START     │
                    │ (content_id) │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  normalizer  │ Clean HTML, strip boilerplate,
                    │              │ normalize whitespace → cleaned_text
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   chunker    │ Sliding window chunking
                    │              │ 1000 tokens, 200 token overlap
                    └──────┬───────┘
                           │
                    ┌──────▼─────────────┐
                    │  entity_extractor  │ LLM call: companies, tickers,
                    │                    │ people, themes → entities[]
                    └──────┬─────────────┘
                           │
                    ┌──────▼─────────────┐
                    │  thesis_extractor  │ LLM call: investment thesis,
                    │                    │ conviction level, sentiment
                    └──────┬─────────────┘
                           │
                    ┌──────▼───────┐
                    │   embedder   │ OpenAI embedding per chunk
                    │              │ → store in content_chunks
                    └──────┬───────┘
                           │
                    ┌──────▼─────────────┐
                    │  report_generator  │ LLM call: generate investor
                    │                    │ report markdown if triggered
                    └──────┬─────────────┘
                           │
                    ┌──────▼─────────────┐
                    │   alert_checker    │ Score significance → create
                    │                    │ alerts if threshold met
                    └──────┬─────────────┘
                           │
                    ┌──────▼───────┐
                    │     END      │
                    └──────────────┘

Conditional edges:
- After entity_extractor: if error → END with error state
- After thesis_extractor: if content_type == 'filing' → skip thesis (go to embedder)
- After embedder: if filing → directly to alert_checker (no report_generator for raw filings)
- report_generator triggered only for: investor_letters, newsletter, video transcripts
```

### Node Specifications

**normalizer**
- Input: `state.raw_text`, `state.content_item_id`
- Processing: Strip HTML tags, normalize Unicode, collapse whitespace, remove page headers/footers, remove repeated boilerplate (navigation menus, disclaimers). Use `trafilatura` + custom regex patterns.
- Output: `state.cleaned_text`
- No LLM call; pure Python text processing.

**entity_extractor**
- Input: `state.chunks` (process in batches of 3 chunks)
- LLM: GPT-4o-mini (`gpt-4o-mini`)
- Prompt Strategy: Structured output via function calling / JSON mode. Provide few-shot examples. Ask for: company names, stock tickers, key people mentioned, macro themes. Specify output format strictly.
- Output: `state.entities` — list of `{entity_type, entity_name, ticker_symbol, sentiment, conviction_level, context_snippet}`
- Tool requirements: None (pure LLM call with JSON output)

Entity Extraction Prompt Template:
```
You are an expert investment analyst extracting structured information from investor communications.

Analyze the following text excerpt and extract:
1. Companies mentioned (with their ticker symbols if identifiable)
2. Investment themes or macro topics discussed
3. Key people mentioned
4. The sentiment expressed toward each company (bullish/bearish/neutral/mixed)
5. Conviction level (high/medium/low) based on language strength

Return a JSON array of entities. Each entity:
{
  "entity_type": "company|ticker|person|theme|macro_theme",
  "entity_name": "Full name",
  "ticker_symbol": "TICKER or null",
  "sentiment": "bullish|bearish|neutral|mixed",
  "conviction_level": "high|medium|low|unknown",
  "context_snippet": "1-2 sentence direct quote or paraphrase supporting this extraction"
}

TEXT:
{chunk_text}
```

**thesis_extractor**
- Input: `state.cleaned_text` (full text, not chunks — for holistic thesis understanding)
- LLM: GPT-4o (`gpt-4o`) — higher quality needed here
- Prompt Strategy: Identify the core investment thesis for each company mentioned. Look for: why the investor likes/dislikes the position, key catalysts mentioned, risks acknowledged, time horizon, position sizing language ("significant position," "core holding").
- Output: `state.theses` — list of `{company, ticker, thesis_summary, bullish_points, bearish_points, catalysts, risks, conviction_score_0_to_10}`

**embedder**
- Input: `state.chunks`
- Processing: Call `openai.embeddings.create(model="text-embedding-3-small", input=chunks)` in batches of 20
- Output: `state.embeddings_stored = True` after writing to `content_chunks` table
- No LLM generation; embedding API call only.

**report_generator**
- Input: `state.entities`, `state.theses`, investor context (recent history from DB)
- LLM: GPT-4o
- Trigger condition: Only runs if `content_type in ['article', 'newsletter', 'video', 'filing']` AND this is a new 13F or investor letter
- Prompt: Uses report template (see Section 10). Inject all extracted entities and theses, plus last 3 reports for continuity.
- Output: Markdown report string → stored in `reports` table

**alert_checker**
- Input: `state.entities`, `state.theses`, content metadata
- Processing: Rule-based scoring (no LLM). See Section 11 for scoring rules.
- Output: `state.alerts_created` — list of alert IDs written to DB

---

## 9. Content Processing Pipeline

### Step 1: Acquire Content
**Purpose:** Fetch raw content from external source.
**Implementation:** Source adapter (SECEdgarAdapter, WebScraperAdapter, YouTubeAdapter, RSSAdapter) fetches raw text. `httpx.AsyncClient` with 30s timeout. Playwright fallback for JS-heavy pages.
**Libraries:** `httpx`, `playwright`, `feedparser`, `youtube-transcript-api`, `sec-edgar-downloader`
**Edge Cases:** Paywalled content returns empty or login page → detect via content length < 500 chars or presence of "login" redirect → mark as `skipped`. PDFs are downloaded and extracted with `pdfplumber`.

### Step 2: Normalize Content
**Purpose:** Produce clean, readable text from HTML/XML/transcript noise.
**Implementation:** `trafilatura.extract(html, include_links=False, include_images=False)` as primary extractor. Falls back to `BeautifulSoup4` tag stripping. Normalize Unicode via `unicodedata.normalize('NFKD', text)`. Strip consecutive whitespace with regex.
**Libraries:** `trafilatura`, `beautifulsoup4`, `lxml`
**Edge Cases:** For transcripts, strip timestamp annotations (`[00:01:23]`). For SEC XML, ignore non-text elements.

### Step 3: Clean Content
**Purpose:** Remove noise patterns that confuse LLM extraction.
**Implementation:** Custom regex patterns to remove: email headers, copyright notices, navigation menus, repeated disclaimers, SEC header boilerplate (EDGAR submission headers). Collapse paragraphs separated by more than 2 newlines into 2. Remove strings matching patterns like `^\s*Page \d+\s*$` (page numbers).
**Libraries:** `re` (Python stdlib)
**Edge Cases:** Legal disclaimers in investor letters should be retained as context — do not strip "past performance is not indicative" clauses as they sometimes signal conviction about future performance.

### Step 4: Chunk Content
**Purpose:** Split long content into LLM-processable segments while preserving context.
**Implementation:** Use `langchain_text_splitters.RecursiveCharacterTextSplitter` with:
- `chunk_size = 4000` characters (~1000 tokens)
- `chunk_overlap = 400` characters (~100 tokens)
- Separators: `["\n\n", "\n", ". ", " "]`
  Store chunks in `content_chunks` before embedding.
**Libraries:** `langchain-text-splitters`
**Edge Cases:** Short content (< 4000 chars) = 1 chunk. 13F filings are structured XML — chunk by company name groups, not raw text.

### Step 5: Extract Entities
**Purpose:** Identify all companies, tickers, people, and themes discussed.
**Implementation:** Batch 3 chunks per LLM call. Parse JSON response. Deduplicate across chunks (same ticker from multiple chunks → merge, keep highest conviction). Store all in `extracted_mentions`.
**Libraries:** `openai`, `langchain-openai`
**Edge Cases:** Unknown tickers (e.g., private companies) → store with `ticker_symbol = null`. Handle LLM hallucinating tickers by cross-referencing against a simple ticker validation check (no external API needed for MVP; just validate format with regex `^[A-Z]{1,5}$`).

### Step 6: Extract Tickers
**Purpose:** Specifically normalize all ticker symbols into canonical form.
**Implementation:** Post-process entity extraction results. Build a deduplicated ticker list from `extracted_mentions` where `ticker_symbol IS NOT NULL`. For tickers mentioned ambiguously (e.g., "Apple" without "AAPL"), attempt resolution using a static reference CSV of S&P 500 + Russell 1000 tickers included in the repo at `backend/data/tickers.csv`.
**Libraries:** `pandas` for CSV lookup
**Edge Cases:** International tickers (e.g., BABA) should be preserved. Bond tickers or ETF tickers should be flagged differently in metadata.

### Step 7: Extract Theses
**Purpose:** Identify the investor's core reasoning about each position.
**Implementation:** Run thesis extraction on full `cleaned_text` (not chunks) if length < 16,000 chars. For longer documents, run on the 5 highest-entity-density chunks. Store thesis output in `extracted_mentions` with `entity_type = 'company'` and thesis in `context_snippet`.
**Libraries:** `openai`
**Edge Cases:** 13F filings have no thesis content (structured positions only). Skip thesis extraction for `content_type = 'filing'`. Conference call transcripts may have multiple speakers — thesis attribution should note "question" vs "answer" context.

### Step 8: Generate Embeddings
**Purpose:** Enable semantic search across all processed content.
**Implementation:** Call `openai.embeddings.create(model="text-embedding-3-small", input=[chunk_text], dimensions=1536)` for each chunk. Store embedding vector in `content_chunks.embedding` using pgvector.
**Libraries:** `openai`, `pgvector`, `sqlalchemy`
**Edge Cases:** Rate limit: OpenAI embeddings API is 3,000 RPM on Tier 1. Batch up to 20 chunks per API call. Max token length for text-embedding-3-small is 8192 tokens. Chunks over this limit are split again before embedding.

### Step 9: Store Structured Results
**Purpose:** Persist all extracted data for querying and reporting.
**Implementation:** Single database transaction:
1. Update `content_items.processing_status = 'completed'`
2. Bulk insert `extracted_mentions` rows
3. For 13F filings: bulk insert `portfolio_changes` rows
4. Update `sources.last_successful_at = now()`
**Libraries:** `sqlalchemy[asyncio]`, `asyncpg`
**Edge Cases:** If any step fails, rollback transaction and set `status = 'failed'`. Failed items are retried in the next processing job run (up to 3 retries, tracked in `metadata.retry_count`).

### Step 10: Generate Reports
**Purpose:** Synthesize extracted intelligence into human-readable reports.
**Implementation:** Report generation is separate from the extraction pipeline. It is triggered either by:
- Event: new 13F filing detected → generate Investor Report immediately
- Event: investor letter/newsletter processed → generate Investor Report within 1 hour
- Schedule: daily 07:00 UTC → generate Daily Digest for all users
The `ReportService.generate_investor_report()` queries all `extracted_mentions` for the investor in the past 30 days, all `portfolio_changes` from the latest 13F, and feeds them into the Reporting Agent prompt.
**Libraries:** `openai`, `jinja2` (for prompt templates)
**Edge Cases:** If no new content in the last 30 days, do not generate a report (avoid empty reports). If report generation fails, log error and skip — do not create a partial report.

---

## 10. Reporting Engine

### Investor Report Template

```markdown
# Intelligence Report: {investor_name}
**Generated:** {generated_at}  
**Period:** {period_start} — {period_end}  
**Sources analyzed:** {source_count} | **New content items:** {content_count}

---

## Executive Summary
{2-3 sentence AI-generated summary of the most important developments}

---

## Key Observations
{Bulleted list of 3-7 most significant findings from this period}

---

## Companies Discussed
| Company | Ticker | Sentiment | Conviction | Context |
|---------|--------|-----------|------------|---------|
| {name} | {TICK} | 🟢 Bullish | High | {1-sentence context} |
| {name} | {TICK} | 🔴 Bearish | Medium | {1-sentence context} |

---

## Bullish Signals
{For each bullish company/theme: investor's thesis, catalysts mentioned, key quotes}

---

## Bearish Signals  
{For each bearish company/theme: investor's concerns, risks cited, key quotes}

---

## Conviction Indicators
{Language analysis: positions described as "core," "significant," "adding," "trimming"}
- **Strong Conviction:** {companies where investor used highest-conviction language}
- **Monitoring:** {companies mentioned but with lower conviction}

---

## Portfolio Changes (from latest 13F)
**Filing Period:** {quarter}  
**New Positions:** {list}  
**Increased:** {list}  
**Decreased:** {list}  
**Closed:** {list}

---

## Source Links
{List of all source URLs with titles and published dates}
```

### Daily Digest Template

```markdown
# Daily Intelligence Digest
**Date:** {date}  
**Investors with activity:** {count}

---

## Today's Highlights
{Top 3-5 most significant items across all investors}

---

## Investor Activity

### {investor_name}
**Source:** {source_title} ({source_type})  
**Published:** {published_at}  
**Summary:** {2-3 sentence AI summary}  
**Key mentions:** {ticker list}  

[View Full Report →]({report_url})

---
{repeat for each active investor}

## New Themes This Week
{Cross-investor theme analysis: themes appearing in multiple investor communications}

---
*{total_content_items} content items processed | Generated at {timestamp}*
```

### Event Report Template

```markdown
# Event Alert: {event_type}
**Investor:** {investor_name}  
**Triggered:** {triggered_at}  
**Trigger:** {trigger_description}

---

## What Happened
{1 paragraph describing the triggering event}

## Why This Matters
{1-2 paragraphs on significance based on investor's history}

## Key Details
{Structured details: new position size, company description, etc.}

## Source
{link to original content}
```

---

## 11. Alerting System

### Alert Scoring Rules

Scores are additive integers from 0–100. Alerts with score ≥ 80 are `HIGH` severity and trigger email.

```
BASE SCORES:
  new_filing (13F detected):           +40
  new_company_mention (first time):    +30
  new_thesis (thesis change detected): +35
  
MULTIPLIERS:
  Conviction = HIGH:                   +20
  Sentiment = BULLISH or BEARISH:      +10
  Position size change > 20%:          +15
  New position (not seen before):      +20
  Position closed:                     +15
  Mentioned in title/headline:         +10
  
DEDUCTIONS (noise reduction):
  Same company mentioned last 7 days:  -15
  Sentiment = NEUTRAL:                 -10
  Short mention (< 50 chars context):  -10
  
SEVERITY MAPPING:
  0–39:   low
  40–59:  medium
  60–79:  high
  80–100: critical → email sent
```

### Noise Reduction

1. **Cooldown periods:** Do not create a `new_company_mention` alert for the same (investor, ticker) pair more than once per 7 days.
2. **Deduplication:** If two sources publish the same content (same hash), only one alert is created.
3. **Minimum quality gate:** Do not alert on content_items where `cleaned_text` is shorter than 200 characters.
4. **Daily digest batching:** Low/medium severity alerts are not emailed individually; they are batched into the daily digest email.

### Alert Examples

```
[CRITICAL] 🚨 Bill Ackman: New 13F Filing Detected
Severity: critical (score: 92)
Summary: Pershing Square filed 13F for Q3 2024. New positions: NVDA (+$2.1B). 
Closed positions: GOOGL. Portfolio value: $11.2B.
Action: View Report →

[HIGH] 🔵 David Einhorn: New High-Conviction Mention — $GOOG
Severity: high (score: 74)
Summary: Einhorn discussed Google in Q3 letter with high conviction language. 
Called it "significantly undervalued" and described it as a "core holding."
Action: View Mention →

[MEDIUM] 📄 Howard Marks: New Memo Published
Severity: medium (score: 52)
Summary: New Oaktree memo titled "The Impact of Debt." Discusses credit cycles 
and macro themes. 3 companies mentioned.
Action: Read Summary →

[LOW] 📺 Cathie Wood: New YouTube Video
Severity: low (score: 28)
Summary: ARK Invest posted new video discussing AI infrastructure themes.
Action: View →
```

---

## 12. API Design

All routes prefixed with `/api/v1`. Authentication via `Authorization: Bearer {supabase_jwt}` header. All responses follow `{data: ..., error: null}` envelope.

### Authentication

**POST /api/v1/auth/signup**
```json
Request:  { "email": "user@example.com", "password": "securepass123", "full_name": "Jane Doe" }
Response: { "user": { "id": "uuid", "email": "...", "full_name": "..." }, "session": { "access_token": "...", "refresh_token": "..." } }
```

**POST /api/v1/auth/login**
```json
Request:  { "email": "user@example.com", "password": "securepass123" }
Response: { "user": { "id": "uuid", "email": "..." }, "session": { "access_token": "..." } }
```

**POST /api/v1/auth/logout**
```
Headers: Authorization: Bearer {token}
Response: { "message": "logged out" }
```

**GET /api/v1/auth/me**
```json
Response: { "id": "uuid", "email": "user@example.com", "full_name": "Jane Doe", "created_at": "..." }
```

### Investors

**GET /api/v1/investors**
```json
Response: { "data": [ { "id": "uuid", "name": "Bill Ackman", "description": "...", "sources_count": 3, "last_synced_at": "...", "is_active": true } ] }
```

**POST /api/v1/investors**
```json
Request:  { "name": "Bill Ackman", "description": "...", "cik_number": "0001336528" }
Response: { "data": { "id": "uuid", "name": "Bill Ackman", ... } }
```

**GET /api/v1/investors/{investor_id}**
```json
Response: { "data": { "id": "...", "name": "...", "sources": [...], "last_synced_at": "...", "stats": { "content_items": 47, "reports": 5, "unread_alerts": 2 } } }
```

**PUT /api/v1/investors/{investor_id}**
```json
Request:  { "name": "...", "description": "...", "is_active": true }
Response: { "data": { ... updated investor ... } }
```

**DELETE /api/v1/investors/{investor_id}**
```json
Response: { "message": "investor deleted" }
```

**POST /api/v1/investors/{investor_id}/sync**
```json
Response: { "message": "sync queued", "job_id": "..." }
```

### Sources

**GET /api/v1/investors/{investor_id}/sources**
```json
Response: { "data": [ { "id": "uuid", "source_type": "sec_13f", "url": "...", "is_active": true, "last_checked_at": "...", "consecutive_failures": 0 } ] }
```

**POST /api/v1/investors/{investor_id}/sources**
```json
Request:  { "source_type": "youtube", "url": "https://youtube.com/@PershtAckman", "label": "Ackman YouTube", "check_frequency_hours": 12 }
Response: { "data": { "id": "uuid", "source_type": "youtube", ... } }
```

**PUT /api/v1/investors/{investor_id}/sources/{source_id}**
```json
Request:  { "is_active": false }
Response: { "data": { ... updated source ... } }
```

**DELETE /api/v1/investors/{investor_id}/sources/{source_id}**
```json
Response: { "message": "source deleted" }
```

### Reports

**GET /api/v1/reports**
```
Query params: ?page=1&limit=20&investor_id={uuid}&report_type=investor_report&unread_only=true
Response: { "data": [ { "id": "uuid", "title": "...", "summary": "...", "report_type": "...", "investor_name": "...", "generated_at": "...", "is_read": false } ], "total": 42 }
```

**GET /api/v1/reports/{report_id}**
```json
Response: { "data": { "id": "uuid", "title": "...", "content_markdown": "...", "investor": {...}, "generated_at": "..." } }
```

**PUT /api/v1/reports/{report_id}/read**
```json
Response: { "data": { "id": "uuid", "is_read": true } }
```

**POST /api/v1/reports/generate**
```json
Request:  { "investor_id": "uuid", "report_type": "investor_report" }
Response: { "message": "report generation queued", "job_id": "..." }
```

### Alerts

**GET /api/v1/alerts**
```
Query params: ?page=1&limit=20&unread_only=true&severity=high&investor_id={uuid}
Response: { "data": [ { "id": "uuid", "title": "...", "summary": "...", "alert_type": "new_filing", "severity": "critical", "score": 92, "is_read": false, "investor_name": "...", "created_at": "..." } ], "unread_count": 7 }
```

**PUT /api/v1/alerts/{alert_id}/read**
```json
Response: { "data": { "id": "uuid", "is_read": true } }
```

**PUT /api/v1/alerts/read-all**
```json
Response: { "message": "all alerts marked as read", "count": 7 }
```

### Search

**POST /api/v1/search**
```json
Request:  { "query": "Ackman thesis on interest rates", "investor_id": null, "limit": 10 }
Response: { "data": [ { "content_item_id": "...", "chunk_text": "...", "investor_name": "...", "source_title": "...", "published_at": "...", "similarity": 0.87 } ] }
```

### Admin

**GET /api/v1/admin/jobs/status**
```json
Response: { "data": { "scheduler_running": true, "jobs": [ { "id": "ingestion", "next_run": "...", "last_run": "..." } ], "pending_content_items": 3 } }
```

**POST /api/v1/admin/jobs/trigger**
```json
Request:  { "job": "ingestion" }
Response: { "message": "job triggered" }
```

---

## 13. Frontend Design

### Design System
Use **shadcn/ui** + **Tailwind CSS** for all components. Color palette: dark neutral background (slate-950/zinc-900), white content cards, accent colors: blue-500 (primary), green-500 (bullish), red-500 (bearish), amber-500 (warning). Typography: Inter font via `next/font`.

Layout: Fixed left sidebar (220px wide) + main content area. Top navigation bar on mobile. Responsive breakpoints: mobile (< 640px), tablet (640-1024px), desktop (> 1024px).

### Dashboard Page (`/`)
**Layout:** 3-column stat row + 2-column content grid

**Stat Row:**
- "Investors Tracked" (count)
- "Unread Alerts" (count, red badge if > 0)
- "Reports This Week" (count)

**Content Grid (left, 60%):**
- "Recent Reports" — card list of 5 most recent reports with investor name, report type badge, summary, "Read" CTA

**Content Grid (right, 40%):**
- "Alert Feed" — last 10 alerts with severity color coding, investor name, one-line summary, timestamp

**Empty state:** If no investors, show a prominent "Add Your First Investor" card with CTA button.

### Investors Page (`/investors`)
**Layout:** Full-width table/card list

**Features:**
- Card grid (desktop) / list (mobile) of all tracked investors
- Each card: investor name, avatar (initial letter), sources count, last synced timestamp, activity status indicator (green dot = active, gray = inactive)
- "Add Investor" button top-right
- Quick-filter tabs: All | Active | Inactive
- Status badge per source type (SEC, YouTube, RSS, Website icons)

### Investor Detail Page (`/investors/[id]`)
**Layout:** Sticky header + tab navigation

**Header:** Investor name, description, "Sync Now" button, "Edit" button, last synced timestamp

**Tabs:**
1. **Overview** — Summary stats, latest report preview, recent mentions (ticker chips)
2. **Timeline** — Chronological feed of all content_items. Each item: source icon, title, published date, status badge, "View" link. Filterable by content type.
3. **Portfolio** — Table of latest 13F holdings with change indicators (▲▼ arrows). Columns: Company, Ticker, Shares, Value, Change, % of Portfolio. Only shown if SEC source exists.
4. **Reports** — List of all reports for this investor, newest first. Click → opens ReportViewer modal.
5. **Sources** — Editable list of sources. Inline add/remove/toggle.

### Reports Page (`/reports`)
**Layout:** Sidebar filters + main content list

**Filter sidebar:** Report type (All / Investor / Digest / Event), Investor (multi-select), Date range, Read/Unread toggle

**Report list:** Card per report. Shows: title, type badge, investor name, generated date, 2-line summary. Unread items have left border accent. Click → opens full report.

**Report Viewer:** Markdown rendered with `react-markdown` + `remark-gfm` (for tables). Sticky header with investor name, date, "Mark Read" button. Source links section at bottom.

### Alerts Page (`/alerts`)
**Layout:** Full-width sorted feed

**Features:**
- "Mark All Read" button top-right
- Filter bar: Severity (all/critical/high/medium/low), Alert type, Investor
- Each alert item: severity color bar (left border), icon, title, investor name, summary, timestamp, "View Report" link if available
- Clicking alert opens a slide-over drawer with full alert detail

### Settings Page (`/settings`)
**Layout:** Sectioned form

**Sections:**
- **Profile** — Name, email (read-only), password change button
- **Notifications** — Toggle: email alerts for critical alerts (default: on), daily digest email (default: on), minimum severity for email
- **API Configuration** — Display area for noting OpenAI API key is configured server-side (no user-side key needed for MVP)
- **Data** — "Export My Data" button (future), "Delete Account" danger zone

---

## 14. Development Phases

### Phase 1: Foundation (Week 1–2)
**Deliverables:**
- Working FastAPI backend with Supabase connection
- All database tables created via Alembic migrations
- Supabase Auth integration (JWT validation middleware)
- Full investor CRUD API
- Full source CRUD API
- Basic Next.js app with auth pages
- Working end-to-end: sign up → add investor → add source → see it in DB

**Dependencies:** Supabase project created, Railway account set up, environment variables configured
**Success Criteria:** A user can authenticate and manage investors + sources via the API. All DB tables exist with correct indexes.
**Estimated Effort:** 3–4 days

### Phase 2: Data Ingestion (Week 2–3)
**Deliverables:**
- SEC EDGAR adapter: fetch + parse 13F filings
- Website scraper adapter: httpx + trafilatura + Playwright fallback
- RSS adapter: feedparser
- YouTube adapter: Data API + transcript fetching
- Content deduplication (hash-based)
- APScheduler running all 4 jobs
- `portfolio_changes` populated from 13F data
- Content items stored with `status = 'completed'` after raw storage

**Dependencies:** Phase 1 complete, YouTube Data API v3 key configured
**Success Criteria:** For a test investor (e.g., Bill Ackman CIK), the system automatically fetches and stores 13F holdings, parses his website, and stores content items in the database without manual intervention.
**Estimated Effort:** 4–5 days

### Phase 3: AI Processing (Week 3–4)
**Deliverables:**
- LangGraph pipeline assembled and runnable
- Entity extraction working (companies, tickers extracted accurately)
- Thesis extraction working
- Embeddings generated and stored in pgvector
- `extracted_mentions` table populated
- Processing job triggered automatically for pending content items
- Semantic search endpoint working

**Dependencies:** Phase 2 complete, OpenAI API key configured
**Success Criteria:** A processed content item has extracted_mentions with accurate tickers and sentiments. A semantic search query returns relevant chunks.
**Estimated Effort:** 4–5 days

### Phase 4: Reporting & Alerts (Week 4–5)
**Deliverables:**
- Investor Report generator producing full markdown reports
- Daily Digest generator (triggered at 07:00 UTC)
- Event-driven report triggered on new 13F
- Alert scoring logic
- Alert creation for all 4 alert types
- Email delivery via Resend for critical/high severity alerts
- Reports and alerts stored in DB and retrievable via API

**Dependencies:** Phase 3 complete, Resend API key configured
**Success Criteria:** A new 13F filing triggers: (1) portfolio changes stored, (2) investor report generated within 1 hour, (3) critical alert created, (4) email sent. Daily digest email arrives at 07:00 UTC.
**Estimated Effort:** 3–4 days

### Phase 5: Frontend (Week 5–7)
**Deliverables:**
- Complete Next.js application with all 6 pages
- Auth flow working (sign up, login, protected routes)
- Dashboard showing real data
- Investor management UI (add/edit/delete investors and sources)
- Reports page with markdown rendering
- Alerts page with read/unread functionality
- Responsive design (mobile + desktop)
- Deployed to Vercel, backend deployed to Railway

**Dependencies:** Phase 4 complete, Vercel project configured
**Success Criteria:** A non-technical user can sign up, add Bill Ackman as an investor, wait for the first sync, and read a generated intelligence report — all without touching the API directly.
**Estimated Effort:** 5–7 days

---

## 15. Claude Code Build Plan

> Execute tasks in strict sequence. Each task is scoped for a single Claude Code session (~1–2 hours). Do not proceed to the next task until acceptance criteria are met.

---

### Task 1: Initialize Repository Structure
**Objective:** Create the full repository scaffold with all directories and placeholder files.
**Files Affected:** All top-level directories and `__init__.py` files, `README.md`, `.env.example`, `.gitignore`
**Dependencies:** None
**Acceptance Criteria:**
- `hedge-fund-intelligence/` directory structure matches Section 4 exactly
- `.env.example` contains all required environment variable names (no values): `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`, `OPENAI_API_KEY`, `RESEND_API_KEY`, `YOUTUBE_API_KEY`, `DATABASE_URL`, `FRONTEND_URL`
- All `__init__.py` files created
- `.gitignore` excludes `.env`, `__pycache__`, `.venv`, `node_modules`, `.next`

---

### Task 2: Configure FastAPI Backend
**Objective:** Create a working FastAPI app with config management, health check, and CORS setup.
**Files Affected:** `backend/app/main.py`, `backend/app/config.py`, `backend/pyproject.toml`
**Dependencies:** Task 1
**Acceptance Criteria:**
- `pyproject.toml` lists all dependencies (fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, alembic, pydantic[email], pydantic-settings, supabase, python-jose[cryptography], httpx, playwright, beautifulsoup4, trafilatura, feedparser, youtube-transcript-api, google-api-python-client, apscheduler, langgraph, langchain-openai, openai, pgvector, tenacity, structlog, python-dotenv, resend, pdfplumber, lxml, feedparser)
- `config.py` uses `pydantic_settings.BaseSettings` to load all env vars with type validation
- `main.py` creates FastAPI app, configures CORS (allow `FRONTEND_URL`), includes a `GET /health` endpoint returning `{"status": "ok"}`
- `uvicorn backend.app.main:app --reload` runs without errors

---

### Task 3: Configure Supabase Database Connection
**Objective:** Set up SQLAlchemy async engine connected to Supabase PostgreSQL, plus pgvector extension.
**Files Affected:** `backend/database/connection.py`, `backend/database/base.py`, `backend/database/migrations/env.py`, `alembic.ini`
**Dependencies:** Task 2, Supabase project created with connection string in `.env`
**Acceptance Criteria:**
- `connection.py` creates an async SQLAlchemy engine using `asyncpg` driver with the Supabase connection string
- `base.py` defines `Base = declarative_base()`
- Alembic is configured to use the async engine
- Running `alembic upgrade head` against a blank Supabase DB completes without errors (empty migration to start)
- pgvector extension exists in Supabase DB (enable via Supabase dashboard before running)

---

### Task 4: Create All Database Models and Initial Migration
**Objective:** Define all SQLAlchemy ORM models and generate the initial Alembic migration.
**Files Affected:** All files in `backend/models/`, `backend/database/migrations/versions/001_initial_schema.py`
**Dependencies:** Task 3
**Acceptance Criteria:**
- All 9 tables from Section 5 are defined as SQLAlchemy models: `User`, `Investor`, `Source`, `ContentItem`, `ContentChunk`, `ExtractedMention`, `PortfolioChange`, `Report`, `Alert`
- `ContentChunk.embedding` uses `Vector(1536)` type from `pgvector.sqlalchemy`
- All ENUM types defined in PostgreSQL match Section 5
- All indexes defined in `__table_args__`
- `alembic revision --autogenerate -m "initial_schema"` generates a valid migration
- `alembic upgrade head` creates all tables with correct structure in Supabase

---

### Task 5: Implement Authentication Middleware
**Objective:** Create JWT verification middleware that validates Supabase-issued tokens on all protected routes.
**Files Affected:** `backend/api/deps.py`, `backend/api/auth.py`
**Dependencies:** Task 4
**Acceptance Criteria:**
- `deps.py` defines `get_current_user(token: str = Depends(oauth2_scheme)) -> User` that decodes the Supabase JWT using `SUPABASE_JWT_SECRET`, queries the user from the DB, and raises `HTTP 401` if invalid
- `auth.py` defines `POST /api/v1/auth/signup`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me` endpoints
- Signup calls Supabase Auth API to create user, then inserts into local `users` table
- Login calls Supabase Auth API, returns session tokens
- `GET /api/v1/auth/me` returns current user profile (protected route test)
- Test: a POST to `/auth/signup` with valid email/password returns a session token; using that token on `GET /auth/me` returns user data

---

### Task 6: Implement Investor CRUD API
**Objective:** Full CRUD for investors including EDGAR CIK lookup.
**Files Affected:** `backend/api/investors.py`, `backend/schemas/investor.py`, `backend/services/investor_service.py`
**Dependencies:** Task 5
**Acceptance Criteria:**
- `schemas/investor.py` defines `InvestorCreate`, `InvestorUpdate`, `InvestorResponse` Pydantic models
- `investor_service.py` implements `create`, `get`, `list`, `update`, `delete` methods using async SQLAlchemy
- All investor operations are scoped to `current_user.id` (users can only see their own investors)
- `GET /api/v1/investors` returns list of current user's investors
- `POST /api/v1/investors` creates investor and returns it
- `DELETE /api/v1/investors/{id}` cascades deletes to sources, content_items, etc.
- Test: create 2 investors, list returns both, delete one, list returns one

---

### Task 7: Implement Source CRUD API
**Objective:** Full CRUD for investor sources with validation per source type.
**Files Affected:** `backend/api/sources.py`, `backend/schemas/source.py`, `backend/services/source_service.py`
**Dependencies:** Task 6
**Acceptance Criteria:**
- `schemas/source.py` defines `SourceCreate`, `SourceUpdate`, `SourceResponse` with `source_type` validation
- `source_service.py` validates URL format per source type (e.g., YouTube URL must contain `youtube.com` or `youtu.be`)
- `POST /api/v1/investors/{investor_id}/sources` validates that investor belongs to current user before creating source
- `PUT` endpoint allows toggling `is_active` and updating `check_frequency_hours`
- Test: add a `sec_13f` source and a `youtube` source to an investor; list returns both; toggle one inactive

---

### Task 8: Implement Pydantic Schemas for All Entities
**Objective:** Define all remaining Pydantic request/response schemas.
**Files Affected:** `backend/schemas/content.py`, `backend/schemas/report.py`, `backend/schemas/alert.py`, `backend/schemas/search.py`
**Dependencies:** Task 7
**Acceptance Criteria:**
- `ContentItemResponse` includes `id`, `title`, `url`, `content_type`, `published_at`, `processing_status`, `investor_id`
- `ReportResponse` includes `id`, `title`, `summary`, `report_type`, `generated_at`, `is_read`, `investor_name`
- `ReportDetailResponse` adds `content_markdown`, `source_item_ids`
- `AlertResponse` includes all alert fields plus `investor_name`
- `SearchRequest` and `SearchResponse` defined
- All schemas have proper `model_config = ConfigDict(from_attributes=True)` for ORM compatibility

---

### Task 9: Create SEC EDGAR Adapter
**Objective:** Implement the SEC 13F filing fetcher and XML parser.
**Files Affected:** `backend/ingestion/base_adapter.py`, `backend/ingestion/sec_adapter.py`, `backend/ingestion/content_hasher.py`
**Dependencies:** Task 8
**Acceptance Criteria:**
- `base_adapter.py` defines `BaseAdapter` abstract class with `async def fetch(source: Source) -> List[RawContentItem]` method
- `RawContentItem` dataclass defined with: `title`, `url`, `raw_text`, `published_at`, `content_type`, `metadata: dict`
- `sec_adapter.py` fetches latest 13F filings for a CIK from `data.sec.gov/submissions/{cik}.json`
- Parser correctly extracts all holdings from 13F XML `infotable.xml` into a structured list in `metadata`
- `content_hasher.py` computes SHA-256 of raw text for deduplication
- Test: for CIK `0001336528` (Pershing Square), adapter returns at least one 13F filing with non-empty metadata containing holdings

---

### Task 10: Create Website and RSS Adapters
**Objective:** Implement web scraping and RSS feed adapters.
**Files Affected:** `backend/ingestion/web_adapter.py`, `backend/ingestion/rss_adapter.py`
**Dependencies:** Task 9
**Acceptance Criteria:**
- `web_adapter.py` fetches URL with `httpx`, extracts main content using `trafilatura`. Falls back to BeautifulSoup paragraph extraction if trafilatura returns empty. Downloads and extracts text from PDF links using `pdfplumber`.
- `rss_adapter.py` parses RSS/Atom feeds with `feedparser`. Filters entries newer than `source.last_checked_at`. Delegates full-article fetching to `web_adapter` for entries without content.
- Both adapters respect rate limits (2s delay between requests to same domain)
- Test: `web_adapter.fetch` on `https://oaktree.com/insights` returns at least one content item with > 500 chars of text. `rss_adapter.fetch` on a known Substack RSS URL returns at least one entry.

---

### Task 11: Create YouTube Adapter
**Objective:** Implement YouTube video discovery and transcript fetching.
**Files Affected:** `backend/ingestion/youtube_adapter.py`
**Dependencies:** Task 10, YouTube Data API v3 key in `.env`
**Acceptance Criteria:**
- `youtube_adapter.py` accepts a channel URL, extracts channel ID, uses `googleapiclient.discovery` to list latest 20 videos from uploads playlist
- Filters videos published since `source.last_checked_at`
- For each new video, calls `YouTubeTranscriptApi.get_transcript(video_id)` to get transcript segments
- Concatenates segments into full text stored in `raw_text`
- If transcript unavailable, sets `metadata["transcript_available"] = False` and stores title + description only
- Test: for a known YouTube channel (e.g., ARK Invest), adapter returns at least one video with a transcript of > 1000 chars

---

### Task 12: Configure APScheduler and Ingestion Jobs
**Objective:** Set up background job scheduler with all 4 ingestion jobs running on schedule.
**Files Affected:** `backend/jobs/scheduler.py`, `backend/jobs/ingestion_job.py`, `backend/app/main.py` (lifespan)
**Dependencies:** Tasks 9–11
**Acceptance Criteria:**
- `scheduler.py` creates `AsyncIOScheduler` with 4 jobs: SEC EDGAR (every 6h), YouTube (every 12h), RSS (every 4h), Website (every 24h)
- `ingestion_job.py` implements `run_ingestion_for_source_type(source_type)` that queries all active sources of that type, runs the appropriate adapter, handles deduplication, and stores new `content_items` with `status = 'pending'`
- Scheduler starts in FastAPI `lifespan` context manager (starts on app startup, shuts down cleanly)
- Failed adapters increment `sources.consecutive_failures`; after 5 failures, set `is_active = False`
- Test: manually trigger SEC ingestion job via scheduler; verify new content_item rows appear in DB for a test investor with SEC source

---

### Task 13: Implement Content Normalization and Chunking
**Objective:** Build the first two steps of the processing pipeline.
**Files Affected:** `backend/agents/nodes/normalizer.py`, `backend/services/content_service.py`
**Dependencies:** Task 12
**Acceptance Criteria:**
- `normalizer.py` node: strips HTML, normalizes Unicode, removes boilerplate patterns (page numbers, repeated disclaimers), collapses whitespace. Accepts `PipelineState`, returns updated state with `cleaned_text`.
- `content_service.py` implements `chunk_text(text: str) -> List[str]` using `RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=400)`
- Test: pass a sample investor letter HTML through normalizer; output should be clean readable text without HTML tags or excessive whitespace. Chunk a 10,000 character text; verify ~3 chunks with expected overlap.

---

### Task 14: Implement LangGraph State and Pipeline Assembly
**Objective:** Define the LangGraph state and assemble the full pipeline graph.
**Files Affected:** `backend/agents/state.py`, `backend/agents/pipeline.py`
**Dependencies:** Task 13
**Acceptance Criteria:**
- `state.py` defines `PipelineState(TypedDict)` with all fields from Section 8
- `pipeline.py` creates a `StateGraph(PipelineState)` and adds nodes: `normalizer`, `entity_extractor`, `thesis_extractor`, `embedder`, `report_generator`, `alert_checker`
- Conditional edges: skip `thesis_extractor` if `content_type == 'filing'`; skip `report_generator` if not triggered
- `pipeline.compile()` returns a runnable graph
- Test: run pipeline with a dummy `PipelineState` (mock LLM calls using `unittest.mock`); verify all nodes execute in correct order and state transitions properly

---

### Task 15: Implement Entity Extraction Node
**Objective:** Build the LLM-powered entity extraction node.
**Files Affected:** `backend/agents/nodes/entity_extractor.py`, `backend/agents/prompts/entity_extraction.py`
**Dependencies:** Task 14
**Acceptance Criteria:**
- `entity_extraction.py` contains the prompt template from Section 8 as a `PromptTemplate`
- `entity_extractor.py` node batches `state.chunks` in groups of 3 and calls GPT-4o-mini with JSON output mode
- Response is parsed into a list of entity dicts; invalid entries (malformed JSON, missing fields) are skipped with a warning log
- Ticker symbols are validated against format `^[A-Z]{1,5}(\.[A-Z]{1,2})?$`; invalid ones have `ticker_symbol` set to `None`
- Results stored in `extracted_mentions` table
- Test: run entity extraction on a sample Ackman letter excerpt containing known company mentions; verify GOOGL, NVDA, etc. are correctly extracted with appropriate sentiment

---

### Task 16: Implement Thesis Extraction Node
**Objective:** Build the investment thesis extraction node.
**Files Affected:** `backend/agents/nodes/thesis_extractor.py`, `backend/agents/prompts/thesis_extraction.py`
**Dependencies:** Task 15
**Acceptance Criteria:**
- `thesis_extractor.py` runs on `state.cleaned_text` (full text, not chunks)
- Calls GPT-4o with structured JSON output containing: `company`, `ticker`, `thesis_summary`, `bullish_points: []`, `bearish_points: []`, `catalysts: []`, `risks: []`, `conviction_score: int (0-10)`
- For texts > 16,000 chars, truncate to first 16,000 characters with a note in metadata
- Merges thesis results with entity mentions: updates `conviction_level` in `extracted_mentions` based on `conviction_score` (>= 7 = high, 4–6 = medium, < 4 = low)
- Skips for `content_type == 'filing'`
- Test: run thesis extraction on a sample letter; verify output contains a thesis summary and bullish/bearish points for at least one company

---

### Task 17: Implement Embedding Generation Node
**Objective:** Generate and store vector embeddings for all content chunks.
**Files Affected:** `backend/agents/nodes/embedder.py`, `backend/services/embedding_service.py`
**Dependencies:** Task 16
**Acceptance Criteria:**
- `embedding_service.py` wraps OpenAI `text-embedding-3-small` API call with batch support (max 20 texts per call) and `tenacity` retry (3 attempts, exponential backoff)
- `embedder.py` node calls embedding service for each chunk in `state.chunks`, then bulk-inserts rows into `content_chunks` (with `chunk_index`, `chunk_text`, `embedding` vector)
- Sets `state.embeddings_stored = True` on success
- Test: generate embeddings for 5 test chunks; verify 5 rows inserted in `content_chunks` with non-null `embedding` VECTOR columns; verify a cosine similarity query against pgvector returns reasonable results

---

### Task 18: Implement Processing Background Job
**Objective:** Create the background job that picks up pending content_items and runs the full pipeline.
**Files Affected:** `backend/jobs/processing_job.py`, `backend/jobs/scheduler.py` (add job)
**Dependencies:** Task 17
**Acceptance Criteria:**
- `processing_job.py` queries `content_items WHERE processing_status = 'pending' LIMIT 10`, sets them to `'processing'`, then invokes the LangGraph pipeline for each
- On success: sets `status = 'completed'`, updates `sources.last_successful_at`
- On exception: sets `status = 'failed'`, writes error to `processing_error`, increments `metadata.retry_count`; items with `retry_count >= 3` are set to `'skipped'`
- Job added to APScheduler running every 30 minutes
- Test: insert a pending content_item manually; trigger processing job; verify item moves to `completed` status and `extracted_mentions` rows are created

---

### Task 19: Implement Investor Report Generator
**Objective:** Build the LLM-powered investor report generation system.
**Files Affected:** `backend/agents/nodes/report_generator.py`, `backend/agents/prompts/report_generation.py`, `backend/services/report_service.py`
**Dependencies:** Task 18
**Acceptance Criteria:**
- `report_service.py` implements `generate_investor_report(investor_id, period_start, period_end)` that:
  1. Queries all `extracted_mentions` for the investor in the period
  2. Queries all `portfolio_changes` from the latest 13F in the period (if any)
  3. Builds a structured context dict
  4. Calls the `report_generator` node
- `report_generator.py` node calls GPT-4o with the full report template from Section 10, injects context, returns markdown
- Report is saved to `reports` table with `report_type = 'investor_report'`
- Triggered automatically when: a 13F filing is processed OR an investor letter is processed
- Test: manually call `generate_investor_report` for a test investor with at least 5 extracted_mentions; verify a report is created in DB with non-empty `content_markdown` containing all sections from the template

---

### Task 20: Implement Daily Digest Generator
**Objective:** Build the daily digest that summarizes all investor activity.
**Files Affected:** `backend/services/report_service.py` (add method), `backend/jobs/digest_job.py`
**Dependencies:** Task 19
**Acceptance Criteria:**
- `generate_daily_digest(user_id)` queries all investors for the user, finds content_items processed in the last 24 hours, generates a digest report using the Daily Digest template from Section 10
- If no content was processed in the last 24 hours, skips digest generation for that user
- `digest_job.py` runs `generate_daily_digest` for all users at 07:00 UTC daily via APScheduler
- One `daily_digest` report created per user per day (not per investor)
- Test: insert several content_items processed in the last 24h for a test investor; trigger digest job; verify one `daily_digest` report created with content covering all investors

---

### Task 21: Implement Alert Scoring and Creation
**Objective:** Build the complete alerting system with scoring logic.
**Files Affected:** `backend/agents/nodes/alert_checker.py`, `backend/services/alert_service.py`
**Dependencies:** Task 20
**Acceptance Criteria:**
- `alert_service.py` implements `score_and_create_alerts(content_item, extracted_mentions, portfolio_changes)` using the scoring rules from Section 11
- Cooldown check: query `alerts` for same `(investor_id, alert_type)` in last 7 days before creating duplicate
- Creates appropriate alert types: `new_filing`, `new_company_mention`, `new_thesis`, `high_conviction`, `portfolio_change`
- `alert_checker.py` node calls `alert_service` with the current pipeline state
- Test: run alert checker for a content_item with high-conviction AAPL mention; verify an alert is created with score >= 60 and severity = 'high'

---

### Task 22: Implement Email Delivery
**Objective:** Send email alerts for high/critical severity items via Resend.
**Files Affected:** `backend/services/email_service.py`
**Dependencies:** Task 21, Resend API key in `.env`
**Acceptance Criteria:**
- `email_service.py` wraps Resend Python SDK to send transactional emails
- `send_alert_email(user, alert, report)` generates a clean HTML email from the alert and linked report data
- `send_daily_digest_email(user, report)` sends the daily digest markdown rendered as HTML
- Only called when `alert.severity in ('high', 'critical')` AND `alert.email_sent == False`
- After successful send, sets `alert.email_sent = True`
- Test: trigger a critical alert and verify Resend API is called with correct recipient, subject, and body (mock Resend in test; test against real Resend in staging)

---

### Task 23: Implement Content, Reports, and Alerts API Endpoints
**Objective:** Create all remaining API endpoints for content, reports, alerts, and search.
**Files Affected:** `backend/api/content.py`, `backend/api/reports.py`, `backend/api/alerts.py`, `backend/api/search.py`, `backend/api/admin.py`, `backend/app/main.py` (register routers)
**Dependencies:** Task 22
**Acceptance Criteria:**
- All endpoints from Section 12 implemented with correct request/response schemas
- `GET /api/v1/reports` supports `page`, `limit`, `investor_id`, `report_type`, `unread_only` query params
- `POST /api/v1/search` executes pgvector cosine similarity search against `content_chunks.embedding`, returns top-N results with chunk text and source metadata
- `GET /api/v1/admin/jobs/status` returns scheduler status and pending content_item count
- All endpoints protected by `get_current_user` dependency
- Test: end-to-end API test: create investor + source → trigger sync → verify content items appear in `/content` → verify report appears in `/reports` → verify alert appears in `/alerts`

---

### Task 24: Initialize Next.js Frontend
**Objective:** Set up Next.js 14 app with Supabase auth, Tailwind, shadcn/ui, and React Query.
**Files Affected:** `frontend/` directory — full initialization
**Dependencies:** Task 23
**Acceptance Criteria:**
- `npx create-next-app@latest` with TypeScript, Tailwind CSS, App Router
- Install: `@supabase/supabase-js`, `@supabase/auth-helpers-nextjs`, `@tanstack/react-query`, `react-markdown`, `remark-gfm`, `date-fns`
- `shadcn/ui` initialized with `neutral` base color
- `lib/supabase.ts` exports browser client and server client
- `lib/api.ts` exports a typed fetch wrapper with auto-attach of Supabase session token to `Authorization` header
- `next.config.ts` configures `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL`
- Test: `npm run dev` starts without errors; root page renders without crashes

---

### Task 25: Implement Authentication Pages
**Objective:** Build sign up, log in, and auth redirect logic.
**Files Affected:** `frontend/src/app/(auth)/login/page.tsx`, `frontend/src/app/(auth)/signup/page.tsx`, `frontend/src/app/layout.tsx`, `frontend/src/components/layout/Sidebar.tsx`
**Dependencies:** Task 24
**Acceptance Criteria:**
- Login page: email + password form → calls Supabase `signInWithPassword` → redirects to `/` on success → shows error on failure
- Signup page: name + email + password form → calls backend `POST /auth/signup` → redirects to `/` on success
- `app/layout.tsx` wraps with React Query `QueryClientProvider` and Supabase session provider
- Route protection: `(dashboard)/layout.tsx` checks Supabase session; redirects to `/login` if not authenticated
- Sidebar component: shows nav links (Dashboard, Investors, Reports, Alerts, Settings) and user email
- Test: sign up with a new email, log in, verify redirect to dashboard, log out, verify redirect to login

---

### Task 26: Implement Dashboard Page
**Objective:** Build the main dashboard with real data from the API.
**Files Affected:** `frontend/src/app/(dashboard)/page.tsx`, `frontend/src/components/dashboard/ActivityFeed.tsx`, `frontend/src/components/dashboard/StatCard.tsx`
**Dependencies:** Task 25
**Acceptance Criteria:**
- Dashboard fetches `/api/v1/investors` (count), `/api/v1/alerts?unread_only=true` (count), `/api/v1/reports?limit=5` (recent reports), `/api/v1/alerts?limit=10` (recent alerts)
- 3 stat cards displayed: Investors tracked, Unread alerts, Reports this week
- Recent reports list: title, report type badge (colored), investor name, generated date, 2-line summary, "Read" link
- Alert feed: severity color-coded left border, investor name, alert title, time-ago timestamp
- Empty state: if no investors, show "Add Your First Investor" CTA card
- Loading states via React Query `isLoading` skeleton placeholders
- Test: with test data in DB, dashboard shows correct counts and report/alert items

---

### Task 27: Implement Investors List and Add Investor Pages
**Objective:** Build the investors listing page and add/edit investor form.
**Files Affected:** `frontend/src/app/(dashboard)/investors/page.tsx`, `frontend/src/app/(dashboard)/investors/new/page.tsx`, `frontend/src/components/investors/InvestorCard.tsx`, `frontend/src/components/investors/InvestorForm.tsx`
**Dependencies:** Task 26
**Acceptance Criteria:**
- Investors page: grid of `InvestorCard` components showing name, description, source count, last synced, activity status
- Each card has: "View" button (links to detail page), "Sync Now" button (calls `/investors/{id}/sync`), toggle active/inactive
- "Add Investor" button opens `InvestorForm`
- `InvestorForm`: name (required), description (optional), CIK number (optional), submit → calls `POST /api/v1/investors` → redirects to investor detail page
- Edit investor: same form pre-populated, calls `PUT`
- Delete investor: confirmation dialog, calls `DELETE`
- Test: add an investor via form, verify it appears in the list, click "Sync Now", verify job triggers

---

### Task 28: Implement Source Manager Component
**Objective:** Build the inline source management UI for investor detail pages.
**Files Affected:** `frontend/src/components/investors/SourceManager.tsx`
**Dependencies:** Task 27
**Acceptance Criteria:**
- Lists existing sources with type icon, URL, active status toggle, last checked time, delete button
- "Add Source" form: source_type dropdown (sec_13f, website, youtube, rss, custom), URL field, optional label, check frequency select
- Source type icons: SEC shield icon, globe for website, play button for YouTube, RSS symbol
- Toggle active/inactive calls `PUT /api/v1/investors/{id}/sources/{source_id}`
- Delete calls `DELETE` with confirmation
- Add calls `POST /api/v1/investors/{id}/sources`
- Error display for failed sources (consecutive_failures > 0)
- Test: add a YouTube source, toggle it inactive, add an RSS source, delete the first one

---

### Task 29: Implement Investor Detail Page
**Objective:** Build the full investor detail page with all 5 tabs.
**Files Affected:** `frontend/src/app/(dashboard)/investors/[id]/page.tsx`, `frontend/src/components/investors/TimelineFeed.tsx`
**Dependencies:** Task 28
**Acceptance Criteria:**
- Header: investor name, last synced timestamp, "Sync Now" and "Edit" buttons
- Overview tab: stats (content items, reports, alerts), latest report preview card
- Timeline tab: chronological list of `content_items` with source icon, title, published date, processing status badge, "View Source" link. Filtered by content_type (All / Filing / Letter / Video / Newsletter tabs)
- Portfolio tab: table of latest `portfolio_changes` grouped by `filing_period`. Columns: Company, Ticker, Shares, Value ($K), Change type with colored badge. Only visible if SEC source exists.
- Reports tab: list of all reports for this investor with link to full report
- Sources tab: renders `SourceManager` component
- Test: navigate to a test investor's detail page with data; verify all tabs render without errors

---

### Task 30: Implement Reports Page and Report Viewer
**Objective:** Build the reports archive and full markdown report viewer.
**Files Affected:** `frontend/src/app/(dashboard)/reports/page.tsx`, `frontend/src/app/(dashboard)/reports/[id]/page.tsx`, `frontend/src/components/reports/ReportCard.tsx`, `frontend/src/components/reports/ReportViewer.tsx`
**Dependencies:** Task 29
**Acceptance Criteria:**
- Reports list page: filter sidebar (report type, investor, unread only, date range) + paginated card list
- `ReportCard`: title, type badge, investor name (if applicable), generated date, 2-sentence summary, unread indicator (bold border)
- Clicking card navigates to `/reports/{id}`
- `ReportViewer`: renders `content_markdown` using `react-markdown` with `remark-gfm` (for table support). Sticky header with investor name, generated date, "← Back", "Mark as Read" button. Source links section at bottom.
- Mark as Read calls `PUT /api/v1/reports/{id}/read`; removes unread indicator
- Test: navigate to a generated report; verify all sections render correctly (Executive Summary, tables, bulleted lists); click "Mark Read" and verify indicator disappears

---

### Task 31: Implement Alerts Page
**Objective:** Build the full alerts feed with filtering and read functionality.
**Files Affected:** `frontend/src/app/(dashboard)/alerts/page.tsx`, `frontend/src/components/alerts/AlertFeed.tsx`, `frontend/src/components/alerts/AlertItem.tsx`
**Dependencies:** Task 30
**Acceptance Criteria:**
- Alerts page: filter bar (severity, type, investor) + feed list sorted by `created_at DESC`
- `AlertItem`: severity color bar (left border, red=critical, orange=high, yellow=medium, gray=low), type icon, title, investor name, summary, time-ago timestamp, "View Report" link if `report_id` exists
- "Mark All Read" button at top calls `PUT /api/v1/alerts/read-all`
- Individual alert click marks it read via `PUT /api/v1/alerts/{id}/read`
- Unread count badge shown in sidebar navigation
- Test: verify critical alert shows in red, clicking it marks it read, badge count decrements

---

### Task 32: Implement Settings Page
**Objective:** Build the user settings page.
**Files Affected:** `frontend/src/app/(dashboard)/settings/page.tsx`
**Dependencies:** Task 31
**Acceptance Criteria:**
- Profile section: display name, email (read-only), "Change Password" button (triggers Supabase password reset email)
- Notifications section: toggles for "Email alerts for critical/high severity" and "Daily digest email" — calls `PUT /api/v1/auth/me` to update preferences stored in `users.metadata` JSONB
- Data section: "Export My Data" (future, shows as disabled)
- Delete Account: danger zone with confirmation dialog calling Supabase `deleteUser`
- Test: toggle notification preference, verify it persists on page refresh

---

### Task 33: Add Error Handling, Loading States, and Polish
**Objective:** Ensure all pages have proper loading states, error states, and empty states.
**Files Affected:** All frontend pages and components
**Dependencies:** Task 32
**Acceptance Criteria:**
- All data-fetching components show skeleton loaders while `isLoading = true`
- All forms show validation errors inline
- API errors display a toast notification (shadcn `toast` component)
- Empty states: "No investors yet", "No reports yet", "No alerts" — each with contextual CTA
- 404 page for unknown routes
- Global error boundary in `app/layout.tsx`
- Test: disconnect from backend; verify error toasts appear; verify empty states show on fresh account

---

### Task 34: Deploy Backend to Railway
**Objective:** Deploy the FastAPI backend to Railway with all environment variables.
**Files Affected:** `backend/Dockerfile`, `backend/railway.toml`, deployment docs
**Dependencies:** Task 33
**Acceptance Criteria:**
- `Dockerfile` based on `python:3.12-slim`, installs dependencies from `pyproject.toml`, runs `uvicorn` on port 8000
- `railway.toml` specifies build and start commands
- All environment variables configured in Railway dashboard
- `alembic upgrade head` runs as part of deployment start (pre-start command)
- Playwright Chromium installed in Docker image (for JS fallback scraping)
- Health check endpoint `GET /health` returns 200 after deploy
- Test: deployed backend responds to `GET /health`; `GET /api/v1/auth/me` with valid token returns user data

---

### Task 35: Deploy Frontend to Vercel
**Objective:** Deploy the Next.js frontend to Vercel.
**Files Affected:** `frontend/next.config.ts`, `frontend/.env.production`, Vercel project config
**Dependencies:** Task 34
**Acceptance Criteria:**
- Vercel project created, connected to GitHub repo, auto-deploy on main branch push
- Environment variables set in Vercel: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL` (pointing to Railway backend)
- Supabase Auth redirect URLs updated to include Vercel production domain
- CORS on backend updated to include Vercel production domain
- Full end-to-end test on production: sign up → add investor → wait for sync → read report

---

## 16. Risks and Simplifications

### Technical Risks

**Risk: APScheduler in-process vs. dedicated queue**
*Risk level: Medium.* APScheduler running inside the FastAPI process means background jobs compete with API requests for CPU/memory. For MVP at < 100 investors, this is acceptable.
*Simplification accepted.* If processing becomes a bottleneck, migrate to Celery + Redis later.

**Risk: Playwright cold starts**
*Risk level: Low-Medium.* Playwright requires Chromium to be installed in the Docker image, adding ~300MB to image size and 3–5 seconds to cold starts on Railway.
*Mitigation:* Only invoke Playwright as a fallback after httpx fails. Most investor letters are plain HTML.

**Risk: LangGraph pipeline blocking**
*Risk level: Low.* LangGraph runs synchronously within a background job thread. For long investor letters (> 50,000 chars), a single pipeline run may take 30–90 seconds due to multiple LLM calls.
*Mitigation:* Background jobs run in `APScheduler`'s thread pool; they don't block the API event loop. Set LLM call timeouts to 60s.

**Risk: Database connection pooling**
*Risk level: Low.* SQLAlchemy async engine with Supabase's connection pooler (PgBouncer) — ensure `pool_size=5, max_overflow=10` to avoid exhausting Supabase's connection limits on the free tier.

### Data Quality Risks

**Risk: SEC 13F XML format variations**
*Risk level: Medium.* Older 13F filings use different XML namespaces and field formats. Some firms use the `informationTable.xml` filename instead of `infotable.xml`.
*Mitigation:* Parse both filenames; handle both XML namespace patterns. Log parsing failures with filing URL for manual review.

**Risk: LLM hallucinating tickers**
*Risk level: Medium.* GPT-4o-mini may confidently produce invalid ticker symbols (e.g., "APPL" instead of "AAPL").
*Mitigation:* Regex validation of ticker format. Cross-reference against bundled S&P 1500 + Russell 2000 CSV. Set `ticker_symbol = null` if not validated; entity still stored as company name.

**Risk: Website structure changes**
*Risk level: Medium.* Investor websites may redesign, breaking scrapers. This will manifest as `content_items` with < 200 chars of cleaned text.
*Mitigation:* Alert the user if a website source produces no new content for 14 days despite checking. The user can update the URL.

**Risk: YouTube transcript quality**
*Risk level: Low.* Auto-generated captions are occasionally inaccurate (especially for financial terms, ticker symbols). This may reduce extraction quality.
*Mitigation:* Flag content items with `metadata["transcript_auto_generated"] = True`; the reporting agent prompt should note to treat such content with lower confidence.

### API Risks

**Risk: OpenAI API rate limits**
*Risk level: Medium.* If many investors are processed simultaneously, API rate limits (Tier 1: 500 RPM for GPT-4o-mini) may throttle processing.
*Mitigation:* `tenacity.retry` with exponential backoff handles transient 429s. APScheduler processes sources serially within a job run (not parallel) for MVP. This naturally limits concurrent API calls.

**Risk: YouTube Data API quota**
*Risk level: Low.* Default quota is 10,000 units/day. Fetching a playlist costs ~1–3 units; fetching video metadata costs ~1–3 units. At MVP scale (< 50 YouTube sources), daily usage is well under quota.
*Mitigation:* Store consumed quota in logs; add quota monitoring to admin dashboard in Phase 2.

**Risk: EDGAR rate limiting**
*Risk level: Low.* SEC requires a User-Agent header identifying your application and sets a rate limit of 10 requests/second.
*Mitigation:* Always include `User-Agent: HedgeFundIntelligence/1.0 (contact@example.com)` header; add `asyncio.sleep(0.2)` between EDGAR requests.

### Cost Risks

**Risk: LLM costs scaling with content volume**
*Risk level: Medium.* Each content item processed costs roughly:
- Entity extraction (3 chunks × GPT-4o-mini): ~$0.002
- Thesis extraction (GPT-4o): ~$0.05–$0.15
- Embeddings (5 chunks × text-embedding-3-small): ~$0.0001
- Report generation (GPT-4o): ~$0.10–$0.30
- Total per content item: ~$0.15–$0.45

At 20 investors × 3 new items/week = 60 items/week ≈ $9–$27/week. Acceptable for MVP.
*Mitigation:* Batch items processed per investor (avoid re-processing unchanged content). Cap report generation to once per investor per day maximum.

**Risk: Railway compute costs**
*Risk level: Low.* Railway Hobby plan starts at $5/month + usage. A single FastAPI + APScheduler service running moderate workloads costs ~$15–$30/month.

### Recommended MVP Simplifications

1. **Skip multi-turn LangGraph** for MVP. Run the pipeline as a linear chain, not a reactive agent with tool calls. Simpler to debug.
2. **One LLM provider for MVP** — use OpenAI only (GPT-4o-mini for extraction, GPT-4o for reports). Add Anthropic Claude as an alternative in Phase 2.
3. **No real-time updates** — frontend polls at 30-second intervals for alert count. WebSocket upgrade is Phase 2.
4. **No user-facing scheduler controls** — users cannot change the check frequency per source in the MVP UI (hardcoded defaults). The API supports it, but the Settings UI does not expose it yet.
5. **Email via Resend only** — no Slack, no webhook integrations. Email is sufficient for MVP alerting.
6. **Flat user model** — no organizations, no teams, no role-based access. Each user owns their own investors.

---

## 17. Future Roadmap

The following features are intentionally excluded from MVP. They should be built only after the core tracking + reporting loop is proven valuable to users.

**Podcast Monitoring**
Requires audio transcription (OpenAI Whisper API), feed parsing for audio files (RSS enclosures), and handling hours-long content. Adds significant complexity and cost (~$0.006/minute via Whisper). Defer until users specifically request it.

**Twitter/X Integration**
API costs ($100+/month for Basic tier) and ToS restrictions make this unattractive for MVP. Defer until the product demonstrates clear revenue justification.

**Cross-Investor Theme Analysis**
Identifying themes that appear across multiple investor communications simultaneously is high value but requires significant additional reporting infrastructure (cross-investor entity aggregation, theme clustering via embeddings). Deferred to prevent overcomplicating the MVP data model.

**Knowledge Graph**
Building a graph database of relationships between investors, companies, and themes enables powerful queries but is a separate architectural layer. Not needed until the linear reporting workflow is mature.

**Portfolio Reconstruction**
Reconstructing approximate real-time holdings by combining 13F data with earnings call signals, news, and SEC Form 4 filings is complex and introduces potential liability. Deferred indefinitely pending legal review.

**Multi-User Organizations / Teams**
Row-level security for shared investors, permission levels, and team workspaces require significant auth infrastructure changes. Build after the solo-user model is validated.

**Custom AI Agents**
Allowing users to define custom extraction rules or reporting templates requires a UI builder and agent configuration system. Not needed until users have clear feature requests beyond default reports.

**Real-Time Streaming Infrastructure**
WebSockets, SSE, or event-driven architecture add operational overhead without providing additional value at MVP scale. Polling is sufficient until users demand < 5-minute latency on updates.

**News Article Aggregation**
Monitoring news written *about* tracked investors adds breadth but not depth. The core value proposition is investor-authored content. Add NewsAPI integration in Phase 2 when users have validated the base workflow.

**Mobile Application**
React Native or Expo wrapper. Deferred until web product is stable and user demand justifies it. The web app should be fully responsive as a mobile substitute for MVP.

**Browser Extension**
A Chrome extension that highlights tracked companies when browsing the web adds convenience but requires separate development and distribution effort. Phase 3+.

**Advanced Backtesting / Analytics**
Correlating investor thesis mentions with subsequent stock performance is interesting research but outside the core intelligence-reporting scope. Requires significant financial data integration.

**Webhook / Zapier Integrations**
Sending alerts to Slack, Notion, or CRM systems is high-value for power users but adds integration surface area. Build after email alerting is validated.

---

*End of IMPLEMENTATION PLAN v1.0*

*This document is intended to be directly executed by Claude Code, task by task, in sequence. Each task contains sufficient detail to implement without requiring additional architectural decisions.*
