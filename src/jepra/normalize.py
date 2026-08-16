"""名寄せ・重複排除のための正規化ユーティリティ。

収集ソースが違えば同じ店でも表記が揺れる（"Rougier & Plé" / "Rougier&Plé"、
"http://x.fr/" / "https://www.x.fr"）。ここで正規化した値を突き合わせキーに使う。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional
from urllib.parse import urlsplit

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MULTISPACE = re.compile(r"\s+")

# 名寄せの邪魔になる法人格・業態語。国を増やすときはここに足す。
_STOPWORDS = {
    "sarl", "sas", "sasu", "eurl", "sa", "snc", "gmbh", "srl", "spa", "bv", "nv",
    "ltd", "limited", "llc", "inc", "co", "kk",
    "la", "le", "les", "l", "du", "de", "des", "der", "die", "das", "the",
}


def strip_accents(text: str) -> str:
    """アクセント記号を落とす（Plé -> Ple）。"""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def slug(text: Optional[str]) -> str:
    """比較用のスラグ。英数字以外を潰し、法人格・冠詞を除く。"""
    if not text:
        return ""
    base = _NON_ALNUM.sub(" ", strip_accents(text).lower())
    tokens = [t for t in base.split() if t and t not in _STOPWORDS]
    return "-".join(tokens)


def clean_text(text: Optional[str]) -> str:
    """前後の空白と連続空白を潰す。CSV由来のBOMや全角空白も落とす。"""
    if not text:
        return ""
    return _MULTISPACE.sub(" ", text.replace("﻿", "").replace("　", " ")).strip()


def normalize_url(url: Optional[str]) -> str:
    """スキーム補完と末尾スラッシュ除去。空なら空文字。"""
    raw = clean_text(url)
    if not raw:
        return ""
    # 収集データには "HTTP://" のような大文字スキームが混じる。小文字化して判定しないと
    # スキームを二重に付けてしまう。
    if not raw.lower().startswith(("http://", "https://")):
        raw = "https://" + raw.lstrip("/")
    parts = urlsplit(raw)
    if not parts.netloc:
        return ""
    path = parts.path.rstrip("/")
    rebuilt = "{}://{}{}".format(parts.scheme, parts.netloc.lower(), path)
    if parts.query:
        rebuilt += "?" + parts.query
    return rebuilt


def domain_of(url: Optional[str]) -> str:
    """URLから www を除いたホスト名。重複排除とメール検証の両方で使う。"""
    normalized = normalize_url(url)
    if not normalized:
        return ""
    host = urlsplit(normalized).netloc.lower()
    if ":" in host:
        host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def normalize_phone(phone: Optional[str], default_country_code: str = "") -> str:
    """E.164 に寄せる。桁が読めない場合は入力をそのまま返す（捨てない）。"""
    raw = clean_text(phone)
    if not raw:
        return ""
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits.startswith("+"):
        return "+" + re.sub(r"\D", "", digits[1:])
    if default_country_code and digits.startswith("0"):
        return "+{}{}".format(default_country_code.lstrip("+"), digits[1:])
    return raw


_HOUSE_NUMBER = re.compile(r"^\s*(\d+)")
# 郵便番号は4〜6桁。番地(1〜3桁が大半)と取り違えないよう桁数で区別する。
_POSTCODE = re.compile(r"\b(\d{4,6})\b")


def address_key(address: Optional[str]) -> str:
    """住所から「番地|郵便番号」を取り出す。

    表記揺れ（"Pass." / "Passage"、区切り記号の違い）に強い部分だけを使う。
    同じチェーンの別支店を見分けるための最小の識別子。
    """
    text = clean_text(address)
    if not text:
        return ""
    normalized = strip_accents(text)
    house_match = _HOUSE_NUMBER.match(normalized)
    house = house_match.group(1) if house_match else ""
    codes = _POSTCODE.findall(normalized)
    # 郵便番号は住所の末尾寄りに来るので最後の一致を採る（先頭は番地のことがある）。
    postcode = codes[-1] if codes else ""
    if house and postcode and house == postcode and len(codes) == 1:
        postcode = ""  # 数字が1つしかない住所を番地と郵便番号に二重計上しない
    return "{}|{}".format(house, postcode)


def dedupe_key(name: str, city: str, website: str, address: str = "") -> str:
    """突き合わせキー。

    自社サイトを持つ店はドメインが最も強い identity。ただしチェーン店
    （Rougier&Plé など）は全店が同一ドメインなので、ドメインだけで束ねると
    支店が1件に潰れる。同じ理由で Wix や sites.google.com のような共有ドメインも
    危ない。そこで住所（番地＋郵便番号）を識別子に加える。

    住所が取れない場合は店名にフォールバックする。過剰統合（別の店が1件に潰れる）
    は取り返しがつかないが、統合漏れは送信前にメールアドレスで弾けるため、
    迷ったら分ける側に倒している。
    """
    city_slug = slug(city)
    place = address_key(address)
    host = domain_of(website)
    if host:
        return "web:{}|{}|{}".format(host, city_slug, place or slug(name))
    return "name:{}|{}|{}".format(slug(name), city_slug, place)
