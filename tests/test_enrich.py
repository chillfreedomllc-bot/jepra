import unittest

from jepra.enrich.website import _contact_urls, _pick_best, _score
from jepra.models import Lead


class TestEmailScoring(unittest.TestCase):
    def test_own_domain_beats_freemail(self):
        own = _score("contact@trait.fr", "mailto", "trait.fr")
        free = _score("trait.papeterie@gmail.com", "mailto", "trait.fr")
        self.assertGreater(own, free)

    def test_mailto_beats_body_text(self):
        self.assertGreater(
            _score("contact@trait.fr", "mailto", "trait.fr"),
            _score("contact@trait.fr", "text", "trait.fr"),
        )

    def test_picks_best_candidate(self):
        email, source, score = _pick_best(
            [("info@wanadoo.fr", "text"), ("contact@trait.fr", "mailto")],
            "trait.fr",
        )
        self.assertEqual(email, "contact@trait.fr")
        self.assertEqual(source, "mailto")
        self.assertGreater(score, 0.9)

    def test_blocklist_filters_noise(self):
        email, _, _ = _pick_best(
            [("no-reply@trait.fr", "mailto"), ("logo@2x.png", "text")], "trait.fr")
        self.assertEqual(email, "")

    def test_normalizes_case_and_trailing_punctuation(self):
        email, _, _ = _pick_best([("Contact@Trait.FR.", "mailto")], "trait.fr")
        self.assertEqual(email, "contact@trait.fr")


class TestContactUrls(unittest.TestCase):
    def test_selects_contact_pages_on_same_domain(self):
        urls = _contact_urls(
            "https://trait.fr",
            ["/contact", "/nous-contacter", "/panier",
             "https://facebook.com/contact", "/mentions-legales"],
            limit=3,
        )
        self.assertEqual(urls, [
            "https://trait.fr/contact",
            "https://trait.fr/nous-contacter",
            "https://trait.fr/mentions-legales",
        ])

    def test_ignores_other_domains(self):
        urls = _contact_urls("https://trait.fr", ["https://other.fr/contact"], limit=3)
        self.assertEqual(urls, [])

    def test_deduplicates_fragments(self):
        urls = _contact_urls(
            "https://trait.fr", ["/contact#form", "/contact"], limit=3)
        self.assertEqual(urls, ["https://trait.fr/contact"])


class TestFixtureEnrichment(unittest.TestCase):
    def test_fixture_lead_resolves_offline(self):
        from jepra.enrich import enrich_lead

        lead = Lead(
            name="Maison Paon - Maison de haute papeterie",
            country="FR", city="Angers", category="stationery",
            website="https://maisonpaon.fr", source="fixture",
        )
        result = enrich_lead(lead)
        self.assertTrue(result.found)
        self.assertEqual(result.email, "commande@maisonpaon.fr")

    def test_lead_without_website_is_skipped(self):
        from jepra.enrich import enrich_lead

        result = enrich_lead(Lead(name="X", source="fixture"))
        self.assertFalse(result.found)
        self.assertEqual(result.error, "no-website")


if __name__ == "__main__":
    unittest.main()
