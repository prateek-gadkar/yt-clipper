import unittest

from clipper.shorts import _BLUR_VF, _CROP_VF, ShortsError, build_command


class TestBuildCommand(unittest.TestCase):
    def test_crop_mode(self):
        cmd = build_command("ffmpeg", "in.mp4", "out.mp4", "crop")
        self.assertIn("-vf", cmd)
        self.assertIn(_CROP_VF, cmd)
        self.assertIn("out.mp4", cmd)

    def test_blur_mode(self):
        cmd = build_command("ffmpeg", "in.mp4", "out.mp4", "blur")
        self.assertIn("-vf", cmd)
        self.assertIn(_BLUR_VF, cmd)
        # single filter graph -> the one video output is picked automatically;
        # no -filter_complex so -map can't accidentally drop the video stream
        self.assertNotIn("-filter_complex", cmd)

    def test_audio_is_copied_not_reencoded(self):
        for mode in ("blur", "crop"):
            cmd = build_command("ffmpeg", "in.mp4", "out.mp4", mode)
            self.assertIn("copy", cmd)
            self.assertIn("-c:a", cmd)

    def test_vertical_geometry(self):
        self.assertIn("1080:1920", _CROP_VF)
        self.assertIn("1080:1920", _BLUR_VF)
        self.assertIn("crop=1080:1920", _BLUR_VF)

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            build_command("ffmpeg", "in.mp4", "out.mp4", "widescreen")

    def test_shorts_error_is_descriptive(self):
        self.assertTrue(issubclass(ShortsError, RuntimeError))


if __name__ == "__main__":
    unittest.main()
