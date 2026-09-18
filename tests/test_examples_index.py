"""Tests for tools/examples_index.py.

https://github.com/teslamotors/light-show/issues/87 asks for the .xsq of a
show, which nobody could answer from the repository: examples/ is sixty
megabytes of archives and there was no way to see what was inside them. These
hold the index honest against the files themselves.
"""

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import examples_index as ei  # noqa: E402


class CarCountTests(unittest.TestCase):
    def test_per_car_folders_are_counted(self):
        self.assertEqual(ei._car_count([
            "show/Car #1/LightShow/lightshow.fseq",
            "show/Car #2/LightShow/lightshow.fseq",
        ]), 2)

    def test_a_file_named_like_a_car_is_not_a_car(self):
        """Car_setup.jpg sits beside the car folders in two examples."""
        self.assertEqual(ei._car_count([
            "show/Car #1/LightShow/lightshow.fseq",
            "show/Car_setup.jpg",
        ]), 1)

    def test_the_folder_must_be_a_whole_segment(self):
        self.assertEqual(ei._car_count(["show/Carousel/lightshow.fseq"]), 0)

    def test_several_spellings_are_accepted(self):
        for spelling in ("Car #1", "Car 1", "Car1", "car-1", "CAR_1"):
            self.assertEqual(
                ei._car_count(["show/{}/x.fseq".format(spelling)]), 1,
                spelling)

    def test_a_single_car_show_has_no_car_folders(self):
        self.assertEqual(ei._car_count(["show/lightshow.fseq"]), 0)


class DescribeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def make_zip(self, name, members):
        path = os.path.join(self.tmpdir, name)
        with zipfile.ZipFile(path, "w") as bundle:
            for member, data in members.items():
                bundle.writestr(member, data)
        return path

    def test_a_source_only_example_is_reported_as_such(self):
        path = self.make_zip("show.zip", {
            "Show/lightshow.xsq": "<xsequence/>",
            "Show/lightshow.wav": "RIFF",
        })
        example = ei.describe(path)

        self.assertTrue(example.has_source)
        self.assertFalse(example.has_show)
        self.assertIsNone(example.duration_ms)
        self.assertEqual(example.packaging, "zip")

    def test_a_show_only_example_is_reported_as_such(self):
        path = self.make_zip("show.zip", {"Show/lightshow.fseq": "not a show"})
        example = ei.describe(path)

        self.assertTrue(example.has_show)
        self.assertFalse(example.has_source)

    def test_an_unreadable_show_does_not_stop_the_index(self):
        path = self.make_zip("show.zip", {"Show/lightshow.fseq": "rubbish"})
        example = ei.describe(path)

        self.assertIsNone(example.duration_ms)
        self.assertIsNone(example.suits)

    def test_the_name_drops_the_zip_suffix(self):
        path = self.make_zip("my_show.zip", {"a/lightshow.xsq": "<x/>"})
        self.assertEqual(ei.describe(path).name, "my_show")


class RenderTests(unittest.TestCase):
    def test_the_table_has_a_row_per_example(self):
        rows = ei.render_markdown([
            ei.Example(name="one", packaging="zip", cars=1, shows=1,
                       sources=1, audio=1, duration_ms=45000,
                       suits="Model S (2021+)", suits_share=0.93),
        ]).splitlines()

        self.assertEqual(len(rows), 3)          # header, rule, one row
        self.assertIn("| one | 1 | yes | yes | 0:45 | Model S (2021+) (93%) |",
                      rows[2])

    def test_a_missing_duration_renders_as_a_dash(self):
        text = ei.render_markdown([
            ei.Example(name="x", packaging="zip", cars=1, sources=1)])
        self.assertIn("| no | yes | - | - |", text)


class ShippedExamplesTests(unittest.TestCase):
    """The index has to match what is actually in examples/."""

    def setUp(self):
        self.examples = {e.name: e for e in ei.collect()}

    def test_every_example_is_listed(self):
        on_disk = {n[:-4] if n.lower().endswith(".zip") else n
                   for n in os.listdir(ei.EXAMPLES_DIR)}
        self.assertEqual(set(self.examples), on_disk)

    def test_the_car_counts_match_the_names(self):
        self.assertEqual(
            self.examples["lightshow_example_3_The_Arrival_5_Car"].cars, 5)
        self.assertEqual(
            self.examples[
                "lightshow_example_4_Ready_for_Assault_8_Car"].cars, 8)
        self.assertEqual(
            self.examples[
                "lightshow_example_5_Cyber_Symphony_4_Car"].cars, 4)

    def test_which_examples_ship_an_editable_source(self):
        """The answer issue 87 needed.

        Five of the seven ship a .xsq. The two multi-car sets that do not are
        the same shows as examples 6 and 7, which ship the source on its own.
        """
        with_source = {name for name, e in self.examples.items()
                       if e.has_source}
        self.assertEqual(with_source, {
            "lightshow_example_1_elevator_music",
            "lightshow_example_2_Max_Carlisle_Auld_Lang_Syne_In_the_City",
            "lightshow_example_3_The_Arrival_5_Car",
            "lightshow_example_6_Ready_for_Assault_1_Car",
            "lightshow_example_7_Cyber_Symphony_1_Car",
        })

    def test_the_source_only_examples_ship_no_fseq(self):
        for name in ("lightshow_example_6_Ready_for_Assault_1_Car",
                     "lightshow_example_7_Cyber_Symphony_1_Car"):
            self.assertFalse(self.examples[name].has_show, name)
            self.assertTrue(self.examples[name].has_source, name)

    def test_every_example_ships_audio(self):
        for name, example in self.examples.items():
            self.assertGreater(example.audio, 0, name)

    def test_which_multi_car_shows_have_a_single_car_publication(self):
        """Issue 102, stated as a fact that can go stale.

        Ready for Assault and Cyber Symphony each ship a one-car sequence
        beside their multi-car set. The Arrival does not, which is exactly
        what the issue asks for. If that changes, the README paragraph
        claiming it does not exist has to change with it.
        """
        multi = {name: e for name, e in self.examples.items() if e.cars > 1}
        single = {name for name, e in self.examples.items() if e.cars == 1}

        self.assertIn("lightshow_example_6_Ready_for_Assault_1_Car", single)
        self.assertIn("lightshow_example_7_Cyber_Symphony_1_Car", single)
        self.assertIn("lightshow_example_3_The_Arrival_5_Car", multi)
        self.assertEqual(
            [n for n in single if "Arrival" in n], [],
            "a single-car Arrival now ships; update the README")

    def test_the_readme_records_that_gap(self):
        with open(os.path.join(REPO_ROOT, "README.md"),
                  encoding="utf-8") as handle:
            readme = handle.read()
        self.assertIn("no equivalent single-car publication of *The Arrival*",
                      readme)

    def test_the_readme_table_matches_this_output(self):
        """The table in README.md is generated; keep it that way."""
        with open(os.path.join(REPO_ROOT, "README.md"),
                  encoding="utf-8") as handle:
            readme = handle.read()
        for line in ei.render_markdown(ei.collect()).splitlines():
            self.assertIn(line, readme, line)


class CommandLineTests(unittest.TestCase):
    def run_main(self, *argv):
        stdout = io.StringIO()
        original = sys.stdout
        sys.stdout = stdout
        try:
            code = ei.main(list(argv))
        finally:
            sys.stdout = original
        return code, stdout.getvalue()

    def test_markdown_is_the_default(self):
        code, out = self.run_main()

        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("| Example |"))

    def test_json_output_parses(self):
        code, out = self.run_main("--json")
        payload = json.loads(out)

        self.assertEqual(code, 0)
        self.assertTrue(any(e["has_source"] for e in payload))
        self.assertTrue(any(not e["has_show"] for e in payload))


if __name__ == "__main__":
    unittest.main()
