"""
Queries the Chroma collection built by indexer.py.
"""
from __future__ import annotations

from app.config import settings
from app.embedder import embed_query
from app.vectorstore import get_collection


def retrieve(query: str, subdomain: str | None = None, top_k: int | None = None) -> list[dict]:
    """Returns a list of {text, similarity, paper_title, source_path, page},
    sorted by similarity descending."""
    top_k = top_k or settings.rag_top_k
    collection = get_collection()

    where = {"subdomain": subdomain} if subdomain and subdomain != "All" else None
    query_embedding = embed_query(query)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
    )

    if not results["ids"] or not results["ids"][0]:
        return []

    out = []
    for text, meta, distance in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        # Collection uses cosine space, so distance = 1 - cosine_similarity.
        similarity = 1 - distance
        out.append(
            {
                "text": text,
                "similarity": similarity,
                "paper_title": meta.get("paper_title"),
                "source_path": meta.get("source_path"),
                "page": meta.get("page"),
                "subdomain": meta.get("subdomain"),
            }
        )
    return out


def list_papers(subdomain: str | None = None) -> list[dict]:
    """Returns distinct {paper_title, source_path, subdomain} in the
    library, for the report pipeline and sidebar."""
    collection = get_collection()
    where = {"subdomain": subdomain} if subdomain and subdomain != "All" else None
    results = collection.get(where=where, include=["metadatas"])

    seen = {}
    for meta in results["metadatas"]:
        path = meta.get("source_path")
        if path not in seen:
            seen[path] = {
                "paper_title": meta.get("paper_title"),
                "source_path": path,
                "subdomain": meta.get("subdomain"),
            }
    return list(seen.values())
