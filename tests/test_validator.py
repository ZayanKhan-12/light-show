"""Tests for validator.py.

validator.py is the tool the README sends people to, and the one packaged as
validator-windows.exe, so its messages are the repository's front line. The
channel-count messages here answer
https://github.com/teslamotors/light-show/issues/65, where owners hit the
vehicle's "Incorrect number of channels" with nothing to tell them what it
meant.
"""

import datetime
import io
import os
import struct
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import validator  # noqa: E402


HEADER_BYTES = 32


def fseq(frames=100, channel_count=200, step_time=20, magic=b"PSEQ",
         compression=0, major=2, minor=0, start=HEADER_BYTES, body=True):
    header = bytearray(HEADER_BYTES)
    header[0:4] = magic
    struct.pack_into("<H", header, 4, start)
    header[6] = minor
    header[7] = major
    struct.pack_into("<IIB", header, 10, channel_count, frames, step_time)
    header[20] = compression
    payload = bytes(channel_count * frames) if body else b""
    return io.BytesIO(bytes(header) + payload)


class AcceptedFilesTests(unittest.TestCase):
    def test_a_200_channel_show_is_accepted(self):
        results = validator.validate(fseq(channel_count=200))

        self.assertEqual(results.frame_count, 100)
        self.assertEqual(results.step_time, 20)
        self.assertEqual(results.duration_s, 2.0)

    def test_a_48_channel_show_is_still_accepted(self):
        # Shows exported before the 2023 update must keep validating.
        self.assertEqual(
            validator.validate(fseq(channel_count=48)).frame_count, 100)

    def test_the_documented_frame_intervals_are_accepted(self):
        # README.md: any value between 15 ms and 100 ms is supported.
        for step_time in (15, 20, 25, 50, 100):
            self.assertEqual(
                validator.validate(fseq(step_time=step_time)).step_time,
                step_time)


class ChannelCountTests(unittest.TestCase):
    """Issue 65: the vehicle says "Incorrect number of channels" and stops."""

    def message_for(self, channel_count):
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate(fseq(channel_count=channel_count))
        return str(caught.exception)

    def test_a_wrong_count_is_rejected(self):
        self.assertIn("Expected 48 or 200 channels, got 64",
                      self.message_for(64))

    def test_every_message_names_the_error_the_owner_saw(self):
        for channel_count in (1, 47, 64, 199, 1000):
            self.assertIn(validator.VEHICLE_ERROR,
                          self.message_for(channel_count))

    def test_a_multiple_of_200_is_explained_as_a_cross_vehicle_export(self):
        message = self.message_for(1000)

        self.assertIn("5 x 200 channels", message)
        self.assertIn("cross-vehicle", message)
        self.assertIn("cross-vehicle-shows/README.md", message)

    def test_the_car_count_is_worked_out_from_the_file(self):
        self.assertIn("2 x 200 channels", self.message_for(400))
        self.assertIn("3 x 200 channels", self.message_for(600))

    def test_any_other_count_points_at_the_show_folder(self):
        message = self.message_for(64)

        self.assertIn("tesla_xlights_show_folder", message)
        self.assertNotIn("cross-vehicle sequence", message)

    def test_a_single_car_count_is_not_called_cross_vehicle(self):
        # 200 is valid, so the only way to reach describe_channel_count with
        # one car's worth is a direct call; it must not claim 1 x 200.
        self.assertNotIn("1 x 200",
                         validator.describe_channel_count(200))

    def test_describe_channel_count_is_usable_on_its_own(self):
        # usb_check.py and multi_car_check.py surface these messages.
        self.assertTrue(validator.describe_channel_count(1000))


class CrossVehicleFolderTests(unittest.TestCase):
    """Keep the explanation tied to the show folder it describes."""

    def channels_in(self, archive, member):
        with zipfile.ZipFile(os.path.join(REPO_ROOT, archive)) as bundle:
            root = ET.fromstring(bundle.read(member))
        return sum(int(network.get("MaxChannels", 0))
                   for controller in root.findall("Controller")
                   for network in controller.findall("network"))

    def test_the_project_folder_exports_one_car(self):
        self.assertEqual(
            self.channels_in("xlights/tesla_xlights_show_folder.zip",
                             "tesla_xlights_show_folder/xlights_networks.xml"),
            validator.CHANNELS_PER_CAR)

    def test_the_cross_vehicle_folder_exports_five_cars(self):
        """The number the error message explains.

        If this changes, describe_channel_count() is describing a folder that
        no longer exists.
        """
        total = self.channels_in(
            "xlights/tesla_xlights_cross_vehicle_folder.zip",
            "tesla_xlights_cross_vehicle_folder/xlights_networks.xml")

        self.assertEqual(total, 5 * validator.CHANNELS_PER_CAR)
        self.assertIn("5 x 200 channels",
                      validator.describe_channel_count(total))


class RejectedFilesTests(unittest.TestCase):
    def assertRejected(self, stream, fragment):
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate(stream)
        self.assertIn(fragment, str(caught.exception))

    def test_a_file_that_is_not_an_fseq(self):
        self.assertRejected(fseq(magic=b"NOPE"), "Unknown file format")

    def test_a_header_that_is_too_short(self):
        self.assertRejected(fseq(start=16), "Unknown file format")

    def test_a_show_with_no_frames(self):
        self.assertRejected(fseq(frames=0), "Unknown file format")

    def test_a_frame_interval_below_15ms(self):
        self.assertRejected(fseq(step_time=14), "Unknown file format")

    def test_a_compressed_file(self):
        self.assertRejected(fseq(compression=1), "V2 Uncompressed")

    def test_a_show_longer_than_four_hours(self):
        # 4 hours at 100 ms per frame is 144000 frames; go one over.
        stream = fseq(frames=144001, step_time=100, channel_count=48,
                      body=False)
        self.assertRejected(stream, "less than 4 hours")

    def test_exactly_four_hours_is_accepted(self):
        results = validator.validate(
            fseq(frames=144000, step_time=100, channel_count=48, body=False))
        self.assertEqual(
            datetime.timedelta(seconds=results.duration_s),
            datetime.timedelta(hours=4))


class VersionWarningTests(unittest.TestCase):
    def capture(self, stream):
        stdout = io.StringIO()
        original = sys.stdout
        sys.stdout = stdout
        try:
            results = validator.validate(stream)
        finally:
            sys.stdout = original
        return results, stdout.getvalue()

    def test_versions_2_0_and_2_2_are_quiet(self):
        for minor in (0, 2):
            _, output = self.capture(fseq(minor=minor))
            self.assertEqual(output, "")

    def test_an_unvalidated_version_warns_but_still_returns(self):
        results, output = self.capture(fseq(minor=1))

        self.assertEqual(results.frame_count, 100)
        self.assertIn("WARNING", output)
        self.assertIn("2.1", output)


class ShippedExampleTests(unittest.TestCase):
    def test_every_example_show_validates(self):
        examples = os.path.join(REPO_ROOT, "examples")
        seen = 0
        for current, _, files in os.walk(examples):
            for name in sorted(files):
                if not name.lower().endswith(".fseq"):
                    continue
                seen += 1
                with open(os.path.join(current, name), "rb") as handle:
                    results = validator.validate(handle)
                self.assertGreater(results.frame_count, 0)
        for name in sorted(os.listdir(examples)):
            if not name.endswith(".zip"):
                continue
            with zipfile.ZipFile(os.path.join(examples, name)) as bundle:
                for member in bundle.namelist():
                    if not member.lower().endswith(".fseq"):
                        continue
                    seen += 1
                    validator.validate(io.BytesIO(bundle.read(member)))
        self.assertGreater(seen, 0, "no example shows were found")


if __name__ == "__main__":
    unittest.main()
