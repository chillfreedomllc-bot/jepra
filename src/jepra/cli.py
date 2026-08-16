"""jepra のコマンドラインインターフェース。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from . import __version__, csvio, metrics, pipeline
from .models import Event
from .outreach import Profile, render, template_names
from .simulate import simulate_campaign
from .sources import CATEGORIES, Query, source_names
from .store import DEFAULT_DB, Store

DEMO_DB = "jepra-demo.db"
DEMO_CAMPAIGN_DB = "jepra-demo-campaign.db"


# ---------- 表示ヘルパ ----------

def pct(value: Optional[float]) -> str:
    return "—" if value is None else "{:.1f}%".format(value * 100)


def rule(char: str = "─", width: int = 62) -> str:
    return char * width


def heading(text: str) -> None:
    print("\n{}\n{}".format(text, rule()))


def print_funnel(funnel: metrics.Funnel) -> None:
    data = funnel.as_dict()
    rows = [
        ("収集した店舗", data["discovered"], None),
        ("メール取得済み", data["contactable"], data["contact_rate"]),
    ]
    # 未送信の段階で 0 の行を並べても読みづらいだけなので、送信後だけ出す。
    if data["sent"]:
        rows += [
            ("送信", data["sent"], None),
            ("　うちバウンス", data["bounced"], None),
            ("到達", data["delivered"], data["delivery_rate"]),
            ("開封", data["opened"], data["open_rate"]),
            ("返信", data["replied"], data["reply_rate"]),
            ("前向きな返信", data["positive"], data["positive_rate"]),
            ("商談化", data["meeting"], data["meeting_rate"]),
            ("成約", data["won"], None),
        ]
    for label, count, rate in rows:
        suffix = "  ({})".format(pct(rate)) if rate is not None else ""
        print("  {:<16} {:>6}{}".format(label, count, suffix))

    if data["sent"]:
        print("\n  ※ 到達率 = (送信-バウンス)/送信、返信率 = 返信/到達")
    else:
        print("\n  ※ 送信実績がまだありません。`jepra log sent --lead <ID>` で記録すると"
              "到達率・返信率が出ます。")


def print_breakdown(groups: List[metrics.Funnel], dimension: str) -> None:
    header = "{:<18} {:>7} {:>7} {:>7} {:>8} {:>8}".format(
        dimension, "収集", "送信", "到達", "返信", "返信率")
    print("  " + header)
    print("  " + rule("-", len(header)))
    for group in groups:
        data = group.as_dict()
        print("  {:<18} {:>7} {:>7} {:>7} {:>8} {:>8}".format(
            data["label"][:18], data["discovered"], data["sent"],
            data["delivered"], data["replied"], pct(data["reply_rate"])))


def print_ab(store: Store, **filters: Any) -> None:
    comparison = metrics.ab_compare(store, metric="replied", **filters)
    if comparison is None:
        print("  A/B比較: 2枝ぶんの送信実績がまだありません。")
        return
    note = metrics.sample_size_note(
        comparison["p_value"], comparison["n_a"], comparison["n_b"])
    print("  枝 {}: 返信率 {} ({}通中)".format(
        comparison["label_a"], pct(comparison["rate_a"]), comparison["n_a"]))
    print("  枝 {}: 返信率 {} ({}通中)".format(
        comparison["label_b"], pct(comparison["rate_b"]), comparison["n_b"]))

    # 符号だけ出してもどちらが勝っているか読み取りにくいので、勝ち枝を明示する。
    if comparison["lift"] >= 0:
        winner, loser, gap = comparison["label_a"], comparison["label_b"], comparison["lift"]
    else:
        winner, loser, gap = comparison["label_b"], comparison["label_a"], -comparison["lift"]
    print("  差分: {} が {} より {:.1f}pt 高い / p値 {:.3f} → {}".format(
        winner, loser, gap * 100, comparison["p_value"], note))


# ---------- 各コマンド ----------

def cmd_init(args: argparse.Namespace) -> int:
    with Store(args.db) as store:
        print("DB を初期化しました: {} (既存 {} 件)".format(args.db, store.count_leads()))
    if not os.path.exists("jepra.profile.json"):
        print("差出人情報がまだありません。`jepra profile init` を実行してください。")
    return 0


def cmd_sources(_: argparse.Namespace) -> int:
    heading("収集ソース")
    from .sources import get_source
    for name in source_names():
        source = get_source(name)
        problem = source.check_ready()
        status = "利用可" if problem is None else "使用不可: {}".format(problem)
        rating = "評価あり" if source.provides_rating else "評価なし"
        print("  {:<10} {:<10} {}".format(name, rating, status))

    heading("業種")
    for key, category in sorted(CATEGORIES.items()):
        print("  {:<14} {:<12} 検索語(fr): {}".format(
            key, category.label, category.term("fr")))

    heading("文面テンプレート")
    print("  " + ", ".join(template_names()) + "  / 枝: A, B  / 言語: fr, en, ja")
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    path = args.path
    if args.action == "init":
        if os.path.exists(path) and not args.force:
            print("既にあります: {}（上書きするには --force）".format(path))
            return 1
        Profile().save(path)
        print("雛形を作成しました: {}".format(path))
        print("中の <...> を自社の情報に書き換えてから compose を実行してください。")
    else:
        profile = Profile.load(path)
        print(json.dumps(profile.__dict__, ensure_ascii=False, indent=2))
    return 0


def cmd_scrape(args: argparse.Namespace) -> int:
    query = Query(country=args.country, city=args.city,
                  category=args.category, limit=args.limit)
    with Store(args.db) as store:
        pipeline.collect(store, query, args.source)
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    with Store(args.db) as store:
        pipeline.enrich(
            store, limit=args.limit, max_pages=args.max_pages,
            respect_robots=not args.ignore_robots,
        )
    return 0


def cmd_compose(args: argparse.Namespace) -> int:
    profile = Profile.load(args.profile)
    with Store(args.db) as store:
        pipeline.compose(store, profile, template=args.template,
                         lang=args.lang, variant=args.variant, limit=args.limit)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    query = Query(country=args.country, city=args.city,
                  category=args.category, limit=args.limit)
    profile = Profile.load(args.profile)
    with Store(args.db) as store:
        pipeline.run(
            store, query, profile,
            source_name=args.source, template=args.template,
            lang=args.lang, variant=args.variant, do_enrich=not args.no_enrich,
            max_pages=args.max_pages, respect_robots=not args.ignore_robots,
        )
        if args.out:
            leads = store.leads(country=args.country, category=args.category,
                                city=args.city or None)
            csvio.export_leads(store, args.out, leads)
            print("\n納品用CSVを書き出しました: {} ({}件)".format(args.out, len(leads)))
        heading("現在のファネル")
        print_funnel(metrics.funnel(store))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    with Store(args.db) as store:
        with_email = True if args.with_email else (False if args.without_email else None)
        leads = store.leads(stage=args.stage, city=args.city, category=args.category,
                            country=args.country, with_email=with_email, limit=args.limit)
        count = csvio.export_leads(store, args.out, leads)
    print("書き出しました: {} ({}件)".format(args.out, count))
    return 0


def cmd_export_events(args: argparse.Namespace) -> int:
    with Store(args.db) as store:
        count = csvio.export_events(store, args.out)
    print("書き出しました: {} ({}件)".format(args.out, count))
    return 0


def cmd_import_csv(args: argparse.Namespace) -> int:
    with Store(args.db) as store:
        result = csvio.import_csv(store, args.path, country=args.country,
                                  category=args.category, city=args.city)
        print("取り込み {} 件 / スキップ {} 件（DB合計 {} 件）".format(
            result["imported"], result["skipped"], store.count_leads()))
    return 0


def cmd_import_events(args: argparse.Namespace) -> int:
    with Store(args.db) as store:
        result = csvio.import_events(store, args.path)
    print("イベント追加 {} 件 / 突合できず {} 件".format(
        result["added"], result["unmatched"]))
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    with Store(args.db) as store:
        lead = store.get_lead(args.lead)
        if lead is None:
            raise SystemExit("リードID {} が見つかりません".format(args.lead))

        variant, template = args.variant, args.template
        if args.kind != "sent" and not (variant and template):
            # 返信やバウンスは「どの文面で送った結果か」に紐づけないと A/B が測れない。
            # 指定が無ければ直近の送信イベントから引き継ぐ。
            sends = [e for e in store.events(args.lead) if e["kind"] == "sent"]
            if sends:
                variant = variant or sends[-1]["variant"]
                template = template or sends[-1]["template"]

        created = store.add_event(Event(
            lead_id=args.lead, kind=args.kind,
            variant=variant or "", template=template or "",
            meta={"note": args.note} if args.note else {},
        ))
        status = "記録しました" if created else "既に記録済みのため無視しました"
        print("{}: [{}] {} (枝 {})".format(status, args.kind, lead.name, variant or "-"))
    return 0


def cmd_followup(args: argparse.Namespace) -> int:
    profile = Profile.load(args.profile)
    with Store(args.db) as store:
        pipeline.followup(store, profile, days=args.days,
                          lang=args.lang, limit=args.limit)
    return 0


def cmd_inbox(args: argparse.Namespace) -> int:
    """こちらが動く番のリードを出す。段階3（商談創出）の日次の起点。"""
    with Store(args.db) as store:
        pending = store.leads_needing_reply(limit=args.limit)
        heading("返信あり・未対応 ({}件)".format(len(pending)))
        if not pending:
            print("  対応待ちはありません。")
        for entry in pending:
            lead = entry["lead"]
            print("  [{}] {} / {} <{}>".format(
                lead.id, lead.name, lead.city, lead.email))
            print("       返信日時 {}  →  jepra log positive --lead {}".format(
                entry["replied_at"][:16], lead.id))

        waiting = store.leads_awaiting_followup(days=args.days)
        heading("追客推奨 ({}件・初回送信から{}日以上)".format(len(waiting), args.days))
        for lead in waiting[:args.limit or 20]:
            print("  [{}] {} / {} <{}>".format(
                lead.id, lead.name, lead.city, lead.email))
        if len(waiting) > (args.limit or 20):
            print("  ... 他 {} 件".format(len(waiting) - (args.limit or 20)))
        if waiting:
            print("\n  `jepra followup --days {}` で追客文面をまとめて生成できます。".format(
                args.days))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    filters = {k: v for k, v in
               (("city", args.city), ("category", args.category),
                ("country", args.country), ("source", args.source)) if v}

    with Store(args.db) as store:
        overall = metrics.funnel(store, **filters)
        if args.json:
            payload: Dict[str, Any] = {"overall": overall.as_dict()}
            if args.by:
                payload[args.by] = [
                    g.as_dict() for g in metrics.breakdown(store, args.by, **filters)
                ]
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        heading("ファネル{}".format(
            "（{}）".format(", ".join(filters.values())) if filters else ""))
        print_funnel(overall)

        if args.by:
            heading("{} 別".format(args.by))
            print_breakdown(metrics.breakdown(store, args.by, **filters), args.by)

        heading("文面 A/B（返信率）")
        print_ab(store, **filters)
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    with Store(args.db) as store:
        result = simulate_campaign(store, leads=args.leads, seed=args.seed)
    print("架空データを生成しました: リード {leads} / 送信 {sent} / 返信 {replied}".format(**result))
    print("※ 全て meta.simulated=true。実案件のDBとは混ぜないでください。")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """通信不要・APIキー不要で全工程を見せる。商談デモ用。"""
    for path in (DEMO_DB, DEMO_CAMPAIGN_DB):
        if os.path.exists(path) and args.reset:
            os.remove(path)

    print(rule("="))
    print(" jepra デモ — 越境BtoBリードの収集から効果測定まで")
    print(rule("="))
    print("\n【第1部】実データによるリスト生成")
    print("フランスの文房具店リストを、収集→連絡先発掘→多言語文面生成まで通します。")
    print("(デモ用の同梱データを使うため通信は発生しません)\n")

    query = Query(country="FR", city=args.city, category="stationery", limit=args.limit)
    profile = Profile.load(args.profile)

    with Store(DEMO_DB) as store:
        pipeline.run(store, query, profile, source_name="fixture",
                     template="intro", lang="fr", variant="auto")

        heading("生成された文面の例")
        queued = store.leads(stage="queued", limit=1)
        if queued:
            draft = store.drafts([queued[0].id]).get(queued[0].id)
            if draft:
                print("  宛先: {} <{}>".format(queued[0].name, queued[0].email))
                print("  枝  : {} / 言語 {}".format(draft["variant"], draft["lang"]))
                print("  件名: {}\n".format(draft["subject"]))
                for line in draft["body"].splitlines():
                    print("  | " + line)

        out_path = args.out or "demo_leads.csv"
        leads = store.leads()
        csvio.export_leads(store, out_path, leads)
        print("\n  納品用CSV: {} ({}件)".format(out_path, len(leads)))

        heading("第1部のファネル（実データ）")
        print_funnel(metrics.funnel(store))

    if args.simulate <= 0:
        return 0

    print("\n")
    print(rule("="))
    print("【第2部】効果測定レイヤ（ここからは架空の配信実績）")
    print(rule("="))
    print("実案件で {} 通配信した場合に何が測れるかを示します。".format(args.simulate))
    print("以下の数値は全てシミュレーションで、実在の店舗とは無関係です。")

    with Store(DEMO_CAMPAIGN_DB) as store:
        if store.count_leads() == 0:
            simulate_campaign(store, leads=args.simulate)
        heading("キャンペーン全体")
        print_funnel(metrics.funnel(store))
        heading("都市別")
        print_breakdown(metrics.breakdown(store, "city"), "city")
        heading("文面 A/B（返信率）")
        print_ab(store)
        print("\n  A=条件提示型 / B=店舗個別型。差が出た枝に寄せて次回配信を組みます。")

    print("\n" + rule())
    print("実データで動かす場合:")
    print("  jepra run --country FR --city Lyon --category stationery \\")
    print("            --limit 100 --source overpass --out lyon.csv")
    print(rule())
    return 0


# ---------- パーサ ----------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jepra",
        description="越境BtoB向け リード収集・アプローチ・効果測定パイプライン",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  jepra demo                                     デモを通す（通信不要）\n"
            "  jepra import-csv papeterie_nationwide.csv      既存CSVを取り込む\n"
            "  jepra run --country FR --city Lyon --limit 50  収集から文面まで一括\n"
            "  jepra log replied --lead 12                    返信を記録\n"
            "  jepra stats --by variant                       効果測定\n"
        ),
    )
    parser.add_argument("--version", action="version", version="jepra {}".format(__version__))
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite ファイル (既定: %(default)s)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        return subparsers.add_parser(name, help=help_text, description=help_text)

    p = add("init", "DB を作成する")
    p.set_defaults(func=cmd_init)

    p = add("sources", "使えるソース・業種・テンプレートを一覧する")
    p.set_defaults(func=cmd_sources)

    p = add("profile", "差出人情報の雛形作成・確認")
    p.add_argument("action", choices=["init", "show"], nargs="?", default="show")
    p.add_argument("--path", default="jepra.profile.json")
    p.add_argument("--force", action="store_true", help="既存ファイルを上書きする")
    p.set_defaults(func=cmd_profile)

    def add_query_args(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--country", default="FR", help="ISO国コード (既定: %(default)s)")
        sub.add_argument("--city", default="", help="都市名。省略時は国全体")
        sub.add_argument("--category", default="stationery",
                         choices=sorted(CATEGORIES), help="業種 (既定: %(default)s)")
        sub.add_argument("--limit", type=int, default=100, help="最大件数 (既定: %(default)s)")
        sub.add_argument("--source", default="overpass", choices=source_names(),
                         help="収集ソース (既定: %(default)s)")

    def add_enrich_args(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--max-pages", type=int, default=4,
                         help="1サイトあたりの巡回上限 (既定: %(default)s)")
        sub.add_argument("--ignore-robots", action="store_true",
                         help="robots.txt を無視する（非推奨）")

    p = add("scrape", "店舗を収集して DB に入れる")
    add_query_args(p)
    p.set_defaults(func=cmd_scrape)

    p = add("enrich", "サイトを巡回してメールアドレスを掘る")
    p.add_argument("--limit", type=int, default=None)
    add_enrich_args(p)
    p.set_defaults(func=cmd_enrich)

    p = add("compose", "アプローチ文面を生成する")
    p.add_argument("--template", default="intro", choices=template_names())
    p.add_argument("--lang", default="auto", help="fr / en / ja / auto")
    p.add_argument("--variant", default="auto", help="A / B / auto")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--profile", default="jepra.profile.json")
    p.set_defaults(func=cmd_compose)

    p = add("run", "収集→連絡先発掘→文面生成 を一括で実行")
    add_query_args(p)
    add_enrich_args(p)
    p.add_argument("--template", default="intro", choices=template_names())
    p.add_argument("--lang", default="auto")
    p.add_argument("--variant", default="auto")
    p.add_argument("--profile", default="jepra.profile.json")
    p.add_argument("--no-enrich", action="store_true", help="サイト巡回を省く")
    p.add_argument("--out", default="", help="納品用CSVの出力先")
    p.set_defaults(func=cmd_run)

    p = add("export", "リードをCSVに書き出す")
    p.add_argument("--out", required=True)
    p.add_argument("--stage", default=None)
    p.add_argument("--city", default=None)
    p.add_argument("--category", default=None)
    p.add_argument("--country", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--with-email", action="store_true", help="メール取得済みのみ")
    p.add_argument("--without-email", action="store_true", help="メール未取得のみ")
    p.set_defaults(func=cmd_export)

    p = add("export-events", "イベントログをCSVに書き出す")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_export_events)

    p = add("import-csv", "既存の店舗リストCSVを取り込む")
    p.add_argument("path")
    p.add_argument("--country", default="FR")
    p.add_argument("--category", default="stationery")
    p.add_argument("--city", default="",
                   help="都市列が無いCSV用の既定都市（名寄せに使われる）")
    p.set_defaults(func=cmd_import_csv)

    p = add("import-events", "送信結果CSVを一括で取り込む")
    p.add_argument("path")
    p.set_defaults(func=cmd_import_events)

    p = add("log", "送信・バウンス・返信などを記録する")
    p.add_argument("kind", choices=["sent", "bounced", "opened", "replied",
                                    "positive", "meeting", "won", "closed",
                                    "unsubscribed"])
    p.add_argument("--lead", type=int, required=True, help="リードID")
    p.add_argument("--variant", default="", help="省略時は直近の送信から引き継ぐ")
    p.add_argument("--template", default="")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_log)

    p = add("inbox", "対応待ち・追客推奨のリードを一覧する")
    p.add_argument("--days", type=int, default=7, help="追客までの日数 (既定: %(default)s)")
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_inbox)

    p = add("followup", "反応のないリードに追客文面を作る")
    p.add_argument("--days", type=int, default=7, help="初回送信からの経過日数")
    p.add_argument("--lang", default="auto")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--profile", default="jepra.profile.json")
    p.set_defaults(func=cmd_followup)

    p = add("stats", "到達率・返信率などを集計する")
    p.add_argument("--by", default=None, choices=sorted(metrics.DIMENSIONS),
                   help="集計軸")
    p.add_argument("--city", default=None)
    p.add_argument("--category", default=None)
    p.add_argument("--country", default=None)
    p.add_argument("--source", default=None)
    p.add_argument("--json", action="store_true", help="JSONで出力する")
    p.set_defaults(func=cmd_stats)

    p = add("simulate", "計測レイヤ確認用の架空データを作る")
    p.add_argument("--leads", type=int, default=400)
    p.add_argument("--seed", type=int, default=20260816)
    p.set_defaults(func=cmd_simulate)

    p = add("demo", "通信不要のデモを通す（商談用）")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--city", default="")
    p.add_argument("--simulate", type=int, default=1200,
                   help="第2部で生成する架空配信数。0で第2部を省く")
    p.add_argument("--profile", default="jepra.profile.json")
    p.add_argument("--out", default="")
    p.add_argument("--reset", action="store_true", help="デモ用DBを作り直す")
    p.set_defaults(func=cmd_demo)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except KeyboardInterrupt:
        print("\n中断しました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
