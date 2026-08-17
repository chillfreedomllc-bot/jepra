import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from kirinuki.analyze import (
    MIN_GAP_DB, profile_levels,
    Level, baseline_db, build_clips, find_moments, format_timestamp,
    levels_from_chunks, levels_from_pcm, parse_timestamp,
)


def pcm_from_db(segments, rate=16000):
    """(長さ秒, dBFS) の並びから 16bit PCM を作る。"""
    chunks = []
    for seconds, db in segments:
        amplitude = 32768 * (10 ** (db / 20.0)) * math.sqrt(2)
        t = np.arange(int(rate * seconds)) / rate
        wave = amplitude * np.sin(2 * math.pi * 440 * t)
        chunks.append(np.clip(wave, -32768, 32767).astype(np.int16))
    return np.concatenate(chunks).tobytes() if chunks else b""


class TestLevels(unittest.TestCase):
    def test_measures_level_close_to_input(self):
        levels = levels_from_pcm(pcm_from_db([(2.0, -20.0)]), window=0.5)
        self.assertEqual(len(levels), 4)
        for level in levels:
            self.assertAlmostEqual(level.db, -20.0, delta=1.0)

    def test_times_are_sequential(self):
        levels = levels_from_pcm(pcm_from_db([(1.5, -30.0)]), window=0.5)
        self.assertEqual([l.time for l in levels], [0.0, 0.5, 1.0])

    def test_empty_input(self):
        self.assertEqual(levels_from_pcm(b""), [])


class TestStreaming(unittest.TestCase):
    """逐次処理でも一括処理と同じ結果になること。

    長い素材ではメモリを抑えるため断片ごとに処理するが、窓の途中で切れた端数を
    正しく繰り越さないと、そこだけ音量がずれて誤検出の原因になる。
    """

    def setUp(self):
        self.pcm = pcm_from_db([(3.0, -20.0), (1.0, -6.0), (3.0, -20.0)])
        self.expected = levels_from_pcm(self.pcm)

    def split(self, size):
        return [self.pcm[i:i + size] for i in range(0, len(self.pcm), size)]

    def test_matches_whole_read_on_odd_boundaries(self):
        # 窓(0.5秒=8000サンプル=16000バイト)の倍数にならない刻みで割る。
        actual = levels_from_chunks(self.split(9973 * 2))
        self.assertEqual(len(actual), len(self.expected))
        for got, want in zip(actual, self.expected):
            self.assertAlmostEqual(got.db, want.db, places=4)
            self.assertAlmostEqual(got.time, want.time, places=6)

    def test_matches_on_tiny_chunks(self):
        actual = levels_from_chunks(self.split(1000))
        self.assertEqual([round(l.db, 4) for l in actual],
                         [round(l.db, 4) for l in self.expected])

    def test_no_chunks(self):
        self.assertEqual(levels_from_chunks([]), [])


class TestBaseline(unittest.TestCase):
    def test_ignores_silence(self):
        # 半分が無音でも、普段の音量は喋りの高さになるべき。
        levels = levels_from_pcm(pcm_from_db([(5.0, -80.0), (5.0, -20.0)]))
        self.assertAlmostEqual(baseline_db(levels), -20.0, delta=1.5)

    def test_all_silent_does_not_crash(self):
        levels = levels_from_pcm(pcm_from_db([(2.0, -80.0)]))
        self.assertLess(baseline_db(levels), -50.0)


class TestProfile(unittest.TestCase):
    def test_speech_level_ignores_long_silence(self):
        # 静かな時間が長くても「普段の高さ」は喋りの高さであるべき。
        levels = levels_from_pcm(pcm_from_db([(30.0, -60.0), (30.0, -20.0)]))
        self.assertAlmostEqual(profile_levels(levels).speech_db, -20.0, delta=2.0)

    def test_flat_source_uses_the_minimum_gap(self):
        # 音量が一定なら広がりが0になる。境目が普段の高さに張り付くと
        # 全部が「反応」になってしまうので、最低限の差を空ける。
        levels = levels_from_pcm(pcm_from_db([(30.0, -20.0)]))
        profile = profile_levels(levels)
        self.assertAlmostEqual(profile.cut_db - profile.speech_db, MIN_GAP_DB, delta=0.5)

    def test_quiet_heavy_source_stays_reachable(self):
        # 無音が多い素材で四分位範囲を使うと境目が跳ね上がり、到達不能になる。
        # 上半分の広がりで測ることで、実際に鳴っている音より上に行かないこと。
        levels = levels_from_pcm(
            pcm_from_db([(10.0, -20.0), (20.0, -60.0), (2.0, -6.0)]))
        profile = profile_levels(levels)
        self.assertLess(profile.cut_db, -6.0)

    def test_threshold_overrides_the_automatic_cut(self):
        levels = levels_from_pcm(pcm_from_db([(30.0, -20.0)]))
        profile = profile_levels(levels, threshold_db=20.0)
        self.assertAlmostEqual(profile.cut_db - profile.speech_db, 20.0, delta=0.5)

    def test_higher_sensitivity_raises_the_cut(self):
        levels = levels_from_pcm(
            pcm_from_db([(10.0, -40.0), (10.0, -30.0), (10.0, -22.0)]))
        loose = profile_levels(levels, sensitivity=1.0).cut_db
        strict = profile_levels(levels, sensitivity=3.0).cut_db
        self.assertGreater(strict, loose)

    def test_empty_levels(self):
        profile = profile_levels([])
        self.assertEqual(profile.speech_db, profile.cut_db)


class TestFindMoments(unittest.TestCase):
    def test_finds_the_loud_part(self):
        # 喋り10秒 → 静寂3秒 → 悲鳴2秒 → 喋り10秒
        pcm = pcm_from_db([(10.0, -20.0), (3.0, -50.0), (2.0, -6.0), (10.0, -20.0)])
        moments = find_moments(levels_from_pcm(pcm))
        self.assertEqual(len(moments), 1)
        self.assertAlmostEqual(moments[0].start, 13.0, delta=0.6)
        self.assertGreater(moments[0].excess_db, 10.0)

    def test_steady_speech_produces_nothing(self):
        # ずっと同じ音量なら「跳ね上がり」は存在しない。
        moments = find_moments(levels_from_pcm(pcm_from_db([(30.0, -20.0)])))
        self.assertEqual(moments, [])

    def test_quiet_before_is_recorded(self):
        pcm = pcm_from_db([(10.0, -20.0), (5.0, -55.0), (2.0, -6.0)])
        moment = find_moments(levels_from_pcm(pcm))[0]
        self.assertLess(moment.quiet_before_db, -40.0)

    def test_contrast_raises_the_score(self):
        loud = (2.0, -6.0)
        with_silence = find_moments(levels_from_pcm(
            pcm_from_db([(10.0, -20.0), (5.0, -55.0), loud, (5.0, -20.0)])))
        without = find_moments(levels_from_pcm(
            pcm_from_db([(15.0, -20.0), loud, (5.0, -20.0)])))
        self.assertTrue(with_silence and without)
        # 同じ音量の悲鳴でも、直前が静かなほうが切り抜きとして強い。
        self.assertGreater(with_silence[0].score, without[0].score)

    def test_nearby_spikes_merge(self):
        pcm = pcm_from_db([
            (10.0, -20.0), (1.5, -6.0), (1.0, -20.0), (1.5, -6.0), (5.0, -20.0)])
        self.assertEqual(len(find_moments(levels_from_pcm(pcm), merge_gap=2.0)), 1)

    def test_distant_spikes_stay_separate(self):
        pcm = pcm_from_db([
            (10.0, -20.0), (1.5, -6.0), (10.0, -20.0), (1.5, -6.0), (5.0, -20.0)])
        self.assertEqual(len(find_moments(levels_from_pcm(pcm), merge_gap=2.0)), 2)

    def test_threshold_controls_sensitivity(self):
        pcm = pcm_from_db([(10.0, -20.0), (2.0, -14.0), (10.0, -20.0)])
        self.assertEqual(find_moments(levels_from_pcm(pcm), threshold_db=8.0), [])
        self.assertEqual(len(find_moments(levels_from_pcm(pcm), threshold_db=4.0)), 1)


class TestBuildClips(unittest.TestCase):
    def moment(self, start, end, score=20.0):
        from kirinuki.analyze import Moment
        return Moment(start=start, end=end, peak_db=-6.0, excess_db=14.0,
                      quiet_before_db=-50.0, attack_db=17.0, score=score)

    def test_adds_pre_roll_and_post_roll(self):
        clip = build_clips([self.moment(60.0, 62.0)], pre_roll=8.0, post_roll=3.0)[0]
        self.assertAlmostEqual(clip.start, 52.0)
        self.assertAlmostEqual(clip.end, 65.0)

    def test_does_not_go_before_zero(self):
        clip = build_clips([self.moment(2.0, 3.0)], pre_roll=8.0)[0]
        self.assertEqual(clip.start, 0.0)

    def test_respects_source_duration(self):
        clip = build_clips([self.moment(95.0, 97.0)], duration=100.0, post_roll=10.0)[0]
        self.assertEqual(clip.end, 100.0)

    def test_overlapping_clips_merge(self):
        # 5秒差の2つの反応。前フリ8秒だと範囲が重なるので1本にする。
        clips = build_clips([self.moment(60.0, 61.0), self.moment(66.0, 67.0)])
        self.assertEqual(len(clips), 1)
        self.assertEqual(len(clips[0].moments), 2)

    def test_far_apart_clips_stay_separate(self):
        clips = build_clips([self.moment(10.0, 11.0), self.moment(120.0, 121.0)])
        self.assertEqual(len(clips), 2)

    def test_long_merged_clip_is_trimmed(self):
        moments = [self.moment(t, t + 1.0) for t in range(30, 200, 6)]
        for clip in build_clips(moments, max_length=55.0):
            self.assertLessEqual(clip.duration, 55.0 + 0.01)

    def test_sorted_by_score(self):
        clips = build_clips([self.moment(10.0, 11.0, score=5.0),
                             self.moment(120.0, 121.0, score=40.0)])
        self.assertEqual(clips[0].score, 40.0)


class TestTimestamps(unittest.TestCase):
    def test_format(self):
        self.assertEqual(format_timestamp(0), "0:00:00.0")
        self.assertEqual(format_timestamp(3725.5), "1:02:05.5")

    def test_round_trip(self):
        self.assertAlmostEqual(parse_timestamp(format_timestamp(3725.5)), 3725.5, places=1)

    def test_parses_short_form(self):
        self.assertAlmostEqual(parse_timestamp("1:23"), 83.0)

    def test_negative_is_clamped(self):
        self.assertEqual(format_timestamp(-5), "0:00:00.0")


if __name__ == "__main__":
    unittest.main()


class TestScreamVsLoudTalking(unittest.TestCase):
    """「悲鳴」と「ただの大声」の扱い。

    実素材で外れた候補は全て「喋ってはいるが大声なだけ」だった。一度これを
    立ち上がりの速さで分ける形に組み替えたが、実素材の成績が落ちたため
    （10本中7本使える → 5本）スコアからは外した。attack_db は記録だけ残して
    あるので、ここでは「記録できていること」と「現状どこまで分けられるか」を
    確かめる。
    """

    def scream(self):
        # 喋り → 一瞬静か → いきなり大音量 → 戻る
        return pcm_from_db([(60.0, -23.0), (1.0, -30.0), (1.5, -6.0), (40.0, -23.0)])

    def loud_talking(self):
        # 喋り → じわじわ上がる → 大きいまま続く → 戻る
        return pcm_from_db([
            (60.0, -23.0), (1.5, -19.0), (1.5, -14.0), (1.5, -10.0),
            (7.0, -8.0), (30.0, -23.0),
        ])

    def top_score(self, pcm):
        moments = find_moments(levels_from_pcm(pcm))
        self.assertTrue(moments, "反応が検出されていない")
        return max(m.score for m in moments)

    def test_both_are_detected(self):
        # どちらも「普段より大きい」ので検出自体はされる。問題は順位。
        self.assertTrue(find_moments(levels_from_pcm(self.scream())))
        self.assertTrue(find_moments(levels_from_pcm(self.loud_talking())))

    def test_scream_outranks_loud_talking(self):
        self.assertGreater(self.top_score(self.scream()),
                           self.top_score(self.loud_talking()))

    def test_attack_is_larger_for_the_scream(self):
        scream = max(find_moments(levels_from_pcm(self.scream())),
                     key=lambda m: m.score)
        talking = max(find_moments(levels_from_pcm(self.loud_talking())),
                      key=lambda m: m.score)
        self.assertGreater(scream.attack_db, talking.attack_db)

    def test_sustained_loudness_is_not_penalised(self):
        """長く続く大音量に減点はしない。これは既知の弱点。

        「3秒を超えたら減点」を試したが、実素材で成績が落ちたので戻した。
        そのため喋りっぱなしで大きい区間も候補に残る。音だけでは切り分け
        きれていない部分で、直すにはマイクを別トラックで録る必要がある。
        """
        short = pcm_from_db([(60.0, -23.0), (1.0, -30.0), (1.5, -6.0), (40.0, -23.0)])
        long = pcm_from_db([(60.0, -23.0), (1.0, -30.0), (9.0, -6.0), (40.0, -23.0)])
        self.assertGreaterEqual(self.top_score(long), self.top_score(short))
