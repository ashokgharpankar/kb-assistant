"""Turn files on disk into `SourceDocument`s.

PDFs: text per page with PyMuPDF, grouped into sections using the PDF's own
table of contents (bookmarks). Each section remembers which page every
character came from, so a chunk can cite an exact page later.

Markdown / text: split on `#` and `##` headings; "page" is always 1.

Cleaning (see docs/investigations/0001-retrieval-quality.md for the evidence):
- ligatures expanded ("ﬁ" -> "fi") and Unicode normalised (NFKC)
- running page headers and footers removed
- table-of-contents dot-leader lines removed
- table of contents, document revisions and notices sections skipped
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
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
# "Implementation guidance ........ 25": a table-of-contents entry, not content.
_DOT_LEADER_LINE = re.compile(r"\.{5,}\s*\d*\s*$")

# PyMuPDF's default text flags KEEP ligature characters ("ﬁ" as one character),
# which breaks exact-word matching. Same defaults, ligatures expanded.
_PDF_TEXT_FLAGS = pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES

# Sections with no guidance in them. Matched against the section title.
_SKIP_SECTIONS = re.compile(
    r"^(table of contents|contents|document revisions?|notices|document history)$", re.IGNORECASE
)

# A line counts as a running header/footer if it sits in the first or last
# _EDGE_LINES lines of at least this share of pages.
_EDGE_LINES = 3
_REPEAT_SHARE = 0.5


def document_id_for(path: Path) -> str:
    """Stable id from the file name: `wellarchitected-framework.pdf` -> `wellarchitected-framework`."""
    return re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")


def normalize(text: str) -> str:
    """NFKC turns compatibility characters into plain ones: "ﬁ" -> "fi", "ﬀ" -> "ff",
    non-breaking spaces -> spaces. A safety net even when extraction expands ligatures."""
    return unicodedata.normalize("NFKC", text)


def clean_text(text: str, drop_lines: frozenset[str] = frozenset()) -> str:
    """Normalise, then drop page-number lines, dot-leader lines and known headers/footers."""
    lines = [_WS.sub(" ", line).strip() for line in normalize(text).splitlines()]
    lines = [
        line
        for line in lines
        if line not in drop_lines
        and not _PAGE_NUMBER_LINE.match(line)
        and not _DOT_LEADER_LINE.search(line)
    ]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def repeated_edge_lines(pages: list[str]) -> frozenset[str]:
    """Lines that appear near the top or bottom of most pages: running headers and footers.

    Only edge positions are considered, so a phrase that is merely common in the body
    (like "Implementation guidance") is never removed.
    """
    if len(pages) < 3:
        return frozenset()
    counts: Counter[str] = Counter()
    for page in pages:
        lines = [_WS.sub(" ", line).strip() for line in normalize(page).splitlines()]
        lines = [line for line in lines if line]
        counts.update(set(lines[:_EDGE_LINES] + lines[-_EDGE_LINES:]))
    threshold = max(3, int(len(pages) * _REPEAT_SHARE))
    return frozenset(line for line, n in counts.items() if n >= threshold and len(line) <= 120)


def load_pdf(path: Path) -> SourceDocument:
    with pymupdf.open(path) as pdf:  # type: ignore[no-untyped-call]
        raw_pages = [page.get_text("text", flags=_PDF_TEXT_FLAGS) for page in pdf]
        toc = [
            (level, normalize(title).strip(), page)
            for level, title, page in pdf.get_toc()
            if level <= _TOC_DEPTH
        ]
        title = normalize((pdf.metadata or {}).get("title") or path.stem)

    headers_footers = repeated_edge_lines(raw_pages)
    pages = [clean_text(page, headers_footers) for page in raw_pages]

    # Section boundaries: TOC entry -> first page of that entry (1-based).
    starts = [(max(page, 1), heading) for _, heading, page in toc if heading]
    if not starts or starts[0][0] > 1:
        starts.insert(0, (1, title))

    sections: list[Section] = []
    for i, (first_page, heading) in enumerate(starts):
        last_page = starts[i + 1][0] - 1 if i + 1 < len(starts) else len(pages)
        if last_page < first_page:  # several TOC entries on one page: give it to the last one
            continue
        if _SKIP_SECTIONS.match(heading):
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
        if text and not _SKIP_SECTIONS.match(heading):
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
