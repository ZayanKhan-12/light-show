"""Tests for tools/fseq_export.py.

https://github.com/teslamotors/light-show/issues/79 asks how to get the data
back out of a .fseq. These hold the half of the answer this repository owns:
reading the show out in a form a person or a script can work with, with each
value decoded the way README.md documents it.
"""

import csv
import io
import json
import os
import struct
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import fseq_export as fx  # noqa: E402
import vehicle_preview as vp  # noqa: E402

HEADER_BYTES = 32

ON_INSTANT = 255
ON_2000 = 229          # 90%
OFF_500 = 25           # 10%
OPEN_CMD = 64          # 25%
DANCE_CMD = 128        # 50%


def make_show(frame_count, events, channel_count=200, step_time=20):
    data = bytearray(frame_count * channel_count)
    for channel, spans in events.items():
        for start, length, value in spans:
            for frame in range(start, start + length):
                data[frame * channel_count + (channel - 1)] = value
    return vp.Show(channel_count, frame_count, step_time, bytes(data))


def write_fseq(path, show):
    header = bytearray(HEADER_BYTES)
    header[0:4] = b"PSEQ"
    struct.pack_into("<H", header, 4, HEADER_BYTES)
    header[7] = 2
    struct.pack_into("<IIB", header, 10, show.channel_count,
                     show.frame_count, show.step_time_ms)
    with open(path, "wb") as handle:
        handle.write(bytes(header) + show.data)
    return path


class EffectNameTests(unittest.TestCase):
    def test_a_light_ramp_code_is_named(self):
        self.assertEqual(fx.describe_effect(1, ON_2000), "on over 2000 ms")
        self.assertEqual(fx.describe_effect(1, OFF_500), "off over 500 ms")

    def test_instant_on_carries_no_ramp(self):
        self.assertEqual(fx.describe_effect(1, ON_INSTANT), "on")

    def test_a_closure_command_is_named(self):
        self.assertEqual(fx.describe_effect(41, OPEN_CMD), "Open")
        self.assertEqual(fx.describe_effect(41, DANCE_CMD), "Dance")

    def test_an_interior_channel_reports_a_level(self):
        self.assertEqual(fx.describe_effect(176, 200), "level 200")

    def test_an_undocumented_light_value_says_so(self):
        # 60% is not one of the documented steps.
        text = fx.describe_effect(1, 153)
        self.assertIn("60%", text)
        self.assertIn("on", text)

    def test_an_undocumented_closure_value_says_so(self):
        self.assertIn("undocumented", fx.describe_effect(41, 100))


class ExportTests(unittest.TestCase):
    def test_one_row_per_stretch_of_frames(self):
        show = make_show(100, {1: [(10, 5, ON_INSTANT), (30, 5, ON_2000)]})
        rows = fx.export(show)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["start_ms"], 200)
        self.assertEqual(rows[0]["end_ms"], 300)
        self.assertEqual(rows[0]["duration_ms"], 100)
        self.assertEqual(rows[1]["effect"], "on over 2000 ms")

    def test_dark_stretches_are_left_out_by_default(self):
        show = make_show(100, {1: [(10, 5, ON_INSTANT)]})
        self.assertEqual(len(fx.export(show)), 1)

    def test_dark_stretches_can_be_asked_for(self):
        show = make_show(100, {1: [(10, 5, ON_INSTANT)]})
        rows = fx.export(show, channels=[1], include_off=True)

        self.assertEqual(len(rows), 3)          # dark, lit, dark
        self.assertEqual(rows[0]["value"], 0)

    def test_rows_come_out_in_time_order(self):
        show = make_show(100, {1: [(50, 5, ON_INSTANT)],
                               2: [(10, 5, ON_INSTANT)]})
        rows = fx.export(show)

        self.assertEqual([r["channel"] for r in rows], [2, 1])

    def test_channels_can_be_limited(self):
        show = make_show(100, {1: [(10, 5, ON_INSTANT)],
                               2: [(10, 5, ON_INSTANT)]})
        rows = fx.export(show, channels=[2])

        self.assertEqual({r["channel"] for r in rows}, {2})

    def test_channels_outside_the_show_are_skipped(self):
        show = make_show(10, {1: [(0, 5, ON_INSTANT)]}, channel_count=48)
        self.assertEqual(fx.export(show, channels=[1, 300]),
                         fx.export(show, channels=[1]))

    def test_every_row_carries_the_channel_name_and_kind(self):
        show = make_show(100, {41: [(10, 5, OPEN_CMD)]})
        row = fx.export(show)[0]

        self.assertEqual(row["name"], "Liftgate")
        self.assertEqual(row["kind"], vp.CLOSURE)

    def test_a_show_that_does_nothing_exports_nothing(self):
        self.assertEqual(fx.export(make_show(100, {})), [])


class RenderTests(unittest.TestCase):
    def test_csv_has_a_header_and_a_row_each(self):
        show = make_show(100, {1: [(10, 5, ON_INSTANT)]})
        text = fx.render_csv(fx.export(show))
        rows = list(csv.DictReader(io.StringIO(text)))

        self.assertEqual(list(rows[0].keys()), list(fx.FIELDS))
        self.assertEqual(rows[0]["name"], "Left Outer Main Beam")

    def test_json_carries_the_show_header_too(self):
        show = make_show(100, {1: [(10, 5, ON_INSTANT)]})
        payload = json.loads(fx.render_json(show, fx.export(show)))

        self.assertEqual(payload["channel_count"], 200)
        self.assertEqual(payload["step_time_ms"], 20)
        self.assertEqual(payload["first_lit_ms"], 200)
        self.assertEqual(len(payload["rows"]), 1)


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
            code = fx.main(list(argv))
        finally:
            sys.stdout, sys.stderr = original
        return code, stdout.getvalue(), stderr.getvalue()

    def a_show(self):
        show = make_show(100, {1: [(10, 5, ON_INSTANT)],
                               41: [(20, 5, OPEN_CMD)]})
        return write_fseq(os.path.join(self.tmpdir, "show.fseq"), show)

    def test_csv_goes_to_standard_output(self):
        code, out, _ = self.run_main(self.a_show())

        self.assertEqual(code, 0)
        self.assertIn("Left Outer Main Beam", out)
        self.assertIn("Liftgate", out)

    def test_channels_can_be_limited_from_the_command_line(self):
        _, out, _ = self.run_main(self.a_show(), "--channels", "41")

        self.assertNotIn("Left Outer Main Beam", out)
        self.assertIn("Liftgate", out)

    def test_a_range_works(self):
        _, out, _ = self.run_main(self.a_show(), "--channels", "1-4")
        self.assertIn("Left Outer Main Beam", out)

    def test_json_output_parses(self):
        code, out, _ = self.run_main(self.a_show(), "--json")
        self.assertEqual(json.loads(out)["frame_count"], 100)

    def test_output_can_go_to_a_file(self):
        target = os.path.join(self.tmpdir, "out.csv")
        code, out, _ = self.run_main(self.a_show(), "-o", target)

        self.assertEqual(code, 0)
        self.assertIn("Wrote 2 row(s)", out)
        with open(target) as handle:
            self.assertIn("Liftgate", handle.read())

    def test_a_file_that_is_not_an_fseq_exits_two(self):
        path = os.path.join(self.tmpdir, "notes.txt")
        with open(path, "w") as handle:
            handle.write("nope")
        code, _, err = self.run_main(path)

        self.assertEqual(code, 2)
        self.assertTrue(err.strip())

    def test_a_bad_channel_spec_exits_two(self):
        code, _, err = self.run_main(self.a_show(), "--channels", "left")
        self.assertEqual(code, 2)
        self.assertIn("left", err)


class ShippedExampleTests(unittest.TestCase):
    def test_a_real_show_exports_and_decodes(self):
        path = os.path.join(
            REPO_ROOT, "examples", "lightshow_example_5_Cyber_Symphony_4_Car",
            "Car #1", "LightShow", "lightshow.fseq")
        show = vp.read_fseq(path)
        rows = fx.export(show, channels=[41])

        self.assertTrue(rows)
        self.assertEqual(rows[0]["effect"], "Open")
        self.assertEqual(rows[0]["start_ms"], 29120)
        self.assertEqual([r["effect"] for r in rows],
                         ["Open", "Dance", "Dance"])

    def test_every_row_of_a_real_show_names_an_effect(self):
        path = os.path.join(
            REPO_ROOT, "examples", "lightshow_example_3_The_Arrival_5_Car",
            "Car #1", "LightShow", "lightshow.fseq")
        rows = fx.export(vp.read_fseq(path))

        self.assertGreater(len(rows), 100)
        for row in rows:
            self.assertTrue(row["effect"])


if __name__ == "__main__":
    unittest.main()
