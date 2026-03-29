# ESG-rapportgenerator for almene boligorganisationer i Danmark

Systemet genererer AlmenKompas ESG-ledelsesrapporter (HTML + PDF) fra uploadede JSON-datasæt uden API-integrationer.

## Teknisk stack
- Python 3.10+
- Jinja2 (HTML-rendering)
- pdfkit + wkhtmltopdf (PDF-eksport)
- Anthropic Claude API (valgfrit – LLM-tekster)

## Mappestruktur
```text
esg_rapport/
├── __init__.py
├── generator.py
├── esg_engine.py
├── report_logic.py
├── validate_input.py
├── pdf_export.py
├── requirements.txt
├── data/
│   ├── indicator_registry.json
│   ├── min_org.json
│   ├── domea_roedovre.json
│   └── boligforeningen_fremad.json
├── templates/
│   ├── rapport.html.jinja
│   └── rapport_pdf.html.jinja
└── outputs/
```

## Pipeline
```text
JSON-input → validate_input → esg_engine → report_logic → Jinja2 → HTML/PDF
```

## Indikatorbank
27 indikatorer fordelt på:
- E: 8
- S: 7
- G: 12

Trafiklysmetoder:
- `benchmark_relativ`
- `benchmark_relativ_procentpoint`
- `absolut_taerskel`
- `binaer`
- `binaer_omvendt`
- `ingen_benchmark`

Ingen `eval()` anvendes; threshold-fortolkning sker via sikker deklarativ parser (`_parse_thresholds`).

## Kørsel
Fra mappen `esg_rapport/`:

```bash
pip install -r requirements.txt
python pdf_export.py --generate-fonts
python validate_input.py data/min_org.json
python generator.py --input data/min_org.json --no-llm
python generator.py --input data/min_org.json --pdf
```

Alternativt fra repo-roden:

```bash
pip install -r esg_rapport/requirements.txt
python esg_rapport/pdf_export.py --generate-fonts
python esg_rapport/validate_input.py esg_rapport/data/min_org.json
python esg_rapport/generator.py --input esg_rapport/data/min_org.json --no-llm
python esg_rapport/generator.py --input esg_rapport/data/min_org.json --pdf
```

## Noter
- PDF kræver installeret `wkhtmltopdf` i miljøet.
- LLM-berigelse er valgfri og aktiveres kun hvis `ANTHROPIC_API_KEY` findes i miljøet.
