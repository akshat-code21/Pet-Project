"""
Thesis extractor node.
Uses a sliding-window approach over cleaned_text for full-document coverage.
Uses GPT-4o for quality. Skipped for filing content_type.
"""
import json

import structlog
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from agents.prompts.thesis_extraction import THESIS_EXTRACTION_PROMPT
from agents.state import InvestmentThesis, PipelineState
from app.config import get_settings

logger = structlog.get_logger()
WINDOW_CHARS = 16_000
WINDOW_OVERLAP = 2_000


def _deduplicate_theses(all_theses: list[InvestmentThesis]) -> list[InvestmentThesis]:
    """Merge theses from multiple windows, keeping highest conviction score per company/ticker."""
    seen: dict[str, InvestmentThesis] = {}

    for thesis in all_theses:
        key = (thesis.get("company") or "").lower()
        ticker = (thesis.get("ticker") or "").upper()
        if ticker:
            key = ticker

        existing = seen.get(key)
        if existing is None:
            seen[key] = thesis
        else:
            if (thesis.get("conviction_score") or 0) > (existing.get("conviction_score") or 0):
                seen[key] = thesis

    return list(seen.values())


def thesis_extractor_node(state: PipelineState) -> PipelineState:
    # 13F filings have no thesis content — positions only
    if state.get("content_type") == "filing":
        return {**state, "theses": []}

    cleaned = state.get("cleaned_text", "") or ""
    if not cleaned or len(cleaned) < 200:
        return {**state, "theses": []}

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    # Sliding-window extraction for full-document coverage
    all_theses: list[InvestmentThesis] = []
    offset = 0
    window_idx = 0

    while offset < len(cleaned):
        window_text = cleaned[offset : offset + WINDOW_CHARS]
        if len(window_text) < 200:
            break  # remaining text too short to extract from

        try:
            theses = _extract_theses(client, window_text)
            all_theses.extend(theses)
            logger.debug(
                "thesis_extractor: window processed",
                window_idx=window_idx,
                theses_found=len(theses),
            )
        except Exception as e:
            logger.error("Thesis extraction window failed", window_idx=window_idx, error=str(e))
            # Continue with remaining windows even if one fails

        offset += WINDOW_CHARS - WINDOW_OVERLAP
        window_idx += 1

    if window_idx > 1:
        logger.info(
            "thesis_extractor: sliding window complete",
            windows=window_idx,
            total_theses_raw=len(all_theses),
        )

    # Deduplicate across windows
    theses = _deduplicate_theses(all_theses)

    # Merge conviction scores back into entities
    entities = state.get("entities", [])
    ticker_to_score = {t.get("ticker", "").upper(): t.get("conviction_score", 5) for t in theses if t.get("ticker")}
    name_to_score = {t.get("company", "").lower(): t.get("conviction_score", 5) for t in theses}

    for entity in entities:
        ticker = (entity.get("ticker_symbol") or "").upper()
        name = (entity.get("entity_name") or "").lower()
        score = ticker_to_score.get(ticker) or name_to_score.get(name)
        if score is not None:
            if score >= 7:
                entity["conviction_level"] = "high"
            elif score >= 4:
                entity["conviction_level"] = "medium"
            else:
                entity["conviction_level"] = "low"

    return {**state, "theses": theses, "entities": entities}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=10, max=60))
def _extract_theses(client: OpenAI, text: str) -> list[InvestmentThesis]:
    prompt = THESIS_EXTRACTION_PROMPT.format(full_text=text)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=3000,
    )
    raw = response.choices[0].message.content or "[]"
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        parsed = parsed.get("theses", list(parsed.values())[0] if parsed else [])
    return [_validate_thesis(t) for t in parsed if isinstance(t, dict)]


def _validate_thesis(t: dict) -> InvestmentThesis:
    return InvestmentThesis(
        company=t.get("company", ""),
        ticker=t.get("ticker"),
        thesis_summary=t.get("thesis_summary", ""),
        bullish_points=t.get("bullish_points", []),
        bearish_points=t.get("bearish_points", []),
        catalysts=t.get("catalysts", []),
        risks=t.get("risks", []),
        conviction_score=max(0, min(10, int(t.get("conviction_score", 5)))),
    )
