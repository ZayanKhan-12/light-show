"""Tests for tools/multi_car_check.py.

https://github.com/teslamotors/light-show/issues/64 asks for animation that
runs across several cars. The rule that matters is in
test_different_frame_intervals_are_not_a_problem: the cars are kept together
by the length of their shows, not by their frame rate, and a check that got
that wrong would reject the five-car show this repository ships.
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
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import multi_car_check as mc  # noqa: E402


HEADER_BYTES = 32


def build_fseq_bytes(frames=100, channel_count=48, step_time=20,
                     magic=b"PSEQ", compression=0, major=2, minor=0):
    header = bytearray(HEADER_BYTES)
    header[0:4] = magic
    struct.pack_into("<H", header, 4, HEADER_BYTES)
    header[6] = minor
    header[7] = major
    struct.pack_into("<IIB", header, 10, channel_count, frames, step_time)
    header[20] = compression
    return bytes(header) + bytes(channel_count * frames)


def write_wav(path, seconds=1.0, sample_rate=44100, level=0):
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = int(sample_rate * seconds)
        handle.writeframes(bytes([level, 0] * frames))


class SetBuilder:
    """A folder of per-car shows."""

    def __init__(self, root):
        self.root = root

    def add_car(self, name, frames=100, step_time=20, channel_count=48,
                audio="lightshow.wav", audio_level=0, nested=True,
                fseq_name="lightshow.fseq", fseq_bytes=None):
        folder = os.path.join(self.root, name)
        show_folder = os.path.join(folder, "LightShow") if nested else folder
        os.makedirs(show_folder, exist_ok=True)
        if fseq_name:
            with open(os.path.join(show_folder, fseq_name), "wb") as handle:
                handle.write(fseq_bytes if fseq_bytes is not None
                             else build_fseq_bytes(frames, channel_count,
                                                   step_time))
        if audio:
            write_wav(os.path.join(show_folder, audio),
                      seconds=frames * step_time / 1000.0,
                      level=audio_level)
        return show_folder


class MultiCarTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name
        self.builder = SetBuilder(self.tmpdir)

    def check(self):
        return mc.check_set(self.tmpdir)

    def codes(self, show_set):
        return [f.code for f in show_set.findings]

    def add_cars(self, count, **kwargs):
        for index in range(1, count + 1):
            self.builder.add_car("Car #{}".format(index), **kwargs)


class DiscoveryTests(MultiCarTestCase):
    def test_cars_are_found_and_ordered_by_number(self):
        for name in ("Car #3", "Car #1", "Car #10", "Car #2"):
            self.builder.add_car(name)
        cars = mc.discover_cars(self.tmpdir)

        self.assertEqual([c.name for c in cars],
                         ["Car #1", "Car #2", "Car #3", "Car #10"])
        self.assertEqual([c.number for c in cars], [1, 2, 3, 10])

    def test_a_car_folder_holding_the_files_directly_is_accepted(self):
        self.builder.add_car("Car #1", nested=False)
        self.assertEqual(len(mc.discover_cars(self.tmpdir)), 1)

    def test_a_single_drive_is_not_a_set(self):
        # A folder that is itself one car's drive has a LightShow folder at
        # its base; that is usb_check.py's job, not this tool's.
        os.makedirs(os.path.join(self.tmpdir, "LightShow"))
        self.assertEqual(mc.discover_cars(self.tmpdir), [])

    def test_folders_without_a_show_are_ignored(self):
        self.builder.add_car("Car #1")
        os.makedirs(os.path.join(self.tmpdir, "artwork"))
        self.assertEqual([c.name for c in mc.discover_cars(self.tmpdir)],
                         ["Car #1"])

    def test_a_missing_folder_is_an_error(self):
        with self.assertRaises(mc.ShowSetError):
            mc.discover_cars(os.path.join(self.tmpdir, "nope"))

    def test_an_empty_folder_reports_no_cars(self):
        show_set = self.check()
        self.assertEqual(self.codes(show_set), ["no-cars-found"])
        self.assertEqual(show_set.counts()[mc.ERROR], 1)


class CarReadingTests(MultiCarTestCase):
    def test_a_car_reports_its_length_interval_and_channels(self):
        self.builder.add_car("Car #1", frames=500, step_time=20,
                             channel_count=200)
        car = mc.check_set(self.tmpdir).cars[0]

        self.assertEqual(car.duration_ms, 10000)
        self.assertEqual(car.step_time_ms, 20)
        self.assertEqual(car.channel_count, 200)
        self.assertTrue(car.ok)

    def test_a_car_without_a_show_is_unusable(self):
        self.builder.add_car("Car #1", fseq_name=None)
        show_set = self.check()

        self.assertIn("car-show-unusable", self.codes(show_set))
        self.assertFalse(show_set.cars[0].ok)

    def test_two_shows_on_one_car_is_unusable(self):
        folder = self.builder.add_car("Car #1")
        with open(os.path.join(folder, "second.fseq"), "wb") as handle:
            handle.write(build_fseq_bytes())
        show_set = self.check()

        self.assertIn("car-show-unusable", self.codes(show_set))
        self.assertIn("2 .fseq files", show_set.cars[0].error)

    def test_an_invalid_show_carries_the_validator_message(self):
        self.builder.add_car("Car #1",
                             fseq_bytes=build_fseq_bytes(magic=b"NOPE"))
        show_set = self.check()

        self.assertIn("car-show-unusable", self.codes(show_set))
        self.assertIn("FSEQ v2.0", show_set.cars[0].error)


class DurationTests(MultiCarTestCase):
    def test_matching_lengths_pass(self):
        self.add_cars(3, frames=500, step_time=20)
        show_set = self.check()

        self.assertEqual(show_set.counts()[mc.ERROR], 0)
        self.assertEqual(show_set.counts()[mc.WARNING], 0)

    def test_a_shorter_car_is_an_error(self):
        self.builder.add_car("Car #1", frames=500)
        self.builder.add_car("Car #2", frames=400)
        show_set = self.check()

        findings = [f for f in show_set.findings
                    if f.code == "duration-mismatch"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, mc.ERROR)
        self.assertIn("Car #2", findings[0].detail)

    def test_a_small_difference_is_tolerated(self):
        self.builder.add_car("Car #1", frames=500, step_time=20)
        self.builder.add_car("Car #2", frames=502, step_time=20)  # 40 ms
        self.assertNotIn("duration-mismatch", self.codes(self.check()))

    def test_different_frame_intervals_are_not_a_problem(self):
        """The rule from lightshow_example_3: length matters, rate does not.

        Cars 1 and 3 of the shipped five-car show run at 25 ms and the rest
        at 50 ms, every car lasting the same 110.25 s.
        """
        self.builder.add_car("Car #1", frames=1000, step_time=25)
        self.builder.add_car("Car #2", frames=500, step_time=50)
        show_set = self.check()

        self.assertNotIn("duration-mismatch", self.codes(show_set))
        self.assertEqual(show_set.counts()[mc.ERROR], 0)
        interval = [f for f in show_set.findings
                    if f.code == "frame-interval-mismatch"]
        self.assertEqual(len(interval), 1)
        self.assertEqual(interval[0].severity, mc.INFO)

    def test_one_car_alone_needs_no_agreement(self):
        self.builder.add_car("Car #1")
        self.assertNotIn("duration-mismatch", self.codes(self.check()))


class AudioTests(MultiCarTestCase):
    def test_the_same_track_on_every_car_passes(self):
        self.add_cars(3)
        self.assertNotIn("audio-mismatch", self.codes(self.check()))

    def test_a_different_track_on_one_car_is_an_error(self):
        self.builder.add_car("Car #1")
        self.builder.add_car("Car #2")
        self.builder.add_car("Car #3", audio_level=7)   # same length, new bytes
        show_set = self.check()

        findings = [f for f in show_set.findings if f.code == "audio-mismatch"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, mc.ERROR)

    def test_a_car_with_no_audio_is_an_error(self):
        self.builder.add_car("Car #1")
        self.builder.add_car("Car #2", audio=None)
        show_set = self.check()

        findings = [f for f in show_set.findings if f.code == "audio-missing"]
        self.assertEqual(len(findings), 1)
        self.assertIn("Car #2", findings[0].detail)

    def test_the_same_file_under_two_names_is_only_a_note(self):
        self.builder.add_car("Car #1", audio="lightshow.wav")
        self.builder.add_car("Car #2", audio="the-arrival.wav")
        show_set = self.check()

        self.assertNotIn("audio-mismatch", self.codes(show_set))
        notes = [f for f in show_set.findings
                 if f.code == "audio-named-differently"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].severity, mc.INFO)


class NumberingTests(MultiCarTestCase):
    def test_a_gap_in_the_numbering_is_a_warning(self):
        self.builder.add_car("Car #1")
        self.builder.add_car("Car #2")
        self.builder.add_car("Car #4")
        findings = [f for f in self.check().findings
                    if f.code == "car-numbering-gap"]

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, mc.WARNING)
        self.assertIn("car 3", findings[0].summary)

    def test_contiguous_numbering_passes(self):
        self.add_cars(4)
        self.assertNotIn("car-numbering-gap", self.codes(self.check()))

    def test_a_repeated_number_is_a_warning(self):
        self.builder.add_car("Car #1")
        self.builder.add_car("Car #1 copy")
        self.assertIn("car-number-repeated", self.codes(self.check()))

    def test_unnumbered_folders_are_a_note(self):
        self.builder.add_car("left")
        self.builder.add_car("right")
        findings = [f for f in self.check().findings
                    if f.code == "cars-not-numbered"]

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, mc.INFO)

    def test_more_cars_than_the_guide_documents_is_a_note(self):
        self.add_cars(8)
        findings = [f for f in self.check().findings
                    if f.code == "more-cars-than-documented"]

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, mc.INFO)

    def test_five_cars_is_not_noted(self):
        self.add_cars(5)
        self.assertNotIn("more-cars-than-documented", self.codes(self.check()))


class ChannelCountTests(MultiCarTestCase):
    def test_mixed_exports_are_a_warning(self):
        self.builder.add_car("Car #1", channel_count=200)
        self.builder.add_car("Car #2", channel_count=48)
        findings = [f for f in self.check().findings
                    if f.code == "channel-count-mismatch"]

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, mc.WARNING)

    def test_one_layout_across_the_set_passes(self):
        self.add_cars(3, channel_count=200)
        self.assertNotIn("channel-count-mismatch", self.codes(self.check()))


class ReportingTests(MultiCarTestCase):
    def test_a_clean_set_says_so(self):
        self.add_cars(3)
        text = mc.render_report(self.check(), verbose=False)

        self.assertIn("3 car(s):", text)
        self.assertIn("this set will run as one show", text)

    def test_notes_are_hidden_unless_verbose(self):
        self.builder.add_car("Car #1", frames=1000, step_time=25)
        self.builder.add_car("Car #2", frames=500, step_time=50)
        show_set = self.check()

        self.assertNotIn("frame-interval-mismatch",
                         mc.render_report(show_set, verbose=False))
        self.assertIn("frame-interval-mismatch",
                      mc.render_report(show_set, verbose=True))

    def test_an_unusable_car_is_shown_in_the_table(self):
        self.builder.add_car("Car #1")
        self.builder.add_car("Car #2", fseq_name=None)
        self.assertIn("no .fseq file",
                      mc.render_report(self.check(), verbose=False))

    def test_the_report_serialises_to_json(self):
        self.add_cars(2)
        payload = json.loads(json.dumps(self.check().as_dict()))

        self.assertEqual(payload["car_count"], 2)
        self.assertTrue(payload["cars"][0]["ok"])
        self.assertEqual(payload["counts"]["error"], 0)


class CommandLineTests(MultiCarTestCase):
    def run_main(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        original = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout, stderr
        try:
            code = mc.main(list(argv))
        finally:
            sys.stdout, sys.stderr = original
        return code, stdout.getvalue(), stderr.getvalue()

    def test_a_consistent_set_exits_zero(self):
        self.add_cars(3)
        code, out, _ = self.run_main(self.tmpdir)

        self.assertEqual(code, 0)
        self.assertIn("run as one show", out)

    def test_a_mismatch_exits_one(self):
        self.builder.add_car("Car #1", frames=500)
        self.builder.add_car("Car #2", frames=100)
        self.assertEqual(self.run_main(self.tmpdir)[0], 1)

    def test_warnings_only_exit_zero_unless_strict(self):
        self.builder.add_car("Car #1")
        self.builder.add_car("Car #3")

        self.assertEqual(self.run_main(self.tmpdir)[0], 0)
        self.assertEqual(self.run_main(self.tmpdir, "--strict")[0], 1)

    def test_an_unreadable_path_exits_two(self):
        code, _, err = self.run_main(os.path.join(self.tmpdir, "nope"))

        self.assertEqual(code, 2)
        self.assertIn("nope", err)

    def test_json_output_parses(self):
        self.add_cars(2)
        code, out, _ = self.run_main(self.tmpdir, "--json")

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["car_count"], 2)


class ShippedCrossVehicleShowTests(unittest.TestCase):
    """The three cross-vehicle shows this repository ships must pass."""

    def sets(self):
        examples = os.path.join(REPO_ROOT, "examples")
        for name in sorted(os.listdir(examples)):
            path = os.path.join(examples, name)
            if os.path.isdir(path) and mc.discover_cars(path):
                yield name, mc.check_set(path)

    def test_every_shipped_set_agrees(self):
        seen = 0
        for name, show_set in self.sets():
            seen += 1
            serious = [f for f in show_set.findings
                       if f.severity in (mc.ERROR, mc.WARNING)]
            self.assertEqual([], serious, "{}: {}".format(
                name, [f.summary for f in serious]))
        self.assertGreaterEqual(seen, 3, "expected the shipped multi-car sets")

    def test_the_arrival_mixes_frame_intervals_deliberately(self):
        """The case that shaped the duration rule."""
        path = os.path.join(REPO_ROOT, "examples",
                            "lightshow_example_3_The_Arrival_5_Car")
        show_set = mc.check_set(path)
        intervals = {c.step_time_ms for c in show_set.cars}
        durations = {c.duration_ms for c in show_set.cars}

        self.assertEqual(intervals, {25, 50})
        self.assertEqual(len(durations), 1)
        self.assertEqual(show_set.counts()[mc.ERROR], 0)

    def test_every_shipped_car_carries_the_same_audio(self):
        for name, show_set in self.sets():
            digests = {c.audio_digest for c in show_set.cars}
            self.assertEqual(len(digests), 1, name)


if __name__ == "__main__":
    unittest.main()
