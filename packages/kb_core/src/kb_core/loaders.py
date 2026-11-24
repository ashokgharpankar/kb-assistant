"""Turn files on disk into `SourceDocument`s.

PDFs: text per page with PyMuPDF, split into sections using the PDF's own
table of contents (bookmarks). Each heading is located in the text, so a section
starts exactly where its heading does, even when several headings share a page.
Each section is titled with its full heading path ("Security > Design principles")
and remembers which page every character came from, for exact page citations.

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

# Default TOC depth used for sections. Deeper headings stay inside their parent.
# Phase 1 used 2 (pillar level); Phase 4 found the "Design principles" headings
# one or two levels further down. Configurable: KB_TOC_DEPTH.
DEFAULT_TOC_DEPTH = 4
PATH_SEPARATOR = " > "

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


def _heading_pattern(title: str) -> re.Pattern[str]:
    """The heading at the start of a line, tolerant of any whitespace inside it."""
    words = [re.escape(w) for w in title.split()]
    return re.compile(r"(?m)^[ \t]*" + r"\s+".join(words) + r"[ \t]*$", re.IGNORECASE)


def build_sections(
    pages: list[str],
    toc: list[tuple[int, str, int]],
    document_title: str,
    toc_depth: int = DEFAULT_TOC_DEPTH,
) -> list[Section]:
    """Split cleaned page texts into sections at the TOC headings.

    `toc` is PyMuPDF's [(level, title, page), ...]. Each heading is searched for on its
    page (and the next, in case it flows over); if it can't be found, the section starts
    at the top of that page. Titles are heading paths: "Security > Design principles".
    """
    page_offsets: list[tuple[int, int]] = []  # (offset in full text, page number)
    position = 0
    for number, text in enumerate(pages, start=1):
        page_offsets.append((position, number))
        position += len(text) + 2  # the "\n\n" join below
    full = "\n\n".join(pages)
    starts = {number: offset for offset, number in page_offsets}

    entries: list[tuple[int, int, str]] = []  # (offset, level, title)
    for level, raw_title, page in toc:
        title = normalize(raw_title).strip()
        if level > toc_depth or not title:
            continue
        page = min(max(page, 1), len(pages))
        lo = starts[page]
        hi = starts.get(page + 2, len(full))
        found = _heading_pattern(title).search(full, lo, hi)
        entries.append((found.start() if found else lo, level, title))
    entries.sort(key=lambda e: e[0])  # stable: keeps TOC order for equal offsets
    if not entries or entries[0][0] > 0:
        entries.insert(0, (0, 0, document_title))

    def page_of(offset: int) -> int:
        page = 1
        for start, number in page_offsets:
            if start > offset:
                break
            page = number
        return page

    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    for i, (offset, level, title) in enumerate(entries):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        end = entries[i + 1][0] if i + 1 < len(entries) else len(full)
        text = full[offset:end]
        if not text.strip() or any(_SKIP_SECTIONS.match(t) for _, t in stack):
            continue
        path = PATH_SEPARATOR.join(t for lvl, t in stack if lvl > 0) or document_title
        page_starts = [(0, page_of(offset))] + [
            (start - offset, number) for start, number in page_offsets if offset < start < end
        ]
        sections.append(Section(path, text, tuple(page_starts)))
    return sections


def load_pdf(path: Path, toc_depth: int = DEFAULT_TOC_DEPTH) -> SourceDocument:
    with pymupdf.open(path) as pdf:  # type: ignore[no-untyped-call]
        raw_pages = [page.get_text("text", flags=_PDF_TEXT_FLAGS) for page in pdf]
        toc = [(level, title, page) for level, title, page in pdf.get_toc()]
        title = normalize((pdf.metadata or {}).get("title") or path.stem)

    headers_footers = repeated_edge_lines(raw_pages)
    pages = [clean_text(page, headers_footers) for page in raw_pages]
    sections = build_sections(pages, toc, title, toc_depth)
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


def load_file(path: Path, toc_depth: int = DEFAULT_TOC_DEPTH) -> SourceDocument:
    if path.suffix.lower() == ".pdf":
        return load_pdf(path, toc_depth)
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
