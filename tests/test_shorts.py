import unittest

from clipper.shorts import _BLUR_FILTER, _CROP_FILTER, build_command


class TestBuildCommand(unittest.TestCase):
    def test_crop_mode(self):
        cmd = build_command("ffmpeg", "in.mp4", "out.mp4", "crop")
        self.assertIn("-vf", cmd)
        self.assertIn(_CROP_FILTER, cmd)
        self.assertIn("out.mp4", cmd)

    def test_blur_mode(self):
        cmd = build_command("ffmpeg", "in.mp4", "out.mp4", "blur")
        self.assertIn("-filter_complex", cmd)
        self.assertIn(_BLUR_FILTER, cmd)
        self.assertIn("-map", cmd)

    def test_audio_is_copied_not_reencoded(self):
        for mode in ("blur", "crop"):
            cmd = build_command("ffmpeg", "in.mp4", "out.mp4", mode)
            self.assertIn("copy", cmd)

    def test_vertical_geometry(self):
        # both modes must end at 1080x1920
        self.assertIn("1080:1920", _CROP_FILTER)
        self.assertIn("1080:1920", _BLUR_FILTER)
        self.assertIn("crop=1080:1920", _BLUR_FILTER)

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            build_command("ffmpeg", "in.mp4", "out.mp4", "widescreen")


if __name__ == "__main__":
    unittest.main()
