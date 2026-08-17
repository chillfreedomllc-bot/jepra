import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kirinuki import config


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)  # カレントの設定を拾わせないため

    def tearDown(self):
        os.chdir(self.cwd)


class TestResolveOutDir(ConfigTestCase):
    def test_explicit_wins(self):
        self.assertEqual(
            config.resolve_out_dir("/tmp/here", "/videos/a.mp4"), "/tmp/here")

    def test_defaults_next_to_the_video(self):
        result = config.resolve_out_dir("", "/videos/a.mp4", "kirinuki_out")
        self.assertEqual(result, os.path.join("/videos", "kirinuki_out"))

    def test_uses_configured_folder_with_a_per_video_subfolder(self):
        # 素材ごとに分けないと、次の動画のクリップと混ざる。
        config.save({"out_dir": os.path.join(self.dir, "切り抜き")}, base=self.dir)
        with open(os.path.join(self.dir, config.FILENAME), encoding="utf-8") as fh:
            self.assertIn("切り抜き", fh.read())
        os.chdir(self.dir)
        result = config.resolve_out_dir("", "/videos/実況_12.mp4")
        self.assertEqual(os.path.basename(result), "実況_12")
        self.assertEqual(os.path.basename(os.path.dirname(result)), "切り抜き")


class TestLoad(ConfigTestCase):
    def test_missing_file_is_empty(self):
        self.assertEqual(config.load(self.dir), {})

    def test_broken_file_does_not_raise(self):
        with open(os.path.join(self.dir, config.FILENAME), "w", encoding="utf-8") as fh:
            fh.write("{ this is not json")
        self.assertEqual(config.load(self.dir), {})

    def test_round_trip_keeps_japanese(self):
        config.save({"out_dir": "C:\\Users\\PC\\Videos\\ショート用切り抜き"}, base=self.dir)
        self.assertEqual(config.load(self.dir)["out_dir"],
                         "C:\\Users\\PC\\Videos\\ショート用切り抜き")

    def test_save_merges_instead_of_replacing(self):
        config.save({"out_dir": "/a"}, base=self.dir)
        config.save({"other": 1}, base=self.dir)
        loaded = config.load(self.dir)
        self.assertEqual(loaded["out_dir"], "/a")
        self.assertEqual(loaded["other"], 1)


if __name__ == "__main__":
    unittest.main()
