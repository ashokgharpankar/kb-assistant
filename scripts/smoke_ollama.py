"""Phase 0 smoke test for local models (free).

Checks that Ollama is running and that the chat and embedding models respond.
Uses only the standard library so it works before any project code exists.

Run:  make smoke-ollama
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from kb_core.settings import get_settings


def post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(  # local, fixed http://localhost URL
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result: dict[str, Any] = json.load(response)
        return result


def main() -> int:
    s = get_settings()
    base = s.ollama_base_url.rstrip("/")
    try:
        started = time.perf_counter()
        chat = post(
            f"{base}/api/chat",
            {
                "model": s.ollama_chat_model,
                "stream": False,
                "messages": [
                    {
                        "role": "user",
                        "content": "In one sentence, what is retrieval-augmented generation?",
                    }
                ],
            },
        )
        chat_ms = (time.perf_counter() - started) * 1000
        emb = post(
            f"{base}/api/embed",
            {"model": s.ollama_embed_model, "input": "Design for failure and nothing will fail."},
        )
    except urllib.error.URLError as exc:
        print(f"Cannot reach Ollama at {base}: {exc}")
        print("Start the Ollama app, then: ollama pull llama3.2 && ollama pull nomic-embed-text")
        return 1

    print(f"1. {s.ollama_chat_model}")
    print(f"   answer : {chat['message']['content'].strip()}")
    print(
        f"   tokens : {chat.get('prompt_eval_count')} in / {chat.get('eval_count')} out"
        f"   latency: {chat_ms:.0f} ms   cost: $0"
    )
    vector = emb["embeddings"][0]
    print(f"2. {s.ollama_embed_model}")
    print(f"   vector : {len(vector)} dimensions, first 3 = {vector[:3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
