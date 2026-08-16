import os
import tempfile
import unittest

from jepra.models import Event, Lead
from jepra.store import Store


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.dir, "t.db"))

    def tearDown(self):
        self.store.close()


class TestUpsert(StoreTestCase):
    def test_duplicate_merges_instead_of_inserting(self):
        first = self.store.upsert_lead(
            Lead(name="Trait Papier", city="Toulouse", website="https://trait.fr"))
        second = self.store.upsert_lead(
            Lead(name="TRAIT papier", city="Toulouse", website="http://trait.fr/"))
        self.assertEqual(first, second)
        self.assertEqual(self.store.count_leads(), 1)

    def test_merge_fills_blanks_without_clobbering(self):
        lead_id = self.store.upsert_lead(
            Lead(name="Trait", city="Toulouse", website="https://trait.fr",
                 email="contact@trait.fr"))
        # 再収集でメールが取れなかった場合でも、既存のアドレスは消えてはいけない。
        self.store.upsert_lead(
            Lead(name="Trait", city="Toulouse", website="https://trait.fr",
                 phone="+33561231117"))
        lead = self.store.get_lead(lead_id)
        self.assertEqual(lead.email, "contact@trait.fr")
        self.assertEqual(lead.phone, "+33561231117")


class TestStages(StoreTestCase):
    def test_stage_advances_but_never_regresses(self):
        lead_id = self.store.upsert_lead(Lead(name="A", city="Lyon"))
        self.store.set_stage(lead_id, "queued")
        self.store.set_stage(lead_id, "enriched")
        self.assertEqual(self.store.get_lead(lead_id).stage, "queued")

    def test_unknown_stage_rejected(self):
        lead_id = self.store.upsert_lead(Lead(name="A", city="Lyon"))
        with self.assertRaises(ValueError):
            self.store.set_stage(lead_id, "nope")


class TestEvents(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.lead_id = self.store.upsert_lead(Lead(name="A", city="Lyon"))

    def test_duplicate_event_ignored(self):
        first = self.store.add_event(
            Event(lead_id=self.lead_id, kind="sent", variant="A", template="intro"))
        second = self.store.add_event(
            Event(lead_id=self.lead_id, kind="sent", variant="A", template="intro"))
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(self.store.events(self.lead_id)), 1)

    def test_followup_with_other_template_is_recorded(self):
        self.store.add_event(
            Event(lead_id=self.lead_id, kind="sent", variant="A", template="intro"))
        self.assertTrue(self.store.add_event(
            Event(lead_id=self.lead_id, kind="sent", variant="A", template="followup")))

    def test_event_advances_stage(self):
        self.store.add_event(Event(lead_id=self.lead_id, kind="replied"))
        self.assertEqual(self.store.get_lead(self.lead_id).stage, "replied")

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add_event(Event(lead_id=self.lead_id, kind="nope"))


if __name__ == "__main__":
    unittest.main()
