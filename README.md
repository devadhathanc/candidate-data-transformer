# Multi-Source Candidate Data Transformer

A linear pipeline that ingests candidate data from multiple heterogeneous sources,
normalizes formats, resolves entity matches, merges conflicting fields, and projects
the result into a configurable output shape.

## Architecture

```
[Ingestion/Parsing] → [Normalization] → [Entity Resolution & Merging] → [Validation] → [Projection] → [Output]
```

### Source Types
| Source | Type | Authority | Parser |
|---|---|---|---|
| ATS JSON | Structured | 0.95 | `parse_ats_json.py` |
| Recruiter CSV | Structured | 0.85 | `csv_parser.py` |
| Resume PDF/DOCX | Unstructured | 0.50 | `resume_parser.py` |
| Free-text Notes | Unstructured | 0.50 | `ingestion.py` |

## Quick Start

### Install dependencies
```bash
pip install -r requirements.txt
```

### Run the pipeline
```bash
python main.py \
  --inputs samples/candidate_ats.json samples/resume_alice.pdf \
  --config samples/view_config.json
```

### Run tests
```bash
python -m pytest tests/test_pipeline.py -v
```

## Pipeline Stages

1. **Parse** — Route each input file to the appropriate parser based on extension
2. **Normalize** — Phones → E.164, skills → alias + dedup, dates → YYYY-MM, locations → ISO-3166, markdown stripped
3. **Merge** — Union-Find groups records by email/phone/name+company, resolves conflicts by source authority with recency tie-breaking
4. **Validate** — Pydantic `CanonicalProfile` schema validation
5. **Project** — Pure function reshaping via runtime JSON config with `null`/`omit`/`error` strategies

## Projection Config

```json
{
  "fields": [
    { "path": "name", "from": "full_name" },
    { "path": "email", "from": "emails[0]", "on_missing": "omit" },
    { "path": "city", "from": "location.city", "on_missing": "null" }
  ]
}
```

## Project Structure

```
├── main.py                  # CLI entry point & orchestrator
├── models.py                # Pydantic schema (CanonicalProfile)
├── parse_ats_json.py        # ATS JSON parser
├── csv_parser.py            # Recruiter CSV parser
├── ingestion.py             # Unstructured text parser
├── resume_parser.py         # PDF/DOCX resume parser
├── normalization_engine.py  # Normalization (phones, skills, dates, locations)
├── merge_engine.py          # Union-Find entity resolution & merging
├── projection.py            # Configurable output projection
├── requirements.txt         # Python dependencies
├── samples/                 # Sample input data & config
│   ├── candidate_ats.json
│   ├── resume.pdf
│   └── view_config.json
└── tests/
    └── test_pipeline.py     # 54 pytest tests
```
