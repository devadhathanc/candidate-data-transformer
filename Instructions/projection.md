# projection.py — Dynamic Projection / Reshaping (Step 5)

## Purpose
A pure function that reshapes a canonical profile into an arbitrary output
shape at runtime based on a JSON configuration file.

## Config Format
```json
{
  "fields": [
    { "path": "full_name", "type": "string" },
    { "path": "primary_email", "from": "emails[0]", "on_missing": "omit" }
  ]
}
```

| Key | Default | Behaviour |
|---|---|---|
| `path` | (required) | Output key name in the result dict |
| `from` | same as `path` | Source path to extract from the canonical record |
| `type` | ignored | Informational only (schema hint) |
| `on_missing` | `"null"` | `"null"` → set value to `None`; `"omit"` → skip key; `"error"` → raise `ConfigurationError` |

## Schema Validation
Before extraction, every source path is validated against a strict whitelist of
fields that exist in the `CanonicalProfile` schema. Array indices like `emails[0]`
are normalised to `emails[*]` for matching. Unknown paths raise `ConfigurationError`
with a list of suggestions.

## Path Resolution (`_safe_get`)
Supports:
- Simple keys: `full_name`
- Nested dicts: `location.city`
- Array indices: `emails[0]`, `skills[0].name`
- Combinations: `experience[0].company`

Returns `None` for any out-of-bounds or missing intermediate key.
