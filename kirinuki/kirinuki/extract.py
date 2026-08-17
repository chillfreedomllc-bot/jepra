"""候補区間を実ファイルとして切り出す。

CapCut は EDL や XML を受け付けないので、タイムスタンプを渡しても結局
3時間の素材を読み込んでスクラブすることになる。そこで**該当箇所だけの
短いファイル**を出して、それをドラッグしてもらう形にしている。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional

from . import ffmpeg
from .analyze import Clip

# 縦型(9:16)の出力サイズ。ショートの推奨解像度。
VERTICAL_WIDTH = 1080
VERTICAL_HEIGHT = 1920

_UNSAFE = re.compile(r'[\\/:*?"<>|\s]+')


def safe_stem(name: str, limit: int = 40) -> str:
    """ファイル名に使える形にする。日本語はそのまま残す。"""
    cleaned = _UNSAFE.sub("_", name).strip("_")
    return cleaned[:limit] or "clip"


@dataclass
class CutResult:
    path: str
    clip: Clip
    ok: bool
    error: str = ""


def _vertical_filter(style: str) -> str:
    if style == "crop":
        # 中央だけを使う。顔出しワイプがある実況だと端が切れることがある。
        return (
            "scale=-2:{h},crop={w}:{h}".format(w=VERTICAL_WIDTH, h=VERTICAL_HEIGHT)
        )
    # 既定はぼかし背景。ゲーム画面を一切切らずに縦型へ収める。
    return (
        "[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
        "crop={w}:{h},boxblur=25:3[bg];"
        "[0:v]scale={w}:-2[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2"
    ).format(w=VERTICAL_WIDTH, h=VERTICAL_HEIGHT)


def _encoder_args(encoder: str, quality: int) -> List[str]:
    if encoder == "h264_nvenc":
        # p4 は速度と画質の中庸。cq は libx264 の crf に相当する。
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", str(quality)]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(quality)]


def cut_clip(
    source: str,
    clip: Clip,
    out_path: str,
    vertical: bool = False,
    vertical_style: str = "blur",
    crf: int = 20,
    encoder: str = "libx264",
    threads: int = 0,
) -> CutResult:
    """1区間を切り出す。

    ストリームコピーではなく再エンコードする。コピーは直前のキーフレームまで
    戻ってしまい、前フリの秒数がずれるため。切り抜きは秒単位の精度が要る。
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)

    args = ["-v", "error", "-y"]
    if threads:
        args += ["-threads", str(threads)]
    args += [
        "-ss", "{:.3f}".format(clip.start),
        "-i", source,
        "-t", "{:.3f}".format(clip.duration),
    ]
    if vertical:
        filter_text = _vertical_filter(vertical_style)
        if vertical_style == "crop":
            args += ["-vf", filter_text]
        else:
            args += ["-filter_complex", filter_text]
    args += _encoder_args(encoder, crf) + [
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        out_path,
    ]

    result = ffmpeg.run(args)
    if result.returncode != 0 or not os.path.exists(out_path):
        message = ""
        if result.stderr:
            message = result.stderr.decode("utf-8", "replace").strip().splitlines()
            message = message[-1] if message else ""
        return CutResult(out_path, clip, ok=False, error=message or "ffmpeg が失敗しました")
    return CutResult(out_path, clip, ok=True)


def cut_clips(
    source: str,
    clips: List[Clip],
    out_dir: str,
    prefix: Optional[str] = None,
    vertical: bool = False,
    vertical_style: str = "blur",
    encoder: str = "libx264",
    threads: int = 0,
    on_progress=None,
) -> List[CutResult]:
    """複数区間をまとめて切り出す。1本失敗しても残りは続ける。"""
    stem = prefix or safe_stem(os.path.splitext(os.path.basename(source))[0])
    results: List[CutResult] = []
    for index, clip in enumerate(clips, 1):
        suffix = "_vert" if vertical else ""
        name = "{}_{:02d}{}.mp4".format(stem, index, suffix)
        path = os.path.join(out_dir, name)
        result = cut_clip(source, clip, path, vertical=vertical,
                          vertical_style=vertical_style, encoder=encoder,
                          threads=threads)
        results.append(result)
        if on_progress:
            on_progress(index, len(clips), result)
    return results
