import json
import re
from pathlib import Path
from typing import Any

# Re-export the structured parser
from parse_ats_json import parse_ats_json  # noqa: F401


def parse_unstructured_text(text: str, source: str, candidate_id: str) -> dict:
    """Core text-parsing logic shared by TXT notes and resume files."""
    profile: dict[str, Any] = {}
    provenance: list[dict[str, str]] = []
    method = "direct_mapping"

    # ── candidate_id ───────────────────────────────────────────────
    profile["candidate_id"] = candidate_id
    provenance.append({"field": "candidate_id", "source": source, "method": method})

    # ── full_name (first non-empty line) ───────────────────────────
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if lines:
        profile["full_name"] = lines[0]
        provenance.append({"field": "full_name", "source": source, "method": method})

    # ── email ──────────────────────────────────────────────────────
    email_match = re.search(r"[\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,}", text)
    if email_match:
        profile["emails"] = [email_match.group(0)]
        provenance.append({"field": "emails", "source": source, "method": method})

    # ── phone ──────────────────────────────────────────────────────
    phone_match = re.search(r"\+?\d[\d\s.\-()]{7,}\d", text)
    if phone_match:
        candidate = phone_match.group(0).strip()
        digit_count = sum(c.isdigit() for c in candidate)
        # Reject if it looks like a date range or calendar date
        if (
            7 <= digit_count <= 15
            and not re.search(r"\d{4}[-–]\d{2}[-–]\d{2}|\d{4}[-–]\d{2}", candidate)
        ):
            profile["phones"] = [candidate]
            provenance.append({"field": "phones", "source": source, "method": method})

    # ── years_experience ──────────────────────────────────────────
    exp_match = re.search(r"(\d+)\+?\s*years?", text, re.IGNORECASE)
    if exp_match:
        profile["years_experience"] = float(exp_match.group(1))
        provenance.append({"field": "years_experience", "source": source, "method": method})

    # ── skills (bulleted / comma-separated lines) ──────────────────
    skill_keywords = [
        "python", "java", "javascript", "typescript", "c++", "go", "rust",
        "react", "angular", "vue", "node", "aws", "gcp", "azure",
        "docker", "kubernetes", "sql", "nosql", "mongodb", "postgresql",
        "git", "ci/cd", "machine learning", "data engineering",
    ]
    skills: list[dict[str, Any]] = []
    seen_skills: set[str] = set()
    lower = text.lower()
    for kw in skill_keywords:
        if kw in lower and kw not in seen_skills:
            seen_skills.add(kw)
            skills.append({"name": kw, "confidence": 0.5, "sources": [source]})
    if skills:
        profile["skills"] = skills
        provenance.append({"field": "skills", "source": source, "method": method})

    # ── headline ───────────────────────────────────────────────────
    if lines and len(lines) > 1:
        candidate = lines[1]
        if "@" not in candidate and len(candidate) < 120:
            profile["headline"] = candidate
            provenance.append({"field": "headline", "source": source, "method": method})

    # ── experience lines ───────────────────────────────────────────
    experiences: list[dict[str, Any]] = []
    for line in lines[2:]:
        m = re.match(
            r"(.+?)\s+at\s+(.+?)(?:\s+\((\d{4}-\d{2})\s*[-–]\s*(\d{4}-\d{2}|present)\))?\s*$",
            line,
            re.IGNORECASE,
        )
        if m:
            entry: dict[str, Any] = {
                "title": m.group(1).strip(),
                "company": m.group(2).strip(),
            }
            if m.group(3):
                entry["start"] = m.group(3)
            if m.group(4) and m.group(4).lower() != "present":
                entry["end"] = m.group(4)
            experiences.append(entry)
    if experiences:
        profile["experience"] = experiences
        provenance.append({"field": "experience", "source": source, "method": method})

    # ── field-level confidence ─────────────────────────────────────
    # Formula: field_confidence = max(0, source_authority − 0.10 × malformed_attributes)
    source_authority = 0.50
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

    # ── provenance ─────────────────────────────────────────────────
    profile["provenance"] = provenance

    return profile


def parse_unstructured_notes(filepath: str) -> dict:
    """Parse a free-form TXT candidate note into a CanonicalProfile-compatible dict."""
    text = Path(filepath).read_text(encoding="utf-8")
    return parse_unstructured_text(text, "unstructured_notes", Path(filepath).stem)
