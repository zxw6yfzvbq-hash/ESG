from __future__ import annotations

import os
from typing import Any
from urllib import request
import json


def build_report_sections(payload: dict[str, Any], indicators: list[dict[str, Any]], use_llm: bool = False) -> list[dict[str, str]]:
    org_name = payload["organization"]["name"]

    grouped = {
        "E": [i for i in indicators if i["dimension"] == "E"],
        "S": [i for i in indicators if i["dimension"] == "S"],
        "G": [i for i in indicators if i["dimension"] == "G"],
    }

    sections = [
        {
            "title": "1. Om organisationen",
            "body": f"{org_name} indgår i denne ESG-ledelsesrapport. Rapporten er baseret på uploadet JSON og er genereret uden API-integrationer."
        },
        {
            "title": "2. Overblik over målepunktsstatus",
            "body": _status_overview(indicators)
        },
        {
            "title": "3. Analyseoverblik",
            "body": "Analysen adskiller observation, fortolkning, risici/potentialer og ledelsesimplikation. Datamangler markeres eksplicit."
        },
        {
            "title": "4. Detaljerede analyser for E, S og G",
            "body": _dimension_block("E", grouped["E"]) + "\n\n" + _dimension_block("S", grouped["S"]) + "\n\n" + _dimension_block("G", grouped["G"])
        },
        {
            "title": "5. Overordnede betragtninger",
            "body": _overall_considerations(indicators)
        },
        {
            "title": "6. Andre forhold",
            "body": "Rapporten er skabelonbaseret og opfinder ikke data. Resultater bør suppleres med lokal ledelsesdialog."
        },
    ]

    if use_llm:
        sections = _enrich_with_llm(sections, payload, indicators)

    return sections


def _status_overview(indicators: list[dict[str, Any]]) -> str:
    measured = sum(1 for i in indicators if i["current"] is not None)
    red = sum(1 for i in indicators if i["trafficlight"] == "roed")
    yellow = sum(1 for i in indicators if i["trafficlight"] == "gul")
    green = sum(1 for i in indicators if i["trafficlight"] == "groen")
    return (
        f"{measured} indikatorer har måledata. Trafiklysfordeling: {green} grønne, {yellow} gule, {red} røde. "
        "Grå betyder, at indikatoren ikke kan vurderes; se årsagen ved indikatoren."
    )


def _dimension_block(dimension: str, items: list[dict[str, Any]]) -> str:
    titles = {"E": "E – Miljø", "S": "S – Sociale forhold", "G": "G – God almen ledelse"}
    lines = [titles[dimension]]
    for item in items:
        lines.append(_indicator_paragraph(item))
    return "\n\n".join(lines)


def _indicator_paragraph(item: dict[str, Any]) -> str:
    observation = (
        f"Seneste niveau er {item['current']} {item['unit']}" if item["current"] is not None else "Seneste niveau mangler"
    )
    trend = f"Udvikling: {item['delta_pct']:.1f}%" if item["delta_pct"] is not None else "Udvikling kan ikke beregnes"
    if item["trafficlight"] == "graa":
        implication = "Afklar datagrundlag og vurderingsgrundlag før konklusion"
    elif item["trafficlight"] in {"roed", "gul"}:
        implication = "Skærpet ledelsesopmærksomhed anbefales"
    else:
        implication = "Niveauet bør fastholdes"
    coverage = ""
    if item.get("coverage_total", 0):
        coverage = f" Datadækning: {item['coverage_count']}/{item['coverage_total']} afdelingsrækker."
    note = item.get("trafficlight_note", "")
    if note:
        coverage += f" Vurderingsgrundlag: {note}."
    for warning in item.get("warnings", []):
        coverage += f" Advarsel: {warning}."

    return (
        f"{item['name']}\n"
        f"1. Kort konklusion: Trafiklys er {item['trafficlight']}.\n"
        f"2. Hvad viser data?: {observation}. {trend}.{coverage}\n"
        f"3. Hvad betyder det?: Vurderingen er baseret på metoden {item['method']}.\n"
        f"4. Risici og potentialer: Risiko øges ved vedvarende rødt niveau; potentiale ligger i målrettede indsatser.\n"
        f"5. Ledelsesimplikation: {implication}."
    )


def _overall_considerations(indicators: list[dict[str, Any]]) -> str:
    red_items = [i["name"] for i in indicators if i["trafficlight"] == "roed"]
    if not indicators or all(i["trafficlight"] == "graa" for i in indicators):
        return "Grundlaget tillader ikke en samlet trafiklysvurdering. Afklar data og benchmarks før ledelsesmæssige konklusioner."
    if not red_items and any(i["trafficlight"] == "graa" for i in indicators):
        return "Ingen vurderede indikatorer er røde. Grå indikatorer kan ikke vurderes; afklar deres datagrundlag og benchmarks."
    if not red_items:
        return "Ingen indikatorer er røde i seneste periode. Fokus bør være stabilisering af resultater og datadisciplin."
    return "Følgende indikatorer kræver særlig ledelsesopmærksomhed: " + ", ".join(red_items) + "."


def _enrich_with_llm(
    sections: list[dict[str, str]], payload: dict[str, Any], indicators: list[dict[str, Any]]
) -> list[dict[str, str]]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return sections

    prompt = {
        "organization": payload.get("organization", {}),
        "indicators": [{"name": i["name"], "trafficlight": i["trafficlight"], "current": i["current"]} for i in indicators],
        "instruction": "Forbedr sektion 5 i kort, professionelt dansk. Ingen nye data."
    }

    req = request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({
            "model": "claude-3-5-sonnet-latest",
            "max_tokens": 300,
            "messages": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
        }).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    try:
        with request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            text = body["content"][0]["text"]
            for s in sections:
                if s["title"].startswith("5."):
                    s["body"] = text.strip()
    except Exception:
        return sections

    return sections

