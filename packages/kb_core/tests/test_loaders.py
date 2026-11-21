from pathlib import Path

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
