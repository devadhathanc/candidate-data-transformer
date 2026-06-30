from collections import defaultdict
from typing import Any, Optional


SOURCE_AUTHORITY: dict[str, float] = {
    "ats_json": 0.95,
    "unstructured_notes": 0.50,
}


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
        return [self._merge_group(indices, records) for indices in groups]

    # ------------------------------------------------------------------
    # Match Matrix — group by email → phone → name + company
    # ------------------------------------------------------------------
    @staticmethod
    def _build_groups(records: list[dict]) -> list[list[int]]:
        n = len(records)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # Pre-extract identifiers per record
        emails: list[set[str]] = []
        phones: list[set[str]] = []
        names: list[str] = []
        companies: list[set[str]] = []

        for rec in records:
            emails.append(set(rec.get("emails", [])))
            phones.append(set(rec.get("phones", [])))
            names.append((rec.get("full_name") or "").strip().lower())

            exps = rec.get("experience", [])
            companies.append(
                {e.get("company", "") for e in exps if isinstance(e, dict)}
            )

        for i in range(n):
            for j in range(i + 1, n):
                # 1. Shared email
                if emails[i] and emails[j] and (emails[i] & emails[j]):
                    union(i, j)
                    continue
                # 2. Shared phone
                if phones[i] and phones[j] and (phones[i] & phones[j]):
                    union(i, j)
                    continue
                # 3. Same name + at least one shared employer
                if (
                    names[i]
                    and names[j]
                    and names[i] == names[j]
                    and companies[i]
                    and companies[j]
                    and (companies[i] & companies[j])
                ):
                    union(i, j)

        groups: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            groups[find(i)].append(i)
        return list(groups.values())

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

        merged["overall_confidence"] = self._compute_confidence(all_provenance)
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
    def _compute_confidence(self, provenance: list[dict]) -> float:
        if not provenance:
            return 0.0
        scores = [
            self.authority.get(prov.get("source", ""), 0.0)
            for prov in provenance
        ]
        return sum(scores) / len(scores)
