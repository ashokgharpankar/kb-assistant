import pytest

from kb_core.settings import Settings


def test_defaults_are_free_and_local() -> None:
    # A fresh clone must never call a paid API by accident.
    s = Settings(_env_file=None)
    assert s.llm_provider == "ollama"
    assert s.env == "local"


def test_env_var_switches_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_LLM_PROVIDER", "bedrock")
    assert Settings(_env_file=None).llm_provider == "bedrock"


def test_embed_dimensions_read_from_env_string(monkeypatch: pytest.MonkeyPatch) -> None:
    # Env vars are always strings. This is the case a .env file produces.
    monkeypatch.setenv("KB_EMBED_DIMENSIONS", "1024")
    assert Settings(_env_file=None).embed_dimensions == 1024


def test_embed_dimensions_rejects_unsupported_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_EMBED_DIMENSIONS", "300")
    with pytest.raises(ValueError):
        Settings(_env_file=None)
