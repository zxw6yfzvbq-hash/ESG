import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from esg_rapport import generator, pdf_export, report_logic
from esg_rapport.esg_engine import compute_scores, load_registry

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "esg_rapport/data"


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.output = self.root / "outputs"
        self.output_patch = patch.object(generator, "OUTPUT_DIR", self.output)
        self.output_patch.start()
        self.addCleanup(self.output_patch.stop)

    def input_file(self, data=None):
        data = data or json.loads((DATA / "domea_roedovre.json").read_text())
        path = self.root / "input.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def test_all_sample_html_reports(self):
        for source in DATA.glob("*.json"):
            if source.name == "indicator_registry.json":
                continue
            with self.subTest(source=source.name):
                html_path, pdf_path = generator.generate_report(source, use_llm=False, export_pdf=False)
                html = html_path.read_text()
                self.assertIsNone(pdf_path)
                self.assertEqual(html.count("<tr>"), 28)
                self.assertIn("27 indikatorer har måledata", html)
                self.assertEqual(html.count("<h2>"), 7)
                self.assertNotIn("Seneste niveau mangler", html)
                self.assertNotIn("nan", html.lower())
                for color in re.findall('class="light-([a-z]+)"', html):
                    self.assertIn(".light-" + color + " {", html)

    def test_html_escapes_text_and_preserves_danish(self):
        data = json.loads((DATA / "min_org.json").read_text())
        data["organization"]["name"] = '<script>alert("æøå & Ø")</script>'
        path, _ = generator.generate_report(self.input_file(data), False, False)
        text = path.read_text()
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("æøå &amp; Ø", text)

    def test_pdf_has_table_and_does_not_replace_browser_html(self):
        source = self.input_file()
        html_path, _ = generator.generate_report(source, False, False)
        original = html_path.read_text()
        print_sources = []

        def convert(html_path, pdf_path):
            print_sources.append(html_path)
            text = html_path.read_text()
            self.assertEqual(text.count("<tr>"), 28)
            self.assertIn("27 indikatorer har måledata", text)
            self.assertIn("DejaVu Sans", text)
            pdf_path.write_bytes(b"%PDF-test")

        with patch.object(generator, "html_to_pdf", side_effect=convert):
            new_html, pdf_path = generator.generate_report(source, False, True)
        self.assertEqual(new_html, html_path)
        self.assertEqual(new_html.read_text(), original)
        self.assertEqual(pdf_path.read_bytes(), b"%PDF-test")
        self.assertFalse(print_sources[0].exists())

    def test_invalid_input_stops_before_calculation_and_output(self):
        source = self.input_file({"organization": {"name": "X"}})
        with patch.object(generator, "compute_scores") as compute:
            with self.assertRaisesRegex(ValueError, "Input-validering"):
                generator.generate_report(source, False, False)
            compute.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_pdf_failure_cleans_print_source(self):
        print_sources = []

        def fail(html_path, pdf_path):
            print_sources.append(html_path)
            raise OSError("wkhtmltopdf unavailable")

        with patch.object(generator, "html_to_pdf", side_effect=fail):
            with self.assertRaisesRegex(OSError, "wkhtmltopdf unavailable"):
                generator.generate_report(self.input_file(), False, True)
        self.assertFalse(print_sources[0].exists())
        self.assertFalse((self.output / "input_report.pdf").exists())

    def test_pdf_options_and_converter_failure(self):
        with patch.object(pdf_export.pdfkit, "from_file", side_effect=OSError("converter failed")) as convert:
            with self.assertRaisesRegex(OSError, "converter failed"):
                pdf_export.html_to_pdf(Path("input.html"), self.root / "out.pdf")
        options = convert.call_args.kwargs["options"]
        self.assertEqual(options["encoding"], "UTF-8")
        self.assertEqual(options["page-size"], "A4")

    def test_grey_does_not_recommend_maintaining_missing_level(self):
        data = {"organization": {"name": "Test"}, "report_year": 2025,
                "records": [{"department": "A", "year": 2025}]}
        scores = compute_scores(data, load_registry(DATA / "indicator_registry.json"))
        sections = report_logic.build_report_sections(data, scores)
        text = "\n".join(s["body"] for s in sections)
        self.assertIn("0 indikatorer har måledata", text)
        self.assertNotIn("Niveauet bør fastholdes", text)
        self.assertNotIn("Fokus bør være stabilisering", text)
        self.assertIn("Måledata mangler", text)

    def test_partial_coverage_is_visible(self):
        data = {"organization": {"name": "Test"}, "report_year": 2025,
                "records": [{"department": "A", "year": 2025, "energy_kwh_m2": 100},
                            {"department": "B", "year": 2025}]}
        scores = compute_scores(data, load_registry(DATA / "indicator_registry.json"))
        sections = report_logic.build_report_sections(data, scores)
        self.assertIn("Datadækning: 1/2", sections[3]["body"])

    def test_no_llm_never_calls_network(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(report_logic.request, "urlopen") as network:
                generator.generate_report(self.input_file(), False, False)
        network.assert_not_called()

    def test_llm_fallbacks_and_enrichment(self):
        sections = [{"title": "5. Overordnede betragtninger", "body": "Original"}]
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(report_logic.request, "urlopen") as network:
                self.assertEqual(report_logic._enrich_with_llm(sections.copy(), {}, []), sections)
                network.assert_not_called()
        for error in [TimeoutError("timeout"), ValueError("invalid JSON")]:
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                with patch.object(report_logic.request, "urlopen", side_effect=error):
                    self.assertEqual(report_logic._enrich_with_llm(sections.copy(), {}, []), sections)
        for response, expected in [(b'{}', "Original"),
                                   (json.dumps({"content": [{"text": "Forbedret"}]}).encode(), "Forbedret")]:
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                with patch.object(report_logic.request, "urlopen") as network:
                    network.return_value.__enter__.return_value.read.return_value = response
                    result = report_logic._enrich_with_llm([dict(sections[0])], {}, [])
                    self.assertEqual(result[0]["body"], expected)

    def test_cli_pdf_failure_does_not_print_success(self):
        stream = io.StringIO()
        with patch("sys.argv", ["generator", "--input", str(self.input_file()), "--no-llm", "--pdf"]):
            with patch.object(generator, "html_to_pdf", side_effect=OSError("failed")):
                with contextlib.redirect_stdout(stream), self.assertRaises(OSError):
                    generator.main()
        self.assertNotIn("PDF genereret", stream.getvalue())


class RealPdfTests(unittest.TestCase):
    def test_real_pdf_contains_report_and_all_indicators(self):
        missing = [name for name in ("wkhtmltopdf", "pdftotext") if not shutil.which(name)]
        if missing:
            if os.getenv("ESG_REQUIRE_PDF") == "1":
                self.fail("Required PDF tools missing: " + ", ".join(missing))
            self.skipTest("PDF integration requires: " + ", ".join(missing))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(generator, "OUTPUT_DIR", output):
                _, pdf = generator.generate_report(DATA / "domea_roedovre.json", False, True)
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))
            text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                                  check=True, capture_output=True, text=True).stdout
            self.assertIn("Domea Rødovre", text)
            self.assertIn("2025", text)
            self.assertIn("Indikatoroversigt", text)
            for indicator in [f"E{i}" for i in range(1, 9)] + [f"S{i}" for i in range(1, 8)] + [f"G{i}" for i in range(1, 13)]:
                self.assertRegex(text, r"\b" + indicator + r"\b")
