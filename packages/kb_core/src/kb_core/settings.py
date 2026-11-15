"""Typed application settings.

Twelve-factor rule: configuration lives in the environment, never in code.
Every value here can be overridden with an env var prefixed `KB_`
(for example `KB_LLM_PROVIDER=bedrock`), or in a local `.env` file.

Why this matters for FinOps: `KB_LLM_PROVIDER` is the switch between free local
models (Ollama) and paid Bedrock models. Same code, different bill.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
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

    @field_validator("embed_dimensions")
    @classmethod
    def _valid_embed_dimensions(cls, value: int) -> int:
        # An int field (not a Literal) so the string "512" from an env var is converted.
        if value not in (256, 512, 1024):
            raise ValueError("embed_dimensions must be 256, 512 or 1024")
        return value

    # --- data stores ---------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://kb:kb_local_only@localhost:5433/kb",
        description="Local pgvector. Port 5433 so it never clashes with Langfuse's Postgres.",
    )

    # --- observability -------------------------------------------------------
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
