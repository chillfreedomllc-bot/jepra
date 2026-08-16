"""データモデル。

Lead が1店舗、Event が1店舗に起きた出来事（送信/バウンス/返信…）。
ステータスを Lead に直接書き換えるのではなくイベントを積むことで、
「いつ何通出して何件返ってきたか」を後から何度でも集計し直せる。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from typing import Any, Dict, Optional

from .normalize import clean_text, dedupe_key, normalize_phone, normalize_url

# アプローチの進捗。数値は順序を持ち、後退しない（既存より小さい値では上書きしない）。
STAGES = {
    "discovered": 0,   # 収集しただけ
    "enriched": 10,    # サイトを見た（メール有無が確定）
    "queued": 20,      # 文面を作って送信待ち
    "sent": 30,        # 送信済み
    "bounced": 35,     # 宛先不達（到達率の分母から外れる）
    "opened": 40,      # 開封
    "replied": 50,     # 返信あり
    "positive": 60,    # 前向きな返信
    "meeting": 70,     # 商談化
    "won": 80,         # 成約
    "closed": 90,      # 打ち切り（不要・不通・辞退）
    "unsubscribed": 95,  # 配信停止要求（再送禁止）
}

# 到達率などの計算に使うイベント種別。stage と同名にして対応を分かりやすくする。
EVENT_KINDS = (
    "sent", "bounced", "opened", "replied", "positive",
    "meeting", "won", "closed", "unsubscribed",
)


@dataclass
class Lead:
    """1店舗ぶんのリード。"""

    name: str
    country: str = ""
    city: str = ""
    address: str = ""
    category: str = ""
    website: str = ""
    phone: str = ""
    email: str = ""
    email_source: str = ""       # どうやってメールを得たか（mailto / text / pattern など）
    email_confidence: float = 0.0
    contact_form_url: str = ""   # メールが無くフォームだけある店の受け皿
    rating: Optional[float] = None
    review_count: Optional[int] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    source: str = ""             # overpass / google / fixture / legacy-csv
    external_id: str = ""        # ソース側のID（再収集時の突き合わせ用）
    stage: str = "discovered"
    notes: str = ""
    id: Optional[int] = None
    dedupe: str = ""

    def __post_init__(self) -> None:
        self.name = clean_text(self.name)
        self.city = clean_text(self.city)
        self.address = clean_text(self.address)
        self.country = clean_text(self.country).upper()
        self.website = normalize_url(self.website)
        self.phone = normalize_phone(self.phone)
        self.email = clean_text(self.email).lower()
        self.contact_form_url = normalize_url(self.contact_form_url)
        if not self.dedupe:
            self.dedupe = dedupe_key(self.name, self.city, self.website, self.address)

    @property
    def contactable(self) -> bool:
        """メールでアプローチできるか。フォームのみの店は別動線なので False。"""
        return bool(self.email)

    def to_row(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Lead":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in row.items() if k in known})


@dataclass
class Event:
    """リードに起きた出来事。"""

    lead_id: int
    kind: str
    ts: str = ""                 # ISO8601。空ならストアが現在時刻を入れる
    variant: str = ""            # A/B テストの枝
    template: str = ""           # 使った文面テンプレート名
    channel: str = "email"
    meta: Dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None

    def meta_json(self) -> str:
        return json.dumps(self.meta, ensure_ascii=False, sort_keys=True)
