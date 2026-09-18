"""Tests for tools/show_folder_check.py.

https://github.com/teslamotors/light-show/issues/75 is one sentence -- "the
file doesn't show up when I press custom and then I select file of model S" --
and it has two ordinary causes that can be told apart from disk: the audio is
a format xLights never lists, or the folder given to xLights is not the
project folder. Both are covered here.
"""

import io
import json
import os
import sys
import tempfile
import unittest
import wave
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import show_folder_check as sf  # noqa: E402


NETWORKS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Networks>
{controllers}
</Networks>"""

CONTROLLER = """  <Controller Id="{id}" Name="Model S {id}" Type="Null">
    <network NetworkType="NULL" MaxChannels="200"/>
  </Controller>"""

RGBEFFECTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<xrgb>
  <models>
{models}
  </models>
</xrgb>"""


class FolderBuilder:
    def __init__(self, root):
        self.root = root

    def show_folder(self, name="tesla_xlights_show_folder", cars=1, models=3,
                    files=sf.EXPECTED_FILES):
        folder = os.path.join(self.root, name)
        os.makedirs(folder, exist_ok=True)
        for filename in files:
            path = os.path.join(folder, filename)
            if filename == sf.NETWORKS:
                body = "\n".join(CONTROLLER.format(id=i + 1)
                                 for i in range(cars))
                text = NETWORKS_XML.format(controllers=body)
            elif filename == sf.RGBEFFECTS:
                body = "\n".join(
                    '    <model name="Model {}" StartChannel="1"/>'.format(i)
                    for i in range(models))
                text = RGBEFFECTS_XML.format(models=body)
            else:
                text = "<xml/>"
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        return folder

    def audio(self, folder, name, sample_rate=44100, seconds=0.1):
        path = os.path.join(folder, name)
        if name.lower().endswith(".wav"):
            with wave.open(path, "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(sample_rate)
                handle.writeframes(bytes(int(sample_rate * seconds) * 2))
        else:
            with open(path, "wb") as handle:
                handle.write(b"\x00" * 64)
        return path


class ShowFolderTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name
        self.builder = FolderBuilder(self.tmpdir)

    def codes(self, report):
        return [f.code for f in report.findings]

    def find(self, report, code):
        return [f for f in report.findings if f.code == code]


class LocateTests(ShowFolderTestCase):
    def test_a_correct_folder_is_recognised(self):
        folder = self.builder.show_folder()
        report = sf.check_show_folder(folder)

        self.assertTrue(report.is_show_folder)
        self.assertEqual(report.counts()[sf.ERROR], 0)

    def test_the_extract_all_mistake_names_the_right_folder(self):
        inner = self.builder.show_folder()
        report = sf.check_show_folder(self.tmpdir)

        findings = self.find(report, "folder-one-level-up")
        self.assertEqual(len(findings), 1)
        self.assertIn(inner, findings[0].detail)
        self.assertTrue(report.is_show_folder)

    def test_a_zip_is_reported_as_not_extracted(self):
        path = os.path.join(self.tmpdir, "tesla_xlights_show_folder.zip")
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("x", "y")
        report = sf.check_show_folder(path)

        self.assertEqual(self.codes(report), ["not-extracted"])
        self.assertFalse(report.is_show_folder)

    def test_a_truncated_download_is_told_apart_from_an_unextracted_one(self):
        """Issue 101: a download that stopped part way looks like a .zip."""
        good = os.path.join(self.tmpdir, "tesla_xlights_show_folder.zip")
        with zipfile.ZipFile(good, "w") as bundle:
            bundle.writestr("tesla_xlights_show_folder/x", "y")
        with open(good, "rb") as handle:
            whole = handle.read()

        broken = os.path.join(self.tmpdir, "half.zip")
        with open(broken, "wb") as handle:
            handle.write(whole[:len(whole) // 2])

        self.assertEqual(self.codes(sf.check_show_folder(broken)),
                         ["download-incomplete"])
        self.assertEqual(self.codes(sf.check_show_folder(good)),
                         ["not-extracted"])

    def test_an_empty_archive_is_reported_as_incomplete(self):
        path = os.path.join(self.tmpdir, "empty.zip")
        with zipfile.ZipFile(path, "w"):
            pass
        findings = sf.check_show_folder(path).findings

        self.assertEqual([f.code for f in findings], ["download-incomplete"])
        self.assertIn("empty", findings[0].detail)

    def test_an_intact_archive_says_it_is_intact(self):
        path = os.path.join(self.tmpdir, "show.zip")
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("show/x", "y")
        findings = sf.check_show_folder(path).findings

        self.assertIn("intact", findings[0].detail)

    def test_the_shipped_archives_are_readable(self):
        """What a download is supposed to arrive as."""
        for name in ("xlights/tesla_xlights_show_folder.zip",
                     "xlights/tesla_xlights_cross_vehicle_folder.zip"):
            path = os.path.join(REPO_ROOT, name)
            self.assertIsNone(sf._zip_problem(path), name)

    def test_a_folder_holding_only_the_zip_says_to_unzip_it(self):
        with zipfile.ZipFile(
                os.path.join(self.tmpdir,
                             "tesla_xlights_show_folder.zip"), "w") as bundle:
            bundle.writestr("x", "y")
        self.assertEqual(self.codes(sf.check_show_folder(self.tmpdir)),
                         ["still-zipped"])

    def test_two_project_folders_side_by_side_are_reported(self):
        self.builder.show_folder(name="one")
        self.builder.show_folder(name="two")
        self.assertEqual(self.codes(sf.check_show_folder(self.tmpdir)),
                         ["several-show-folders"])

    def test_an_unrelated_folder_is_reported(self):
        os.makedirs(os.path.join(self.tmpdir, "holiday photos"))
        report = sf.check_show_folder(self.tmpdir)

        self.assertEqual(self.codes(report), ["not-a-show-folder"])
        self.assertIn(sf.RGBEFFECTS, report.findings[0].summary)

    def test_an_ordinary_file_is_not_a_folder(self):
        path = os.path.join(self.tmpdir, "notes.txt")
        with open(path, "w") as handle:
            handle.write("x")
        self.assertEqual(self.codes(sf.check_show_folder(path)),
                         ["not-a-folder"])

    def test_a_missing_path_raises(self):
        with self.assertRaises(sf.ShowFolderError):
            sf.check_show_folder(os.path.join(self.tmpdir, "nope"))


class ContentsTests(ShowFolderTestCase):
    def test_controllers_models_and_channels_are_counted(self):
        report = sf.check_show_folder(self.builder.show_folder(models=7))

        self.assertEqual(report.models, 7)
        self.assertEqual(report.controllers, 1)
        self.assertEqual(report.channels, 200)
        self.assertEqual(report.cars, 1)

    def test_the_cross_vehicle_folder_is_named_as_such(self):
        report = sf.check_show_folder(self.builder.show_folder(cars=5))
        findings = self.find(report, "cross-vehicle-folder")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sf.INFO)
        self.assertEqual(report.cars, 5)
        self.assertIn("1000 channels", findings[0].detail)

    def test_a_single_car_folder_is_not_flagged(self):
        report = sf.check_show_folder(self.builder.show_folder(cars=1))
        self.assertNotIn("cross-vehicle-folder", self.codes(report))

    def test_a_missing_required_file_is_an_error(self):
        folder = self.builder.show_folder(files=(sf.RGBEFFECTS,))
        report = sf.check_show_folder(folder)

        findings = self.find(report, "incomplete-show-folder")
        self.assertEqual(len(findings), 1)
        self.assertIn(sf.NETWORKS, findings[0].summary)

    def test_a_folder_with_no_models_is_a_warning(self):
        report = sf.check_show_folder(self.builder.show_folder(models=0))
        findings = self.find(report, "no-models")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sf.WARNING)


class CrossVehicleTests(ShowFolderTestCase):
    """Issue 134: extending the cross-vehicle folder past five cars.

    A car is a controller, 77 models named "<car> <model>" on that
    controller, and a mapping file. Duplicating that by hand is where it goes
    wrong, and each of these is a mistake someone actually makes.
    """

    def build(self, cars, models=("Rear Light Bar", "Brake Lights"),
              controller_for=None, mappings=None, drop=()):
        folder = self.builder.show_folder(cars=len(cars))
        entries = []
        for car in cars:
            for model in models:
                if (car, model) in drop:
                    continue
                owner = (controller_for or {}).get(car, car)
                entries.append(
                    '    <model name="{} {}" StartChannel="!Model S {}:1"/>'
                    .format(car, model, owner))
        with open(os.path.join(folder, sf.RGBEFFECTS), "w",
                  encoding="utf-8") as handle:
            handle.write(RGBEFFECTS_XML.format(models="\n".join(entries)))
        for car in (cars if mappings is None else mappings):
            open(os.path.join(folder,
                              "{}{}.xmap".format(sf.MAPPING_PREFIX, car)),
                 "w").close()
        return folder

    def test_a_consistent_set_of_cars_passes(self):
        report = sf.check_show_folder(self.build([1, 2, 3]))

        self.assertEqual(report.counts()[sf.ERROR], 0)
        self.assertEqual(report.counts()[sf.WARNING], 0)

    def test_a_car_missing_a_model_is_an_error(self):
        report = sf.check_show_folder(
            self.build([1, 2], drop={(2, "Brake Lights")}))
        findings = self.find(report, "cars-do-not-match")

        self.assertEqual(len(findings), 1)
        self.assertIn("Brake Lights", findings[0].detail)

    def test_a_duplicate_left_on_the_wrong_controller_is_an_error(self):
        """The usual mistake: a copied model keeps its StartChannel."""
        report = sf.check_show_folder(
            self.build([1, 2], controller_for={2: 1}))
        findings = self.find(report, "car-on-wrong-controller")

        self.assertEqual(len(findings), 1)
        self.assertIn("Model S 1", findings[0].detail)

    def test_a_car_with_no_mapping_file_is_a_warning(self):
        report = sf.check_show_folder(self.build([1, 2], mappings=[1]))
        findings = self.find(report, "no-mapping-for-car")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sf.WARNING)
        self.assertIn("cross_vehicle_mapping_2.xmap", findings[0].summary)

    def test_the_car_count_is_reported(self):
        report = sf.check_show_folder(self.build([1, 2, 3, 4, 5, 6]))
        findings = self.find(report, "cross-vehicle-cars")

        self.assertEqual(len(findings), 1)
        self.assertIn("6 cars", findings[0].summary)

    def test_a_single_car_folder_is_not_checked_this_way(self):
        report = sf.check_show_folder(self.builder.show_folder(cars=1))
        found = self.codes(report)
        for code in ("cars-do-not-match", "car-on-wrong-controller",
                     "no-mapping-for-car", "cross-vehicle-cars"):
            self.assertNotIn(code, found)

    def test_the_shipped_cross_vehicle_folder_is_consistent(self):
        import tempfile
        import zipfile

        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(os.path.join(
                    REPO_ROOT,
                    "xlights/tesla_xlights_cross_vehicle_folder.zip")) as z:
                z.extractall(tmp)
            report = sf.check_show_folder(
                os.path.join(tmp, "tesla_xlights_cross_vehicle_folder"))

        self.assertEqual(report.counts()[sf.ERROR], 0)
        self.assertEqual(report.counts()[sf.WARNING], 0)
        self.assertEqual(report.cars, 5)


class AudioTests(ShowFolderTestCase):
    def test_a_format_xlights_never_lists_is_a_warning(self):
        folder = self.builder.show_folder()
        self.builder.audio(folder, "my song.m4a")
        report = sf.check_show_folder(folder)

        findings = self.find(report, "audio-format-not-listed")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sf.WARNING)
        self.assertIn("my song.m4a", findings[0].detail)

    def test_every_unlisted_format_is_caught(self):
        folder = self.builder.show_folder()
        for extension in sf.UNLISTED_AUDIO:
            self.builder.audio(folder, "track" + extension)
        report = sf.check_show_folder(folder)

        unlisted = [a for a in report.audio if not a.listed_by_xlights]
        self.assertEqual(len(unlisted), len(sf.UNLISTED_AUDIO))

    def test_a_playable_file_is_listed_and_the_filter_is_explained(self):
        folder = self.builder.show_folder()
        self.builder.audio(folder, "lightshow.wav")
        report = sf.check_show_folder(folder)

        findings = self.find(report, "audio-file-type-filter")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sf.INFO)
        # The dropdown from images/wav_hidden.png.
        self.assertIn(sf.AUDIO_FILE_TYPE, findings[0].detail)

    def test_the_wrong_sample_rate_is_a_warning(self):
        folder = self.builder.show_folder()
        self.builder.audio(folder, "lightshow.wav", sample_rate=48000)
        report = sf.check_show_folder(folder)

        findings = self.find(report, "audio-sample-rate")
        self.assertEqual(len(findings), 1)
        self.assertIn("48000", findings[0].summary)

    def test_44100_is_not_flagged(self):
        folder = self.builder.show_folder()
        self.builder.audio(folder, "lightshow.wav", sample_rate=44100)
        self.assertNotIn("audio-sample-rate",
                         self.codes(sf.check_show_folder(folder)))

    def test_an_empty_folder_says_where_the_audio_is_not(self):
        report = sf.check_show_folder(self.builder.show_folder())

        findings = self.find(report, "no-audio-here")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, sf.INFO)

    def test_unrelated_files_are_ignored(self):
        folder = self.builder.show_folder()
        with open(os.path.join(folder, "notes.txt"), "w") as handle:
            handle.write("x")
        self.assertEqual(sf.check_show_folder(folder).audio, [])


class ShippedFolderTests(unittest.TestCase):
    """The folders this repository actually distributes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def extract(self, archive):
        target = os.path.join(self._tmp.name, os.path.basename(archive))
        with zipfile.ZipFile(os.path.join(REPO_ROOT, archive)) as bundle:
            bundle.extractall(target)
        return target

    def test_the_project_folder_extracts_to_something_xlights_can_use(self):
        parent = self.extract("xlights/tesla_xlights_show_folder.zip")
        report = sf.check_show_folder(
            os.path.join(parent, "tesla_xlights_show_folder"))

        self.assertTrue(report.is_show_folder)
        self.assertEqual(report.counts()[sf.ERROR], 0)
        self.assertEqual(report.cars, 1)
        self.assertGreater(report.models, 50)

    def test_the_cross_vehicle_folder_is_recognised_as_five_cars(self):
        parent = self.extract(
            "xlights/tesla_xlights_cross_vehicle_folder.zip")
        report = sf.check_show_folder(
            os.path.join(parent, "tesla_xlights_cross_vehicle_folder"))

        self.assertEqual(report.cars, 5)
        self.assertTrue([f for f in report.findings
                         if f.code == "cross-vehicle-folder"])

    def test_pointing_at_the_extraction_parent_is_guided_down(self):
        parent = self.extract("xlights/tesla_xlights_show_folder.zip")
        report = sf.check_show_folder(parent)

        self.assertTrue([f for f in report.findings
                         if f.code == "folder-one-level-up"])


class ReportingTests(ShowFolderTestCase):
    def test_a_good_folder_says_what_to_do_with_it(self):
        folder = self.builder.show_folder()
        self.builder.audio(folder, "lightshow.wav")
        text = sf.render_report(sf.check_show_folder(folder), verbose=False)

        self.assertIn("model(s)", text)
        self.assertIn("File > Select Show Folder", text)

    def test_notes_are_hidden_unless_verbose(self):
        report = sf.check_show_folder(self.builder.show_folder())

        self.assertNotIn("no-audio-here", sf.render_report(report, False))
        self.assertIn("no-audio-here", sf.render_report(report, True))

    def test_the_report_serialises_to_json(self):
        folder = self.builder.show_folder(models=4)
        self.builder.audio(folder, "song.m4a")
        payload = json.loads(json.dumps(
            sf.check_show_folder(folder).as_dict()))

        self.assertEqual(payload["models"], 4)
        self.assertFalse(payload["audio"][0]["listed_by_xlights"])


class CommandLineTests(ShowFolderTestCase):
    def run_main(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        original = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout, stderr
        try:
            code = sf.main(list(argv))
        finally:
            sys.stdout, sys.stderr = original
        return code, stdout.getvalue(), stderr.getvalue()

    def test_a_good_folder_exits_zero(self):
        code, out, _ = self.run_main(self.builder.show_folder())

        self.assertEqual(code, 0)
        self.assertIn("Select Show Folder", out)

    def test_a_wrong_folder_exits_one(self):
        os.makedirs(os.path.join(self.tmpdir, "photos"))
        self.assertEqual(self.run_main(self.tmpdir)[0], 1)

    def test_a_warning_only_fails_under_strict(self):
        folder = self.builder.show_folder()
        self.builder.audio(folder, "song.m4a")

        self.assertEqual(self.run_main(folder)[0], 0)
        self.assertEqual(self.run_main(folder, "--strict")[0], 1)

    def test_a_missing_path_exits_two(self):
        code, _, err = self.run_main(os.path.join(self.tmpdir, "nope"))

        self.assertEqual(code, 2)
        self.assertIn("nope", err)

    def test_json_output_parses(self):
        code, out, _ = self.run_main(self.builder.show_folder(), "--json")

        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["is_show_folder"])


if __name__ == "__main__":
    unittest.main()
