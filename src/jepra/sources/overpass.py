"""OpenStreetMap (Overpass API) からの収集。

APIキー不要・無料で、住所/サイト/電話に加えて email タグが入っていることもある。
弱点は評価(★)が無いことと、店舗の網羅性が地域によってムラがあること。
まず overpass で拾い、足りなければ google で補うのが安上がり。
"""

from __future__ import annotations

import time
from typing import Dict, Iterator, Optional

from ..models import Lead
from .base import Query, Source, require

ENDPOINT = "https://overpass-api.de/api/interpreter"
USER_AGENT = "jepra/0.1 (B2B lead research; contact via repository owner)"


def _build_query(query: Query) -> str:
    """Overpass QL を組み立てる。

    都市指定があれば行政界（admin_level 7-8 = commune 相当）で絞り、
    無ければ ISO 国コードで国全体を対象にする。
    """
    if query.city:
        area = (
            'area["name"="{city}"]["boundary"="administrative"]'
            '["admin_level"~"^(6|7|8)$"]->.searchArea;'
        ).format(city=query.city)
    else:
        area = (
            'area["ISO3166-1"="{cc}"]["admin_level"="2"]->.searchArea;'
        ).format(cc=query.country)

    selectors = "\n  ".join(
        'nwr["{k}"="{v}"](area.searchArea);'.format(k=k, v=v) for k, v in query.cat.osm
    )
    return (
        "[out:json][timeout:90];\n"
        "{area}\n"
        "(\n  {selectors}\n);\n"
        "out center tags {limit};\n"
    ).format(area=area, selectors=selectors, limit=max(query.limit * 3, 50))


def _address(tags: Dict[str, str]) -> str:
    parts = [
        " ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street")) if p),
        " ".join(p for p in (tags.get("addr:postcode"), tags.get("addr:city")) if p),
    ]
    return ", ".join(p for p in parts if p)


class OverpassSource(Source):
    name = "overpass"
    provides_rating = False

    def __init__(self, endpoint: str = ENDPOINT, pause: float = 1.0):
        self.endpoint = endpoint
        self.pause = pause

    def search(self, query: Query) -> Iterator[Lead]:
        requests = require("requests")
        payload = _build_query(query)
        response = requests.post(
            self.endpoint,
            data={"data": payload},
            headers={"User-Agent": USER_AGENT},
            timeout=120,
        )
        if response.status_code == 429:
            raise SystemExit("Overpass にレート制限されました。数分おいて再実行してください。")
        response.raise_for_status()
        # Overpass は共有インフラなので、連続実行時は必ず間を空ける。
        time.sleep(self.pause)

        emitted = 0
        for element in response.json().get("elements", []):
            if emitted >= query.limit:
                break
            tags = element.get("tags", {})
            name = tags.get("name")
            if not name:
                continue  # 無名のノードは営業対象にならない
            center = element.get("center", {})
            yield Lead(
                name=name,
                country=query.country,
                city=tags.get("addr:city") or query.city,
                address=_address(tags),
                category=query.category,
                website=tags.get("website") or tags.get("contact:website") or tags.get("url", ""),
                phone=tags.get("phone") or tags.get("contact:phone", ""),
                email=tags.get("email") or tags.get("contact:email", ""),
                email_source="osm-tag" if (tags.get("email") or tags.get("contact:email")) else "",
                email_confidence=0.9 if (tags.get("email") or tags.get("contact:email")) else 0.0,
                lat=element.get("lat", center.get("lat")),
                lon=element.get("lon", center.get("lon")),
                source=self.name,
                external_id="{}/{}".format(element.get("type"), element.get("id")),
            )
            emitted += 1

    def check_ready(self) -> Optional[str]:
        try:
            import requests  # noqa: F401
        except ImportError:
            return "requests 未インストール（pip install -e '.[live]'）"
        return None
