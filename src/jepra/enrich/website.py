"""サイトを巡回して連絡先を掘る。

リストの価値はここで決まる。店名と住所だけのリストは誰でも作れるが、
「担当に届くメールアドレス付き」になると単価が一桁変わる。

方針:
  - トップページ → 連絡先系ページの順に最大 N ページだけ見る（深追いしない）
  - mailto: を最優先、次に本文中の記載
  - サイトのドメインと一致するアドレスを高く評価（gmail等の汎用より確度が高い）
  - メールが無ければ問い合わせフォームのURLを記録し、別動線に回す
  - robots.txt で拒否されていれば取得しない
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from ..models import Lead
from ..normalize import domain_of, normalize_url
from ..sources.base import require
from ..sources.fixture import site_hints

USER_AGENT = "jepra/0.1 (+B2B contact research; respects robots.txt)"

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)

# 連絡先が載りがちなページ。多言語（仏/英/独/伊/西）を一括で見る。
CONTACT_HINTS = (
    "contact", "nous-contacter", "contactez", "kontakt", "contatti", "contacto",
    "mentions-legales", "impressum", "about", "a-propos", "chi-siamo",
    "pro", "professionnel", "wholesale", "revendeur", "grossiste",
)

# 収集しても意味がない、あるいは他社のアドレス。
EMAIL_BLOCKLIST = re.compile(
    r"(^(no-?reply|postmaster|abuse|donotreply)@)"
    r"|(@(example|sentry|wixpress|shopify|squarespace|godaddy|sentry)\.)"
    r"|(\.(png|jpe?g|gif|webp|svg|css|js)$)",
    re.IGNORECASE,
)

# 個人アドレスでも受け取り手はいるが、独自ドメインより確度は落ちる。
FREEMAIL = {
    "gmail.com", "wanadoo.fr", "orange.fr", "free.fr", "hotmail.com", "hotmail.fr",
    "outlook.com", "outlook.fr", "yahoo.fr", "yahoo.com", "laposte.net", "sfr.fr",
    "gmx.de", "web.de", "libero.it", "icloud.com",
}


class _LinkParser(HTMLParser):
    """<a href> と mailto: を拾うだけの軽量パーサ（bs4 不要）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: List[str] = []
        self.mailtos: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        if href.lower().startswith("mailto:"):
            address = href[7:].split("?", 1)[0].strip()
            if address:
                self.mailtos.append(address)
        elif href:
            self.links.append(href)


@dataclass
class EnrichResult:
    """1件ぶんの巡回結果。"""

    email: str = ""
    email_source: str = ""
    confidence: float = 0.0
    contact_form_url: str = ""
    all_emails: List[str] = field(default_factory=list)
    pages_fetched: int = 0
    error: str = ""

    @property
    def found(self) -> bool:
        return bool(self.email)


def _score(email: str, source: str, site_domain: str) -> float:
    """このアドレスがどれくらい「その店の窓口」らしいか。"""
    email_domain = email.rsplit("@", 1)[-1].lower()
    base = 0.85 if source == "mailto" else 0.6
    if site_domain and email_domain == site_domain:
        base += 0.10           # サイトと同じドメイン = ほぼ確実に本人
    elif email_domain in FREEMAIL:
        base -= 0.10           # 個人アドレス。届くが窓口とは限らない
    local = email.split("@", 1)[0].lower()
    if local in ("contact", "info", "bonjour", "hello", "commande", "commercial", "pro"):
        base += 0.05           # 代表窓口。BtoBの初回接触には向く
    return round(min(base, 0.99), 2)


def _pick_best(candidates: List[Tuple[str, str]], site_domain: str) -> Tuple[str, str, float]:
    """(email, source) の候補から最良の1件を選ぶ。"""
    best: Tuple[str, str, float] = ("", "", 0.0)
    for email, source in candidates:
        email = email.strip().lower().rstrip(".,;:")
        if not email or EMAIL_BLOCKLIST.search(email):
            continue
        score = _score(email, source, site_domain)
        if score > best[2]:
            best = (email, source, score)
    return best


def _robots_allows(base_url: str, user_agent: str = USER_AGENT) -> bool:
    parts = urlsplit(base_url)
    robots_url = "{}://{}/robots.txt".format(parts.scheme, parts.netloc)
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except Exception:
        return True  # robots.txt が読めない = 制限なしとみなす（一般的な運用）
    return parser.can_fetch(user_agent, base_url)


def _contact_urls(base_url: str, links: List[str], limit: int) -> List[str]:
    """連絡先が載っていそうなページURLを、同一ドメインに限って選ぶ。"""
    host = domain_of(base_url)
    seen: Set[str] = set()
    picked: List[str] = []
    for href in links:
        absolute = urljoin(base_url, href)
        if not absolute.startswith(("http://", "https://")):
            continue
        if domain_of(absolute) != host:
            continue
        lowered = absolute.lower()
        if not any(hint in lowered for hint in CONTACT_HINTS):
            continue
        cleaned = absolute.split("#", 1)[0]
        if cleaned in seen:
            continue
        seen.add(cleaned)
        picked.append(cleaned)
        if len(picked) >= limit:
            break
    return picked


def enrich_lead(
    lead: Lead,
    max_pages: int = 4,
    timeout: int = 15,
    pause: float = 0.5,
    respect_robots: bool = True,
) -> EnrichResult:
    """1件のリードのサイトを巡回して連絡先を探す。

    fixture ソースのリードは通信せず、同梱の想定結果を返す（デモ用）。
    """
    hints = site_hints(lead)
    if hints is not None:
        emails = hints.get("emails", [])
        if emails:
            email, source, score = _pick_best(
                [(e, "mailto") for e in emails], domain_of(lead.website)
            )
            return EnrichResult(
                email=email, email_source=source, confidence=score,
                all_emails=emails, pages_fetched=1,
            )
        return EnrichResult(
            contact_form_url=normalize_url(hints.get("contact_form", "")),
            pages_fetched=1,
        )

    if not lead.website:
        return EnrichResult(error="no-website")

    requests = require("requests")
    base = lead.website
    if respect_robots and not _robots_allows(base):
        return EnrichResult(error="robots-disallowed")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    candidates: List[Tuple[str, str]] = []
    all_emails: List[str] = []
    contact_form = ""
    fetched = 0
    queue = [base]
    visited: Set[str] = set()
    error = ""

    while queue and fetched < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            response = session.get(url, timeout=timeout, allow_redirects=True)
            response.raise_for_status()
        except Exception as exc:  # 1件の失敗で全体を止めない
            if not error:
                error = "{}: {}".format(type(exc).__name__, str(exc)[:120])
            continue
        fetched += 1
        html = response.text
        if len(html) > 800_000:
            html = html[:800_000]  # 巨大ページで時間を食わない

        parser = _LinkParser()
        try:
            parser.feed(html)
        except Exception:
            pass  # 壊れたHTMLでも本文の正規表現抽出は続ける

        for address in parser.mailtos:
            candidates.append((address, "mailto"))
            all_emails.append(address)
        for match in EMAIL_RE.findall(html):
            candidates.append((match, "text"))
            all_emails.append(match)

        if not contact_form and re.search(r"<form[^>]*>", html, re.IGNORECASE):
            contact_form = url

        if fetched == 1:
            queue.extend(_contact_urls(url, parser.links, max_pages - 1))
        time.sleep(pause)

    email, source, score = _pick_best(candidates, domain_of(base))
    return EnrichResult(
        email=email,
        email_source=source,
        confidence=score,
        contact_form_url="" if email else contact_form,
        all_emails=sorted({e.lower() for e in all_emails if not EMAIL_BLOCKLIST.search(e)}),
        pages_fetched=fetched,
        error="" if (email or contact_form) else error,
    )
