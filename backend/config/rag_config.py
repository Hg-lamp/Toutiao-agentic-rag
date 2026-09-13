import os
from dataclasses import dataclass


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


@dataclass(frozen=True)
class RagSettings:
    retrieval_concurrency: int = _env_int("RAG_RETRIEVAL_CONCURRENCY", 8)
    retrieval_timeout_seconds: float = _env_float("RAG_RETRIEVAL_TIMEOUT_SECONDS", 25.0, 0.1)

    parent_window: int = _env_int("RAG_PARENT_WINDOW", 1, 0)
    parent_expansion_concurrency: int = _env_int("RAG_PARENT_EXPANSION_CONCURRENCY", 8)

    max_per_document: int = _env_int("RAG_MAX_PER_DOCUMENT", 2)
    max_per_source: int = _env_int("RAG_MAX_PER_SOURCE", 3)

    total_token_budget: int = _env_int("RAG_TOTAL_TOKEN_BUDGET", 8000)
    system_token_reserve: int = _env_int("RAG_SYSTEM_TOKEN_RESERVE", 1200)
    history_token_reserve: int = _env_int("RAG_HISTORY_TOKEN_RESERVE", 1200)
    output_token_reserve: int = _env_int("RAG_OUTPUT_TOKEN_RESERVE", 1000)
    safety_token_margin: int = _env_int("RAG_SAFETY_TOKEN_MARGIN", 500)
    minimum_context_tokens: int = _env_int("RAG_MIN_CONTEXT_TOKENS", 500)

    rrf_k: int = _env_int("RAG_RRF_K", 60)
    rerank_weight: float = _env_float("RAG_RERANK_WEIGHT", 0.65)
    retrieval_weight: float = _env_float("RAG_RETRIEVAL_WEIGHT", 0.20)
    metadata_weight: float = _env_float("RAG_METADATA_WEIGHT", 0.15)


rag_settings = RagSettings()

