# Multi-Source Candidate Data Transformer - Technical Design Document

### 1. End-to-End Principle
The system must be deterministic and explainable (same inputs always produce the same output, every field traceable to a source and method), robust (a missing or garbage source never crashes the run — unknown values become null, never invented), and scalable (linear-time algorithms suitable for thousands of candidates).

### 2. Flow Diagram
`Input Files → [Ingest & Parse] → [Normalize] → [Entity Resolution & Merging] → [Validation] → [Projection] → [Output JSON]`
*Ingest: extract raw. Normalize: standardize formats. Merge: Union-Find grouping. Validate: strict canonical schema. Project: pure config-driven reshape.*

### 3. Canonical Data Model & Normalization Strategy
The canonical schema is the single internal source of truth, kept strictly separate from any output projection.
**Key fields:** `candidate_id`, `full_name`, `emails[]`, `phones[]`, `location {city, region, country}`, `links {linkedin, github, portfolio, other[]}`, `headline`, `years_experience`, `skills[]`, `experience[]`, `education[]`, `provenance[]`, `overall_confidence`.
**Strategy:** every source maps into this one model before merging — no source-specific shortcuts downstream of normalization.

### 4. Normalization Rules & Principles
Phones → E.164. Dates → YYYY-MM. Country → ISO-3166 alpha-2. Skills → lowercased + alias-mapped to one canonical name (synonym dictionary).
`years_experience`: overlapping experience date intervals are merged into union ranges first, then summed, to avoid double-counting concurrent roles.
**Principle:** normalization is centralized — one normalization layer shared across all source types (structured and unstructured alike), not duplicated per-parser.

### 5. Confidence Scoring
Field-level confidence is calculated to heavily penalize missing critical attributes:
```
field_confidence = max(0, source_authority - 0.10 * malformed_attributes)
overall_confidence = mean(populated_field_confidences)
```
**Source authority hierarchy:** ATS JSON (0.95) > Recruiter CSV (0.85) > LinkedIn/GitHub (0.75) > Unstructured Notes/Resumes (0.50).

### 6. Merge / Conflict-Resolution Mechanism
**Multi-key match matrix:** primary = shared email, secondary = shared phone, tertiary = full_name + employer (fallback for sources lacking emails).
Transitive merges resolved via Union-Find (A↔B, B↔C ⇒ single connected profile).
Conflicting single-value fields resolved by source authority; equal-authority ties broken by content-based recency (latest `experience.end` date), falling back to file modification timestamp.
Arrays (emails, phones, skills, etc.) are unioned and deduplicated, not overwritten.

### 7. Runtime Custom-Output Config (Projection)
Pure function `project(CanonicalRecord, Config) -> CustomJSON`, strictly separated from the canonical record. Supports field selection, remapping via path strings (`emails[0]`), per-field normalization overrides, toggling provenance/confidence. `on_missing: null | omit | error`. Invalid config paths raise `ConfigurationError` immediately. Output is validated against the requested schema after projection, before serialization.
```json
{
  "fields": [
    { "path": "name", "from": "full_name" },
    { "path": "email", "from": "emails[0]", "on_missing": "omit" }
  ]
}
```

### 8. Edge Cases (3-5) & Deliberate Descoping
**Edge cases:** Circular/transitive merges (handled by Union-Find), malformed/empty input (confidence 0.0, never crashes), equal-authority conflicts (recency tiebreak), skill synonym aliasing, and the tertiary-match-key false-merge tradeoff (favors recall over precision).
**Descoping:** Multi-threading, external DB persistence, and GitHub ingestion are explicitly out of scope for the prototype to focus on linear-time in-memory merging accuracy.
