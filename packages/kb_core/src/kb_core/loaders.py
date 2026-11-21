"""Turn files on disk into `SourceDocument`s.

PDFs: text per page with PyMuPDF, grouped into sections using the PDF's own
table of contents (bookmarks). Each section remembers which page every
character came from, so a chunk can cite an exact page later.

Markdown / text: split on `#` and `##` headings; "page" is always 1.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pymupdf

from kb_core.models import Section, SourceDocument

SUPPORTED_SUFFIXES = {".pdf", ".md", ".markdown", ".txt"}

# Section titles come from the TOC down to this depth. Deeper headings stay
# inside their parent section, which keeps sections reasonably sized.
_TOC_DEPTH = 2

_WS = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")
_PAGE_NUMBER_LINE = re.compile(r"^\s*(page\s+)?\d+\s*$", re.IGNORECASE)


def document_id_for(path: Path) -> str:
    """Stable id from the file name: `wellarchitected-framework.pdf` -> `wellarchitected-framework`."""
    return re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")


def clean_text(text: str) -> str:
    """Normalise whitespace and drop lines that are only a page number."""
    lines = [_WS.sub(" ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if not _PAGE_NUMBER_LINE.match(line)]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def load_pdf(path: Path) -> SourceDocument:
    with pymupdf.open(path) as pdf:  # type: ignore[no-untyped-call]
        pages = [clean_text(page.get_text("text")) for page in pdf]
        toc = [
            (level, title.strip(), page)
            for level, title, page in pdf.get_toc()
            if level <= _TOC_DEPTH
        ]
        title = (pdf.metadata or {}).get("title") or path.stem

    # Section boundaries: TOC entry -> first page of that entry (1-based).
    starts = [(max(page, 1), heading) for _, heading, page in toc if heading]
    if not starts or starts[0][0] > 1:
        starts.insert(0, (1, title))

    sections: list[Section] = []
    for i, (first_page, heading) in enumerate(starts):
        last_page = starts[i + 1][0] - 1 if i + 1 < len(starts) else len(pages)
        if last_page < first_page:  # several TOC entries on one page: give it to the last one
            continue
        parts: list[str] = []
        page_starts: list[tuple[int, int]] = []
        offset = 0
        for number in range(first_page, last_page + 1):
            text = pages[number - 1]
            if not text:
                continue
            page_starts.append((offset, number))
            parts.append(text)
            offset += len(text) + 2  # the "\n\n" join below
        if parts:
            sections.append(Section(heading, "\n\n".join(parts), tuple(page_starts)))

    return SourceDocument(document_id_for(path), title, path.resolve().as_uri(), tuple(sections))


_MD_HEADING = re.compile(r"^(#{1,2})\s+(.+?)\s*$", re.MULTILINE)


def load_markdown(path: Path) -> SourceDocument:
    raw = path.read_text(encoding="utf-8")
    matches = list(_MD_HEADING.finditer(raw))
    title = matches[0].group(2) if matches else path.stem

    sections: list[Section] = []
    bounds = [(m.start(), m.group(2)) for m in matches] or [(0, title)]
    if bounds[0][0] > 0 and raw[: bounds[0][0]].strip():
        bounds.insert(0, (0, title))
    for i, (start, heading) in enumerate(bounds):
        end = bounds[i + 1][0] if i + 1 < len(bounds) else len(raw)
        text = clean_text(raw[start:end])
        if text:
            sections.append(Section(heading, text, ((0, 1),)))

    return SourceDocument(document_id_for(path), title, path.resolve().as_uri(), tuple(sections))


def load_file(path: Path) -> SourceDocument:
    if path.suffix.lower() == ".pdf":
        return load_pdf(path)
    if path.suffix.lower() in SUPPORTED_SUFFIXES:
        return load_markdown(path)
    raise ValueError(f"unsupported file type: {path.name}")


def discover(root: Path) -> Iterator[Path]:
    """Every supported file under `root` (or `root` itself), in a stable order."""
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path
