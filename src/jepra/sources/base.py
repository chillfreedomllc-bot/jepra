"""収集ソースの共通インターフェースと業種辞書。

業種を1か所に定義しておくことで、対象を「フランスの文房具店」から
「ドイツのギフトショップ」に変えるのがフラグ2つで済む。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

from ..models import Lead

# 検索語をどの言語で投げるか。未登録の国は英語で検索する。
COUNTRY_LANG = {
    "FR": "fr", "BE": "fr", "CH": "fr", "DE": "de", "AT": "de",
    "IT": "it", "ES": "es", "PT": "pt", "NL": "nl",
    "GB": "en", "IE": "en", "US": "en", "CA": "en", "AU": "en",
    "JP": "ja", "KR": "ko", "TW": "zh", "SG": "en",
}


@dataclass(frozen=True)
class Category:
    """業種ひとつ。OSM のタグと、各言語での検索語を持つ。"""

    key: str
    label: str
    osm: List[Tuple[str, str]]          # Overpass 用の (key, value)
    google_type: str                    # Places API の includedType
    terms: Dict[str, str] = field(default_factory=dict)  # lang -> 検索語

    def term(self, lang: str) -> str:
        return self.terms.get(lang) or self.terms.get("en") or self.key


CATEGORIES: Dict[str, Category] = {
    c.key: c for c in [
        Category(
            key="stationery", label="文房具店",
            osm=[("shop", "stationery")], google_type="store",
            terms={"fr": "papeterie", "en": "stationery shop", "de": "Schreibwarengeschäft",
                   "it": "cartoleria", "es": "papelería", "nl": "kantoorboekhandel",
                   "pt": "papelaria", "ja": "文房具店"},
        ),
        Category(
            key="art_supplies", label="画材店",
            osm=[("shop", "art"), ("shop", "craft")], google_type="store",
            terms={"fr": "magasin beaux-arts", "en": "art supply store",
                   "de": "Künstlerbedarf", "it": "belle arti", "es": "bellas artes",
                   "ja": "画材店"},
        ),
        Category(
            key="bookshop", label="書店",
            osm=[("shop", "books")], google_type="book_store",
            terms={"fr": "librairie", "en": "bookshop", "de": "Buchhandlung",
                   "it": "libreria", "es": "librería", "ja": "書店"},
        ),
        Category(
            key="gift", label="ギフトショップ",
            osm=[("shop", "gift")], google_type="gift_shop",
            terms={"fr": "boutique cadeaux", "en": "gift shop", "de": "Geschenkeladen",
                   "it": "negozio di regali", "es": "tienda de regalos", "ja": "ギフトショップ"},
        ),
        Category(
            key="homeware", label="生活雑貨店",
            osm=[("shop", "houseware"), ("shop", "interior_decoration")],
            google_type="home_goods_store",
            terms={"fr": "magasin décoration maison", "en": "homeware shop",
                   "de": "Haushaltswaren", "it": "casalinghi", "es": "artículos del hogar",
                   "ja": "生活雑貨店"},
        ),
        Category(
            key="kitchenware", label="キッチン用品店",
            osm=[("shop", "kitchen"), ("shop", "houseware")], google_type="home_goods_store",
            terms={"fr": "magasin arts de la table", "en": "kitchenware shop",
                   "de": "Küchenbedarf", "it": "articoli da cucina", "ja": "キッチン用品店"},
        ),
        Category(
            key="tea_coffee", label="茶葉・コーヒー店",
            osm=[("shop", "tea"), ("shop", "coffee")], google_type="store",
            terms={"fr": "maison de thé", "en": "tea shop", "de": "Teeladen",
                   "it": "casa del tè", "es": "tienda de té", "ja": "日本茶専門店"},
        ),
        Category(
            key="deli", label="食料品専門店",
            osm=[("shop", "deli")], google_type="store",
            terms={"fr": "épicerie fine", "en": "delicatessen", "de": "Feinkostladen",
                   "it": "gastronomia", "es": "tienda gourmet", "ja": "食料品専門店"},
        ),
        Category(
            key="toys", label="玩具店",
            osm=[("shop", "toys")], google_type="store",
            terms={"fr": "magasin de jouets", "en": "toy shop", "de": "Spielwarengeschäft",
                   "it": "negozio di giocattoli", "ja": "玩具店"},
        ),
    ]
}


@dataclass
class Query:
    """収集条件。ソースをまたいで同じ形。"""

    country: str = "FR"
    city: str = ""
    category: str = "stationery"
    limit: int = 100

    def __post_init__(self) -> None:
        self.country = self.country.upper()
        if self.category not in CATEGORIES:
            raise SystemExit(
                "未知の業種 '{}'。使えるのは: {}".format(
                    self.category, ", ".join(sorted(CATEGORIES))
                )
            )

    @property
    def cat(self) -> Category:
        return CATEGORIES[self.category]

    @property
    def lang(self) -> str:
        return COUNTRY_LANG.get(self.country, "en")


class Source:
    """収集ソースの基底クラス。"""

    name = "base"
    #: 評価値（★）を返せるか。返せないソースは優先度付けの材料が減る。
    provides_rating = False

    def search(self, query: Query) -> Iterator[Lead]:
        raise NotImplementedError

    def check_ready(self) -> Optional[str]:
        """使えない理由を文字列で返す。使えるなら None。"""
        return None


def require(module: str, extra: str = "live") -> object:
    """任意依存を遅延 import する。demo だけ動かす人に requests を強制しない。"""
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError:
        raise SystemExit(
            "{} が必要です。`pip install -e '.[{}]'` を実行してください。".format(module, extra)
        )
