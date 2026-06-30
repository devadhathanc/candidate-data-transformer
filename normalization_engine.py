import re
from datetime import datetime
from typing import Any, Optional

import phonenumbers


DEFAULT_SKILL_ALIASES: dict[str, str] = {
    "c++": "c++",
    "cpp": "c++",
    "c plus plus": "c++",
    "c#": "c#",
    "csharp": "c#",
    "c sharp": "c#",
    "javascript": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "ts": "typescript",
    "python": "python",
    "py": "python",
    "golang": "go",
    "react": "react",
    "reactjs": "react",
    "react.js": "react",
    "node": "node.js",
    "nodejs": "node.js",
    "aws": "aws",
    "amazon web services": "aws",
    "gcp": "google cloud platform",
    "google cloud platform": "google cloud platform",
    "azure": "azure",
    "microsoft azure": "azure",
    "docker": "docker",
    "kubernetes": "kubernetes",
    "k8s": "kubernetes",
}


class NormalizationEngine:
    def __init__(
        self,
        skill_aliases: Optional[dict[str, str]] = None,
        default_region: str = "US",
    ):
        self.skill_aliases = skill_aliases or DEFAULT_SKILL_ALIASES
        self.default_region = default_region

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def transform(self, raw: dict) -> dict:
        result = dict(raw)
        result["phones"] = self._normalize_phones(result.get("phones", []))
        result["skills"] = self._normalize_skills(result.get("skills", []))
        result["experience"] = self._normalize_experience_dates(result.get("experience", []))
        result["education"] = self._normalize_education_dates(result.get("education", []))
        return result

    # ------------------------------------------------------------------
    # Phones — E.164
    # ------------------------------------------------------------------
    def _normalize_phones(self, phones: Any) -> list[str]:
        if not isinstance(phones, list):
            return []
        cleaned: list[str] = []
        for phone in phones:
            if not isinstance(phone, str) or not phone.strip():
                continue
            try:
                parsed = phonenumbers.parse(phone, self.default_region)
                if phonenumbers.is_valid_number(parsed):
                    cleaned.append(
                        phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
                    )
            except phonenumbers.NumberParseException:
                continue
        return cleaned

    # ------------------------------------------------------------------
    # Skills — lowercase, alias, deduplicate
    # ------------------------------------------------------------------
    def _normalize_skills(self, skills: Any) -> list[dict]:
        if not isinstance(skills, list):
            return []
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for skill in skills:
            if not isinstance(skill, dict):
                continue
            raw_name = skill.get("name", "")
            if not isinstance(raw_name, str):
                continue
            cleaned = raw_name.strip().lower()
            aliased = self.skill_aliases.get(cleaned, cleaned)
            if aliased and aliased not in seen:
                seen.add(aliased)
                result.append({**skill, "name": aliased})
        return result

    # ------------------------------------------------------------------
    # Dates — ISO -> YYYY-MM
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_date(raw: Any) -> Optional[str]:
        if not isinstance(raw, str) or not raw.strip():
            return None
        raw = raw.strip()

        # Already YYYY-MM or YYYY
        if re.fullmatch(r"\d{4}-\d{2}", raw):
            return raw
        if re.fullmatch(r"\d{4}", raw):
            return raw

        # ISO 8601 variants
        candidates = [
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%Y/%m/%d",
        ]
        for fmt in candidates:
            try:
                return datetime.strptime(raw[:26] if "." in raw else raw[:19], fmt).strftime("%Y-%m")
            except ValueError:
                continue

        # Last-resort regex — grab any YYYY-MM substring
        m = re.search(r"(\d{4})-(\d{2})", raw)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        return None

    @staticmethod
    def _normalize_experience_dates(experiences: Any) -> list[dict]:
        if not isinstance(experiences, list):
            return []
        result: list[dict[str, Any]] = []
        for exp in experiences:
            if not isinstance(exp, dict):
                continue
            entry = dict(exp)
            if "start" in entry:
                entry["start"] = NormalizationEngine._parse_date(entry["start"])
            if "end" in entry:
                entry["end"] = NormalizationEngine._parse_date(entry["end"])
            result.append(entry)
        return result

    @staticmethod
    def _normalize_education_dates(education: Any) -> list[dict]:
        if not isinstance(education, list):
            return []
        result: list[dict[str, Any]] = []
        for edu in education:
            if not isinstance(edu, dict):
                continue
            entry = dict(edu)
            if "end_year" in entry:
                parsed = NormalizationEngine._parse_date(entry["end_year"])
                if parsed:
                    entry["end_year"] = parsed
            result.append(entry)
        return result
