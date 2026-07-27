from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ingestion import parse_ats_json, parse_unstructured_notes
from normalization import NormalizationEngine
from merging import MergeEngine
from projection import project_profile, validate_projected_output, ConfigurationError, OutputValidationError
from models import CanonicalProfile
from resume_parser import parse_resume_file
from csv_parser import parse_recruiter_csv

logger = logging.getLogger(__name__)


def _load_config(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Config file not found — %s", path)
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error("Config file is not valid JSON — %s", e)
        sys.exit(1)


def _route(filepath: str) -> dict | list[dict] | None:
    path = Path(filepath)
    try:
        if path.suffix == ".json":
            return parse_ats_json(str(path))
        elif path.suffix == ".txt":
            return parse_unstructured_notes(str(path))
        elif path.suffix == ".csv":
            return parse_recruiter_csv(str(path))  # returns list[dict]
        elif path.suffix in (".pdf", ".docx"):
            return parse_resume_file(str(path))
        else:
            logger.warning("Skipping unknown extension '%s' — %s", path.suffix, path.name)
            return None
    except FileNotFoundError:
        logger.warning("Input file not found — %s", path)
        return None
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse %s — %s", path.name, e)
        return None
    except Exception as e:
        logger.warning("Unexpected error reading %s — %s", path.name, e)
        return None


def _validate(profile_dict: dict) -> dict | None:
    try:
        validated = CanonicalProfile.model_validate(profile_dict)
        return validated.model_dump()
    except Exception as e:
        logger.warning(
            "Schema validation failed for candidate '%s' — %s",
            profile_dict.get("candidate_id", "?"),
            e,
        )
        return None


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(
        description="Multi-Source Candidate Data Transformer",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch the Web Application server UI",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address for web server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for web server (default: 8000)",
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        required=False,
        help="One or more candidate data files (.json / .csv / .txt / .pdf / .docx)",
    )
    parser.add_argument(
        "--config",
        required=False,
        help="Projection configuration file (JSON)",
    )
    args = parser.parse_args()

    if args.web:
        import uvicorn
        logger.info("Starting Web Application at http://%s:%d", args.host, args.port)
        uvicorn.run("app:app", host=args.host, port=args.port, reload=True)
        return

    if not args.inputs or not args.config:
        parser.error("--inputs and --config are required when --web is not specified.")


    # ── 0. Load projection config ──────────────────────────────────
    config = _load_config(args.config)

    # ── 1. Parse ───────────────────────────────────────────────────
    raw_records: list[dict] = []
    for fp in args.inputs:
        rec = _route(fp)
        if rec is not None:
            if isinstance(rec, list):
                raw_records.extend(r for r in rec if r)
            else:
                raw_records.append(rec)

    if not raw_records:
        logger.error("No usable records to process. Exiting.")
        sys.exit(0)

    # ── 2. Normalize ───────────────────────────────────────────────
    normalizer = NormalizationEngine()
    normalized = [normalizer.transform(r) for r in raw_records]

    # ── 3. Merge ───────────────────────────────────────────────────
    merger = MergeEngine()
    merged = merger.merge(normalized)

    # ── 4. Validate ────────────────────────────────────────────────
    validated = []
    for rec in merged:
        v = _validate(rec)
        if v is not None:
            validated.append(v)

    # ── 5. Project & validate output ────────────────────────────────
    projected: list[dict] = []
    for rec in validated:
        try:
            result = project_profile(rec, config)
            validate_projected_output(result, config)
            projected.append(result)
        except ConfigurationError as e:
            logger.error(
                "Invalid projection config for candidate '%s' — %s",
                rec.get("candidate_id", "?"),
                e,
            )
            sys.exit(1)
        except OutputValidationError as e:
            logger.error(
                "Post-projection validation failed for candidate '%s' — %s",
                rec.get("candidate_id", "?"),
                e,
            )
            sys.exit(1)

    # ── 6. Output ──────────────────────────────────────────────────
    print(json.dumps(projected, indent=2, default=str))


if __name__ == "__main__":
    main()
