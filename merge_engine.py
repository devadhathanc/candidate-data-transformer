from collections import defaultdict
from typing import Any, Optional


SOURCE_AUTHORITY: dict[str, float] = {
    "ats_json": 0.95,
    "recruiter_csv": 0.85,
    "unstructured_notes": 0.50,
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
                company = (exp.get("company") or "").strip()
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

        merged["overall_confidence"] = self._compute_confidence(group_recs)
        return merged

    # ------------------------------------------------------------------
    # Conflict resolution — highest authority source wins
    # ------------------------------------------------------------------
    def _resolve_field(self, field: str, records: list[dict]) -> Any:
        best_value: Any = None
        best_score = -1.0
        for rec in records:
            val = rec.get(field)
            if val is None:
                continue
            source = self._field_source(field, rec)
            if source is None:
                continue
            score = self.authority.get(source, 0.0)
            if score > best_score:
                best_score = score
                best_value = val
        return best_value

    @staticmethod
    def _field_source(field: str, record: dict) -> Optional[str]:
        for prov in record.get("provenance", []):
            if prov.get("field") == field:
                return prov.get("source")
        return None

    # ------------------------------------------------------------------
    # Array merging — combine and deduplicate exact matches
    # ------------------------------------------------------------------
    @staticmethod
    def _merge_arrays(records: list[dict], field: str) -> list:
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
    def _hash_item(item: Any) -> Optional[str]:
        if isinstance(item, dict):
            return str(sorted((k, MergeEngine._hash_item(v)) for k, v in item.items()))
        if isinstance(item, str):
            return item
        return str(item)

    # ------------------------------------------------------------------
    # Confidence — average of source-authority scores across all fields
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Confidence — average of decayed source scores, clamped at 0.0
    # ------------------------------------------------------------------
    def _compute_confidence(self, group_recs: list[dict]) -> float:
        if not group_recs:
            return 0.0
            
        # Extract the pre-calculated confidence scores from the ingestion layer
        # (which already correctly applied the -0.10 penalty for malformed attributes)
        scores = [rec.get("overall_confidence", 0.0) for rec in group_recs]
        
        # Calculate the arithmetic mean
        average_confidence = sum(scores) / len(scores)
        
        # Clamp at 0.0 to prevent meaningless negative confidence scores
        return round(max(0.0, average_confidence), 2)
