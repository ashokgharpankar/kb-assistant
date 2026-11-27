"""Model providers: the one place that knows about Ollama vs Bedrock.

Everything else asks for `get_embeddings()` / `get_chat_model()` and receives a
LangChain interface. Switching `KB_LLM_PROVIDER` changes the bill, not the code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

from kb_core.settings import Settings

# Known output sizes. A vector index is built for one size, so a provider's
# dimension decides which table its vectors live in.
_OLLAMA_DIMS = {"nomic-embed-text": 768, "mxbai-embed-large": 1024, "all-minilm": 384}


class PrefixedEmbeddings(Embeddings):
    """Adds task prefixes some embedding models were trained with.

    nomic-embed-text expects "search_document: " on stored text and
    "search_query: " on questions. Without them retrieval quality drops,
    and nothing errors: the kind of bug only evaluation catches.
    """

    def __init__(self, inner: Embeddings, document_prefix: str, query_prefix: str) -> None:
        self.inner = inner
        self.document_prefix = document_prefix
        self.query_prefix = query_prefix

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed_documents([self.document_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed_query(self.query_prefix + text)


@dataclass(frozen=True)
class EmbeddingSpace:
    """Identifies a family of vectors that can be compared with each other."""

    provider: str
    model: str
    dimensions: int

    @property
    def table_name(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", f"{self.provider}_{self.model}").strip("_")
        return f"kb_chunks_{slug}_{self.dimensions}"[:63]  # Postgres identifier limit


def embedding_space(settings: Settings) -> EmbeddingSpace:
    if settings.llm_provider == "ollama":
        model = settings.ollama_embed_model
        base = model.split(":")[0]
        if base not in _OLLAMA_DIMS:
            raise ValueError(
                f"unknown dimension for Ollama model {model!r}; add it to _OLLAMA_DIMS"
            )
        return EmbeddingSpace("ollama", model, _OLLAMA_DIMS[base])
    return EmbeddingSpace("bedrock", settings.bedrock_embed_model, settings.embed_dimensions)


def get_embeddings(settings: Settings) -> Embeddings:
    if settings.llm_provider == "ollama":
        from langchain_ollama import OllamaEmbeddings

        inner = OllamaEmbeddings(
            model=settings.ollama_embed_model, base_url=settings.ollama_base_url
        )
        if settings.ollama_embed_model.startswith("nomic-embed-text"):
            return PrefixedEmbeddings(inner, "search_document: ", "search_query: ")
        return inner

    from langchain_aws import BedrockEmbeddings

    return BedrockEmbeddings(
        model_id=settings.bedrock_embed_model,
        region_name=settings.aws_region,
        dimensions=settings.embed_dimensions,
        normalize=True,
    )


def get_chat_model(settings: Settings, model: str | None = None) -> BaseChatModel:
    """The configured chat model, or `model` from the same provider (Phase 8b routing)."""
    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model or settings.ollama_chat_model,
            base_url=settings.ollama_base_url,
            temperature=0.1,
            num_predict=settings.answer_max_tokens,
            num_ctx=8192,  # Ollama's default (2048) would silently truncate the retrieved context
        )

    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(
        model_id=model or settings.bedrock_chat_model,
        region_name=settings.aws_region,
        temperature=0.1,
        max_tokens=settings.answer_max_tokens,
    )


def chat_model_id(settings: Settings) -> str:
    return (
        settings.ollama_chat_model
        if settings.llm_provider == "ollama"
        else settings.bedrock_chat_model
    )
