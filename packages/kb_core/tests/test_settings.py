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


def test_database_url_built_from_parts_in_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    # ECS injects the username and password from the RDS-managed secret (Phase 6c).
    monkeypatch.setenv("KB_DB_HOST", "kb.cluster-abc.us-east-1.rds.amazonaws.com")
    monkeypatch.setenv("KB_DB_USERNAME", "kb_admin")
    monkeypatch.setenv("KB_DB_PASSWORD", "p@ss/w:rd?#")
    s = Settings(_env_file=None)
    assert s.database_url == (
        "postgresql+psycopg://kb_admin:p%40ss%2Fw%3Ard%3F%23"
        "@kb.cluster-abc.us-east-1.rds.amazonaws.com:5432/kb?sslmode=require"
    )
    assert "p@ss" not in repr(s.db_password)  # SecretStr keeps it out of logs


def test_database_parts_need_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_DB_HOST", "kb.cluster-abc.us-east-1.rds.amazonaws.com")
    with pytest.raises(ValueError, match="KB_DB_USERNAME"):
        Settings(_env_file=None)


def test_database_url_unchanged_without_db_host() -> None:
    assert Settings(_env_file=None).database_url.startswith(
        "postgresql+psycopg://kb:kb_local_only@localhost"
    )


def test_semantic_cache_is_off_by_default_and_empty_means_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KB_CACHE_SEMANTIC_THRESHOLD", raising=False)
    assert Settings(_env_file=None).cache_semantic_threshold is None
    monkeypatch.setenv("KB_CACHE_SEMANTIC_THRESHOLD", "")
    assert Settings(_env_file=None).cache_semantic_threshold is None
    monkeypatch.setenv("KB_CACHE_SEMANTIC_THRESHOLD", "0.99")
    assert Settings(_env_file=None).cache_semantic_threshold == 0.99
