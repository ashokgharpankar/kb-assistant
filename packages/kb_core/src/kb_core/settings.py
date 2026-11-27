"""Typed application settings.

Twelve-factor rule: configuration lives in the environment, never in code.
Every value here can be overridden with an env var prefixed `KB_`
(for example `KB_LLM_PROVIDER=bedrock`), or in a local `.env` file.

Why this matters for FinOps: `KB_LLM_PROVIDER` is the switch between free local
models (Ollama) and paid Bedrock models. Same code, different bill.
"""

from functools import lru_cache
from typing import Literal, Self
from urllib.parse import quote

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KB_", env_file=".env", extra="ignore")

    env: Literal["local", "dev", "prod"] = "local"

    # --- model routing -------------------------------------------------------
    llm_provider: Literal["ollama", "bedrock"] = "ollama"

    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.2"
    ollama_embed_model: str = "nomic-embed-text"

    aws_region: str = "us-east-1"
    bedrock_chat_model: str = "amazon.nova-micro-v1:0"
    bedrock_embed_model: str = "amazon.titan-embed-text-v2:0"
    # Titan v2 supports 256 / 512 / 1024. Smaller = cheaper storage and faster search.
    embed_dimensions: int = 512
    # Filled in from `terraform output app_role_arn` once Phase 0 infra exists.
    app_role_arn: str | None = None

    @model_validator(mode="after")
    def _database_url_from_parts(self) -> Self:
        if self.db_host is None:
            return self
        if not self.db_username or self.db_password is None:
            raise ValueError("KB_DB_HOST is set, so KB_DB_USERNAME and KB_DB_PASSWORD are required")
        # Quote both: generated passwords can contain characters that break a URL.
        user = quote(self.db_username, safe="")
        password = quote(self.db_password.get_secret_value(), safe="")
        self.database_url = (
            f"postgresql+psycopg://{user}:{password}@{self.db_host}:{self.db_port}/"
            f"{self.db_name}?sslmode={self.db_sslmode}"
        )
        return self

    @field_validator("cache_semantic_threshold", mode="before")
    @classmethod
    def _empty_means_off(cls, value: object) -> object:
        # `KB_CACHE_SEMANTIC_THRESHOLD=` in .env must mean "off", not a parse error.
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("embed_dimensions")
    @classmethod
    def _valid_embed_dimensions(cls, value: int) -> int:
        # An int field (not a Literal) so the string "512" from an env var is converted.
        if value not in (256, 512, 1024):
            raise ValueError("embed_dimensions must be 256, 512 or 1024")
        return value

    # --- ingestion and retrieval (Phase 1) -----------------------------------
    data_dir: str = "data/raw"
    # Characters, not tokens: about 4 characters per token for English, so
    # 1200 characters is roughly 300 tokens. See docs/adr/0004-chunking-strategy.md
    chunk_size: int = Field(default=1200, ge=200, le=8000)
    chunk_overlap: int = Field(default=200, ge=0, le=2000)
    # Sections come from the PDF's table of contents down to this depth (Phase 4).
    toc_depth: int = Field(default=4, ge=1, le=8)
    # Embed each chunk under its heading path ("Security > Design principles").
    chunk_headers: bool = True
    retrieval_k: int = Field(default=4, ge=1, le=20)
    # "vector": cosine similarity only. "hybrid": vectors + Postgres full-text search,
    # merged with reciprocal rank fusion (Phase 4).
    retrieval_mode: Literal["vector", "hybrid"] = "hybrid"
    # "none" or "flashrank" (a small local cross-encoder; downloads ~30 MB once).
    reranker: Literal["none", "flashrank"] = "none"
    # How many candidates hybrid search and the reranker look at before keeping k.
    retrieval_candidates: int = Field(default=20, ge=1, le=100)
    # Cosine similarity below this is treated as "not relevant": no model call.
    # 0.62 sits in the measured gap (off-topic <= 0.571, relevant >= 0.730, with
    # nomic-embed-text; investigation 0001). `kb eval` recommends a value from the
    # evaluation set; each embedding model needs its own calibration.
    min_similarity: float = Field(default=0.62, ge=0.0, le=1.0)
    answer_max_tokens: int = Field(default=600, ge=50, le=4000)
    # "pipeline": retrieve once, answer once (Phases 1-4). "agent": a LangGraph loop that
    # searches again when the answer comes back "not found" (Phase 5b, ADR 0013).
    answer_mode: Literal["pipeline", "agent"] = "pipeline"
    # Phase 7b: input screen, refusal detection and grounding check around every answer.
    # Off only to measure the model without them (`KB_GUARDRAILS=false kb eval`).
    guardrails: bool = True
    # Phase 8a: answer cache. Exact hits are always safe; semantic hits reuse the answer
    # to a near-identical earlier question (cosine >= threshold). Off by default: with
    # nomic-embed-text, "Is it safe…" vs "Is it unsafe…" scored 0.986, above almost every
    # true rewording, so no threshold is safe (`kb cache-check`, ADR 0018). Unset or
    # empty = exact only.
    cache_enabled: bool = True
    cache_semantic_threshold: float | None = Field(default=None, ge=0.8, le=1.0)
    cache_ttl_hours: int = Field(default=168, ge=1)
    # What the eval reports as "projected cost": local token counts priced as this model.
    projected_price_model: str = "amazon.nova-micro-v1:0"
    # The agent's hard limit on searches per question; bounds cost and latency.
    agent_max_searches: int = Field(default=3, ge=1, le=5)

    # --- data stores ---------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://kb:kb_local_only@localhost:5433/kb",
        description="Local pgvector. Port 5433 so it never clashes with Langfuse's Postgres.",
    )
    # In AWS (Phase 6c) the URL is built from parts: ECS injects the username and
    # password from the Secrets Manager secret RDS manages, so no full URL containing
    # the password is ever stored. Setting KB_DB_HOST switches to this mode.
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "kb"
    db_username: str | None = None
    db_password: SecretStr | None = None
    db_sslmode: Literal["disable", "prefer", "require", "verify-full"] = "require"

    # --- authentication (Phase 2c) --------------------------------------------
    # "cognito": the API rejects requests without a valid Cognito access token.
    # "disabled": no sign-in; only for tests and the demo, never for a deployed API.
    # The default is the safe one: a missing setting can't silently open the API.
    auth_mode: Literal["cognito", "disabled"] = "cognito"
    # From `terraform output` (Phase 2c). The region is aws_region above.
    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None

    # --- observability -------------------------------------------------------
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
