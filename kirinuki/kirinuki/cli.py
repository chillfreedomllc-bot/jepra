"""kirinuki のコマンドライン。"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from typing import List, Optional

from . import config, ffmpeg
from .analyze import (
    Clip, build_clips, find_moments, format_timestamp, levels_from_chunks,
    profile_levels,
)
from .extract import cut_clips

__version__ = "0.5.1"


def log(message: str = "") -> None:
    print(message, file=sys.stderr, flush=True)


def analyse(path: str, args: argparse.Namespace) -> tuple:
    """素材を読んで候補を返す。scan と cut の共通処理。"""
    if not os.path.exists(path):
        raise SystemExit("ファイルがありません: {}".format(path))

    duration = ffmpeg.probe_duration(path)
    log("解析中: {}{}".format(
        os.path.basename(path),
        "（{}）".format(format_timestamp(duration)) if duration else "",
    ))

    tracks = ffmpeg.list_audio_tracks(path)
    if len(tracks) > 1:
        log("  音声トラック: {}本（{}番目を解析）".format(len(tracks), args.audio_track + 1))
    if args.audio_track >= max(len(tracks), 1):
        raise SystemExit(
            "音声トラック {} 番はありません。この動画には {} 本しかありません。\n"
            "`kirinuki tracks 動画.mp4` で一覧を確認してください。".format(
                args.audio_track + 1, len(tracks)))

    levels = levels_from_chunks(
        ffmpeg.iter_pcm(path, threads=args.threads, track=args.audio_track),
        window=args.window)
    if not levels:
        raise SystemExit("音声が取れませんでした。音声トラックがあるか確認してください。")

    profile = profile_levels(levels, sensitivity=args.sensitivity,
                             threshold_db=args.threshold)
    moments = find_moments(levels, window=args.window, profile=profile,
                           merge_gap=args.merge_gap)
    clips = build_clips(
        moments, duration=duration,
        pre_roll=args.pre_roll, post_roll=args.post_roll, max_length=args.max_length,
    )
    log("  音量: {}".format(profile.describe()))
    log("  反応を検出: {}箇所 → 切り抜き候補 {}本".format(len(moments), len(clips)))

    # 録音レベルが低すぎると、音量の差そのものが潰れて検出が効かなくなる。
    if profile.speech_db < -35.0:
        log("  ※ 録音レベルが低めです（普段 {:.1f} dBFS）。"
            "音の差が出にくく、検出精度が落ちます。".format(profile.speech_db))
    return clips, duration, profile


def print_table(clips: List[Clip], limit: Optional[int]) -> None:
    shown = clips[:limit] if limit else clips
    if not shown:
        log("\n候補が見つかりませんでした。--sensitivity 1.0 で拾いやすくなります。")
        return

    print()
    print("  {:>3}  {:>10}  {:>10}  {:>6}  {:>6}  {:>5}".format(
        "#", "開始", "終了", "長さ", "スコア", "反応"))
    print("  " + "-" * 54)
    for index, clip in enumerate(shown, 1):
        print("  {:>3}  {:>10}  {:>10}  {:>5.1f}s  {:>6.1f}  {:>5}".format(
            index,
            format_timestamp(clip.start),
            format_timestamp(clip.end),
            clip.duration,
            clip.score,
            len(clip.moments),
        ))
    print()
    print("  スコアは「普段の音量からの跳ね上がり＋直前の静けさ＋反応の長さ」の合計。")
    print("  『反応』は、その範囲に含まれる音の跳ね上がりの回数。")


def write_csv(clips: List[Clip], path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["No", "開始", "終了", "開始秒", "終了秒", "長さ秒",
                         "スコア", "反応数", "最大音量dBFS"])
        for index, clip in enumerate(clips, 1):
            writer.writerow([
                index, format_timestamp(clip.start), format_timestamp(clip.end),
                round(clip.start, 2), round(clip.end, 2), round(clip.duration, 2),
                clip.score, len(clip.moments), round(clip.peak_db, 1),
            ])


def cmd_scan(args: argparse.Namespace) -> int:
    clips, _, _ = analyse(args.video, args)
    print_table(clips, args.top)
    if args.csv:
        write_csv(clips[:args.top] if args.top else clips, args.csv)
        log("\nCSVを書き出しました: {}".format(args.csv))
    if clips:
        log("\n切り出すには: kirinuki cut {} --top {}".format(
            args.video, min(args.top or 10, len(clips))))
    return 0


def cmd_cut(args: argparse.Namespace) -> int:
    clips, _, _ = analyse(args.video, args)
    if not clips:
        log("候補がないので切り出しませんでした。--sensitivity 1.0 を試してください。")
        return 1

    selected = clips[:args.top] if args.top else clips
    print_table(selected, None)

    encoder = ffmpeg.pick_encoder(args.encoder)
    suffix = "kirinuki_shorts" if args.vertical else "kirinuki_out"
    out_dir = config.resolve_out_dir(args.out, args.video, suffix)
    log("\n切り出し中 → {}/  （エンコーダ: {}{}）".format(
        out_dir, encoder, " ＝GPU" if encoder == "h264_nvenc" else " ＝CPU"))

    def progress(index: int, total: int, result) -> None:
        mark = "✓" if result.ok else "✗"
        log("  {} {}/{}  {}{}".format(
            mark, index, total, os.path.basename(result.path),
            "  " + result.error if not result.ok else ""))

    results = cut_clips(
        args.video, selected, out_dir,
        vertical=args.vertical, vertical_style=args.vertical_style,
        encoder=encoder, threads=args.threads, speed=args.speed,
        on_progress=progress,
    )
    ok = sum(1 for r in results if r.ok)
    log("\n完了: {}/{} 本".format(ok, len(results)))
    if ok:
        log("このフォルダの mp4 を CapCut にドラッグしてください。")
    return 0 if ok == len(results) else 1


def cmd_tracks(args: argparse.Namespace) -> int:
    """音声トラックを一覧する。どれがマイクかを確かめるため。"""
    tracks = ffmpeg.list_audio_tracks(args.video)
    if not tracks:
        print("音声トラックが見つかりませんでした。")
        return 1

    print("音声トラック {}本".format(len(tracks)))
    for track in tracks:
        print("  --audio-track {}  {}{}".format(
            track["index"],
            track["detail"],
            "  [{}]".format(track["language"]) if track["language"] else ""))
    if len(tracks) == 1:
        print()
        print("1本しかないため、マイクとゲーム音が混ざっています。")
        print("どちらが鳴ったのか区別できないので、検出の精度には限界があります。")
        print("OBS で音声を別トラックに分けて録ると、マイクだけを解析できます。")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """保存先などを憶えさせる。以後 --out を毎回書かなくてよくなる。"""
    if args.out:
        expanded = os.path.abspath(os.path.expanduser(args.out))
        path = config.save({"out_dir": expanded})
        print("保存先を憶えました: {}".format(expanded))
        print("  設定ファイル: {}".format(path))
        print("  以後、切り抜きは この中に「動画名のフォルダ」を作って入ります。")
        return 0

    current = config.load()
    if not current:
        print("設定はまだありません。")
        print('  例: kirinuki config --out "C:\\Users\\PC_User\\Videos\\ショート用切り抜き"')
        return 0
    print("設定ファイル: {}".format(config.config_path()))
    for key, value in sorted(current.items()):
        print("  {} = {}".format(key, value))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kirinuki",
        description="ゲーム実況の生素材から、盛り上がっている場所を見つけて切り出す",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  kirinuki scan 実況.mp4                 候補を一覧するだけ\n"
            "  kirinuki scan 実況.mp4 --csv out.csv   一覧をCSVに保存\n"
            "  kirinuki cut  実況.mp4 --top 10        上位10本を切り出す\n"
            "  kirinuki cut  実況.mp4 --top 5 --vertical   縦型(ショート用)で出す\n"
        ),
    )
    parser.add_argument("--version", action="version",
                        version="kirinuki {}".format(__version__))
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("video", help="生素材の動画ファイル")
        sub.add_argument("--sensitivity", type=float, default=1.5,
                         help="拾う厳しさ (既定 %(default)s)。"
                              "候補が多すぎるなら 2.0、少なすぎるなら 1.0")
        sub.add_argument("--threshold", type=float, default=None,
                         help="dBで直接指定する場合（普段の音量からの差）。"
                              "指定すると --sensitivity より優先される")
        sub.add_argument("--pre-roll", type=float, default=8.0,
                         help="反応の何秒前から切るか (既定 %(default)s)")
        sub.add_argument("--post-roll", type=float, default=3.0,
                         help="反応の何秒後まで切るか (既定 %(default)s)")
        sub.add_argument("--max-length", type=float, default=55.0,
                         help="1本の上限秒数 (既定 %(default)s＝ショートに収まる長さ)")
        sub.add_argument("--merge-gap", type=float, default=2.0,
                         help="この秒数以内の反応は1つにまとめる (既定 %(default)s)")
        sub.add_argument("--window", type=float, default=0.5,
                         help="音量を測る窓の長さ (既定 %(default)s秒)")
        sub.add_argument("--audio-track", type=int, default=0,
                         help="解析する音声トラック番号（0始まり）。OBSでマイクを"
                              "別トラックに録っている場合に指定する")
        sub.add_argument("--threads", type=int, default=0,
                         help="ffmpegが使うCPUスレッド数の上限。"
                              "0=制限なし。他の作業と並行するなら 2 程度を指定")

    p = subparsers.add_parser("scan", help="候補を一覧する（ファイルは作らない）")
    add_common(p)
    p.add_argument("--top", type=int, default=20, help="表示する本数 (既定 %(default)s)")
    p.add_argument("--csv", default="", help="一覧をCSVに書き出す")
    p.set_defaults(func=cmd_scan)

    p = subparsers.add_parser("tracks", help="音声トラックを一覧する")
    p.add_argument("video")
    p.set_defaults(func=cmd_tracks)

    p = subparsers.add_parser("config", help="保存先を憶えさせる")
    p.add_argument("--out", default="",
                   help="切り抜きの保存先フォルダ。省略すると現在の設定を表示する")
    p.set_defaults(func=cmd_config)

    p = subparsers.add_parser("cut", help="候補をmp4に切り出す")
    add_common(p)
    p.add_argument("--top", type=int, default=10, help="切り出す本数 (既定 %(default)s)")
    p.add_argument("--out", default="",
                   help="出力フォルダ。省略時は kirinuki config で憶えさせた場所、"
                        "それも無ければ動画と同じ場所")
    p.add_argument("--vertical", action="store_true",
                   help="9:16の縦型で出す（ショート用）")
    p.add_argument("--vertical-style", choices=["blur", "crop"], default="blur",
                   help="縦型の作り方。blur=ぼかし背景で全画面を残す / "
                        "crop=中央を切る (既定 %(default)s)")
    p.add_argument("--speed", type=float, default=1.0,
                   help="再生速度 (既定 %(default)s＝等倍)。ショート向けに 1.25 など。"
                        "声の高さは変わりません")
    p.add_argument("--encoder", choices=["auto", "cpu", "nvenc"], default="auto",
                   help="auto=GPUがあれば使う / cpu=CPUのみ / nvenc=GPUを強制 "
                        "(既定 %(default)s)")
    p.set_defaults(func=cmd_cut)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except ffmpeg.FFmpegMissing as exc:
        log(str(exc))
        return 2
    except KeyboardInterrupt:
        log("\n中断しました。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
