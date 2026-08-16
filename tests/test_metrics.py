import os
import tempfile
import unittest

from jepra import metrics
from jepra.models import Event, Lead
from jepra.store import Store


def seed(store, sent, bounced=0, replied=0, variant="A", city="Lyon"):
    """sent 通送り、うち bounced 通不達、replied 通返信という状態を作る。"""
    for index in range(sent):
        lead_id = store.upsert_lead(
            Lead(name="{}-{}-{}".format(variant, city, index), city=city,
                 email="x{}@example.test".format(index)))
        store.add_event(Event(lead_id=lead_id, kind="sent",
                              variant=variant, template="intro"))
        if index < bounced:
            store.add_event(Event(lead_id=lead_id, kind="bounced",
                                  variant=variant, template="intro"))
        elif index < bounced + replied:
            store.add_event(Event(lead_id=lead_id, kind="replied",
                                  variant=variant, template="intro"))


class MetricsTestCase(unittest.TestCase):
    def setUp(self):
        self.store = Store(os.path.join(tempfile.mkdtemp(), "t.db"))

    def tearDown(self):
        self.store.close()


class TestFunnel(MetricsTestCase):
    def test_rates(self):
        seed(self.store, sent=100, bounced=10, replied=9)
        result = metrics.funnel(self.store).as_dict()
        self.assertEqual(result["sent"], 100)
        self.assertEqual(result["delivered"], 90)
        self.assertAlmostEqual(result["delivery_rate"], 0.90)
        # 返信率の分母は送信ではなく到達。
        self.assertAlmostEqual(result["reply_rate"], 9 / 90)

    def test_rate_is_none_without_denominator(self):
        self.store.upsert_lead(Lead(name="A", city="Lyon"))
        self.assertIsNone(metrics.funnel(self.store).as_dict()["reply_rate"])

    def test_contact_rate(self):
        self.store.upsert_lead(Lead(name="A", city="Lyon", email="a@example.test"))
        self.store.upsert_lead(Lead(name="B", city="Lyon"))
        self.assertAlmostEqual(
            metrics.funnel(self.store).as_dict()["contact_rate"], 0.5)


class TestBreakdown(MetricsTestCase):
    def test_split_by_variant(self):
        seed(self.store, sent=50, replied=2, variant="A")
        seed(self.store, sent=50, replied=8, variant="B")
        groups = {g.label: g for g in metrics.breakdown(self.store, "variant")}
        self.assertAlmostEqual(groups["A"].as_dict()["reply_rate"], 2 / 50)
        self.assertAlmostEqual(groups["B"].as_dict()["reply_rate"], 8 / 50)

    def test_split_by_city_counts_uncontacted_leads(self):
        seed(self.store, sent=10, city="Lyon")
        self.store.upsert_lead(Lead(name="Solo", city="Nice"))
        groups = {g.label: g for g in metrics.breakdown(self.store, "city")}
        self.assertEqual(groups["Nice"].discovered, 1)
        self.assertEqual(groups["Nice"].sent, 0)

    def test_unknown_dimension_rejected(self):
        with self.assertRaises(SystemExit):
            metrics.breakdown(self.store, "'; DROP TABLE leads;--")


class TestSignificance(MetricsTestCase):
    def test_detects_large_difference(self):
        seed(self.store, sent=500, replied=10, variant="A")
        seed(self.store, sent=500, replied=60, variant="B")
        result = metrics.ab_compare(self.store)
        self.assertLess(result["p_value"], 0.05)
        self.assertIn("有意差あり", metrics.sample_size_note(
            result["p_value"], result["n_a"], result["n_b"]))

    def test_small_sample_is_flagged_as_weak(self):
        seed(self.store, sent=10, replied=1, variant="A")
        seed(self.store, sent=10, replied=3, variant="B")
        result = metrics.ab_compare(self.store)
        self.assertIn("参考値", metrics.sample_size_note(
            result["p_value"], result["n_a"], result["n_b"]))

    def test_none_when_only_one_variant(self):
        seed(self.store, sent=20, replied=2, variant="A")
        self.assertIsNone(metrics.ab_compare(self.store))


if __name__ == "__main__":
    unittest.main()
