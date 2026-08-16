"""Google Places API (New) からの収集。

評価(★)とレビュー件数が取れるのが最大の利点。営業では「評価4.3以上の店だけ」
のような絞り込みが返信率に直結するので、本番運用ではこちらを主にする。
GOOGLE_MAPS_API_KEY が必要（従量課金）。
"""

from __future__ import annotations

import os
import time
from typing import Iterator, Optional

from ..models import Lead
from .base import Query, Source, require

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"

# 課金は要求フィールド数で変わるので、営業に要るものだけ指定する。
FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.websiteUri",
    "places.internationalPhoneNumber",
    "places.rating",
    "places.userRatingCount",
    "places.location",
    "nextPageToken",
])


class GooglePlacesSource(Source):
    name = "google"
    provides_rating = True

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")

    def check_ready(self) -> Optional[str]:
        try:
            import requests  # noqa: F401
        except ImportError:
            return "requests 未インストール（pip install -e '.[live]'）"
        if not self.api_key:
            return "環境変数 GOOGLE_MAPS_API_KEY が未設定"
        return None

    def search(self, query: Query) -> Iterator[Lead]:
        problem = self.check_ready()
        if problem:
            raise SystemExit(problem)
        requests = require("requests")

        where = query.city or query.country
        text_query = "{} {}".format(query.cat.term(query.lang), where)
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        }
        body = {
            "textQuery": text_query,
            "languageCode": query.lang,
            "regionCode": query.country,
            "pageSize": 20,
        }

        emitted = 0
        page_token = None
        while emitted < query.limit:
            if page_token:
                body["pageToken"] = page_token
            response = requests.post(ENDPOINT, headers=headers, json=body, timeout=60)
            if response.status_code in (401, 403):
                raise SystemExit(
                    "Google Places の認証に失敗しました（{}）。"
                    "APIキーと Places API (New) の有効化を確認してください。".format(
                        response.status_code
                    )
                )
            response.raise_for_status()
            data = response.json()

            places = data.get("places", [])
            if not places:
                break
            for place in places:
                if emitted >= query.limit:
                    break
                name = (place.get("displayName") or {}).get("text", "")
                if not name:
                    continue
                location = place.get("location", {})
                yield Lead(
                    name=name,
                    country=query.country,
                    city=query.city,
                    address=place.get("formattedAddress", ""),
                    category=query.category,
                    website=place.get("websiteUri", ""),
                    phone=place.get("internationalPhoneNumber", ""),
                    rating=place.get("rating"),
                    review_count=place.get("userRatingCount"),
                    lat=location.get("latitude"),
                    lon=location.get("longitude"),
                    source=self.name,
                    external_id=place.get("id", ""),
                )
                emitted += 1

            page_token = data.get("nextPageToken")
            if not page_token:
                break
            # 次ページのトークンが有効になるまで少し待つ必要がある。
            time.sleep(2)
