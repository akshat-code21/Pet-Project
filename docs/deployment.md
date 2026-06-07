# Deployment Guide — Railway (Backend) + Vercel (Frontend)

This guide covers deploying the Hedge Fund Intelligence Platform to production.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Supabase Setup](#supabase-setup)
3. [Backend: Railway](#backend-railway)
4. [Frontend: Vercel](#frontend-vercel)
5. [Environment Variables Reference](#environment-variables-reference)
6. [Running Migrations](#running-migrations)
7. [Verifying Deployment](#verifying-deployment)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- [Supabase](https://supabase.com) account with a project created
- [Railway](https://railway.app) account
- [Vercel](https://vercel.com) account (for frontend)
- [OpenAI](https://platform.openai.com) API key (GPT-4o access required)
- [Resend](https://resend.com) account + verified sending domain

---

## Supabase Setup

### 1. Create a Supabase Project

1. Go to [supabase.com](https://supabase.com) → New Project
2. Choose a region close to your users
3. Save the database password

### 2. Enable pgvector Extension

In the Supabase SQL Editor, run:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

Or: Dashboard → Database → Extensions → Enable `vector`

### 3. Collect Credentials

From **Project Settings → API**:
- `SUPABASE_URL` — Project URL (e.g. `https://xxxx.supabase.co`)
- `SUPABASE_SERVICE_KEY` — service_role key (under "Project API keys")
- `SUPABASE_JWT_SECRET` — JWT Secret (under "JWT Settings" tab)

From **Project Settings → Database**:
- `DATABASE_URL` — Connection string in asyncpg format:
  ```
  postgresql+asyncpg://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres
  ```
  > **Note:** Use port `5432` (direct connection), not `6543` (pooler), for Alembic migrations. For the running app, either port works but the pooler (`6543`) is recommended for production to avoid connection limits.

---

## Backend: Railway

### 1. Create Railway Project

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Initialize from project directory
cd Pet-Project/backend
railway init
```

Or use the Railway dashboard: **New Project → Deploy from GitHub repo**

### 2. Configure Environment Variables

In Railway dashboard → your project → Variables, add all values from the [Environment Variables Reference](#environment-variables-reference) section below.

Key production values:
```
APP_ENV=production
SCHEDULER_ENABLED=true
FRONTEND_URL=https://your-app.vercel.app
```

### 3. Configure Build

Railway auto-detects the `Dockerfile` in `backend/`. The `railway.toml` file configures the deployment:

```toml
# backend/railway.toml (already in repo)
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
```

### 4. Run Database Migrations

After deploying, run migrations using Railway's one-off command:

```bash
# Using Railway CLI
railway run alembic upgrade head
```

Or add a Release Command in Railway dashboard settings:
```
alembic upgrade head
```

### 5. Install Playwright Browser

The Dockerfile should install Playwright's browser binaries. If not already present in your Dockerfile, add:

```dockerfile
RUN playwright install chromium --with-deps
```

---

## Frontend: Vercel

### 1. Deploy to Vercel

```bash
cd Pet-Project/frontend
vercel --prod
```

Or connect the GitHub repo in the Vercel dashboard.

### 2. Configure Environment Variables

In Vercel dashboard → Project → Settings → Environment Variables:

```
NEXT_PUBLIC_SUPABASE_URL=https://xxxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key from Supabase>
NEXT_PUBLIC_API_URL=https://your-backend.railway.app
```

> ⚠️ Never expose `SUPABASE_SERVICE_KEY` to the frontend. Only use the `anon` key client-side.

### 3. Configure Next.js

Ensure `next.config.ts` has the backend API URL in allowed origins:

```ts
// frontend/next.config.ts
const nextConfig = {
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  },
}
```

---

## Environment Variables Reference

### Backend (Railway)

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `SUPABASE_URL` | ✅ | Supabase project URL | `https://xxxx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | ✅ | Service role key (server-only) | `eyJ...` |
| `SUPABASE_JWT_SECRET` | ✅ | JWT secret for token verification | `super-secret-jwt-secret` |
| `DATABASE_URL` | ✅ | PostgreSQL asyncpg connection string | `postgresql+asyncpg://postgres:pass@db.xxx.supabase.co:5432/postgres` |
| `OPENAI_API_KEY` | ✅ | OpenAI API key (GPT-4o + embeddings) | `sk-proj-...` |
| `RESEND_API_KEY` | ✅ | Resend API key for email | `re_...` |
| `FRONTEND_URL` | ✅ | Frontend origin (CORS allow-list) | `https://your-app.vercel.app` |
| `APP_ENV` | ✅ | `development` or `production` | `production` |
| `LOG_LEVEL` | ❌ | Log level (default: `INFO`) | `INFO` |
| `SCHEDULER_ENABLED` | ❌ | Toggle background jobs (default: `true`) | `true` |

> **Tip:** In production, `APP_ENV=production` disables `/docs` and `/redoc` Swagger endpoints.

### Frontend (Vercel)

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_SUPABASE_URL` | ✅ | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | ✅ | Supabase anonymous/public key |
| `NEXT_PUBLIC_API_URL` | ✅ | Backend API base URL |

---

## Running Migrations

### First-time setup (local)

```bash
cd backend

# Make sure DATABASE_URL points to your Supabase DB
alembic upgrade head
```

### Creating a new migration (local dev)

```bash
# After modifying ORM models
alembic revision --autogenerate -m "add_new_field_to_investors"
alembic upgrade head
```

### Migration on Railway (production)

Option A — Railway one-off command:
```bash
railway run alembic upgrade head
```

Option B — Add to Railway release phase in `railway.toml`:
```toml
[deploy]
releaseCommand = "alembic upgrade head"
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
```

> ⚠️ Always run migrations against a backup of the database before deploying schema changes to production.

---

## Verifying Deployment

### Health check

```bash
curl https://your-backend.railway.app/health
# {"status":"ok"}
```

### Scheduler status

```bash
curl https://your-backend.railway.app/api/v1/admin/jobs/status \
  -H "Authorization: Bearer <your_jwt>"
```

Expected: `"scheduler_running": true` with 6 jobs listed.

### Test authentication

```bash
curl -X POST https://your-backend.railway.app/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"TestPass123!"}'
```

### Verify pgvector

Run in Supabase SQL Editor:
```sql
SELECT extname FROM pg_extension WHERE extname = 'vector';
-- Should return: vector
```

---

## Troubleshooting

### `asyncpg.InvalidCatalogNameError: database "postgres" does not exist`

The `DATABASE_URL` format is wrong. Ensure it uses `asyncpg` driver:
```
# Wrong
postgresql://postgres:pass@db.xxx.supabase.co:5432/postgres

# Correct
postgresql+asyncpg://postgres:pass@db.xxx.supabase.co:5432/postgres
```

### `JWTError: Signature verification failed`

`SUPABASE_JWT_SECRET` is wrong. Find it in: Supabase Dashboard → Project Settings → API → JWT Settings → JWT Secret.

### `scheduler_running: false` in admin/jobs/status

`SCHEDULER_ENABLED` env var is `false` or the app started in a non-async context. Ensure:
1. `SCHEDULER_ENABLED=true` in Railway environment
2. The app starts via `uvicorn` (not as a library import)

### Playwright: `BrowserType.launch: Executable doesn't exist`

Run `playwright install chromium` in the Docker build step. Add to Dockerfile:
```dockerfile
RUN python -m playwright install chromium
RUN python -m playwright install-deps chromium
```

### `pgvector` extension not found

Enable it in Supabase Dashboard → Database → Extensions → Search "vector" → Enable.

Or run in SQL Editor:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### `CORS` errors from frontend

`FRONTEND_URL` env var must exactly match the frontend origin (scheme + domain + port), e.g.:
```
FRONTEND_URL=https://your-app.vercel.app
```
No trailing slash. In development: `FRONTEND_URL=http://localhost:3000`.

### Email alerts not sending

1. Verify `RESEND_API_KEY` is set correctly
2. Verify sending domain is verified in Resend dashboard
3. Check alert score threshold: emails only send for `score >= 80` (critical severity)
4. Check `email_sent` field on alerts in Supabase to confirm delivery attempts

### Railway app crashes on startup

1. Check Railway deployment logs
2. Verify all required environment variables are set
3. Run `alembic upgrade head` if tables are missing (common first-deploy issue)
