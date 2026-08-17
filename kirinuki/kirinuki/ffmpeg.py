"""ffmpeg の場所を解決して呼び出す。

システムに ffmpeg が入っていればそれを使い、無ければ pip の imageio-ffmpeg が
同梱するバイナリにフォールバックする。編集ソフトしか入れていないPCでも
`pip install imageio-ffmpeg` だけで動かせるようにするため。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache
from typing import Dict, List, Optional


class FFmpegMissing(RuntimeError):
    pass


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    override = os.environ.get("KIRINUKI_FFMPEG")
    if override:
        return override
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise FFmpegMissing(
            "ffmpeg が見つかりません。次のどちらかを実行してください:\n"
            "  pip install imageio-ffmpeg      （かんたん）\n"
            "  ffmpeg を入れて PATH に通す      （既に入っているなら）"
        )


@lru_cache(maxsize=1)
def available_encoders() -> frozenset:
    """この ffmpeg が使えるエンコーダ名の集合。"""
    result = subprocess.run(
        [ffmpeg_path(), "-v", "quiet", "-encoders"],
        capture_output=True, text=True, errors="replace",
    )
    names = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        # " V....D h264_nvenc  NVIDIA NVENC H.264 encoder" の形
        if len(parts) >= 2 and parts[0] and parts[0][0] in "VAS":
            names.add(parts[1])
    return frozenset(names)


def pick_encoder(preference: str = "auto") -> str:
    """使うエンコーダを決める。

    NVIDIA GPU があれば h264_nvenc のほうが数倍速い。ただし ffmpeg のビルドに
    含まれていないことがあるので、auto では存在を確認してから選ぶ。
    """
    if preference == "cpu":
        return "libx264"
    encoders = available_encoders()
    if preference == "nvenc":
        if "h264_nvenc" not in encoders:
            raise SystemExit(
                "この ffmpeg は h264_nvenc に対応していません。\n"
                "GPUを使うには NVIDIA 対応ビルドの ffmpeg が必要です。\n"
                "（--encoder cpu を付ければCPUで実行できます）"
            )
        return "h264_nvenc"
    return "h264_nvenc" if "h264_nvenc" in encoders else "libx264"


def run(args: List[str], capture: bool = True) -> subprocess.CompletedProcess:
    """ffmpeg を呼ぶ。args は実行ファイル名を除いた引数のみ。"""
    command = [ffmpeg_path()] + args
    return subprocess.run(command, capture_output=capture, text=not capture)


def probe_duration(path: str) -> Optional[float]:
    """動画の長さ(秒)。取れなければ None。

    ffprobe が無い環境もあるので、ffmpeg の標準エラー出力から読む。
    """
    result = subprocess.run(
        [ffmpeg_path(), "-i", path], capture_output=True, text=True, errors="replace"
    )
    for line in result.stderr.splitlines():
        if "Duration:" not in line:
            continue
        stamp = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
        try:
            hours, minutes, seconds = stamp.split(":")
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except ValueError:
            return None
    return None


def list_audio_tracks(path: str) -> List[Dict[str, str]]:
    """動画に入っている音声トラックを列挙する。

    ゲームバーの録画はマイクとゲーム音が1本に混ざっているため、どちらが鳴ったのか
    区別できない。OBS のように別トラックで録っておけば、マイクだけを解析できる。
    """
    result = subprocess.run(
        [ffmpeg_path(), "-i", path], capture_output=True, text=True, errors="replace"
    )
    tracks: List[Dict[str, str]] = []
    pattern = re.compile(r"Stream #0:(\d+)(?:\[[^\]]*\])?(?:\(([^)]*)\))?: Audio: ([^\n]*)")
    for line in result.stderr.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        tracks.append({
            "index": str(len(tracks)),        # -map 0:a:N で使う番号
            "stream": match.group(1),
            "language": match.group(2) or "",
            "detail": match.group(3).strip(),
        })
    return tracks


def iter_pcm(path: str, rate: int = 16000, threads: int = 0,
             track: int = 0, chunk_frames: int = 1 << 19):
    """音声を少しずつ読み出す。

    3時間の素材だと PCM は 350MB になる。一度に抱えると numpy の変換で
    その倍を使うので、区切って流す。こうすると常時数MBで済む。
    映像はデコードしないので、CPU負荷も低い。
    """
    args = [ffmpeg_path(), "-v", "quiet"]
    if threads:
        args += ["-threads", str(threads)]
    args += ["-i", path, "-map", "0:a:{}".format(track),
             "-f", "s16le", "-ac", "1", "-ar", str(rate), "-"]

    process = subprocess.Popen(args, stdout=subprocess.PIPE)
    produced = False
    try:
        while True:
            block = process.stdout.read(chunk_frames * 2)  # 16bit = 2バイト
            if not block:
                break
            produced = True
            yield block
    finally:
        if process.stdout:
            process.stdout.close()
        process.wait()

    if not produced:
        raise RuntimeError(
            "音声を読み取れませんでした: {}\n"
            "ファイルが壊れているか、音声トラックがない可能性があります。".format(path)
        )


def read_pcm(path: str, rate: int = 16000, track: int = 0) -> bytes:
    """音声を 16bit モノラル PCM として取り出す。

    解析に必要なのは音量の変化だけなので、16kHz まで落として読み込み量を減らす。
    3時間の素材でも 350MB 程度に収まる。
    """
    result = run([
        "-v", "quiet", "-i", path, "-map", "0:a:{}".format(track),
        "-f", "s16le", "-ac", "1", "-ar", str(rate), "-",
    ])
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(
            "音声を読み取れませんでした: {}\n"
            "ファイルが壊れているか、音声トラックがない可能性があります。".format(path)
        )
    return result.stdout
