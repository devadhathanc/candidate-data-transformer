# ingestion.py — Unified Ingestion Entry Point (Step 1)

## Purpose
Provides both parsers under one module. `main.py` imports from here exclusively.

## Functions

### `parse_ats_json(filepath)`
Thin re-export from `parse_ats_json.py`. See `Instructions/parse_ats_json.md`.

### `parse_unstructured_notes(filepath)`
Reads free-form TXT notes and extracts candidate data via regex patterns.

| Pattern | What it extracts |
|---|---|
| `[\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,}` | Email (first match) |
| `\+?\d[\d\s.\-()]{7,}\d` | Phone number (first match) |
| `(\d+)\+?\s*years?` | `years_experience` |
| `(.+?)\s+at\s+(.+?)\(start-end\)` | Experience entries from lines matching `"Title at Company (YYYY-MM – YYYY-MM)"` |
| Keyword lookup (Python, AWS, etc.) | Skills detection in lowercased text |

## Design Decisions
- Confidence base for unstructured notes is `0.50` (lower authority than ATS).
- Deduction rules mirror ATS parser (missing name/email/phone → `-0.10`).
- Experience extraction uses a regex that expects `"Title at Company (start – end)"` format.
- `candidate_id` defaults to the filename stem (e.g., `notes_alice.txt` → `notes_alice`).
