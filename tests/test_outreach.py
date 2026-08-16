import unittest

from jepra.models import Lead
from jepra.outreach import Profile, pick_variant, render

PROFILE = Profile(
    sender_name="山田",
    company="Chill Freedom",
    product="papeterie japonaise",
    product_desc="carnets et stylos fabriqués au Japon",
    website="https://example.jp",
    reply_to="hello@example.jp",
    catalog_url="https://example.jp/catalogue",
    moq="300 EUR",
    lead_time="3 semaines",
)


def lead(**overrides):
    base = dict(name="Trait Papier", country="FR", city="Toulouse", rating=4.6, id=2)
    base.update(overrides)
    return Lead(**base)


class TestVariantAssignment(unittest.TestCase):
    def test_auto_is_deterministic(self):
        self.assertEqual(pick_variant(2), pick_variant(2))

    def test_auto_splits_evenly(self):
        variants = [pick_variant(i) for i in range(100)]
        self.assertEqual(variants.count("A"), 50)
        self.assertEqual(variants.count("B"), 50)

    def test_explicit_variant_wins(self):
        self.assertEqual(pick_variant(3, "A"), "A")


class TestRender(unittest.TestCase):
    def test_language_follows_country(self):
        _, _, lang, _ = render(lead(), PROFILE)
        self.assertEqual(lang, "fr")
        _, _, lang_jp, _ = render(lead(country="JP", city="東京"), PROFILE)
        self.assertEqual(lang_jp, "ja")

    def test_unsupported_language_falls_back_to_english(self):
        _, _, lang, _ = render(lead(country="NL", city="Amsterdam"), PROFILE)
        self.assertEqual(lang, "en")

    def test_no_placeholders_left_unfilled(self):
        for country, city in (("FR", "Toulouse"), ("GB", "London"), ("JP", "東京")):
            for variant in ("A", "B"):
                subject, body, _, _ = render(
                    lead(country=country, city=city), PROFILE, variant=variant)
                self.assertNotIn("{", subject)
                self.assertNotIn("{", body)
                self.assertIn(PROFILE.company, body)

    def test_opt_out_line_always_present(self):
        for template in ("intro", "followup"):
            for variant in ("A", "B"):
                _, body, _, _ = render(
                    lead(), PROFILE, template=template, variant=variant)
                self.assertIn("STOP", body)

    def test_high_rating_is_mentioned_in_variant_b(self):
        _, body, _, _ = render(lead(rating=4.9), PROFILE, variant="B")
        self.assertIn("4.9/5", body)

    def test_low_rating_is_not_mentioned(self):
        _, body, _, _ = render(lead(rating=2.6), PROFILE, variant="B")
        self.assertNotIn("/5", body)

    def test_missing_rating_is_safe(self):
        _, body, _, _ = render(lead(rating=None), PROFILE, variant="B")
        self.assertNotIn("None", body)

    def test_unknown_template_rejected(self):
        with self.assertRaises(SystemExit):
            render(lead(), PROFILE, template="nope")


if __name__ == "__main__":
    unittest.main()
