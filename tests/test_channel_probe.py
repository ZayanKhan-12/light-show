"""Tests for tools/channel_probe.py.

https://github.com/teslamotors/light-show/issues/72 reports that Inner and
Outer Main Beam are swapped on one build. Nothing here decides whether that is
true -- the point of the tool is to let the owner of that car show what their
channels do. What the tests hold is that the show it builds is playable, that
the printed schedule matches the file, and that closures are not spent by
accident.
"""

import io
import json
import os
import struct
import sys
import tempfile
import unittest
import wave

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import channel_probe as cp  # noqa: E402


def ONE(*channels):
    """One turn per channel, the shape build_probe() takes."""
    return [(c,) for c in channels]
import validator  # noqa: E402
import vehicle_preview as vp  # noqa: E402


class ParseChannelsTests(unittest.TestCase):
    def test_a_plain_list(self):
        self.assertEqual(cp.parse_channels("1,2,3"), [(1,), (2,), (3,)])

    def test_a_range(self):
        self.assertEqual(cp.parse_channels("1-4"), [(1,), (2,), (3,), (4,)])

    def test_ranges_and_singles_together(self):
        self.assertEqual(cp.parse_channels("1, 3-5 ,9"),
                         [(1,), (3,), (4,), (5,), (9,)])

    def test_a_backwards_range_is_rejected(self):
        with self.assertRaises(cp.ProbeError):
            cp.parse_channels("9-3")

    def test_nonsense_is_rejected(self):
        with self.assertRaises(cp.ProbeError):
            cp.parse_channels("left headlight")


class CombinedStepTests(unittest.TestCase):
    """Issue 76: comparing two channels that may be one lamp.

    A Model X owner reports Front Turn and Aux Park as the same light --
    orange from one, white from the other, a dimmer mix from both. Answering
    that needs a turn that drives both at once.
    """

    def test_a_plus_makes_one_turn_of_several_channels(self):
        self.assertEqual(cp.parse_channels("13+17"), [(13, 17)])

    def test_singles_and_combinations_mix(self):
        self.assertEqual(cp.parse_channels("13,17,13+17"),
                         [(13,), (17,), (13, 17)])

    def test_nonsense_inside_a_combination_is_rejected(self):
        with self.assertRaises(cp.ProbeError):
            cp.parse_channels("13+left")

    def test_the_combined_turn_drives_every_channel_in_it(self):
        probe = cp.build_probe([(13,), (17,), (13, 17)], on_ms=200,
                               gap_ms=200, step_ms=20)
        raw = cp.render_fseq(probe)
        show = vp.Show(probe.channel_count, probe.frame_count, probe.step_ms,
                       raw[cp.HEADER_BYTES:])

        frame = probe.steps[2].start_ms // probe.step_ms
        lit = [c for c in range(1, probe.channel_count + 1)
               if show.series(c)[frame]]
        self.assertEqual(lit, [13, 17])

    def test_the_single_turns_stay_single(self):
        probe = cp.build_probe([(13,), (17,), (13, 17)], on_ms=200,
                               gap_ms=200, step_ms=20)
        raw = cp.render_fseq(probe)
        show = vp.Show(probe.channel_count, probe.frame_count, probe.step_ms,
                       raw[cp.HEADER_BYTES:])

        for index, expected in enumerate([[13], [17]]):
            frame = probe.steps[index].start_ms // probe.step_ms
            lit = [c for c in range(1, probe.channel_count + 1)
                   if show.series(c)[frame]]
            self.assertEqual(lit, expected)

    def test_a_combined_turn_is_named_after_both_channels(self):
        probe = cp.build_probe([(13, 17)])
        self.assertEqual(probe.steps[0].name,
                         "Left Front Turn + Left Aux Park")

    def test_the_named_group_covers_both_sides(self):
        chosen = cp.resolve_channels("front-turn-aux-park", None, False)
        self.assertEqual(chosen, [(13,), (17,), (14,), (18,)])

    def test_a_combination_including_a_closure_needs_the_flag(self):
        # The whole turn is dropped, and dropping every turn is an error.
        with self.assertRaises(cp.ProbeError):
            cp.resolve_channels(None, "1+41", False)
        self.assertEqual(cp.resolve_channels(None, "1+41", True), [(1, 41)])


class ChannelSelectionTests(unittest.TestCase):
    def test_the_default_group_is_the_beams_in_question(self):
        # Issue 72 is about Inner and Outer Main Beam.
        self.assertEqual(cp.resolve_channels(None, None, False),
                         [(1,), (2,), (3,), (4,)])
        for channel in cp.GROUPS["headlights"]:
            self.assertIn("Main Beam", vp.channel_name(channel))

    def test_closures_are_left_out_unless_asked_for(self):
        chosen = cp.resolve_channels(None, "1,2,41,46", False)

        self.assertEqual(chosen, [(1,), (2,)])
        self.assertNotIn((41,), chosen)

    def test_closures_are_included_on_request(self):
        self.assertEqual(cp.resolve_channels(None, "1,41", True),
                         [(1,), (41,)])

    def test_the_closures_group_works_without_the_flag(self):
        chosen = cp.resolve_channels("closures", None, False)

        self.assertTrue(chosen)
        for step in chosen:
            for channel in step:
                self.assertEqual(vp.CHANNELS[channel][1], vp.CLOSURE)

    def test_selecting_only_closures_without_the_flag_explains_itself(self):
        with self.assertRaises(cp.ProbeError) as caught:
            cp.resolve_channels(None, "41,46", False)
        self.assertIn("--include-closures", str(caught.exception))

    def test_the_order_given_is_kept_and_duplicates_dropped(self):
        self.assertEqual(cp.resolve_channels(None, "3,1,3,2", False),
                         [(3,), (1,), (2,)])

    def test_every_named_group_resolves(self):
        for name in cp.GROUPS:
            self.assertTrue(cp.resolve_channels(name, None, True), name)


class ScheduleTests(unittest.TestCase):
    def test_channels_take_turns_with_a_gap_between(self):
        probe = cp.build_probe(ONE(1, 2), on_ms=3000, gap_ms=1000, step_ms=20)

        self.assertEqual([(s.start_ms, s.end_ms) for s in probe.steps],
                         [(1000, 4000), (5000, 8000)])

    def test_the_show_is_long_enough_for_the_last_channel(self):
        probe = cp.build_probe(ONE(1, 2), on_ms=3000, gap_ms=1000, step_ms=20)

        self.assertGreaterEqual(probe.duration_ms, probe.steps[-1].end_ms)
        self.assertEqual(probe.frame_count, 9000 // 20)

    def test_each_step_carries_the_channel_name(self):
        probe = cp.build_probe(ONE(1))
        self.assertEqual(probe.steps[0].name, vp.channel_name(1))

    def test_an_unsupported_frame_interval_is_rejected(self):
        for step_ms in (10, 120):
            with self.assertRaises(cp.ProbeError):
                cp.build_probe(ONE(1), step_ms=step_ms)

    def test_a_channel_shorter_than_a_frame_is_rejected(self):
        with self.assertRaises(cp.ProbeError):
            cp.build_probe(ONE(1), on_ms=10, step_ms=20)

    def test_a_channel_outside_the_layout_is_rejected(self):
        with self.assertRaises(cp.ProbeError) as caught:
            cp.build_probe(ONE(201), channel_count=200)
        self.assertIn("201", str(caught.exception))

    def test_a_48_channel_layout_rejects_the_higher_channels(self):
        with self.assertRaises(cp.ProbeError):
            cp.build_probe(ONE(100), channel_count=48)

    def test_an_unsupported_layout_is_explained_by_the_validator(self):
        with self.assertRaises(cp.ProbeError) as caught:
            cp.build_probe(ONE(1), channel_count=64)
        self.assertIn(validator.VEHICLE_ERROR, str(caught.exception))

    def test_a_probe_longer_than_four_hours_is_rejected(self):
        with self.assertRaises(cp.ProbeError) as caught:
            cp.build_probe(ONE(1), on_ms=5 * 60 * 60 * 1000)
        self.assertIn("4 hours", str(caught.exception))


class FseqTests(unittest.TestCase):
    def probe_bytes(self, channels, **kwargs):
        probe = cp.build_probe(channels, **kwargs)
        return probe, cp.render_fseq(probe)

    def test_the_file_passes_the_repository_validator(self):
        _, raw = self.probe_bytes(ONE(1, 2, 3, 4))
        results = validator.validate(io.BytesIO(raw))

        self.assertGreater(results.frame_count, 0)
        self.assertEqual(results.step_time, cp.DEFAULT_STEP_MS)

    def test_the_header_says_what_it_should(self):
        probe, raw = self.probe_bytes(ONE(1), channel_count=200)
        channels, frames, step = struct.unpack("<IIB", raw[10:19])

        self.assertEqual(raw[0:4], b"PSEQ")
        self.assertEqual((channels, frames, step),
                         (200, probe.frame_count, probe.step_ms))
        self.assertEqual(raw[20], 0)              # uncompressed
        self.assertEqual(len(raw), cp.HEADER_BYTES + 200 * probe.frame_count)

    def test_only_the_scheduled_channel_is_lit(self):
        probe, raw = self.probe_bytes(ONE(1, 2), on_ms=200, gap_ms=200,
                                      step_ms=20)
        show = vp.Show(probe.channel_count, probe.frame_count, probe.step_ms,
                       raw[cp.HEADER_BYTES:])

        for step in probe.steps:
            frame = step.start_ms // probe.step_ms
            lit = [c for c in range(1, probe.channel_count + 1)
                   if show.series(c)[frame]]
            self.assertEqual(lit, list(step.channels))

    def test_everything_is_dark_in_the_gaps(self):
        probe, raw = self.probe_bytes(ONE(1), on_ms=200, gap_ms=200, step_ms=20)
        show = vp.Show(probe.channel_count, probe.frame_count, probe.step_ms,
                       raw[cp.HEADER_BYTES:])

        self.assertEqual(sum(show.series(1)[:probe.steps[0].start_ms // 20]), 0)

    def test_lights_are_driven_fully_on(self):
        probe, raw = self.probe_bytes(ONE(1))
        show = vp.Show(probe.channel_count, probe.frame_count, probe.step_ms,
                       raw[cp.HEADER_BYTES:])
        self.assertEqual(max(show.series(1)), cp.ON_VALUE)

    def test_a_closure_is_sent_open_not_full_brightness(self):
        # README.md: 25% is Open; 100% on a closure is Stop.
        probe, raw = self.probe_bytes(ONE(41))
        show = vp.Show(probe.channel_count, probe.frame_count, probe.step_ms,
                       raw[cp.HEADER_BYTES:])
        value = max(show.series(41))

        self.assertEqual(value, cp.CLOSURE_OPEN_VALUE)
        self.assertEqual(vp.CLOSURE_CODES[vp.to_percent(value)], "Open")

    def test_the_probe_spends_one_command_per_closure(self):
        probe, raw = self.probe_bytes(ONE(41, 46))
        show = vp.Show(probe.channel_count, probe.frame_count, probe.step_ms,
                       raw[cp.HEADER_BYTES:])

        for entry in vp.closure_usage(show):
            self.assertLessEqual(entry.count, 1, entry.channel)
        self.assertEqual(vp.analyze_closures(show), [])


class WavTests(unittest.TestCase):
    def test_the_audio_matches_the_show(self):
        probe = cp.build_probe(ONE(1, 2))
        raw = cp.render_wav(probe)
        with wave.open(io.BytesIO(raw)) as handle:
            # README.md, "Audio file requirements": 44.1 kHz.
            self.assertEqual(handle.getframerate(), cp.SAMPLE_RATE)
            self.assertEqual(handle.getnchannels(), 1)
            seconds = handle.getnframes() / float(handle.getframerate())
        self.assertAlmostEqual(seconds, probe.duration_ms / 1000.0, places=2)

    def test_a_tone_marks_each_channel(self):
        probe = cp.build_probe(ONE(1, 2), on_ms=1000, gap_ms=1000)
        with wave.open(io.BytesIO(cp.render_wav(probe))) as handle:
            frames = handle.readframes(handle.getnframes())

        def loudest(at_ms):
            start = int(cp.SAMPLE_RATE * at_ms / 1000.0) * 2
            window = frames[start:start + 2000]
            return max(abs(struct.unpack_from("<h", window, i)[0])
                       for i in range(0, len(window) - 1, 2))

        for step in probe.steps:
            self.assertGreater(loudest(step.start_ms), 1000)
        # Halfway through a gap there is nothing.
        self.assertEqual(loudest(probe.steps[0].end_ms + 400), 0)


class WriteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def test_both_files_are_written_and_named_together(self):
        probe = cp.build_probe(ONE(1, 2))
        fseq_path, wav_path = cp.write_probe(
            probe, os.path.join(self.tmpdir, "probe"))

        self.assertTrue(os.path.exists(fseq_path))
        self.assertTrue(os.path.exists(wav_path))
        self.assertEqual(os.path.splitext(fseq_path)[0],
                         os.path.splitext(wav_path)[0])

    def test_an_fseq_suffix_on_the_output_name_is_not_doubled(self):
        probe = cp.build_probe(ONE(1))
        fseq_path, _ = cp.write_probe(
            probe, os.path.join(self.tmpdir, "probe.fseq"))
        self.assertTrue(fseq_path.endswith("probe.fseq"))

    def test_the_written_pair_is_a_show_the_drive_check_accepts(self):
        import usb_check

        folder = os.path.join(self.tmpdir, "LightShow")
        os.makedirs(folder)
        cp.write_probe(cp.build_probe(ONE(1, 2)), os.path.join(folder, "probe"))
        report = usb_check.check_drive(self.tmpdir)

        self.assertEqual([s.name for s in report.playable_shows], ["probe"])
        self.assertEqual(report.counts()[usb_check.ERROR], 0)


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def run_main(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        original = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout, stderr
        try:
            code = cp.main(list(argv))
        finally:
            sys.stdout, sys.stderr = original
        return code, stdout.getvalue(), stderr.getvalue()

    def out(self, name="probe"):
        return os.path.join(self.tmpdir, name)

    def test_the_default_run_writes_a_headlight_probe(self):
        code, out, _ = self.run_main(self.out())

        self.assertEqual(code, 0)
        self.assertIn("Left Outer Main Beam", out)
        self.assertIn("Right Inner Main Beam", out)

    def test_the_schedule_is_printed_with_timestamps(self):
        _, out, _ = self.run_main(self.out(), "--channels", "1",
                                  "--on-ms", "2000", "--gap-ms", "1000")
        self.assertIn("0:01.000 - 0:03.000", out)

    def test_json_output_parses_and_names_the_files(self):
        code, out, _ = self.run_main(self.out(), "--json")
        payload = json.loads(out)

        self.assertEqual(code, 0)
        self.assertEqual(len(payload["steps"]), 4)
        self.assertTrue(payload["fseq"].endswith(".fseq"))
        self.assertTrue(payload["wav"].endswith(".wav"))

    def test_a_bad_request_exits_two(self):
        code, _, err = self.run_main(self.out(), "--channels", "999")

        self.assertEqual(code, 2)
        self.assertIn("999", err)

    def test_closures_are_reported_as_left_open(self):
        _, out, _ = self.run_main(self.out(), "--channels", "41",
                                  "--include-closures")
        self.assertIn("left open", out)


if __name__ == "__main__":
    unittest.main()
