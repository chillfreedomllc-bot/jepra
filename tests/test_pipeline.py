import os
import tempfile
import unittest

from jepra import csvio, metrics, pipeline
from jepra.outreach import Profile
from jepra.sources import Query
from jepra.store import Store

CSV_SAMPLE = """﻿店舗名,都市,業態,評価,住所,WebサイトURL,電話番号(国際表記),対応ステータス,メールアドレス
La Papétheque Herriot,Lyon,文房具店,4.4,"42 Rue Herriot, 69001 Lyon",https://la-papetheque-enligne.com,+33 4 78 28 37 60,未着手,la-papetheque.lyon@wanadoo.fr
Papeterie République,Lyon,文房具店,2.6,"29 Rue Tupin, 69002 Lyon",,+33 4 78 37 71 96,サイト未確認,
,Lyon,文房具店,,,,,,
"""


class PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.dir, "t.db"))

    def tearDown(self):
        self.store.close()

    def path(self, name):
        return os.path.join(self.dir, name)


class TestFixtureRun(PipelineTestCase):
    def test_end_to_end_produces_drafts(self):
        pipeline.run(
            self.store,
            Query(country="FR", category="stationery", limit=20),
            Profile(),
            source_name="fixture",
            report=pipeline.silent_reporter,
        )
        self.assertGreater(self.store.count_leads(), 0)
        queued = self.store.leads(stage="queued")
        self.assertTrue(queued, "メール取得済みのリードが1件も文面生成されていない")
        drafts = self.store.drafts([l.id for l in queued])
        for lead in queued:
            self.assertIn(lead.id, drafts)
            self.assertTrue(drafts[lead.id]["subject"])

    def test_rerun_is_idempotent(self):
        query = Query(country="FR", category="stationery", limit=20)
        pipeline.collect(self.store, query, "fixture", pipeline.silent_reporter)
        first = self.store.count_leads()
        pipeline.collect(self.store, query, "fixture", pipeline.silent_reporter)
        self.assertEqual(self.store.count_leads(), first)

    def test_city_filter(self):
        pipeline.collect(
            self.store,
            Query(country="FR", city="Lyon", category="stationery", limit=50),
            "fixture", pipeline.silent_reporter,
        )
        self.assertTrue(self.store.count_leads() > 0)
        self.assertEqual({l.city for l in self.store.leads()}, {"Lyon"})


class TestCsvImport(PipelineTestCase):
    def test_imports_japanese_headers(self):
        path = self.path("legacy.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(CSV_SAMPLE)
        result = csvio.import_csv(self.store, path)
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["skipped"], 1)  # 店名が空の行

        leads = {l.name: l for l in self.store.leads()}
        herriot = leads["La Papétheque Herriot"]
        self.assertEqual(herriot.email, "la-papetheque.lyon@wanadoo.fr")
        self.assertEqual(herriot.phone, "+33478283760")
        self.assertEqual(herriot.rating, 4.4)
        self.assertEqual(herriot.city, "Lyon")

    def test_status_column_folded_into_notes(self):
        path = self.path("legacy.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(CSV_SAMPLE)
        csvio.import_csv(self.store, path)
        leads = {l.name: l for l in self.store.leads()}
        self.assertIn("対応ステータス", leads["La Papétheque Herriot"].notes)


class TestExport(PipelineTestCase):
    def test_export_writes_header_and_rows(self):
        pipeline.run(
            self.store, Query(country="FR", category="stationery", limit=10),
            Profile(), source_name="fixture", report=pipeline.silent_reporter,
        )
        out = self.path("out.csv")
        leads = self.store.leads()
        count = csvio.export_leads(self.store, out, leads)
        self.assertEqual(count, len(leads))

        # 本文には改行が入るので、行数ではなくCSVレコード数で数える。
        import csv as _csv

        with open(out, encoding="utf-8-sig", newline="") as fh:
            rows = list(_csv.reader(fh))
        self.assertIn("店名", rows[0])
        self.assertEqual(len(rows) - 1, len(leads))

    def test_multiline_body_survives_round_trip(self):
        pipeline.run(
            self.store, Query(country="FR", category="stationery", limit=20),
            Profile(), source_name="fixture", report=pipeline.silent_reporter,
        )
        out = self.path("out.csv")
        csvio.export_leads(self.store, out, self.store.leads(stage="queued"))

        import csv as _csv

        with open(out, encoding="utf-8-sig", newline="") as fh:
            rows = list(_csv.DictReader(fh))
        self.assertTrue(rows)
        self.assertIn("\n", rows[0]["本文"])


class TestSimulate(PipelineTestCase):
    def test_simulated_campaign_is_reproducible(self):
        from jepra.simulate import simulate_campaign

        other = Store(self.path("t2.db"))
        try:
            a = simulate_campaign(self.store, leads=120, seed=7)
            b = simulate_campaign(other, leads=120, seed=7)
            self.assertEqual(a, b)
        finally:
            other.close()

    def test_rates_land_near_configuration(self):
        from jepra.simulate import simulate_campaign

        simulate_campaign(self.store, leads=6000, seed=11)
        result = metrics.funnel(self.store).as_dict()
        # 設定は到達94% / 開封42%。乱数なので幅を持たせて検証する。
        self.assertAlmostEqual(result["delivery_rate"], 0.94, delta=0.02)
        self.assertAlmostEqual(result["open_rate"], 0.42, delta=0.03)

        groups = {g.label: g.as_dict() for g in metrics.breakdown(self.store, "variant")}
        self.assertAlmostEqual(groups["A"]["reply_rate"], 0.055, delta=0.015)
        self.assertAlmostEqual(groups["B"]["reply_rate"], 0.082, delta=0.015)


if __name__ == "__main__":
    unittest.main()
