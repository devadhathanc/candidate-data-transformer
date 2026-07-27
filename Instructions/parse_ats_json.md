# parse_ats_json.py — Structured JSON Parser (Step 1)

## Purpose
Reads a proprietary ATS JSON file with deeply nested keys and maps it to a
flat dictionary compatible with `CanonicalProfile`.

## Assumed Input Shape
```
{
  "CandidateId": "abc",
  "PersonalDetails": { "FirstName": "...", "LastName": "...", "Headline": "..." },
  "Contact": { "PrimaryEmail": "...", "Phone": "...", "LinkedIn": "...", "Github": "...", "Portfolio": "...", "OtherLinks": [...] },
  "Location": { "City": "...", "Region": "...", "Country": "..." },
  "Tags": [ { "Name": "...", "Confidence": 0.95, "Sources": [...] } ],
  "WorkHistory": [ { "Company": "...", "Title": "...", "StartDate": "...", "EndDate": "...", "Summary": "..." } ],
  "Education": [ { "Institution": "...", "Degree": "...", "Field": "...", "EndYear": "..." } ],
  "YearsExperience": 5.0
}
```

## Key Steps
1. **Safe extraction** — every field uses `.get()`; missing keys silently return `None`.
2. **Array coercion** — flat scalars like `PrimaryEmail` are wrapped into `[email]`.
3. **Confidence** — base `0.95`, deduct `0.10` per missing critical field
   (`candidate_id`, `full_name`, `emails`), clamped at `0.0`.
4. **Provenance** — every extracted field gets a `{field, source: 'ats_json', method: 'direct_mapping'}` entry.

## Edge Cases Handled
- Missing `PersonalDetails` object → `pd = {}`, `.get()` returns `None` for sub-fields.
- `Tags` items can be either dicts or plain strings.
- `OtherLinks` can be a list or a single string.
