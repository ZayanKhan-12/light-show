"""Tests for tools/sequence_check.py.

The case that matters is test_a_sequence_with_no_marks_explains_the_dialog:
https://github.com/teslamotors/light-show/issues/66 is an owner who spent a
year updating graphics drivers because xLights titles that warning "Graphics
Driver Problem". The tool has to say plainly that the title is wrong and what
the real cause is.
"""

import io
import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import sequence_check as sc  # noqa: E402


MARK = '<Effect label="" startTime="{}" endTime="{}"/>'


def timing_track(name, marks=0):
    effects = "".join(MARK.format(i * 500, (i + 1) * 500) for i in range(marks))
    return ('<Element type="timing" name="{}"><EffectLayer>{}'
            "</EffectLayer></Element>".format(name, effects))


def build_xsq(timing="", frame="20 ms", duration="60.0", media="",
              sequence_type="Media", version="2024.11", models=1,
              root="xsequence"):
    model_elements = "".join(
        '<Element type="model" name="Model {}"><EffectLayer/></Element>'.format(i)
        for i in range(models))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<{root}>"
        "<head><version>{version}</version>"
        "<sequenceTiming>{frame}</sequenceTiming>"
        "<sequenceType>{sequence_type}</sequenceType>"
        "<mediaFile>{media}</mediaFile>"
        "<sequenceDuration>{duration}</sequenceDuration></head>"
        "<DisplayElements/>"
        "<ElementEffects>{models}{timing}</ElementEffects>"
        "</{root}>"
    ).format(root=root, version=version, frame=frame,
             sequence_type=sequence_type, media=media, duration=duration,
             models=model_elements, timing=timing)


class SequenceCheckTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def write(self, text, name="lightshow.xsq"):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def check(self, **kwargs):
        return sc.check_sequence(self.write(build_xsq(**kwargs)))

    def codes(self, sequence):
        return [f.code for f in sequence.findings]

    def find(self, sequence, code):
        return [f for f in sequence.findings if f.code == code]


class ReadingTests(SequenceCheckTestCase):
    def test_the_header_is_read(self):
        sequence = self.check(version="2023.20", frame="25 ms",
                              duration="110.263", media="C:/x/song.mp3")

        self.assertEqual(sequence.xlights_version, "2023.20")
        self.assertEqual(sequence.frame_ms, 25)
        self.assertAlmostEqual(sequence.duration_s, 110.263)
        self.assertEqual(sequence.media_file, "C:/x/song.mp3")

    def test_timing_tracks_and_marks_are_counted(self):
        sequence = self.check(
            timing=timing_track("Beats", 4) + timing_track("Bars", 2))

        self.assertEqual([t.name for t in sequence.timing_tracks],
                         ["Beats", "Bars"])
        self.assertEqual([t.marks for t in sequence.timing_tracks], [4, 2])
        self.assertEqual(sequence.total_marks, 6)

    def test_model_elements_are_counted_separately(self):
        sequence = self.check(models=5, timing=timing_track("Beats", 1))

        self.assertEqual(sequence.model_elements, 5)
        self.assertEqual(len(sequence.timing_tracks), 1)

    def test_a_file_that_is_not_a_sequence_is_rejected(self):
        path = self.write(build_xsq(root="notxsequence"))
        with self.assertRaises(sc.SequenceError) as caught:
            sc.read_sequence(path)
        self.assertIn("validator.py", str(caught.exception))

    def test_malformed_xml_is_rejected(self):
        path = self.write("<xsequence><head>")
        with self.assertRaises(sc.SequenceError):
            sc.read_sequence(path)

    def test_a_missing_file_is_rejected(self):
        with self.assertRaises(sc.SequenceError):
            sc.read_sequence(os.path.join(self.tmpdir, "nope.xsq"))


class TimingMarkTests(SequenceCheckTestCase):
    def test_a_sequence_with_no_marks_explains_the_dialog(self):
        """Issue 66. The title xLights uses is wrong and must be called out."""
        sequence = self.check()
        findings = self.find(sequence, "no-timing-marks")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sc.WARNING)
        # The exact words from the screenshot, so a search reaches this.
        self.assertIn(sc.PASTE_BY_CELL_DIALOG, findings[0].detail)
        self.assertIn("misleading", findings[0].detail)
        self.assertIn("Paste By Time", findings[0].detail)

    def test_a_timing_track_with_no_marks_is_still_no_marks(self):
        sequence = self.check(timing=timing_track("Empty", 0))
        self.assertIn("no-timing-marks", self.codes(sequence))

    def test_marks_clear_the_warning(self):
        sequence = self.check(timing=timing_track("Beats", 1))
        self.assertNotIn("no-timing-marks", self.codes(sequence))

    def test_an_empty_track_beside_a_full_one_is_a_note(self):
        sequence = self.check(
            timing=timing_track("Beats", 8) + timing_track("Spare", 0))
        findings = self.find(sequence, "empty-timing-track")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sc.INFO)
        self.assertIn("'Spare'", findings[0].detail)

    def test_all_tracks_populated_says_nothing(self):
        sequence = self.check(
            timing=timing_track("Beats", 8) + timing_track("Bars", 2))
        self.assertNotIn("empty-timing-track", self.codes(sequence))


class FrameIntervalTests(SequenceCheckTestCase):
    def good(self, **kwargs):
        kwargs.setdefault("timing", timing_track("Beats", 4))
        kwargs.setdefault("media", __file__)
        return self.check(**kwargs)

    def test_an_interval_below_the_minimum_is_an_error(self):
        findings = self.find(self.good(frame="10 ms"),
                             "frame-interval-unsupported")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sc.ERROR)

    def test_an_interval_above_the_maximum_is_an_error(self):
        self.assertTrue(self.find(self.good(frame="120 ms"),
                                  "frame-interval-unsupported"))

    def test_the_documented_bounds_are_accepted(self):
        for frame in ("15 ms", "100 ms"):
            self.assertEqual(
                self.find(self.good(frame=frame),
                          "frame-interval-unsupported"), [])

    def test_the_recommended_interval_is_silent(self):
        self.assertEqual(self.codes(self.good(frame="20 ms")), [])

    def test_another_supported_interval_is_only_a_note(self):
        findings = self.find(self.good(frame="25 ms"),
                             "frame-interval-not-recommended")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sc.INFO)

    def test_a_missing_interval_is_a_warning(self):
        findings = self.find(self.good(frame=""), "frame-interval-unknown")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sc.WARNING)


class DurationTests(SequenceCheckTestCase):
    def test_a_sequence_longer_than_four_hours_is_an_error(self):
        sequence = self.check(duration=str(sc.MAX_DURATION_S + 1),
                              timing=timing_track("Beats", 1))
        findings = self.find(sequence, "duration-too-long")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sc.ERROR)

    def test_exactly_four_hours_is_accepted(self):
        sequence = self.check(duration=str(sc.MAX_DURATION_S),
                              timing=timing_track("Beats", 1))
        self.assertNotIn("duration-too-long", self.codes(sequence))

    def test_an_unreadable_duration_is_ignored(self):
        sequence = self.check(duration="not a number",
                              timing=timing_track("Beats", 1))
        self.assertIsNone(sequence.duration_s)
        self.assertNotIn("duration-too-long", self.codes(sequence))


class MediaTests(SequenceCheckTestCase):
    def test_a_musical_sequence_with_no_audio_is_a_warning(self):
        sequence = self.check(media="", timing=timing_track("Beats", 1))
        findings = self.find(sequence, "no-media-file")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sc.WARNING)

    def test_an_animation_sequence_needs_no_audio(self):
        sequence = self.check(media="", sequence_type="Animation",
                              timing=timing_track("Beats", 1))
        self.assertNotIn("no-media-file", self.codes(sequence))

    def test_audio_from_another_machine_is_a_note(self):
        sequence = self.check(media="C:\\\\Users\\\\someone\\\\song.mp3",
                              timing=timing_track("Beats", 1))
        findings = self.find(sequence, "media-file-not-on-this-machine")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sc.INFO)

    def test_audio_present_on_this_machine_says_nothing(self):
        sequence = self.check(media=__file__, timing=timing_track("Beats", 1))
        self.assertEqual(self.codes(sequence), [])


class ReportingTests(SequenceCheckTestCase):
    def test_the_header_line_summarises_the_sequence(self):
        sequence = self.check(timing=timing_track("Beats", 4), models=3,
                              media=__file__)
        text = sc.render_report(sequence, verbose=False)

        self.assertIn("3 model element(s), 1 timing track(s), 4 mark(s)", text)
        self.assertIn("This sequence is in good shape.", text)

    def test_timing_tracks_are_listed_only_when_verbose(self):
        sequence = self.check(timing=timing_track("Beats", 4), media=__file__)

        self.assertNotIn("'Beats'", sc.render_report(sequence, False))
        self.assertIn("'Beats'", sc.render_report(sequence, True))

    def test_the_report_serialises_to_json(self):
        sequence = self.check(timing=timing_track("Beats", 4))
        payload = json.loads(json.dumps(sequence.as_dict()))

        self.assertEqual(payload["total_marks"], 4)
        self.assertEqual(payload["timing_tracks"][0]["name"], "Beats")


class ReadmeReferenceTests(unittest.TestCase):
    """Every section a finding cites has to exist."""

    def test_cited_sections_are_in_the_readme(self):
        with open(os.path.join(REPO_ROOT, "README.md"),
                  encoding="utf-8") as handle:
            readme = handle.read()
        cited = set()
        for builder in (
            lambda s: sc._check_timing_marks(s),
            lambda s: sc._check_frame_interval(s),
            lambda s: sc._check_duration(s),
            lambda s: sc._check_media(s),
        ):
            sequence = sc.Sequence_(path="x", sequence_type="Media",
                                    duration_s=sc.MAX_DURATION_S + 1)
            builder(sequence)
            cited |= {f.readme for f in sequence.findings if f.readme}
        self.assertTrue(cited)
        for section in sorted(cited):
            self.assertIn(section, readme)


class CommandLineTests(SequenceCheckTestCase):
    def run_main(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        original = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout, stderr
        try:
            code = sc.main(list(argv))
        finally:
            sys.stdout, sys.stderr = original
        return code, stdout.getvalue(), stderr.getvalue()

    def test_a_clean_sequence_exits_zero(self):
        path = self.write(build_xsq(timing=timing_track("Beats", 4),
                                    media=__file__))
        code, out, _ = self.run_main(path)

        self.assertEqual(code, 0)
        self.assertIn("good shape", out)

    def test_an_error_exits_one(self):
        path = self.write(build_xsq(frame="10 ms",
                                    timing=timing_track("Beats", 4)))
        self.assertEqual(self.run_main(path)[0], 1)

    def test_a_warning_only_fails_under_strict(self):
        path = self.write(build_xsq(media=__file__))   # no timing marks

        self.assertEqual(self.run_main(path)[0], 0)
        self.assertEqual(self.run_main(path, "--strict")[0], 1)

    def test_an_unreadable_file_exits_two(self):
        code, _, err = self.run_main(os.path.join(self.tmpdir, "nope.xsq"))

        self.assertEqual(code, 2)
        self.assertTrue(err.strip())

    def test_json_output_parses(self):
        path = self.write(build_xsq(timing=timing_track("Beats", 4)))
        code, out, _ = self.run_main(path, "--json")

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["total_marks"], 4)


class ShippedSequenceTests(unittest.TestCase):
    """The .xsq files this repository ships."""

    def sequences(self):
        examples = os.path.join(REPO_ROOT, "examples")
        for current, _, files in os.walk(examples):
            for name in sorted(files):
                if name.lower().endswith(".xsq"):
                    yield os.path.join(current, name)

    def test_every_shipped_sequence_parses(self):
        seen = 0
        for path in self.sequences():
            sequence = sc.check_sequence(path)
            seen += 1
            self.assertGreater(sequence.model_elements, 0, path)
            self.assertEqual(sequence.counts()[sc.ERROR], 0, path)
        self.assertGreater(seen, 0, "no .xsq files were found")

    def test_every_shipped_sequence_has_timing_marks(self):
        # If one did not, it would be an example of the issue 66 state.
        for path in self.sequences():
            sequence = sc.check_sequence(path)
            self.assertGreater(sequence.total_marks, 0, path)
            self.assertNotIn(
                "no-timing-marks",
                [f.code for f in sequence.findings], path)


if __name__ == "__main__":
    unittest.main()
