# Bring Your Own Key (BYOK) — Multi-Provider API Key Management

Allow users to provide their own API keys for OpenAI, Anthropic (Claude), or Google (Gemini) and select which provider powers their LLM calls.

## Confirmed Decisions

| Decision | Choice |
|---|---|
| **Multi-provider support** | ✅ Option B — Users pick a provider (OpenAI/Claude/Gemini) + provide a key. LLM calls route through their chosen provider with equivalent models. |
| **Embeddings** | Server key only — always uses your OpenAI `text-embedding-3-small` key. User keys are for LLM calls only. |
| **Fallback** | Graceful fallback to server key when user hasn't configured one. |

---

## Current LLM Touchpoints (Audit)

All places that need modification:

| File | Current Model | Purpose | Needs BYOK? |
|---|---|---|---|
| [entity_extractor.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/agents/nodes/entity_extractor.py) | `gpt-4o-mini` | Entity extraction from chunks | ✅ Yes |
| [thesis_extractor.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/agents/nodes/thesis_extractor.py) | `gpt-4o` | Investment thesis extraction | ✅ Yes |
| [report_generator.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/agents/nodes/report_generator.py) | `gpt-4o` | Report markdown generation | ✅ Yes |
| [vector_store.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/services/vector_store.py) | `text-embedding-3-small` | Embeddings for semantic search | ❌ No (server key) |

---

## Proposed Changes

### 1. Database Layer

#### [NEW] `user_api_keys` table (migration)

```sql
CREATE TABLE user_api_keys (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(20) NOT NULL,        -- 'openai' | 'anthropic' | 'google'
    encrypted_key TEXT NOT NULL,           -- Fernet-encrypted API key
    is_active BOOLEAN DEFAULT true NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    UNIQUE(user_id, provider)
);
CREATE INDEX idx_user_api_keys_user ON user_api_keys(user_id);
```

The `is_active` flag on each row indicates which provider is the user's *selected* provider. Only one row per user should have `is_active = true` at a time. When a user switches providers, we set the old one to `false` and the new one to `true`. The key data stays — so switching back doesn't require re-entering.

#### [NEW] [user_api_key.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/models/user_api_key.py)

SQLAlchemy model:

```python
class UserApiKey(Base):
    __tablename__ = "user_api_keys"
    
    id            = Column(UUID, primary_key=True, default=uuid4)
    user_id       = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider      = Column(String(20), nullable=False)     # openai | anthropic | google
    encrypted_key = Column(Text, nullable=False)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (UniqueConstraint("user_id", "provider"),)
```

---

### 2. Encryption Service

#### [NEW] [crypto.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/services/crypto.py)

Fernet symmetric encryption for API keys at rest:

```python
from cryptography.fernet import Fernet
from app.config import get_settings

def encrypt_api_key(plaintext: str) -> str: ...
def decrypt_api_key(ciphertext: str) -> str: ...
```

Requires a `ENCRYPTION_KEY` env var (a Fernet key generated via `Fernet.generate_key()`).

#### [MODIFY] [config.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/app/config.py)

Add:
```python
encryption_key: str  # Fernet key for encrypting user API keys
```

#### [MODIFY] [.env](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/.env)

Add:
```
ENCRYPTION_KEY=<generated-fernet-key>
```

---

### 3. Unified LLM Client

#### [NEW] [llm_client.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/services/llm_client.py)

A thin wrapper that normalizes the chat completion interface across all 3 providers:

```python
class LLMClient:
    """Unified LLM interface across OpenAI, Anthropic, and Google."""
    
    provider: str       # "openai" | "anthropic" | "google"
    api_key: str
    
    def chat(
        self,
        messages: list[dict],
        model_tier: str,          # "fast" or "standard"
        temperature: float = 0,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> str:
        """Returns raw text response. Routes to the right SDK internally."""
```

**Model tier mapping:**

| `model_tier` | Use Case | OpenAI | Anthropic (Claude) | Google (Gemini) |
|---|---|---|---|---|
| `"fast"` | Entity extraction | `gpt-4o-mini` | `claude-sonnet-4-20250514` | `gemini-2.0-flash` |
| `"standard"` | Thesis extraction, Report generation | `gpt-4o` | `claude-sonnet-4-20250514` | `gemini-2.5-pro` |

> [!NOTE]
> The `model_tier` abstraction means pipeline nodes don't need to know which provider is active — they just say "I need a fast model" or "I need a standard model."

#### [NEW] [llm_factory.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/services/llm_factory.py)

Resolves which `LLMClient` to use for a given user:

```python
async def get_llm_client(user_id: str) -> LLMClient:
    """
    1. Query user_api_keys for active key where is_active=True
    2. If found → decrypt key → build LLMClient for that provider
    3. If not found → fallback to server OpenAI key
    """
```

This function is `async` because it queries the DB. For use inside synchronous pipeline nodes (LangGraph), we'll provide a sync variant `get_llm_client_sync(user_id)` that creates its own DB session.

---

### 4. API Layer

#### [NEW] [api_keys.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/api/api_keys.py)

REST endpoints under `/api/v1/settings/api-keys`:

| Method | Path | Description |
|---|---|---|
| `GET` | `/settings/api-keys` | List all configured providers. Returns `[{provider, masked_key, is_active}]` — never returns raw keys. Masked like `sk-proj-...xXFE`. |
| `PUT` | `/settings/api-keys/{provider}` | Upsert a key. Body: `{api_key: "sk-..."}`. **Validates the key** by making a lightweight test call (list models or a tiny completion). Returns success/error. |
| `DELETE` | `/settings/api-keys/{provider}` | Remove a stored key. If this was the active provider, falls back to server key. |
| `PUT` | `/settings/api-keys/active-provider` | Switch active provider. Body: `{provider: "anthropic"}`. Sets `is_active` on the matching row, clears it on others. Fails if no key exists for that provider. |

**Key validation strategy per provider:**

| Provider | Validation Call |
|---|---|
| OpenAI | `client.models.list()` (lightweight, no tokens consumed) |
| Anthropic | `client.messages.create(model="claude-sonnet-4-20250514", max_tokens=1, messages=[{"role":"user","content":"hi"}])` (1 token) |
| Google | `genai.Client(api_key=key).models.list()` |

#### [MODIFY] Main app router registration

Register the new router:
```python
app.include_router(api_keys_router, prefix="/api/v1/settings", tags=["settings"])
```

#### [NEW] [schemas/api_keys.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/schemas/api_keys.py)

Pydantic schemas:
- `ApiKeyResponse` — `{provider, masked_key, is_active}`
- `ApiKeyUpsertRequest` — `{api_key: str}`
- `ActiveProviderRequest` — `{provider: str}`

---

### 5. Pipeline Modifications

#### [MODIFY] [state.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/agents/state.py)

Add to `PipelineState`:
```python
# LLM configuration (resolved at pipeline start)
llm_provider: Optional[str]       # "openai" | "anthropic" | "google" | None (=server default)
llm_api_key: Optional[str]        # Decrypted key (or None for server default)
```

These are populated when the pipeline is invoked — the caller resolves the user's active key and passes it into the initial state.

#### [MODIFY] [entity_extractor.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/agents/nodes/entity_extractor.py)

Replace:
```python
client = OpenAI(api_key=settings.openai_api_key)
# ... 
response = client.chat.completions.create(model="gpt-4o-mini", ...)
```

With:
```python
from services.llm_client import LLMClient

client = LLMClient.from_state(state)  # reads provider + key from state
response_text = client.chat(
    messages=[{"role": "user", "content": prompt}],
    model_tier="fast",
    temperature=0,
    max_tokens=2000,
    json_mode=True,
)
```

#### [MODIFY] [thesis_extractor.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/agents/nodes/thesis_extractor.py)

Same pattern — replace `OpenAI(...)` + `client.chat.completions.create(model="gpt-4o", ...)` with `LLMClient.from_state(state).chat(model_tier="standard", ...)`.

#### [MODIFY] [report_generator.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/agents/nodes/report_generator.py)

Same pattern — use `LLMClient.from_state(state).chat(model_tier="standard", ...)`.

#### [MODIFY] Pipeline invocation sites

Wherever `run_pipeline(initial_state)` is called (processing jobs), we need to resolve the user's LLM config and inject it into the initial state:

```python
from services.llm_factory import resolve_llm_config

llm_provider, llm_api_key = await resolve_llm_config(user_id)
initial_state = {
    ...,
    "llm_provider": llm_provider,
    "llm_api_key": llm_api_key,
}
```

#### [NO CHANGE] [vector_store.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/services/vector_store.py)

Stays on server-side OpenAI key. No changes needed.

#### [NO CHANGE] [alert_checker.py](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/backend/agents/nodes/alert_checker.py)

Rule-based, no LLM calls. No changes needed.

---

### 6. Frontend Changes

#### [MODIFY] [settings/page.tsx](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/frontend/src/app/(dashboard)/settings/page.tsx)

Add a new **"AI Provider"** card between the Notifications card and the Account card. Design:

```
┌─────────────────────────────────────────────────────┐
│ 🤖 AI Provider                                      │
│ Choose your LLM provider and API key                │
│                                                      │
│ ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│ │  OpenAI  │  │  Claude  │  │  Gemini  │           │
│ │  ○ / ●   │  │  ○ / ●   │  │  ○ / ●   │           │
│ └──────────┘  └──────────┘  └──────────┘           │
│                                                      │
│ API Key  [••••••••••••••xXFE]  👁  [Save]          │
│                                                      │
│ Status: ● Connected                     [Remove]    │
│                                                      │
│ ℹ️ Using default server key (no key configured)      │
└─────────────────────────────────────────────────────┘
```

**Behaviors:**
- On load: `GET /settings/api-keys` → populate provider cards + masked keys
- Click provider card → `PUT /settings/api-keys/active-provider` (only if key exists for that provider)
- Enter key + Save → `PUT /settings/api-keys/{provider}` (validates → shows success/error)
- Remove → `DELETE /settings/api-keys/{provider}` + confirmation dialog
- When no key configured: shows subtle "Using default server key" message with a muted info badge
- Provider cards show a green dot when active & connected, gray when configured but inactive, empty when no key

#### [MODIFY] [api.ts](file:///Users/akshatsipany/Code-Playground-2026/arham/Pet-Project/frontend/src/lib/api.ts)

Add `settingsApi` namespace:

```typescript
export const settingsApi = {
  getApiKeys: () => apiClient.get('/settings/api-keys'),
  upsertApiKey: (provider: string, api_key: string) =>
    apiClient.put(`/settings/api-keys/${provider}`, { api_key }),
  deleteApiKey: (provider: string) =>
    apiClient.delete(`/settings/api-keys/${provider}`),
  setActiveProvider: (provider: string) =>
    apiClient.put('/settings/api-keys/active-provider', { provider }),
}
```

---

### 7. New Dependencies

#### Backend (add to `pyproject.toml`)
| Package | Purpose |
|---|---|
| `cryptography` | Fernet encryption for API keys at rest |
| `anthropic` | Anthropic Python SDK for Claude API calls |
| `google-genai` | Google GenAI SDK for Gemini API calls |

#### Frontend
No new dependencies.

---

## File Summary

| Action | File | Layer |
|---|---|---|
| **NEW** | `models/user_api_key.py` | Database |
| **NEW** | `services/crypto.py` | Encryption |
| **NEW** | `services/llm_client.py` | LLM abstraction |
| **NEW** | `services/llm_factory.py` | LLM resolution |
| **NEW** | `api/api_keys.py` | API endpoints |
| **NEW** | `schemas/api_keys.py` | API schemas |
| **MODIFY** | `app/config.py` | Add encryption_key |
| **MODIFY** | `backend/.env` | Add ENCRYPTION_KEY |
| **MODIFY** | `agents/state.py` | Add llm_provider/llm_api_key fields |
| **MODIFY** | `agents/nodes/entity_extractor.py` | Use LLMClient |
| **MODIFY** | `agents/nodes/thesis_extractor.py` | Use LLMClient |
| **MODIFY** | `agents/nodes/report_generator.py` | Use LLMClient |
| **MODIFY** | `app/main.py` | Register new router |
| **MODIFY** | `models/__init__.py` | Export new model |
| **MODIFY** | `frontend/.../settings/page.tsx` | AI Provider card |
| **MODIFY** | `frontend/src/lib/api.ts` | settingsApi methods |
| **NO CHANGE** | `services/vector_store.py` | Server key always |
| **NO CHANGE** | `agents/nodes/alert_checker.py` | No LLM calls |

---

## Verification Plan

### Automated Tests
```bash
# Existing test suite (regression check)
cd backend && python -m pytest tests/ -v

# Crypto round-trip
python -c "from services.crypto import encrypt_api_key, decrypt_api_key; assert decrypt_api_key(encrypt_api_key('test-key')) == 'test-key'; print('✅ Crypto OK')"
```

### Manual Verification
1. **No key configured** → trigger a pipeline job → verify it uses server OpenAI key (check logs for `provider=openai, source=server`)
2. **Add OpenAI key** → Settings → AI Provider → paste key → Save → verify green status
3. **Run pipeline** → verify logs show `provider=openai, source=user`
4. **Switch to Claude** → add Anthropic key → select Claude → run pipeline → verify Claude models used
5. **Switch to Gemini** → add Google key → select Gemini → run pipeline → verify Gemini models used
6. **Remove key** → delete active key → verify fallback to server key
7. **Invalid key** → paste garbage → Save → verify validation error
8. **Security** → `GET /settings/api-keys` → verify only masked keys returned (never raw)
9. **Embeddings isolation** → with Claude active, run semantic search → verify embeddings still use server OpenAI key
