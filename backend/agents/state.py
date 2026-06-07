from typing import Any, Optional
from typing_extensions import TypedDict


class ExtractedEntity(TypedDict):
    entity_type: str       # company | ticker | person | theme | macro_theme
    entity_name: str
    ticker_symbol: Optional[str]
    sentiment: Optional[str]   # bullish | bearish | neutral | mixed
    conviction_level: Optional[str]  # high | medium | low | unknown
    context_snippet: Optional[str]


class InvestmentThesis(TypedDict):
    company: str
    ticker: Optional[str]
    thesis_summary: str
    bullish_points: list[str]
    bearish_points: list[str]
    catalysts: list[str]
    risks: list[str]
    conviction_score: int  # 0–10


class PipelineState(TypedDict):
    # Input
    content_item_id: str
    investor_id: str
    user_id: str
    content_type: str       # filing | article | video | newsletter | website_page
    raw_text: str
    source_url: str
    investor_name: Optional[str]
    filing_period: Optional[str]

    # Processing
    cleaned_text: str
    chunks: list[Any]       # List[Document]

    # Extraction outputs
    entities: list[ExtractedEntity]
    theses: list[InvestmentThesis]

    # Flags
    embeddings_stored: bool
    report_generated: bool
    report_triggered: bool  # whether report generation was triggered this run
    alerts_created: list[str]

    # Error handling
    error: Optional[str]
