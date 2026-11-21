"""Download the knowledge-base documents listed in data/sources.json into data/raw/.

Skips files that are already present. Run:  make fetch-sources
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "sources.json"
TARGET = ROOT / "data" / "raw"


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    sources = json.loads(MANIFEST.read_text())["sources"]
    failed = 0
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        for src in sources:
            dest = TARGET / f"{src['id']}.pdf"
            if dest.exists():
                print(f"  exists   {dest.name}")
                continue
            try:
                response = client.get(src["url"])
                response.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"  FAILED   {src['id']}: {exc}")
                failed += 1
                continue
            dest.write_bytes(response.content)
            print(f"  fetched  {dest.name} ({len(response.content) / 1_048_576:.1f} MB)")
    print(f"\nFiles are in {TARGET.relative_to(ROOT)}/. Add your own .md runbooks there too.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
