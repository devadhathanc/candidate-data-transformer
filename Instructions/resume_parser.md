# resume_parser.py — Resume File Ingestion (PDF / DOCX)

## Purpose
Extends the pipeline to handle actual binary resume files by extracting their
raw text and reusing the existing unstructured parsing heuristics.

## Functions

### `extract_text_from_file(filepath: str) -> str`
| Extension | Library | Behaviour |
|---|---|---|
| `.pdf` | `pdfplumber` | Iterates pages, joins extracted text. Returns `""` if no text found (e.g., scanned image). |
| `.docx` | `python-docx` | Reads paragraph text. Returns `""` if empty. |
| any other | — | Logs a warning, returns `""`. |

Every path through this function is wrapped in a top-level `try/except` so corrupt,
password-protected, or missing files never crash the pipeline — they return `""`.

### `parse_resume_file(filepath: str) -> dict`
1. Calls `extract_text_from_file()` to get raw text.
2. Delegates to `_parse_unstructured_text()` (shared core from `ingestion.py`).
3. Overrides the provenance source:
   - `.pdf` → `"resume_pdf"`
   - `.docx` → `"resume_docx"`
4. Returns `{}` on any failure — the caller in `main.py` skips empty dicts.

## Refactoring Note
`ingestion._parse_unstructured_text(text, source, candidate_id)` was extracted
from `parse_unstructured_notes(filepath)` so both TXT notes and resume files
share the same email/phone/skill/experience regex logic without code duplication.

## main.py Routing Update
```python
from resume_parser import parse_resume_file

# Inside _route(), add:
elif path.suffix in (".pdf", ".docx"):
    return parse_resume_file(str(path))
```
