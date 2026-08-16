"""既存CSVからデモ用fixture JSONを生成する（一度きりの変換）。

名寄せは本体と同じ dedupe_key を使い、支店が潰れないようにする。
"""
import csv, json, os

from jepra.normalize import dedupe_key

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "src/jepra/fixtures/fr_stationery.json")

records = []
seen = {}


def add(name, city, address, phone, website, rating, notes, emails, form):
    name, city = name.strip(), city.strip()
    if not name:
        return
    key = dedupe_key(name, city, website, address)
    if key in seen:
        # 後から来た行で空欄だけ埋める（先勝ち）。
        existing = seen[key]
        for field, value in (("phone", phone.strip()), ("website", website.strip()),
                             ("address", address.strip()), ("notes", notes.strip())):
            if value and not existing.get(field):
                existing[field] = value
        for e in emails:
            if e and e not in existing["_site"]["emails"]:
                existing["_site"]["emails"].append(e)
        return
    rec = {
        "name": name,
        "city": city,
        "address": address.strip(),
        "phone": phone.strip(),
        "website": website.strip(),
        "rating": float(rating) if rating else None,
        "review_count": None,
        "notes": notes.strip(),
        "_site": {"emails": [e for e in emails if e], "contact_form": form},
    }
    seen[key] = rec
    records.append(rec)


with open(os.path.join(ROOT, "data/legacy/papeterie_nationwide.csv"), encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        status = r.get("対応ステータス", "")
        site = r.get("WebサイトURL", "").strip()
        emails = [r.get("メールアドレス", "").strip(), r.get("その他検出アドレス", "").strip()]
        form = site if (site and not any(emails) and "フォーム" in status) else ""
        add(r["店舗名"], r.get("都市", ""), r.get("住所", ""), r.get("電話番号(国際表記)", ""),
            site, r.get("評価", ""), "", emails, form)

for path, name_col, site_col in (
    ("data/legacy/paris_papeterie_list_final.csv", "店名", "ウェブサイト"),
    ("data/legacy/paris_papeterie_master.csv", "店名", "ウェブサイト"),
):
    with open(os.path.join(ROOT, path), encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            site = r.get(site_col, "").strip()
            add(r[name_col], "Paris", r.get("住所", ""), r.get("電話番号", ""),
                site, r.get("評価", ""), r.get("特徴", ""),
                [r.get("メールアドレス", "").strip()], site if site else "")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
payload = {
    "country": "FR",
    "category": "stationery",
    "note": (
        "デモ・テスト用。実在するフランスの文房具店の公開情報（店名・住所・電話・"
        "サイト・Google評価）。メールアドレスは自社で実際に取得済みのもののみ収録し、"
        "推測アドレスは含めない。"
    ),
    "records": records,
}
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
    fh.write("\n")

with_email = sum(1 for r in records if r["_site"]["emails"])
with_form = sum(1 for r in records if r["_site"]["contact_form"] and not r["_site"]["emails"])
print("records:", len(records), "| email:", with_email, "| form only:", with_form)
print("cities:", len({r["city"] for r in records}))
