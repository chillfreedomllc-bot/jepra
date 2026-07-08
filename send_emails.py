#!/usr/bin/env python3
"""CSV(店名・メールアドレス・件名・本文)を読み込み、Gmailアプリパスワードでメールを送信する。

環境変数:
  GMAIL_ADDRESS      送信元Gmailアドレス
  GMAIL_APP_PASSWORD Gmailのアプリパスワード

使い方:
  python3 send_emails.py --dry-run   # 送信内容を一覧表示するだけ(実際には送らない)
  python3 send_emails.py             # 実際に送信する
"""

import argparse
import csv
import os
import random
import smtplib
import sys
import time
from datetime import datetime
from email.message import EmailMessage

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

MIN_DELAY_SEC = 20
MAX_DELAY_SEC = 40

OPT_OUT_FOOTER = "\n\n---\n今後のご連絡が不要な場合はご返信ください。"

LOG_FIELDS = ["日時", "店名", "メールアドレス", "件名", "結果", "エラー内容"]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="paris_papeterie_list_final.csv", help="送信元CSVファイル")
    parser.add_argument("--log", default="send_log.csv", help="送信結果を記録するログCSVファイル")
    parser.add_argument("--dry-run", action="store_true", help="実際には送信せず、送信予定を一覧表示する")
    return parser.parse_args()


def load_rows(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_sent_addresses(log_path):
    """send_log.csv から送信成功済みのメールアドレス(小文字化)の集合を返す。"""
    sent = set()
    if not os.path.exists(log_path):
        return sent
    with open(log_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("結果") == "成功" and row.get("メールアドレス"):
                sent.add(row["メールアドレス"].strip().lower())
    return sent


def append_log(log_path, entry):
    is_new = not os.path.exists(log_path)
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(entry)


def classify_rows(rows, already_sent):
    """行を (送信対象, フォームのみ等でスキップ, 送信済みでスキップ) に分類する。"""
    to_send, skip_no_email, skip_already_sent = [], [], []
    for row in rows:
        name = row.get("店名", "").strip()
        email = row.get("メールアドレス", "").strip()

        if not email or email == "フォームのみ":
            skip_no_email.append(name)
            continue

        if email.lower() in already_sent:
            skip_already_sent.append(name)
            continue

        to_send.append(row)
    return to_send, skip_no_email, skip_already_sent


def build_message(from_addr, row):
    name = row.get("店名", "").strip()
    to_addr = row.get("メールアドレス", "").strip()
    subject = row.get("件名", "").strip()
    body = row.get("本文", "").strip() + OPT_OUT_FOOTER

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    return msg, name, to_addr, subject


def print_dry_run(to_send, skip_no_email, skip_already_sent):
    print(f"=== 送信予定 ({len(to_send)}件) ===")
    for row in to_send:
        name = row.get("店名", "").strip()
        email = row.get("メールアドレス", "").strip()
        subject = row.get("件名", "").strip()
        body_preview = row.get("本文", "").strip().replace("\n", " ")[:60]
        print(f"- {name} <{email}> 件名: {subject}")
        print(f"    本文冒頭: {body_preview}{'...' if len(body_preview) == 60 else ''}")

    if skip_no_email:
        print(f"\n=== スキップ(メール未登録・フォームのみ) ({len(skip_no_email)}件) ===")
        for name in skip_no_email:
            print(f"- {name}")

    if skip_already_sent:
        print(f"\n=== スキップ(送信済み) ({len(skip_already_sent)}件) ===")
        for name in skip_already_sent:
            print(f"- {name}")


def send_all(to_send, from_addr, app_password, log_path):
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(from_addr, app_password)

        for i, row in enumerate(to_send):
            msg, name, to_addr, subject = build_message(from_addr, row)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            try:
                server.send_message(msg)
                print(f"[送信成功] {name} <{to_addr}>")
                append_log(log_path, {
                    "日時": now, "店名": name, "メールアドレス": to_addr,
                    "件名": subject, "結果": "成功", "エラー内容": "",
                })
            except Exception as e:
                print(f"[送信失敗] {name} <{to_addr}>: {e}")
                append_log(log_path, {
                    "日時": now, "店名": name, "メールアドレス": to_addr,
                    "件名": subject, "結果": "失敗", "エラー内容": str(e),
                })

            if i < len(to_send) - 1:
                delay = random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC)
                print(f"  次の送信まで {delay:.1f} 秒待機します...")
                time.sleep(delay)


def main():
    args = parse_args()

    rows = load_rows(args.csv)
    already_sent = load_sent_addresses(args.log)
    to_send, skip_no_email, skip_already_sent = classify_rows(rows, already_sent)

    if args.dry_run:
        print_dry_run(to_send, skip_no_email, skip_already_sent)
        return

    if skip_no_email:
        print(f"=== スキップ(メール未登録・フォームのみ) ({len(skip_no_email)}件) ===")
        for name in skip_no_email:
            print(f"- {name}")
        print()

    from_addr = os.environ.get("GMAIL_ADDRESS")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not from_addr or not app_password:
        print("エラー: 環境変数 GMAIL_ADDRESS と GMAIL_APP_PASSWORD を設定してください。", file=sys.stderr)
        sys.exit(1)

    if not to_send:
        print("送信対象がありません。")
        return

    send_all(to_send, from_addr, app_password, args.log)


if __name__ == "__main__":
    main()
