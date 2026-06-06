# Hedge Fund Intelligence Platform

AI-powered platform for monitoring hedge fund investors across SEC filings, websites, YouTube, and RSS feeds.

## Stack

- **Backend:** FastAPI + LangGraph + LangChain (Railway)
- **Frontend:** Next.js 14 + shadcn/ui (Vercel)
- **Database:** Supabase PostgreSQL + pgvector
- **AI:** OpenAI GPT-4o / GPT-4o-mini + text-embedding-3-small

## Setup

```bash
cp .env.example .env
# Fill in .env values
```

See `docs/deployment.md` for full setup instructions.
