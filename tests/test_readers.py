"""Reading every kind of file (concierge/agents/files.py): text of any sort, spreadsheets,
slides and OpenDocument files by the words in their XML, zips by the names inside, markup
without its tags, and what a program or a picture gives (nothing)."""

import tarfile
import zipfile

from concierge.agents.files import archive_listing, office_text, read_pages, text_of, without_tags


def test_any_text_file_reads_as_text(tmp_path):
    settings = tmp_path / "notes.cfg"
    settings.write_text("[course]\nname = PHYS 122\n", encoding="utf-8")
    assert "PHYS 122" in text_of(settings)
    assert read_pages(settings)[0][1].startswith("[course]")
    with_bom = tmp_path / "u.unknown"
    with_bom.write_bytes("﻿hello PHYS".encode("utf-8"))
    assert text_of(with_bom) == "hello PHYS"
    wide = tmp_path / "w.dat"
    wide.write_bytes("hi there".encode("utf-16"))
    assert text_of(wide) == "hi there"


def test_a_program_or_a_picture_gives_nothing(tmp_path):
    program = tmp_path / "setup.exe"
    program.write_bytes(bytes(range(256)) * 20)
    assert text_of(program) == "" and read_pages(program) == [(None, "")]
    picture = tmp_path / "a.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4)
    assert text_of(picture) == ""
    assert text_of(tmp_path / "missing.bin") == ""
    (tmp_path / "empty.log").write_bytes(b"")
    assert text_of(tmp_path / "empty.log") == ""


def test_spreadsheets_slides_and_opendocument_files_give_their_words(tmp_path):
    sheet = tmp_path / "hw3.xlsx"
    with zipfile.ZipFile(sheet, "w") as inside:
        inside.writestr("[Content_Types].xml", "<Types/>")
        inside.writestr("xl/sharedStrings.xml", "<sst><si><t>CSE 163 HW3: library checkouts</t></si><si><t>Branch</t></si></sst>")
        inside.writestr("xl/worksheets/sheet1.xml", '<worksheet><sheetData><row><c t="s"><v>0</v></c></row></sheetData></worksheet>')
    words = read_pages(sheet)[0][1]
    assert "CSE 163 HW3: library checkouts" in words and "Branch" in words
    slides = tmp_path / "slides.pptx"
    with zipfile.ZipFile(slides, "w") as inside:
        inside.writestr("ppt/slides/slide1.xml", "<p:sld><a:t>PHYS 122 Lecture 9</a:t><a:t>Magnetism &amp; induction</a:t></p:sld>")
        inside.writestr("ppt/slides/_rels/slide1.xml.rels", "<Relationships/>")
    assert "PHYS 122 Lecture 9 Magnetism & induction" in read_pages(slides)[0][1]
    essay = tmp_path / "essay.odt"
    with zipfile.ZipFile(essay, "w") as inside:
        inside.writestr("content.xml", "<office:document-content><text:p>An essay for HIST 101</text:p></office:document-content>")
    assert "An essay for HIST 101" in read_pages(essay)[0][1]
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a zip")
    assert office_text(broken, ("xl/",)) == "" and read_pages(broken) == [(None, "")]


def test_archives_read_as_the_names_inside(tmp_path):
    packed = tmp_path / "lab3.zip"
    with zipfile.ZipFile(packed, "w") as inside:
        inside.writestr("lab3/", "")
        inside.writestr("lab3/report.pdf", "x")
        inside.writestr("lab3/data.csv", "y")
    assert read_pages(packed)[0][1] == "Files inside: lab3/report.pdf, lab3/data.csv"
    tarred = tmp_path / "hw.tar"
    with tarfile.open(tarred, "w") as tar:
        tar.add(packed, arcname="lab3.zip")
    assert archive_listing(tarred) == "Files inside: lab3.zip"
    assert archive_listing(tmp_path / "none.zip") == ""
    (tmp_path / "odd.zip").write_bytes(b"zip? no")
    assert archive_listing(tmp_path / "odd.zip") == ""


def test_markup_reads_without_its_tags(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<html><head><style>p{}</style><script>x=1</script></head><body><h1>PHYS 122</h1>"
                    "<p>Lab &amp; notes</p></body></html>", encoding="utf-8")
    assert read_pages(page)[0][1] == "PHYS 122 Lab & notes"
    assert without_tags("<a>b</a>") == "b"
