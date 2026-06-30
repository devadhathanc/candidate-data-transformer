import argparse
import json
import sys
from pathlib import Path

from ingestion import parse_ats_json, parse_unstructured_notes
from normalization import NormalizationEngine
from merging import MergeEngine
from projection import project_profile, ConfigurationError
from models import CanonicalProfile


def _load_config(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: config file not found — {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: config file is not valid JSON — {e}", file=sys.stderr)
        sys.exit(1)


def _route(filepath: str) -> dict | None:
    path = Path(filepath)
    try:
        if path.suffix == ".json":
            return parse_ats_json(str(path))
        elif path.suffix == ".txt":
            return parse_unstructured_notes(str(path))
        else:
            print(f"Warning: skipping unknown extension '{path.suffix}' — {path.name}", file=sys.stderr)
            return None
    except FileNotFoundError:
        print(f"Warning: input file not found — {path}", file=sys.stderr)
        return None
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Warning: failed to parse {path.name} — {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Warning: unexpected error reading {path.name} — {e}", file=sys.stderr)
        return None


def _validate(profile_dict: dict) -> dict | None:
    try:
        validated = CanonicalProfile.model_validate(profile_dict)
        return validated.model_dump()
    except Exception as e:
        print(
            f"Warning: schema validation failed for candidate "
            f"'{profile_dict.get('candidate_id', '?')}' — {e}",
            file=sys.stderr,
        )
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-Source Candidate Data Transformer",
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="One or more candidate data files (.json / .txt)",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Projection configuration file (JSON)",
    )
    args = parser.parse_args()

    # ── 0. Load projection config ──────────────────────────────────
    config = _load_config(args.config)

    # ── 1. Parse ───────────────────────────────────────────────────
    raw_records: list[dict] = []
    for fp in args.inputs:
        rec = _route(fp)
        if rec is not None:
            raw_records.append(rec)

    if not raw_records:
        print("No usable records to process. Exiting.", file=sys.stderr)
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

    # ── 5. Project ─────────────────────────────────────────────────
    projected: list[dict] = []
    for rec in validated:
        try:
            projected.append(project_profile(rec, config))
        except ConfigurationError as e:
            print(
                f"Error: invalid projection config for candidate "
                f"'{rec.get('candidate_id', '?')}' — {e}",
                file=sys.stderr,
            )
            sys.exit(1)

    # ── 6. Output ──────────────────────────────────────────────────
    print(json.dumps(projected, indent=2, default=str))


if __name__ == "__main__":
    main()
