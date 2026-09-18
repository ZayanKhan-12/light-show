"""Tests for tools/usb_check.py.

The scenarios named "issue 48" reproduce the layouts owners reported in
https://github.com/teslamotors/light-show/issues/48 -- shows in subfolders, a
mis-cased folder, and audio whose name does not match its sequence -- and
assert the tool names the mistake instead of silently listing nothing.
"""

import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import wave

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import usb_check as uc  # noqa: E402


HEADER_BYTES = 32


def build_fseq_bytes(frames=100, channel_count=48, step_time=20,
                     magic=b"PSEQ", compression=0, major=2, minor=0):
    """Assemble a V2 uncompressed .fseq image, as validator.py expects one."""
    header = bytearray(HEADER_BYTES)
    header[0:4] = magic
    struct.pack_into("<H", header, 4, HEADER_BYTES)
    header[6] = minor
    header[7] = major
    struct.pack_into("<IIB", header, 10, channel_count, frames, step_time)
    header[20] = compression
    return bytes(header) + bytes(channel_count * frames)


def build_mp3_bytes(sample_rate=44100, frames=None, seconds=2.0,
                    bitrate_kbps=128, id3=False):
    """Assemble an MPEG 1 Layer III stream header, optionally with Xing.

    Only the header matters -- the tool reads the sample rate and length from
    it and never decodes audio.
    """
    rate_index = {44100: 0, 48000: 1, 32000: 2}[sample_rate]
    bitrate_index = {128: 9, 192: 11}[bitrate_kbps]
    header = bytes([
        0xFF,
        0xFB,                                   # MPEG 1, Layer III
        (bitrate_index << 4) | (rate_index << 2),
        0x00,                                   # stereo
    ])
    body = bytearray(header)
    if frames is not None:
        body.extend(bytes(32))                  # MPEG 1 stereo side info
        body.extend(b"Xing")
        body.extend(struct.pack(">I", 0x01))    # frame-count flag
        body.extend(struct.pack(">I", frames))
    padding = int(seconds * bitrate_kbps * 1000 / 8)
    body.extend(bytes(max(0, padding - len(body))))
    if id3:
        size = 64
        tag = bytearray(b"ID3\x03\x00\x00")
        tag.extend(bytes([0, 0, 0, size]))      # syncsafe size
        tag.extend(bytes(size))
        return bytes(tag) + bytes(body)
    return bytes(body)


def write_wav(path, sample_rate=44100, seconds=1.0, channels=2):
    with wave.open(path, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(int(sample_rate * seconds) * channels * 2))


class DriveBuilder:
    """A temporary folder shaped like a light show USB drive."""

    def __init__(self, tmpdir, show_folder=uc.SHOW_FOLDER):
        self.root = tmpdir
        self.show_folder = os.path.join(tmpdir, show_folder) \
            if show_folder else tmpdir
        if show_folder:
            os.makedirs(self.show_folder, exist_ok=True)

    def add_show(self, name, audio="wav", frames=100, step_time=20,
                 sample_rate=44100, audio_seconds=2.0, audio_name=None):
        self.write_fseq(name, frames=frames, step_time=step_time)
        if audio:
            self.write_audio(audio_name or name, kind=audio,
                             sample_rate=sample_rate, seconds=audio_seconds)
        return self

    def write_fseq(self, name, **kwargs):
        path = os.path.join(self.show_folder, name + ".fseq")
        with open(path, "wb") as handle:
            handle.write(build_fseq_bytes(**kwargs))
        return path

    def write_audio(self, name, kind="wav", sample_rate=44100, seconds=2.0):
        path = os.path.join(self.show_folder, "{}.{}".format(name, kind))
        if kind == "wav":
            write_wav(path, sample_rate=sample_rate, seconds=seconds)
        else:
            with open(path, "wb") as handle:
                handle.write(build_mp3_bytes(sample_rate=sample_rate,
                                             seconds=seconds))
        return path

    def write_file(self, relative, data=b""):
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def makedirs(self, relative):
        path = os.path.join(self.root, relative)
        os.makedirs(path, exist_ok=True)
        return path


class UsbCheckTestCase(unittest.TestCase):
    """Shared helpers.  Filesystem detection is stubbed unless a test wants
    it, so that the result does not depend on where the tests are run."""

    filesystem = "exfat"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name
        original = uc.detect_filesystem
        uc.detect_filesystem = lambda path: self.filesystem
        self.addCleanup(setattr, uc, "detect_filesystem", original)

    def drive(self, show_folder=uc.SHOW_FOLDER):
        return DriveBuilder(self.tmpdir, show_folder)

    def codes(self, report):
        return {f.code for f in report.all_findings()}

    def assertCode(self, report, code):
        self.assertIn(code, self.codes(report))

    def assertNoCode(self, report, code):
        self.assertNotIn(code, self.codes(report))


class MultiShowDriveTests(UsbCheckTestCase):
    """Issue 48: several shows side by side in one LightShow folder."""

    def test_lists_every_paired_show(self):
        drive = self.drive()
        for name in ("darude-sandstorm", "nz-lightshow-2023",
                     "blue-da-ba-dee-by-eiffel-65"):
            drive.add_show(name)
        report = uc.check_drive(self.tmpdir)

        self.assertEqual(
            [show.name for show in report.playable_shows],
            ["blue-da-ba-dee-by-eiffel-65", "darude-sandstorm",
             "nz-lightshow-2023"])
        self.assertEqual(report.counts()[uc.ERROR], 0)

    def test_reports_duration_of_each_show(self):
        drive = self.drive()
        drive.add_show("one", frames=5500, step_time=20)   # 1 min 50 sec
        report = uc.check_drive(self.tmpdir)

        show = report.playable_shows[0]
        self.assertEqual(show.duration_ms, 110000)
        self.assertEqual(uc._format_duration(show.duration_ms),
                         "1 min 50 sec")

    def test_accepts_being_pointed_at_the_show_folder(self):
        drive = self.drive()
        drive.add_show("one")
        report = uc.check_drive(drive.show_folder)

        self.assertEqual(report.show_folder, drive.show_folder)
        self.assertEqual(len(report.playable_shows), 1)

    def test_mp3_and_wav_shows_both_count(self):
        drive = self.drive()
        drive.add_show("wav-show", audio="wav")
        drive.add_show("mp3-show", audio="mp3")
        report = uc.check_drive(self.tmpdir)

        self.assertEqual(len(report.playable_shows), 2)


class PairingTests(UsbCheckTestCase):
    def test_fseq_without_audio_is_not_offered(self):
        drive = self.drive()
        drive.add_show("good")
        drive.write_fseq("lonely")
        report = uc.check_drive(self.tmpdir)

        self.assertEqual([s.name for s in report.playable_shows], ["good"])
        self.assertCode(report, "AUDIO_MISSING")

    def test_name_mismatch_is_distinguished_from_missing_audio(self):
        """Issue 48: `Show1.fseq` beside `show1.wav` is a rename, not a
        missing file, and deserves the more specific message."""
        drive = self.drive()
        drive.write_fseq("Show1")
        drive.write_audio("show1")
        report = uc.check_drive(self.tmpdir)

        self.assertCode(report, "AUDIO_NAME_MISMATCH")
        self.assertNoCode(report, "AUDIO_MISSING")

    def test_audio_without_a_sequence_is_reported(self):
        drive = self.drive()
        drive.add_show("good")
        drive.write_audio("just-music", kind="mp3")
        report = uc.check_drive(self.tmpdir)

        self.assertCode(report, "AUDIO_WITHOUT_SHOW")
        self.assertEqual(report.counts()[uc.ERROR], 0)

    def test_both_wav_and_mp3_is_ambiguous_but_playable(self):
        drive = self.drive()
        drive.add_show("two-tracks", audio="wav")
        drive.write_audio("two-tracks", kind="mp3")
        report = uc.check_drive(self.tmpdir)

        self.assertCode(report, "AUDIO_AMBIGUOUS")
        show = report.playable_shows[0]
        # The README recommends .wav, so that is the file described.
        self.assertTrue(show.audio.path.endswith(".wav"))

    def test_names_differing_only_by_case_are_flagged(self):
        # Built directly: a case-insensitive filesystem cannot hold both.
        findings = uc._check_case_collisions({"Show": "a", "show": "b"})
        self.assertEqual([f.code for f in findings], ["NAME_COLLISION"])
        self.assertEqual(findings[0].severity, uc.WARNING)

    def test_no_collision_for_distinct_names(self):
        self.assertEqual(uc._check_case_collisions({"a": "x", "b": "y"}), [])


class ShowFolderLayoutTests(UsbCheckTestCase):
    def test_missing_show_folder(self):
        report = uc.check_drive(self.tmpdir)
        self.assertCode(report, "SHOW_FOLDER_MISSING")
        self.assertIsNone(report.show_folder)

    def test_mis_cased_show_folder(self):
        """Issue 48: the folder name is case sensitive."""
        drive = self.drive(show_folder="lightshow")
        drive.add_show("one")
        report = uc.check_drive(self.tmpdir)

        self.assertCode(report, "SHOW_FOLDER_CASE")
        self.assertIsNone(report.show_folder)

    def test_show_folder_below_the_base_level(self):
        os.makedirs(os.path.join(self.tmpdir, "usb", uc.SHOW_FOLDER))
        report = uc.check_drive(self.tmpdir)

        self.assertCode(report, "SHOW_FOLDER_NOT_AT_BASE")

    def test_shows_in_subfolders_are_not_read(self):
        """Issue 48: subfolders per show were the first thing owners tried."""
        drive = self.drive()
        nested = DriveBuilder(drive.show_folder, "show1")
        nested.add_show("lightshow")
        report = uc.check_drive(self.tmpdir)

        self.assertCode(report, "SHOWS_IN_SUBFOLDER")
        self.assertEqual(report.playable_shows, [])

    def test_empty_subfolder_is_not_reported_as_a_show_folder(self):
        drive = self.drive()
        drive.add_show("one")
        os.makedirs(os.path.join(drive.show_folder, "notes"))
        report = uc.check_drive(self.tmpdir)

        self.assertNoCode(report, "SHOWS_IN_SUBFOLDER")

    def test_empty_show_folder(self):
        self.drive()
        report = uc.check_drive(self.tmpdir)
        self.assertCode(report, "NO_SHOWS")

    def test_authoring_files_are_only_a_note(self):
        drive = self.drive()
        drive.add_show("one")
        with open(os.path.join(drive.show_folder, "one.xsq"), "w") as handle:
            handle.write("<xsequence/>")
        report = uc.check_drive(self.tmpdir)

        extra = [f for f in report.all_findings() if f.code == "EXTRA_FILES"]
        self.assertEqual(len(extra), 1)
        self.assertEqual(extra[0].severity, uc.INFO)

    def test_macos_sidecar_files_are_reported_not_treated_as_shows(self):
        drive = self.drive()
        drive.add_show("one")
        with open(os.path.join(drive.show_folder, "._one.fseq"), "wb") as h:
            h.write(b"\x00\x05\x16\x07")
        report = uc.check_drive(self.tmpdir)

        self.assertCode(report, "MACOS_SIDECAR_FILES")
        self.assertEqual([s.name for s in report.shows], ["one"])


class DriveLevelTests(UsbCheckTestCase):
    def test_teslacam_folder_blocks_the_drive(self):
        drive = self.drive()
        drive.add_show("one")
        drive.makedirs("TeslaCam")
        report = uc.check_drive(self.tmpdir)

        self.assertCode(report, "TESLACAM_PRESENT")
        self.assertEqual(report.counts()[uc.ERROR], 1)

    def test_teslacam_is_matched_regardless_of_case(self):
        drive = self.drive()
        drive.add_show("one")
        drive.makedirs("teslacam")
        report = uc.check_drive(self.tmpdir)

        self.assertCode(report, "TESLACAM_PRESENT")

    def test_teslacam_found_when_pointed_at_the_show_folder(self):
        drive = self.drive()
        drive.add_show("one")
        drive.makedirs("TeslaCam")
        report = uc.check_drive(drive.show_folder)

        self.assertCode(report, "TESLACAM_PRESENT")

    def test_the_teslacam_advice_offers_the_partition_route(self):
        """Issue 111: owners keep both on one drive by splitting it."""
        drive = self.drive()
        drive.add_show("one")
        drive.makedirs("TeslaCam")
        finding = [f for f in uc.check_drive(self.tmpdir).findings
                   if f.code == "TESLACAM_PRESENT"][0]

        self.assertIn("partitions", finding.detail)
        self.assertIn("volume", finding.detail)

    def test_a_teslacam_folder_on_another_volume_is_not_this_drive(self):
        """The check only ever looks at the volume it was given.

        That is what makes the partition layout work: TeslaCam beside the
        LightShow folder is a problem, TeslaCam on a different volume is not
        this tool's business.
        """
        drive = self.drive()
        drive.add_show("one")
        sibling = os.path.join(os.path.dirname(self.tmpdir), "other-volume")
        os.makedirs(os.path.join(sibling, "TeslaCam"), exist_ok=True)
        self.addCleanup(shutil.rmtree, sibling, True)

        self.assertNoCode(uc.check_drive(self.tmpdir), "TESLACAM_PRESENT")

    def test_update_like_files_are_a_warning_not_an_error(self):
        drive = self.drive()
        drive.add_show("one")
        drive.write_file("firmware.tar", b"\x00")
        report = uc.check_drive(self.tmpdir)

        findings = [f for f in report.findings
                    if f.code == "POSSIBLE_UPDATE_FILES"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, uc.WARNING)

    def test_ordinary_files_at_the_base_are_not_flagged(self):
        drive = self.drive()
        drive.add_show("one")
        drive.write_file("readme.txt", b"hello")
        report = uc.check_drive(self.tmpdir)

        self.assertNoCode(report, "POSSIBLE_UPDATE_FILES")


class FilesystemTests(UsbCheckTestCase):
    def test_ntfs_is_rejected(self):
        self.filesystem = "ntfs"
        drive = self.drive()
        drive.add_show("one")
        report = uc.check_drive(self.tmpdir)

        self.assertCode(report, "FILESYSTEM_UNSUPPORTED")
        self.assertEqual(report.counts()[uc.ERROR], 1)

    def test_exfat_is_accepted(self):
        findings = uc.check_filesystem("exfat", "/Volumes/USB")
        self.assertEqual([f.code for f in findings], ["FILESYSTEM_OK"])
        self.assertEqual(findings[0].severity, uc.INFO)

    def test_unknown_filesystem_is_only_a_note(self):
        findings = uc.check_filesystem(None, "/tmp/drive")
        self.assertEqual([f.code for f in findings], ["FILESYSTEM_UNKNOWN"])
        self.assertEqual(findings[0].severity, uc.INFO)

    def test_unrecognised_filesystem_is_a_warning(self):
        findings = uc.check_filesystem("apfs", "/Volumes/USB")
        self.assertEqual([f.code for f in findings],
                         ["FILESYSTEM_UNRECOGNISED"])
        self.assertEqual(findings[0].severity, uc.WARNING)

    def test_mount_output_is_parsed(self):
        output = (
            "/dev/disk1s5s1 on / (apfs, sealed, local, read-only)\n"
            "/dev/disk4s1 on /Volumes/LIGHTSHOW (exfat, local, nodev)\n")
        self.assertEqual(
            uc._detect_filesystem_mount("/Volumes/LIGHTSHOW/LightShow",
                                        output),
            "exfat")
        # The longest matching mount point wins, not the first.
        self.assertEqual(uc._detect_filesystem_mount("/etc", output), "apfs")

    def test_mount_output_without_a_match(self):
        self.assertIsNone(uc._detect_filesystem_mount("/Volumes/X", ""))

    def test_detect_filesystem_never_raises(self):
        # The real detector must stay best-effort on any platform.
        original = uc.detect_filesystem
        uc.detect_filesystem = original
        self.assertIn(type(original(self.tmpdir)), (str, type(None)))


class SequenceValidationTests(UsbCheckTestCase):
    def test_invalid_fseq_is_rejected_with_the_validator_message(self):
        drive = self.drive()
        drive.write_audio("broken")
        with open(os.path.join(drive.show_folder, "broken.fseq"), "wb") as h:
            h.write(build_fseq_bytes(magic=b"NOPE"))
        report = uc.check_drive(self.tmpdir)

        findings = [f for f in report.all_findings()
                    if f.code == "FSEQ_INVALID"]
        self.assertEqual(len(findings), 1)
        self.assertIn("FSEQ v2.0", findings[0].detail)
        self.assertEqual(report.playable_shows, [])

    def test_wrong_channel_count_is_rejected(self):
        drive = self.drive()
        drive.write_audio("wide")
        with open(os.path.join(drive.show_folder, "wide.fseq"), "wb") as h:
            h.write(build_fseq_bytes(channel_count=64))
        report = uc.check_drive(self.tmpdir)

        self.assertCode(report, "FSEQ_INVALID")

    def test_truncated_fseq_is_reported_not_raised(self):
        drive = self.drive()
        drive.write_audio("stub")
        with open(os.path.join(drive.show_folder, "stub.fseq"), "wb") as h:
            h.write(b"PSEQ")
        report = uc.check_drive(self.tmpdir)

        self.assertTrue(
            self.codes(report) & {"FSEQ_INVALID", "FSEQ_UNREADABLE"})

    def test_200_channel_show_is_accepted(self):
        drive = self.drive()
        drive.add_show("cybertruck", frames=10)
        with open(os.path.join(drive.show_folder, "cybertruck.fseq"),
                  "wb") as handle:
            handle.write(build_fseq_bytes(frames=10, channel_count=200))
        report = uc.check_drive(self.tmpdir)

        self.assertEqual(len(report.playable_shows), 1)


class AudioHeaderTests(UsbCheckTestCase):
    def test_wav_sample_rate_and_duration(self):
        path = os.path.join(self.tmpdir, "a.wav")
        write_wav(path, sample_rate=44100, seconds=2.5)
        audio = uc.read_audio(path)

        self.assertEqual(audio.sample_rate, 44100)
        self.assertAlmostEqual(audio.duration_ms, 2500, delta=20)
        self.assertFalse(audio.estimated)
        self.assertIsNone(audio.error)

    def test_48khz_wav_is_flagged(self):
        drive = self.drive()
        drive.add_show("fast", sample_rate=48000)
        report = uc.check_drive(self.tmpdir)

        findings = [f for f in report.all_findings()
                    if f.code == "AUDIO_SAMPLE_RATE"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, uc.WARNING)
        # A wrong sample rate still plays, so the show is still listed.
        self.assertEqual(len(report.playable_shows), 1)

    def test_44khz_wav_is_not_flagged(self):
        drive = self.drive()
        drive.add_show("fine", sample_rate=44100)
        report = uc.check_drive(self.tmpdir)

        self.assertNoCode(report, "AUDIO_SAMPLE_RATE")

    def test_mp3_sample_rate_from_frame_header(self):
        path = os.path.join(self.tmpdir, "a.mp3")
        with open(path, "wb") as handle:
            handle.write(build_mp3_bytes(sample_rate=48000))
        audio = uc.read_audio(path)

        self.assertEqual(audio.sample_rate, 48000)
        self.assertTrue(audio.estimated)

    def test_mp3_behind_an_id3_tag(self):
        path = os.path.join(self.tmpdir, "tagged.mp3")
        with open(path, "wb") as handle:
            handle.write(build_mp3_bytes(sample_rate=44100, id3=True))
        audio = uc.read_audio(path)

        self.assertEqual(audio.sample_rate, 44100)

    def test_mp3_duration_from_xing_header(self):
        path = os.path.join(self.tmpdir, "xing.mp3")
        with open(path, "wb") as handle:
            # 1000 frames x 1152 samples at 44100 Hz is about 26 seconds.
            handle.write(build_mp3_bytes(frames=1000, seconds=30))
        audio = uc.read_audio(path)

        self.assertAlmostEqual(audio.duration_ms, 26122, delta=50)

    def test_mp3_duration_falls_back_to_a_bitrate_estimate(self):
        path = os.path.join(self.tmpdir, "cbr.mp3")
        with open(path, "wb") as handle:
            handle.write(build_mp3_bytes(seconds=10, bitrate_kbps=128))
        audio = uc.read_audio(path)

        self.assertAlmostEqual(audio.duration_ms, 10000, delta=200)

    def test_unreadable_audio_is_a_warning_not_a_rejection(self):
        drive = self.drive()
        drive.write_fseq("odd")
        with open(os.path.join(drive.show_folder, "odd.wav"), "wb") as handle:
            handle.write(b"not a wav at all")
        report = uc.check_drive(self.tmpdir)

        self.assertCode(report, "AUDIO_UNREADABLE")
        self.assertEqual(len(report.playable_shows), 1)

    def test_length_mismatch_is_a_note(self):
        drive = self.drive()
        drive.add_show("short-audio", frames=5000, step_time=20,
                       audio_seconds=1.0)
        report = uc.check_drive(self.tmpdir)

        findings = [f for f in report.all_findings()
                    if f.code == "LENGTH_MISMATCH"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, uc.INFO)
        self.assertIn("sequence runs", findings[0].summary)

    def test_the_mismatch_names_the_symptom_it_causes(self):
        # Issue 78: a trimmed intro on one file is how the music ends up
        # running ahead of the lights.
        drive = self.drive()
        drive.add_show("short-audio", frames=5000, step_time=20,
                       audio_seconds=1.0)
        report = uc.check_drive(self.tmpdir)
        finding = [f for f in report.all_findings()
                   if f.code == "LENGTH_MISMATCH"][0]

        self.assertIn("ahead of the lights", finding.detail)

    def test_matching_lengths_produce_no_note(self):
        drive = self.drive()
        drive.add_show("matched", frames=100, step_time=20, audio_seconds=2.0)
        report = uc.check_drive(self.tmpdir)

        self.assertNoCode(report, "LENGTH_MISMATCH")


class ReportingTests(UsbCheckTestCase):
    def test_durations_are_formatted_like_the_car(self):
        self.assertEqual(uc._format_duration(110000), "1 min 50 sec")
        self.assertEqual(uc._format_duration(93000), "1 min 33 sec")
        self.assertEqual(uc._format_duration(9000), "9 sec")
        self.assertEqual(uc._format_duration(3723000), "1 hr 2 min 3 sec")
        self.assertEqual(uc._format_duration(None), "-")

    def test_text_report_lists_the_picker_and_the_reasons(self):
        drive = self.drive()
        drive.add_show("keeper")
        drive.write_fseq("dropped")
        report = uc.check_drive(self.tmpdir)
        text = uc.render_report(report, verbose=False)

        self.assertIn("The car will list 1 custom show:", text)
        self.assertIn("keeper", text)
        self.assertIn("1 show will not appear:", text)
        self.assertIn("AUDIO_MISSING", text)

    def test_clean_drive_says_so(self):
        drive = self.drive()
        drive.add_show("one")
        report = uc.check_drive(self.tmpdir)
        text = uc.render_report(report, verbose=False)

        self.assertIn("This drive is ready for the car.", text)

    def test_notes_are_hidden_unless_verbose(self):
        drive = self.drive()
        drive.add_show("one")
        drive.write_file(os.path.join(uc.SHOW_FOLDER, "one.xsq"), b"<x/>")
        report = uc.check_drive(self.tmpdir)

        self.assertNotIn("EXTRA_FILES",
                         uc.render_report(report, verbose=False))
        self.assertIn("EXTRA_FILES", uc.render_report(report, verbose=True))

    def test_report_serialises_to_json(self):
        drive = self.drive()
        drive.add_show("one")
        report = uc.check_drive(self.tmpdir)
        payload = json.loads(json.dumps(report.as_dict()))

        self.assertEqual(payload["playable_show_count"], 1)
        self.assertEqual(payload["shows"][0]["name"], "one")
        self.assertEqual(payload["counts"]["error"], 0)


class CommandLineTests(UsbCheckTestCase):
    def run_main(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        original = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout, stderr
        try:
            code = uc.main(list(argv))
        finally:
            sys.stdout, sys.stderr = original
        return code, stdout.getvalue(), stderr.getvalue()

    def test_clean_drive_exits_zero(self):
        drive = self.drive()
        drive.add_show("one")
        code, out, _ = self.run_main(self.tmpdir)

        self.assertEqual(code, 0)
        self.assertIn("The car will list 1 custom show", out)

    def test_errors_exit_one(self):
        drive = self.drive()
        drive.write_fseq("lonely")
        code, _, _ = self.run_main(self.tmpdir)

        self.assertEqual(code, 1)

    def test_warnings_only_exit_zero_unless_strict(self):
        drive = self.drive()
        drive.add_show("one")
        drive.write_audio("spare", kind="mp3")

        self.assertEqual(self.run_main(self.tmpdir)[0], 0)
        self.assertEqual(self.run_main(self.tmpdir, "--strict")[0], 1)

    def test_unreadable_path_exits_two(self):
        code, _, err = self.run_main(os.path.join(self.tmpdir, "nope"))

        self.assertEqual(code, 2)
        self.assertIn("nope", err)

    def test_json_flag_emits_parseable_json(self):
        drive = self.drive()
        drive.add_show("one")
        code, out, _ = self.run_main(self.tmpdir, "--json")

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["playable_show_count"], 1)


class VehicleSupportTests(UsbCheckTestCase):
    """Issue 52: the half of "my car will not play it" the drive cannot show."""

    def test_the_support_requirements_are_always_stated(self):
        drive = self.drive()
        drive.add_show("one")
        report = uc.check_drive(self.tmpdir)

        findings = [f for f in report.findings if f.code == "VEHICLE_SUPPORT"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, uc.INFO)
        self.assertIn("Model X (2021+)", findings[0].detail)

    def test_nothing_is_claimed_when_there_is_no_show_folder(self):
        report = uc.check_drive(self.tmpdir)
        self.assertNoCode(report, "VEHICLE_SUPPORT")

    def test_more_than_one_show_names_the_software_it_needs(self):
        drive = self.drive()
        drive.add_show("one")
        drive.add_show("two")
        report = uc.check_drive(self.tmpdir)

        findings = [f for f in report.findings
                    if f.code == "MULTI_SHOW_SOFTWARE"]
        self.assertEqual(len(findings), 1)
        self.assertIn(uc.MULTI_SHOW_SOFTWARE, findings[0].summary)

    def test_a_single_show_does_not(self):
        drive = self.drive()
        drive.add_show("only-one")
        report = uc.check_drive(self.tmpdir)

        self.assertNoCode(report, "MULTI_SHOW_SOFTWARE")

    def test_shows_that_will_not_play_do_not_count_towards_the_multi_note(self):
        drive = self.drive()
        drive.add_show("good")
        drive.write_fseq("no-audio")
        report = uc.check_drive(self.tmpdir)

        self.assertNoCode(report, "MULTI_SHOW_SOFTWARE")

    def test_the_notes_do_not_change_the_exit_code(self):
        drive = self.drive()
        drive.add_show("one")
        drive.add_show("two")
        report = uc.check_drive(self.tmpdir)

        self.assertEqual(report.counts()[uc.ERROR], 0)
        self.assertEqual(report.counts()[uc.WARNING], 0)


if __name__ == "__main__":
    unittest.main()
