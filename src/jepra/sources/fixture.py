"""オフラインの固定データソース。

用途は2つ。
1. 客先デモ — 通信やAPIキーに依存せず、必ず同じ結果が出る。回線事故で商談が
   止まらないので、デモは常にこちらを使う。
2. テスト — 外部APIを叩かずにパイプライン全体を検証できる。

同梱データは実在するフランスの文房具店の公開情報（店名・住所・サイト）で、
メールアドレスは含めていない。エンリッチ工程のデモには擬似の発見結果を使う。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterator, List, Optional

from ..models import Lead
from ..normalize import slug
from .base import Query, Source

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")


def _load(country: str, category: str) -> List[Dict[str, Any]]:
    path = os.path.join(FIXTURE_DIR, "{}_{}.json".format(country.lower(), category))
    if not os.path.exists(path):
        available = sorted(
            f[:-5] for f in os.listdir(FIXTURE_DIR) if f.endswith(".json")
        ) if os.path.isdir(FIXTURE_DIR) else []
        raise SystemExit(
            "デモ用データがありません: {}_{}。用意があるのは: {}".format(
                country.lower(), category, ", ".join(available) or "なし"
            )
        )
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["records"]


def site_hints(lead: Lead) -> Optional[Dict[str, Any]]:
    """デモ時に「サイトを巡回したら何が見つかるか」を返す。

    fixture 以外のソースでは None（＝実際にサイトを取りに行く）。
    """
    if lead.source != "fixture" or not lead.website:
        return None
    for record in _load(lead.country or "FR", lead.category or "stationery"):
        if slug(record.get("name", "")) == slug(lead.name):
            return record.get("_site", {})
    return None


class FixtureSource(Source):
    name = "fixture"
    provides_rating = True

    def search(self, query: Query) -> Iterator[Lead]:
        records = _load(query.country, query.category)
        emitted = 0
        for record in records:
            if emitted >= query.limit:
                break
            if query.city and slug(record.get("city", "")) != slug(query.city):
                continue
            yield Lead(
                name=record["name"],
                country=query.country,
                city=record.get("city", ""),
                address=record.get("address", ""),
                category=query.category,
                website=record.get("website", ""),
                phone=record.get("phone", ""),
                rating=record.get("rating"),
                review_count=record.get("review_count"),
                notes=record.get("notes", ""),
                source=self.name,
                external_id="fixture/{}".format(slug(record["name"])),
            )
            emitted += 1
