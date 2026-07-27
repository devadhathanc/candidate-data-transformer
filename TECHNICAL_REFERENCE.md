# Multi-Source Candidate Data Transformer — Complete Process & Technical Reference

---

## 1. Problem Statement

Build a pipeline that ingests candidate data from **multiple heterogeneous sources** (structured JSON, unstructured resume text), merges records belonging to the same person, resolves conflicting fields, and outputs a configurable JSON shape.

**Core challenge:** Real-world candidate data arrives in different formats, with overlapping/conflicting information, from sources of varying reliability. The system must intelligently combine everything into a single clean profile.

---

## 2. Pipeline Architecture (Linear, 6-Stage)

```
Input Files → [1. Parse] → [2. Normalize] → [3. Merge] → [4. Validate] → [5. Project] → [6. Output JSON]
```

### Stage-by-Stage Breakdown

### Stage 1 — Ingestion & Parsing (`parse_ats_json.py`, `ingestion.py`, `resume_parser.py`, `csv_parser.py`)

**What it does:** Routes each input file to the correct parser based on file extension.

| Extension | Parser | Source Type |
|---|---|---|
| `.json` | `parse_ats_json()` | Structured (ATS) |
| `.csv` | `parse_recruiter_csv()` | Structured (Recruiter) |
| `.pdf` | `parse_resume_file()` → `pdfplumber` | Unstructured (Resume) |
| `.docx` | `parse_resume_file()` → `python-docx` | Unstructured (Resume) |
| `.txt` | `parse_unstructured_notes()` | Unstructured (Notes) |

**Techniques used:**

- **ATS JSON Parser:** Nested `.get()` chains for safe extraction from deeply nested JSON keys. Scalar-to-array coercion (e.g., single email → `[email]`). Polymorphic tag handling (tags can be dicts or plain strings).

- **Unstructured Text Parser:** Regex-based extraction:
  - Email: `[\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,}`
  - Phone: `\+?\d[\d\s.\-()]{7,}\d` with digit-count validation (7–15 digits) and date-pattern rejection
  - Years of experience: `(\d+)\+?\s*years?`
  - Experience entries: `(.+?)\s+at\s+(.+?)(?:\s+\((\d{4}-\d{2})\s*[-–]\s*(\d{4}-\d{2}|present)\))?`
  - Skills: keyword lookup against a curated list scanned over lowercased text

- **Resume Parser:** Binary file text extraction via `pdfplumber` (PDF) and `python-docx` (DOCX), then delegates to the shared unstructured text parser. Lazy imports (`import pdfplumber` inside the function) so the libraries are only loaded when needed.

- **CSV Parser:** `csv.DictReader` with flexible header normalization (`FirstName` → `first_name`). Semicolon-separated skill parsing. One record per row.

**Field-Level Confidence (per the design doc formula):**
```
field_confidence = max(0, source_authority − 0.10 × malformed_attributes)
```
- `source_authority`: 0.95 (ATS), 0.85 (CSV), 0.50 (resume/notes)
- `malformed_attributes`: count of missing critical fields (candidate_id, full_name, emails, phones) in this record
- Each provenance entry carries its own field-level confidence score
- `overall_confidence` = arithmetic mean of all populated field confidences

**Provenance tracking:** Every extracted field gets a `{field, source, method, confidence}` entry recording its origin and quality score.

---

### Stage 2 — Normalization (`normalization_engine.py`)

**What it does:** Cleans and standardizes raw parsed data into strict target formats.

| Field | Technique | Library/Method |
|---|---|---|
| Phones | Parse → validate → format as E.164 (`+15551234567`) | `phonenumbers` library |
| Skills | Lowercase → alias lookup → deduplicate by name | Custom alias dictionary (36 entries) |
| Dates | ISO 8601 / various formats → `YYYY-MM` | `datetime.strptime()` with 4 format candidates + regex fallback |
| Location | Country name → ISO-3166 alpha-2 code | Custom mapping dictionary (40+ countries) |
| Headline | Strip markdown (`**bold**`, `_italic_`, `[links](url)`, backticks, escape sequences) | Regex substitutions |
| Experience | Strip markdown from title/summary fields | Same as headline |
| Years Experience | Merge overlapping date intervals → sum duration | Interval merging algorithm (see below) |

**Overlapping Interval Merging Algorithm (for `years_experience`):**
```
1. Parse start/end dates from each experience entry → absolute months
2. Sort intervals by start date
3. Sweep through: if current.start ≤ previous.end, merge (extend previous.end)
4. Sum total months across non-overlapping merged ranges
5. Convert to years (months ÷ 12), rounded to 1 decimal
```
This prevents double-counting concurrent roles (e.g., an internship during full-time employment).

**Skill Alias Dictionary (examples):**
```
"js" → "javascript"    "k8s" → "kubernetes"    "reactjs" → "react"
"cpp" → "c++"          "py" → "python"         "nodejs" → "node.js"
"amazon web services" → "aws"                   "golang" → "go"
```

---

### Stage 3 — Entity Resolution & Merging (`merge_engine.py`)

**What it does:** Groups records belonging to the same person and merges them into one canonical profile.

**Algorithm: Disjoint Set Union (Union-Find) with Path Compression**

Instead of O(N²) pairwise comparison, uses Union-Find for near-linear O(N·α(N)) time.

```python
class UnionFind:
    find(x)       # Returns root with path compression (flattens tree)
    union(a, b)   # Merges sets containing a and b
    groups()      # Returns {root: [indices...]} — all connected components
```

**Three-Pass Graph Construction:**

| Pass | Key Type | Match Rule |
|---|---|---|
| 1. Primary | Email | Any shared email string in the `emails[]` array |
| 2. Secondary | Phone | Any shared phone string in the `phones[]` array |
| 3. Tertiary | Name + Company | Exact match on `(lowercased full_name, company)` from experience |

Records sharing any key in any pass are `union()`-ed, automatically resolving **transitive links** (A shares email with B, B shares phone with C → all three merge).

**Conflict Resolution (Single-Value Fields):**

Source Authority Hierarchy:
```
ats_json: 0.95 > recruiter_csv: 0.85 > resume_pdf/resume_docx/unstructured_notes: 0.50
```

For fields like `full_name`, `headline`, `location` — the value from the highest-authority source wins.

**Equal-Authority Tie-Breaking:**
When two sources have the same authority score, the one with the **most recent `experience.end` date** wins (content-based recency signal).

**Array Merging:**
- `emails`, `phones`, `experience`, `education` — combined and deduplicated by exact hash
- `skills` — deduplicated by **normalized name**, keeping the highest-confidence entry and merging the `sources[]` arrays

**Confidence Recalculation:**
```
merged_confidence = average(record1.overall_confidence, record2.overall_confidence, ...)
clamped at 0.0
```

---

### Stage 4 — Validation (`models.py`)

**What it does:** Validates merged profiles against the Pydantic `CanonicalProfile` schema.

**Schema (Pydantic v2 BaseModel):**

| Model | Key Fields |
|---|---|
| `Location` | `city`, `region`, `country` (ISO-3166) |
| `Links` | `linkedin`, `github`, `portfolio`, `other[]` |
| `Skill` | `name`, `confidence`, `sources[]` |
| `Experience` | `company`, `title`, `start`/`end` (YYYY-MM), `summary` |
| `Education` | `institution`, `degree`, `field_of_study` (alias: `field`), `end_year` |
| `Provenance` | `field`, `source`, `method` |
| `CanonicalProfile` | All above + `candidate_id`, `full_name`, `emails[]`, `phones[]`, `headline`, `years_experience`, `overall_confidence` |

**Design decisions:**
- All list fields use `default_factory=list` to avoid mutable default traps
- `Education.field_of_study` uses Pydantic `Field(alias="field")` so both names are accepted
- Invalid profiles are logged and skipped (don't crash the pipeline)

---

### Stage 5 — Projection (`projection.py`)

**What it does:** A **pure function** that reshapes the canonical profile into any output shape at runtime based on a JSON config.

**Config format:**
```json
{
  "fields": [
    { "path": "name", "from": "full_name" },
    { "path": "email", "from": "emails[0]", "on_missing": "omit" },
    { "path": "city", "from": "location.city", "on_missing": "null" }
  ]
}
```

**Path resolution (`_safe_get`):**
- Simple keys: `full_name`
- Nested dicts: `location.city`
- Array indices: `emails[0]`, `skills[0].name`
- Combinations: `experience[0].company`

**Missing value strategies:**

| Strategy | Behavior |
|---|---|
| `"null"` (default) | Sets value to `None` |
| `"omit"` | Omits the key entirely from output |
| `"error"` | Raises `ConfigurationError`, halting execution |

**Safety checks:**
- **Schema validation:** Every source path is validated against a whitelist of paths that exist in `CanonicalProfile`. Unknown paths raise `ConfigurationError` with suggestions.
- **Collision detection:** If two config fields map to the same output key, raises `ConfigurationError` before processing.

---

### Stage 6 — Output (`main.py`)

Serializes the projected profiles to JSON with `json.dumps(indent=2)` on stdout.
All warnings/errors go to stderr via the `logging` module, keeping stdout clean for piping.

---

## 3. Edge Cases Handled

### Parsing Edge Cases
| Edge Case | How It's Handled |
|---|---|
| Empty JSON `{}` | All critical fields missing (candidate_id, full_name, emails, phones) → field_confidence = 0.55 |
| Missing `PersonalDetails` object | Safe `.get()` returns `{}`, sub-fields return `None` |
| Tags as plain strings (not dicts) | Polymorphic handling: strings get `confidence: 0.0` |
| `OtherLinks` as single string | Coerced to `[string]` |
| Empty/unreadable PDF | Returns `""`, caller skips empty result |
| Password-protected/corrupt files | Top-level try/except returns `""`, never crashes |
| Phone numbers that look like dates | Digit-count validation (7–15) + date-pattern rejection regex |
| Empty unstructured text | Produces minimal profile with `overall_confidence ≈ 0.10` |

### Normalization Edge Cases
| Edge Case | How It's Handled |
|---|---|
| Invalid phone numbers | Silently dropped by `phonenumbers` validation |
| Skill name variants (`ReactJS`, `react.js`, `React`) | All normalize to `"react"` via alias dictionary |
| Duplicate skills after aliasing | First occurrence wins, subsequent dropped |
| ISO 8601 date with milliseconds | `strptime` truncates to YYYY-MM |
| Bare year `"2020"` | Returned as-is (valid YYYY format) |
| Unparseable date strings | Returns `None` |
| 2-letter country code already correct | Preserved as uppercase (e.g., `"us"` → `"US"`) |
| Full country name | Mapped via 40+ entry dictionary (e.g., `"India"` → `"IN"`) |
| Overlapping work experience dates | Merged into union ranges before summing (prevents double-counting) |
| Missing end date (current job) | Uses current date as end |
| Markdown in headline/experience | Stripped: bold, italic, links, backticks, escape sequences |

### Merging Edge Cases
| Edge Case | How It's Handled |
|---|---|
| Transitive/circular merges (A↔B↔C) | Union-Find automatically resolves connected components |
| Two sources with identical authority | Tie-broken by content-based recency (latest `experience.end`) |
| Same skill from multiple sources | Deduplicated by name; highest confidence kept; sources merged |
| Record with no merge keys | Creates a new standalone canonical profile |
| Malformed/garbage input | Produces empty profile with `overall_confidence = 0.0` |

### Projection Edge Cases
| Edge Case | How It's Handled |
|---|---|
| Invalid/unknown source path | `ConfigurationError` with suggestions |
| Out-of-bounds array index (`emails[5]`) | Returns `None`, triggers `on_missing` strategy |
| Two fields mapping to same output key | `ConfigurationError` before processing |
| Missing intermediate key in nested path | Returns `None` gracefully |

---

## 4. Data Structures & Algorithms

| Component | Data Structure / Algorithm | Why |
|---|---|---|
| Entity Resolution | **Disjoint Set Union (Union-Find)** with path compression | Near-linear O(N·α(N)) vs O(N²) pairwise comparison |
| Skill Deduplication | **Hash map** (name → best skill dict) | O(1) lookup per skill |
| Array Deduplication | **Set** of serialized hashes | O(1) duplicate detection |
| Phone Normalization | **E.164 standard** via `phonenumbers` library | International phone format standard |
| Date Interval Merging | **Sweep line algorithm** (sort + merge overlapping) | O(N log N) for N experience entries |
| Schema Validation | **Pydantic v2 BaseModel** | Declarative validation with type coercion |
| Path Resolution | **Recursive segment parser** (`skills[0].name` → `['skills', 0, 'name']`) | Supports arbitrary nesting depth |
| Config Validation | **Whitelist set** with wildcard indices (`[*]`) | O(1) path validation |

---

## 5. Test Suite Summary (44 Tests)

### How to run:
```bash
python -m pytest tests/test_pipeline.py -v
```

### Test Categories:

#### 1. ATS Parser Tests (8 tests)
| Test | What It Verifies |
|---|---|
| `test_basic_fields` | candidate_id, full_name, emails, phones, headline extracted correctly |
| `test_skills_extraction` | Tags array parsed into skill dicts with name/confidence |
| `test_experience_extraction` | WorkHistory mapped to experience entries with dates |
| `test_confidence_full_record` | Complete record gets base confidence (0.95) |
| `test_confidence_missing_email` | Missing email deducts 0.10 → 0.85 |
| `test_provenance_tracking` | Every field gets a provenance entry |
| `test_empty_json` | Empty `{}` produces valid result with low confidence |
| `test_tags_as_strings` | Tags can be plain strings (not just dicts) |

#### 2. Unstructured Parser Tests (5 tests)
| Test | What It Verifies |
|---|---|
| `test_basic_fields` | Name, email extracted from free-form text |
| `test_experience_extraction` | "Title at Company (start – end)" pattern parsed |
| `test_years_experience` | "7+ years" regex extraction works |
| `test_skills_detection` | Keyword matching finds skills in text |
| `test_empty_text` | Empty string produces minimal valid result |

#### 3. Normalization Tests (9 tests)
| Test | What It Verifies |
|---|---|
| `test_phone_e164` | Various phone formats → E.164, invalid dropped |
| `test_skill_aliasing` | ReactJS→react, k8s→kubernetes, JS→javascript |
| `test_skill_dedup` | Python/python deduplicated to single entry |
| `test_date_normalization` | ISO 8601 → YYYY-MM, already-correct preserved |
| `test_location_iso_country` | "India" → "IN" |
| `test_location_preserves_2letter` | "US" stays "US" |
| `test_markdown_stripping` | `**bold**`, `_italic_`, `[links]` removed |
| `test_years_experience_overlapping` | Overlapping intervals → 3.0 years (not 4.0) |
| `test_years_experience_no_overlap` | Non-overlapping → simple sum = 2.0 years |

#### 4. Union-Find Tests (3 tests)
| Test | What It Verifies |
|---|---|
| `test_basic_union` | Two separate unions create two groups |
| `test_transitive_union` | A↔B + B↔C → A,B,C in same group |
| `test_groups` | Correct group enumeration |

#### 5. Merge Engine Tests (6 tests)
| Test | What It Verifies |
|---|---|
| `test_merge_by_email` | Shared email → merge; ATS wins conflict |
| `test_no_merge_different_emails` | Different emails → separate profiles |
| `test_merge_by_phone` | Shared phone → merge |
| `test_skill_dedup_across_sources` | Same skill from 2 sources → 1 entry, sources combined |
| `test_recency_tiebreaker` | Equal authority → more recent experience.end wins |
| `test_confidence_averaging` | Merged confidence = average of constituent confidences |

#### 6. Projection Tests (8 tests)
| Test | What It Verifies |
|---|---|
| `test_basic_remapping` | `full_name` → `name`, `emails[0]` → `email` |
| `test_on_missing_null` | Missing value → `None` in output |
| `test_on_missing_omit` | Missing value → key omitted from output |
| `test_on_missing_error` | Missing value → `ConfigurationError` raised |
| `test_invalid_path_raises` | Unknown path → `ConfigurationError` with suggestions |
| `test_nested_path` | `location.city` resolves correctly |
| `test_duplicate_output_key_raises` | Two fields → same key → `ConfigurationError` |
| `test_array_index_path` | `skills[0].name` resolves correctly |

#### 7. Schema Validation Tests (3 tests)
| Test | What It Verifies |
|---|---|
| `test_valid_profile` | Complete profile passes validation |
| `test_missing_required_field` | Missing `full_name` raises validation error |
| `test_default_lists` | Optional list fields default to `[]` |

#### 8. End-to-End Tests (2 tests)
| Test | What It Verifies |
|---|---|
| `test_full_pipeline_ats_json` | Full pipeline: parse → normalize → merge → validate → project |
| `test_multi_source_merge` | ATS JSON + unstructured text → merged into single profile |

---

## 6. Dependencies

| Library | Purpose | Version |
|---|---|---|
| `pydantic` | Schema validation & data models | ≥ 2.0 |
| `phonenumbers` | Phone number parsing & E.164 formatting | ≥ 8.13 |
| `pdfplumber` | PDF text extraction | ≥ 0.10 |
| `python-docx` | DOCX text extraction | ≥ 1.0 |
| `pytest` | Test framework | (dev dependency) |

---

## 7. CLI Usage

```bash
# Basic: one structured + one unstructured source
python main.py --inputs candidate.json resume.pdf --config view.json

# Multiple sources
python main.py --inputs ats1.json ats2.json notes.txt resume.pdf --config view.json

# Run tests
python -m pytest tests/test_pipeline.py -v
```

---

## 8. Known Limitations & Design Tradeoffs

| Limitation | Rationale |
|---|---|
| Tertiary match key (name + company) risks false merges for common names | Deliberate: favors recall (merging fragmented profiles) over strict precision |
| In-memory only (no database) | Scoped out: simplifies architecture for the prototype |
| No multi-threading | Scoped out: linear pipeline is sufficient for expected data volumes |
| Skill keyword detection is hardcoded list | Practical: covers the most common tech skills; extensible via config |
| Country ISO-3166 mapping covers ~40 countries | Extensible: add more as needed |
