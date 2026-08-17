"""テスト用の合成動画を作る。

実況の生素材に似せて、BGMが鳴り続ける中に会話と悲鳴を置く。
「無音の中の物音」ではなく「常時音がある中の跳ね上がり」を検出できるかを
確かめるためで、真の無音を背景にすると検出が簡単すぎて意味がない。
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Tuple

from kirinuki import ffmpeg

# (開始秒, 長さ, 音量, 周波数) 音量は 1.0 が最大
SPEECH = 0.10
SCREAM = 0.55
BGM = 0.012

#: 悲鳴の位置。テスト側でこの時刻を検出できたか照合する。
SCREAM_TIMES: List[float] = [45.0, 100.0, 150.0]

_EVENTS: List[Tuple[float, float, float, int]] = [
    # 実況者はほぼ喋りっぱなし（全体の約85%）。ここを疎にすると、普段の音量が
    # BGMの高さに寄ってしまい、ただの会話まで「反応」として拾ってしまう。
    # 実素材では喋りが基準になるので、そちらに合わせている。
    (2.0, 38.0, SPEECH, 240),
    (48.0, 47.0, SPEECH, 250),
    (103.0, 42.0, SPEECH, 235),
    (152.0, 26.0, SPEECH, 245),
    # 悲鳴。直前に数秒の静寂を置いてある（ホラーの「タメ」）。
    (SCREAM_TIMES[0], 2.5, SCREAM, 880),
    (SCREAM_TIMES[1], 3.0, SCREAM, 920),
    (SCREAM_TIMES[2], 2.0, SCREAM, 900),
]

DURATION = 180


def build(path: str) -> str:
    """合成動画を書き出してパスを返す。既にあれば作り直さない。"""
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    parts = [
        "aevalsrc='{v}*sin(220*2*PI*t)':d={d}:s=44100[bgm]".format(v=BGM, d=DURATION)
    ]
    labels = ["[bgm]"]
    for index, (start, length, volume, freq) in enumerate(_EVENTS):
        label = "[e{}]".format(index)
        delay = int(start * 1000)
        parts.append(
            "aevalsrc='{v}*sin({f}*2*PI*t)':d={d}:s=44100,"
            "adelay={ms}|{ms}{label}".format(
                v=volume, f=freq, d=length, ms=delay, label=label)
        )
        labels.append(label)

    mix = "{}amix=inputs={}:duration=first:normalize=0[a]".format(
        "".join(labels), len(labels))
    filter_complex = ";".join(parts + [mix])

    result = ffmpeg.run([
        "-y", "-v", "error",
        "-f", "lavfi", "-i",
        "testsrc=size=640x360:rate=15:duration={}".format(DURATION),
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-t", str(DURATION),
        path,
    ])
    if result.returncode != 0:
        raise RuntimeError(
            (result.stderr or b"").decode("utf-8", "replace")[-500:]
        )
    return path


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "fixture.mp4"
    print(build(target))
