import json
from typing import Any


def parse_ats_json(json_filepath: str) -> dict:
    """Read a proprietary ATS JSON file and map it to a CanonicalProfile-compatible dict."""
    with open(json_filepath, "r") as f:
        data: dict[str, Any] = json.load(f)

    profile: dict[str, Any] = {}
    provenance: list[dict[str, str]] = []

    # ── candidate_id ────────────────────────────────────────────────
    if cid := data.get("CandidateId"):
        profile["candidate_id"] = cid
        provenance.append({"field": "candidate_id", "source": "ats_json", "method": "direct_mapping"})

    # ── full_name (PersonalDetails.FirstName + LastName) ────────────
    pd = data.get("PersonalDetails", {})
    first = pd.get("FirstName")
    last = pd.get("LastName")
    parts = [p for p in (first, last) if p]
    if parts:
        profile["full_name"] = " ".join(parts)
        provenance.append({"field": "full_name", "source": "ats_json", "method": "direct_mapping"})

    # ── emails (Contact.PrimaryEmail → list) ────────────────────────
    contact = data.get("Contact", {})
    if email := contact.get("PrimaryEmail"):
        profile["emails"] = [email]
        provenance.append({"field": "emails", "source": "ats_json", "method": "direct_mapping"})

    # ── phones (Contact.Phone → list) ───────────────────────────────
    if phone := contact.get("Phone"):
        profile["phones"] = [phone]
        provenance.append({"field": "phones", "source": "ats_json", "method": "direct_mapping"})

    # ── location ────────────────────────────────────────────────────
    loc = data.get("Location")
    if loc:
        loc_out: dict[str, str] = {}
        if loc.get("City"):
            loc_out["city"] = loc["City"]
        if loc.get("Region"):
            loc_out["region"] = loc["Region"]
        if loc.get("Country"):
            loc_out["country"] = loc["Country"]
        if loc_out:
            profile["location"] = loc_out
            provenance.append({"field": "location", "source": "ats_json", "method": "direct_mapping"})

    # ── links ───────────────────────────────────────────────────────
    links: dict[str, Any] = {}
    if contact.get("LinkedIn"):
        links["linkedin"] = contact["LinkedIn"]
    if contact.get("Github"):
        links["github"] = contact["Github"]
    if contact.get("Portfolio"):
        links["portfolio"] = contact["Portfolio"]
    other_links = contact.get("OtherLinks", [])
    if other_links:
        links["other"] = other_links if isinstance(other_links, list) else [other_links]
    if links:
        profile["links"] = links
        provenance.append({"field": "links", "source": "ats_json", "method": "direct_mapping"})

    # ── headline ────────────────────────────────────────────────────
    if headline := pd.get("Headline"):
        profile["headline"] = headline
        provenance.append({"field": "headline", "source": "ats_json", "method": "direct_mapping"})

    # ── years_experience ────────────────────────────────────────────
    if (ye := data.get("YearsExperience")) is not None:
        profile["years_experience"] = float(ye)
        provenance.append({"field": "years_experience", "source": "ats_json", "method": "direct_mapping"})

    # ── skills (Tags array) ─────────────────────────────────────────
    tags = data.get("Tags", [])
    skills_out: list[dict[str, Any]] = []
    for tag in tags:
        if isinstance(tag, dict):
            if name := tag.get("Name"):
                skills_out.append({
                    "name": name,
                    "confidence": tag.get("Confidence", 0.0),
                    "sources": tag.get("Sources", []),
                })
        elif isinstance(tag, str):
            skills_out.append({"name": tag, "confidence": 0.0, "sources": []})
    if skills_out:
        profile["skills"] = skills_out
        provenance.append({"field": "skills", "source": "ats_json", "method": "direct_mapping"})

    # ── experience (WorkHistory array) ──────────────────────────────
    work_history = data.get("WorkHistory", [])
    exp_out: list[dict[str, Any]] = []
    for wh in work_history:
        entry: dict[str, Any] = {
            "company": wh.get("Company", ""),
            "title": wh.get("Title", ""),
        }
        if wh.get("StartDate"):
            entry["start"] = wh["StartDate"]
        if wh.get("EndDate"):
            entry["end"] = wh["EndDate"]
        if wh.get("Summary"):
            entry["summary"] = wh["Summary"]
        exp_out.append(entry)
    if exp_out:
        profile["experience"] = exp_out
        provenance.append({"field": "experience", "source": "ats_json", "method": "direct_mapping"})

    # ── education (Education array) ─────────────────────────────────
    edu_data = data.get("Education", [])
    edu_out: list[dict[str, Any]] = []
    for edu in edu_data:
        entry: dict[str, Any] = {
            "institution": edu.get("Institution", ""),
        }
        if edu.get("Degree"):
            entry["degree"] = edu["Degree"]
        if edu.get("Field"):
            entry["field"] = edu["Field"]
        if edu.get("EndYear"):
            entry["end_year"] = edu["EndYear"]
        edu_out.append(entry)
    if edu_out:
        profile["education"] = edu_out
        provenance.append({"field": "education", "source": "ats_json", "method": "direct_mapping"})

    # ── confidence ──────────────────────────────────────────────────
    confidence = 0.95
    if not profile.get("candidate_id"):
        confidence -= 0.10
    if not profile.get("full_name"):
        confidence -= 0.10
    if not profile.get("emails"):
        confidence -= 0.10
    profile["overall_confidence"] = max(confidence, 0.0)

    # ── provenance ──────────────────────────────────────────────────
    if provenance:
        profile["provenance"] = provenance

    return profile
