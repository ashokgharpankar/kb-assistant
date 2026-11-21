from pathlib import Path

import pymupdf

from kb_core.loaders import clean_text, discover, document_id_for, load_file


def test_document_id_is_stable_slug() -> None:
    assert (
        document_id_for(Path("AWS Well-Architected_Framework.pdf"))
        == "aws-well-architected-framework"
    )


def test_clean_text_drops_page_number_lines_and_extra_space() -> None:
    assert clean_text("Hello   world\n\n\n\n12\nPage 3\nEnd") == "Hello world\n\nEnd"


def test_pdf_sections_follow_the_table_of_contents(sample_pdf: Path) -> None:
    doc = load_file(sample_pdf)
    assert doc.document_id == "sample-framework"
    assert doc.title == "Sample Framework"
    assert [s.title for s in doc.sections] == [
        "Introduction",
        "Reliability pillar",
        "Cost optimization pillar",
    ]
    reliability = doc.sections[1]
    assert "Availability Zones" in reliability.text
    assert reliability.page_at(0) == 2


def test_pdf_footer_page_numbers_are_removed(sample_pdf: Path) -> None:
    doc = load_file(sample_pdf)
    assert all(not line.strip().isdigit() for s in doc.sections for line in s.text.splitlines())


def test_markdown_splits_on_headings(tmp_path: Path) -> None:
    md = tmp_path / "runbook.md"
    md.write_text("# Restore runbook\n\nIntro text here.\n\n## Step one\n\nStop the service.\n")
    doc = load_file(md)
    assert doc.title == "Restore runbook"
    assert [s.title for s in doc.sections] == ["Restore runbook", "Step one"]


def test_discover_finds_supported_files_only(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# A")
    (tmp_path / "b.pdf").write_bytes(b"")
    (tmp_path / "c.png").write_bytes(b"")
    assert [p.name for p in discover(tmp_path)] == ["a.md", "b.pdf"]


# --- cleaning (docs/investigations/0001-retrieval-quality.md) -----------------

from kb_core.loaders import normalize, repeated_edge_lines  # noqa: E402


def test_ligatures_and_compatibility_characters_are_normalized() -> None:
    assert normalize("Conﬁgure shuﬄe-sharding eﬀort") == "Configure shuffle-sharding effort"
    assert normalize("non breaking") == "non breaking"


def test_dot_leader_table_of_contents_lines_are_dropped() -> None:
    text = "Implementation guidance ........................ 25\nReal guidance text here."
    assert clean_text(text) == "Real guidance text here."


def test_running_headers_are_found_only_at_page_edges() -> None:
    pages = [
        f"AWS Well-Architected Framework\nFramework\nBody text {i}.\nImplementation guidance\nMore body.\nmore {i}\nand more {i}\nend {i}"
        for i in range(10)
    ]
    found = repeated_edge_lines(pages)
    assert {"AWS Well-Architected Framework", "Framework"} <= found
    # common in the body, but never at a page edge: kept
    assert "Implementation guidance" not in found


def test_too_few_pages_means_no_header_detection() -> None:
    assert repeated_edge_lines(["Title\nA", "Title\nB"]) == frozenset()


def test_pdf_headers_and_toc_sections_are_removed(tmp_path: Path) -> None:
    path = tmp_path / "with-headers.pdf"
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    bodies = [
        "Overview ........................ 3\nReliability pillar ........................ 4",
        "Reliability means a workload performs its intended function correctly and consistently.",
        "Deploy across multiple Availability Zones and automate recovery from failure.",
        "Cost optimization means delivering business value at the lowest price point.",
    ]
    for body in bodies:
        page = doc.new_page()
        page.insert_text((50, 40), "Example Guide Running Header", fontsize=9)
        page.insert_textbox(pymupdf.Rect(50, 80, 550, 700), body, fontsize=11)  # type: ignore[no-untyped-call]
    doc.set_toc([[1, "Table of Contents", 1], [1, "Reliability", 2], [1, "Cost", 4]])
    doc.save(path)  # type: ignore[no-untyped-call]
    doc.close()  # type: ignore[no-untyped-call]

    loaded = load_file(path)
    assert [s.title for s in loaded.sections] == ["Reliability", "Cost"]
    text = loaded.full_text
    assert "Running Header" not in text
    assert "......" not in text
    assert "Availability Zones" in text


def test_markdown_document_revisions_section_is_skipped(tmp_path: Path) -> None:
    md = tmp_path / "guide.md"
    md.write_text("# Guide\n\nUseful text.\n\n## Document revisions\n\n2024: first version.\n")
    assert [s.title for s in load_file(md).sections] == ["Guide"]
