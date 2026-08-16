import unittest

from jepra.normalize import (
    address_key, dedupe_key, domain_of, normalize_phone, normalize_url, slug,
)


class TestSlug(unittest.TestCase):
    def test_strips_accents_and_punctuation(self):
        self.assertEqual(slug("Rougier & Plé"), "rougier-ple")
        self.assertEqual(slug("Rougier&Plé"), "rougier-ple")

    def test_drops_articles_and_legal_forms(self):
        self.assertEqual(slug("La Papétheque"), "papetheque")
        self.assertEqual(slug("Papetheque SARL"), "papetheque")

    def test_empty(self):
        self.assertEqual(slug(""), "")
        self.assertEqual(slug(None), "")


class TestUrl(unittest.TestCase):
    def test_adds_scheme_and_strips_trailing_slash(self):
        self.assertEqual(normalize_url("trait.fr/"), "https://trait.fr")

    def test_lowercases_host_only(self):
        self.assertEqual(
            normalize_url("HTTPS://WWW.Example.FR/Contact/"),
            "https://www.example.fr/Contact",
        )

    def test_domain_drops_www(self):
        self.assertEqual(domain_of("https://www.rougier-ple.fr/pro"), "rougier-ple.fr")
        self.assertEqual(domain_of(""), "")


class TestPhone(unittest.TestCase):
    def test_compacts_international(self):
        self.assertEqual(normalize_phone("+33 4 78 28 37 60"), "+33478283760")

    def test_converts_double_zero_prefix(self):
        self.assertEqual(normalize_phone("0033 4 78 28 37 60"), "+33478283760")

    def test_local_number_with_country_code(self):
        self.assertEqual(normalize_phone("04 78 28 37 60", "33"), "+33478283760")

    def test_keeps_unparseable_input(self):
        self.assertEqual(normalize_phone("sur rendez-vous"), "sur rendez-vous")


class TestAddressKey(unittest.TestCase):
    def test_house_number_and_postcode(self):
        self.assertEqual(address_key("26 Pass. Molière, 75003 Paris"), "26|75003")

    def test_four_digit_house_number(self):
        self.assertEqual(
            address_key("1464 Av. de l'Europe, 34170 Castelnau-le-Lez"), "1464|34170")

    def test_no_leading_house_number(self):
        self.assertEqual(
            address_key("Promenade Sainte-Catherine, 9 Rue Margaux, 33000 Bordeaux"),
            "|33000")

    def test_empty(self):
        self.assertEqual(address_key(""), "")


class TestDedupeKey(unittest.TestCase):
    def test_same_shop_written_differently_collapses(self):
        a = dedupe_key("Rougier & Plé", "Paris", "https://www.rougier-ple.fr/",
                       "15 Bd des Filles du Calvaire, 75003 Paris")
        b = dedupe_key("Rougier & Plé (Filles du Calvaire)", "paris",
                       "http://rougier-ple.fr", "15 Bd des Filles du Calvaire 75003")
        self.assertEqual(a, b)

    def test_chain_branches_in_same_city_stay_separate(self):
        # 同一ドメイン・同一都市でも別住所なら別店舗。ここを潰すと支店が消える。
        keys = {
            dedupe_key("Rougier & Plé", "Paris", "https://www.rougier-ple.fr", address)
            for address in (
                "15 Bd des Filles du Calvaire, 75003 Paris",
                "108 Bd Saint-Germain, 75006 Paris",
                "30 Av. d'Italie, 75013 Paris",
                "157 Rue Lecourbe, 75015 Paris",
            )
        }
        self.assertEqual(len(keys), 4)

    def test_chain_branches_in_different_cities_stay_separate(self):
        lyon = dedupe_key("Rougier & Plé", "Lyon", "https://www.rougier-ple.fr")
        nice = dedupe_key("Rougier & Plé", "Nice", "https://www.rougier-ple.fr")
        self.assertNotEqual(lyon, nice)

    def test_shared_hosting_domain_does_not_merge_shops(self):
        # sites.google.com のような共有ドメインでドメインだけ見ると別の店が潰れる。
        a = dedupe_key("Junku", "Paris", "https://sites.google.com/junku",
                       "18 Rue des Pyramides, 75001 Paris")
        b = dedupe_key("Autre Papeterie", "Paris", "https://sites.google.com/autre",
                       "5 Rue de Rivoli, 75004 Paris")
        self.assertNotEqual(a, b)

    def test_falls_back_to_name_when_no_site(self):
        self.assertEqual(
            dedupe_key("Papeterie République", "Lyon", "", "29 Rue Tupin, 69002 Lyon"),
            dedupe_key("papeterie republique", "lyon", "", "29 Rue Tupin 69002"),
        )


if __name__ == "__main__":
    unittest.main()
