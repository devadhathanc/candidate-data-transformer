"""Recruiter CSV parser — maps recruiter-exported CSV rows to CanonicalProfile-compatible dicts.

Expected CSV columns (case-insensitive, underscores and spaces interchangeable):
    CandidateId, FirstName, LastName, Email, Phone, Headline,
    City, Region, Country, LinkedIn, Github, Portfolio,
    Skills (semicolon-separated), Company, Title, StartDate, EndDate,
    Institution, Degree, Field, EndYear, YearsExperience
"""

import csv
import re
from pathlib import Path
from typing import Any


def _normalize_header(header: str) -> str:
    """Lowercase, strip, replace spaces with underscores for flexible matching."""
    return re.sub(r"\s+", "_", header.strip().lower())


_COLUMN_MAP: dict[str, str] = {
    "candidateid": "candidate_id",
    "candidate_id": "candidate_id",
    "firstname": "first_name",
    "first_name": "first_name",
    "lastname": "last_name",
    "last_name": "last_name",
    "email": "email",
    "phone": "phone",
    "headline": "headline",
    "city": "city",
    "region": "region",
    "country": "country",
    "linkedin": "linkedin",
    "github": "github",
    "portfolio": "portfolio",
    "skills": "skills",
    "company": "company",
    "title": "title",
    "startdate": "start_date",
    "start_date": "start_date",
    "enddate": "end_date",
    "end_date": "end_date",
    "institution": "institution",
    "degree": "degree",
    "field": "field",
    "endyear": "end_year",
    "end_year": "end_year",
    "yearsexperience": "years_experience",
    "years_experience": "years_experience",
}


def _map_row(row: dict[str, str]) -> dict[str, str]:
    """Map raw CSV column names to canonical keys."""
    mapped: dict[str, str] = {}
    for raw_key, value in row.items():
        norm = _normalize_header(raw_key)
        canon = _COLUMN_MAP.get(norm)
        if canon and value and value.strip():
            mapped[canon] = value.strip()
    return mapped


def parse_recruiter_csv(filepath: str) -> list[dict]:
    """Parse a recruiter CSV file and return a list of CanonicalProfile-compatible dicts.

    Each row in the CSV becomes one candidate record. Returns an empty list
    if the file is empty or unreadable.
    """
    path = Path(filepath)
    source = "recruiter_csv"
    method = "direct_mapping"

    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return []
            rows = list(reader)
    except (FileNotFoundError, UnicodeDecodeError, csv.Error):
        return []

    results: list[dict] = []

    for row in rows:
        mapped = _map_row(row)
        if not mapped:
            continue

        profile: dict[str, Any] = {}
        provenance: list[dict[str, str]] = []

        # ── candidate_id ──────────────────────────────────────────
        if cid := mapped.get("candidate_id"):
            profile["candidate_id"] = cid
            provenance.append({"field": "candidate_id", "source": source, "method": method})
        else:
            # Fallback: use filename stem + row index
            profile["candidate_id"] = f"{path.stem}_{len(results)}"
            provenance.append({"field": "candidate_id", "source": source, "method": "generated"})

        # ── full_name ─────────────────────────────────────────────
        first = mapped.get("first_name", "")
        last = mapped.get("last_name", "")
        name_parts = [p for p in (first, last) if p]
        if name_parts:
            profile["full_name"] = " ".join(name_parts)
            provenance.append({"field": "full_name", "source": source, "method": method})

        # ── emails ────────────────────────────────────────────────
        if email := mapped.get("email"):
            profile["emails"] = [email]
            provenance.append({"field": "emails", "source": source, "method": method})

        # ── phones ────────────────────────────────────────────────
        if phone := mapped.get("phone"):
            profile["phones"] = [phone]
            provenance.append({"field": "phones", "source": source, "method": method})

        # ── headline ──────────────────────────────────────────────
        if headline := mapped.get("headline"):
            profile["headline"] = headline
            provenance.append({"field": "headline", "source": source, "method": method})

        # ── location ──────────────────────────────────────────────
        loc: dict[str, str] = {}
        if mapped.get("city"):
            loc["city"] = mapped["city"]
        if mapped.get("region"):
            loc["region"] = mapped["region"]
        if mapped.get("country"):
            loc["country"] = mapped["country"]
        if loc:
            profile["location"] = loc
            provenance.append({"field": "location", "source": source, "method": method})

        # ── links ─────────────────────────────────────────────────
        links: dict[str, Any] = {}
        if mapped.get("linkedin"):
            links["linkedin"] = mapped["linkedin"]
        if mapped.get("github"):
            links["github"] = mapped["github"]
        if mapped.get("portfolio"):
            links["portfolio"] = mapped["portfolio"]
        if links:
            profile["links"] = links
            provenance.append({"field": "links", "source": source, "method": method})

        # ── skills (semicolon-separated) ──────────────────────────
        if skills_raw := mapped.get("skills"):
            skill_names = [s.strip() for s in skills_raw.split(";") if s.strip()]
            if skill_names:
                profile["skills"] = [
                    {"name": s, "confidence": 0.85, "sources": [source]}
                    for s in skill_names
                ]
                provenance.append({"field": "skills", "source": source, "method": method})

        # ── experience (single entry per row) ─────────────────────
        company = mapped.get("company")
        title = mapped.get("title")
        if company and title:
            entry: dict[str, Any] = {"company": company, "title": title}
            if mapped.get("start_date"):
                entry["start"] = mapped["start_date"]
            if mapped.get("end_date"):
                entry["end"] = mapped["end_date"]
            profile["experience"] = [entry]
            provenance.append({"field": "experience", "source": source, "method": method})

        # ── education (single entry per row) ──────────────────────
        institution = mapped.get("institution")
        if institution:
            edu_entry: dict[str, Any] = {"institution": institution}
            if mapped.get("degree"):
                edu_entry["degree"] = mapped["degree"]
            if mapped.get("field"):
                edu_entry["field"] = mapped["field"]
            if mapped.get("end_year"):
                edu_entry["end_year"] = mapped["end_year"]
            profile["education"] = [edu_entry]
            provenance.append({"field": "education", "source": source, "method": method})

        # ── years_experience ──────────────────────────────────────
        if ye := mapped.get("years_experience"):
            try:
                profile["years_experience"] = float(ye)
                provenance.append({"field": "years_experience", "source": source, "method": method})
            except ValueError:
                pass

        # ── field-level confidence ────────────────────────────────
        # Formula: field_confidence = max(0, source_authority − 0.10 × malformed_attributes)
        source_authority = 0.85
        malformed_count = sum([
            not profile.get("candidate_id"),
            not profile.get("full_name"),
            not profile.get("emails"),
            not profile.get("phones"),
        ])
        field_confidence = max(0.0, source_authority - 0.10 * malformed_count)

        for prov in provenance:
            prov["confidence"] = round(field_confidence, 4)

        # overall_confidence = mean of populated field confidences
        if provenance:
            profile["overall_confidence"] = round(
                sum(p["confidence"] for p in provenance) / len(provenance), 4
            )
        else:
            profile["overall_confidence"] = 0.0

        # ── provenance ────────────────────────────────────────────
        profile["provenance"] = provenance

        results.append(profile)

    return results
