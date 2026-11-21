import pytest

from kb_core.providers import EmbeddingSpace, PrefixedEmbeddings, embedding_space
from kb_core.settings import Settings

from .conftest import WordHashEmbeddings


class Recorder(WordHashEmbeddings):
    def __init__(self) -> None:
        self.seen: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.seen.extend(texts)
        return super().embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        self.seen.append(text)
        return super().embed_query(text)


def test_nomic_prefixes_are_added() -> None:
    inner = Recorder()
    emb = PrefixedEmbeddings(inner, "search_document: ", "search_query: ")
    emb.embed_documents(["a chunk"])
    emb.embed_query("a question")
    assert inner.seen == ["search_document: a chunk", "search_query: a question"]


def test_each_provider_gets_its_own_table() -> None:
    local = embedding_space(Settings(_env_file=None))
    cloud = embedding_space(Settings(_env_file=None, llm_provider="bedrock", embed_dimensions=512))
    assert local == EmbeddingSpace("ollama", "nomic-embed-text", 768)
    assert local.table_name == "kb_chunks_ollama_nomic_embed_text_768"
    assert cloud.table_name == "kb_chunks_bedrock_amazon_titan_embed_text_v2_0_512"


def test_unknown_ollama_embedding_model_fails_loudly() -> None:
    with pytest.raises(ValueError):
        embedding_space(Settings(_env_file=None, ollama_embed_model="mystery-embed"))
