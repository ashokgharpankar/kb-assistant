import pytest

from kb_core.chunking import chunk_document, content_fingerprint
from kb_core.models import Section, SourceDocument


def _doc(text: str, page_starts: tuple[tuple[int, int], ...] = ((0, 1),)) -> SourceDocument:
    return SourceDocument("doc", "Doc", "file:///doc", (Section("Intro", text, page_starts),))


LONG = " ".join(
    f"Sentence number {i} explains one idea about resilient systems." for i in range(120)
)


def test_chunks_respect_the_size_limit() -> None:
    chunks = chunk_document(_doc(LONG), chunk_size=400, chunk_overlap=80)
    assert len(chunks) > 5
    assert all(len(c.text) <= 400 for c in chunks)


def test_neighbouring_chunks_overlap() -> None:
    a, b = chunk_document(_doc(LONG), chunk_size=400, chunk_overlap=80)[:2]
    assert a.text[-40:].split()[-1] in b.text  # the end of one chunk reappears in the next


def test_chunk_ids_are_stable_and_ordered() -> None:
    chunks = chunk_document(_doc(LONG), chunk_size=400, chunk_overlap=80)
    assert [c.chunk_id for c in chunks[:2]] == ["doc:00000", "doc:00001"]
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_each_chunk_gets_the_page_it_starts_on() -> None:
    page1 = "Alpha paragraph. " * 30
    page2 = "Bravo paragraph. " * 30
    text = page1 + "\n\n" + page2
    doc = _doc(text, ((0, 4), (len(page1) + 2, 5)))
    chunks = chunk_document(doc, chunk_size=300, chunk_overlap=0)
    assert chunks[0].page == 4
    assert chunks[-1].page == 5
    assert all(c.page == 5 for c in chunks if c.text.startswith("Bravo"))


def test_tiny_fragments_are_dropped() -> None:
    assert chunk_document(_doc("Too short."), chunk_size=400, chunk_overlap=0) == []


def test_overlap_must_be_smaller_than_size() -> None:
    with pytest.raises(ValueError):
        chunk_document(_doc(LONG), chunk_size=200, chunk_overlap=200)


def test_fingerprint_changes_with_text_or_settings() -> None:
    base = content_fingerprint(_doc(LONG), 400, 80)
    assert base == content_fingerprint(_doc(LONG), 400, 80)
    assert base != content_fingerprint(_doc(LONG + " More."), 400, 80)
    assert base != content_fingerprint(_doc(LONG), 500, 80)
