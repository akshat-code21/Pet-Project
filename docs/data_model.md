# Data Model Reference

This document describes every database table, its purpose, columns, and relationships.

---

## Schema Diagram

```
users
  └──< investors (user_id FK)
         └──< sources (investor_id FK)
         │      └──< content_items (source_id FK, investor_id FK)
         │             └──< content_chunks (content_item_id FK)
         │             └──< extracted_mentions (content_item_id FK, investor_id FK)
         │             └──< portfolio_changes (content_item_id FK, investor_id FK)
         └──< reports (investor_id FK, user_id FK)
         └──< alerts (investor_id FK, user_id FK, content_item_id FK, report_id FK)
```

---

## Tables

### `users`

Extends Supabase `auth.users`. One row per registered user.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | — | References `auth.users(id)`, cascades on delete |
| `email` | TEXT | ❌ | — | Indexed |
| `full_name` | TEXT | ✅ | NULL | Optional display name |
| `created_at` | TIMESTAMPTZ | ❌ | `now()` | |
| `updated_at` | TIMESTAMPTZ | ❌ | `now()` | Auto-updated |

---

### `investors`

Core entity. Each row is an investor tracked by a user.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | `uuid_generate_v4()` | PK |
| `user_id` | UUID | ❌ | — | FK → `users.id` CASCADE |
| `name` | TEXT | ❌ | — | Display name (e.g. "Bill Ackman") |
| `description` | TEXT | ✅ | NULL | Optional notes |
| `cik_number` | TEXT | ✅ | NULL | SEC CIK, padded to 10 digits |
| `is_active` | BOOLEAN | ❌ | `TRUE` | Inactive investors are skipped in jobs |
| `last_synced_at` | TIMESTAMPTZ | ✅ | NULL | Updated after each full sync |
| `created_at` | TIMESTAMPTZ | ❌ | `now()` | |
| `updated_at` | TIMESTAMPTZ | ❌ | `now()` | |

**Indexes:** `(user_id)`, `(user_id, is_active)`, `(cik_number) WHERE NOT NULL`

---

### `sources`

Each source is a URL/feed/channel attached to one investor. Multiple sources per investor.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | `uuid_generate_v4()` | PK |
| `investor_id` | UUID | ❌ | — | FK → `investors.id` CASCADE |
| `source_type` | ENUM | ❌ | — | `sec_13f` \| `website` \| `youtube` \| `rss` \| `twitter` \| `custom` |
| `url` | TEXT | ❌ | — | Source URL |
| `label` | TEXT | ✅ | NULL | Human-readable label |
| `config` | JSONB | ✅ | `{}` | Extra config: `cik_number`, `has_sitemap`, etc. |
| `is_active` | BOOLEAN | ❌ | `TRUE` | Set to `false` after 5 consecutive failures |
| `last_checked_at` | TIMESTAMPTZ | ✅ | NULL | Updated after each check (success or fail) |
| `last_successful_at` | TIMESTAMPTZ | ✅ | NULL | Updated only on success |
| `check_frequency_hours` | INTEGER | ❌ | `24` | How often the scheduler checks this source |
| `consecutive_failures` | INTEGER | ❌ | `0` | Auto-incremented on failure, reset on success |
| `created_at` | TIMESTAMPTZ | ❌ | `now()` | |
| `updated_at` | TIMESTAMPTZ | ❌ | `now()` | |

**Indexes:** `(investor_id)`, `(source_type)`, `(is_active, last_checked_at) WHERE is_active`

**Config examples:**
```json
// sec_13f
{"cik_number": "0001336528"}

// website with sitemap
{"has_sitemap": true, "sitemap_url": "https://example.com/sitemap.xml"}
```

---

### `content_items`

Every piece of raw content fetched from any source. The raw data store.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | `uuid_generate_v4()` | PK |
| `source_id` | UUID | ❌ | — | FK → `sources.id` CASCADE |
| `investor_id` | UUID | ❌ | — | FK → `investors.id` CASCADE (denormalized for query speed) |
| `content_type` | ENUM | ❌ | — | `filing` \| `article` \| `video` \| `newsletter` \| `website_page` \| `custom` |
| `title` | TEXT | ✅ | NULL | Article/video title |
| `url` | TEXT | ✅ | NULL | Canonical URL of the content |
| `raw_text` | TEXT | ✅ | NULL | Original fetched text (HTML stripped) |
| `cleaned_text` | TEXT | ✅ | NULL | Post-normalizer cleaned text |
| `published_at` | TIMESTAMPTZ | ✅ | NULL | Original publication date |
| `content_hash` | TEXT | ❌ | — | SHA-256 of raw_text; `UNIQUE` constraint for deduplication |
| `processing_status` | ENUM | ❌ | `pending` | `pending` \| `processing` \| `completed` \| `failed` \| `skipped` |
| `processing_error` | TEXT | ✅ | NULL | Error message if status=failed |
| `metadata` | JSONB | ✅ | `{}` | Flexible metadata (filing_period, video_duration, etc.) |
| `created_at` | TIMESTAMPTZ | ❌ | `now()` | |

**Indexes:** `(source_id)`, `(investor_id)`, `(processing_status) WHERE IN ('pending','processing')`, `(investor_id, published_at DESC)`, `(investor_id, content_type)`

**Deduplication:** `UNIQUE (content_hash)` — inserting duplicate content raises an integrity error, caught and silently skipped.

---

### `content_chunks`

Chunked segments of content_items with vector embeddings. Enables semantic search.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | `uuid_generate_v4()` | PK |
| `content_item_id` | UUID | ❌ | — | FK → `content_items.id` CASCADE |
| `chunk_index` | INTEGER | ❌ | — | Zero-based position within the content item |
| `chunk_text` | TEXT | ❌ | — | Text of this chunk (~4000 characters) |
| `embedding` | VECTOR(1536) | ✅ | NULL | OpenAI `text-embedding-3-small` embedding |
| `created_at` | TIMESTAMPTZ | ❌ | `now()` | |

**Indexes:** `(content_item_id)`, HNSW on `(embedding vector_cosine_ops)` with `m=16, ef_construction=64`

> The HNSW index enables sub-second approximate nearest-neighbor search at MVP scale. `ef_construction=64` balances index quality vs. build time.

---

### `extracted_mentions`

Structured AI-extracted entities (companies, tickers, themes) from content.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | `uuid_generate_v4()` | PK |
| `content_item_id` | UUID | ❌ | — | FK → `content_items.id` CASCADE |
| `investor_id` | UUID | ❌ | — | FK → `investors.id` CASCADE (denormalized) |
| `entity_type` | ENUM | ❌ | — | `company` \| `ticker` \| `person` \| `theme` \| `sector` \| `macro_theme` |
| `entity_name` | TEXT | ❌ | — | Full name (e.g. "NVIDIA Corporation") |
| `ticker_symbol` | TEXT | ✅ | NULL | Stock ticker (e.g. "NVDA"); NULL for non-tickers |
| `sentiment` | ENUM | ✅ | NULL | `bullish` \| `bearish` \| `neutral` \| `mixed` |
| `conviction_level` | ENUM | ✅ | NULL | `high` \| `medium` \| `low` \| `unknown` |
| `context_snippet` | TEXT | ✅ | NULL | 1–3 sentence supporting quote from source |
| `created_at` | TIMESTAMPTZ | ❌ | `now()` | |

**Indexes:** `(content_item_id)`, `(investor_id)`, `(ticker_symbol) WHERE NOT NULL`, `(entity_type, entity_name)`

---

### `portfolio_changes`

Structured holdings changes parsed from 13F filings. Separate table for queryability.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | `uuid_generate_v4()` | PK |
| `investor_id` | UUID | ❌ | — | FK → `investors.id` CASCADE |
| `content_item_id` | UUID | ❌ | — | FK → `content_items.id` CASCADE |
| `ticker_symbol` | TEXT | ❌ | — | Stock ticker |
| `company_name` | TEXT | ✅ | NULL | Company name from 13F |
| `cusip` | TEXT | ✅ | NULL | CUSIP identifier |
| `change_type` | ENUM | ❌ | — | `new_position` \| `increased` \| `decreased` \| `closed` \| `unchanged` |
| `shares_previous` | BIGINT | ✅ | `0` | Shares held in prior period |
| `shares_current` | BIGINT | ❌ | — | Shares held in this period |
| `value_usd` | BIGINT | ✅ | NULL | Value in thousands (SEC standard reporting unit) |
| `percent_of_portfolio` | NUMERIC(6,3) | ✅ | NULL | % of total portfolio value |
| `filing_period` | TEXT | ❌ | — | Filing quarter (e.g. "2024-Q3") |
| `report_date` | DATE | ✅ | NULL | Date of the 13F report |
| `created_at` | TIMESTAMPTZ | ❌ | `now()` | |

**Indexes:** `(investor_id)`, `(ticker_symbol)`, `(investor_id, filing_period)`, `(change_type)`

---

### `reports`

Generated intelligence reports (investor, digest, event). Stored as markdown.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | `uuid_generate_v4()` | PK |
| `user_id` | UUID | ❌ | — | FK → `users.id` CASCADE |
| `investor_id` | UUID | ✅ | NULL | FK → `investors.id` SET NULL; NULL for daily digest |
| `report_type` | ENUM | ❌ | — | `investor_report` \| `daily_digest` \| `event_report` |
| `title` | TEXT | ❌ | — | Report title |
| `summary` | TEXT | ✅ | NULL | 2–3 sentence TL;DR |
| `content_markdown` | TEXT | ❌ | — | Full report in markdown |
| `source_item_ids` | UUID[] | ✅ | `{}` | Array of content_item IDs referenced |
| `is_read` | BOOLEAN | ❌ | `FALSE` | Read/unread state |
| `period_start` | TIMESTAMPTZ | ✅ | NULL | Report coverage period start |
| `period_end` | TIMESTAMPTZ | ✅ | NULL | Report coverage period end |
| `generated_at` | TIMESTAMPTZ | ❌ | `now()` | When the LLM generation completed |
| `created_at` | TIMESTAMPTZ | ❌ | `now()` | |

**Indexes:** `(user_id)`, `(investor_id) WHERE NOT NULL`, `(user_id, report_type)`, `(user_id, generated_at DESC)`, `(user_id, is_read) WHERE NOT read`

---

### `alerts`

Actionable notifications with severity scoring.

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `id` | UUID | ❌ | `uuid_generate_v4()` | PK |
| `user_id` | UUID | ❌ | — | FK → `users.id` CASCADE |
| `investor_id` | UUID | ✅ | NULL | FK → `investors.id` SET NULL |
| `content_item_id` | UUID | ✅ | NULL | FK → `content_items.id` SET NULL |
| `report_id` | UUID | ✅ | NULL | FK → `reports.id` SET NULL |
| `alert_type` | ENUM | ❌ | — | `new_filing` \| `new_company_mention` \| `new_thesis` \| `high_conviction` \| `portfolio_change` \| `daily_digest_ready` |
| `title` | TEXT | ❌ | — | Alert title (shown in feed) |
| `summary` | TEXT | ✅ | NULL | 1–2 sentence alert summary |
| `severity` | ENUM | ❌ | `medium` | `low` \| `medium` \| `high` \| `critical` |
| `score` | INTEGER | ❌ | `50` | 0–100 alert score (CHECK constraint) |
| `is_read` | BOOLEAN | ❌ | `FALSE` | |
| `email_sent` | BOOLEAN | ❌ | `FALSE` | True after Resend delivery attempt |
| `metadata` | JSONB | ✅ | `{}` | Flexible extra data |
| `created_at` | TIMESTAMPTZ | ❌ | `now()` | |

**Indexes:** `(user_id, is_read, created_at DESC)`, `(investor_id) WHERE NOT NULL`, `(alert_type)`, `(user_id, severity) WHERE NOT read`

---

## Alert Scoring Rules

Scores are additive integers (0–100). Used to determine `severity` and whether to send email.

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

DEDUCTIONS:
  Same company mentioned last 7 days:  -15
  Sentiment = NEUTRAL:                 -10
  Short mention (< 50 chars context):  -10

SEVERITY MAPPING:
  0–39:   low
  40–59:  medium
  60–79:  high
  80–100: critical → email sent via Resend
```
