"""収集ソース。

`get_source(name)` で差し替える。国・都市・業種の指定は共通なので、
ソースを変えても呼び出し側（CLI や run パイプライン）は変わらない。
"""

from __future__ import annotations

from typing import Dict, Type

from .base import CATEGORIES, COUNTRY_LANG, Query, Source
from .fixture import FixtureSource
from .google_places import GooglePlacesSource
from .overpass import OverpassSource

_SOURCES: Dict[str, Type[Source]] = {
    "overpass": OverpassSource,
    "google": GooglePlacesSource,
    "fixture": FixtureSource,
}


def get_source(name: str) -> Source:
    try:
        return _SOURCES[name]()
    except KeyError:
        raise SystemExit(
            "未知のソース '{}'。使えるのは: {}".format(name, ", ".join(sorted(_SOURCES)))
        )


def source_names() -> list:
    return sorted(_SOURCES)


__all__ = [
    "CATEGORIES", "COUNTRY_LANG", "Query", "Source",
    "get_source", "source_names",
]
