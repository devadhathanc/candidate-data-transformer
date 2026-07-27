# models.py — Pydantic Schema Definition

## Purpose
Defines the strict target schema for the entire pipeline. Every parsed, normalized,
merged, and projected record must conform to these models.

## Models

| Class | Description | Key Fields |
|---|---|---|
| `Location` | Geographic location | `city`, `region`, `country` (ISO-3166 alpha-2) |
| `Links` | Social/portfolio URLs | `linkedin`, `github`, `portfolio`, `other[]` |
| `Skill` | Named skill with confidence | `name`, `confidence`, `sources[]` |
| `Experience` | Work history entry | `company`, `title`, `start`/`end` (YYYY-MM), `summary` |
| `Education` | Academic background | `institution`, `degree`, `field` (alias `field_of_study`), `end_year` |
| `Provenance` | Field-level lineage | `field`, `source`, `method` |
| `CanonicalProfile` | Top-level merged profile | All above + `candidate_id`, `full_name`, `emails[]`, `phones[]`, `headline`, `years_experience`, `overall_confidence` |

## Design Decisions
- All list fields use `default_factory=list` to avoid mutable default traps.
- `Education.field` uses Pydantic `Field(alias="field")` so both the canonical key
  `field_of_study` and the alias `field` are accepted.
- No validation logic here — models are pure structural contracts; validation
  happens at `CanonicalProfile.model_validate()` in the pipeline.
