"""Test suite for the Multi-Source Candidate Data Transformer pipeline."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parse_ats_json import parse_ats_json
from ingestion import parse_unstructured_text, parse_unstructured_notes
from normalization_engine import NormalizationEngine
from merge_engine import MergeEngine, UnionFind
from projection import project_profile, validate_projected_output, ConfigurationError, OutputValidationError
from models import CanonicalProfile


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def sample_ats_data():
    return {
        "CandidateId": "c-001",
        "PersonalDetails": {"FirstName": "Alice", "LastName": "Johnson", "Headline": "Senior **SWE**"},
        "Contact": {
            "PrimaryEmail": "alice@example.com",
            "Phone": "+15551234567",
            "LinkedIn": "https://linkedin.com/in/alice",
        },
        "Location": {"City": "San Francisco", "Region": "CA", "Country": "United States"},
        "Tags": [
            {"Name": "Python", "Confidence": 0.95, "Sources": ["ats_json"]},
            {"Name": "AWS", "Confidence": 0.90, "Sources": ["ats_json"]},
        ],
        "WorkHistory": [
            {"Company": "TechCorp", "Title": "Senior SWE", "StartDate": "2021-03", "EndDate": "2025-06"},
            {"Company": "StartupXYZ", "Title": "SWE", "StartDate": "2018-06", "EndDate": "2021-02"},
        ],
        "Education": [{"Institution": "Stanford", "Degree": "M.S.", "Field": "CS", "EndYear": "2018"}],
        "YearsExperience": 7.0,
    }


@pytest.fixture
def sample_unstructured_text():
    return (
        "Alice Johnson\n"
        "Senior Software Engineer\n"
        "alice@example.com | +1-555-123-4567\n"
        "Senior SWE at TechCorp (2021-03 – 2025-06)\n"
        "SWE at StartupXYZ (2018-06 – 2021-02)\n"
        "Skills: Python, AWS, Docker, Kubernetes\n"
        "7+ years experience.\n"
    )


# ═══════════════════════════════════════════════════════════════════
# 1. PARSING TESTS
# ═══════════════════════════════════════════════════════════════════

class TestATSParser:
    def test_basic_fields(self, sample_ats_data, tmp_path):
        fp = tmp_path / "candidate.json"
        fp.write_text(json.dumps(sample_ats_data))
        result = parse_ats_json(str(fp))

        assert result["candidate_id"] == "c-001"
        assert result["full_name"] == "Alice Johnson"
        assert result["emails"] == ["alice@example.com"]
        assert result["phones"] == ["+15551234567"]
        assert result["headline"] == "Senior **SWE**"

    def test_skills_extraction(self, sample_ats_data, tmp_path):
        fp = tmp_path / "candidate.json"
        fp.write_text(json.dumps(sample_ats_data))
        result = parse_ats_json(str(fp))

        assert len(result["skills"]) == 2
        assert result["skills"][0]["name"] == "Python"
        assert result["skills"][0]["confidence"] == 0.95

    def test_experience_extraction(self, sample_ats_data, tmp_path):
        fp = tmp_path / "candidate.json"
        fp.write_text(json.dumps(sample_ats_data))
        result = parse_ats_json(str(fp))

        assert len(result["experience"]) == 2
        assert result["experience"][0]["company"] == "TechCorp"
        assert result["experience"][0]["start"] == "2021-03"

    def test_confidence_full_record(self, sample_ats_data, tmp_path):
        fp = tmp_path / "candidate.json"
        fp.write_text(json.dumps(sample_ats_data))
        result = parse_ats_json(str(fp))
        assert result["overall_confidence"] == 0.95

    def test_confidence_missing_email(self, sample_ats_data, tmp_path):
        del sample_ats_data["Contact"]["PrimaryEmail"]
        fp = tmp_path / "candidate.json"
        fp.write_text(json.dumps(sample_ats_data))
        result = parse_ats_json(str(fp))
        assert result["overall_confidence"] == 0.85  # 0.95 - 0.10

    def test_provenance_tracking(self, sample_ats_data, tmp_path):
        fp = tmp_path / "candidate.json"
        fp.write_text(json.dumps(sample_ats_data))
        result = parse_ats_json(str(fp))

        sources = {p["field"] for p in result["provenance"]}
        assert "candidate_id" in sources
        assert "full_name" in sources
        assert "emails" in sources

    def test_empty_json(self, tmp_path):
        fp = tmp_path / "empty.json"
        fp.write_text("{}")
        result = parse_ats_json(str(fp))
        # Empty JSON has no provenance entries → overall_confidence = 0.0
        assert result.get("overall_confidence") == 0.0

    def test_tags_as_strings(self, tmp_path):
        data = {"CandidateId": "x", "PersonalDetails": {"FirstName": "Test"},
                "Contact": {"PrimaryEmail": "t@t.com", "Phone": "+11234567890"},
                "Tags": ["Python", "Go"]}
        fp = tmp_path / "c.json"
        fp.write_text(json.dumps(data))
        result = parse_ats_json(str(fp))
        assert len(result["skills"]) == 2
        assert result["skills"][0]["name"] == "Python"


class TestUnstructuredParser:
    def test_basic_fields(self, sample_unstructured_text):
        result = parse_unstructured_text(sample_unstructured_text, "notes", "alice")
        assert result["candidate_id"] == "alice"
        assert result["full_name"] == "Alice Johnson"
        assert result["emails"] == ["alice@example.com"]

    def test_experience_extraction(self, sample_unstructured_text):
        result = parse_unstructured_text(sample_unstructured_text, "notes", "alice")
        assert len(result.get("experience", [])) >= 2

    def test_years_experience(self, sample_unstructured_text):
        result = parse_unstructured_text(sample_unstructured_text, "notes", "alice")
        assert result["years_experience"] == 7.0

    def test_skills_detection(self, sample_unstructured_text):
        result = parse_unstructured_text(sample_unstructured_text, "notes", "alice")
        skill_names = {s["name"] for s in result.get("skills", [])}
        assert "python" in skill_names
        assert "aws" in skill_names

    def test_empty_text(self):
        result = parse_unstructured_text("", "notes", "empty")
        assert result["candidate_id"] == "empty"
        assert result["overall_confidence"] <= 0.21  # 0.50 - 4*0.10 = 0.10


# ═══════════════════════════════════════════════════════════════════
# 2. NORMALIZATION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestNormalization:
    def setup_method(self):
        self.engine = NormalizationEngine()

    def test_phone_e164(self):
        raw = {"phones": ["+1 (555) 123-4567", "invalid", "5551234567"]}
        result = self.engine.transform(raw)
        assert all(p.startswith("+") for p in result["phones"])

    def test_skill_aliasing(self):
        raw = {"skills": [
            {"name": "ReactJS", "confidence": 0.8, "sources": []},
            {"name": "k8s", "confidence": 0.7, "sources": []},
            {"name": "JS", "confidence": 0.6, "sources": []},
        ]}
        result = self.engine.transform(raw)
        names = [s["name"] for s in result["skills"]]
        assert "react" in names
        assert "kubernetes" in names
        assert "javascript" in names

    def test_skill_dedup(self):
        raw = {"skills": [
            {"name": "Python", "confidence": 0.9, "sources": []},
            {"name": "python", "confidence": 0.5, "sources": []},
        ]}
        result = self.engine.transform(raw)
        assert len(result["skills"]) == 1

    def test_date_normalization(self):
        raw = {"experience": [
            {"company": "A", "title": "B", "start": "2020-01-15T00:00:00Z", "end": "2021-06"},
        ]}
        result = self.engine.transform(raw)
        assert result["experience"][0]["start"] == "2020-01"
        assert result["experience"][0]["end"] == "2021-06"

    def test_location_iso_country(self):
        raw = {"location": {"city": "Mumbai", "country": "India"}}
        result = self.engine.transform(raw)
        assert result["location"]["country"] == "IN"

    def test_location_preserves_2letter(self):
        raw = {"location": {"country": "US"}}
        result = self.engine.transform(raw)
        assert result["location"]["country"] == "US"

    def test_markdown_stripping(self):
        raw = {"headline": "**Senior** _Engineer_ at [TechCorp](http://tech.com)"}
        result = self.engine.transform(raw)
        assert "**" not in result["headline"]
        assert "_" not in result["headline"]
        assert "http" not in result["headline"]

    def test_years_experience_overlapping(self):
        raw = {"experience": [
            {"company": "A", "title": "T", "start": "2020-01", "end": "2023-01"},
            {"company": "B", "title": "T", "start": "2021-06", "end": "2022-06"},  # overlapping
        ]}
        result = self.engine.transform(raw)
        # Should be 3.0 years (2020-01 to 2023-01), NOT 4.0 (sum of both)
        assert result["years_experience"] == 3.0

    def test_years_experience_no_overlap(self):
        raw = {"experience": [
            {"company": "A", "title": "T", "start": "2020-01", "end": "2021-01"},
            {"company": "B", "title": "T", "start": "2022-01", "end": "2023-01"},
        ]}
        result = self.engine.transform(raw)
        assert result["years_experience"] == 2.0


# ═══════════════════════════════════════════════════════════════════
# 3. MERGE ENGINE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestUnionFind:
    def test_basic_union(self):
        uf = UnionFind(5)
        uf.union(0, 1)
        uf.union(2, 3)
        assert uf.find(0) == uf.find(1)
        assert uf.find(2) == uf.find(3)
        assert uf.find(0) != uf.find(2)

    def test_transitive_union(self):
        uf = UnionFind(3)
        uf.union(0, 1)
        uf.union(1, 2)
        assert uf.find(0) == uf.find(2)

    def test_groups(self):
        uf = UnionFind(4)
        uf.union(0, 1)
        uf.union(2, 3)
        groups = uf.groups()
        assert len(groups) == 2


class TestMergeEngine:
    def setup_method(self):
        self.engine = MergeEngine()

    def test_merge_by_email(self):
        records = [
            {"candidate_id": "1", "full_name": "Alice", "emails": ["alice@test.com"],
             "provenance": [{"field": "full_name", "source": "ats_json", "method": "dm"}],
             "overall_confidence": 0.95},
            {"candidate_id": "2", "full_name": "Alice J", "emails": ["alice@test.com"],
             "provenance": [{"field": "full_name", "source": "resume_pdf", "method": "dm"}],
             "overall_confidence": 0.50},
        ]
        merged = self.engine.merge(records)
        assert len(merged) == 1
        assert merged[0]["full_name"] == "Alice"  # ATS wins (higher authority)

    def test_no_merge_different_emails(self):
        records = [
            {"candidate_id": "1", "full_name": "Alice", "emails": ["a@test.com"],
             "provenance": [], "overall_confidence": 0.95},
            {"candidate_id": "2", "full_name": "Bob", "emails": ["b@test.com"],
             "provenance": [], "overall_confidence": 0.85},
        ]
        merged = self.engine.merge(records)
        assert len(merged) == 2

    def test_merge_by_phone(self):
        records = [
            {"candidate_id": "1", "full_name": "Alice", "phones": ["+15551234567"],
             "provenance": [{"field": "full_name", "source": "ats_json", "method": "dm"}],
             "overall_confidence": 0.95},
            {"candidate_id": "2", "full_name": "Alice Johnson", "phones": ["+15551234567"],
             "provenance": [{"field": "full_name", "source": "resume_pdf", "method": "dm"}],
             "overall_confidence": 0.50},
        ]
        merged = self.engine.merge(records)
        assert len(merged) == 1

    def test_skill_dedup_across_sources(self):
        records = [
            {"emails": ["shared@test.com"],
             "skills": [{"name": "python", "confidence": 0.95, "sources": ["ats"]}],
             "provenance": [], "overall_confidence": 0.95},
            {"emails": ["shared@test.com"],
             "skills": [{"name": "python", "confidence": 0.50, "sources": ["resume"]}],
             "provenance": [], "overall_confidence": 0.50},
        ]
        merged = self.engine.merge(records)
        assert len(merged) == 1  # merged by shared email
        skills = merged[0].get("skills", [])
        python_skills = [s for s in skills if s["name"] == "python"]
        assert len(python_skills) == 1
        assert python_skills[0]["confidence"] == 0.95
        assert "ats" in python_skills[0]["sources"]
        assert "resume" in python_skills[0]["sources"]

    def test_recency_tiebreaker(self):
        """When two sources have equal authority, the one with the more recent experience.end wins."""
        records = [
            {"full_name": "Alice Old", "headline": "Old Title",
             "emails": ["alice@test.com"],
             "experience": [{"company": "A", "title": "T", "end": "2020-01"}],
             "provenance": [
                 {"field": "full_name", "source": "ats_json", "method": "dm"},
                 {"field": "headline", "source": "ats_json", "method": "dm"},
             ],
             "overall_confidence": 0.95},
            {"full_name": "Alice New", "headline": "New Title",
             "emails": ["alice@test.com"],
             "experience": [{"company": "B", "title": "T", "end": "2025-06"}],
             "provenance": [
                 {"field": "full_name", "source": "ats_json", "method": "dm"},
                 {"field": "headline", "source": "ats_json", "method": "dm"},
             ],
             "overall_confidence": 0.95},
        ]
        merged = self.engine.merge(records)
        assert len(merged) == 1  # merged by shared email
        assert merged[0]["headline"] == "New Title"  # More recent wins

    def test_confidence_from_provenance(self):
        """After merge, overall_confidence is the mean of max per-field confidences."""
        records = [
            {"emails": ["shared@test.com"],
             "provenance": [
                 {"field": "full_name", "source": "ats_json", "method": "dm", "confidence": 0.95},
                 {"field": "emails", "source": "ats_json", "method": "dm", "confidence": 0.95},
             ],
             "overall_confidence": 0.95},
            {"emails": ["shared@test.com"],
             "provenance": [
                 {"field": "full_name", "source": "resume_pdf", "method": "regex", "confidence": 0.50},
                 {"field": "skills", "source": "resume_pdf", "method": "regex", "confidence": 0.50},
             ],
             "overall_confidence": 0.50},
        ]
        merged = self.engine.merge(records)
        assert len(merged) == 1
        # field_best: full_name=0.95 (ats wins), emails=0.95, skills=0.50
        # mean = (0.95 + 0.95 + 0.50) / 3 = 0.8
        assert merged[0]["overall_confidence"] == 0.8


# ═══════════════════════════════════════════════════════════════════
# 4. PROJECTION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestProjection:
    def test_basic_remapping(self):
        record = {"full_name": "Alice", "emails": ["a@b.com"]}
        config = {"fields": [
            {"path": "name", "from": "full_name"},
            {"path": "email", "from": "emails[0]"},
        ]}
        result = project_profile(record, config)
        assert result["name"] == "Alice"
        assert result["email"] == "a@b.com"

    def test_on_missing_null(self):
        config = {"fields": [{"path": "phone", "from": "phones[0]", "on_missing": "null"}]}
        result = project_profile({"phones": []}, config)
        assert result["phone"] is None

    def test_on_missing_omit(self):
        config = {"fields": [{"path": "phone", "from": "phones[0]", "on_missing": "omit"}]}
        result = project_profile({"phones": []}, config)
        assert "phone" not in result

    def test_on_missing_error(self):
        config = {"fields": [{"path": "phone", "from": "phones[0]", "on_missing": "error"}]}
        with pytest.raises(ConfigurationError):
            project_profile({"phones": []}, config)

    def test_invalid_path_raises(self):
        config = {"fields": [{"path": "x", "from": "nonexistent_field"}]}
        with pytest.raises(ConfigurationError, match="does not exist"):
            project_profile({}, config)

    def test_nested_path(self):
        record = {"location": {"city": "SF", "country": "US"}}
        config = {"fields": [{"path": "city", "from": "location.city"}]}
        result = project_profile(record, config)
        assert result["city"] == "SF"

    def test_duplicate_output_key_raises(self):
        config = {"fields": [
            {"path": "name", "from": "full_name"},
            {"path": "name", "from": "headline"},
        ]}
        with pytest.raises(ConfigurationError, match="Duplicate output key"):
            project_profile({}, config)

    def test_array_index_path(self):
        record = {"skills": [{"name": "Python", "confidence": 0.9, "sources": []}]}
        config = {"fields": [{"path": "top_skill", "from": "skills[0].name"}]}
        result = project_profile(record, config)
        assert result["top_skill"] == "Python"


# ═══════════════════════════════════════════════════════════════════
# 5. SCHEMA VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestSchema:
    def test_valid_profile(self):
        data = {
            "candidate_id": "c-001",
            "full_name": "Alice Johnson",
            "emails": ["alice@test.com"],
            "phones": ["+15551234567"],
            "overall_confidence": 0.95,
        }
        profile = CanonicalProfile.model_validate(data)
        assert profile.candidate_id == "c-001"
        assert profile.full_name == "Alice Johnson"

    def test_missing_required_field(self):
        data = {"candidate_id": "c-001"}  # missing full_name
        with pytest.raises(Exception):
            CanonicalProfile.model_validate(data)

    def test_default_lists(self):
        data = {"candidate_id": "c-001", "full_name": "Alice"}
        profile = CanonicalProfile.model_validate(data)
        assert profile.emails == []
        assert profile.skills == []
        assert profile.experience == []


# ═══════════════════════════════════════════════════════════════════
# 6. END-TO-END PIPELINE TEST
# ═══════════════════════════════════════════════════════════════════

class TestEndToEnd:
    def test_full_pipeline_ats_json(self, sample_ats_data, tmp_path):
        """Full pipeline: parse ATS JSON → normalize → merge → validate → project."""
        # Write sample ATS JSON
        fp = tmp_path / "candidate.json"
        fp.write_text(json.dumps(sample_ats_data))

        # 1. Parse
        record = parse_ats_json(str(fp))
        assert record["candidate_id"] == "c-001"

        # 2. Normalize
        engine = NormalizationEngine()
        normalized = engine.transform(record)
        assert normalized["location"]["country"] == "US"

        # 3. Merge (single record — no merge needed)
        merger = MergeEngine()
        merged = merger.merge([normalized])
        assert len(merged) == 1

        # 4. Validate
        profile = CanonicalProfile.model_validate(merged[0])
        validated = profile.model_dump()

        # 5. Project
        config = {"fields": [
            {"path": "name", "from": "full_name"},
            {"path": "email", "from": "emails[0]"},
            {"path": "confidence", "from": "overall_confidence"},
        ]}
        result = project_profile(validated, config)
        assert result["name"] == "Alice Johnson"
        assert result["email"] == "alice@example.com"
        assert isinstance(result["confidence"], float)

    def test_multi_source_merge(self, sample_ats_data, sample_unstructured_text, tmp_path):
        """ATS JSON + unstructured notes for the same person merge into one profile."""
        # Parse ATS
        fp = tmp_path / "candidate.json"
        fp.write_text(json.dumps(sample_ats_data))
        ats_record = parse_ats_json(str(fp))

        # Parse unstructured
        notes_record = parse_unstructured_text(sample_unstructured_text, "resume_pdf", "alice")

        # Normalize both
        engine = NormalizationEngine()
        norm_ats = engine.transform(ats_record)
        norm_notes = engine.transform(notes_record)

        # Merge — should combine into one (shared email)
        merger = MergeEngine()
        merged = merger.merge([norm_ats, norm_notes])
        assert len(merged) == 1

        # Validate
        profile = CanonicalProfile.model_validate(merged[0])
        validated = profile.model_dump()

        # ATS should win for headline (higher authority)
        assert "SWE" in validated["headline"]


# ═══════════════════════════════════════════════════════════════════
# 7. POST-PROJECTION VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestPostProjectionValidation:
    def test_valid_output_passes(self):
        output = {"name": "Alice", "email": "alice@test.com", "age": 30}
        config = {"fields": [
            {"path": "name", "from": "full_name", "type": "string"},
            {"path": "email", "from": "emails[0]", "type": "string"},
            {"path": "age", "from": "years_experience", "type": "number"},
        ]}
        validate_projected_output(output, config)  # should not raise

    def test_required_field_missing_raises(self):
        output = {}
        config = {"fields": [
            {"path": "name", "from": "full_name", "required": True},
        ]}
        with pytest.raises(OutputValidationError, match="Required field 'name'"):
            validate_projected_output(output, config)

    def test_required_field_null_raises(self):
        output = {"name": None}
        config = {"fields": [
            {"path": "name", "from": "full_name", "required": True},
        ]}
        with pytest.raises(OutputValidationError, match="present but null"):
            validate_projected_output(output, config)

    def test_required_omit_does_not_raise(self):
        """If on_missing is 'omit', absence is expected for required fields."""
        output = {}
        config = {"fields": [
            {"path": "phone", "from": "phones[0]", "required": True, "on_missing": "omit"},
        ]}
        validate_projected_output(output, config)  # should not raise

    def test_type_mismatch_raises(self):
        output = {"age": "thirty"}
        config = {"fields": [
            {"path": "age", "from": "years_experience", "type": "number"},
        ]}
        with pytest.raises(OutputValidationError, match="expected type 'number'"):
            validate_projected_output(output, config)

    def test_type_array_passes(self):
        output = {"skills": [{"name": "python"}]}
        config = {"fields": [
            {"path": "skills", "from": "skills", "type": "array"},
        ]}
        validate_projected_output(output, config)  # should not raise

    def test_multiple_errors_collected(self):
        output = {"name": 42}  # wrong type, missing required "email"
        config = {"fields": [
            {"path": "name", "from": "full_name", "type": "string"},
            {"path": "email", "from": "emails[0]", "required": True},
        ]}
        with pytest.raises(OutputValidationError, match="2 error"):
            validate_projected_output(output, config)


# ═══════════════════════════════════════════════════════════════════
# 8. FIELD-LEVEL CONFIDENCE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestFieldLevelConfidence:
    def test_provenance_carries_confidence(self, sample_ats_data, tmp_path):
        fp = tmp_path / "candidate.json"
        fp.write_text(json.dumps(sample_ats_data))
        result = parse_ats_json(str(fp))

        for prov in result["provenance"]:
            assert "confidence" in prov
            assert prov["confidence"] == 0.95  # all critical fields present

    def test_malformed_reduces_field_confidence(self, tmp_path):
        data = {"PersonalDetails": {"FirstName": "Test"},
                "Contact": {"PrimaryEmail": "t@t.com"}}
        # Missing: candidate_id, phones → malformed_count = 2
        # field_confidence = max(0, 0.95 - 0.10*2) = 0.75
        fp = tmp_path / "c.json"
        fp.write_text(json.dumps(data))
        result = parse_ats_json(str(fp))

        for prov in result["provenance"]:
            assert prov["confidence"] == 0.75

    def test_overall_is_mean_of_field_confidences(self, sample_ats_data, tmp_path):
        fp = tmp_path / "candidate.json"
        fp.write_text(json.dumps(sample_ats_data))
        result = parse_ats_json(str(fp))

        # All fields have same confidence (0.95), so mean = 0.95
        assert result["overall_confidence"] == 0.95
