# Live Stream Ingestion Support

Add the ability to monitor and ingest live streams (YouTube Live, CNBC, Yahoo Finance, Bloomberg TV) so that when an investor speaks live, their words are captured, transcribed, and fed through the existing AI pipeline in near-real-time.

**Decisions confirmed:**
- ✅ Support YouTube Live + CNBC/Bloomberg/Yahoo Finance
- ✅ 30–60 second polling latency (APScheduler)
- ✅ Auto-detect when subscribed YouTube channels go live
- ✅ Live transcript UI with real-time updates

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                     LIVE STREAM FLOW                             │
│                                                                  │
│  Two entry points:                                               │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ 1. Manual: User pastes live URL → POST /live-streams     │    │
│  │ 2. Auto: YouTube channel source detected as live         │    │
│  └──────────────────────────────────────────────────────────┘    │
│       │                                                          │
│       ▼                                                          │
│  LiveStreamSession created (status=monitoring)                   │
│       │                                                          │
│       ▼                                                          │
│  APScheduler: poll_live_streams (every 30s)                      │
│       │                                                          │
│       ├─► YouTube Live:                                          │
│       │     yt-dlp --write-auto-sub → WebVTT captions            │
│       │                                                          │
│       ├─► CNBC / Bloomberg / Yahoo Finance:                      │
│       │     streamlink → capture 30s audio → Whisper API         │
│       │                                                          │
│       ├─► Create ContentItem (type=transcript_segment)           │
│       │     with segment text + timestamp range                  │
│       │                                                          │
│       ├─► Push to SSE endpoint → frontend live panel             │
│       │                                                          │
│       └─► On stream end detected:                                │
│              └─► Consolidation: merge all segments               │
│                    └─► Single ContentItem (type=live_transcript)  │
│                         └─► Normal pipeline (entities, thesis…)  │
└──────────────────────────────────────────────────────────────────┘
```

### Platform Strategy

| Platform | Method | Transcript Source | Latency | Cost |
|----------|--------|-------------------|---------|------|
| **YouTube Live** | `yt-dlp` | Auto-generated captions (WebVTT) | ~30s | Free |
| **CNBC** | `streamlink` + known stream URLs | Whisper API on audio | ~45s | ~$0.006/min |
| **Bloomberg TV** | `streamlink` + known stream URLs | Whisper API on audio | ~45s | ~$0.006/min |
| **Yahoo Finance** | `streamlink` or `yt-dlp` (YF has a YT channel) | Captions or Whisper | ~30–45s | Free or ~$0.006/min |

> [!NOTE]
> For CNBC/Bloomberg, we maintain a registry of known stream URLs in `config`. Users can also provide custom HLS/DASH URLs. `streamlink` handles extracting the actual media stream from page URLs.

---

## Proposed Changes

### Phase 1: Backend Data Layer

---

#### [MODIFY] [source.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/models/source.py)

Add `live_stream` to `SourceTypeEnum`. Requires an Alembic migration to alter the PostgreSQL enum.

```diff
 SourceTypeEnum = Enum(
-    "sec_13f", "website", "youtube", "rss", "twitter", "custom",
+    "sec_13f", "website", "youtube", "rss", "twitter", "custom", "live_stream",
     name="source_type",
 )
```

---

#### [MODIFY] [content_item.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/models/content_item.py)

Add `transcript_segment` and `live_transcript` to `ContentTypeEnum`.

```diff
 ContentTypeEnum = Enum(
-    "filing", "article", "video", "newsletter", "website_page", "custom",
+    "filing", "article", "video", "newsletter", "website_page", "custom",
+    "transcript_segment", "live_transcript",
     name="content_type",
 )
```

---

#### [NEW] [live_stream_session.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/models/live_stream_session.py)

New SQLAlchemy model to track active and completed live stream monitoring sessions.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `source_id` | UUID | FK → sources.id (nullable — manual streams may not have a source) |
| `investor_id` | UUID | FK → investors.id |
| `user_id` | UUID | FK → users.id |
| `stream_url` | TEXT | The live stream URL |
| `stream_title` | TEXT | Title from the platform |
| `platform` | ENUM | `youtube` \| `cnbc` \| `bloomberg` \| `yahoo_finance` \| `custom` |
| `status` | ENUM | `monitoring` \| `ended` \| `consolidating` \| `completed` \| `failed` |
| `started_at` | TIMESTAMPTZ | When monitoring began |
| `ended_at` | TIMESTAMPTZ | When stream ended / monitoring stopped |
| `segment_count` | INT | Running count of segments captured |
| `total_duration_seconds` | INT | Total duration transcribed |
| `consolidated_content_item_id` | UUID | FK → content_items.id (the merged transcript) |
| `last_segment_at` | TIMESTAMPTZ | Timestamp of last captured segment |
| `config` | JSONB | Stream-specific config (language, whisper model, etc.) |
| `error_message` | TEXT | Error details if status=failed |
| `created_at` | TIMESTAMPTZ | |

**Indexes:** `(status) WHERE status = 'monitoring'` (for the polling query), `(investor_id)`, `(user_id)`

**Relationships:**
- `source` → Source (optional)
- `investor` → Investor
- `user` → User
- `consolidated_item` → ContentItem (optional)

---

#### [NEW] Alembic migration

```python
# Migration operations:
# 1. ALTER TYPE source_type ADD VALUE 'live_stream'
# 2. ALTER TYPE content_type ADD VALUE 'transcript_segment'
# 3. ALTER TYPE content_type ADD VALUE 'live_transcript'
# 4. CREATE TYPE live_stream_platform (youtube, cnbc, bloomberg, yahoo_finance, custom)
# 5. CREATE TYPE live_stream_status (monitoring, ended, consolidating, completed, failed)
# 6. CREATE TABLE live_stream_sessions (...)
# 7. CREATE INDEX idx_live_sessions_monitoring ON live_stream_sessions(status) WHERE status = 'monitoring'
# 8. CREATE INDEX idx_live_sessions_investor ON live_stream_sessions(investor_id)
```

---

### Phase 2: Backend Ingestion & Transcription

---

#### [NEW] [live_stream_loader.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/ingestion/live_stream_loader.py)

Core ingestion module (~200 lines). Key functions:

```python
@dataclass
class TranscriptSegment:
    text: str
    start_time: float       # seconds from stream start
    end_time: float
    language: str = "en"
    source: str = "captions"  # "captions" | "whisper"


@dataclass
class StreamStatus:
    is_live: bool
    title: str | None
    viewer_count: int | None
    platform: str


async def check_stream_status(stream_url: str) -> StreamStatus:
    """Quick probe: is the stream still live? Uses yt-dlp --dump-json."""


async def fetch_youtube_live_captions(
    stream_url: str,
    last_segment_end: float | None,
) -> list[TranscriptSegment]:
    """
    Fetch auto-generated captions from a YouTube Live stream.
    Uses: yt-dlp --write-auto-sub --skip-download --sub-lang en
    Parses the resulting WebVTT file.
    Filters to segments after last_segment_end.
    """


async def fetch_audio_and_transcribe(
    stream_url: str,
    duration_seconds: int = 30,
    platform: str = "cnbc",
) -> list[TranscriptSegment]:
    """
    For CNBC/Bloomberg/Yahoo Finance streams without captions:
    1. Use streamlink to capture `duration_seconds` of audio
    2. Send to OpenAI Whisper API for transcription
    3. Return TranscriptSegments with timestamps
    
    streamlink command: streamlink <url> best --stdout -O | ffmpeg -i pipe: -t 30 -f wav pipe:
    """


async def consolidate_session(session_id: uuid.UUID) -> uuid.UUID | None:
    """
    After stream ends:
    1. Query all ContentItems where metadata.session_id == session_id
       AND content_type == 'transcript_segment', ordered by created_at
    2. Concatenate all segment texts with timestamps
    3. Create a single ContentItem with content_type='live_transcript'
    4. Mark it as processing_status='pending' (to go through normal pipeline)
    5. Update LiveStreamSession.consolidated_content_item_id
    6. Return the new ContentItem's ID
    """
```

**Platform registry** (hardcoded known URLs, extensible via source config):

```python
KNOWN_STREAMS = {
    "cnbc": {
        "urls": [
            "https://www.cnbc.com/live-tv/",
            "https://www.youtube.com/c/CNBC/live",
        ],
        "method": "streamlink",  # or "youtube" if YT URL
    },
    "bloomberg": {
        "urls": [
            "https://www.bloomberg.com/live",
            "https://www.youtube.com/c/BloombergTV/live",  
        ],
        "method": "streamlink",
    },
    "yahoo_finance": {
        "urls": [
            "https://www.youtube.com/c/YahooFinance/live",
            "https://finance.yahoo.com/live/",
        ],
        "method": "youtube",  # YF live is usually on YouTube
    },
}
```

---

### Phase 3: Backend Jobs & Scheduling

---

#### [NEW] [live_stream_job.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/jobs/live_stream_job.py)

Three job functions (~150 lines):

```python
async def poll_active_live_streams() -> dict:
    """
    Runs every 30 seconds. For each LiveStreamSession with status='monitoring':
    
    1. check_stream_status(session.stream_url)
    2. If still live:
       a. Fetch new transcript segments (captions or whisper based on platform)
       b. For each segment:
          - Create ContentItem(content_type='transcript_segment', 
                              processing_status='skipped',  # don't run full pipeline on segments
                              metadata={'session_id': ..., 'segment_index': ..., 
                                       'start_time': ..., 'end_time': ...})
          - Increment session.segment_count
          - Update session.last_segment_at
       c. Broadcast segments via SSE (see API section)
    3. If stream ended:
       a. Set session.status = 'ended', session.ended_at = now()
       b. Trigger consolidation
    
    Returns: {sessions_polled: N, segments_captured: M, streams_ended: K}
    """


async def consolidate_ended_streams() -> dict:
    """
    Find sessions with status='ended', run consolidate_session() on each.
    Sets status='consolidating' during processing, 'completed' after.
    On error: status='failed' with error_message.
    """


async def auto_detect_live_streams() -> dict:
    """
    Runs every 5 minutes. For each YouTube source:
    1. Check if the channel is currently live (yt-dlp --dump-json on channel/live URL)
    2. If live AND no active session exists for this source:
       a. Create LiveStreamSession(status='monitoring', platform='youtube')
       b. Log alert "Auto-detected live stream: {title}"
    
    Returns: {channels_checked: N, new_sessions: M}
    """
```

---

#### [MODIFY] [scheduler.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/jobs/scheduler.py)

Add three new scheduled jobs:

```python
# High-frequency: poll active live streams every 30 seconds
scheduler.add_job(
    _run_live_stream_polling,
    trigger=IntervalTrigger(seconds=30),
    id="poll_live_streams",
    name="Live Stream Polling",
    replace_existing=True,
    misfire_grace_time=15,
)

# Consolidation: check for ended streams every 2 minutes
scheduler.add_job(
    _run_live_stream_consolidation,
    trigger=IntervalTrigger(minutes=2),
    id="consolidate_live_streams",
    name="Live Stream Consolidation",
    replace_existing=True,
    misfire_grace_time=60,
)

# Auto-detection: check YouTube channels for live streams every 5 minutes
scheduler.add_job(
    _run_live_stream_detection,
    trigger=IntervalTrigger(minutes=5),
    id="detect_live_streams",
    name="Live Stream Auto-Detection",
    replace_existing=True,
    misfire_grace_time=120,
)
```

Plus three corresponding `_run_*` wrapper functions.

---

#### [MODIFY] [processing_job.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/jobs/processing_job.py)

- Skip `transcript_segment` items from normal processing (they're intermediate data)
- Process `live_transcript` items through the full pipeline

```diff
  # In process_pending_content, add filter:
  select(ContentItem)
      .where(ContentItem.processing_status == "pending")
+     .where(ContentItem.content_type != "transcript_segment")
      .order_by(ContentItem.created_at.asc())

  # In _should_trigger_report:
  def _should_trigger_report(content_type: str) -> bool:
-     return content_type in {"filing", "article", "newsletter", "video"}
+     return content_type in {"filing", "article", "newsletter", "video", "live_transcript"}
```

---

#### [MODIFY] [ingestion_job.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/jobs/ingestion_job.py)

Add `live_stream` to `_fetch_documents` dispatch and `_detect_content_type`:

```python
# In _fetch_documents:
elif source_type == "live_stream":
    # Live streams are handled by the live_stream_job, not batch ingestion.
    # This is a no-op — live stream sources are polled by poll_active_live_streams.
    logger.debug("live_stream sources are handled by live stream polling job")
    return []

# In _detect_content_type:
if source_type == "live_stream":
    return "live_transcript"
```

---

### Phase 4: Backend API & SSE

---

#### [NEW] [live_streams.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/api/live_streams.py)

New API router (~120 lines):

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/investors/{id}/live-streams` | Start monitoring a live stream. Body: `{url, platform?, label?}`. Creates Source + LiveStreamSession. |
| `GET` | `/investors/{id}/live-streams` | List all sessions for investor (active first, then history). |
| `GET` | `/investors/{id}/live-streams/{session_id}` | Session detail + latest segments. |
| `GET` | `/investors/{id}/live-streams/{session_id}/transcript` | Full concatenated transcript so far. |
| `DELETE` | `/investors/{id}/live-streams/{session_id}` | Stop monitoring (sets status='ended', triggers consolidation). |
| `GET` | `/investors/{id}/live-streams/{session_id}/events` | **SSE endpoint** — streams new transcript segments as they arrive. |

**SSE endpoint detail:**
```python
@router.get("/{investor_id}/live-streams/{session_id}/events")
async def stream_transcript_events(
    investor_id: uuid.UUID,
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
):
    """
    Server-Sent Events endpoint.
    Streams new transcript segments as they are captured.
    
    Event format:
    data: {"segment_index": 42, "text": "...", "start_time": 1234.5, "end_time": 1264.5, "timestamp": "..."}
    
    Also sends periodic heartbeats and a 'stream_ended' event when the session ends.
    """
    return EventSourceResponse(transcript_event_generator(session_id))
```

Uses an in-memory `asyncio.Queue` per session (set up in `live_stream_service.py`) to push segments from the polling job to connected SSE clients. Falls back to DB polling if the client reconnects.

---

#### [MODIFY] [main.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/app/main.py)

Register the new router:

```python
from api.live_streams import router as live_streams_router
app.include_router(live_streams_router, prefix=f"{prefix}/investors", tags=["live-streams"])
```

---

### Phase 5: Backend Schemas & Services

---

#### [NEW] [live_stream.py (schema)](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/schemas/live_stream.py)

```python
class LiveStreamCreate(BaseModel):
    url: str
    platform: Literal["youtube", "cnbc", "bloomberg", "yahoo_finance", "custom"] | None = None
    label: str | None = None

class LiveStreamSessionResponse(BaseModel):
    id: uuid.UUID
    investor_id: uuid.UUID
    stream_url: str
    stream_title: str | None
    platform: str
    status: str  # monitoring | ended | consolidating | completed | failed
    started_at: datetime
    ended_at: datetime | None
    segment_count: int
    total_duration_seconds: int
    last_segment_at: datetime | None
    error_message: str | None
    created_at: datetime

class TranscriptSegmentResponse(BaseModel):
    segment_index: int
    text: str
    start_time: float
    end_time: float
    timestamp: datetime

class LiveTranscriptResponse(BaseModel):
    session_id: uuid.UUID
    full_text: str
    segment_count: int
    total_duration_seconds: int
    is_live: bool
```

---

#### [NEW] [live_stream_service.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/services/live_stream_service.py)

Business logic (~200 lines):

```python
# Session management
async def create_session(db, investor_id, user_id, data: LiveStreamCreate) -> LiveStreamSession
async def list_sessions(db, investor_id, user_id) -> list[LiveStreamSession]
async def get_session(db, session_id, user_id) -> LiveStreamSession | None
async def stop_session(db, session_id, user_id) -> LiveStreamSession | None

# Transcript
async def get_transcript(db, session_id) -> LiveTranscriptResponse
async def get_segments(db, session_id, after_index: int = 0) -> list[TranscriptSegmentResponse]

# SSE event management (in-memory queues)
_session_queues: dict[uuid.UUID, list[asyncio.Queue]] = {}

def subscribe_to_session(session_id: uuid.UUID) -> asyncio.Queue
def unsubscribe_from_session(session_id: uuid.UUID, queue: asyncio.Queue)
async def broadcast_segment(session_id: uuid.UUID, segment: TranscriptSegmentResponse)

# Platform detection
def detect_platform(url: str) -> str  # Auto-detect platform from URL
```

---

#### [MODIFY] [source.py (schema)](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/schemas/source.py)

```diff
-SourceType = Literal["sec_13f", "website", "youtube", "rss", "twitter", "custom"]
+SourceType = Literal["sec_13f", "website", "youtube", "rss", "twitter", "custom", "live_stream"]
```

---

### Phase 6: Frontend

---

#### [MODIFY] [api.ts](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/frontend/src/types/api.ts)

Add new types:

```typescript
export interface LiveStreamSession {
  id: string
  investor_id: string
  stream_url: string
  stream_title: string | null
  platform: 'youtube' | 'cnbc' | 'bloomberg' | 'yahoo_finance' | 'custom'
  status: 'monitoring' | 'ended' | 'consolidating' | 'completed' | 'failed'
  started_at: string
  ended_at: string | null
  segment_count: number
  total_duration_seconds: number
  last_segment_at: string | null
  error_message: string | null
  created_at: string
}

export interface LiveStreamCreate {
  url: string
  platform?: LiveStreamSession['platform']
  label?: string
}

export interface TranscriptSegment {
  segment_index: number
  text: string
  start_time: number
  end_time: number
  timestamp: string
}

// Update Source type
export interface Source {
  // ... existing fields
  source_type: 'sec_13f' | 'website' | 'youtube' | 'rss' | 'twitter' | 'custom' | 'live_stream'
}

// Update ContentItem type  
export interface ContentItem {
  // ... existing fields
  content_type: 'filing' | 'article' | 'video' | 'newsletter' | 'website_page' | 'custom' | 'transcript_segment' | 'live_transcript'
}
```

---

#### [MODIFY] [api.ts](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/frontend/src/lib/api.ts)

Add live streams API client:

```typescript
export const liveStreamsApi = {
  list: (investorId: string) =>
    apiClient.get<LiveStreamSession[]>(`/investors/${investorId}/live-streams`),
  create: (investorId: string, data: LiveStreamCreate) =>
    apiClient.post<LiveStreamSession>(`/investors/${investorId}/live-streams`, data),
  get: (investorId: string, sessionId: string) =>
    apiClient.get<LiveStreamSession>(`/investors/${investorId}/live-streams/${sessionId}`),
  getTranscript: (investorId: string, sessionId: string) =>
    apiClient.get<{ full_text: string; segment_count: number; is_live: boolean }>(
      `/investors/${investorId}/live-streams/${sessionId}/transcript`
    ),
  stop: (investorId: string, sessionId: string) =>
    apiClient.delete(`/investors/${investorId}/live-streams/${sessionId}`),
  // SSE is handled directly via EventSource, not axios
}
```

---

#### [NEW] [useLiveStreams.ts](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/frontend/src/hooks/useLiveStreams.ts)

React Query hooks + SSE subscription hook:

```typescript
export const LIVE_STREAM_KEYS = {
  all: (investorId: string) => ['live-streams', investorId] as const,
  detail: (investorId: string, sessionId: string) => ['live-streams', investorId, sessionId] as const,
  transcript: (investorId: string, sessionId: string) => ['live-streams', investorId, sessionId, 'transcript'] as const,
}

export function useLiveStreams(investorId: string) { ... }
export function useCreateLiveStream(investorId: string) { ... }
export function useStopLiveStream(investorId: string) { ... }
export function useLiveTranscript(investorId: string, sessionId: string) { ... }

// SSE hook for real-time segments
export function useLiveStreamEvents(investorId: string, sessionId: string, enabled: boolean) {
  // Creates an EventSource connection to the SSE endpoint
  // Returns { segments: TranscriptSegment[], isConnected: boolean, error: string | null }
  // Accumulates segments in state as they arrive
  // Auto-reconnects on disconnect
}
```

---

#### [NEW] [LiveStreamPanel.tsx](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/frontend/src/components/investors/LiveStreamPanel.tsx)

Main live stream UI component (~250 lines). Renders inside the investor detail page as a new tab.

**Design:**
- **Header**: Stream title, platform badge (YouTube/CNBC/Bloomberg), live indicator (pulsing red dot), duration timer
- **Transcript area**: Auto-scrolling container showing transcript segments as they arrive, with timestamps on the left. New text fades in with a smooth animation.
- **Controls**: "Start Monitoring" button (opens a modal with URL input + platform selector), "Stop" button for active streams
- **Session history**: List of past live stream sessions with links to consolidated transcripts

```
┌─────────────────────────────────────────────────────────────┐
│  🔴 LIVE  │  Trump Speech on Tariffs - CNBC  │  ⏱ 00:12:34 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  00:00:12  We are going to announce a very important...     │
│  00:00:42  The tariffs on China will be reduced to...       │
│  00:01:15  This is going to be the biggest deal in...       │
│  00:01:48  ▊  (cursor — waiting for next segment)          │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  [Stop Monitoring]                                          │
└─────────────────────────────────────────────────────────────┘
```

---

#### [MODIFY] [SourceManager.tsx](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/frontend/src/components/investors/SourceManager.tsx)

- Add `live_stream` option to the source type dropdown
- Add `Radio` (or similar) icon for live streams in the icon map

---

#### [MODIFY] [page.tsx (investor detail)](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/frontend/src/app/(dashboard)/investors/[id]/page.tsx)

- Add a new **"Live Streams"** tab alongside Content, Portfolio, Sources, Reports, Alerts
- Import and render `LiveStreamPanel` in the new tab
- Add a live indicator badge on the tab if any session is actively monitoring

```diff
  <TabsList>
    <TabsTrigger value="content">Content</TabsTrigger>
    <TabsTrigger value="portfolio">Portfolio</TabsTrigger>
+   <TabsTrigger value="live-streams">
+     Live Streams {activeSessions > 0 && <span className="ml-1 w-2 h-2 rounded-full bg-red-500 animate-pulse inline-block" />}
+   </TabsTrigger>
    <TabsTrigger value="sources">Sources</TabsTrigger>
    <TabsTrigger value="reports">Reports</TabsTrigger>
    <TabsTrigger value="alerts">Alerts</TabsTrigger>
  </TabsList>
```

---

### Dependencies

#### [MODIFY] [pyproject.toml](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/pyproject.toml)

```diff
  # Loader dependencies
  ...
+ # Live stream support
+ "streamlink>=7.0",
+ "webvtt-py>=0.5",
+ "sse-starlette>=2.0",
```

- `streamlink` — extracts media streams from CNBC/Bloomberg/Yahoo page URLs
- `webvtt-py` — parses WebVTT caption files from yt-dlp
- `sse-starlette` — Server-Sent Events support for FastAPI
- `yt-dlp` and `openai` (Whisper) are already dependencies
- `ffmpeg` must be available on the system PATH (for audio extraction); add to Dockerfile

#### [MODIFY] Dockerfile

```diff
+ # Install ffmpeg for audio processing (live stream transcription)
+ RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
```

---

## File Summary

| Phase | File | Action | Lines (est.) |
|-------|------|--------|-------------|
| 1 | `models/source.py` | MODIFY | +1 |
| 1 | `models/content_item.py` | MODIFY | +2 |
| 1 | `models/live_stream_session.py` | NEW | ~60 |
| 1 | `models/__init__.py` | MODIFY | +1 |
| 1 | Alembic migration | NEW | ~50 |
| 2 | `ingestion/live_stream_loader.py` | NEW | ~200 |
| 3 | `jobs/live_stream_job.py` | NEW | ~150 |
| 3 | `jobs/scheduler.py` | MODIFY | +35 |
| 3 | `jobs/processing_job.py` | MODIFY | +5 |
| 3 | `jobs/ingestion_job.py` | MODIFY | +8 |
| 4 | `api/live_streams.py` | NEW | ~120 |
| 4 | `app/main.py` | MODIFY | +3 |
| 5 | `schemas/live_stream.py` | NEW | ~50 |
| 5 | `schemas/source.py` | MODIFY | +1 |
| 5 | `services/live_stream_service.py` | NEW | ~200 |
| 6 | `frontend/src/types/api.ts` | MODIFY | +30 |
| 6 | `frontend/src/lib/api.ts` | MODIFY | +15 |
| 6 | `frontend/src/hooks/useLiveStreams.ts` | NEW | ~100 |
| 6 | `frontend/src/components/investors/LiveStreamPanel.tsx` | NEW | ~250 |
| 6 | `frontend/src/components/investors/SourceManager.tsx` | MODIFY | +5 |
| 6 | `frontend/src/app/(dashboard)/investors/[id]/page.tsx` | MODIFY | +20 |
| — | `pyproject.toml` | MODIFY | +3 |
| — | `Dockerfile` | MODIFY | +1 |

**Total: ~1,300 lines of new/modified code**

---

## Verification Plan

### Automated Tests

```bash
# Unit tests for live stream loader (mocked yt-dlp/streamlink)
pytest tests/test_live_stream_loader.py -v

# Unit tests for consolidation logic
pytest tests/test_live_stream_consolidation.py -v

# API endpoint tests
pytest tests/test_live_stream_api.py -v
```

### Manual Verification

1. **YouTube Live**: Find a currently live YouTube stream → paste URL → verify segments appear every ~30s → stop → verify consolidation creates a single transcript
2. **CNBC**: Use CNBC live URL → verify streamlink captures audio → Whisper transcribes → segments appear
3. **Auto-detection**: Add a YouTube channel source that has a live stream → wait 5 minutes → verify auto-detected session is created
4. **Live UI**: Open the Live Streams tab → start monitoring → verify transcript text appears in real-time with smooth animations
5. **Pipeline integration**: After stream ends and consolidation completes, verify entity extraction and thesis extraction run on the full transcript
6. **SSE reconnection**: Kill the browser tab, reopen → verify SSE reconnects and shows full transcript including missed segments
