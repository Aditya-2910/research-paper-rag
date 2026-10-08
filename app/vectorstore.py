"""
Single place that opens the Chroma persistent collection, so indexer.py
and retriever.py always agree on where it lives and how it's configured.
"""
from functools import lru_cache

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings

COLLECTION_NAME = "papers"


@lru_cache
def get_collection():
    client = chromadb.PersistentClient(
        path=settings.chroma_dir,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    # cosine distance so similarity = 1 - distance everywhere we read it back
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
