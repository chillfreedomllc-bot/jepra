"""収集 → 補完 → 文面生成 を一続きで回す。

CLI の `run` / `demo` はどちらもここを呼ぶ。工程を関数に割っておくことで、
「収集だけやり直す」「文面だけ作り直す」が個別に実行できる。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .enrich import enrich_lead
from .models import Lead
from .outreach import Profile, render
from .sources import Query, get_source
from .store import Store

Reporter = Callable[[str], None]


def stderr_reporter(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def silent_reporter(_: str) -> None:
    pass


@dataclass
class StageResult:
    collected: int = 0
    new: int = 0
    enriched: int = 0
    emails_found: int = 0
    forms_found: int = 0
    drafted: int = 0
    skipped_duplicate_email: int = 0


def collect(
    store: Store,
    query: Query,
    source_name: str = "overpass",
    report: Reporter = stderr_reporter,
) -> StageResult:
    """収集して DB に入れる。重複は既存レコードにマージされる。"""
    source = get_source(source_name)
    problem = source.check_ready()
    if problem:
        raise SystemExit("ソース '{}' が使えません: {}".format(source_name, problem))

    report("[1/3] 収集: {} / {} / {} (最大{}件)".format(
        source_name, query.country, query.cat.label, query.limit))
    if not source.provides_rating:
        report("      ※ このソースは評価(★)を持ちません。優先度付けは手動になります。")

    result = StageResult()
    before = store.count_leads()
    for lead in source.search(query):
        store.upsert_lead(lead)
        result.collected += 1
    result.new = store.count_leads() - before
    report("      取得 {} 件（うち新規 {} 件、重複 {} 件は既存に統合）".format(
        result.collected, result.new, result.collected - result.new))
    return result


def enrich(
    store: Store,
    limit: Optional[int] = None,
    report: Reporter = stderr_reporter,
    **enrich_kwargs,
) -> StageResult:
    """メール未取得のリードのサイトを巡回する。"""
    targets = [
        lead for lead in store.leads(with_email=False, limit=limit)
        if lead.website and lead.stage in ("discovered", "enriched")
    ]
    report("[2/3] 連絡先の発掘: 対象 {} 件".format(len(targets)))

    result = StageResult()
    for index, lead in enumerate(targets, 1):
        outcome = enrich_lead(lead, **enrich_kwargs)
        result.enriched += 1
        updates: Dict[str, object] = {}
        if outcome.found:
            updates.update({
                "email": outcome.email,
                "email_source": outcome.email_source,
                "email_confidence": outcome.confidence,
            })
            result.emails_found += 1
        elif outcome.contact_form_url:
            updates["contact_form_url"] = outcome.contact_form_url
            result.forms_found += 1
        if updates and lead.id:
            store.update_lead(lead.id, **updates)
        if lead.id:
            store.set_stage(lead.id, "enriched")
        if index % 10 == 0 or index == len(targets):
            report("      {}/{} 完了（メール {} 件 / フォームのみ {} 件）".format(
                index, len(targets), result.emails_found, result.forms_found))
    return result


def compose(
    store: Store,
    profile: Profile,
    template: str = "intro",
    lang: str = "auto",
    variant: str = "auto",
    limit: Optional[int] = None,
    report: Reporter = stderr_reporter,
) -> StageResult:
    """メールを持つリードに文面を作り、送信待ちにする。"""
    targets = [
        lead for lead in store.leads(with_email=True, limit=limit)
        if lead.stage in ("discovered", "enriched", "queued")
    ]
    report("[3/3] 文面生成: 対象 {} 件（テンプレート: {}）".format(len(targets), template))

    result = StageResult()
    variants: Dict[str, int] = {}
    target_ids = {lead.id for lead in targets}

    # 名寄せをすり抜けた重複や、チェーンの複数支店が同じ代表アドレスを載せている
    # ケースがある。同じ宛先に2通行くのは相手に迷惑で、迷惑メール判定も招くため、
    # 文面生成の時点でアドレス単位に1通へ絞る。
    seen_emails = set()
    for lead_id in store.drafts():
        if lead_id in target_ids:
            continue
        other = store.get_lead(lead_id)
        if other and other.email:
            seen_emails.add(other.email)

    for lead in targets:
        if not lead.id:
            continue
        if lead.email in seen_emails:
            result.skipped_duplicate_email += 1
            continue
        seen_emails.add(lead.email)

        subject, body, resolved_lang, resolved_variant = render(
            lead, profile, template=template, lang=lang, variant=variant
        )
        store.save_draft(lead.id, resolved_lang, resolved_variant, template, subject, body)
        store.set_stage(lead.id, "queued")
        variants[resolved_variant] = variants.get(resolved_variant, 0) + 1
        result.drafted += 1

    if variants:
        split = " / ".join("{}: {}件".format(k, v) for k, v in sorted(variants.items()))
        report("      生成 {} 件（{}）".format(result.drafted, split))
    if result.skipped_duplicate_email:
        report("      宛先重複のため {} 件を除外（同一アドレスへの複数送信を防止）".format(
            result.skipped_duplicate_email))
    return result


def followup(
    store: Store,
    profile: Profile,
    days: int = 7,
    lang: str = "auto",
    limit: Optional[int] = None,
    report: Reporter = stderr_reporter,
) -> StageResult:
    """反応のないリードに追客文面を作る。

    A/B の枝は初回送信から引き継ぐ。追客で枝を変えると、返信がどちらの文面に
    よるものか分からなくなり、A/B の集計が壊れるため。
    """
    targets = store.leads_awaiting_followup(days=days, limit=limit)
    report("追客対象: {} 件（初回送信から{}日以上・反応なし）".format(len(targets), days))

    result = StageResult()
    for lead in targets:
        if not lead.id:
            continue
        sends = [e for e in store.events(lead.id) if e["kind"] == "sent"]
        variant = sends[-1]["variant"] if sends else "auto"
        subject, body, resolved_lang, resolved_variant = render(
            lead, profile, template="followup", lang=lang, variant=variant or "auto"
        )
        store.save_draft(
            lead.id, resolved_lang, resolved_variant, "followup", subject, body)
        result.drafted += 1

    if result.drafted:
        report("      追客文面を {} 件生成しました。`jepra export --stage sent` で"
               "取り出せます。".format(result.drafted))
    return result


def run(
    store: Store,
    query: Query,
    profile: Profile,
    source_name: str = "overpass",
    template: str = "intro",
    lang: str = "auto",
    variant: str = "auto",
    do_enrich: bool = True,
    report: Reporter = stderr_reporter,
    **enrich_kwargs,
) -> StageResult:
    """収集 → 補完 → 文面生成 を通しで実行する。"""
    total = StageResult()
    collected = collect(store, query, source_name, report)
    total.collected, total.new = collected.collected, collected.new

    if do_enrich:
        enriched = enrich(store, report=report, **enrich_kwargs)
        total.enriched = enriched.enriched
        total.emails_found = enriched.emails_found
        total.forms_found = enriched.forms_found
    else:
        report("[2/3] 連絡先の発掘: スキップ")

    drafted = compose(store, profile, template, lang, variant, report=report)
    total.drafted = drafted.drafted
    return total
