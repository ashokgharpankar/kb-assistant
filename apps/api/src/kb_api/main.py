"""API entry point.

Phase 0 ships only a health endpoint. It is still worth having: the load
balancer, the container health check and the deploy pipeline will all call it.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from kb_core import __version__
from kb_core.settings import get_settings

app = FastAPI(title="KB Assistant API", version=__version__)


class Health(BaseModel):
    status: str
    version: str
    env: str
    llm_provider: str


@app.get("/health")
def health() -> Health:
    s = get_settings()
    return Health(status="ok", version=__version__, env=s.env, llm_provider=s.llm_provider)
