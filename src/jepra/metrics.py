"""ファネル集計と A/B 比較。

ここが商品の説得力そのもの。「リストを作りました」ではなく
「1,000通出して到達94%、返信7.2%、うち商談13件」と言えるかどうかで
提案の通りやすさが変わる。

用語:
  到達率 = (送信 - バウンス) / 送信
  返信率 = 返信 / 到達      ← 分母を送信ではなく到達にする。届いていない宛先を
                              分母に入れると文面の良し悪しが測れなくなるため。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .store import Store

# 集計軸として許可する列。SQL に直接埋めるのでホワイトリストで縛る。
DIMENSIONS = {
    "variant": "e.variant",
    "template": "e.template",
    "city": "l.city",
    "category": "l.category",
    "country": "l.country",
    "source": "l.source",
}

FUNNEL_KINDS = ("sent", "bounced", "opened", "replied", "positive", "meeting", "won")


@dataclass
class Funnel:
    """1セグメントぶんのファネル。"""

    label: str = "all"
    discovered: int = 0
    contactable: int = 0
    counts: Dict[str, int] = field(default_factory=dict)

    @property
    def sent(self) -> int:
        return self.counts.get("sent", 0)

    @property
    def delivered(self) -> int:
        return max(self.sent - self.counts.get("bounced", 0), 0)

    def rate(self, numerator: str, denominator: str) -> Optional[float]:
        den = self._value(denominator)
        if not den:
            return None
        return self._value(numerator) / den

    def _value(self, key: str) -> int:
        if key == "delivered":
            return self.delivered
        if key == "discovered":
            return self.discovered
        if key == "contactable":
            return self.contactable
        return self.counts.get(key, 0)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "discovered": self.discovered,
            "contactable": self.contactable,
            "sent": self.sent,
            "bounced": self.counts.get("bounced", 0),
            "delivered": self.delivered,
            "opened": self.counts.get("opened", 0),
            "replied": self.counts.get("replied", 0),
            "positive": self.counts.get("positive", 0),
            "meeting": self.counts.get("meeting", 0),
            "won": self.counts.get("won", 0),
            "contact_rate": self.rate("contactable", "discovered"),
            "delivery_rate": self.rate("delivered", "sent"),
            "open_rate": self.rate("opened", "delivered"),
            "reply_rate": self.rate("replied", "delivered"),
            "positive_rate": self.rate("positive", "replied"),
            "meeting_rate": self.rate("meeting", "delivered"),
        }


def _where(filters: Dict[str, Any], alias: str = "l") -> Tuple[str, List[Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    for column in ("city", "category", "country", "source"):
        value = filters.get(column)
        if value:
            clauses.append("{}.{} = ?".format(alias, column))
            params.append(value.upper() if column == "country" else value)
    return (" AND " + " AND ".join(clauses) if clauses else ""), params


def funnel(store: Store, **filters: Any) -> Funnel:
    """全体（またはフィルタ後）のファネル。"""
    where, params = _where(filters)

    row = store.conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN l.email != '' THEN 1 ELSE 0 END) AS contactable "
        "FROM leads l WHERE 1=1" + where,
        params,
    ).fetchone()

    result = Funnel(
        label=filters.get("label", "all"),
        discovered=int(row["total"] or 0),
        contactable=int(row["contactable"] or 0),
    )
    for kind_row in store.conn.execute(
        "SELECT e.kind AS kind, COUNT(DISTINCT e.lead_id) AS n "
        "FROM events e JOIN leads l ON l.id = e.lead_id "
        "WHERE 1=1" + where + " GROUP BY e.kind",
        params,
    ):
        result.counts[kind_row["kind"]] = int(kind_row["n"])
    return result


def breakdown(store: Store, dimension: str, **filters: Any) -> List[Funnel]:
    """指定軸ごとのファネル。"""
    if dimension not in DIMENSIONS:
        raise SystemExit(
            "未知の集計軸 '{}'。使えるのは: {}".format(
                dimension, ", ".join(sorted(DIMENSIONS))
            )
        )
    column = DIMENSIONS[dimension]
    where, params = _where(filters)

    buckets: Dict[str, Funnel] = {}

    # 送信より手前の軸（都市・業種など）はリード表から数える。
    if column.startswith("l."):
        for row in store.conn.execute(
            "SELECT {col} AS bucket, COUNT(*) AS total, "
            "SUM(CASE WHEN l.email != '' THEN 1 ELSE 0 END) AS contactable "
            "FROM leads l WHERE 1=1{where} GROUP BY bucket".format(col=column, where=where),
            params,
        ):
            label = row["bucket"] or "(未設定)"
            buckets[label] = Funnel(
                label=label,
                discovered=int(row["total"] or 0),
                contactable=int(row["contactable"] or 0),
            )

    for row in store.conn.execute(
        "SELECT {col} AS bucket, e.kind AS kind, COUNT(DISTINCT e.lead_id) AS n "
        "FROM events e JOIN leads l ON l.id = e.lead_id "
        "WHERE 1=1{where} GROUP BY bucket, e.kind".format(col=column, where=where),
        params,
    ):
        label = row["bucket"] or "(未設定)"
        bucket = buckets.setdefault(label, Funnel(label=label))
        bucket.counts[row["kind"]] = int(row["n"])

    return sorted(buckets.values(), key=lambda f: (-f.sent, -f.discovered, f.label))


# ---------- A/B の有意差 ----------


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def two_proportion_test(
    hits_a: int, total_a: int, hits_b: int, total_b: int
) -> Optional[Dict[str, float]]:
    """2群の比率の差の検定（z検定）。母数が足りなければ None。"""
    if total_a <= 0 or total_b <= 0:
        return None
    p_a = hits_a / total_a
    p_b = hits_b / total_b
    pooled = (hits_a + hits_b) / (total_a + total_b)
    se = math.sqrt(pooled * (1 - pooled) * (1 / total_a + 1 / total_b))
    if se == 0:
        return None
    z = (p_a - p_b) / se
    return {
        "rate_a": p_a,
        "rate_b": p_b,
        "lift": p_a - p_b,
        "z": z,
        "p_value": 2 * (1 - _normal_cdf(abs(z))),
    }


def ab_compare(
    store: Store, metric: str = "replied", dimension: str = "variant", **filters: Any
) -> Optional[Dict[str, Any]]:
    """2枝の比較結果。枝が2つちょうどのときだけ返す。"""
    groups = breakdown(store, dimension, **filters)
    groups = [g for g in groups if g.sent > 0]
    if len(groups) != 2:
        return None
    a, b = sorted(groups, key=lambda g: g.label)
    stats = two_proportion_test(
        a._value(metric), a.delivered, b._value(metric), b.delivered
    )
    if stats is None:
        return None
    stats.update({"label_a": a.label, "label_b": b.label, "metric": metric,
                  "n_a": a.delivered, "n_b": b.delivered})
    return stats


def sample_size_note(p_value: Optional[float], n_a: int, n_b: int) -> str:
    """提案書にそのまま書ける日本語の但し書き。"""
    if p_value is None:
        return "判定不能（送信数が不足）"
    if min(n_a, n_b) < 30:
        return "参考値（各群30通未満のため判断材料としては弱い）"
    if p_value < 0.05:
        return "有意差あり（p<0.05）"
    if p_value < 0.10:
        return "傾向あり（p<0.10）。追加送信で確認の余地あり"
    return "有意差なし。現時点では文面差より宛先選定の影響が大きい可能性"
