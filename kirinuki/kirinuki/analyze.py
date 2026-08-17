"""音声から「盛り上がっている場所」を見つける。

考え方はひとつだけ。**その素材の普段の音量からどれだけ跳ねたか**を見る。
絶対的な音量で判定すると、録音レベルが違う素材で毎回しきい値を調整する羽目になる。

ホラーゲーム実況向けに、もう一段の工夫を入れている。
悲鳴そのものより、**直前が静かだったか**を加点している。静かに歩く→悲鳴、
という落差が切り抜きとして成立する形で、悲鳴だけを切っても面白くならないため。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np

# 無音とみなす下限。これより下の窓はベースラインの計算から外す。
# ゲーム実況にはBGMや環境音が常にあるので、真の無音はほぼ無い。
SILENCE_FLOOR_DB = -55.0


@dataclass
class Level:
    time: float
    db: float


@dataclass
class Moment:
    """盛り上がっている一区間。"""

    start: float          # 音が跳ねはじめた時刻
    end: float            # 収まった時刻
    peak_db: float
    excess_db: float      # ベースラインからの超過
    quiet_before_db: float  # 直前5秒の音量（低いほど落差が大きい）
    score: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Clip:
    """実際に切り出す範囲。Moment に前フリと余韻を足したもの。"""

    start: float
    end: float
    score: float
    moments: List[Moment]

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def peak_db(self) -> float:
        return max(m.peak_db for m in self.moments)


def _db_of_frames(samples: np.ndarray, size: int) -> np.ndarray:
    """窓ごとの dBFS を計算する。"""
    # int16 のまま二乗すると溢れるので float に上げてから計算する。
    frames = samples.astype(np.float32).reshape(-1, size)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    rms = np.maximum(rms, 1.0)  # log(0) を避ける
    return 20.0 * np.log10(rms / 32768.0)


def levels_from_pcm(pcm: bytes, rate: int = 16000, window: float = 0.5) -> List[Level]:
    """PCM 全体を一度に受け取って dBFS 列に変換する（短い素材・テスト用）。"""
    return levels_from_chunks([pcm], rate=rate, window=window)


def levels_from_chunks(chunks, rate: int = 16000, window: float = 0.5) -> List[Level]:
    """PCM の断片を順に受け取って dBFS 列にする。

    長い素材でもメモリを数MBに保つため、窓の整数倍だけ処理して端数は次に繰り越す。
    """
    size = max(int(rate * window), 1)
    levels: List[Level] = []
    carry = np.empty(0, dtype=np.int16)
    index = 0

    for chunk in chunks:
        block = np.frombuffer(chunk, dtype=np.int16)
        samples = np.concatenate((carry, block)) if carry.size else block
        usable = (samples.size // size) * size
        if usable:
            for value in _db_of_frames(samples[:usable], size):
                levels.append(Level(index * window, float(value)))
                index += 1
        # 端数はコピーして持ち越す（ビューのままだと元データを掴み続けるため）。
        carry = np.array(samples[usable:], dtype=np.int16)

    return levels


def baseline_db(levels: Sequence[Level]) -> float:
    """その素材の「普段の音量」。無音窓を除いた中央値。"""
    audible = [l.db for l in levels if l.db > SILENCE_FLOOR_DB]
    if not audible:
        return float(np.median([l.db for l in levels])) if levels else SILENCE_FLOOR_DB
    return float(np.median(audible))


def _quiet_before(levels: Sequence[Level], index: int, window: float,
                  lookback: float = 5.0) -> float:
    """直前 lookback 秒の平均音量。落差の判定に使う。"""
    span = max(int(lookback / window), 1)
    start = max(index - span, 0)
    if start >= index:
        return levels[index].db
    return float(np.mean([l.db for l in levels[start:index]]))


def find_moments(
    levels: Sequence[Level],
    window: float = 0.5,
    threshold_db: float = 8.0,
    min_duration: float = 0.4,
    merge_gap: float = 2.0,
) -> List[Moment]:
    """ベースラインを threshold_db 超えた区間を拾う。"""
    if not levels:
        return []
    base = baseline_db(levels)
    limit = base + threshold_db

    # まず「超えている窓」を連続区間にまとめる。
    spans: List[List[int]] = []
    current: Optional[List[int]] = None
    for index, level in enumerate(levels):
        if level.db >= limit:
            if current is None:
                current = [index, index]
            else:
                current[1] = index
        elif current is not None:
            spans.append(current)
            current = None
    if current is not None:
        spans.append(current)

    # 近すぎる区間は1つの出来事とみなす（悲鳴が途切れて2回鳴るのは1回の反応）。
    merged: List[List[int]] = []
    for span in spans:
        if merged and (span[0] - merged[-1][1]) * window <= merge_gap:
            merged[-1][1] = span[1]
        else:
            merged.append(span)

    moments: List[Moment] = []
    for first, last in merged:
        start = levels[first].time
        end = levels[last].time + window
        if end - start < min_duration:
            continue
        peak = max(l.db for l in levels[first:last + 1])
        quiet = _quiet_before(levels, first, window)

        excess = peak - base
        # 落差の加点。直前がベースラインより静かなほど効く（上限12dB）。
        contrast = min(max(base - quiet, 0.0), 12.0)
        # 一瞬のノイズより、続いた反応を上に置く（上限2秒ぶん）。
        sustain = min(end - start, 2.0)
        score = excess + contrast * 0.8 + sustain * 2.0

        moments.append(Moment(
            start=start, end=end, peak_db=peak, excess_db=excess,
            quiet_before_db=quiet, score=round(score, 2),
        ))
    return moments


def build_clips(
    moments: Sequence[Moment],
    duration: Optional[float] = None,
    pre_roll: float = 8.0,
    post_roll: float = 3.0,
    max_length: float = 55.0,
) -> List[Clip]:
    """Moment に前フリと余韻を足し、重なるものは1本にまとめる。

    pre_roll を長めに取っているのはホラー向けの既定値。悲鳴の瞬間だけ切っても
    見ている側は何が起きたか分からず、落差も伝わらないため。
    max_length はショートの上限(60秒)に収めるための頭打ち。
    """
    clips: List[Clip] = []
    for moment in sorted(moments, key=lambda m: m.start):
        start = max(moment.start - pre_roll, 0.0)
        end = moment.end + post_roll
        if duration is not None:
            end = min(end, duration)

        if clips and start <= clips[-1].end:
            # 重なる場合は延長して1本にする。切り抜きが二重になるのを防ぐ。
            previous = clips[-1]
            previous.end = max(previous.end, end)
            previous.moments.append(moment)
            previous.score = round(max(previous.score, moment.score)
                                   + 0.5 * (len(previous.moments) - 1), 2)
        else:
            clips.append(Clip(start=start, end=end, score=moment.score,
                              moments=[moment]))

    # 長くなりすぎたものは、一番強い Moment を中心に切り詰める。
    for clip in clips:
        if clip.duration <= max_length:
            continue
        best = max(clip.moments, key=lambda m: m.score)
        clip.start = max(best.start - pre_roll, 0.0)
        clip.end = clip.start + max_length
        if duration is not None and clip.end > duration:
            clip.end = duration
            clip.start = max(duration - max_length, 0.0)

    return sorted(clips, key=lambda c: c.score, reverse=True)


def format_timestamp(seconds: float) -> str:
    """0:07:23.5 の形。CapCut でスクラブするときに読む用。"""
    if seconds < 0:
        seconds = 0.0
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return "{}:{:02d}:{:04.1f}".format(int(hours), int(minutes), secs)


def parse_timestamp(text: str) -> float:
    """format_timestamp の逆。手で書いた 1:23 のような短い形も受ける。"""
    parts = [float(p) for p in str(text).strip().split(":")]
    total = 0.0
    for part in parts:
        total = total * 60 + part
    return total


__all__ = [
    "Clip", "Level", "Moment", "baseline_db", "build_clips", "find_moments",
    "format_timestamp", "levels_from_chunks", "levels_from_pcm", "parse_timestamp",
]
