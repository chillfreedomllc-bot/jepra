"""CSV の入口と出口。

正は SQLite だが、客先に渡すのも、既存の手作業リストを取り込むのも CSV。
列名の揺れ（「店名」「店舗名」「Name」）はここで吸収する。
"""

from __future__ import annotations

import csv
import os
from typing import Any, Dict, Iterable, List, Optional

from .models import Lead
from .normalize import clean_text
from .store import Store

# CSV の列名 -> Lead の項目。小文字化・空白除去して突き合わせる。
ALIASES: Dict[str, str] = {}


def _register(field: str, *names: str) -> None:
    for name in names:
        ALIASES[name.lower().replace(" ", "")] = field


_register("name", "店名", "店舗名", "会社名", "name", "shop", "shopname", "店舗")
_register("city", "都市", "市", "city", "town")
_register("address", "住所", "address", "所在地")
_register("phone", "電話番号", "電話番号(国際表記)", "電話", "phone", "tel", "telephone")
_register("website", "ウェブサイト", "webサイトurl", "サイト", "website", "url", "web")
_register("email", "メールアドレス", "メール", "email", "mail", "e-mail")
_register("rating", "評価", "rating", "score", "星")
_register("category", "業態", "業種", "カテゴリ", "category", "type")
_register("notes", "特徴", "備考", "notes", "note", "memo", "コメント")
_register("country", "国", "country")
_register("contact_form_url", "問い合わせフォーム", "フォーム", "contactform")

# 取り込み時に notes へ畳み込む列（ステータス系はステージ管理に置き換わるため）。
NOTE_COLUMNS = {"対応ステータス", "ステータス", "status", "その他検出アドレス", "件名", "本文"}

# 客先納品用の列順。日本語ヘッダのまま Excel で開ける形にする。
EXPORT_COLUMNS = [
    ("id", "ID"),
    ("name", "店名"),
    ("city", "都市"),
    ("country", "国"),
    ("category", "業種"),
    ("rating", "評価"),
    ("address", "住所"),
    ("phone", "電話番号"),
    ("website", "ウェブサイト"),
    ("email", "メールアドレス"),
    ("email_confidence", "メール確度"),
    ("contact_form_url", "問い合わせフォーム"),
    ("stage", "ステージ"),
    ("notes", "備考"),
]

DRAFT_COLUMNS = [("subject", "件名"), ("body", "本文"), ("variant", "文面枝"), ("lang", "言語")]


def _map_headers(fieldnames: Iterable[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for raw in fieldnames or []:
        key = clean_text(raw).lower().replace(" ", "")
        if key in ALIASES:
            mapping[raw] = ALIASES[key]
    return mapping


def import_csv(
    store: Store,
    path: str,
    country: str = "FR",
    category: str = "",
    city: str = "",
    source: str = "legacy-csv",
) -> Dict[str, int]:
    """既存の手作業CSVを取り込む。列名は自動判定する。

    city は都市列を持たない単一都市のリスト（「パリの店だけ」等）用の既定値。
    名寄せキーに都市を使うため、ここを埋めておかないと同じ店が別レコードとして残る。
    """
    if not os.path.exists(path):
        raise SystemExit("ファイルがありません: {}".format(path))

    imported = 0
    skipped = 0
    # Excel 由来の BOM を素通しさせるため utf-8-sig で開く。
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        mapping = _map_headers(reader.fieldnames or [])
        if "name" not in mapping.values():
            raise SystemExit(
                "店名にあたる列が見つかりません。ヘッダ: {}".format(reader.fieldnames)
            )
        for row in reader:
            values: Dict[str, Any] = {}
            notes: List[str] = []
            for raw_key, raw_value in row.items():
                value = clean_text(raw_value)
                if not value:
                    continue
                if raw_key in NOTE_COLUMNS:
                    notes.append("{}: {}".format(clean_text(raw_key), value))
                    continue
                field = mapping.get(raw_key)
                if field:
                    values[field] = value

            if not values.get("name"):
                skipped += 1
                continue
            if values.get("rating"):
                try:
                    values["rating"] = float(values["rating"])
                except ValueError:
                    values.pop("rating")
            if notes:
                values["notes"] = " / ".join(
                    filter(None, [values.get("notes", "")] + notes)
                )
            values.setdefault("country", country)
            if city:
                values.setdefault("city", city)
            if category:
                values.setdefault("category", category)
            values["source"] = source
            if values.get("email"):
                values["email_source"] = "legacy-csv"
                values["email_confidence"] = 0.8

            store.upsert_lead(Lead(**values))
            imported += 1

    return {"imported": imported, "skipped": skipped}


def export_leads(
    store: Store,
    path: str,
    leads: List[Lead],
    include_drafts: bool = True,
) -> int:
    """納品用CSVを書き出す。文面があれば件名・本文も同梱する。"""
    drafts = store.drafts([l.id for l in leads if l.id]) if include_drafts else {}
    columns = list(EXPORT_COLUMNS)
    if drafts:
        columns += DRAFT_COLUMNS

    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)

    # Excel が UTF-8 を誤認しないよう BOM 付きで書く。
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([header for _, header in columns])
        for lead in leads:
            draft = drafts.get(lead.id or -1, {})
            row = []
            for field, _ in columns:
                if field in ("subject", "body", "variant", "lang"):
                    row.append(draft.get(field, ""))
                else:
                    value = getattr(lead, field, "")
                    row.append("" if value is None else value)
            writer.writerow(row)
    return len(leads)


def export_events(store: Store, path: str) -> int:
    """イベントログを書き出す。集計の生データとして客先に添える用。"""
    events = store.events()
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ID", "リードID", "店名", "種別", "日時", "文面枝", "テンプレート", "経路"])
        leads = {l.id: l for l in store.leads()}
        for event in events:
            lead = leads.get(event["lead_id"])
            writer.writerow([
                event["id"], event["lead_id"], lead.name if lead else "",
                event["kind"], event["ts"], event["variant"],
                event["template"], event["channel"],
            ])
    return len(events)


def import_events(store: Store, path: str) -> Dict[str, int]:
    """送信結果CSVを一括で取り込む。

    想定する列: リードID(または店名) / 種別 / 日時 / 文面枝 / テンプレート
    メール配信ツールのエクスポートを整形して流し込む口。
    """
    from .models import Event

    if not os.path.exists(path):
        raise SystemExit("ファイルがありません: {}".format(path))

    by_name = {}
    for lead in store.leads():
        by_name[lead.name.lower()] = lead.id

    added = 0
    unmatched = 0
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            normalized = {clean_text(k).lower(): clean_text(v) for k, v in row.items()}
            lead_id: Optional[int] = None
            for key in ("リードid", "lead_id", "id"):
                if normalized.get(key, "").isdigit():
                    lead_id = int(normalized[key])
                    break
            if lead_id is None:
                for key in ("店名", "name", "shop"):
                    if normalized.get(key):
                        lead_id = by_name.get(normalized[key].lower())
                        break
            kind = normalized.get("種別") or normalized.get("kind") or normalized.get("event")
            if lead_id is None or not kind:
                unmatched += 1
                continue
            if store.add_event(Event(
                lead_id=lead_id,
                kind=kind,
                ts=normalized.get("日時") or normalized.get("ts") or "",
                variant=normalized.get("文面枝") or normalized.get("variant") or "",
                template=normalized.get("テンプレート") or normalized.get("template") or "",
            )):
                added += 1

    return {"added": added, "unmatched": unmatched}
