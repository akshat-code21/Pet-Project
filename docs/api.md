# API Reference

**Base URL:** `http://localhost:8000/api/v1` (development) | `https://your-app.railway.app/api/v1` (production)

**Authentication:** All protected endpoints require `Authorization: Bearer <supabase_jwt>` header.

**Interactive Docs:** Available at `/docs` (Swagger UI) and `/redoc` in non-production environments.

---

## Table of Contents

- [Health](#health)
- [Authentication](#authentication)
- [Investors](#investors)
- [Sources](#sources)
- [Content](#content)
- [Reports](#reports)
- [Alerts](#alerts)
- [Search](#search)
- [Admin](#admin)
- [Error Responses](#error-responses)
- [Enumerations](#enumerations)

---

## Health

### `GET /health`

Health check endpoint. No authentication required.

**Response `200 OK`:**
```json
{"status": "ok"}
```

---

## Authentication

All auth endpoints live under `/api/v1/auth`.

---

### `POST /auth/signup`

Register a new user. Creates a Supabase Auth account and a local `users` row.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "SecurePass123!",
  "full_name": "Jane Doe"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `email` | string (email) | ✅ | Must be valid email format |
| `password` | string | ✅ | Supabase enforces minimum length |
| `full_name` | string | ❌ | Optional display name |

**Response `201 Created`:**
```json
{
  "user": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "email": "user@example.com",
    "full_name": "Jane Doe"
  },
  "session": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "v1.M9jd..."
  }
}
```

**Errors:**
- `400` — Email already registered or Supabase signup failed

---

### `POST /auth/login`

Login with email + password. Returns JWT tokens.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "SecurePass123!"
}
```

**Response `200 OK`:**
```json
{
  "user": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "email": "user@example.com",
    "full_name": "Jane Doe"
  },
  "session": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "v1.M9jd..."
  }
}
```

**Errors:**
- `401` — Invalid credentials

---

### `POST /auth/logout`

🔒 **Requires auth.**

Clears the server-side session. The JWT is not actively invalidated (Supabase handles expiry), but the server logs the logout.

**Response `200 OK`:**
```json
{"message": "logged out"}
```

---

### `GET /auth/me`

🔒 **Requires auth.**

Returns the currently authenticated user's profile.

**Response `200 OK`:**
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "email": "user@example.com",
  "full_name": "Jane Doe"
}
```

**Errors:**
- `401` — Invalid or expired token

---

## Investors

Base path: `/api/v1/investors`

All endpoints require authentication.

---

### `GET /investors`

List all investors tracked by the authenticated user.

**Response `200 OK`:**
```json
[
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "user_id": "a1b2c3d4-...",
    "name": "Bill Ackman",
    "description": "Pershing Square Capital Management",
    "cik_number": "0001336528",
    "is_active": true,
    "last_synced_at": "2024-01-15T10:30:00Z",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-15T10:30:00Z",
    "sources_count": 3
  }
]
```

---

### `POST /investors`

Create a new investor to track.

**Request Body:**
```json
{
  "name": "Bill Ackman",
  "description": "Pershing Square Capital Management",
  "cik_number": "0001336528"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string (1–255 chars) | ✅ | Display name for the investor |
| `description` | string | ❌ | Optional notes or firm name |
| `cik_number` | string (1–10 digits) | ❌ | SEC CIK — auto-padded to 10 digits |

**Response `201 Created`:** Same as investor object in list response above.

---

### `GET /investors/{investor_id}`

Get investor detail including sources, stats, and activity counts.

**Path Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `investor_id` | UUID | Investor identifier |

**Response `200 OK`:**
```json
{
  "id": "3fa85f64-...",
  "name": "Bill Ackman",
  "description": "Pershing Square Capital Management",
  "cik_number": "0001336528",
  "is_active": true,
  "last_synced_at": "2024-01-15T10:30:00Z",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "sources_count": 3,
  "stats": {
    "content_items": 47,
    "reports": 5,
    "unread_alerts": 2
  }
}
```

**Errors:**
- `404` — Investor not found or not owned by user

---

### `PUT /investors/{investor_id}`

Update investor fields. All fields are optional (partial update).

**Request Body:**
```json
{
  "name": "Bill Ackman",
  "description": "Updated description",
  "cik_number": "0001336528",
  "is_active": true
}
```

**Response `200 OK`:** Updated investor object.

**Errors:**
- `404` — Investor not found

---

### `DELETE /investors/{investor_id}`

Delete investor and all associated data (sources, content items, portfolio changes, reports, alerts) via cascade.

**Response `204 No Content`**

**Errors:**
- `404` — Investor not found

---

### `POST /investors/{investor_id}/sync`

Queue an immediate ingestion run for all active sources belonging to this investor. Runs as an async background task.

**Response `200 OK`:**
```json
{
  "message": "sync queued",
  "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

**Errors:**
- `404` — Investor not found

---

## Sources

Base path: `/api/v1/investors/{investor_id}/sources`

Sources are always nested under an investor. All endpoints require authentication.

---

### `GET /investors/{investor_id}/sources`

List all sources for an investor.

**Response `200 OK`:**
```json
[
  {
    "id": "b2c3d4e5-...",
    "investor_id": "3fa85f64-...",
    "source_type": "sec_13f",
    "url": "https://www.sec.gov/cgi-bin/browse-edgar?...",
    "label": "Ackman 13F Filings",
    "config": {"cik_number": "0001336528"},
    "is_active": true,
    "last_checked_at": "2024-01-15T06:00:00Z",
    "last_successful_at": "2024-01-15T06:05:00Z",
    "check_frequency_hours": 6,
    "consecutive_failures": 0,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-15T06:05:00Z"
  }
]
```

---

### `POST /investors/{investor_id}/sources`

Add a new source to an investor.

**Request Body:**
```json
{
  "source_type": "youtube",
  "url": "https://www.youtube.com/@PershingSquare",
  "label": "Pershing Square YouTube",
  "check_frequency_hours": 12,
  "config": {}
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `source_type` | enum | ✅ | One of: `sec_13f`, `website`, `youtube`, `rss`, `custom` |
| `url` | string (URL) | ✅ | Must start with `http://` or `https://`. YouTube URLs must contain `youtube.com` or `youtu.be` |
| `label` | string | ❌ | Human-readable label |
| `check_frequency_hours` | integer (1–720) | ❌ | Default: 24 |
| `config` | object | ❌ | Source-specific config. For `sec_13f`: `{"cik_number": "..."}` |

**Response `201 Created`:** Source object (see GET response above).

**Errors:**
- `404` — Investor not found
- `422` — Invalid URL format or source_type validation failed

---

### `PUT /investors/{investor_id}/sources/{source_id}`

Update a source.

**Request Body:**
```json
{
  "label": "Updated label",
  "is_active": false,
  "check_frequency_hours": 24,
  "config": {"cik_number": "0001336528"}
}
```

All fields are optional. Commonly used to toggle `is_active`.

**Response `200 OK`:** Updated source object.

**Errors:**
- `404` — Source not found or not owned by user

---

### `DELETE /investors/{investor_id}/sources/{source_id}`

Remove a source. Associated content items are cascaded.

**Response `204 No Content`**

**Errors:**
- `404` — Source not found

---

## Content

Base path: `/api/v1/content`

Read-only endpoints for browsing ingested content and portfolio data.

---

### `GET /content/investors/{investor_id}/content`

List content items ingested for an investor. Ordered by `created_at DESC`.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `content_type` | string | — | Filter: `filing`, `article`, `video`, `newsletter`, `website_page` |
| `limit` | integer (1–200) | 50 | Page size |
| `offset` | integer (≥0) | 0 | Pagination offset |

**Response `200 OK`:**
```json
[
  {
    "id": "c3d4e5f6-...",
    "source_id": "b2c3d4e5-...",
    "investor_id": "3fa85f64-...",
    "content_type": "filing",
    "title": "13F-HR Filing Q3 2024",
    "url": "https://www.sec.gov/Archives/edgar/data/...",
    "published_at": "2024-11-14T00:00:00Z",
    "processing_status": "completed",
    "processing_error": null,
    "metadata": {
      "filing_period": "2024-Q3",
      "accession_number": "0001336528-24-000023"
    },
    "created_at": "2024-11-14T06:05:00Z"
  }
]
```

**Processing statuses:** `pending` | `processing` | `completed` | `failed` | `skipped`

---

### `GET /content/investors/{investor_id}/portfolio`

Get parsed 13F portfolio holdings for an investor. Only populated after a 13F filing is processed.

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `filing_period` | string | Filter by period, e.g. `2024-Q3` |

**Response `200 OK`:**
```json
[
  {
    "id": "d4e5f6g7-...",
    "investor_id": "3fa85f64-...",
    "ticker_symbol": "NVDA",
    "company_name": "NVIDIA Corporation",
    "cusip": "67066G104",
    "change_type": "new_position",
    "shares_previous": 0,
    "shares_current": 1500000,
    "value_usd": 2100000,
    "percent_of_portfolio": 18.500,
    "filing_period": "2024-Q3",
    "report_date": "2024-09-30",
    "created_at": "2024-11-14T06:05:00Z"
  }
]
```

**Change types:** `new_position` | `increased` | `decreased` | `closed` | `unchanged`

---

## Reports

Base path: `/api/v1/reports`

---

### `GET /reports`

List reports for the authenticated user, newest first.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | integer (≥1) | 1 | Page number |
| `limit` | integer (1–100) | 20 | Page size |
| `investor_id` | UUID | — | Filter to specific investor |
| `report_type` | string | — | `investor_report` \| `daily_digest` \| `event_report` |
| `unread_only` | boolean | false | Show only unread reports |

**Response `200 OK`:**
```json
{
  "data": [
    {
      "id": "e5f6g7h8-...",
      "user_id": "a1b2c3d4-...",
      "investor_id": "3fa85f64-...",
      "report_type": "investor_report",
      "title": "Intelligence Report: Bill Ackman — Q3 2024",
      "summary": "Pershing Square filed 13F for Q3 2024. New position in NVDA worth $2.1B...",
      "is_read": false,
      "period_start": "2024-07-01T00:00:00Z",
      "period_end": "2024-09-30T00:00:00Z",
      "generated_at": "2024-11-14T07:30:00Z",
      "created_at": "2024-11-14T07:30:00Z",
      "investor_name": "Bill Ackman"
    }
  ],
  "total": 15,
  "page": 1
}
```

---

### `GET /reports/{report_id}`

Get full report content including the markdown body.

**Response `200 OK`:**
```json
{
  "id": "e5f6g7h8-...",
  "user_id": "a1b2c3d4-...",
  "investor_id": "3fa85f64-...",
  "report_type": "investor_report",
  "title": "Intelligence Report: Bill Ackman — Q3 2024",
  "summary": "...",
  "content_markdown": "# Intelligence Report: Bill Ackman\n\n## Executive Summary\n...",
  "source_item_ids": ["c3d4e5f6-...", "f7g8h9i0-..."],
  "is_read": false,
  "period_start": "2024-07-01T00:00:00Z",
  "period_end": "2024-09-30T00:00:00Z",
  "generated_at": "2024-11-14T07:30:00Z",
  "created_at": "2024-11-14T07:30:00Z",
  "investor_name": "Bill Ackman"
}
```

**Errors:**
- `404` — Report not found

---

### `PUT /reports/{report_id}/read`

Mark a report as read.

**Response `200 OK`:** Updated report object (same schema as list item, `is_read: true`).

**Errors:**
- `404` — Report not found

---

### `POST /reports/generate`

Queue a report generation for an investor. Runs as an async background task — returns immediately.

**Request Body:**
```json
{
  "investor_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "report_type": "investor_report"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `investor_id` | UUID | ✅ | Target investor |
| `report_type` | string | ❌ | Default: `investor_report`. Options: `investor_report`, `daily_digest`, `event_report` |

**Response `202 Accepted`:**
```json
{
  "message": "report generation queued",
  "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

---

## Alerts

Base path: `/api/v1/alerts`

---

### `GET /alerts`

List alerts for the authenticated user, sorted by severity then `created_at DESC`.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | integer (≥1) | 1 | Page number |
| `limit` | integer (1–100) | 20 | Page size |
| `investor_id` | UUID | — | Filter to specific investor |
| `severity` | string | — | `low` \| `medium` \| `high` \| `critical` |
| `unread_only` | boolean | false | Show only unread alerts |

**Response `200 OK`:**
```json
{
  "data": [
    {
      "id": "f6g7h8i9-...",
      "user_id": "a1b2c3d4-...",
      "investor_id": "3fa85f64-...",
      "content_item_id": "c3d4e5f6-...",
      "report_id": "e5f6g7h8-...",
      "alert_type": "new_filing",
      "title": "🚨 Bill Ackman: New 13F Filing Detected",
      "summary": "Pershing Square filed 13F for Q3 2024. New positions: NVDA (+$2.1B). Closed: GOOGL.",
      "severity": "critical",
      "score": 92,
      "is_read": false,
      "email_sent": true,
      "metadata": {"filing_period": "2024-Q3"},
      "created_at": "2024-11-14T06:05:00Z",
      "investor_name": "Bill Ackman"
    }
  ],
  "unread_count": 7,
  "total": 23
}
```

**Alert types:** `new_filing` | `new_company_mention` | `new_thesis` | `high_conviction` | `portfolio_change` | `daily_digest_ready`

---

### `PUT /alerts/{alert_id}/read`

Mark a single alert as read.

**Response `200 OK`:** Updated alert object with `is_read: true`.

**Errors:**
- `404` — Alert not found

---

### `PUT /alerts/read-all`

Mark all unread alerts as read for the authenticated user.

**Response `200 OK`:**
```json
{
  "message": "all alerts marked as read",
  "count": 7
}
```

---

## Search

### `POST /search`

Semantic vector search across all processed content using pgvector cosine similarity.

**Request Body:**
```json
{
  "query": "Ackman thesis on interest rates and real estate",
  "investor_id": null,
  "limit": 10
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `query` | string (1–500 chars) | ✅ | Natural language search query |
| `investor_id` | UUID | ❌ | Scope search to one investor |
| `limit` | integer (1–50) | ❌ | Default: 10 |

**Response `200 OK`:**
```json
{
  "data": [
    {
      "content_item_id": "c3d4e5f6-...",
      "chunk_text": "Ackman discussed the impact of rising interest rates on real estate valuations...",
      "investor_name": "Bill Ackman",
      "source_url": "https://pershingas.com/letters/q3-2024",
      "published_at": "2024-10-15T00:00:00Z",
      "similarity": 0.8741
    }
  ],
  "query": "Ackman thesis on interest rates and real estate"
}
```

> **Note:** Results are returned in descending similarity order. The search uses OpenAI `text-embedding-3-small` for query embedding and pgvector HNSW index for fast approximate nearest-neighbor lookup.

---

## Admin

Base path: `/api/v1/admin`

> These endpoints are authenticated but not role-restricted in MVP. In production, consider restricting to admin users only.

---

### `GET /admin/jobs/status`

Get scheduler status and pending content item count.

**Response `200 OK`:**
```json
{
  "data": {
    "scheduler_running": true,
    "jobs": [
      {"id": "ingest_sec_13f", "next_run": "2024-01-16 06:00:00+00:00"},
      {"id": "ingest_websites", "next_run": "2024-01-15 14:00:00+00:00"},
      {"id": "ingest_rss", "next_run": "2024-01-15 12:00:00+00:00"},
      {"id": "ingest_youtube", "next_run": "2024-01-15 18:00:00+00:00"},
      {"id": "process_pending", "next_run": "2024-01-15 10:05:00+00:00"},
      {"id": "daily_digest", "next_run": "2024-01-16 07:00:00+00:00"}
    ],
    "pending_content_items": 3
  }
}
```

---

### `POST /admin/jobs/trigger`

Immediately trigger a scheduled job by ID.

**Request Body:**
```json
{
  "job": "process_pending"
}
```

| Job ID | Description |
|--------|-------------|
| `ingest_sec_13f` | Run SEC EDGAR ingestion for all 13F sources |
| `ingest_websites` | Run website scraping for all website sources |
| `ingest_rss` | Run RSS polling for all RSS sources |
| `ingest_youtube` | Run YouTube ingestion for all YouTube sources |
| `process_pending` | Run LangGraph pipeline on all pending content items |
| `daily_digest` | Generate daily digest reports for all users |

**Response `200 OK`:**
```json
{"message": "job process_pending triggered"}
```

---

## Error Responses

All errors follow HTTP standard status codes with a JSON detail body:

```json
{
  "detail": "Investor not found"
}
```

| Status | Meaning |
|--------|---------|
| `400` | Bad request — validation error or business logic rejection |
| `401` | Unauthorized — missing, invalid, or expired JWT |
| `404` | Not found — resource doesn't exist or isn't owned by the user |
| `422` | Unprocessable Entity — Pydantic validation error with field details |
| `500` | Internal server error — logged via structlog |

**422 validation errors** include a `detail` array:
```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "source_type"],
      "msg": "Input should be 'sec_13f', 'website', 'youtube', 'rss' or 'custom'",
      "input": "invalid_type"
    }
  ]
}
```

---

## Enumerations

### Source Types

| Value | Description |
|-------|-------------|
| `sec_13f` | SEC EDGAR 13F filings (requires `config.cik_number`) |
| `website` | Generic website or investor letter page |
| `youtube` | YouTube channel (URL must contain youtube.com or youtu.be) |
| `rss` | RSS or Atom feed |
| `custom` | Custom URL, treated like website |

### Content Types

| Value | Description |
|-------|-------------|
| `filing` | SEC 13F or regulatory filing |
| `article` | Blog post, newsletter article, web page |
| `video` | YouTube video (transcript as text) |
| `newsletter` | RSS-fetched newsletter entry |
| `website_page` | Generic web page |

### Processing Status

| Value | Description |
|-------|-------------|
| `pending` | Fetched, waiting for AI pipeline |
| `processing` | Currently being processed by LangGraph |
| `completed` | Successfully processed, entities + embeddings stored |
| `failed` | Processing failed (see `processing_error` field) |
| `skipped` | Content too short or duplicate |

### Report Types

| Value | Description |
|-------|-------------|
| `investor_report` | Per-investor intelligence report |
| `daily_digest` | Cross-investor daily digest |
| `event_report` | Triggered by a specific event (e.g. new 13F) |

### Alert Types

| Value | Description |
|-------|-------------|
| `new_filing` | New 13F filing detected |
| `new_company_mention` | First-time mention of a company by this investor |
| `new_thesis` | New investment thesis extracted |
| `high_conviction` | High-conviction language detected |
| `portfolio_change` | Position size change > 20% |
| `daily_digest_ready` | Daily digest report generated |

### Alert Severity

| Value | Score Range | Email Sent |
|-------|-------------|------------|
| `low` | 0–39 | No (batched in digest) |
| `medium` | 40–59 | No (batched in digest) |
| `high` | 60–79 | No |
| `critical` | 80–100 | ✅ Yes, immediately |

### Entity Types (extracted_mentions)

| Value | Description |
|-------|-------------|
| `company` | Public or private company |
| `ticker` | Stock ticker symbol |
| `person` | Named individual |
| `theme` | Investment theme (e.g. "AI infrastructure") |
| `sector` | Market sector |
| `macro_theme` | Macro-economic theme |

### Change Types (portfolio_changes)

| Value | Description |
|-------|-------------|
| `new_position` | Position not held in prior period |
| `increased` | Shares increased vs prior period |
| `decreased` | Shares decreased vs prior period |
| `closed` | Position fully exited |
| `unchanged` | No change in shares |

### Sentiment

| Value | Description |
|-------|-------------|
| `bullish` | Positive/optimistic language |
| `bearish` | Negative/pessimistic language |
| `neutral` | Neither bullish nor bearish |
| `mixed` | Both positive and negative signals |
