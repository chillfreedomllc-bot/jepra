"""合成動画を実際に通して、検出と切り出しが噛み合うかを見る。

単体テストは各部品の正しさしか見ない。ここでは ffmpeg を通した実ファイルで、
「悲鳴を置いた位置が候補として出るか」を端から端まで確認する。
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import make_fixture
from kirinuki import ffmpeg
from kirinuki.analyze import build_clips, find_moments, levels_from_pcm
from kirinuki.extract import cut_clips, safe_stem

FIXTURE = os.path.join(tempfile.gettempdir(), "kirinuki_fixture.mp4")


def setUpModule():
    make_fixture.build(FIXTURE)


class TestDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        levels = levels_from_pcm(ffmpeg.read_pcm(FIXTURE))
        cls.moments = find_moments(levels)
        cls.clips = build_clips(cls.moments, duration=make_fixture.DURATION)

    def test_finds_every_scream(self):
        self.assertEqual(len(self.moments), len(make_fixture.SCREAM_TIMES))

    def test_no_false_positives_on_normal_speech(self):
        # 喋り続けている場面を拾ってしまうと、候補が使い物にならなくなる。
        self.assertEqual(len(self.clips), len(make_fixture.SCREAM_TIMES))

    def test_each_scream_lands_inside_a_clip(self):
        for expected in make_fixture.SCREAM_TIMES:
            covered = any(c.start <= expected <= c.end for c in self.clips)
            self.assertTrue(covered, "{}秒の悲鳴がどの候補にも入っていない".format(expected))

    def test_clip_starts_before_the_scream(self):
        # ホラーは「タメ」が要る。悲鳴の瞬間から始まる切り抜きは成立しない。
        for clip in self.clips:
            first = min(m.start for m in clip.moments)
            self.assertLess(clip.start, first)

    def test_clips_fit_in_a_short(self):
        for clip in self.clips:
            self.assertLessEqual(clip.duration, 55.0)


class TestExtraction(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        levels = levels_from_pcm(ffmpeg.read_pcm(FIXTURE))
        self.clips = build_clips(find_moments(levels), duration=make_fixture.DURATION)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_writes_playable_files(self):
        results = cut_clips(FIXTURE, self.clips[:2], self.dir)
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertTrue(result.ok, result.error)
            self.assertTrue(os.path.exists(result.path))
            self.assertGreater(os.path.getsize(result.path), 1000)

    def test_output_duration_matches_the_clip(self):
        result = cut_clips(FIXTURE, self.clips[:1], self.dir)[0]
        actual = ffmpeg.probe_duration(result.path)
        self.assertAlmostEqual(actual, self.clips[0].duration, delta=0.5)

    def test_vertical_output_is_nine_by_sixteen(self):
        result = cut_clips(FIXTURE, self.clips[:1], self.dir, vertical=True)[0]
        self.assertTrue(result.ok, result.error)
        probe = ffmpeg.run(["-i", result.path])
        text = probe.stderr.decode("utf-8", "replace")
        self.assertIn("1080x1920", text)

    def test_filenames_are_numbered(self):
        results = cut_clips(FIXTURE, self.clips[:2], self.dir, prefix="test")
        names = sorted(os.path.basename(r.path) for r in results)
        self.assertEqual(names, ["test_01.mp4", "test_02.mp4"])


class TestSafeStem(unittest.TestCase):
    def test_strips_path_unsafe_characters(self):
        self.assertEqual(safe_stem("実況 第12回/裏面?"), "実況_第12回_裏面")

    def test_keeps_japanese(self):
        self.assertEqual(safe_stem("ホラゲー実況"), "ホラゲー実況")

    def test_falls_back_when_empty(self):
        self.assertEqual(safe_stem("///"), "clip")


class TestEncoderSelection(unittest.TestCase):
    def test_cpu_is_always_available(self):
        self.assertEqual(ffmpeg.pick_encoder("cpu"), "libx264")

    def test_auto_returns_a_known_encoder(self):
        self.assertIn(ffmpeg.pick_encoder("auto"), ("libx264", "h264_nvenc"))



class TestSpeed(unittest.TestCase):
    """再生速度を変えたときに、出力の長さが正しく縮むこと。

    -t を -i の後ろに置くと「出力の長さ」の指定になり、速度を上げたぶん
    元素材を余計に読んでしまう（1.25倍で13秒の出力を作るのに16.25秒読む）。
    見た目には気づきにくく、切り抜きの終端が想定より先まで入る。
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        levels = levels_from_pcm(ffmpeg.read_pcm(FIXTURE))
        self.clips = build_clips(find_moments(levels), duration=make_fixture.DURATION)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def cut_at(self, speed):
        result = cut_clips(FIXTURE, self.clips[:1], self.dir, speed=speed)[0]
        self.assertTrue(result.ok, result.error)
        return ffmpeg.probe_duration(result.path)

    def test_normal_speed_matches_the_clip(self):
        self.assertAlmostEqual(self.cut_at(1.0), self.clips[0].duration, delta=0.5)

    def test_faster_speed_shortens_the_output(self):
        expected = self.clips[0].duration / 1.25
        self.assertAlmostEqual(self.cut_at(1.25), expected, delta=0.5)

    def test_slower_speed_lengthens_the_output(self):
        expected = self.clips[0].duration / 0.8
        self.assertAlmostEqual(self.cut_at(0.8), expected, delta=0.5)


class TestSpeedFilters(unittest.TestCase):
    def test_normal_speed_adds_nothing(self):
        from kirinuki.extract import _speed_filters
        self.assertEqual(_speed_filters(1.0), ("", ""))

    def test_audio_uses_atempo_to_keep_the_pitch(self):
        from kirinuki.extract import _speed_filters
        _, audio = _speed_filters(1.25)
        self.assertIn("atempo", audio)

    def test_large_factors_are_chained(self):
        # atempo は 0.5〜2.0 しか受け付けないので、超える場合は連鎖が要る。
        from kirinuki.extract import _speed_filters
        _, audio = _speed_filters(3.0)
        self.assertEqual(audio.count("atempo"), 2)

if __name__ == "__main__":
    unittest.main()
