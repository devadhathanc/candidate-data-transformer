# normalization_engine.py — Data Cleaning / Normalization (Step 2)

## Purpose
Takes raw parsed dicts and normalises specific fields before merging.

## Transformation Rules

### Phones → E.164
- Uses `phonenumbers` library (`pip install phonenumbers`).
- Parses with the configurable `default_region` (default `"US"`).
- Invalid/unparseable numbers are silently dropped.

### Skills → Lowercase + Alias + Deduplicate
1. Strip whitespace from the skill name.
2. Lowercase.
3. Look up in `DEFAULT_SKILL_ALIASES` (e.g., `"cpp"` → `"c++"`, `"py"` → `"python"`).
4. First occurrence of each aliased name wins; subsequent duplicates are dropped.

### Dates → YYYY-MM
- Already in `YYYY-MM` or bare `YYYY` → returned as-is.
- ISO 8601 variants (`2020-01-15T00:00:00Z`, `2020-01-15T00:00:00.000Z`) → truncated to `2020-01`.
- Last resort: regex grabs the first `YYYY-MM` substring.
- Unparseable values → `None`.

## Customisation
Constructor accepts:
- `skill_aliases` — override the default alias dictionary.
- `default_region` — change phone parsing region.
