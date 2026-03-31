"""
esg_engine.py
=============
Beregningsmodul: mapper inputdata → beregnede indikatorer med trafiklys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any
import json
import re as _re
from pathlib import Path


@dataclass
class CalculatedIndicator:
    id: str
    navn: str
    esg: str
    maalepunkt: str
    enhed_display: str
    indikator_type: str
    prompt_type: str
    org_vaerdi: Optional[float]
    org_aar: Optional[int]
    benchmark_vaerdi: Optional[float]
    benchmark_aar: Optional[int]
    datastatus: str
    difference_abs: Optional[float]
    difference_pct: Optional[float]
    difference_type: str
    ratio: Optional[float]
    trafiklys: str
    trafiklys_metode: str
    trafiklys_note: Optional[str]
    analytisk_begraensning: Optional[str]
    aar_usikker: bool
    billede_emoji: str
    registry_def: dict = field(default_factory=dict)
    org_vaerdi_fmt: str = ""
    benchmark_vaerdi_fmt: str = ""
    diff_abs_fmt: str = ""
    diff_pct_fmt: str = ""


def _format_value(value: Any, enhed_kode: str) -> str:
    if value is None:
        return "–"
    if isinstance(value, str):
        return value
    if enhed_kode == "pct":
        return f"{value:,.1f}%".replace(",", ".")
    if enhed_kode in ("kr", "kr_per_lejemaal", "kr_per_m2"):
        return f"{int(value):,} kr.".replace(",", ".")
    if enhed_kode == "kgCO2e_per_m2":
        return f"{value:.2f} kgCO₂e/m²"
    if enhed_kode == "kwh_per_m2":
        return f"{value:.1f} kWh/m²"
    if enhed_kode == "mwh":
        return f"{value:,.0f} MWh".replace(",", ".")
    if enhed_kode == "tco2e":
        return f"{value:,.2f} tCO₂e".replace(",", ".")
    if enhed_kode == "antal_per_1000":
        return f"{value:.1f} per 1.000 beboere"
    return str(value)


def _format_diff(diff: Optional[float], diff_type: str, enhed_kode: str) -> str:
    if diff is None:
        return "–"
    sign = "+" if diff >= 0 else ""
    if enhed_kode in ("kr", "kr_per_lejemaal", "kr_per_m2"):
        return f"{sign}{int(diff):,} kr.".replace(",", ".")
    if diff_type == "procentpoint":
        return f"{sign}{diff:.1f} procentpoint"
    if diff_type == "relativ_pct":
        return f"{sign}{diff:.1f}%"
    return str(round(diff, 2))


def _parse_threshold(expr: str) -> tuple:
    expr = expr.strip()
    if expr in ("False", "false"):
        return ("always_false",)

    str_match = _re.match(r"\w+ == '([^']+)'$", expr)
    if str_match:
        return ("str_eq", str_match.group(1))

    num = r"-?\d+(?:\.\d+)?"
    op = r"(?:==|!=|[><]=?)"

    and_match = _re.match(rf"\w+ ({op}) ({num}) and \w+ ({op}) ({num})$", expr)
    if and_match:
        op1, v1, op2, v2 = and_match.groups()
        lo, hi = float(v1), float(v2)
        lo_inc = op1 in (">=", "==")
        hi_inc = op2 in ("<=", "==")
        return ("between", lo, hi, lo_inc, hi_inc)

    simple = _re.match(rf"\w+ ({op}) ({num})$", expr)
    if simple:
        operator, val = simple.groups()
        return (operator, float(val))

    raise ValueError(f"Kan ikke parse taerskeludtryk: {expr!r}")


def _eval_threshold(parsed: tuple, value: Any) -> bool:
    kind = parsed[0]
    if kind == "always_false":
        return False
    if kind == "str_eq":
        return str(value) == parsed[1]
    if kind == "between":
        _, lo, hi, lo_inc, hi_inc = parsed
        lo_ok = (value >= lo) if lo_inc else (value > lo)
        hi_ok = (value <= hi) if hi_inc else (value < hi)
        return lo_ok and hi_ok
    operator, threshold = parsed[0], parsed[1]
    return {
        "<": value < threshold,
        "<=": value <= threshold,
        ">": value > threshold,
        ">=": value >= threshold,
        "==": value == threshold,
        "!=": value != threshold,
    }[operator]


def _evaluate_traffic_light(
    org_vaerdi: Any,
    benchmark_vaerdi: Optional[float],
    ratio: Optional[float],
    definition: dict,
    datastatus: str,
) -> str:
    tl = definition["trafiklys"]
    metode = tl["metode"]

    if datastatus != "tilgaengelig" or org_vaerdi is None:
        return "graa"

    try:
        if metode == "ingen_benchmark":
            return "graa"

        if metode == "benchmark_relativ":
            if ratio is None:
                return "graa"
            for farve in ("groen", "gul", "roed"):
                if _eval_threshold(_parse_threshold(tl[farve]), ratio):
                    return farve
            return "graa"

        if metode == "benchmark_relativ_procentpoint":
            if benchmark_vaerdi is None:
                return "graa"
            diff = float(org_vaerdi) - float(benchmark_vaerdi)
            for farve in ("groen", "gul", "roed"):
                if _eval_threshold(_parse_threshold(tl[farve]), diff):
                    return farve
            return "graa"

        if metode == "absolut_taerskel":
            val = float(org_vaerdi)
            for farve in ("groen", "gul", "roed"):
                if _eval_threshold(_parse_threshold(tl[farve]), val):
                    return farve
            return "graa"

        if metode in ("binaer", "binaer_omvendt"):
            for farve in ("groen", "gul", "roed"):
                expr = tl.get(farve, "False")
                if _eval_threshold(_parse_threshold(expr), org_vaerdi):
                    return farve
            return "graa"

    except (ValueError, KeyError):
        return "graa"

    return "graa"


class ValidationError(Exception):
    pass


def validate_input(raw_indicator: dict, definition: dict) -> list[str]:
    warnings: list[str] = []
    ind_id = raw_indicator.get("id", "ukendt")
    known_statuses = {"tilgaengelig", "data_undervejs", "planlagt_2026", "ikke_indtastet"}

    status = raw_indicator.get("datastatus", "")
    if status not in known_statuses:
        warnings.append(f"{ind_id}: Ukendt datastatus '{status}'")

    if status == "tilgaengelig":
        val = raw_indicator.get("org_vaerdi")
        if val is None:
            warnings.append(f"{ind_id}: datastatus='tilgaengelig' men org_vaerdi mangler")
        elif not isinstance(val, (int, float, str, bool)):
            warnings.append(f"{ind_id}: org_vaerdi har ukendt type: {type(val)}")

    if raw_indicator.get("org_vaerdi") is not None and raw_indicator.get("org_aar") is None:
        warnings.append(f"{ind_id}: org_vaerdi er sat men org_aar mangler")

    if (
        raw_indicator.get("org_vaerdi") is not None
        and raw_indicator.get("benchmark_vaerdi") is None
        and definition.get("trafiklys", {}).get("metode") in {"benchmark_relativ", "benchmark_relativ_procentpoint"}
    ):
        warnings.append(f"{ind_id}: Benchmark mangler for benchmark-metode")

    return warnings


def calculate(raw_indicators: list[dict], registry: dict[str, dict]) -> list[CalculatedIndicator]:
    results: list[CalculatedIndicator] = []

    for raw in raw_indicators:
        ind_id = raw.get("id")
        if ind_id not in registry:
            continue

        defn = registry[ind_id]
        validate_input(raw, defn)

        org_val = raw.get("org_vaerdi")
        org_aar = raw.get("org_aar")
        bench_val = raw.get("benchmark_vaerdi")
        bench_aar = raw.get("benchmark_aar")
        datastatus = raw.get("datastatus", "ikke_indtastet")
        aar_usikker = org_val is not None and org_aar is None

        diff_abs = None
        diff_pct = None
        ratio = None
        diff_type = defn["beregningsregel"]["difference_type"]

        if isinstance(org_val, (int, float)) and isinstance(bench_val, (int, float)) and bench_val != 0:
            ratio = org_val / bench_val
            diff_abs = org_val - bench_val
            if diff_type == "relativ_pct":
                diff_pct = (diff_abs / bench_val) * 100
            elif diff_type == "procentpoint":
                diff_pct = diff_abs

        trafiklys = _evaluate_traffic_light(org_val, bench_val, ratio, defn, datastatus)

        enhed_kode = defn["enhed"]["kode"]
        enhed_display = defn["enhed"]["display"]

        calc = CalculatedIndicator(
            id=ind_id,
            navn=defn["navn"],
            esg=defn["esg"],
            maalepunkt=defn["maalepunkt"],
            enhed_display=enhed_display,
            indikator_type=defn["indikator_type"],
            prompt_type=defn["prompt_type"],
            org_vaerdi=org_val if isinstance(org_val, (int, float)) else None,
            org_aar=org_aar,
            benchmark_vaerdi=bench_val,
            benchmark_aar=bench_aar,
            datastatus=datastatus,
            difference_abs=diff_abs,
            difference_pct=diff_pct,
            difference_type=diff_type,
            ratio=ratio,
            trafiklys=trafiklys,
            trafiklys_metode=defn["trafiklys"]["metode"],
            trafiklys_note=defn.get("trafiklys_metode_note"),
            analytisk_begraensning=defn.get("analytisk_begraensning"),
            aar_usikker=aar_usikker,
            billede_emoji=defn.get("billede_emoji", "📊"),
            registry_def=defn,
            org_vaerdi_fmt=_format_value(org_val, enhed_kode),
            benchmark_vaerdi_fmt=_format_value(bench_val, enhed_kode),
            diff_abs_fmt=_format_diff(diff_abs, diff_type, enhed_kode),
            diff_pct_fmt=(f"{'+' if diff_pct >= 0 else ''}{diff_pct:.1f}%" if diff_pct is not None else "–"),
        )
        results.append(calc)

    return results


def load_registry(registry_path: Path) -> dict[str, dict]:
    data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    registry: dict[str, dict] = {}

    for item in data:
        method = item["method"]
        benchmark = item.get("benchmark")
        operator = item.get("operator", "lte")

        if method == "benchmark_relativ":
            if operator == "lte":
                tl = {
                    "metode": "benchmark_relativ",
                    "groen": "ratio <= 1.0",
                    "gul": "ratio > 1.0 and ratio <= 1.10",
                    "roed": "ratio > 1.10",
                }
            else:
                tl = {
                    "metode": "benchmark_relativ",
                    "groen": "ratio >= 1.0",
                    "gul": "ratio < 1.0 and ratio >= 0.90",
                    "roed": "ratio < 0.90",
                }
            diff_type = "relativ_pct"
        elif method == "benchmark_relativ_procentpoint":
            tl = {
                "metode": "benchmark_relativ_procentpoint",
                "groen": "diff <= 0",
                "gul": "diff > 0 and diff <= 5",
                "roed": "diff > 5",
            }
            diff_type = "procentpoint"
        elif method == "absolut_taerskel":
            th = item.get("thresholds", {})
            tl = {
                "metode": "absolut_taerskel",
                "groen": f"value >= {th.get('green', 0)}",
                "gul": f"value >= {th.get('yellow', 0)} and value < {th.get('green', 0)}",
                "roed": f"value < {th.get('yellow', 0)}",
            }
            diff_type = "ingen"
        elif method in {"binaer", "binaer_omvendt"}:
            tl = {
                "metode": method,
                "groen": "org_vaerdi == 'Ja'" if method == "binaer" else "org_vaerdi == 'Nej'",
                "gul": "False",
                "roed": "org_vaerdi != 'Ja'" if method == "binaer" else "org_vaerdi != 'Nej'",
            }
            diff_type = "ingen"
        else:
            tl = {"metode": "ingen_benchmark", "groen": "False", "gul": "False", "roed": "False"}
            diff_type = "ingen"

        registry[item["id"]] = {
            "id": item["id"],
            "navn": item["name"],
            "esg": item["dimension"],
            "maalepunkt": item["topic"],
            "enhed": {"kode": _unit_code(item.get("unit", "")), "display": item.get("unit", "")},
            "indikator_type": "performance",
            "prompt_type": "kvantitativ",
            "source_key": item["source_key"],
            "benchmark": benchmark,
            "beregningsregel": {"difference_type": diff_type},
            "trafiklys": tl,
        }

    return registry


def _unit_code(unit: str) -> str:
    mapping = {
        "%": "pct",
        "kWh/m2": "kwh_per_m2",
        "ton CO2e": "tco2e",
        "bool": "ja_nej",
        "score": "score",
        "index": "score",
        "hours": "antal",
        "l/m2": "score",
        "måneder": "antal",
    }
    return mapping.get(unit, "score")


def compute_scores(payload: dict[str, Any], registry: dict[str, dict]) -> list[dict[str, Any]]:
    records = payload.get("records", [])
    if not records:
        return []

    latest_year = max(r["year"] for r in records)
    previous_year = latest_year - 1

    latest_rows = [r for r in records if r.get("year") == latest_year]
    previous_rows = [r for r in records if r.get("year") == previous_year]

    raw_indicators: list[dict] = []
    for ind_id, defn in registry.items():
        source_key = defn["source_key"]
        cur_vals = [r.get(source_key) for r in latest_rows if isinstance(r.get(source_key), (int, float, bool))]
        prev_vals = [r.get(source_key) for r in previous_rows if isinstance(r.get(source_key), (int, float, bool))]

        current = _mean_value(cur_vals)
        previous = _mean_value(prev_vals)

        raw_indicators.append(
            {
                "id": ind_id,
                "org_vaerdi": _bool_to_ja_nej(current) if isinstance(current, bool) else current,
                "org_aar": latest_year,
                "benchmark_vaerdi": defn.get("benchmark"),
                "benchmark_aar": latest_year,
                "datastatus": "tilgaengelig" if current is not None else "ikke_indtastet",
                "_previous": previous,
            }
        )

    calculated = calculate(raw_indicators, registry)

    scores = []
    for calc, raw in zip(calculated, raw_indicators):
        previous = raw.get("_previous")
        current = calc.org_vaerdi
        delta_pct = None
        if isinstance(current, (int, float)) and isinstance(previous, (int, float)) and previous != 0:
            delta_pct = ((current - previous) / abs(previous)) * 100

        scores.append(
            {
                "id": calc.id,
                "dimension": calc.esg,
                "name": calc.navn,
                "unit": calc.enhed_display,
                "method": calc.trafiklys_metode,
                "current": current,
                "previous": previous,
                "delta_pct": delta_pct,
                "trafficlight": calc.trafiklys,
                "benchmark": calc.benchmark_vaerdi,
                "latest_year": calc.org_aar,
            }
        )

    return scores


def _mean_value(values: list[Any]) -> float | bool | None:
    if not values:
        return None
    if all(isinstance(v, bool) for v in values):
        return sum(1 if v else 0 for v in values) >= len(values) / 2
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _bool_to_ja_nej(value: bool) -> str:
    return "Ja" if value else "Nej"
