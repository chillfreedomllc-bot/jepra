"""出力先などの設定を憶えておく。

Windows の .bat には日本語を書けない（CP932 で読まれて壊れる）ので、
「ビデオ\\ショート用切り抜き」のような保存先を .bat 側に持たせられない。
そこで Python 側の JSON に置く。こちらは UTF-8 で素直に読める。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

FILENAME = "kirinuki.json"


def config_path(base: Optional[str] = None) -> str:
    """設定ファイルの置き場所。.bat と同じフォルダに置く。"""
    if base:
        return os.path.join(base, FILENAME)
    # パッケージの親 = 配布フォルダ（1_候補を出す.bat がある場所）
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        FILENAME)


def load(base: Optional[str] = None) -> Dict[str, Any]:
    """設定を読む。カレントに置かれていればそちらを優先する。"""
    candidates = [os.path.join(os.getcwd(), FILENAME), config_path(base)]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            # 壊れた設定で実行を止めない。既定値で動けば十分。
            continue
    return {}


def save(values: Dict[str, Any], base: Optional[str] = None) -> str:
    path = config_path(base)
    existing = load(base)
    existing.update({k: v for k, v in values.items() if v is not None})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


def resolve_out_dir(
    explicit: Optional[str],
    source_video: str,
    suffix: str = "kirinuki_out",
) -> str:
    """出力先を決める。--out > 設定ファイル > 動画と同じ場所。

    設定に保存先があれば、その中に動画名のフォルダを作る。素材ごとに分かれて
    いないと、次の動画を処理したときに前回のクリップと混ざるため。
    """
    if explicit:
        return explicit

    configured = load().get("out_dir")
    if configured:
        stem = os.path.splitext(os.path.basename(source_video))[0]
        return os.path.join(configured, stem)

    return os.path.join(os.path.dirname(os.path.abspath(source_video)), suffix)
