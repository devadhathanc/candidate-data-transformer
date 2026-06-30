import re
from typing import Any


class ConfigurationError(Exception):
    pass


# ── Schema paths that exist in CanonicalProfile ───────────────────
# [*] matches any numeric array index.
_VALID_SCHEMA_PATHS: set[str] = {
    "candidate_id",
    "full_name",
    "headline",
    "years_experience",
    "overall_confidence",
    "emails",
    "emails[*]",
    "phones",
    "phones[*]",
    "location",
    "location.city",
    "location.region",
    "location.country",
    "links",
    "links.linkedin",
    "links.github",
    "links.portfolio",
    "links.other",
    "skills",
    "skills[*]",
    "skills[*].name",
    "skills[*].confidence",
    "skills[*].sources",
    "experience",
    "experience[*]",
    "experience[*].company",
    "experience[*].title",
    "experience[*].start",
    "experience[*].end",
    "experience[*].summary",
    "education",
    "education[*]",
    "education[*].institution",
    "education[*].degree",
    "education[*].field",
    "education[*].end_year",
    "provenance",
    "provenance[*]",
    "provenance[*].field",
    "provenance[*].source",
    "provenance[*].method",
}


# ── Helpers ───────────────────────────────────────────────────────

def _to_schema_path(requested: str) -> str:
    """Replace array indices with [*] so we can match against the schema."""
    return re.sub(r"\[\d+\]", "[*]", requested)


def _validate_path(requested: str) -> None:
    schema_path = _to_schema_path(requested)
    if schema_path not in _VALID_SCHEMA_PATHS:
        # Collect suggestions for a helpful error message
        suggestions = sorted(
            p for p in _VALID_SCHEMA_PATHS
            if p.startswith(schema_path.split(".")[0])
        )
        hint = ""
        if suggestions:
            hint = f" Did you mean: {', '.join(suggestions)}?"
        raise ConfigurationError(
            f"Path '{requested}' does not exist in the CanonicalProfile schema.{hint}"
        )


def _parse_path(path: str) -> list:
    """'skills[0].name' → ['skills', 0, 'name']"""
    segments: list = []
    for part in path.split("."):
        m = re.match(r"^(\w+)\[(\d+)\]$", part)
        if m:
            segments.append(m.group(1))
            segments.append(int(m.group(2)))
        else:
            segments.append(part)
    return segments


def _safe_get(obj: dict, path: str) -> Any:
    segments = _parse_path(path)
    current: Any = obj
    for seg in segments:
        if isinstance(current, dict) and isinstance(seg, str) and seg in current:
            current = current[seg]
        elif isinstance(current, list) and isinstance(seg, int) and 0 <= seg < len(current):
            current = current[seg]
        else:
            return None
    return current


# ── Public API ────────────────────────────────────────────────────

def project_profile(canonical_record: dict, config: dict) -> dict:
    output: dict[str, Any] = {}

    for field_cfg in config.get("fields", []):
        if not isinstance(field_cfg, dict):
            continue

        out_key = field_cfg.get("path")
        if not isinstance(out_key, str):
            continue

        source_path = field_cfg.get("from", out_key)
        if not isinstance(source_path, str):
            continue

        _validate_path(source_path)

        value = _safe_get(canonical_record, source_path)

        if value is None:
            strategy = field_cfg.get("on_missing", "null")
            if strategy == "null":
                output[out_key] = None
            elif strategy == "omit":
                continue
            elif strategy == "error":
                raise ConfigurationError(
                    f"Required field '{out_key}' (source path: '{source_path}') "
                    f"resolved to None or is out-of-bounds in the canonical record."
                )
            else:
                output[out_key] = None
        else:
            output[out_key] = value

    return output
