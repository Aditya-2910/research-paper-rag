"""
Central settings, loaded from environment variables (.env). Import
`settings` from here anywhere in the app rather than reading os.environ
directly.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Paper library
    papers_dir: str = "papers"
    chroma_dir: str = "index/chroma"
    reports_dir: str = "reports"

    # Embeddings
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    embedding_device: str = "cuda"

    # Chunking
    chunk_size: int = 900
    chunk_overlap: int = 150

    # RAG
    rag_top_k: int = 6
    rag_similarity_threshold: float = 0.42

    # Paper acquisition (app/acquire.py)
    arxiv_request_delay_seconds: float = 3.0
    acquire_max_candidates: int = 8

    # LLM provider
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    log_level: str = "INFO"


settings = Settings()
