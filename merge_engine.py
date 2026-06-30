from collections import defaultdict
from typing import Any, Optional


SOURCE_AUTHORITY: dict[str, float] = {
    "ats_json": 0.95,
    "recruiter_csv": 0.85,
    "unstructured_notes": 0.50,
    "resume_pdf": 0.50,
    "resume_docx": 0.50,
}


# ── DSU / Union-Find ──────────────────────────────────────────────

class UnionFind:
    """Disjoint Set Union with path compression (no rank needed for this scale)."""

    def __init__(self, n: int):
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def groups(self) -> dict[int, list[int]]:
        g: dict[int, list[int]] = defaultdict(list)
        for i in range(len(self._parent)):
            g[self.find(i)].append(i)
        return g


# ── Merge Engine ──────────────────────────────────────────────────

class MergeEngine:
    def __init__(
        self,
        source_authority: Optional[dict[str, float]] = None,
    ):
        self.authority = source_authority or SOURCE_AUTHORITY

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def merge(self, records: list[dict]) -> list[dict]:
        if not records:
            return []
        groups = self._build_groups(records)
        return [self._merge_group(indices, records) for indices in groups.values()]

    # ------------------------------------------------------------------
    # Graph Construction via DSU (O(N·α(N)))
    # ------------------------------------------------------------------
    
    @staticmethod
    def _build_groups(records: list[dict]) -> dict[int, list[int]]:
        n = len(records)
        dsu = UnionFind(n)

        # 1. Primary key — emails
        email_map: dict[str, list[int]] = defaultdict(list)
        for i, rec in enumerate(records):
            for email in rec.get("emails", []):
                email_map[email].append(i)
        for indices in email_map.values():
            if len(indices) > 1:
                root = indices[0]
                for idx in indices[1:]:
                    dsu.union(root, idx)

        # 2. Secondary key — phones
        phone_map: dict[str, list[int]] = defaultdict(list)
        for i, rec in enumerate(records):
            for phone in rec.get("phones", []):
                phone_map[phone].append(i)
        for indices in phone_map.values():
            if len(indices) > 1:
                root = indices[0]
                for idx in indices[1:]:
                    dsu.union(root, idx)

        # 3. Tertiary key — (lowercased full_name, company) from experience
        name_company_map: dict[tuple[str, str], list[int]] = defaultdict(list)
        for i, rec in enumerate(records):
            name = (rec.get("full_name") or "").strip().lower()
            if not name:
                continue
            for exp in rec.get("experience", []):
                company = (exp.get("company") or "").strip().lower()
                if not company:
                    continue
                name_company_map[(name, company)].append(i)
        for indices in name_company_map.values():
            if len(indices) > 1:
                root = indices[0]
                for idx in indices[1:]:
                    dsu.union(root, idx)

        return dsu.groups()

    # ------------------------------------------------------------------
    # Group merger
    # ------------------------------------------------------------------
    _SINGLE_FIELDS = frozenset({
        "candidate_id", "full_name", "headline",
        "years_experience", "location", "links",
    })
    _ARRAY_FIELDS = frozenset({
        "emails", "phones", "skills", "experience", "education",
    })

    def _merge_group(self, indices: list[int], records: list[dict]) -> dict:
        group_recs = [records[i] for i in indices]
        merged: dict[str, Any] = {}

        for field in self._SINGLE_FIELDS:
            val = self._resolve_field(field, group_recs)
            if val is not None:
                merged[field] = val

        for field in self._ARRAY_FIELDS:
            arr = self._merge_arrays(group_recs, field)
            if arr:
                merged[field] = arr

        # Provenance — union from every record, deduplicate
        all_provenance = []
        seen_prov: set[tuple[str, str, str]] = set()
        for rec in group_recs:
            for prov in rec.get("provenance", []):
                key = (
                    prov.get("field", ""),
                    prov.get("source", ""),
                    prov.get("method", ""),
                )
                if key not in seen_prov:
                    seen_prov.add(key)
                    all_provenance.append(dict(prov))
        if all_provenance:
            merged["provenance"] = all_provenance

        # overall_confidence = mean of the max confidence per unique field
        merged["overall_confidence"] = self._compute_confidence(all_provenance)
        return merged

    # ------------------------------------------------------------------
    # Conflict resolution — highest field-level confidence wins
    # ------------------------------------------------------------------
    def _resolve_field(self, field: str, records: list[dict]) -> Any:
        """Resolve a single-value field across multiple records.

        Uses field-level confidence from provenance (not the authority map)
        so each field carries the pre-computed penalty for malformed attributes.
        Ties in confidence are broken by content-based recency.
        """
        best_value: Any = None
        best_conf = -1.0
        best_recency: str = ""
        for rec in records:
            val = rec.get(field)
            if val is None:
                continue
            conf = self._field_confidence(field, rec)
            if conf is None:
                continue
            recency = self._latest_experience_end(rec)
            if conf > best_conf or (conf == best_conf and recency > best_recency):
                best_conf = conf
                best_value = val
                best_recency = recency
        return best_value

    @staticmethod
    def _latest_experience_end(record: dict) -> str:
        """Return the latest experience.end date string for recency tie-breaking.

        Returns empty string if no dates are found, so records without dates
        naturally lose ties to records that have them.
        """
        latest = ""
        for exp in record.get("experience", []):
            end = exp.get("end")
            if isinstance(end, str) and end > latest:
                latest = end
        return latest

    @staticmethod
    def _field_confidence(field: str, record: dict) -> Optional[float]:
        """Look up the field-level confidence for *field* from this record's provenance."""
        for prov in record.get("provenance", []):
            if prov.get("field") == field:
                return prov.get("confidence", 0.0)
        return None

    # ------------------------------------------------------------------
    # Array merging — combine and deduplicate exact matches
    # ------------------------------------------------------------------
    @staticmethod
    def _merge_arrays(records: list[dict], field: str) -> list:
        if field == "skills":
            return MergeEngine._merge_skills(records)
        seen: set[str] = set()
        result: list = []
        for rec in records:
            for item in rec.get(field, []):
                key = MergeEngine._hash_item(item)
                if key is not None and key not in seen:
                    seen.add(key)
                    result.append(item)
        return result

    @staticmethod
    def _merge_skills(records: list[dict]) -> list[dict]:
        """Merge skills across records, deduplicating by normalized name.

        Cross-source deduplication uses *highest-confidence wins*: when the same
        skill appears from multiple sources, the entry with the highest confidence
        is kept and the sources lists are combined. This is a deliberate design
        choice — unlike within-source dedup (normalization_engine, first-occurrence)
        — because cross-source data has meaningful confidence differences that
        should determine which metadata is authoritative.
        """
        best: dict[str, dict] = {}  # normalized_name -> best skill dict
        for rec in records:
            for skill in rec.get("skills", []):
                if not isinstance(skill, dict):
                    continue
                name = (skill.get("name") or "").strip().lower()
                if not name:
                    continue
                conf = skill.get("confidence", 0.0)
                if name not in best or conf > best[name].get("confidence", 0.0):
                    merged_sources = list(best[name].get("sources", [])) if name in best else []
                    new_sources = skill.get("sources", [])
                    combined = list(dict.fromkeys(merged_sources + new_sources))
                    best[name] = {**skill, "sources": combined}
                else:
                    # Lower confidence — just merge sources
                    existing_sources = best[name].get("sources", [])
                    new_sources = skill.get("sources", [])
                    best[name]["sources"] = list(dict.fromkeys(existing_sources + new_sources))
        return list(best.values())

    @staticmethod
    def _hash_item(item: Any) -> Optional[str]:
        if isinstance(item, dict):
            return str(sorted((k, MergeEngine._hash_item(v)) for k, v in item.items()))
        if isinstance(item, str):
            return item
        return str(item)
    # ------------------------------------------------------------------
    # Confidence — mean of max per-field confidences from provenance
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_confidence(all_provenance: list[dict]) -> float:
        """Compute overall_confidence as the mean of the max confidence per
        unique field across the merged provenance entries.

        For each field that appears in provenance, we take the *max* confidence
        across sources (because that represents the winning source's data quality).
        The overall score is the arithmetic mean across all populated fields.
        """
        if not all_provenance:
            return 0.0

        # Group by field name, take max confidence per field
        field_best: dict[str, float] = {}
        for prov in all_provenance:
            field = prov.get("field", "")
            conf = prov.get("confidence", 0.0)
            if field not in field_best or conf > field_best[field]:
                field_best[field] = conf

        if not field_best:
            return 0.0

        mean_conf = sum(field_best.values()) / len(field_best)
        return round(max(0.0, mean_conf), 4)