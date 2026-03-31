from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_ROOT_FIELDS = ["organization", "report_year", "records"]
REQUIRED_ORG_FIELDS = ["name"]
REQUIRED_RECORD_FIELDS = ["department", "year"]


class ValidationError(Exception):
    pass


def validate_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    for field in REQUIRED_ROOT_FIELDS:
        if field not in payload:
            errors.append(f"Mangler root-felt: {field}")

    org = payload.get("organization")
    if not isinstance(org, dict):
        errors.append("organization skal være et objekt")
    else:
        for field in REQUIRED_ORG_FIELDS:
            if field not in org:
                errors.append(f"organization.{field} mangler")

    records = payload.get("records")
    if not isinstance(records, list) or not records:
        errors.append("records skal være en ikke-tom liste")
    else:
        for i, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                errors.append(f"record[{i}] skal være et objekt")
                continue

            for field in REQUIRED_RECORD_FIELDS:
                if field not in record:
                    errors.append(f"record[{i}].{field} mangler")

            if "year" in record and not isinstance(record["year"], int):
                errors.append(f"record[{i}].year skal være heltal")

    return errors


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Valider input-JSON til ESG-rapportgenerator")
    parser.add_argument("input", type=Path, help="Path til input JSON")
    args = parser.parse_args()

    payload = load_json(args.input)
    errors = validate_payload(payload)

    if errors:
        print("Validering fejlede:")
        for err in errors:
            print(f"- {err}")
        raise SystemExit(1)

    print("Validering OK")


if __name__ == "__main__":
    main()
