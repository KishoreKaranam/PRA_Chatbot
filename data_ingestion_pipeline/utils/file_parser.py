# Helper functions to parse each supported file type into plain text.
# Kept simple: each function returns a text string, used by tools in script3.

import csv
import openpyxl
import pdfplumber
from docx import Document
from striprtf.striprtf import rtf_to_text


def parse_txt(path):
    """Read a plain text file."""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def parse_csv(path):
    """Read a CSV file and join rows into plain text lines."""
    lines = []
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            lines.append(", ".join(row))
    return "\n".join(lines)


def parse_xlsx(path):
    """Read all sheets of an Excel file (xls/xlsx) into plain text lines."""
    workbook = openpyxl.load_workbook(path, data_only=True)
    lines = []
    for sheet in workbook.worksheets:
        lines.append(f"# Sheet: {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            values = [str(cell) if cell is not None else "" for cell in row]
            lines.append(", ".join(values))
    return "\n".join(lines)


def parse_docx(path):
    """Read a Word document (docx) into plain text paragraphs."""
    document = Document(path)
    paragraphs = [p.text for p in document.paragraphs]
    return "\n".join(paragraphs)


def parse_rtf(path):
    """Read an RTF document and strip formatting to plain text."""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        raw = f.read()
    return rtf_to_text(raw)


def parse_pdf(path):
    """Read a PDF file and extract text page by page."""
    lines = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                lines.append(text)
    return "\n".join(lines)


# Maps file extension to the function that can parse it.
# "xls" and "doc" are legacy binary formats without a pure-python reader here,
# so they are intentionally left out and should be converted upstream if needed.
PARSERS = {
    "txt": parse_txt,
    "csv": parse_csv,
    "xlsx": parse_xlsx,
    "docx": parse_docx,
    "rtf": parse_rtf,
    "pdf": parse_pdf,
}


def parse_file(path, extension):
    """Dispatch to the correct parser based on file extension."""
    extension = extension.lower().lstrip(".")
    parser = PARSERS.get(extension)
    if parser is None:
        raise ValueError(f"No parser available for extension: {extension}")
    return parser(path)
