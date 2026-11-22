import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from esg_rapport.esg_engine import (
    _eval_threshold, _parse_threshold, calculate, compute_scores, load_registry,
)
from esg_rapport.validate_input import validate_payload

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "esg_rapport/data/indicator_registry.json"


def payload(records=None, year=2025):
    return {"organization": {"name": "Testbolig"}, "report_year": year,
            "records": records if records is not None else [{"department": "A", "year": year}]}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(REGISTRY_PATH)

    def score(self, ind_id, key, value):
        data = payload([{"department": "A", "year": 2025, key: value}])
        return next(x for x in compute_scores(data, self.registry) if x["id"] == ind_id)

    def test_real_registry_and_samples(self):
        self.assertEqual(len(self.registry), 27)
        self.assertEqual({d: sum(i["esg"] == d for i in self.registry.values()) for d in "ESG"},
                         {"E": 8, "S": 7, "G": 12})
        for name in ["min_org", "domea_roedovre", "boligforeningen_fremad"]:
            with self.subTest(name=name):
                data = json.loads((REGISTRY_PATH.parent / (name + ".json")).read_text())
                self.assertEqual(validate_payload(data), [])
                scores = compute_scores(data, self.registry)
                self.assertEqual(len(scores), 27)
                self.assertTrue(all(i["current"] is not None for i in scores))

    def test_benchmark_boundaries(self):
        cases = [
            ("E1", "co2e_total_tons", [(1000, "groen"), (1000.01, "gul"), (1100, "gul"), (1100.01, "roed")]),
            ("G8", "liquidity_months", [(2.6999, "roed"), (2.7, "gul"), (2.9999, "gul"), (3, "groen")]),
            ("E3", "energy_label_score", [(54.99, "roed"), (55, "gul"), (69.99, "gul"), (70, "groen")]),
        ]
        for ind_id, key, values in cases:
            for value, expected in values:
                with self.subTest(indicator=ind_id, value=value):
                    self.assertEqual(self.score(ind_id, key, value)["trafficlight"], expected)

    def test_all_binary_methods_preserve_observations(self):
        for ind_id, definition in self.registry.items():
            method = definition["trafiklys"]["metode"]
            if method not in {"binaer", "binaer_omvendt"}:
                continue
            for value in [True, False]:
                with self.subTest(indicator=ind_id, value=value):
                    result = self.score(ind_id, definition["source_key"], value)
                    good = value if method == "binaer" else not value
                    self.assertEqual(result["trafficlight"], "groen" if good else "roed")
                    self.assertEqual(result["current"], "Ja" if value else "Nej")
                    self.assertIsNone(result["delta_pct"])

    def test_every_benchmark_indicator(self):
        for ind_id, definition in self.registry.items():
            if definition["trafiklys"]["metode"] != "benchmark_relativ":
                continue
            higher_is_better = ">=" in definition["trafiklys"]["groen"]
            cases = [(1, "groen"), (.95, "gul"), (.89, "roed")] if higher_is_better else [
                (1, "groen"), (1.05, "gul"), (1.11, "roed")]
            for ratio, expected in cases:
                with self.subTest(indicator=ind_id, ratio=ratio):
                    result = self.score(ind_id, definition["source_key"], definition["benchmark"] * ratio)
                    self.assertEqual(result["trafficlight"], expected)

    def test_every_absolute_threshold(self):
        items = json.loads(REGISTRY_PATH.read_text())
        for item in items:
            if item["method"] != "absolut_taerskel":
                continue
            green, yellow = item["thresholds"]["green"], item["thresholds"]["yellow"]
            for value, color in [(yellow - .001, "roed"), (yellow, "gul"),
                                 (green - .001, "gul"), (green, "groen")]:
                with self.subTest(indicator=item["id"], value=value):
                    self.assertEqual(self.score(item["id"], item["source_key"], value)["trafficlight"], color)

    def test_relative_and_year_differences(self):
        data = payload([{"department": "A", "year": 2024, "energy_kwh_m2": 100},
                        {"department": "A", "year": 2025, "energy_kwh_m2": 110}])
        result = next(x for x in compute_scores(data, self.registry) if x["id"] == "E2")
        self.assertEqual(result["previous"], 100)
        self.assertAlmostEqual(result["delta_pct"], 10)
        raw = {"id": "E2", "org_vaerdi": 110, "org_aar": 2025,
               "benchmark_vaerdi": 100, "datastatus": "tilgaengelig"}
        calc = calculate([raw], self.registry)[0]
        self.assertAlmostEqual(calc.ratio, 1.1)
        self.assertEqual(calc.difference_abs, 10)
        self.assertEqual(calc.difference_pct, 10)

    def test_zero_benchmark_still_has_absolute_difference(self):
        definition = copy.deepcopy(self.registry["S3"])
        definition["beregningsregel"]["difference_type"] = "procentpoint"
        definition["trafiklys"] = {"metode": "benchmark_relativ_procentpoint", "groen": "diff <= 0",
                                  "gul": "diff > 0 and diff <= 5", "roed": "diff > 5"}
        for value, color in [(0, "groen"), (5, "gul"), (5.001, "roed")]:
            with self.subTest(value=value):
                calc = calculate([{"id": "S3", "org_vaerdi": value, "org_aar": 2025,
                                   "benchmark_vaerdi": 0, "datastatus": "tilgaengelig"}], {"S3": definition})[0]
                self.assertEqual(calc.difference_abs, value)
                self.assertEqual(calc.difference_pct, value)
                self.assertIsNone(calc.ratio)
                self.assertEqual(calc.trafiklys, color)
                self.assertIn("procentpoint", calc.diff_pct_fmt)

    def test_report_year_is_used_and_order_does_not_matter(self):
        rows = [{"department": "A", "year": 2024, "energy_kwh_m2": 100},
                {"department": "A", "year": 2025, "energy_kwh_m2": 200}]
        scores = compute_scores(payload(rows, 2024), self.registry)
        self.assertEqual(scores, compute_scores(payload(rows[::-1], 2024), self.registry))
        e2 = next(x for x in scores if x["id"] == "E2")
        self.assertEqual(e2["latest_year"], 2024)
        self.assertEqual(e2["current"], 100)

    def test_missing_values_and_comparison_year(self):
        for rows in [[{"department": "A", "year": 2025}],
                     [{"department": "A", "year": 2023, "energy_kwh_m2": 100},
                      {"department": "A", "year": 2025}],
                     [{"department": "A", "year": 2024, "energy_kwh_m2": 0},
                      {"department": "A", "year": 2025}]]:
            result = next(x for x in compute_scores(payload(rows), self.registry) if x["id"] == "E2")
            self.assertIsNone(result["current"])
            self.assertIsNone(result["delta_pct"])
            self.assertEqual(result["trafficlight"], "graa")

    def test_zero_previous_does_not_divide(self):
        rows = [{"department": "A", "year": 2024, "energy_kwh_m2": 0},
                {"department": "A", "year": 2025, "energy_kwh_m2": 100}]
        e2 = next(x for x in compute_scores(payload(rows), self.registry) if x["id"] == "E2")
        self.assertIsNone(e2["delta_pct"])

    def test_data_status_controls_color(self):
        for status in ["ikke_indtastet", "data_undervejs", "planlagt_2026"]:
            calc = calculate([{"id": "E2", "org_vaerdi": 100, "org_aar": 2025,
                               "benchmark_vaerdi": 105, "datastatus": status}], self.registry)[0]
            self.assertEqual(calc.trafiklys, "graa")

    def test_invalid_registry_is_rejected(self):
        original = json.loads(REGISTRY_PATH.read_text())
        mutations = [lambda xs: xs.append(copy.deepcopy(xs[0])),
                     lambda xs: xs[0].update(method="typo"),
                     lambda xs: xs[0].update(operator="typo"),
                     lambda xs: xs[0].update(benchmark=None),
                     lambda xs: xs[2].update(thresholds={}),
                     lambda xs: xs[2].update(thresholds={"green": 40, "yellow": 55})]
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                items = copy.deepcopy(original)
                mutation(items)
                path = Path(directory) / "registry.json"
                path.write_text(json.dumps(items))
                with self.assertRaises(ValueError):
                    load_registry(path)


class ParserTests(unittest.TestCase):
    def test_comparisons(self):
        for expression, value, expected in [
            ("ratio < 1.0 and ratio >= 0.90", .95, True),
            ("ratio >= 0.90 and ratio < 1.0", .90, True),
            ("ratio < 1.0 and ratio >= 0.90", 1, False),
            ("ratio > 1.0 and ratio <= 1.10", 1.1, True),
            ("value >= -2.5", -2.5, True), ("value < 0", 0, False),
            ("value == 0", 0, True), ("value != 0", 0, False),
            ("org_vaerdi != 'Ja'", "Nej", True),
            ("org_vaerdi == 'Ja'", "Ja", True), ("False", 1, False),
        ]:
            with self.subTest(expression=expression, value=value):
                self.assertEqual(_eval_threshold(_parse_threshold(expression), value), expected)

    def test_invalid_expressions(self):
        for expression in ["__import__('os')", "value > 1 trailing", "value ~~ 2", "", "value > nan"]:
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                _parse_threshold(expression)


class InputTests(unittest.TestCase):
    def test_invalid_root_types_return_errors(self):
        for data in [None, [], "text", 42, True]:
            with self.subTest(data=data):
                self.assertTrue(validate_payload(data))

    def test_required_fields_and_types(self):
        for data in [{}, {"organization": {}, "records": []},
                     payload([42]), payload([{"year": 2025}])]:
            self.assertTrue(validate_payload(data))
        for path, values in [("name", [None, "", "  ", 42]),
                             ("report_year", [None, "2025", True, 2025.5]),
                             ("year", [None, "2025", True, 2025.5]),
                             ("department", [None, "", "  ", 42])]:
            for value in values:
                with self.subTest(path=path, value=value):
                    data = payload()
                    if path == "name": data["organization"]["name"] = value
                    elif path == "report_year": data[path] = value
                    else: data["records"][0][path] = value
                    self.assertTrue(validate_payload(data))

    def test_indicator_types_ranges_and_nonfinite_numbers(self):
        for key, values in [("energy_kwh_m2", ["104", "104,5", True, -1, [], {}, math.nan, math.inf]),
                            ("waste_sorting_pct", [-1, 101]),
                            ("policy_compliance_flag", ["true", "Ja", 1, 0])]:
            for value in values:
                with self.subTest(key=key, value=value):
                    data = payload()
                    data["records"][0][key] = value
                    self.assertTrue(validate_payload(data))
        data = payload()
        data["records"][0].update(energy_kwh_m2=None, policy_compliance_flag=None)
        self.assertEqual(validate_payload(data), [])

    def test_duplicate_and_missing_report_year(self):
        row = {"department": "A", "year": 2025}
        self.assertTrue(validate_payload(payload([row, dict(row)])))
        self.assertTrue(validate_payload(payload([dict(row, year=2024)])))
        self.assertTrue(validate_payload(payload([row, dict(row, year=2026)])))
