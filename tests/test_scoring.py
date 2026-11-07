import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend import evaluator, scoring  # noqa: E402

with open(os.path.join(ROOT, "data", "checklist_default.json"), encoding="utf-8") as f:
    CL = json.load(f)
    CL["id"] = "test@1"


class ScoringTest(unittest.TestCase):
    def test_all_yes_is_100(self):
        a = {"c01": "yes", "c02": "yes", "c03": "yes", "c04": 20, "c05": "yes", "c06": 10, "c07": "yes", "c08": "no"}
        r = scoring.compute(CL, a)
        self.assertEqual(r["total"], 100.0)
        self.assertFalse(r["gross_error"])

    def test_na_redistribution_example(self):
        # 03 N/A, 04 = 15/20, 06 = 7/10, 07 = Нет -> 65.5 / 80 * 100 = 81.875 -> 81.88
        a = {"c01": "yes", "c02": "yes", "c03": "na", "c04": 15, "c05": "yes", "c06": 7, "c07": "no", "c08": "no"}
        r = scoring.compute(CL, a)
        self.assertEqual(r["applicable_weight"], 80)
        self.assertEqual(r["total"], 81.88)
        c01 = next(x for x in r["criteria"] if x["criterion_id"] == "c01")
        self.assertEqual(c01["effective_weight"], 12.5)

    def test_gross_flag_separate(self):
        a = {"c01": "yes", "c02": "yes", "c03": "yes", "c04": 20, "c05": "yes", "c06": 10, "c07": "yes", "c08": "yes"}
        r = scoring.compute(CL, a)
        self.assertEqual(r["total"], 100.0)
        self.assertTrue(r["gross_error"])

    def test_no_applicable(self):
        cl = {"name": "x", "criteria": [{"id": "a", "title": "a", "type": "binary", "weight": 10, "na_allowed": True}]}
        self.assertIsNone(scoring.compute(cl, {"a": "na"})["total"])

    def test_na_not_allowed_falls_back(self):
        c01 = CL["criteria"][0]
        self.assertEqual(scoring.normalize_answer(c01, "na")[0], "no")

    def test_scale_snaps(self):
        c04 = CL["criteria"][3]
        self.assertEqual(scoring.normalize_answer(c04, 13)[0], 15)
        self.assertEqual(scoring.normalize_answer(c04, "20")[0], 20)

    def test_sections(self):
        a = {"c01": "yes", "c02": "na", "c03": "na", "c04": "na", "c05": "yes", "c06": 10, "c07": "yes", "c08": "no"}
        r = scoring.compute(CL, a)
        self.assertEqual(r["total"], 100.0)
        start = next(s for s in r["sections"] if s["id"] == "start")
        self.assertEqual(start["percent"], 100.0)

    def test_validate(self):
        self.assertEqual(scoring.validate_checklist(CL), [])
        bad = json.loads(json.dumps(CL))
        bad["criteria"][3]["scale"] = [{"value": 5, "label": "x"}]
        self.assertTrue(scoring.validate_checklist(bad))


class HeuristicTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "data", "demo_dataset.json"), encoding="utf-8") as f:
            self.recs = {r["conversation_id"]: r for r in json.load(f)["data"]["records"]}

    def ev(self, cid):
        e = evaluator.evaluate(self.recs[cid], CL, mode="heuristic")
        return {r["criterion_id"]: r["answer"] for r in e["results"]}, e

    def test_good_chat(self):
        a, e = self.ev("demo-ru-001")
        self.assertEqual(a["c01"], "yes")
        self.assertEqual(a["c03"], "na")
        self.assertEqual(a["c07"], "yes")
        self.assertEqual(a["c08"], "no")

    def test_no_identification(self):
        a, _ = self.ev("demo-ru-002")
        self.assertEqual(a["c03"], "no")
        self.assertEqual(a["c01"], "no")

    def test_gross_bypass(self):
        a, e = self.ev("demo-ru-003")
        self.assertEqual(a["c08"], "yes")
        self.assertTrue(e["score"]["gross_error"])

    def test_abandoned(self):
        a, _ = self.ev("demo-ru-004")
        self.assertEqual(a["c04"], "na")
        self.assertEqual(a["c07"], "na")

    def test_kz(self):
        a, _ = self.ev("demo-kz-001")
        self.assertEqual(a["c01"], "yes")
        self.assertEqual(a["c03"], "yes")
        self.assertEqual(a["c05"], "yes")
        self.assertEqual(a["c06"], 10)  # ожидание с предупреждением

    def test_en_wrong_language(self):
        a, _ = self.ev("demo-en-002")
        self.assertEqual(a["c01"], "no")

    def test_en_complaint(self):
        a, _ = self.ev("demo-en-001")
        self.assertEqual(a["c05"], "no")
        self.assertIn(a["c06"], (0, 4))

    def test_call_iso(self):
        a, e = self.ev("demo-call-001")
        self.assertEqual(a["c03"], "yes")
        self.assertEqual(a["c07"], "yes")


if __name__ == "__main__":
    unittest.main()


class HumanRefsTest(unittest.TestCase):
    def test_zero_based_refs_become_ui_numbers(self):
        from backend.evaluator import human_refs
        self.assertEqual(human_refs("в [9] и [11], затем [0]"), "в #10 и #12, затем #1")
        self.assertIsNone(human_refs(None))
