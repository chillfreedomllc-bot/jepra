"""計測レイヤの動作確認用に、架空の配信実績を作る。

実データが溜まる前でも「何が測れるのか」を見せられるようにするためのもの。
生成されるリードは実在しない名前（Demo Shop NNN）で、全イベントの meta に
simulated=true が入る。実案件の DB とは必ず別ファイルで使うこと。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from .models import Event, Lead
from .store import Store

CITIES = ["Paris", "Lyon", "Marseille", "Bordeaux", "Toulouse", "Lille", "Nantes"]

# 実案件で観測されがちな水準に寄せた既定値。B の方が返信率が高い設定にしてある
# （A/B 比較が機能していることを見せるため）。
DEFAULTS = {
    "delivery_rate": 0.94,   # 到達率（1 - バウンス率）
    "open_rate": 0.42,       # 到達に対する開封率
    "reply_rate_A": 0.055,   # 条件提示型
    "reply_rate_B": 0.082,   # 店舗個別型
    "positive_share": 0.42,  # 返信のうち前向きな割合
    "meeting_share": 0.45,   # 前向き返信のうち商談化する割合
    "won_share": 0.25,       # 商談のうち成約する割合
}


def simulate_campaign(
    store: Store,
    leads: int = 400,
    seed: int = 20260816,
    template: str = "intro",
    rates: Dict[str, float] = None,
    country: str = "FR",
    category: str = "stationery",
) -> Dict[str, int]:
    """架空のリードと配信イベントを生成する。"""
    config = dict(DEFAULTS)
    config.update(rates or {})
    rng = random.Random(seed)
    start = datetime.now(timezone.utc) - timedelta(days=45)

    stats = {"leads": 0, "sent": 0, "bounced": 0, "opened": 0,
             "replied": 0, "positive": 0, "meeting": 0, "won": 0}

    for index in range(1, leads + 1):
        city = rng.choice(CITIES)
        lead = Lead(
            name="Demo Shop {:03d}".format(index),
            country=country,
            city=city,
            category=category,
            website="https://demo-{:03d}.example".format(index),
            email="contact@demo-{:03d}.example".format(index),
            email_source="simulated",
            email_confidence=0.9,
            rating=round(rng.uniform(3.4, 5.0), 1),
            review_count=rng.randint(8, 400),
            source="simulated",
            external_id="sim/{:03d}".format(index),
        )
        lead_id = store.upsert_lead(lead)
        stats["leads"] += 1

        variant = "A" if index % 2 == 0 else "B"
        sent_at = start + timedelta(days=rng.randint(0, 40), hours=rng.randint(8, 18))

        def log(kind: str, offset_hours: int) -> None:
            store.add_event(Event(
                lead_id=lead_id,
                kind=kind,
                ts=(sent_at + timedelta(hours=offset_hours)).replace(
                    microsecond=0).isoformat(),
                variant=variant,
                template=template,
                meta={"simulated": True},
            ))
            stats[kind] += 1

        log("sent", 0)
        if rng.random() > config["delivery_rate"]:
            log("bounced", 1)
            continue
        if rng.random() > config["open_rate"]:
            continue
        log("opened", 4)
        if rng.random() > config["reply_rate_{}".format(variant)] / config["open_rate"]:
            continue
        log("replied", 20)
        if rng.random() > config["positive_share"]:
            continue
        log("positive", 24)
        if rng.random() > config["meeting_share"]:
            continue
        log("meeting", 72)
        if rng.random() > config["won_share"]:
            continue
        log("won", 480)

    return stats
