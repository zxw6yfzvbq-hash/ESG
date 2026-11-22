from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

REQUIRED_ROOT_FIELDS = ["organization", "report_year", "records"]
REQUIRED_ORG_FIELDS = ["name"]
REQUIRED_RECORD_FIELDS = ["department", "year"]


class ValidationError(Exception):
    pass


def validate_payload(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["Input skal være et JSON-objekt"]

    for field in REQUIRED_ROOT_FIELDS:
        if field not in payload:
            errors.append(f"Mangler root-felt: {field}")

    org = payload.get("organization")
    if not isinstance(org, dict):
        errors.append("organization skal være et objekt")
    elif not isinstance(org.get("name"), str) or not org["name"].strip():
        errors.append("organization.name skal være en ikke-tom tekst")

    report_year = payload.get("report_year")
    valid_report_year = type(report_year) is int and report_year > 0
    if not valid_report_year:
        errors.append("report_year skal være et positivt heltal")

    records = payload.get("records")
    if not isinstance(records, list) or not records:
        errors.append("records skal være en ikke-tom liste")
        return errors

    # The same registry defines known fields and units for validation and scoring.
    definitions = json.loads((Path(__file__).parent / "data/indicator_registry.json").read_text(encoding="utf-8"))
    seen: set[tuple[str, int]] = set()
    years: set[int] = set()
    for i, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            errors.append(f"record[{i}] skal være et objekt")
            continue
        department = record.get("department")
        year = record.get("year")
        valid_department = isinstance(department, str) and bool(department.strip())
        valid_year = type(year) is int and year > 0
        if not valid_department:
            errors.append(f"record[{i}].department skal være en ikke-tom tekst")
        if not valid_year:
            errors.append(f"record[{i}].year skal være et positivt heltal")
        else:
            years.add(year)
            if valid_report_year and year > report_year:
                errors.append(f"record[{i}].year ligger efter report_year")
        if valid_year and valid_department:
            identity = (department.strip(), year)
            if identity in seen:
                errors.append(f"record[{i}]: Dublet for afdeling og år: {identity}")
            seen.add(identity)
        for definition in definitions:
            key = definition["source_key"]
            value = record.get(key)
            if value is None:
                continue
            field = f"record[{i}].{key}"
            if definition["unit"] == "bool":
                if type(value) is not bool:
                    errors.append(f"{field} skal være boolean eller null")
            elif type(value) not in (int, float) or not math.isfinite(value):
                errors.append(f"{field} skal være et endeligt tal eller null")
            elif value < 0:
                errors.append(f"{field} må ikke være negativ")
            elif definition["unit"] == "%" and value > 100:
                errors.append(f"{field} skal være mellem 0 og 100")
    if valid_report_year and report_year not in years:
        errors.append("records mangler data for report_year")
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

