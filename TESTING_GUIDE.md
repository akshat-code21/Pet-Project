# HFI Platform — MVP Testing Guide

> Step-by-step walkthrough to test the full flow of the Hedge Fund Intelligence MVP via the frontend UI.

---

## Prerequisites

### 1. Environment Setup

Make sure both servers are running:

```bash
# Terminal 1 — Backend
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev
```

### 2. Required Environment Variables

**Backend `.env`** must have:
| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | ✅ | PostgreSQL + asyncpg connection string |
| `SUPABASE_URL` | ✅ | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | ✅ | Supabase service role key |
| `SUPABASE_JWT_SECRET` | ✅ | JWT verification secret |
| `OPENAI_API_KEY` | ✅ | GPT-4o + embeddings |
| `RESEND_API_KEY` | ⚡ Optional | Email alerts (skip if not testing email) |
| `YOUTUBE_API_KEY` | ⚡ Optional | YouTube channel discovery (yt-dlp works without it) |
| `SCHEDULER_ENABLED` | ✅ | Set to `true` |

**Frontend `.env`** must have:
| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Your Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon/public key |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` |

### 3. Database Migration

Make sure the database tables exist:

```bash
cd backend
alembic upgrade head
```

---

## Flow 1: Authentication

### Step 1 — Sign Up

1. Open `http://localhost:3000/signup`
2. Enter an email and password (min 6 chars)
3. Click **Create account**
4. ✅ You should be redirected to the **Dashboard** (`/`)

### Step 2 — Log Out & Log In

1. Click the **avatar** (top-right) or go to **Settings → Sign out**
2. You'll be redirected to `/login`
3. Enter your credentials and click **Sign in**
4. ✅ You should land on the Dashboard again

> **What to verify:**
> - Toast notifications appear on success/failure
> - Invalid credentials show an error toast
> - All dashboard pages require auth (navigating to `/investors` while logged out should redirect)

---

## Flow 2: Dashboard Overview

After login, you're on the Dashboard (`/`). Verify these elements:

| Element | Expected |
|---|---|
| **Stat cards** (top row) | 4 cards: Investors Tracked, Unread Alerts, Reports Generated, Active Sources |
| **Recent Alerts** (left) | List of latest alerts, or empty state "No recent activity" |
| **Latest Reports** (right) | List of recent reports, or empty state "No reports yet" |
| **Tracked Investors** (bottom) | Grid of investor cards, or "Add your first investor" CTA |

---

## Flow 3: Add an Investor

### Step 1 — Create Investor

1. Click **"Add Investor"** button (top-right of Dashboard) — OR navigate to `/investors/new`
2. Fill in:
   - **Name**: e.g. `Berkshire Hathaway`
   - **CIK Number**: e.g. `1067983` (Warren Buffett's CIK on SEC EDGAR)
3. Click **Create**
4. ✅ You should be redirected to the **Investors list** (`/investors`)
5. ✅ Your new investor card should appear

### Step 2 — View Investor Detail

1. Click the investor card
2. ✅ You should see the **Investor detail page** (`/investors/{id}`) with:
   - Investor name, CIK number, and avatar
   - Stat cards: Content Items, Reports, Unread Alerts
   - Tabs: **Content**, **Portfolio**, **Sources**, **Reports**, **Alerts**

---

## Flow 4: Add Data Sources

On the investor detail page, go to the **Sources** tab.

### Add a SEC 13F Source

1. In the Sources tab, click **Add Source**
2. Select **Source Type**: `sec_13f`
3. Enter **URL**: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1067983&type=13F-HR&dateb=&owner=include&count=10`
   - Or simply: `https://sec.gov` (the adapter uses the CIK number directly)
4. Click **Add**
5. ✅ Source appears in the list with a green "Active" badge

### Add an RSS Source

1. Click **Add Source** again
2. Select **Source Type**: `rss`
3. Enter **URL**: e.g. `https://feeds.bloomberg.com/markets/news.rss` or any investor newsletter RSS feed
4. Click **Add**

### Add a Website Source

1. Click **Add Source** again
2. Select **Source Type**: `website`
3. Enter **URL**: e.g. `https://www.berkshirehathaway.com/letters/letters.html`
4. Click **Add**

### Add a YouTube Source

1. Click **Add Source** again
2. Select **Source Type**: `youtube`
3. Enter **URL**: e.g. `https://www.youtube.com/@YahooFinance` or any investor-related channel
4. Click **Add**

> **What to verify:**
> - All 4 source types can be added
> - Each source shows Active status with a green badge
> - Delete button removes a source

---

## Flow 5: Trigger Data Ingestion

### Option A — Sync Button (Frontend)

1. On the investor detail page, click the **"Sync"** button (top-right, next to Edit)
2. ✅ A toast appears: "Sync started — Fetching latest data..."
3. The backend will run ingestion for all active sources of this investor
4. Wait 10–30 seconds, then **refresh the page**
5. ✅ The **Content tab** should now show ingested items

### Option B — Settings Control Panel (UI Trigger)

You can trigger specific ingestion jobs on demand directly from the UI:

1. Go to the **Settings** page (`/settings`) from the sidebar.
2. Scroll down to the **Scheduler & Ingestion Controls** card.
3. Review the status badges: **Scheduler Status** (Active & Running) and **Pending Items** (number of raw items waiting to be processed).
4. Locate the ingestion job you want to run (e.g. `SEC 13F Ingestion`, `RSS News Ingestion`, etc.) and click **Run Now**.
5. The button will show a loading spinner, and a success toast will confirm when the ingestion completes.

---

## Flow 6: AI Processing Pipeline

After ingestion, content items start with `processing_status = "pending"`. The pipeline processes them automatically in the background, but you can also trigger it manually from the UI:

### Option A — Via Content tab (Recommended)

1. Go to the investor detail page → **Content** tab.
2. Since there are pending content items, a **"Process Content"** button will appear in the tab header next to "Content Timeline".
3. Click **"Process Content"** to trigger processing.
4. Once completed, the button disappears and the timeline items will show a green `completed` badge.

### Option B — Via Settings page

1. Navigate to **Settings → Scheduler & Ingestion Controls**.
2. Click **Run Now** next to **Process Pending Content**.

### What the pipeline does (per item):

1. **Normalizer** → cleans & chunks the text
2. **Entity Extractor** → identifies companies, tickers, people (GPT-4o-mini)
3. **Thesis Extractor** → extracts investment theses (GPT-4o)
4. **Embedder** → generates embeddings (text-embedding-3-small) → stores in pgvector
5. **Alert Checker** → creates alerts if significant events detected

### Verify on Frontend

1. Go to investor detail → **Content tab**
   - ✅ Items should show `completed` processing status
2. Go to investor detail → **Alerts tab**
   - ✅ Alerts should appear if significant content was detected


---

## Flow 7: Portfolio Holdings (13F)

If SEC 13F data was ingested:

1. Go to investor detail page
2. Click the **Portfolio** tab
3. ✅ You should see a table of holdings grouped by filing period:
   - Company name, Ticker, Shares, Value ($), % of Portfolio
   - Change badges: **New** (green), **Increased** (green), **Decreased** (orange), **Closed** (red)
4. If no 13F data: you'll see the empty state "No 13F portfolio data yet"

---

## Flow 8: Generate a Report

### From the Frontend

1. Go to the investor detail page (`/investors/{id}`).
2. In the top-right header (next to Sync and Edit), click the **"Generate Report"** button.
   - *Alternative*: If no reports exist yet for the investor, go to the **Reports** tab and click **"Generate First Report"**.
3. A toast notification will appear, and the button will show a loading spinner.
4. Once completed (usually 10-20 seconds), a success toast appears and the new report automatically populates in the **Reports** tab!

### View Reports


1. Go to **Reports** page (`/reports`) from the sidebar
2. ✅ You should see reports listed with:
   - Report type badge (investor report / daily digest)
   - Title and summary
   - Period dates
   - Unread indicator
3. Click a report to open `/reports/{id}`
4. ✅ The report detail page shows:
   - Full markdown content with formatted headings, tables, code blocks
   - Auto-marks the report as read
   - Back button to reports list

### Filter Reports

- Use the **type filter** dropdown (All types / Investor Report / Daily Digest / Event Report)

---

## Flow 9: Alerts

### View Alerts

1. Go to **Alerts** page (`/alerts`) from the sidebar
2. ✅ You should see alert cards with:
   - Severity dot (red/orange/amber/gray) + score
   - Title, summary, type badge
   - Investor name
   - **"View Report →"** link (when an alert is tied to a report)
   - Unread blue dot

### Filter Alerts

- **Unread Only** toggle button
- **Severity** dropdown (Critical / High / Medium / Low)
- **Investor** dropdown (filters alerts to a specific investor)

### Mark as Read

- Click an unread alert → auto-marks it as read
- Click **"Mark all read"** → marks all alerts as read
- ✅ Toast confirms the action

---

## Flow 10: Semantic Search

1. In the **top navigation bar**, type in the search box (min 3 characters)
2. e.g. `"Apple investment thesis"` or `"portfolio position"`
3. ✅ A dropdown appears with search results:
   - Investor name
   - Matching text chunk
   - Source URL
4. Results use **vector similarity search** on pgvector embeddings

> **Note:** Search only works after content has been processed through the AI pipeline (embeddings generated).

---

## Flow 11: Settings

### Appearance

1. Go to **Settings** page (`/settings`)
2. Click Light / Dark / System theme options
3. ✅ Theme changes immediately

### Notifications

1. Toggle **"Critical & high severity emails"** on/off
2. Toggle **"Daily digest email"** on/off
3. ✅ Toast confirms the change

### Password Change

1. Click **"Change"** next to Password
2. Enter a new password (min 6 chars)
3. Click **Update**
4. ✅ Password is updated via Supabase

### Sign Out

1. Click **Sign out** (red button)
2. ✅ Redirected to `/login`

---

## Flow 12: Edit / Delete Investor

### Edit

1. Go to investor detail → click **Edit** button
2. Modify name or CIK number
3. Save changes
4. ✅ Changes reflected on the detail page

### Delete

1. On the investors list (`/investors`), each card has a delete action
2. Delete an investor
3. ✅ Investor removed from the list

---

## Flow 13: Daily Digest (Background Job)

The scheduler automatically runs a daily digest job. To trigger manually from the UI:

1. Navigate to **Settings → Scheduler & Ingestion Controls**.
2. Click **Run Now** next to **Generate Daily Digest**.


This:
1. Generates a summary report across all investors
2. Creates a "daily_digest_ready" alert
3. Sends an email if `RESEND_API_KEY` is configured
4. ✅ Check the Reports page for a new "daily digest" report

---

## Troubleshooting

| Issue | Fix |
|---|---|
| **401 on all API calls** | Token expired — sign out and sign back in |
| **CORS errors** | Ensure backend has `FRONTEND_URL=http://localhost:3000` in `.env` |
| **Empty content after sync** | Check backend terminal logs for ingestion errors; verify source URLs are valid |
| **No embeddings / search fails** | Ensure `OPENAI_API_KEY` is set and has credits |
| **Portfolio tab empty** | 13F processing requires SEC CIK + successful SEC adapter fetch |
| **Scheduler not running** | Check `SCHEDULER_ENABLED=true` in backend `.env` |

---

## Testing Checklist

Use this checklist to verify the complete MVP:

```
Auth
  [ ] Signup works
  [ ] Login works  
  [ ] Protected routes redirect to login
  [ ] Sign out clears session

Dashboard
  [ ] Stat cards render
  [ ] Recent alerts feed shows data
  [ ] Latest reports list shows data
  [ ] Tracked investors grid shows data

Investors
  [ ] Create investor with name + CIK
  [ ] View investor detail page
  [ ] Edit investor
  [ ] Delete investor
  [ ] Sync button triggers ingestion

Sources
  [ ] Add SEC 13F source
  [ ] Add RSS source
  [ ] Add Website source
  [ ] Add YouTube source
  [ ] Delete a source

Content & Processing
  [ ] Content tab shows ingested items
  [ ] Items show processing status (pending → completed)
  [ ] Portfolio tab shows 13F holdings (if applicable)

Reports
  [ ] Reports list page with type filter
  [ ] Report detail page renders markdown
  [ ] Auto mark-as-read on open
  [ ] Generate report via "Generate Report" UI button
  [ ] Generate first report via empty state "Generate First Report" button

Alerts
  [ ] Alerts page with severity filter
  [ ] Alerts page with investor filter
  [ ] Mark single alert as read
  [ ] Mark all alerts as read
  [ ] "View Report" link on relevant alerts

Search
  [ ] Semantic search via top nav
  [ ] Results show investor name + text chunk

Settings
  [ ] Theme toggle (light/dark/system)
  [ ] Notification toggles
  [ ] Password change
  [ ] Trigger scheduler jobs (e.g. process pending, ingest) via Settings UI
  [ ] Sign out
```
