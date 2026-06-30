import logging
from pathlib import Path
from typing import Any

from ingestion import parse_unstructured_text

logger = logging.getLogger(__name__)


# ── Text extraction ───────────────────────────────────────────────

def extract_text_from_file(filepath: str) -> str:
    """Extract raw text from a PDF or DOCX file.

    Supported extensions: .pdf, .docx
    Returns an empty string for unsupported or unreadable files.
    """
    path = Path(filepath)
    suffix = path.suffix.lower()

    try:
        if suffix == ".pdf":
            return _extract_pdf_text(path)
        elif suffix == ".docx":
            return _extract_docx_text(path)
        else:
            logger.warning("Unsupported extension '%s' — %s", suffix, path.name)
            return ""
    except Exception as exc:
        logger.warning("Failed to read %s — %s", path.name, exc)
        return ""


def _extract_pdf_text(path: Path) -> str:
    import pdfplumber

    try:
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() for page in pdf.pages if page.extract_text()]
        if not pages:
            logger.warning("PDF appears to contain no extractable text (maybe a scanned image) — %s", path.name)
            return ""
        return "\n".join(pages)
    except Exception as exc:
        raise RuntimeError(f"PDF extraction failed: {exc}") from exc


def _extract_docx_text(path: Path) -> str:
    import docx

    try:
        doc = docx.Document(path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        if not paragraphs:
            logger.warning("DOCX appears to contain no text — %s", path.name)
            return ""
        return "\n".join(paragraphs)
    except Exception as exc:
        raise RuntimeError(f"DOCX extraction failed: {exc}") from exc


# ── Resume parsing wrapper ────────────────────────────────────────

def parse_resume_file(filepath: str) -> dict:
    """Extract text from a resume file and parse it into a CanonicalProfile-compatible dict.

    The provenance source will be ``resume_pdf`` or ``resume_docx``
    depending on the file extension.
    """
    path = Path(filepath)
    suffix = path.suffix.lower()

    if suffix not in (".pdf", ".docx"):
        logger.warning("Unsupported resume extension '%s' — %s", suffix, path.name)
        return {}

    raw_text = extract_text_from_file(filepath)
    if not raw_text:
        return {}

    source = "resume_pdf" if suffix == ".pdf" else "resume_docx"
    return parse_unstructured_text(raw_text, source, path.stem)
