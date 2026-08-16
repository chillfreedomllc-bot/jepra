"""多言語のアプローチ文面と A/B バリアント。

バリアントは「文章を良くする」ためではなく、**測るため**にある。
A（条件提示型）と B（店舗個別の理由から入る型）を機械的に半々で割り当て、
返信率の差を `jepra stats --by variant` で見る。差が出たら勝ち筋に寄せる。

配信停止の一文は全文面に必ず入れる。GDPR 対応であると同時に、
迷惑メール判定を避けて到達率を守るためでもある。
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import asdict, dataclass, fields
from typing import Dict, Tuple

from ..models import Lead

PROFILE_PATH = os.environ.get("JEPRA_PROFILE", "jepra.profile.json")


@dataclass
class Profile:
    """差出人側の情報。案件ごとに1ファイル作る。"""

    sender_name: str = "<担当者名>"
    company: str = "<自社名>"
    origin: str = "Japon"
    product: str = "<商品カテゴリ>"
    product_desc: str = "<商品の一言説明>"
    website: str = "<自社サイトURL>"
    reply_to: str = "<返信先メールアドレス>"
    catalog_url: str = "<カタログURL>"
    moq: str = "<最低発注額>"
    lead_time: str = "<納期>"

    @classmethod
    def load(cls, path: str = PROFILE_PATH) -> "Profile":
        if not os.path.exists(path):
            return cls()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: str = PROFILE_PATH) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, ensure_ascii=False, indent=2)
            fh.write("\n")


load_profile = Profile.load


# 「評価が高い」と言及できる下限。これ未満の店には触れない（皮肉に読まれる）。
PRAISE_THRESHOLD = 4.3

_PRAISE = {
    "fr": " — et vos clients vous notent {rating}/5",
    "en": " — and your customers rate you {rating}/5",
    "ja": "（お客様評価 {rating}/5）",
}

_OPT_OUT = {
    "fr": "Si vous ne souhaitez plus recevoir nos messages, répondez simplement "
          "« STOP » : nous vous retirerons immédiatement de notre liste.",
    "en": "If you would rather not hear from us again, just reply \"STOP\" and "
          "we will remove you from our list immediately.",
    "ja": "今後の配信が不要な場合は「配信停止」とご返信ください。ただちに削除いたします。",
}

_SIGNATURE = "{sender_name}\n{company}\n{website} / {reply_to}"


# template -> lang -> variant -> (subject, body)
TEMPLATES: Dict[str, Dict[str, Dict[str, Tuple[str, str]]]] = {
    "intro": {
        "fr": {
            "A": (
                "{product} japonais — proposition de gros pour {store_name}",
                "Bonjour,\n\n"
                "Je me permets de vous écrire au sujet de {store_name}, à {city}.\n\n"
                "Je suis {sender_name}, de {company} ({origin}). Nous distribuons "
                "{product} : {product_desc}.\n\n"
                "Nos conditions pour les revendeurs :\n"
                "- Commande minimum : {moq}\n"
                "- Délai de livraison : {lead_time}\n"
                "- Catalogue : {catalog_url}\n\n"
                "Si cela vous intéresse, je vous envoie le catalogue complet avec les "
                "tarifs de gros. Une réponse d'un mot suffit.\n\n"
                "Bien cordialement,\n" + _SIGNATURE + "\n\n--\n{opt_out}",
            ),
            "B": (
                "{store_name} — une sélection japonaise qui pourrait vous plaire",
                "Bonjour,\n\n"
                "J'ai découvert {store_name} en cherchant les meilleures papeteries "
                "indépendantes de {city}{praise}. C'est exactement le type de boutique "
                "à qui nous aimerions confier nos produits.\n\n"
                "{company} distribue {product} : {product_desc}.\n\n"
                "La plupart de nos revendeurs européens ont commencé par une petite "
                "commande d'essai ({moq}), livrée en {lead_time}.\n\n"
                "Souhaitez-vous recevoir le catalogue et les tarifs de gros ? "
                "Je peux vous les envoyer dès aujourd'hui.\n\n"
                "Bien cordialement,\n" + _SIGNATURE + "\n\n--\n{opt_out}",
            ),
        },
        "en": {
            "A": (
                "Japanese {product} — wholesale proposal for {store_name}",
                "Hello,\n\n"
                "I am writing to you about {store_name} in {city}.\n\n"
                "My name is {sender_name}, from {company} ({origin}). We supply "
                "{product}: {product_desc}.\n\n"
                "Our reseller terms:\n"
                "- Minimum order: {moq}\n"
                "- Lead time: {lead_time}\n"
                "- Catalogue: {catalog_url}\n\n"
                "If this is of interest, I will send the full catalogue with wholesale "
                "prices. A one-word reply is enough.\n\n"
                "Kind regards,\n" + _SIGNATURE + "\n\n--\n{opt_out}",
            ),
            "B": (
                "{store_name} — a Japanese range that might suit your shop",
                "Hello,\n\n"
                "I came across {store_name} while looking for the best independent "
                "stationery shops in {city}{praise}. Yours is exactly the kind of shop "
                "we would like to see carrying our products.\n\n"
                "{company} supplies {product}: {product_desc}.\n\n"
                "Most of our European stockists began with a small trial order ({moq}), "
                "delivered in {lead_time}.\n\n"
                "Would you like the catalogue and wholesale price list? "
                "I can send it today.\n\n"
                "Kind regards,\n" + _SIGNATURE + "\n\n--\n{opt_out}",
            ),
        },
        "ja": {
            "A": (
                "【卸のご提案】{product}／{store_name} 御中",
                "{store_name} ご担当者様\n\n"
                "突然のご連絡失礼いたします。{company}の{sender_name}と申します。\n\n"
                "弊社では{product}（{product_desc}）を取り扱っております。\n\n"
                "お取引条件:\n"
                "・最低発注: {moq}\n"
                "・納期: {lead_time}\n"
                "・カタログ: {catalog_url}\n\n"
                "ご関心がございましたら、卸価格表を含む資料一式をお送りいたします。"
                "ひと言ご返信いただくだけで結構です。\n\n"
                + _SIGNATURE + "\n\n--\n{opt_out}",
            ),
            "B": (
                "{store_name} 様に合いそうな商材のご紹介",
                "{store_name} ご担当者様\n\n"
                "{city}の文具店を調べる中で{store_name}様を拝見しました{praise}。"
                "弊社の商品をお預けしたいのは、まさにこうしたお店です。\n\n"
                "{company}では{product}（{product_desc}）を取り扱っております。\n\n"
                "多くの取引先様は、まず少量のお試し発注（{moq}／納期{lead_time}）から"
                "始められています。\n\n"
                "カタログと卸価格表をお送りしてもよろしいでしょうか。\n\n"
                + _SIGNATURE + "\n\n--\n{opt_out}",
            ),
        },
    },
    "followup": {
        "fr": {
            "A": (
                "Re: {product} japonais pour {store_name}",
                "Bonjour,\n\n"
                "Je me permets de revenir vers vous — mon message précédent s'est "
                "peut-être perdu.\n\n"
                "Si le sujet n'est pas d'actualité, dites-le moi simplement et "
                "je n'insisterai pas. Si en revanche vous souhaitez voir le catalogue "
                "et les tarifs, je vous les envoie immédiatement.\n\n"
                "Bien cordialement,\n" + _SIGNATURE + "\n\n--\n{opt_out}",
            ),
            "B": (
                "Une dernière fois au sujet de {store_name}",
                "Bonjour,\n\n"
                "Je ne veux pas encombrer votre boîte mail, donc ce sera mon dernier "
                "message.\n\n"
                "Notre catalogue de {product} reste à votre disposition : {catalog_url}\n\n"
                "Si un jour le sujet devient pertinent pour {store_name}, "
                "écrivez-moi simplement.\n\n"
                "Bien cordialement,\n" + _SIGNATURE + "\n\n--\n{opt_out}",
            ),
        },
        "en": {
            "A": (
                "Re: Japanese {product} for {store_name}",
                "Hello,\n\n"
                "Following up briefly — my earlier message may have gone astray.\n\n"
                "If this is not relevant right now, just say so and I will not press "
                "further. If you would like the catalogue and price list, I will send "
                "it straight away.\n\n"
                "Kind regards,\n" + _SIGNATURE + "\n\n--\n{opt_out}",
            ),
            "B": (
                "One last note about {store_name}",
                "Hello,\n\n"
                "I do not want to clutter your inbox, so this is my last message.\n\n"
                "Our {product} catalogue remains available here: {catalog_url}\n\n"
                "If it ever becomes relevant for {store_name}, just drop me a line.\n\n"
                "Kind regards,\n" + _SIGNATURE + "\n\n--\n{opt_out}",
            ),
        },
        "ja": {
            "A": (
                "Re: {product}のご提案／{store_name} 御中",
                "{store_name} ご担当者様\n\n"
                "先日お送りしたご案内につきまして、念のため再度ご連絡いたしました。\n\n"
                "ご不要でしたらその旨お返しいただければ、以後のご連絡は控えます。"
                "カタログと価格表をご希望でしたら、すぐにお送りいたします。\n\n"
                + _SIGNATURE + "\n\n--\n{opt_out}",
            ),
            "B": (
                "{store_name} 様への最後のご連絡",
                "{store_name} ご担当者様\n\n"
                "何度もお送りするのは本意ではありませんので、本メールを最後といたします。\n\n"
                "{product}のカタログはこちらでご覧いただけます: {catalog_url}\n\n"
                "将来ご入用の際に思い出していただければ幸いです。\n\n"
                + _SIGNATURE + "\n\n--\n{opt_out}",
            ),
        },
    },
}


def template_names() -> list:
    return sorted(TEMPLATES)


def pick_variant(lead_id: int, variant: str = "auto") -> str:
    """A/B を決める。auto なら lead_id で機械的に半々に割る。

    ランダムではなく id 基準にすることで、同じリードは何度実行しても同じ枝に入る。
    途中で条件が変わらないので、集計が後から崩れない。
    """
    if variant and variant != "auto":
        return variant.upper()
    return "A" if lead_id % 2 == 0 else "B"


def resolve_lang(lead: Lead, lang: str = "auto") -> str:
    if lang and lang != "auto":
        return lang
    from ..sources.base import COUNTRY_LANG

    resolved = COUNTRY_LANG.get(lead.country, "en")
    # テンプレートを用意していない言語は英語に落とす。
    return resolved if resolved in TEMPLATES["intro"] else "en"


def render(
    lead: Lead,
    profile: Profile,
    template: str = "intro",
    lang: str = "auto",
    variant: str = "auto",
) -> Tuple[str, str, str, str]:
    """(subject, body, lang, variant) を返す。"""
    if template not in TEMPLATES:
        raise SystemExit(
            "未知のテンプレート '{}'。使えるのは: {}".format(
                template, ", ".join(template_names())
            )
        )
    resolved_lang = resolve_lang(lead, lang)
    resolved_variant = pick_variant(lead.id or 0, variant)

    by_lang = TEMPLATES[template]
    by_variant = by_lang.get(resolved_lang, by_lang["en"])
    if resolved_variant not in by_variant:
        resolved_variant = "A"
    subject_tpl, body_tpl = by_variant[resolved_variant]

    praise = ""
    if lead.rating is not None and lead.rating >= PRAISE_THRESHOLD:
        praise = _PRAISE.get(resolved_lang, _PRAISE["en"]).format(
            rating="{:.1f}".format(lead.rating)
        )

    context = defaultdict(str, asdict(profile))
    context.update({
        "store_name": lead.name,
        "city": lead.city or lead.country,
        "praise": praise,
        "opt_out": _OPT_OUT.get(resolved_lang, _OPT_OUT["en"]),
    })

    return (
        subject_tpl.format_map(context),
        body_tpl.format_map(context),
        resolved_lang,
        resolved_variant,
    )
