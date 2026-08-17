import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from kirinuki.analyze import (
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
                      quiet_before_db=-50.0, score=score)

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
