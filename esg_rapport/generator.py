from __future__ import annotations

import argparse
import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    from .esg_engine import load_registry, compute_scores
    from .report_logic import build_report_sections
    from .validate_input import validate_payload
    from .pdf_export import html_to_pdf
except ImportError:
    from esg_engine import load_registry, compute_scores
    from report_logic import build_report_sections
    from validate_input import validate_payload
    from pdf_export import html_to_pdf

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"


def generate_report(input_path: Path, use_llm: bool, export_pdf: bool) -> tuple[Path, Path | None]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    errors = validate_payload(payload)
    if errors:
        raise ValueError("Input-validering fejlede: " + "; ".join(errors))

    registry = load_registry(BASE_DIR / "data" / "indicator_registry.json")
    scores = compute_scores(payload, registry)
    sections = build_report_sections(payload, scores, use_llm=use_llm)

    env = Environment(
        loader=FileSystemLoader(BASE_DIR / "templates"),
        autoescape=select_autoescape(["html", "jinja"]),
    )

    template_name = "rapport_pdf.html.jinja" if export_pdf else "rapport.html.jinja"
    template = env.get_template(template_name)

    html = template.render(
        organization=payload["organization"],
        report_year=payload["report_year"],
        sections=sections,
        indicators=scores,
    )

    OUTPUT_DIR.mkdir(exist_ok=True)
    slug = input_path.stem
    out_html = OUTPUT_DIR / f"{slug}_report.html"
    out_html.write_text(html, encoding="utf-8")

    out_pdf: Path | None = None
    if export_pdf:
        out_pdf = OUTPUT_DIR / f"{slug}_report.pdf"
        html_to_pdf(out_html, out_pdf)

    return out_html, out_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Generér ESG-ledelsesrapport (HTML/PDF)")
    parser.add_argument("--input", type=Path, required=True, help="Input JSON")
    parser.add_argument("--no-llm", action="store_true", help="Deaktiver LLM")
    parser.add_argument("--pdf", action="store_true", help="Generér også PDF")
    args = parser.parse_args()

    html_path, pdf_path = generate_report(args.input, use_llm=not args.no_llm, export_pdf=args.pdf)
    print(f"HTML genereret: {html_path}")
    if pdf_path:
        print(f"PDF genereret: {pdf_path}")


if __name__ == "__main__":
    main()
