# main.py — CLI Entry Point (Step 6)

## Purpose
Orchestrates the full pipeline: parse → normalize → merge → validate → project → output.

## CLI Usage
```
python main.py --inputs file1.json file2.txt ... --config view.json
```

## Pipeline Stages

| Stage | What Happens | Error Handling |
|---|---|---|
| 0. Load config | `--config` JSON is read | Missing/corrupt config → exit with error |
| 1. Parse | `.json` → `parse_ats_json()`, `.txt` → `parse_unstructured_notes()`, rest skipped | Missing/garbled files → warning + skip |
| 2. Normalize | `NormalizationEngine.transform()` on each raw dict | Propagates (input already validated) |
| 3. Merge | `MergeEngine.merge()` groups & resolves conflicts | Silent (no per-record errors) |
| 4. Validate | `CanonicalProfile.model_validate()` on each merged dict | Invalid profiles → warning + skip |
| 5. Project | `project_profile()` reshapes per runtime config | `ConfigurationError` → exit with error |
| 6. Output | `json.dumps(..., indent=2)` to stdout | — |

## Re-export Wrappers
- `normalization.py` → `from normalization_engine import NormalizationEngine`
- `merging.py` → `from merge_engine import MergeEngine`
