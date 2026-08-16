import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from jepra import pipeline
from jepra.models import Event, Lead
from jepra.outreach import Profile
from jepra.store import Store


def days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).replace(
        microsecond=0).isoformat()


class FollowupTestCase(unittest.TestCase):
    def setUp(self):
        self.store = Store(os.path.join(tempfile.mkdtemp(), "t.db"))

    def tearDown(self):
        self.store.close()

    def seed(self, name, sent_days_ago=10, variant="A", **extra_events):
        lead_id = self.store.upsert_lead(
            Lead(name=name, city="Lyon", country="FR",
                 email="{}@example.test".format(name.lower())))
        self.store.add_event(Event(lead_id=lead_id, kind="sent", variant=variant,
                                   template="intro", ts=days_ago(sent_days_ago)))
        for kind, offset in extra_events.items():
            self.store.add_event(Event(lead_id=lead_id, kind=kind, variant=variant,
                                       template="intro", ts=days_ago(offset)))
        return lead_id


class TestAwaitingFollowup(FollowupTestCase):
    def test_picks_up_silent_leads_past_the_window(self):
        self.seed("silent", sent_days_ago=10)
        names = [l.name for l in self.store.leads_awaiting_followup(days=7)]
        self.assertEqual(names, ["silent"])

    def test_ignores_leads_inside_the_window(self):
        self.seed("recent", sent_days_ago=2)
        self.assertEqual(self.store.leads_awaiting_followup(days=7), [])

    def test_excludes_leads_that_replied(self):
        self.seed("answered", sent_days_ago=10, replied=8)
        self.assertEqual(self.store.leads_awaiting_followup(days=7), [])

    def test_excludes_bounced_and_unsubscribed(self):
        self.seed("gone", sent_days_ago=10, bounced=10)
        self.seed("optout", sent_days_ago=10, unsubscribed=9)
        self.assertEqual(self.store.leads_awaiting_followup(days=7), [])

    def test_excludes_leads_already_followed_up(self):
        lead_id = self.seed("chased", sent_days_ago=20)
        self.store.add_event(Event(lead_id=lead_id, kind="sent", variant="A",
                                   template="followup", ts=days_ago(5)))
        self.assertEqual(self.store.leads_awaiting_followup(days=7), [])

    def test_orders_oldest_first(self):
        self.seed("newer", sent_days_ago=8)
        self.seed("older", sent_days_ago=30)
        names = [l.name for l in self.store.leads_awaiting_followup(days=7)]
        self.assertEqual(names, ["older", "newer"])


class TestNeedingReply(FollowupTestCase):
    def test_lists_replies_not_yet_judged(self):
        self.seed("waiting", sent_days_ago=10, replied=3)
        pending = self.store.leads_needing_reply()
        self.assertEqual([e["lead"].name for e in pending], ["waiting"])

    def test_drops_leads_already_judged(self):
        self.seed("done", sent_days_ago=10, replied=3, positive=2)
        self.assertEqual(self.store.leads_needing_reply(), [])

    def test_drops_closed_leads(self):
        self.seed("nope", sent_days_ago=10, replied=3, closed=2)
        self.assertEqual(self.store.leads_needing_reply(), [])


class TestFollowupComposition(FollowupTestCase):
    def test_generates_followup_drafts(self):
        lead_id = self.seed("silent", sent_days_ago=10, variant="B")
        result = pipeline.followup(
            self.store, Profile(), days=7, report=pipeline.silent_reporter)
        self.assertEqual(result.drafted, 1)

        draft = self.store.drafts([lead_id])[lead_id]
        self.assertEqual(draft["template"], "followup")
        # 枝を初回送信から引き継がないと、返信がどちらの文面によるものか分からなくなる。
        self.assertEqual(draft["variant"], "B")

    def test_nothing_to_do_is_not_an_error(self):
        self.seed("recent", sent_days_ago=1)
        result = pipeline.followup(
            self.store, Profile(), days=7, report=pipeline.silent_reporter)
        self.assertEqual(result.drafted, 0)


if __name__ == "__main__":
    unittest.main()
