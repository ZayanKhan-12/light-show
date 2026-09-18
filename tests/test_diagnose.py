"""Tests for tools/diagnose.py.

https://github.com/teslamotors/light-show/issues/98 is a reproducible crash in
the car after the show has been accepted, which means the drive and the file
were sound by the time it failed. Establishing that in one command is the
point of this tool, so what it rules out matters as much as what it finds.
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

import diagnose as dg  # noqa: E402

HEADER_BYTES = 32


def fseq_bytes(frames=50, channel_count=200, step_time=20, magic=b"PSEQ"):
    header = bytearray(HEADER_BYTES)
    header[0:4] = magic
    struct.pack_into("<H", header, 4, HEADER_BYTES)
    header[7] = 2
    struct.pack_into("<IIB", header, 10, channel_count, frames, step_time)
    return bytes(header) + bytes(channel_count * frames)


class DiagnoseTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def write(self, relative, data=b""):
        path = os.path.join(self.tmpdir, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def a_drive(self, name="show"):
        folder = os.path.join(self.tmpdir, "LightShow")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name + ".fseq"), "wb") as handle:
            handle.write(fseq_bytes())
        with wave.open(os.path.join(folder, name + ".wav"), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(44100)
            handle.writeframes(bytes(44100 * 2))
        return self.tmpdir


class IdentifyTests(DiagnoseTestCase):
    def test_an_fseq_is_a_show(self):
        path = self.write("lightshow.fseq", fseq_bytes())
        self.assertEqual(dg.identify(path), "show")

    def test_an_xsq_is_a_sequence(self):
        path = self.write("lightshow.xsq", b"<xsequence/>")
        self.assertEqual(dg.identify(path), "sequence")

    def test_a_drive_is_a_drive(self):
        self.assertEqual(dg.identify(self.a_drive()), "drive")

    def test_a_project_directory_is_a_show_folder(self):
        self.write("xlights_rgbeffects.xml", b"<xrgb><models/></xrgb>")
        self.assertEqual(dg.identify(self.tmpdir), "show folder")

    def test_per_car_folders_are_a_cross_vehicle_set(self):
        for car in ("Car #1", "Car #2"):
            folder = os.path.join(self.tmpdir, car, "LightShow")
            os.makedirs(folder)
            with open(os.path.join(folder, "lightshow.fseq"), "wb") as handle:
                handle.write(fseq_bytes())
        self.assertEqual(dg.identify(self.tmpdir), "cross-vehicle set")

    def test_an_unknown_file_is_refused_with_advice(self):
        path = self.write("notes.txt", b"hello")
        with self.assertRaises(dg.DiagnoseError) as caught:
            dg.identify(path)
        self.assertIn(".fseq", str(caught.exception))

    def test_a_missing_path_is_refused(self):
        with self.assertRaises(dg.DiagnoseError):
            dg.identify(os.path.join(self.tmpdir, "nope"))


class RunTests(DiagnoseTestCase):
    def test_a_show_is_checked_against_the_vehicles(self):
        path = self.write("lightshow.fseq", fseq_bytes())
        kind, stages = dg.run(path, vehicle="models")

        self.assertEqual(kind, "show")
        self.assertEqual([layer for layer, _, _ in stages], [dg.VEHICLE_FIT])

    def test_a_drive_is_checked_and_so_are_its_shows(self):
        kind, stages = dg.run(self.a_drive(), vehicle="models")
        layers = [layer for layer, _, _ in stages]

        self.assertEqual(kind, "drive")
        self.assertEqual(layers[0], dg.DRIVE)
        self.assertIn(dg.VEHICLE_FIT, layers)

    def test_a_broken_drive_is_reported_as_the_drive(self):
        os.makedirs(os.path.join(self.tmpdir, "LightShow"))
        self.write(os.path.join("LightShow", "lonely.fseq"), fseq_bytes())
        _, stages = dg.run(self.tmpdir)

        drive = [ok for layer, _, ok in stages if layer == dg.DRIVE]
        self.assertEqual(drive, [False])

    def test_a_sequence_is_checked_on_its_own(self):
        path = self.write("lightshow.xsq", (
            b'<xsequence><head><sequenceTiming>20 ms</sequenceTiming>'
            b'</head><ElementEffects/></xsequence>'))
        kind, stages = dg.run(path)

        self.assertEqual(kind, "sequence")
        self.assertEqual([layer for layer, _, _ in stages], [dg.SEQUENCE])


class ConclusionTests(unittest.TestCase):
    def test_a_failure_names_the_layer_and_stops_there(self):
        text = "\n".join(dg.conclude([
            (dg.DRIVE, [], False), (dg.VEHICLE_FIT, [], True)]))

        self.assertIn(dg.DRIVE, text)
        self.assertIn("before looking any further out", text)
        self.assertNotIn("remaining layer", text)

    def test_all_clear_points_at_the_vehicle_software(self):
        text = "\n".join(dg.conclude([(dg.DRIVE, [], True)]))

        self.assertIn("Checked and sound", text)
        self.assertIn(dg.VEHICLE_SOFTWARE, text)
        self.assertIn("CONTRIBUTING.md", text)

    def test_the_symptoms_named_are_the_ones_owners_report(self):
        # #98 "Screen will say 'enjoy the show' then crash", and #112 "worked
        # yesterday, today it would not".
        text = "\n".join(dg.conclude([(dg.DRIVE, [], True)]))

        self.assertIn("crashing", text)
        self.assertIn("starting and then stopping", text)
        self.assertIn("read yesterday", text)

    def test_the_conclusion_points_at_the_recovery_steps(self):
        text = "\n".join(dg.conclude([(dg.DRIVE, [], True)]))
        self.assertIn("under Debug", text)


class CommandLineTests(DiagnoseTestCase):
    def run_main(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        original = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout, stderr
        try:
            code = dg.main(list(argv))
        finally:
            sys.stdout, sys.stderr = original
        return code, stdout.getvalue(), stderr.getvalue()

    def test_a_sound_drive_exits_zero_and_rules_things_out(self):
        code, out, _ = self.run_main(self.a_drive(), "--vehicle", "cybertruck")

        self.assertEqual(code, 0)
        self.assertIn("What this rules out", out)
        self.assertIn(dg.VEHICLE_SOFTWARE, out)

    def test_a_broken_drive_exits_one(self):
        os.makedirs(os.path.join(self.tmpdir, "LightShow"))
        self.write(os.path.join("LightShow", "lonely.fseq"), fseq_bytes())
        self.assertEqual(self.run_main(self.tmpdir)[0], 1)

    def test_an_unknown_path_exits_two(self):
        code, _, err = self.run_main(os.path.join(self.tmpdir, "nope"))

        self.assertEqual(code, 2)
        self.assertTrue(err.strip())

    def test_a_bad_show_file_exits_two_rather_than_crashing(self):
        path = self.write("broken.fseq", fseq_bytes(magic=b"NOPE"))
        code, _, err = self.run_main(path)

        self.assertEqual(code, 2)
        self.assertTrue(err.strip())

    def test_json_output_parses(self):
        code, out, _ = self.run_main(self.a_drive(), "--vehicle", "cybertruck",
                                     "--json")
        payload = json.loads(out)

        self.assertEqual(code, 0)
        self.assertTrue(payload["all_clear"])
        self.assertEqual(payload["kind"], "drive")
        self.assertTrue(payload["stages"])


class ContributingTests(unittest.TestCase):
    """The page diagnose.py sends people to has to exist and say the thing."""

    def contributing(self):
        with open(os.path.join(REPO_ROOT, "CONTRIBUTING.md"),
                  encoding="utf-8") as handle:
            return handle.read()

    def test_it_exists_and_names_every_layer(self):
        # The page writes them as table headings, so match without case.
        text = self.contributing().lower()
        for layer in (dg.DRIVE, dg.SHOW_FILE, dg.VEHICLE_FIT,
                      dg.VEHICLE_SOFTWARE):
            self.assertIn(layer.lower(), text, layer)

    def test_it_says_where_vehicle_reports_go(self):
        text = self.contributing()
        self.assertIn("Tesla service", text)
        self.assertIn("xLights tracker", text)

    def test_it_repeats_the_rule_about_channel_assignments(self):
        self.assertIn("public API", self.contributing())


if __name__ == "__main__":
    unittest.main()
