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
        result["experience"] = self._strip_experience_markdown(result.get("experience", []))
        result["education"] = self._normalize_education_dates(result.get("education", []))
        result["location"] = self._normalize_location(result.get("location"))
        # Strip markdown from headline
        if isinstance(result.get("headline"), str):
            result["headline"] = self._strip_markdown(result["headline"])
        # Compute years_experience from merged overlapping intervals
        computed_ye = self._compute_years_experience(result.get("experience", []))
        if computed_ye is not None:
            result["years_experience"] = computed_ye
        return result

    # ------------------------------------------------------------------
    # Markdown / escaped character stripping
    # ------------------------------------------------------------------
    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Remove common markdown syntax and escaped characters from text."""
        if not text:
            return text
        # Remove markdown bold/italic markers
        text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
        text = re.sub(r"_{1,3}(.+?)_{1,3}", r"\1", text)
        # Remove markdown headings
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Remove markdown links [text](url) → text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # Remove inline code backticks
        text = re.sub(r"`([^`]+)`", r"\1", text)
        # Remove common escape sequences
        text = text.replace("\\n", " ").replace("\\t", " ").replace("\\r", "")
        text = re.sub(r"\\([*_~`#])", r"\1", text)
        # Collapse multiple spaces
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _strip_experience_markdown(experiences: list[dict]) -> list[dict]:
        """Strip markdown from experience title and summary fields."""
        result: list[dict] = []
        for exp in experiences:
            if not isinstance(exp, dict):
                continue
            entry = dict(exp)
            if isinstance(entry.get("title"), str):
                entry["title"] = NormalizationEngine._strip_markdown(entry["title"])
            if isinstance(entry.get("summary"), str):
                entry["summary"] = NormalizationEngine._strip_markdown(entry["summary"])
            result.append(entry)
        return result

    # ------------------------------------------------------------------
    # Location — ISO-3166 alpha-2 country codes
    # ------------------------------------------------------------------
    _COUNTRY_MAP: dict[str, str] = {
        "united states": "US", "usa": "US", "u.s.a.": "US", "u.s.": "US",
        "united kingdom": "GB", "uk": "GB", "great britain": "GB",
        "india": "IN", "canada": "CA", "australia": "AU",
        "germany": "DE", "france": "FR", "japan": "JP",
        "china": "CN", "brazil": "BR", "mexico": "MX",
        "south korea": "KR", "korea": "KR",
        "spain": "ES", "italy": "IT", "netherlands": "NL",
        "sweden": "SE", "norway": "NO", "denmark": "DK",
        "finland": "FI", "switzerland": "CH", "austria": "AT",
        "ireland": "IE", "new zealand": "NZ", "singapore": "SG",
        "israel": "IL", "poland": "PL", "belgium": "BE",
        "portugal": "PT", "russia": "RU", "south africa": "ZA",
        "argentina": "AR", "chile": "CL", "colombia": "CO",
        "indonesia": "ID", "malaysia": "MY", "philippines": "PH",
        "thailand": "TH", "vietnam": "VN", "egypt": "EG",
        "nigeria": "NG", "kenya": "KE", "uae": "AE",
        "united arab emirates": "AE", "saudi arabia": "SA",
        "taiwan": "TW", "hong kong": "HK", "pakistan": "PK",
        "bangladesh": "BD", "sri lanka": "LK", "nepal": "NP",
    }

    def _normalize_location(self, location: Any) -> Any:
        if not isinstance(location, dict):
            return location
        result = dict(location)
        country = result.get("country")
        if isinstance(country, str):
            # If already a 2-letter code, keep it
            if len(country.strip()) == 2 and country.strip().isalpha():
                result["country"] = country.strip().upper()
            else:
                mapped = self._COUNTRY_MAP.get(country.strip().lower())
                if mapped:
                    result["country"] = mapped
        return result

    # ------------------------------------------------------------------
    # years_experience — merge overlapping date intervals
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_years_experience(experiences: list[dict]) -> Optional[float]:
        """Compute years of experience by merging overlapping date intervals.

        Parses start/end dates from experience entries, merges overlapping or
        adjacent intervals into union ranges (to avoid double-counting concurrent
        roles), then sums total duration. Returns None if no valid intervals found.
        """
        intervals: list[tuple[int, int]] = []  # (start_month, end_month) as absolute months

        for exp in experiences:
            start = exp.get("start")
            end = exp.get("end")
            if not isinstance(start, str) or not start:
                continue

            start_months = NormalizationEngine._date_to_months(start)
            if start_months is None:
                continue

            if isinstance(end, str) and end:
                end_months = NormalizationEngine._date_to_months(end)
            else:
                # "present" or missing end — use current date
                end_months = None

            if end_months is None:
                # Use a large value representing "now" (~2026-06)
                from datetime import datetime as _dt
                now = _dt.now()
                end_months = now.year * 12 + now.month

            if end_months >= start_months:
                intervals.append((start_months, end_months))

        if not intervals:
            return None

        # Sort by start, then merge overlapping
        intervals.sort()
        merged: list[tuple[int, int]] = [intervals[0]]
        for start, end in intervals[1:]:
            prev_start, prev_end = merged[-1]
            if start <= prev_end:  # overlapping or adjacent
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))

        # Sum total months across merged ranges
        total_months = sum(end - start for start, end in merged)
        return round(total_months / 12.0, 1)

    @staticmethod
    def _date_to_months(date_str: str) -> Optional[int]:
        """Convert a YYYY-MM or YYYY string to absolute months since epoch."""
        import re as _re
        m = _re.match(r"^(\d{4})-(\d{2})$", date_str.strip())
        if m:
            return int(m.group(1)) * 12 + int(m.group(2))
        m = _re.match(r"^(\d{4})$", date_str.strip())
        if m:
            return int(m.group(1)) * 12 + 1  # January of that year
        return None

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
        """Normalize skill names (lowercase, alias, dedup) within a single source.

        Within-source deduplication uses *first-occurrence wins*: if the same
        skill name appears twice in one source record, the first entry is kept.
        This is acceptable because ambiguity within a single source is rare and
        arbitrary — the ordering has no confidence signal to differentiate.
        Cross-source deduplication (in merge_engine) uses highest-confidence wins.
        """
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
