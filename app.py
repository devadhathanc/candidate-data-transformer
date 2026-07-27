from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ingestion import parse_ats_json, parse_unstructured_notes
from normalization import NormalizationEngine
from merging import MergeEngine
from projection import (
    project_profile,
    validate_projected_output,
    ConfigurationError,
    OutputValidationError,
)
from models import CanonicalProfile
from resume_parser import parse_resume_file
from csv_parser import parse_recruiter_csv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eightfold_app")

app = FastAPI(
    title="Candidate Data Transformer API",
    description="API for ingesting, normalizing, merging, and projecting multi-source candidate data.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent.resolve()
SAMPLES_DIR = BASE_DIR / "samples"
STATIC_DIR = BASE_DIR / "static"


def _get_default_config() -> dict[str, Any]:
    sample_config_path = SAMPLES_DIR / "view_config.json"
    if sample_config_path.exists():
        with open(sample_config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "fields": [
            {"path": "candidate_id", "from": "candidate_id"},
            {"path": "full_name", "from": "full_name"},
            {"path": "emails", "from": "emails", "on_missing": "null"},
            {"path": "phones", "from": "phones", "on_missing": "null"},
            {"path": "skills", "from": "skills", "on_missing": "null"},
            {"path": "work_history", "from": "work_history", "on_missing": "null"},
            {"path": "education", "from": "education", "on_missing": "null"},
            {"path": "location", "from": "location", "on_missing": "null"},
            {"path": "sources", "from": "sources", "on_missing": "null"},
        ]
    }


def parse_uploaded_file(file_path: str) -> list[dict[str, Any]]:
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".json":
        res = parse_ats_json(str(path))
        return [res] if res else []
    elif suffix == ".txt":
        res = parse_unstructured_notes(str(path))
        return [res] if res else []
    elif suffix == ".csv":
        res = parse_recruiter_csv(str(path))
        return res if isinstance(res, list) else []
    elif suffix in (".pdf", ".docx"):
        res = parse_resume_file(str(path))
        return [res] if res else []
    else:
        logger.warning("Unsupported file extension: %s", suffix)
        return []


def run_pipeline(
    raw_records: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
    if not raw_records:
        return {
            "summary": {
                "raw_records": 0,
                "canonical_profiles": 0,
                "projected_profiles": 0,
            },
            "raw_records": [],
            "canonical_profiles": [],
            "projected_profiles": [],
            "config_used": config,
        }

    # 1. Normalize
    normalizer = NormalizationEngine()
    normalized = [normalizer.transform(r) for r in raw_records if r]

    # 2. Merge
    merger = MergeEngine()
    merged = merger.merge(normalized)

    # 3. Validate against CanonicalProfile model
    validated = []
    for rec in merged:
        try:
            profile = CanonicalProfile.model_validate(rec)
            validated.append(profile.model_dump())
        except Exception as e:
            logger.warning(
                "Schema validation failed for candidate '%s': %s",
                rec.get("candidate_id", "?"),
                e,
            )

    # 4. Project
    projected = []
    for rec in validated:
        try:
            res = project_profile(rec, config)
            validate_projected_output(res, config)
            projected.append(res)
        except (ConfigurationError, OutputValidationError) as e:
            logger.error(
                "Projection failed for candidate '%s': %s",
                rec.get("candidate_id", "?"),
                e,
            )
            raise HTTPException(
                status_code=400, detail=f"Projection error for profile: {e}"
            )

    return {
        "summary": {
            "raw_records": len(raw_records),
            "canonical_profiles": len(validated),
            "projected_profiles": len(projected),
        },
        "raw_records": raw_records,
        "canonical_profiles": validated,
        "projected_profiles": projected,
        "config_used": config,
    }


@app.get("/api/config/default")
def get_default_config() -> dict[str, Any]:
    return _get_default_config()


class ReprojectRequest(BaseModel):
    canonical_profiles: list[dict[str, Any]]
    config: dict[str, Any]


@app.post("/api/project")
def reproject(req: ReprojectRequest) -> dict[str, Any]:
    projected = []
    for rec in req.canonical_profiles:
        try:
            res = project_profile(rec, req.config)
            validate_projected_output(res, req.config)
            projected.append(res)
        except (ConfigurationError, OutputValidationError) as e:
            raise HTTPException(
                status_code=400, detail=f"Projection Error: {str(e)}"
            )

    return {"projected_profiles": projected, "config_used": req.config}


@app.post("/api/process")
async def process_files(
    files: list[UploadFile] = File(...),
    config: str | None = Form(None),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    parsed_config = _get_default_config()
    if config:
        try:
            parsed_config = json.loads(config)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid projection config JSON: {e}"
            )

    raw_records: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as temp_dir:
        for file in files:
            file_path = os.path.join(temp_dir, file.filename)
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)

            extracted = parse_uploaded_file(file_path)
            raw_records.extend(extracted)

    return run_pipeline(raw_records, parsed_config)


@app.get("/api/process-samples")
def process_samples() -> dict[str, Any]:
    if not SAMPLES_DIR.exists():
        raise HTTPException(status_code=404, detail="Samples directory not found.")

    default_config = _get_default_config()
    raw_records: list[dict[str, Any]] = []

    for file_path in SAMPLES_DIR.iterdir():
        if file_path.is_file() and file_path.name != "view_config.json":
            extracted = parse_uploaded_file(str(file_path))
            raw_records.extend(extracted)

    return run_pipeline(raw_records, default_config)


# Mount static files for UI if directory exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def root():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Candidate Transformer API is running</h1><p>Visit <a href='/docs'>/docs</a> for API documentation.</p>"
