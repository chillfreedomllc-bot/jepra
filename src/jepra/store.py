"""SQLite ストア。

CSV を手で持ち回すと「どれが最新か」が分からなくなるので、正はこの DB に置く。
CSV は入口（取り込み）と出口（納品）だけで使う。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from .models import EVENT_KINDS, STAGES, Event, Lead

DEFAULT_DB = os.environ.get("JEPRA_DB", "jepra.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe            TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    country           TEXT DEFAULT '',
    city              TEXT DEFAULT '',
    address           TEXT DEFAULT '',
    category          TEXT DEFAULT '',
    website           TEXT DEFAULT '',
    phone             TEXT DEFAULT '',
    email             TEXT DEFAULT '',
    email_source      TEXT DEFAULT '',
    email_confidence  REAL DEFAULT 0,
    contact_form_url  TEXT DEFAULT '',
    rating            REAL,
    review_count      INTEGER,
    lat               REAL,
    lon               REAL,
    source            TEXT DEFAULT '',
    external_id       TEXT DEFAULT '',
    stage             TEXT DEFAULT 'discovered',
    notes             TEXT DEFAULT '',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leads_stage    ON leads(stage);
CREATE INDEX IF NOT EXISTS idx_leads_city     ON leads(city);
CREATE INDEX IF NOT EXISTS idx_leads_category ON leads(category);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id   INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    kind      TEXT NOT NULL,
    ts        TEXT NOT NULL,
    variant   TEXT DEFAULT '',
    template  TEXT DEFAULT '',
    channel   TEXT DEFAULT 'email',
    meta      TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);

-- 同じ種別のイベントを二重計上しないための番人。
-- 再送は variant を変えれば別行として記録できる。
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_unique
    ON events(lead_id, kind, variant, template);

CREATE TABLE IF NOT EXISTS drafts (
    lead_id   INTEGER PRIMARY KEY REFERENCES leads(id) ON DELETE CASCADE,
    lang      TEXT NOT NULL,
    variant   TEXT NOT NULL,
    template  TEXT NOT NULL,
    subject   TEXT NOT NULL,
    body      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# 上書きしてはいけない列（DB側の運用結果を収集結果で潰さないため）。
_PROTECTED = {"id", "dedupe", "stage", "created_at", "updated_at"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, path: str = DEFAULT_DB):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---------- leads ----------

    def upsert_lead(self, lead: Lead) -> int:
        """新規なら挿入、既存なら「空欄を埋める」方向にだけ更新する。

        再収集のたびに手で入れたメールアドレスが消える、という事故を防ぐため、
        既存の非空値は新しい空値で上書きしない。
        """
        existing = self.conn.execute(
            "SELECT * FROM leads WHERE dedupe = ?", (lead.dedupe,)
        ).fetchone()
        ts = now_iso()
        row = lead.to_row()

        if existing is None:
            row.pop("id", None)
            row["created_at"] = ts
            row["updated_at"] = ts
            cols = ", ".join(row)
            marks = ", ".join("?" for _ in row)
            cur = self.conn.execute(
                "INSERT INTO leads ({}) VALUES ({})".format(cols, marks),
                tuple(row.values()),
            )
            self.conn.commit()
            return int(cur.lastrowid)

        updates: Dict[str, Any] = {}
        for key, value in row.items():
            if key in _PROTECTED or value in (None, "", 0.0):
                continue
            if not existing[key]:
                updates[key] = value
        if updates:
            updates["updated_at"] = ts
            assignments = ", ".join("{} = ?".format(k) for k in updates)
            self.conn.execute(
                "UPDATE leads SET {} WHERE id = ?".format(assignments),
                tuple(updates.values()) + (existing["id"],),
            )
            self.conn.commit()
        return int(existing["id"])

    def set_stage(self, lead_id: int, stage: str) -> None:
        """ステージを進める。既に先へ進んでいる場合は何もしない。"""
        if stage not in STAGES:
            raise ValueError("unknown stage: {}".format(stage))
        row = self.conn.execute(
            "SELECT stage FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()
        if row is None:
            raise KeyError("no such lead: {}".format(lead_id))
        if STAGES.get(row["stage"], -1) >= STAGES[stage]:
            return
        self.conn.execute(
            "UPDATE leads SET stage = ?, updated_at = ? WHERE id = ?",
            (stage, now_iso(), lead_id),
        )
        self.conn.commit()

    def update_lead(self, lead_id: int, **values: Any) -> None:
        if not values:
            return
        values["updated_at"] = now_iso()
        assignments = ", ".join("{} = ?".format(k) for k in values)
        self.conn.execute(
            "UPDATE leads SET {} WHERE id = ?".format(assignments),
            tuple(values.values()) + (lead_id,),
        )
        self.conn.commit()

    def get_lead(self, lead_id: int) -> Optional[Lead]:
        row = self.conn.execute(
            "SELECT * FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()
        return self._to_lead(row) if row else None

    def leads(
        self,
        stage: Optional[str] = None,
        city: Optional[str] = None,
        category: Optional[str] = None,
        country: Optional[str] = None,
        with_email: Optional[bool] = None,
        limit: Optional[int] = None,
    ) -> List[Lead]:
        sql = "SELECT * FROM leads WHERE 1=1"
        params: List[Any] = []
        if stage:
            sql += " AND stage = ?"
            params.append(stage)
        if city:
            sql += " AND city = ?"
            params.append(city)
        if category:
            sql += " AND category = ?"
            params.append(category)
        if country:
            sql += " AND country = ?"
            params.append(country.upper())
        if with_email is True:
            sql += " AND email != ''"
        elif with_email is False:
            sql += " AND email = ''"
        # 評価の高い店から当たったほうが返信率が上がるので既定の並びにする。
        sql += " ORDER BY rating IS NULL, rating DESC, id ASC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [self._to_lead(r) for r in self.conn.execute(sql, params)]

    def count_leads(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"])

    # 返事を待っている／こちらが返す番のリードを取り出す。フォロー漏れは
    # 商談数に直結するので、勘ではなくクエリで拾えるようにしておく。

    #: 以後の接触を止めるべきイベント。追客対象から必ず除外する。
    STOP_KINDS = ("replied", "bounced", "unsubscribed", "closed")

    def leads_awaiting_followup(
        self, days: int = 7, template: str = "intro", limit: Optional[int] = None
    ) -> List[Lead]:
        """初回送信から days 日以上たっても反応がなく、まだ追客していないリード。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        placeholders = ", ".join("?" for _ in self.STOP_KINDS)
        sql = """
            SELECT l.* FROM leads l
            JOIN events e ON e.lead_id = l.id AND e.kind = 'sent' AND e.template = ?
            WHERE e.ts <= ?
              AND NOT EXISTS (
                    SELECT 1 FROM events s
                    WHERE s.lead_id = l.id AND s.kind IN ({stops}))
              AND NOT EXISTS (
                    SELECT 1 FROM events f
                    WHERE f.lead_id = l.id AND f.kind = 'sent' AND f.template != ?)
            GROUP BY l.id
            ORDER BY e.ts ASC
        """.format(stops=placeholders)
        params: List[Any] = [template, cutoff] + list(self.STOP_KINDS) + [template]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [self._to_lead(r) for r in self.conn.execute(sql, params)]

    def leads_needing_reply(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """返信が来たのに、まだこちらが判断を記録していないリード。"""
        sql = """
            SELECT l.*, e.ts AS replied_at FROM leads l
            JOIN events e ON e.lead_id = l.id AND e.kind = 'replied'
            WHERE NOT EXISTS (
                    SELECT 1 FROM events x
                    WHERE x.lead_id = l.id
                      AND x.kind IN ('positive', 'meeting', 'won', 'closed', 'unsubscribed'))
            ORDER BY e.ts ASC
        """
        params: List[Any] = []
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [
            {"lead": self._to_lead(row), "replied_at": row["replied_at"]}
            for row in self.conn.execute(sql, params)
        ]

    @staticmethod
    def _to_lead(row: sqlite3.Row) -> Lead:
        return Lead.from_row(dict(row))

    # ---------- events ----------

    def add_event(self, event: Event) -> bool:
        """イベントを記録。同一 (lead, kind, variant, template) の重複は無視。

        戻り値は「新しく記録されたか」。False は既に同じイベントがあった、の意味。
        """
        if event.kind not in EVENT_KINDS:
            raise ValueError("unknown event kind: {}".format(event.kind))
        ts = event.ts or now_iso()
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO events (lead_id, kind, ts, variant, template, channel, meta)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event.lead_id, event.kind, ts, event.variant,
             event.template, event.channel, event.meta_json()),
        )
        self.conn.commit()
        inserted = cur.rowcount > 0
        if inserted and event.kind in STAGES:
            self.set_stage(event.lead_id, event.kind)
        return inserted

    def events(self, lead_id: Optional[int] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM events"
        params: List[Any] = []
        if lead_id is not None:
            sql += " WHERE lead_id = ?"
            params.append(lead_id)
        sql += " ORDER BY ts ASC, id ASC"
        rows = []
        for r in self.conn.execute(sql, params):
            row = dict(r)
            row["meta"] = json.loads(row["meta"] or "{}")
            rows.append(row)
        return rows

    # ---------- drafts ----------

    def save_draft(
        self, lead_id: int, lang: str, variant: str,
        template: str, subject: str, body: str,
    ) -> None:
        self.conn.execute(
            """INSERT INTO drafts (lead_id, lang, variant, template, subject, body, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(lead_id) DO UPDATE SET
                 lang=excluded.lang, variant=excluded.variant, template=excluded.template,
                 subject=excluded.subject, body=excluded.body, updated_at=excluded.updated_at""",
            (lead_id, lang, variant, template, subject, body, now_iso()),
        )
        self.conn.commit()

    def drafts(self, lead_ids: Optional[Iterable[int]] = None) -> Dict[int, Dict[str, Any]]:
        sql = "SELECT * FROM drafts"
        params: List[Any] = []
        if lead_ids is not None:
            ids = list(lead_ids)
            if not ids:
                return {}
            sql += " WHERE lead_id IN ({})".format(", ".join("?" for _ in ids))
            params = ids
        return {int(r["lead_id"]): dict(r) for r in self.conn.execute(sql, params)}
