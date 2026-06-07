# Architecture Decisions

This document records the key architectural decisions made for the Hedge Fund Intelligence Platform, the rationale behind each, and the trade-offs accepted.

---

## Table of Contents

1. [High-Level Architecture](#high-level-architecture)
2. [Data Flow](#data-flow)
3. [Component Decisions](#component-decisions)
4. [Database Design Decisions](#database-design-decisions)
5. [AI Pipeline Design](#ai-pipeline-design)
6. [Ingestion Strategy](#ingestion-strategy)
7. [Scheduling Strategy](#scheduling-strategy)
8. [Security Decisions](#security-decisions)
9. [Trade-offs and Deferred Decisions](#trade-offs-and-deferred-decisions)

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    USER'S BROWSER                           │
│              Next.js Frontend (Vercel)                      │
│     Dashboard / Investors / Reports / Alerts / Settings     │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTPS REST API
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                 FastAPI Backend (Railway)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │   REST API   │  │  APScheduler │  │   LangGraph      │   │
│  │  (routers)   │  │  (jobs)      │  │   Pipeline       │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
│         │                 │                   │             │
│  ┌──────▼─────────────────▼───────────────────▼──────────┐  │
│  │               Service Layer                           │  │
│  │  InvestorService / ContentService / ReportService     │  │
│  └──────────────────────────┬────────────────────────────┘  │
│                             │                               │
│  ┌──────────────────────────▼────────────────────────────┐  │
│  │              Source Adapters / Loaders                │  │
│  │  SEC EDGAR │ WebScraper │ YouTube │ RSS               │  │
│  └──────────────────────────────────────────────────────────│
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  Supabase (Managed)                         │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────┐   │
│  │  PostgreSQL    │  │   pgvector     │  │  Supabase    │   │
│  │  (all tables)  │  │  (embeddings)  │  │  Auth        │   │
│  └────────────────┘  └────────────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
      ┌──────────┐  ┌─────────┐  ┌────────┐
      │  OpenAI  │  │ EDGAR   │  │ Resend │
      │  API     │  │ (free)  │  │ Email  │
      └──────────┘  └─────────┘  └────────┘
```

**Decision: Modular monolith, not microservices.**

For an MVP with < 100 investors and < 500 sources, a single Railway deployment is simpler to operate, debug, and deploy. The codebase is structured so services can be split later if needed — each layer (api, services, agents, ingestion, jobs) has clear boundaries and minimal coupling.

---

## Data Flow

### Content Entry Flow

```
APScheduler fires ingestion job
  └─► Source Adapter fetches URL(s)
        └─► compute SHA-256 content hash
              └─► if hash exists in content_items → skip (dedup)
                    └─► store ContentItem (status=pending, raw_text)
```

### Content Processing Flow

```
process_pending job fires (every 5 min)
  └─► fetch all ContentItems where status=pending
        └─► for each item: run LangGraph pipeline
              ├─► normalizer: clean HTML, strip boilerplate
              ├─► chunker: RecursiveCharacterTextSplitter (4000 chars, 400 overlap)
              ├─► entity_extractor: GPT-4o-mini → extracted_mentions rows
              ├─► thesis_extractor: GPT-4o → investment thesis per company (skipped for 13F filings)
              ├─► embedder: OpenAI text-embedding-3-small → content_chunks rows
              ├─► report_generator: GPT-4o → reports row (if triggered)
              └─► alert_checker: rule-based scoring → alerts rows
```

### Report Generation Flow

```
Two triggers:
  1. Event-driven: new 13F filing detected → generate immediately
  2. Scheduled: daily 07:00 UTC → digest_job generates for all users

ReportService.generate_investor_report():
  └─► query extracted_mentions (past 30 days) + portfolio_changes (latest 13F)
        └─► GPT-4o generates structured markdown report
              └─► store in reports table
                    └─► create alert record (alert_type=daily_digest_ready or new_filing)
                          └─► if score >= 80 → send email via Resend
```

---

## Component Decisions

### FastAPI over Django / Flask

- **Async-native**: EDGAR requests, embedding API calls, and DB operations are all I/O-bound. FastAPI's native async support avoids thread pool overhead.
- **Pydantic v2**: Request validation and response serialization with near-zero boilerplate.
- **Auto-docs**: OpenAPI/Swagger docs generated automatically — critical for frontend development.

### SQLAlchemy 2.0 async over raw SQL or alternative ORMs

- **Type safety**: Mapped columns with Python type annotations enable IDE completion and runtime validation.
- **Alembic**: First-class migration tooling. `alembic revision --autogenerate` works directly from ORM models.
- **Async support**: SQLAlchemy 2.0 async with `asyncpg` driver eliminates thread blocking on DB queries.

### Supabase over plain PostgreSQL + custom auth

- **Auth included**: Supabase Auth handles email confirmation, password hashing, JWT issuance, and session management. Saves 2–3 days of auth plumbing.
- **pgvector included**: Supabase enables pgvector as a first-party extension — no separate vector database (Pinecone, Weaviate) needed for MVP.
- **Managed infrastructure**: Automated backups, connection pooling via PgBouncer, SSL — all included.
- **Trade-off**: Supabase's PostgreSQL is not as configurable as a dedicated instance. For MVP scale (< 100 investors), this is fine.

### LangGraph for AI pipeline over direct LLM calls

- **State management**: LangGraph `TypedDict` state makes intermediate results (chunks, entities, theses) explicit and inspectable.
- **Conditional routing**: Filing content skips thesis extraction (`content_type == 'filing'`). Report generation is optional based on `report_triggered` flag. Clean conditional edge syntax in LangGraph vs. ad-hoc if/else chains.
- **Composability**: Each node is a pure function — independently testable without running the full pipeline.
- **Trade-off**: LangGraph adds import overhead and graph compilation. For simple 6-node sequential pipelines, direct function calls would work. LangGraph is chosen for the conditional routing and future extensibility.

### APScheduler (in-process) over Celery + Redis

- **No Redis dependency**: APScheduler runs inside the FastAPI process. No separate worker process, broker, or result backend to deploy.
- **Sufficient for MVP**: < 100 investors with < 500 sources can be processed well within the scheduling windows.
- **Trade-off**: If the Railway deployment restarts, APScheduler loses state. Jobs will resume on the next scheduled window (acceptable for this use case — worst case is a 6-hour miss for SEC filings).
- **Migration path**: If job complexity grows, the service layer can be extracted and Celery/Redis added without changing business logic.

### PGVector over Pinecone / Weaviate

- **Single database**: All content data and vectors in one system simplifies backup, foreign key constraints, and query joins.
- **HNSW index**: Supabase supports HNSW (Hierarchical Navigable Small World) index for pgvector, providing O(log n) approximate nearest-neighbor search — fast enough for MVP scale.
- **Trade-off**: PGVector doesn't support multi-tenancy or filtering as flexibly as Pinecone. For MVP, we filter by `investor_id` in the `similarity_search_with_score` call using LangChain's `PGVector` wrapper.

---

## Database Design Decisions

### UUIDs as primary keys

- No sequential ID leakage (users can't enumerate records by incrementing an integer)
- Distributable (can generate client-side without DB round-trip)
- Consistent type across all tables → simpler foreign key definitions

### Separate `content_chunks` table (not JSONB array in `content_items`)

- **Indexability**: The HNSW vector index on `content_chunks.embedding` only works on a dedicated column, not inside a JSONB array.
- **Queryability**: Can query chunks independently (e.g., "find all chunks matching this query for investor X").
- **Scalability**: A single content item can produce 10–50 chunks. Storing as separate rows avoids JSONB bloat.

### `content_hash` deduplication

- SHA-256 of raw text → stored as `content_hash TEXT` with `UNIQUE` constraint.
- On insert, attempt INSERT — if `UniqueViolation`, the item is a duplicate → skip silently.
- Handles cross-source duplicates (same article picked up by both RSS and website scraper).

### `portfolio_changes` as a separate table (not JSONB in `content_items`)

- 13F filings list 50–500 holdings. Storing as JSONB would prevent efficient querying by ticker.
- `portfolio_changes` has indexes on `(investor_id)`, `(ticker_symbol)`, and `(investor_id, filing_period)`.
- Enables: "show me all investors who held NVDA in Q3 2024" — a cross-investor query impossible with JSONB.

### Timestamp columns with `timezone=True`

- All timestamps stored as `TIMESTAMPTZ` (timezone-aware) in PostgreSQL.
- Avoids daylight saving time bugs when comparing timestamps across timezones.
- All business logic uses `datetime.now(timezone.utc)` (aware) not `datetime.utcnow()` (naive).

---

## AI Pipeline Design

### Two-model strategy

| Node | Model | Rationale |
|------|-------|-----------|
| `entity_extractor` | GPT-4o-mini | Fast and cheap. Entity extraction is well-defined with few-shot examples. |
| `thesis_extractor` | GPT-4o | Quality matters here — investment thesis extraction requires nuanced understanding of hedge fund language. |
| `report_generator` | GPT-4o | Report quality is the primary user-facing output. Cost justified. |
| `embedder` | `text-embedding-3-small` | Best cost/quality ratio. 1536 dimensions. ~3,000 tokens/dollar. |

### Chunking strategy

- `RecursiveCharacterTextSplitter` with `chunk_size=4000` characters (~1000 tokens), `chunk_overlap=400` characters.
- Separators: `["\n\n", "\n", ". ", " "]` — preserves paragraph and sentence boundaries.
- Rationale: 4000 chars fits comfortably within GPT-4o-mini's context for batch entity extraction (3 chunks per call).

### Thesis extraction on full text (not chunks)

- Thesis identification requires holistic understanding of the document.
- For texts < 16,000 characters: run on `cleaned_text` directly.
- For longer texts: select the 5 chunks with the highest entity density (most mentions) as proxy for the most content-rich sections.

### Alert scoring (rule-based, not LLM)

- LLM scoring of alert severity would add latency and cost on every content item.
- Rule-based additive scoring (documented in IMPLEMENTATION_PLAN.md § 11) is deterministic, auditable, and instant.
- The most important signals (new 13F: +40, new position: +20, high conviction: +20) correctly push filings to critical severity in almost all cases.

---

## Ingestion Strategy

### SEC EDGAR: EDGAR REST API (not scraping)

- `https://data.sec.gov/submissions/CIK{cik}.json` is the official, free, unrestricted EDGAR API.
- No rate limits for reasonable usage (1,000 requests/day baseline, higher for data consumers).
- Returns structured JSON — no HTML parsing needed.
- 13F holdings in XML format (`infotable.xml`) — parsed with Python's `xml.etree.ElementTree`.

### Websites: 4-tier scraping strategy

1. **Tier 1 — `WebBaseLoader` (httpx + BeautifulSoup)**: Simple static pages. Fast, no browser needed.
2. **Tier 2 — `RecursiveUrlLoader` + trafilatura**: Multi-page archive sites. Crawls up to depth 2.
3. **Tier 3 — `AsyncChromiumLoader` (Playwright)**: JS-rendered SPAs. Only invoked if Tier 1 returns < 200 characters.
4. **Tier 4 — `PDFPlumberLoader`**: URLs ending in `.pdf`.
5. **Tier 5 — `SitemapLoader`**: Sites with `config.has_sitemap = true`.

Playwright is the fallback of last resort because it's 10x slower than httpx and requires a running Chromium process.

### YouTube: yt-dlp over YouTube Data API v3

- `yt-dlp` lists channel videos without requiring an API key.
- `youtube-transcript-api` fetches captions without an API key.
- This avoids the YouTube Data API v3 quota (10,000 units/day) for the common case of channel listing + transcript fetching.
- **Trade-off**: yt-dlp is a third-party tool that may break when YouTube changes its internal API. This is acceptable for MVP; the alternative (official API) is added to Phase 2.

### Content deduplication via SHA-256 hash

- Hash computed on `raw_text` (before cleaning) to catch identical content even if fetched from different URLs.
- Stored in `content_items.content_hash` with a `UNIQUE` constraint.
- Failed inserts due to duplicate hashes are silently ignored (not errors).

---

## Scheduling Strategy

| Job | Frequency | Rationale |
|-----|-----------|-----------|
| `ingest_sec_13f` | Daily at 06:00 UTC | 13Fs are quarterly. Daily check is more than sufficient. Early UTC catches US market open. |
| `ingest_websites` | Every 4 hours | Investor letters are infrequent. 4h window minimizes load while ensuring same-day discovery. |
| `ingest_rss` | Every 2 hours | RSS feeds are designed for frequent polling. 2h is respectful and responsive. |
| `ingest_youtube` | Every 6 hours | Videos are uploaded at most daily. 6h ensures same-day discovery. |
| `process_pending` | Every 5 minutes | Minimizes lag between content ingestion and AI processing. 5min is aggressive but LangGraph pipeline is fast (~10–30s per item). |
| `daily_digest` | Daily at 07:00 UTC | 07:00 UTC = before US market open. Users see digest before markets open. |

---

## Security Decisions

### JWT validation (not session cookies)

- Supabase Auth issues JWTs signed with `SUPABASE_JWT_SECRET`.
- Every API request validates the JWT in `api/deps.py` using `python-jose`.
- Stateless: no server-side session store needed.
- `options={"verify_aud": False}` disables audience claim check (Supabase JWTs don't include `aud` by default).

### Service key (not anon key) for auth operations

- `SUPABASE_SERVICE_KEY` bypasses Row Level Security (RLS) for admin operations (creating users, etc.).
- This key is backend-only — never exposed to the frontend.
- The frontend uses the Supabase `anon` key for client-side auth interactions.

### Row-level ownership (application-layer)

- All data queries include `WHERE user_id = current_user.id` filters.
- Supabase RLS is not configured on the custom tables (the backend service key bypasses RLS anyway).
- Application-layer enforcement is simpler to reason about for MVP. Supabase RLS can be added later for defense-in-depth.

---

## Trade-offs and Deferred Decisions

| Decision | Choice Made | Deferred Alternative |
|----------|-------------|---------------------|
| Background job runner | APScheduler (in-process) | Celery + Redis (when job count > 50 or cross-server coordination needed) |
| Real-time updates | HTTP polling | WebSockets (when < 100ms latency matters) |
| Vector database | pgvector (in Supabase) | Pinecone / Weaviate (when > 10M vectors or multi-tenant isolation needed) |
| Twitter/X monitoring | Deferred (API cost) | Twitter API v2 Basic ($100/month) in Phase 2 |
| Multi-user orgs | Single-user accounts | Organizations + team roles in Phase 2 |
| Audio/podcast | Deferred (complex pipeline) | Whisper transcription + existing pipeline in Phase 3 |
| Production observability | structlog only | Sentry + Datadog in production |
| Frontend | Next.js (Phase 5) | React Native for mobile (Phase 3+) |
