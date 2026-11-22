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

Ingen `eval()` anvendes; threshold-fortolkning sker via sikker deklarativ parser (`_parse_threshold`).

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

## Automatiske tests

Fra repo-roden:

```bash
python -m pip install -r esg_rapport/requirements.txt
python -m unittest discover -s tests -v
```

Testene dækker det faktiske indikatorregister, alle eksempeldata, trafiklysmetoder,
grænseværdier, beregninger, inputvalidering, årsvalg, HTML, PDF-kald og LLM-fallback.
Der foretages ingen reelle LLM-kald i tests.

PDF-integrationstesten kræver `wkhtmltopdf` og `pdftotext` (fra `poppler-utils`).
Den kontrollerer PDF-signatur samt udtrukket tekst med organisation, år og alle 27
indikator-id'er. Uden værktøjerne springes denne ene test over lokalt.
Sæt `ESG_REQUIRE_PDF=1` for at kræve værktøjerne og fejle ved manglende installation.
GitHub Actions kører Python 3.10/3.12 samt en separat obligatorisk PDF-test med
værktøjerne installeret. PDF-testen er en indholdstest; den erstatter ikke en visuel
gennemgang af sideskift og layout.

## Input- og årsregler

- `report_year` og hver rækkes `year` skal være positive heltal (ikke boolean).
- Der skal være mindst én række for rapportåret. Rækker efter rapportåret afvises.
- Beregninger bruger rapportåret. Udvikling sammenlignes med året umiddelbart før;
  manglende foregående år eller en tidligere værdi på nul giver ingen procentændring.
- Kombinationen afdeling/år skal være unik. Navne skal være ikke-tomme tekster.
- Indikatorværdier må mangle eller være `null`. Tal skal være endelige og ikke-negative;
  procentværdier skal være mellem 0 og 100. Binære felter kræver `true`/`false`.
  Tal som tekst konverteres ikke stiltiende.
- Et valgfrit `topic` i registeret falder tilbage til indikatornavnet.
- Grå indikatorer ledsages af en årsag. Rapporten viser datadækning som antal
  afdelingsrækker med måling i forhold til afdelingsrækkerne i rapportåret.
- HTML og PDF indeholder samme indikatoroversigt. PDF bruger en midlertidig
  printversion, så en PDF-eksport ikke overskriver browserrapportens layout.

## Faglige afklaringer før brug til beslutningsstøtte

Følgende eksisterende aggregeringsregler er bevaret og er ikke fagligt godkendt af testene:

| Område | Nuværende adfærd | Afklaring |
| --- | --- | --- |
| Numeriske indikatorer | Simpelt gennemsnit af tilgængelige afdelingsværdier | Vælg sum, gennemsnit eller vægtning pr. indikator. CO₂-totaler kan kræve sum; kWh/m² kan kræve arealvægtning. |
| Binære indikatorer | Flertal; stemmelighed bliver `true` | Beslut om én negativ/risikobærende afdeling skal være afgørende for den enkelte indikator. |
| Delvis datadækning | Beregning på tilgængelige værdier; dækningen oplyses | Fastlæg minimumsdækning og konsekvens for trafiklys. Afdelinger uden nogen række kan ikke tælles uden et afdelingsregister. |
| Sammenligning over tid | Foregående kalenderår, også ved ændret afdelingsgrundlag | Fastlæg krav om ens afdelingsgrundlag og eventuel brug af tidligere tilgængelige år. |
| Procentpointmetode | Lavere er bedre; gul ved forskel over 0 til og med 5 | Metoden bruges ikke i det medfølgende register. Afklar eventuel understøttelse af modsat retning. |

Ingen af disse åbne metodevalg bør afgøres alene ved at fastholde den eksisterende kode i tests.

