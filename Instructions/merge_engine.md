# merge_engine.py — Entity Resolution & Merging (Step 3)

## Purpose
Groups records belonging to the same person across multiple source files,
resolves conflicting fields, and produces one canonical profile per group.

## Refactored Architecture (DSU / Union-Find)

Originally used O(N²) pairwise comparison. Refactored to a **Disjoint Set Union**
(Union-Find) graph algorithm for O(N·α(N)) near-linear time.

### `UnionFind` Helper Class
| Method | Behaviour |
|---|---|
| `find(x)` | Returns root with path compression (flattens the tree) |
| `union(a, b)` | Merges the sets containing `a` and `b` |
| `groups()` | Returns `{root: [indices...]}` — all connected components |

### Graph Construction (Three Passes)

| Pass | Key | Map |
|---|---|---|
| 1. Primary | `emails` | `email → [record_indices]` |
| 2. Secondary | `phones` | `phone → [record_indices]` |
| 3. Tertiary | `(full_name, company)` from experience | `(name, company) → [record_indices]` |

Records sharing the same key in any pass are `union()`-ed together, automatically
resolving transitive links (A shares email with B, B shares phone with C → all three
are in one group).

### Conflict Resolution (Single-Value Fields)
For `candidate_id`, `full_name`, `headline`, `years_experience`, `location`, `links`:
- Each record's provenance tells us which source produced the field.
- The value from the highest-authority source wins.

**Source Authority Hierarchy:**
- `ats_json`: 0.95
- `recruiter_csv`: 0.85
- `unstructured_notes`: 0.50

### Array Merging
Arrays (`skills`, `experience`, `education`, `emails`, `phones`) are combined across
all records in the group and deduplicated by exact hash (dicts sorted by key, strings
by identity).

### Confidence Recalculation
Original approach: averaged source-authority scores across all provenance entries.
Current approach: averages the `overall_confidence` values from each constituent
record (which already incorporate the `-0.10` penalty from the ingestion layer),
then clamps at 0.0.
