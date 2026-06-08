# Auto-Discovery of Investor Sources

## Problem

After adding an investor (Name + optional CIK), the user must **manually** add data sources. This plan adds **automatic source discovery** using the investor's name as input.

## Decisions (Approved)

- **YouTube Discovery:** yt-dlp search (free, no API key)
- **Web Discovery:** LangChain `DuckDuckGoSearchResults` from `langchain-community` (already installed, just add `duckduckgo-search` pip dep)
- **Trigger:** Auto on investor creation + manual "Discover Sources" button
- **UX:** Suggest & Confirm — discovered sources appear as pending suggestions
- **LLM Validation:** Yes — GPT-4o-mini validates relevance (~$0.01/run)

## Architecture

```
User creates investor (name + optional CIK)
        │
        ▼
┌─────────────────────────────────┐
│  Source Discovery Service       │
│                                 │
│  1. SEC EDGAR CIK Lookup (free) │
│  2. YouTube Search (yt-dlp)     │
│  3. Web Search (DDG/LangChain)  │
│  4. RSS Feed Detection (HTTP)   │
│  5. LLM Validation (GPT-4o-mini)│
│                                 │
│  Output: List[DiscoveredSource] │
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│  discovered_sources table       │
│  (pending / accepted / dismissed)│
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│  Frontend: Discovered Sources   │
│  Accept ✓  /  Dismiss ✗        │
└─────────────────────────────────┘
```

## Changes

### Backend

| File | Action | Description |
|---|---|---|
| `models/discovered_source.py` | NEW | SQLAlchemy model |
| `schemas/discovered_source.py` | NEW | Pydantic schemas |
| `services/discovery_service.py` | NEW | Orchestrator + strategies |
| `api/discovery.py` | NEW | API endpoints |
| `services/investor_service.py` | MODIFY | Auto-trigger on creation |
| `app/main.py` | MODIFY | Register discovery router |
| `pyproject.toml` | MODIFY | Add `duckduckgo-search` dep |

### Frontend

| File | Action | Description |
|---|---|---|
| `components/investors/DiscoveredSources.tsx` | NEW | Discovered sources panel |
| `hooks/useInvestors.ts` | MODIFY | Add discovery hooks |
| `lib/api.ts` | MODIFY | Add discovery API methods |
| `types/api.ts` | MODIFY | Add DiscoveredSource type |
| `app/(dashboard)/investors/[id]/page.tsx` | MODIFY | Add discovered sources section |

### Database

New `discovered_sources` table with: id, investor_id, source_type, url, label, confidence, discovery_method, status (pending/accepted/dismissed), metadata, created_at.
