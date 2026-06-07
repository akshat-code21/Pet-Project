from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector

from app.config import get_settings

_store: PGVector | None = None


def get_vector_store() -> PGVector:
    global _store
    if _store is None:
        settings = get_settings()
        _store = PGVector(
            embeddings=OpenAIEmbeddings(
                model="text-embedding-3-small",
                api_key=settings.openai_api_key,
            ),
            collection_name="hedge_fund_content",
            connection=settings.database_url_sync,
            use_jsonb=True,
        )
    return _store
