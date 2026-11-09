"""The file organizer end to end with the real Noir model, on a made-up home.

A Downloads folder of course files, a tuition statement, a CV, an I-20 form, a
registration confirmation, notes for a course that has no folder, a README and data
files; the user's own words to set it up; "Only new files from now on"; new files
landing; then the questions people asked in the live runs. Every check must pass.
Everything lives in a temporary folder, and the app's data goes to a temporary
LOCALAPPDATA, so nothing of the user's is read or moved. Ollama must be running.

    python -m concierge.organizer_eval [--keep]
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from concierge import organizer as org
from concierge.agents import builder as builder_mod
from concierge.agents import store
from concierge.agents.builder import CREATE_IT
from concierge.engine import ONLY_NEW, NoirEngine
from concierge.events import (AgentCard, AgentList, ChatList, Error, NoirDone, NoirText, Progress, Question, Result,
                              Thinking, Transcript)

REQUEST = ("organize my school files from Downloads into a folder on my desktop called College, divided into "
           "phys122 and cse163, by what's inside them")

# What is in Downloads when the organizer is made: course material and the things that
# landed beside it in the real runs, which must stay.
OLD = {
    "Lab A3 - Handout.pdf": ["PHYS 122 Lab A3: DC Circuits", "University of Washington, Autumn 2026",
                             "Goals: measure the current through resistors in series and in parallel, check Ohm's law V = IR,",
                             "and find the internal resistance of a battery.",
                             "Equipment: breadboard, two 100 ohm resistors, a 9 V battery, a multimeter.",
                             "Procedure: 1. Build the series circuit. 2. Record V and I for each resistor. 3. Plot V against I.",
                             "Questions: Does the sum of the voltages equal the battery voltage? Explain any difference."],
    "hw5.pdf": ["CSE 163 Homework 5: Data Analysis with pandas", "Due Friday 11:59 pm on Gradescope",
                "In this assignment you will load the Seattle library checkout data into a DataFrame,",
                "group the rows by month, compute the mean checkouts per branch and plot the result with seaborn.",
                "Part 1 (20 points): write load_data(path) that returns a DataFrame.",
                "Part 2 (30 points): write busiest_branch(df) that returns the branch with the most checkouts."],
    "UWTuitionStatement.pdf": ["University of Washington - Student Fiscal Services", "Tuition Statement, Autumn Quarter 2026",
                               "Student: Do Hyun Park    Student number: 2234567",
                               "Registered courses: PHYS 122 A (5 cr), CSE 163 B (4 cr)",
                               "Resident tuition: $4,335.00", "Services and activities fee: $146.00", "Technology fee: $38.00",
                               "Total due: $4,519.00   Due date: 15 October 2026", "Pay online through MyUW or at Schmitz Hall."],
    "Resume_2026.pdf": ["Do Hyun Park", "Seattle, WA  -  dhpark@example.com",
                        "Education: University of Washington, B.S. in progress, expected 2029",
                        "Relevant coursework: PHYS 122, CSE 163, MATH 124",
                        "Experience: Physics 122 lab teaching assistant (2026), tutoring algebra",
                        "Skills: Python, pandas, Git, Korean (native), English (fluent)"],
    "I-20.pdf": ["Certificate of Eligibility for Nonimmigrant Student Status",
                 "Form I-20, U.S. Immigration and Customs Enforcement", "SEVIS ID: N0012345678",
                 "School: University of Washington, Seattle", "Program of study: Physics, Bachelor's",
                 "Program start date: 25 September 2026   Expected end date: 15 June 2030",
                 "Financial support: personal funds $35,000"],
    "Course_registration_confirmation.pdf": ["MyUW Registration Confirmation", "Autumn 2026 schedule for Do Hyun Park",
                                             "PHYS 122 A  General Physics: Electromagnetism  MWF 9:30  Kane 130",
                                             "CSE 163 B  Intermediate Data Programming  TTh 11:30  Gates G20",
                                             "MATH 124 C  Calculus with Analytic Geometry  MWF 12:30",
                                             "Your schedule is confirmed. Add/drop period ends 7 October."],
    "MATH124_week3_notes.pdf": ["MATH 124 Week 3: Derivatives",
                                "The derivative of f at a is the limit of (f(a+h) - f(a)) / h as h goes to 0.",
                                "Rules: power rule, product rule, quotient rule, chain rule.",
                                "Examples: d/dx x^3 = 3x^2; d/dx sin(x) = cos(x); d/dx e^x = e^x."],
    "Week 3 slides.docx": ["PHYS 122 Lecture 7: Electric potential", "Potential energy of a charge in a field: U = qV.",
                           "The potential of a point charge: V = kq / r.",
                           "Equipotential surfaces are perpendicular to field lines.",
                           "Example: the work to move a 2 microcoulomb charge through 12 V."],
    "README.md": ["# bike-trips", "A small Python project that reads Seattle bike trip data and draws the busiest stations.",
                  "## Setup", "```", "pip install -r requirements.txt", "python main.py data/trips.csv", "```",
                  "## License", "MIT"],
    "data.csv": ["station,trips", "Pike St,120", "Fremont,340"],
    "settings.json": ['{"theme": "dark", "font": 14}'],
    "installer_setup.exe": None,  # a program: nothing to read, the name says nothing
    "party.zip": ["IMG_2031.jpg", "IMG_2032.jpg", "IMG_2040.jpg"],  # a zip of photos
    "backup_photos.py": ["# Copies new photos from the camera card to the NAS, once a night.",
                         "import shutil", "from pathlib import Path", "",
                         "CARD, NAS = Path('E:/DCIM'), Path('//nas/photos')", "",
                         "for picture in CARD.glob('*.jpg'):", "    shutil.copy2(picture, NAS / picture.name)"],
    "geopandas_practice.ipynb": {"cells": [
        {"cell_type": "markdown", "source": ["# CSE 163 practice: GeoPandas\n", "Plot the bike stations of Seattle."]},
        {"cell_type": "code", "source": ["import geopandas as gpd\n", "stations = gpd.read_file('stations.shp')\n",
                                         "stations.plot()"]}], "metadata": {}, "nbformat": 4, "nbformat_minor": 5},
}
# What lands after it is switched on.
NEW = {
    "Lab A4 - Handout.pdf": ["PHYS 122 Lab A4: Magnetic fields",
                             "Goals: map the field of a bar magnet with a compass and measure the field",
                             "of a coil with a Hall probe as the current changes.",
                             "Procedure: 1. Place the compass at 2 cm steps. 2. Record the needle's direction.",
                             "Questions: How does the field of the coil depend on the current? Compare with B = mu0 n I."],
    "bookstore_receipt.pdf": ["University Book Store - Receipt", "Order 88213, 2 October 2026",
                              "1 x University Physics Vol. 2 (PHYS 122 required text)  $89.00",
                              "1 x Lab notebook, quad ruled  $6.50",
                              "Subtotal $95.50   Tax $9.79   Total $105.29", "Paid by Visa ending 4421"],
    "hw3_data.xlsx": ["Data for CSE 163 Homework 3: Seattle library checkouts by branch, 2025", "Branch", "Checkouts",
                      "Central", "12034", "Ballard", "8120", "Use this sheet with load_data() in hw3.py"],
    "Lecture 9 slides.pptx": ["PHYS 122 Lecture 9: Magnetism", "Field of a long wire: B = mu0 I / 2 pi r",
                              "Faraday's law: a changing flux makes an emf"],
    "lab notes photo.png": ["PHYS 122 Lab A5: Optics", "Bench notes: lens f = 15 cm,", "object at 30 cm, image at 30 cm"],
    "math207_hw2.pdf": ["MATH 207 Homework 2: Linear Algebra", "Due Monday. Show all work.",
                        "1. Find the eigenvalues of the matrix [[2, 1], [1, 2]].",
                        "2. Show that the vectors (1, 0, 1) and (0, 1, 1) are linearly independent."],
    "phys121_ch3_notes.pdf": ["PHYS 121 Chapter 3: Kinematics in one dimension", "Physics notes from last quarter",
                              "Position, velocity and acceleration; v = v0 + a t; x = x0 + v0 t + a t^2 / 2."],
    "scan_chem142_lab3.pdf": ["CHEM 142 Lab 3: Titration of acetic acid", "Name: Student   Section AB",
                              "Results: 24.8 mL of 0.100 M NaOH", "Molarity of the vinegar: 0.83 M"],
    "hist111_essay_draft.docx": ["HIST 111: The French Revolution, essay draft",
                                 "The fall of the Bastille in 1789 marked the start of a decade of upheaval."],
    "practice5.py": ["# Name: Student", "# CSE 163", "# Autumn 2026", "# Programming Practice 5", "",
                     "# The Commit and Repository classes are provided for you in repository.py. You will define a",
                     "# RemoteRepository that extends Repository, then build a collaboration network with graphs.",
                     "import networkx as nx", "from repository import Repository", "", "",
                     "class RemoteRepository(Repository):", "    def __init__(self, name):", "        super().__init__(name)"],
    "a2_spec.pdf": ["CSE 163 Assessment 2: Data Structures and Algorithms",
                    "In this assessment you implement a document search engine.",
                    "Part 0: write Document, a class that computes term frequency for a text file.",
                    "Part 1: write SearchEngine, which indexes a directory of documents and ranks them by TF-IDF.",
                    "Submit document.py and search_engine.py on Ed by Thursday."],
}
STAYS = ("UWTuitionStatement.pdf", "Resume_2026.pdf", "I-20.pdf", "Course_registration_confirmation.pdf",
         "MATH124_week3_notes.pdf", "README.md", "data.csv", "settings.json", "bookstore_receipt.pdf", "backup_photos.py",
         "installer_setup.exe", "party.zip")
# Which folder each held-back kind belongs in, for the questions.
KINDS = {".xlsx": "CSE163", ".pptx": "PHYS122", ".png": "PHYS122"}
# The courses none of the folders is, asked about once each: what the user answers.
COURSES = {"MATH 207": "math207", "PHYS 121": "no", "HIST 111": "yes"}
SCANNED = "CHEM 142"  # on a scanned page, read through the vision model
SECOND = "when a pdf lands in my downloads, write me a short summary in a notes file"


def pdf(path: Path, lines: list[str]) -> None:
    """A one-page PDF with these lines, the kind pypdf reads back as text."""
    content = ["BT", "/F1 11 Tf", "50 750 Td", "14 TL"]
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content.append(f"({safe}) Tj T*")
    content.append("ET")
    stream = "\n".join(content).encode("cp1252", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    write_pdf(path, objects)


def scan(path: Path, lines: list[str]) -> None:
    """A scanned page: one big photo of the lines, with no text behind it, the kind a
    phone or a copier makes (output.pdf was six of these)."""
    import io

    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (2550, 3300), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 96)
    except OSError:
        font = ImageFont.load_default()
    for number, line in enumerate(lines):
        draw.text((160, 240 + number * 180), line, fill="black", font=font)
    photo = io.BytesIO()
    image.save(photo, "JPEG", quality=80)
    jpeg = photo.getvalue()
    content = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /XObject << /Im1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        (b"<< /Type /XObject /Subtype /Image /Width 2550 /Height 3300 /ColorSpace /DeviceRGB /BitsPerComponent 8 "
         b"/Filter /DCTDecode /Length " + str(len(jpeg)).encode() + b" >>\nstream\n" + jpeg + b"\nendstream"),
    ]
    write_pdf(path, objects)


def write_pdf(path: Path, objects: list[bytes]) -> None:
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def sheet(path: Path, lines: list[str]) -> None:
    """A spreadsheet with these words, the way Excel saves one: a zip of XML."""
    import zipfile

    with zipfile.ZipFile(path, "w") as inside:
        inside.writestr("[Content_Types].xml", "<Types/>")
        inside.writestr("xl/sharedStrings.xml", "<sst>" + "".join(f"<si><t>{line}</t></si>" for line in lines) + "</sst>")
        inside.writestr("xl/worksheets/sheet1.xml", "<worksheet><sheetData/></worksheet>")


def slides(path: Path, lines: list[str]) -> None:
    import zipfile

    with zipfile.ZipFile(path, "w") as inside:
        inside.writestr("[Content_Types].xml", "<Types/>")
        inside.writestr("ppt/slides/slide1.xml", "<p:sld>" + "".join(f"<a:t>{line}</a:t>" for line in lines) + "</p:sld>")


def picture(path: Path, lines: list[str]) -> None:
    """A photo of notes: these lines drawn large on a white page."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (900, 420), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    for number, line in enumerate(lines):
        draw.text((40, 40 + number * 70), line, fill="black", font=font)
    image.save(path)


def packed(path: Path, names: list[str]) -> None:
    import zipfile

    with zipfile.ZipFile(path, "w") as inside:
        for name in names:
            inside.writestr(name, b"x")


def word(path: Path, lines: list[str]) -> None:
    import docx

    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    document.save(str(path))


def drop(downloads: Path, files: dict) -> None:
    for name, lines in files.items():
        path = downloads / name
        if name.startswith("scan_") and name.endswith(".pdf"):
            scan(path, lines)
        elif name.endswith(".pdf"):
            pdf(path, lines)
        elif name.endswith(".docx"):
            word(path, lines)
        elif name.endswith(".ipynb"):
            path.write_text(json.dumps(lines), encoding="utf-8")
        elif name.endswith(".xlsx"):
            sheet(path, lines)
        elif name.endswith(".pptx"):
            slides(path, lines)
        elif name.endswith(".png"):
            picture(path, lines)
        elif name.endswith(".zip"):
            packed(path, lines)
        elif name.endswith(".exe"):
            path.write_bytes(bytes(range(256)) * 64)
        else:
            path.write_text("\n".join(lines), encoding="utf-8")


class Run:
    def __init__(self, root: Path):
        self.home = root / "home"
        self.downloads = self.home / "Downloads"
        self.desktop = self.home / "OneDrive" / "바탕 화면"  # a Korean Windows with OneDrive backup, like the user's
        self.college = self.desktop / "College"
        self.appdata = root / "appdata"
        for folder in (self.downloads, self.desktop, self.appdata):
            folder.mkdir(parents=True)
        self.checks: list[bool] = []

    def place(self, name: str, home: Path | None = None) -> Path:
        return {"Desktop": self.desktop, "Downloads": self.downloads}.get(name, self.home / name)

    def show(self, events, label: str = "") -> list:
        """Print the events the way the window would show them, and keep them."""
        if label:
            print(f"\n>>> {label}")
        kept, text = [], []
        for event in events:
            kept.append(event)
            if isinstance(event, NoirText):
                text.append(event.text)
                continue
            if text:
                print("  NOIR:", self.short("".join(text).strip()))
                text = []
            if isinstance(event, Thinking):
                print("  [think]", event.text.strip().replace("\n", " ")[:200])
            elif isinstance(event, Question):
                print(f"  QUESTION ({event.id}): {event.text}  {event.choices or ''}")
            elif isinstance(event, AgentCard):
                print(f"  CARD {event.name}: reads {event.reads}; can {event.can_do}")
            elif isinstance(event, Result):
                print(f"  RESULT ({event.agent}): {self.short(event.text)}")
            elif isinstance(event, Error):
                print("  ERROR:", event.text)
            elif not isinstance(event, (Progress, NoirDone, AgentList, ChatList, Transcript)):
                print("  ", event)
        if text:
            print("  NOIR:", self.short("".join(text).strip()))
        return kept

    def short(self, text: str) -> str:
        return text.replace(str(self.home), "~").replace("\n", " ")

    @staticmethod
    def said(events) -> str:
        return " ".join(e.text for e in events if isinstance(e, (NoirText, Result)))

    def tree(self) -> None:
        print("  Downloads:", sorted(p.name for p in self.downloads.iterdir()))
        if self.college.is_dir():
            for sub in sorted(self.college.iterdir()):
                print(f"  College/{sub.name}:", sorted(p.name for p in sub.iterdir()))

    def check(self, condition: bool, what: str) -> None:
        print(("  OK   " if condition else "  FAIL ") + what)
        self.checks.append(bool(condition))

    def go(self) -> bool:
        os.environ["LOCALAPPDATA"] = str(self.appdata)
        # The made-up home stands in for the user's: where Desktop and Downloads are, and
        # that a folder under the temp dir counts as a place it may read.
        builder_mod.known_folder = self.place
        org.known_folder = self.place
        builder_mod.watched_from = lambda text: org.watched_from(text, place=self.place)
        builder_mod.destination_from = lambda text: org.destination_from(text, self.home, place=self.place)
        builder_mod.is_blocked = lambda folder: False
        drop(self.downloads, OLD)

        engine = NoirEngine()
        self.show(engine.startup(), "startup")
        engine.organizer._settle_seconds = 1  # a download settles in seconds here, not 20

        events = self.show(engine.send(REQUEST), REQUEST)
        self.check(any(isinstance(e, AgentCard) for e in events), "the request ends in an agent card, nothing asked first")
        slots = engine.builder.draft.slots if engine.builder and engine.builder.draft else {}
        self.check(slots.get("folder") == str(self.downloads), "it watches Downloads, not the destination")
        self.check(slots.get("into") == str(self.college), "the folders go in College on the real desktop")
        self.check(slots.get("groups", "").replace(" ", "") == "PHYS122,CSE163", "the folders are PHYS122 and CSE163")
        self.check(slots.get("by") == org.CONTENT, "it reads what's inside")

        events = self.show(engine.choose("card", CREATE_IT), "click Create it")
        question = next((e for e in events if isinstance(e, Question)), None)
        self.check(question is not None and question.id == "organize_now", "it asks about the files already there")
        self.check(len(list(self.downloads.iterdir())) == len(OLD), "nothing moved on Create it")

        self.show(engine.choose("organize_now", ONLY_NEW), "click Only new files from now on")
        time.sleep(2)
        engine.organizer.look()
        self.check(len(list(self.downloads.iterdir())) == len(OLD), "nothing moved after Only new files")

        drop(self.downloads, NEW)
        time.sleep(2)
        self.show(engine.send("I just downloaded a few files, organize them"), "organize the new files")
        self.tree()
        self.check((self.college / "PHYS122" / "Lab A4 - Handout.pdf").is_file(), "the new physics lab went to PHYS122")
        self.check((self.college / "CSE163" / "a2_spec.pdf").is_file(), "the new CSE assessment went to CSE163")
        self.check((self.college / "CSE163" / "practice5.py").is_file(), "the new CSE practice code went to CSE163")
        sees = bool(engine.organizer.seer())
        print("  vision model:", engine.organizer.seer() or "none installed, so pictures go by name")
        for name in ("hw3_data.xlsx", "Lecture 9 slides.pptx", "lab notes photo.png", "math207_hw2.pdf",
                     "phys121_ch3_notes.pdf", "hist111_essay_draft.docx"):
            self.check((self.downloads / name).is_file(), f"{name} is held back until you say")
        pending = {q["id"].split(":", 2)[-1]: q for q in engine.organizer_questions()}
        wanted = {".xlsx", ".pptx"} | ({".png"} if sees else set())
        self.check(wanted <= set(pending), f"it asks about each new kind once: {sorted(pending)}")
        for ext in wanted & set(pending):
            self.check(KINDS[ext] in pending[ext]["text"], f"the {ext} question names the right folder: {pending[ext]['text']}")
        self.check(set(COURSES) <= set(pending), f"it asks about each new course once, by its code: {sorted(pending)}")
        if sees:
            self.check(SCANNED in pending, f"a scanned page is read through the vision model and asked about: {sorted(pending)}")
            if SCANNED in pending:
                engine.organizer_answer(pending[SCANNED]["id"], True)
                self.check((self.college / "CHEM142" / "scan_chem142_lab3.pdf").is_file(), "yes put the scan in CHEM142")
        self.check(".pdf" not in pending and "PHYS122" not in pending, "PHYS 121 notes were not filed under PHYS122")
        for course, guess in (("MATH 207", "MATH207"), ("PHYS 121", "PHYS121"), ("HIST 111", "HIST111")):
            if course in pending:
                self.check(pending[course].get("guess") == guess and course in pending[course]["text"],
                           f"the {course} question offers {guess}: {pending[course]['text']}")
        answer = self.said(self.show(engine.send("math207"), "math207 (a folder name typed for the MATH 207 question)"))
        self.check("math207" in answer, "the typed name is taken as the folder for that course")
        self.tree()
        self.check((self.college / "math207" / "math207_hw2.pdf").is_file(), "the MATH 207 homework went to College/math207")
        self.check("math207" in store.find_agent("File organizer").slots.get("groups", ""), "the new folder joined the organizer's list")
        if "PHYS 121" in pending:
            engine.organizer_answer(pending["PHYS 121"]["id"], False)
        if "HIST 111" in pending:
            engine.organizer_answer(pending["HIST 111"]["id"], True)
        self.check((self.college / "HIST111" / "hist111_essay_draft.docx").is_file(), "yes with the offered name made HIST111")
        self.check((self.downloads / "phys121_ch3_notes.pdf").is_file(), "no left the old physics notes alone")
        if ".png" in pending:
            engine.organizer_answer(pending[".png"]["id"], False)  # the picture: no
        first = engine.organizer_questions()[0]["id"].rsplit(":", 1)[-1]
        self.said(self.show(engine.send("yes"), f"yes (to the question about {first} files)"))
        self.check(engine.organizer.kinds.get("File organizer", {}).get(first) == "yes",
                   "a plain yes in the chat answers the question")
        for question in engine.organizer_questions():
            engine.organizer_answer(question["id"], True)
        drop(self.downloads, {"math207_hw3.pdf": ["MATH 207 Homework 3: determinants and inverses"],
                              "phys121_ch4_notes.pdf": ["PHYS 121 Chapter 4: Newton's laws, notes from last quarter"]})
        time.sleep(2)
        engine.organizer.look()
        self.check((self.college / "math207" / "math207_hw3.pdf").is_file(), "the next MATH 207 file went straight to math207")
        self.check((self.downloads / "phys121_ch4_notes.pdf").is_file() and len(engine.organizer_questions()) == 0,
                   "the next PHYS 121 file stayed, with no new question")
        self.tree()
        self.check((self.college / "CSE163" / "hw3_data.xlsx").is_file(), "after yes, the spreadsheet went to CSE163")
        self.check((self.college / "PHYS122" / "Lecture 9 slides.pptx").is_file(), "after yes, the slides went to PHYS122")
        self.check((self.downloads / "lab notes photo.png").is_file(), "after no, the picture stayed")
        drop(self.downloads, {"whiteboard2.png": ["PHYS 122 Lab A6", "Diffraction grating notes"]})
        time.sleep(2)
        self.show(engine.send("organize it"), "organize it (a second picture, after no)")
        self.check((self.downloads / "whiteboard2.png").is_file() and len(engine.organizer_questions()) == 0,
                   "a kind you said no to stays, with no question")
        answer = self.said(self.show(engine.send("why didn't you move the whiteboard?"), "why didn't you move the whiteboard?"))
        self.check("whiteboard2.png" in answer and "Downloads" in answer, "why: the picture's own reason")
        self.check((self.downloads / "bookstore_receipt.pdf").is_file(), "the receipt stayed")
        self.check((self.downloads / "UWTuitionStatement.pdf").is_file(), "the tuition statement was not touched")

        answer = self.said(self.show(engine.send("where did you put it"), "where did you put it"))
        self.check(any(f"{name} is in" in answer for name in ("a2_spec.pdf", "Lab A4 - Handout.pdf", "practice5.py",
                                                                "hw3_data.xlsx", "Lecture 9 slides.pptx")),
                   "where: the moved files, whole paths")
        answer = self.said(self.show(engine.send("what did you do"), "what did you do"))
        self.check("Lately:" in answer and "Nothing has been moved" not in answer, "status: counts the pass's moves")
        self.check(f"bookstore_receipt.pdf ({org.NOT_MATERIAL})" in answer, "status: what stayed and why")
        answer = self.said(self.show(engine.send("why didn't you move the receipt?"), "why didn't you move the receipt?"))
        self.check("bookstore_receipt.pdf stayed in" in answer and org.NOT_MATERIAL in answer, "why: the receipt's reason")
        answer = self.said(self.show(engine.send("which folder is the physics lab in now?"), "which folder is the physics lab in now?"))
        self.check("Lab A4 - Handout.pdf" in answer and "PHYS122" in answer, "where: a file named by a word of its name")
        events = self.show(engine.send("is the organizer still on? what does it watch"), "is the organizer still on? what does it watch")
        self.check(not any(isinstance(e, Question) for e in events), "a question about the chore gets an answer, not a question")
        events = self.show(engine.send("can you also sort pictures?"), "can you also sort pictures?")
        self.check(not any(isinstance(e, (Question, AgentCard)) for e in events) and not (engine.builder and engine.builder.active),
                   "a question about the chore starts no new agent and asks nothing")

        self.show(engine.send("go through everything in downloads"), "go through everything in downloads")
        self.tree()
        self.check((self.college / "PHYS122" / "Lab A3 - Handout.pdf").is_file(), "the old physics lab went to PHYS122")
        self.check((self.college / "PHYS122" / "Week 3 slides.docx").is_file(), "the physics slides went to PHYS122")
        self.check((self.college / "CSE163" / "hw5.pdf").is_file(), "the CSE homework went to CSE163")
        self.check((self.college / "CSE163" / "geopandas_practice.ipynb").is_file(), "the CSE notebook went to CSE163")
        for name in STAYS + ("lab notes photo.png", "whiteboard2.png", "phys121_ch3_notes.pdf", "phys121_ch4_notes.pdf"):
            self.check((self.downloads / name).is_file(), f"{name} stayed in Downloads")
        answer = self.said(self.show(engine.send("put installer_setup.exe in Tools"), "put installer_setup.exe in Tools"))
        self.check((self.college / "Tools" / "installer_setup.exe").is_file() and "installer_setup.exe" in answer,
                   "a file placed by the user is moved where they say")
        self.check(engine.organizer.kinds.get("File organizer", {}).get(".exe") == "yes", "and its kind is learned")
        answer = self.said(self.show(engine.send("organize it"), "organize it (nothing new)"))
        self.check("Nothing new has landed" in answer and "Looked at already" in answer,
                   "nothing new: it says what was looked at and why, not just wait")

        answer = self.said(self.show(engine.send("why is my tuition statement still in downloads?"),
                                     "why is my tuition statement still in downloads?"))
        self.check("UWTuitionStatement.pdf stayed in" in answer, "why: the tuition statement's reason")
        answer = self.said(self.show(engine.send("where is the tuition pdf"), "where is the tuition pdf"))
        self.check("UWTuitionStatement.pdf is still in" in answer, "where: a file that stayed is said to have stayed")
        answer = self.said(self.show(engine.send("what did you do"), "what did you do (after the pass)"))
        self.check(org.NOT_MATERIAL in answer and "went to" in answer, "status after the pass")

        # A second kind of agent, made only through the conversation: the summary writer.
        events = self.show(engine.send(SECOND), SECOND)
        question = next((e for e in events if isinstance(e, Question)), None)
        self.check(question is not None and question.id == "notes", "the summary writer is offered and asks where the notes go")
        if question is not None and question.id == "notes":
            events = self.show(engine.choose("notes", "A Summaries.md file in that folder"), "click A Summaries.md file in that folder")
            card = next((e for e in events if isinstance(e, AgentCard)), None)
            self.check(card is not None and card.kind == "Summary writer" and "Summaries.md" in " ".join(card.can_do),
                       "its card says what it reads and where the summaries go")
            events = self.show(engine.choose("card", CREATE_IT), "click Create it")
            self.check(any(isinstance(e, Question) and e.id == "organize_now" for e in events),
                       "it is on and asks about the documents already there")
            self.show(engine.choose("organize_now", ONLY_NEW), "click Only new files from now on")
            drop(self.downloads, {"reading_week6.pdf": ["PHYS 122 Reading for week 6: Faraday's law",
                                                          "A changing magnetic flux through a loop induces an emf."]})
            time.sleep(2)
            engine.organizer.look()
            notes = self.downloads / "Summaries.md"
            self.check(notes.is_file() and "reading_week6.pdf" in notes.read_text(encoding="utf-8"),
                       "the new reading got a summary in Summaries.md")
            self.check((self.college / "PHYS122" / "reading_week6.pdf").is_file(), "and the organizer still filed it")
            answer = self.said(self.show(engine.send("what did you do"), "what did you do (two agents)"))
            self.check("Summary writer" in answer and "File organizer" in answer, "status covers both agents")
        engine.organizer.stop()
        engine.book.save()
        return all(self.checks)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(tempfile.mkdtemp(prefix="noir-organizer-eval-"))
    started = time.time()
    run = Run(root)
    try:
        passed = run.go()
    finally:
        if "--keep" in argv:
            print(f"\nkept: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    print(f"\n{sum(run.checks)} of {len(run.checks)} checks passed in {time.time() - started:.0f}s")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
