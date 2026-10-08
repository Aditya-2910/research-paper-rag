"""
Thin wrapper around sentence-transformers. Loaded once and cached —
loading bge-large takes a few seconds, so we don't want to repeat that
per call.
"""
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.config import settings


@lru_cache
def get_embedder() -> SentenceTransformer:
    return SentenceTransformer(settings.embedding_model, device=settings.embedding_device)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts (documents being indexed — no instruction
    prefix needed, bge only recommends that on the query side)."""
    if not texts:
        return []
    model = get_embedder()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def embed_query(query: str) -> list[float]:
    """BGE models are trained with an instruction prefix on the query
    side for retrieval tasks — using it measurably improves retrieval."""
    model = get_embedder()
    prefixed = f"Represent this sentence for searching relevant passages: {query}"
    vector = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
    return vector.tolist()
