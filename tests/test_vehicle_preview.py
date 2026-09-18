"""Tests for tools/vehicle_preview.py.

The scenarios named "issue 42" reproduce the two mismatches reported in
https://github.com/teslamotors/light-show/issues/42 and assert that the tool
explains each one on Model 3 while staying quiet on Model S, which is the
vehicle the xLights preview models.
"""

import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import vehicle_preview as vp  # noqa: E402


HEADER_BYTES = 32


def build_fseq_bytes(frames, channel_count=48, step_time=20,
                     magic=b"PSEQ", compression=0, major=2, minor=0,
                     payload=None):
    """Assemble a V2 uncompressed .fseq image for tests."""
    header = bytearray(HEADER_BYTES)
    header[0:4] = magic
    struct.pack_into("<H", header, 4, HEADER_BYTES)
    header[6] = minor
    header[7] = major
    struct.pack_into("<IIB", header, 10, channel_count, frames, step_time)
    header[20] = compression
    body = payload if payload is not None else bytes(channel_count * frames)
    return bytes(header) + body


def make_show(frame_count, events, channel_count=48, step_time=20):
    """Build a Show directly.

    `events` maps a 1-based channel to a list of (start_frame, length, value).
    """
    data = bytearray(frame_count * channel_count)
    for channel, spans in events.items():
        for start, length, value in spans:
            for frame in range(start, start + length):
                data[frame * channel_count + (channel - 1)] = value
    return vp.Show(channel_count, frame_count, step_time, bytes(data))


def codes(findings):
    return [f.code for f in findings]


def find(findings, code, channel=None):
    """Return the findings with this code, optionally touching a channel."""
    return [
        f for f in findings
        if f.code == code and (channel is None or channel in f.channels)
    ]


# Brightness bytes for the effects documented in README.md.
ON_INSTANT = 255        # 100%, "Turn on; Instant"
ON_500 = 178            # 70%,  "Turn on; 500 ms"
ON_2000 = 229           # 90%,  "Turn on; 2000 ms"
OFF_500 = 25            # 10%,  "Turn off; 500 ms"

LEFT_FRONT_TURN = 13
RIGHT_FRONT_TURN = 14
LEFT_CH4, LEFT_CH5, LEFT_CH6 = 7, 9, 11
RIGHT_CH4, RIGHT_CH5, RIGHT_CH6 = 8, 10, 12
LEFT_AUX_PARK, LEFT_SIDE_MARKER = 17, 19
LEFT_SIGNATURE = 5


class EffectEncodingTests(unittest.TestCase):
    def test_ramp_codes_round_trip_from_bytes(self):
        # Every documented effect percentage must survive the byte round trip,
        # otherwise the tool would silently misread real shows.
        for percent in vp.RAMP_CODES:
            raw = int(round(percent * 255.0 / 100.0))
            self.assertEqual(vp.to_percent(raw), percent,
                             "percent {} did not round trip".format(percent))

    def test_closure_codes_round_trip_from_bytes(self):
        for percent in vp.CLOSURE_CODES:
            raw = int(round(percent * 255.0 / 100.0))
            self.assertEqual(vp.to_percent(raw), percent)

    def test_on_threshold_matches_the_documented_50_percent_rule(self):
        self.assertFalse(127 > vp.ON_THRESHOLD)   # 49.8% is off
        self.assertTrue(128 > vp.ON_THRESHOLD)    # 50.2% is on


class ChannelMapTests(unittest.TestCase):
    def test_exterior_channel_numbers_are_contiguous_from_one(self):
        exterior = [c for c, (_, kind) in vp.CHANNELS.items()
                    if kind != vp.RGB]
        self.assertEqual(sorted(exterior), list(range(1, 47)))

    def test_interior_channels_are_a_separate_contiguous_block(self):
        """The cabin sits at 176-193, far above the exterior channels."""
        interior = [c for c, (_, kind) in vp.CHANNELS.items()
                    if kind == vp.RGB]
        self.assertEqual(sorted(interior), list(range(176, 194)))

    def test_channel_names_are_unique(self):
        names = [name for name, _ in vp.CHANNELS.values()]
        self.assertEqual(len(names), len(set(names)))

    def test_every_profile_only_names_known_channels(self):
        for profile in vp.VEHICLES.values():
            for channel in profile.kinds:
                self.assertIn(channel, vp.CHANNELS, profile.key)
            for group in profile.or_groups:
                for channel in group.channels:
                    self.assertIn(channel, vp.CHANNELS, profile.key)
            for follower, leader in profile.ramp_leaders.items():
                self.assertIn(follower, vp.CHANNELS, profile.key)
                self.assertIn(leader, vp.CHANNELS, profile.key)

    def test_ramp_leaders_all_point_at_a_channel_4(self):
        # README.md: Channel 4 defines the ramp duration for Channels 4-6.
        for profile in vp.VEHICLES.values():
            for leader in profile.ramp_leaders.values():
                self.assertIn(leader, (LEFT_CH4, RIGHT_CH4), profile.key)


class ReadFseqTests(unittest.TestCase):
    def _write(self, blob):
        handle = tempfile.NamedTemporaryFile(suffix=".fseq", delete=False)
        handle.write(blob)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_reads_a_well_formed_file(self):
        path = self._write(build_fseq_bytes(frames=10))
        show = vp.read_fseq(path)
        self.assertEqual(show.channel_count, 48)
        self.assertEqual(show.frame_count, 10)
        self.assertEqual(show.step_time_ms, 20)
        self.assertEqual(show.duration_ms, 200)

    def test_series_returns_one_channel_across_frames(self):
        show = make_show(4, {LEFT_FRONT_TURN: [(1, 2, ON_INSTANT)]})
        self.assertEqual(list(show.series(LEFT_FRONT_TURN)), [0, 255, 255, 0])

    def test_rejects_foreign_file(self):
        path = self._write(b"NOTAFSEQ" + bytes(64))
        with self.assertRaises(vp.ShowError):
            vp.read_fseq(path)

    def test_rejects_compressed_file(self):
        path = self._write(build_fseq_bytes(frames=4, compression=1))
        with self.assertRaises(vp.ShowError):
            vp.read_fseq(path)

    def test_rejects_unexpected_channel_count(self):
        path = self._write(build_fseq_bytes(frames=4, channel_count=64))
        with self.assertRaises(vp.ShowError):
            vp.read_fseq(path)

    def test_rejects_truncated_frame_data(self):
        blob = build_fseq_bytes(frames=10)
        path = self._write(blob[:HEADER_BYTES + 48 * 3])
        with self.assertRaises(vp.ShowError):
            vp.read_fseq(path)


class RunsTests(unittest.TestCase):
    def test_splits_a_series_into_constant_runs(self):
        runs = vp.runs_of([0, 0, 255, 255, 255, 0])
        self.assertEqual(
            [(r.value, r.start_frame, r.frames) for r in runs],
            [(0, 0, 2), (255, 2, 3), (0, 5, 1)],
        )

    def test_empty_series_has_no_runs(self):
        self.assertEqual(vp.runs_of([]), [])


class OrGroupTests(unittest.TestCase):
    def test_issue_42_channels_4_to_6_collapse_on_model_3(self):
        # The reporter sequenced Right Channel 4/5/6 independently and saw a
        # single lamp light up next to the turn signal.
        show = make_show(60, {
            RIGHT_CH4: [(0, 10, ON_INSTANT)],
            RIGHT_CH5: [(20, 10, ON_INSTANT)],
            RIGHT_CH6: [(40, 10, ON_INSTANT)],
        })
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        collapse = find(findings, "or-group-collapse", RIGHT_CH5)
        self.assertEqual(len(collapse), 1)
        self.assertIn("one output", collapse[0].detail)
        self.assertEqual(collapse[0].first_at_ms, 0)

    def test_issue_42_channels_4_to_6_are_independent_on_model_s(self):
        # Same sequence, no collapse reported: Model S drives each separately,
        # which is exactly why the preview looked right to the reporter.
        show = make_show(60, {
            RIGHT_CH4: [(0, 10, ON_INSTANT)],
            RIGHT_CH5: [(20, 10, ON_INSTANT)],
            RIGHT_CH6: [(40, 10, ON_INSTANT)],
        })
        findings = vp.analyze(show, vp.VEHICLES["models"])
        self.assertEqual(find(findings, "or-group-collapse", RIGHT_CH5), [])

    def test_model_3_merges_all_four_aux_park_and_side_marker_channels(self):
        show = make_show(40, {
            LEFT_AUX_PARK: [(0, 10, ON_INSTANT)],
            LEFT_SIDE_MARKER: [(20, 10, ON_INSTANT)],
        })
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        collapse = find(findings, "or-group-collapse", LEFT_AUX_PARK)
        self.assertEqual(len(collapse), 1)
        # All four channels share the single Model 3/Y output.
        self.assertEqual(collapse[0].channels, (17, 18, 19, 20))

    def test_interleaved_blinking_is_reported_as_a_solid_glow(self):
        # Channel 4 and 5 alternate with no shared gap, so the shared lamp
        # never goes out - README.md's "ord_channel_not_ok" case.
        spans_a = [(start, 10, ON_INSTANT) for start in range(0, 200, 20)]
        spans_b = [(start, 10, ON_INSTANT) for start in range(10, 200, 20)]
        show = make_show(200, {LEFT_CH4: spans_a, LEFT_CH5: spans_b})
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        solid = find(findings, "or-group-never-off", LEFT_CH4)
        self.assertEqual(len(solid), 1)
        self.assertEqual(solid[0].severity, vp.ERROR)

    def test_a_deliberately_solid_light_is_not_reported(self):
        # One member held on for the whole span: the continuous output is what
        # the author asked for, so this must not be flagged.
        show = make_show(200, {
            LEFT_CH4: [(0, 200, ON_INSTANT)],
            LEFT_CH5: [(50, 10, ON_INSTANT)],
        })
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        self.assertEqual(find(findings, "or-group-never-off"), [])

    def test_a_group_with_only_one_channel_used_does_not_collapse(self):
        # Nothing collapses when the rest of the group is empty: the single
        # channel simply drives the shared lamp on its own.
        show = make_show(60, {RIGHT_CH4: [(0, 10, ON_INSTANT)]})
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        self.assertEqual(find(findings, "or-group-collapse"), [])

    def test_two_channels_in_a_group_still_collapse(self):
        show = make_show(60, {
            RIGHT_CH4: [(0, 10, ON_INSTANT)],
            RIGHT_CH6: [(20, 10, ON_INSTANT)],
        })
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        self.assertEqual(len(find(findings, "or-group-collapse", RIGHT_CH4)), 1)

    def test_unused_group_produces_no_findings(self):
        show = make_show(50, {})
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        self.assertEqual(find(findings, "or-group-collapse"), [])
        self.assertEqual(find(findings, "or-group-never-off"), [])


class RampTests(unittest.TestCase):
    def test_issue_42_short_turn_signal_flash_is_an_error_on_model_3(self):
        # A two-frame "Turn on; 500 ms" flash: a crisp blink in the Model S
        # preview, almost invisible on a Model 3 where the channel ramps.
        show = make_show(50, {LEFT_FRONT_TURN: [(0, 2, ON_500)]})
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        short = find(findings, "ramp-too-short", LEFT_FRONT_TURN)
        self.assertEqual(len(short), 1)
        self.assertEqual(short[0].severity, vp.ERROR)
        self.assertIn("boolean on Model S", short[0].detail)

    def test_issue_42_short_turn_signal_flash_is_fine_on_model_s(self):
        show = make_show(50, {LEFT_FRONT_TURN: [(0, 2, ON_500)]})
        findings = vp.analyze(show, vp.VEHICLES["models"])
        self.assertEqual(find(findings, "ramp-too-short", LEFT_FRONT_TURN), [])
        # Model S reports the ignored ramp as a note instead.
        self.assertEqual(
            len(find(findings, "ramp-ignored", LEFT_FRONT_TURN)), 1)

    def test_signature_ramps_on_model_3_but_not_on_model_s(self):
        self.assertEqual(
            vp.kind_of(vp.VEHICLES["model3"], LEFT_SIGNATURE), vp.RAMPING)
        self.assertEqual(
            vp.kind_of(vp.VEHICLES["models"], LEFT_SIGNATURE), vp.BOOLEAN)

    def test_a_ramp_that_almost_completes_is_only_a_note(self):
        # 90% of the way to the setpoint is a rounding detail, not a defect.
        show = make_show(200, {LEFT_FRONT_TURN: [(0, 22, ON_500)]})
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        short = find(findings, "ramp-too-short", LEFT_FRONT_TURN)
        self.assertEqual(len(short), 1)
        self.assertEqual(short[0].severity, vp.INFO)

    def test_a_ramp_with_room_to_complete_is_not_reported(self):
        show = make_show(200, {LEFT_FRONT_TURN: [(0, 40, ON_500)]})
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        self.assertEqual(find(findings, "ramp-too-short", LEFT_FRONT_TURN), [])

    def test_instant_effects_never_report_a_truncated_ramp(self):
        show = make_show(50, {LEFT_FRONT_TURN: [(0, 1, ON_INSTANT)]})
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        self.assertEqual(find(findings, "ramp-too-short", LEFT_FRONT_TURN), [])

    def test_channel_5_ramping_without_channel_4_is_reported(self):
        # README.md: Channel 4 alone defines the ramp duration for 4-6.
        show = make_show(200, {LEFT_CH5: [(0, 150, ON_2000)]})
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        leader = find(findings, "ramp-leader-missing", LEFT_CH5)
        self.assertEqual(len(leader), 1)
        self.assertEqual(leader[0].channels, (LEFT_CH5, LEFT_CH4))

    def test_channel_5_ramping_with_channel_4_present_is_accepted(self):
        show = make_show(200, {
            LEFT_CH4: [(0, 150, OFF_500)],
            LEFT_CH5: [(0, 150, ON_2000)],
        })
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        self.assertEqual(find(findings, "ramp-leader-missing", LEFT_CH5), [])

    def test_ramp_leader_rule_applies_to_model_s_too(self):
        show = make_show(200, {LEFT_CH5: [(0, 150, ON_2000)]})
        findings = vp.analyze(show, vp.VEHICLES["models"])
        self.assertEqual(
            len(find(findings, "ramp-leader-missing", LEFT_CH5)), 1)


class HardwareTests(unittest.TestCase):
    def test_cybertruck_has_no_signature_lights(self):
        show = make_show(20, {LEFT_SIGNATURE: [(0, 10, ON_INSTANT)]})
        findings = vp.analyze(show, vp.VEHICLES["cybertruck"])
        absent = find(findings, "channel-not-present", LEFT_SIGNATURE)
        self.assertEqual(len(absent), 1)
        self.assertEqual(absent[0].severity, vp.INFO)

    def test_front_fog_is_optional_hardware_on_model_3(self):
        show = make_show(20, {15: [(0, 10, ON_INSTANT)]})
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        optional = find(findings, "channel-optional-hardware", 15)
        self.assertEqual(len(optional), 1)
        self.assertIn("Standard Range", optional[0].detail)

    def test_front_fog_is_standard_on_model_y(self):
        show = make_show(20, {15: [(0, 10, ON_INSTANT)]})
        findings = vp.analyze(show, vp.VEHICLES["modely"])
        self.assertEqual(find(findings, "channel-optional-hardware", 15), [])

    def test_untouched_channels_are_never_reported(self):
        show = make_show(20, {})
        for key in vp.VEHICLES:
            findings = vp.analyze(show, vp.VEHICLES[key])
            self.assertEqual(findings, [], key)


class ReportingTests(unittest.TestCase):
    def test_findings_are_ordered_by_severity(self):
        show = make_show(200, {
            LEFT_CH4: [(start, 10, ON_INSTANT) for start in range(0, 200, 20)],
            LEFT_CH5: [(start, 10, ON_INSTANT) for start in range(10, 200, 20)],
            LEFT_SIGNATURE: [(0, 2, ON_500)],
            15: [(0, 5, ON_INSTANT)],
        })
        findings = vp.analyze(show, vp.VEHICLES["model3"])
        ranks = [vp._SEVERITY_ORDER[f.severity] for f in findings]
        self.assertEqual(ranks, sorted(ranks))

    def test_finding_serialises_to_json_friendly_types(self):
        show = make_show(50, {LEFT_FRONT_TURN: [(0, 2, ON_500)]})
        finding = vp.analyze(show, vp.VEHICLES["model3"])[0].as_dict()
        self.assertEqual(
            set(finding),
            {"severity", "code", "summary", "detail", "channels",
             "first_at_ms", "occurrences"},
        )
        self.assertEqual(finding["channels"][0]["name"], "Left Front Turn")

    def test_report_names_every_requested_vehicle(self):
        show = make_show(50, {LEFT_FRONT_TURN: [(0, 2, ON_500)]})
        results = {k: vp.analyze(show, v) for k, v in vp.VEHICLES.items()}
        report = vp.render_report(show, results, verbose=True)
        for profile in vp.VEHICLES.values():
            self.assertIn(profile.label, report)

    def test_clean_show_is_reported_as_matching_the_preview(self):
        show = make_show(50, {LEFT_FRONT_TURN: [(0, 10, ON_INSTANT)]})
        results = {"models": vp.analyze(show, vp.VEHICLES["models"])}
        self.assertIn("renders the same way",
                      vp.render_report(show, results, verbose=False))


class CommandLineTests(unittest.TestCase):
    def _write_show(self, show):
        blob = build_fseq_bytes(
            frames=show.frame_count,
            channel_count=show.channel_count,
            step_time=show.step_time_ms,
            payload=show.data,
        )
        handle = tempfile.NamedTemporaryFile(suffix=".fseq", delete=False)
        handle.write(blob)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def _run(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        saved = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout, stderr
        try:
            code = vp.main(argv)
        finally:
            sys.stdout, sys.stderr = saved
        return code, stdout.getvalue(), stderr.getvalue()

    def test_exits_zero_for_a_show_with_findings(self):
        path = self._write_show(
            make_show(50, {LEFT_FRONT_TURN: [(0, 2, ON_500)]}))
        code, out, _ = self._run([path, "--vehicle", "model3"])
        self.assertEqual(code, 0)
        self.assertIn("ramp-too-short", out)

    def test_strict_exits_non_zero_when_something_is_reported(self):
        path = self._write_show(
            make_show(50, {LEFT_FRONT_TURN: [(0, 2, ON_500)]}))
        code, _, _ = self._run([path, "--vehicle", "model3", "--strict"])
        self.assertEqual(code, 1)

    def test_strict_exits_zero_for_a_clean_show(self):
        path = self._write_show(
            make_show(50, {LEFT_FRONT_TURN: [(0, 10, ON_INSTANT)]}))
        code, _, _ = self._run([path, "--vehicle", "models", "--strict"])
        self.assertEqual(code, 0)

    def test_json_output_is_parseable(self):
        import json
        path = self._write_show(
            make_show(50, {LEFT_FRONT_TURN: [(0, 2, ON_500)]}))
        code, out, _ = self._run([path, "--vehicle", "model3", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["frame_count"], 50)
        self.assertIn("model3", payload["vehicles"])

    def test_unreadable_file_reports_an_error(self):
        code, _, err = self._run([os.path.join(REPO_ROOT, "does-not-exist.fseq")])
        self.assertEqual(code, 2)
        self.assertTrue(err.strip())


def example_fseqs():
    """Yield (label, bytes) for every example show, zipped or loose."""
    examples = os.path.join(REPO_ROOT, "examples")
    for name in sorted(os.listdir(examples)):
        if not name.endswith(".zip"):
            continue
        with zipfile.ZipFile(os.path.join(examples, name)) as bundle:
            for member in sorted(bundle.namelist()):
                if member.lower().endswith(".fseq"):
                    yield "{}:{}".format(name, member), bundle.read(member)
    # The multi-car examples ship unpacked rather than as archives.
    for root, _, files in sorted(os.walk(examples)):
        for name in sorted(files):
            if not name.lower().endswith(".fseq"):
                continue
            path = os.path.join(root, name)
            with open(path, "rb") as handle:
                yield os.path.relpath(path, REPO_ROOT), handle.read()


def example_label(name):
    """Shorten an example path to "lightshow_example_N"."""
    for part in name.replace("\\", "/").split("/"):
        if part.startswith("lightshow_example_"):
            return "_".join(part.split("_")[:3])
    return name


def example_shows():
    """Yield (label, Show) for every example show."""
    for name, blob in example_fseqs():
        handle = tempfile.NamedTemporaryFile(suffix=".fseq", delete=False)
        handle.write(blob)
        handle.close()
        try:
            yield name, vp.read_fseq(handle.name)
        finally:
            os.unlink(handle.name)


class ShippedExampleTests(unittest.TestCase):
    """The example shows in this repository must analyse cleanly end to end."""

    def test_every_example_show_analyses_on_every_vehicle(self):
        seen = 0
        for name, blob in example_fseqs():
            seen += 1
            handle = tempfile.NamedTemporaryFile(suffix=".fseq", delete=False)
            handle.write(blob)
            handle.close()
            try:
                show = vp.read_fseq(handle.name)
                for key, profile in vp.VEHICLES.items():
                    findings = vp.analyze(show, profile)
                    for finding in findings:
                        self.assertIn(finding.severity,
                                      (vp.ERROR, vp.WARNING, vp.INFO))
                        self.assertTrue(finding.summary, name)
                        self.assertTrue(finding.detail, name)
            finally:
                os.unlink(handle.name)
        self.assertGreater(seen, 0, "no example .fseq files were found")

    def test_examples_cover_both_channel_counts(self):
        # The 48-channel shows and the 200-channel Cybertruck shows take
        # different paths through the channel map, so both must be present.
        counts = set()
        for _, blob in example_fseqs():
            counts.add(struct.unpack("<I", blob[10:14])[0])
        self.assertEqual(counts, {48, 200})


# --------------------------------------------------------------------------
# Interior RGB -- https://github.com/teslamotors/light-show/issues/49
# --------------------------------------------------------------------------

WHITE = (255, 255, 255)
RED = (255, 0, 0)
BLACK = (0, 0, 0)

DISPLAY = "Center Front Display"


def interior_show(colours, frames=50, channel_count=200, step_time=20,
                  start=10, length=10):
    """Build a show that lights interior segments.

    `colours` maps a segment name to one (r, g, b) or a list of them, each
    held for `length` frames from `start`.
    """
    events = {}
    for segment in vp.INTERIOR_SEGMENTS:
        if segment.name not in colours:
            continue
        sequence = colours[segment.name]
        if isinstance(sequence, tuple):
            sequence = [sequence]
        for index, colour in enumerate(sequence):
            first = start + index * length
            for channel, value in zip(segment.channels, colour):
                events.setdefault(channel, []).append((first, length, value))
    return make_show(frames, events, channel_count=channel_count,
                     step_time=step_time)


def usage_by_name(show):
    return {u.segment.name: u for u in vp.interior_usage(show)}


class InteriorChannelMapTests(unittest.TestCase):
    """The segment table must match the show folder it describes."""

    def test_segments_match_the_recorded_channel_map(self):
        path = os.path.join(REPO_ROOT, "xlights", "channel_map.json")
        with open(path) as handle:
            models = json.load(handle)["models"]
        for segment in vp.INTERIOR_SEGMENTS:
            self.assertIn(segment.name, models)
            recorded = models[segment.name]["StartChannel"]
            self.assertTrue(
                recorded.endswith(":{}".format(segment.start)),
                "{} starts at {} in the show folder, not {}".format(
                    segment.name, recorded, segment.start))

    def test_readme_describes_a_display_and_five_accent_segments(self):
        # README.md, "Interior RGB Lights": the Center Front Display, plus
        # five accent segments on cars that have Interior Accent Lights.
        accents = [s for s in vp.INTERIOR_SEGMENTS if s.accent]
        display = [s for s in vp.INTERIOR_SEGMENTS if not s.accent]
        self.assertEqual(len(accents), 5)
        self.assertEqual([s.name for s in display], [DISPLAY])

    def test_every_segment_owns_three_rgb_channels(self):
        for segment in vp.INTERIOR_SEGMENTS:
            self.assertEqual(len(segment.channels), 3)
            for channel in segment.channels:
                self.assertEqual(vp.CHANNELS[channel][1], vp.RGB)
                self.assertIn(segment.name, vp.channel_name(channel))

    def test_segments_do_not_overlap_and_fit_a_200_channel_export(self):
        used = [c for s in vp.INTERIOR_SEGMENTS for c in s.channels]
        self.assertEqual(len(used), len(set(used)))
        self.assertLessEqual(vp.INTERIOR_LAST_CHANNEL, 200)


class InteriorIsolationTests(unittest.TestCase):
    """RGB bytes are colours, not the brightness enum used everywhere else.

    None of the ramp, boolean or absent-channel rules may reach them.
    """

    def test_no_vehicle_finding_ever_cites_an_interior_channel(self):
        show = interior_show({s.name: WHITE for s in vp.INTERIOR_SEGMENTS})
        for profile in vp.VEHICLES.values():
            for finding in vp.analyze(show, profile):
                for channel in finding.channels:
                    self.assertLess(
                        channel, vp.INTERIOR_FIRST_CHANNEL,
                        "{} reported interior channel {}".format(
                            finding.code, channel))

    def test_a_ramp_code_value_on_an_interior_channel_is_not_a_ramp(self):
        # 178 is 70%, "Turn on; 500 ms" on a light channel. On an interior
        # channel it is simply a colour component.
        show = interior_show({DISPLAY: (ON_500, 0, 0)})
        for profile in vp.VEHICLES.values():
            found = vp.analyze(show, profile)
            self.assertEqual(
                [f for f in found if f.code in ("ramp-ignored",
                                                "ramp-too-short")], [])

    def test_interior_channels_are_not_reported_as_missing_hardware(self):
        show = interior_show({DISPLAY: WHITE})
        for profile in vp.VEHICLES.values():
            found = vp.analyze(show, profile)
            self.assertEqual(find(found, "channel-not-present"), [])


class InteriorUsageTests(unittest.TestCase):
    def test_measures_colours_changes_and_first_lit_time(self):
        show = interior_show({DISPLAY: [RED, WHITE, RED]}, start=5, length=10)
        entry = usage_by_name(show)[DISPLAY]

        self.assertEqual(entry.colours, 2)          # red and white
        self.assertEqual(entry.lit_frames, 30)
        self.assertEqual(entry.first_lit_ms, 100)   # frame 5 at 20 ms
        self.assertTrue(entry.lit)

    def test_black_is_not_a_colour(self):
        show = interior_show({DISPLAY: [BLACK, BLACK]})
        entry = usage_by_name(show)[DISPLAY]

        self.assertEqual(entry.colours, 0)
        self.assertEqual(entry.lit_frames, 0)
        self.assertFalse(entry.lit)
        self.assertIsNone(entry.first_lit_ms)

    def test_a_48_channel_show_has_no_interior_data_to_measure(self):
        show = make_show(10, {13: [(0, 5, 255)]}, channel_count=48)
        self.assertEqual(vp.interior_usage(show), [])

    def test_every_segment_is_measured_independently(self):
        show = interior_show({DISPLAY: WHITE, "Left Rear RGB": RED})
        entries = usage_by_name(show)

        self.assertTrue(entries[DISPLAY].lit)
        self.assertTrue(entries["Left Rear RGB"].lit)
        self.assertFalse(entries["Right Front RGB"].lit)


class InteriorFindingTests(unittest.TestCase):
    def test_48_channel_show_cannot_reach_the_interior(self):
        show = make_show(10, {13: [(0, 5, 255)]}, channel_count=48)
        findings = vp.analyze_interior(show)

        self.assertEqual(codes(findings), ["interior-not-in-export"])
        self.assertIn("176-193", findings[0].detail)

    def test_200_channel_show_with_a_dark_cabin(self):
        show = interior_show({})
        findings = vp.analyze_interior(show)

        self.assertEqual(codes(findings), ["interior-unused"])
        self.assertEqual(findings[0].severity, vp.INFO)

    def test_accents_without_the_display_is_a_warning(self):
        show = interior_show({"Left Front RGB": WHITE,
                              "Right Front RGB": WHITE,
                              "Left Rear RGB": WHITE,
                              "Right Rear RGB": WHITE,
                              "Center Front RGB": WHITE})
        findings = vp.analyze_interior(show)

        warnings = find(findings, "interior-accents-without-display")
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].severity, vp.WARNING)
        self.assertIn("Interior Accent Lights", warnings[0].detail)

    def test_display_only_is_the_safe_choice(self):
        show = interior_show({DISPLAY: WHITE})
        findings = vp.analyze_interior(show)

        self.assertEqual(codes(findings), ["interior-display-only"])
        self.assertEqual(findings[0].severity, vp.INFO)

    def test_partial_accent_coverage_is_noted(self):
        show = interior_show({DISPLAY: WHITE, "Left Front RGB": WHITE})
        findings = vp.analyze_interior(show)

        partial = find(findings, "interior-partial-accents")
        self.assertEqual(len(partial), 1)
        self.assertIn("4 of 5", partial[0].summary)

    def test_a_fully_driven_cabin_reports_nothing(self):
        show = interior_show({s.name: WHITE for s in vp.INTERIOR_SEGMENTS})
        self.assertEqual(vp.analyze_interior(show), [])

    def test_every_finding_has_a_summary_and_detail(self):
        shows = [
            make_show(10, {13: [(0, 5, 255)]}, channel_count=48),
            interior_show({}),
            interior_show({DISPLAY: WHITE}),
            interior_show({"Left Front RGB": WHITE}),
        ]
        for show in shows:
            for finding in vp.analyze_interior(show):
                self.assertTrue(finding.summary)
                self.assertTrue(finding.detail)
                self.assertIn(finding.severity, (vp.ERROR, vp.WARNING, vp.INFO))


class InteriorReportingTests(unittest.TestCase):
    def test_text_report_includes_the_interior_section(self):
        show = interior_show({DISPLAY: [RED, WHITE]})
        text = vp.render_report(show, {"models": []}, verbose=True,
                                interior=vp.analyze_interior(show))

        self.assertIn("Interior RGB", text)
        self.assertIn(DISPLAY, text)
        self.assertIn("2 colour(s)", text)

    def test_report_without_interior_is_unchanged(self):
        show = interior_show({DISPLAY: WHITE})
        self.assertNotIn("Interior RGB",
                         vp.render_report(show, {"models": []}, verbose=True))

    def test_dark_segments_are_hidden_unless_verbose(self):
        show = interior_show({DISPLAY: WHITE})
        interior = vp.analyze_interior(show)
        quiet = vp.render_report(show, {"models": []}, False, interior)
        loud = vp.render_report(show, {"models": []}, True, interior)

        self.assertNotIn("not driven", quiet)
        self.assertIn("not driven", loud)


class InteriorCommandLineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def write_show(self, show):
        path = os.path.join(self._tmp.name, "show.fseq")
        raw = build_fseq_bytes(show.frame_count,
                               channel_count=show.channel_count,
                               step_time=show.step_time_ms)
        with open(path, "wb") as handle:
            handle.write(raw[:HEADER_BYTES] + show.data)
        return path

    def run_main(self, *argv):
        stdout = io.StringIO()
        original = sys.stdout
        sys.stdout = stdout
        try:
            code = vp.main(list(argv))
        finally:
            sys.stdout = original
        return code, stdout.getvalue()

    def test_json_carries_the_interior_segments(self):
        path = self.write_show(interior_show({DISPLAY: [RED, WHITE]}))
        code, out = self.run_main(path, "--vehicle", "models", "--json")
        payload = json.loads(out)

        self.assertEqual(code, 0)
        self.assertEqual(len(payload["interior"]["segments"]), 6)
        display = payload["interior"]["segments"][0]
        self.assertEqual(display["name"], DISPLAY)
        self.assertEqual(display["channels"], [176, 177, 178])
        self.assertFalse(display["accent"])
        self.assertTrue(display["lit"])

    def test_json_for_a_48_channel_show_has_no_segments(self):
        show = make_show(10, {13: [(0, 5, 255)]}, channel_count=48)
        code, out = self.run_main(self.write_show(show), "--vehicle", "models",
                                  "--json")
        payload = json.loads(out)

        self.assertEqual(payload["interior"]["segments"], [])
        self.assertEqual(
            [f["code"] for f in payload["interior"]["findings"]],
            ["interior-not-in-export"])

    def test_strict_fails_on_the_interior_warning(self):
        path = self.write_show(interior_show({"Left Front RGB": WHITE}))
        self.assertEqual(self.run_main(path, "--vehicle", "models")[0], 0)
        self.assertEqual(
            self.run_main(path, "--vehicle", "models", "--strict")[0], 1)


class ShippedExampleInteriorTests(unittest.TestCase):
    """Real shows, to keep the segment table honest about the file format."""

    def _shows(self):
        return example_shows()

    def test_at_least_one_example_drives_the_interior(self):
        lit = {name: [u.segment.name for u in vp.interior_usage(show) if u.lit]
               for name, show in self._shows()}
        self.assertTrue(any(lit.values()),
                        "no shipped example lights the cabin: {}".format(lit))

    def test_a_show_that_drives_the_cabin_drives_the_display_too(self):
        # Every example that uses the accents also uses the display, so none
        # of them trips the optional-hardware warning.
        for name, show in self._shows():
            findings = vp.analyze_interior(show)
            self.assertEqual(
                find(findings, "interior-accents-without-display"), [],
                "{} drives accents without the display".format(name))

    def test_interior_usage_never_raises_on_a_real_show(self):
        seen = 0
        for _, show in self._shows():
            seen += 1
            usage = vp.interior_usage(show)
            self.assertIn(len(usage), (0, len(vp.INTERIOR_SEGMENTS)))
        self.assertGreater(seen, 0)


# --------------------------------------------------------------------------
# Closure command budget -- https://github.com/teslamotors/light-show/issues/50
# --------------------------------------------------------------------------

# Closure command bytes, from the brightness percentages in README.md.
OPEN_CMD = 64            # 25%, "Q"
DANCE_CMD = 128          # 50%, "A"
CLOSE_CMD = 191          # 75%, "Z"
STOP_CMD = 255           # 100%, "F"

LEFT_MIRROR, RIGHT_MIRROR = 35, 36
LEFT_FRONT_WINDOW = 37
LIFTGATE = 41
LEFT_FRONT_HANDLE = 42
CHARGE_PORT = 46
LEFT_FALCON = 31


def closure_show(events, frames=2000, step_time=20):
    """A show whose only content is closure commands."""
    return make_show(frames, events, step_time=step_time)


def spaced(command, count, spacing_frames=50, start=0, length=5):
    """`count` copies of one command, spaced apart."""
    return [(start + i * spacing_frames, length, command)
            for i in range(count)]


def usage_for(show, channel):
    return next(u for u in vp.closure_usage(show) if u.channel == channel)


class ClosureTableTests(unittest.TestCase):
    """The family table must match the closure table in README.md."""

    def test_every_closure_channel_has_a_family(self):
        closures = [c for c, (_, kind) in vp.CHANNELS.items()
                    if kind == vp.CLOSURE]
        self.assertEqual(sorted(closures), sorted(vp.CLOSURE_FAMILIES))

    def test_documented_limits(self):
        # README.md, "Command Limit Per Show".
        expected = {
            "Liftgate": 6, "Mirrors": 20, "Charge Port": 3, "Windows": 6,
            "Door Handles": 20, "Front Doors": 6, "Falcon Doors": 6,
        }
        actual = {f.name: f.limit for f in vp.CLOSURE_FAMILIES.values()}
        self.assertEqual(actual, expected)

    def test_documented_dance_support(self):
        # README.md, "Supports Dance?": only these four are marked Yes.
        dancing = {f.name for f in vp.CLOSURE_FAMILIES.values() if f.dance}
        self.assertEqual(
            dancing, {"Liftgate", "Charge Port", "Windows", "Falcon Doors"})

    def test_windows_are_the_only_exception_to_dance_needs_open(self):
        exempt = {f.name for f in vp.CLOSURE_FAMILIES.values()
                  if not f.dance_needs_open}
        self.assertEqual(exempt, {"Windows"})

    def test_counted_commands_come_from_the_closure_code_table(self):
        self.assertEqual(
            sorted(vp.COUNTED_COMMANDS),
            sorted(percent for percent, name in vp.CLOSURE_CODES.items()
                   if name in ("Open", "Dance", "Close")))
        self.assertNotIn(vp.STOP, vp.COUNTED_COMMANDS)
        self.assertNotIn(0, vp.COUNTED_COMMANDS)


class ClosureUsageTests(unittest.TestCase):
    def test_a_command_is_a_run_not_a_frame(self):
        # One Dance held for 10 seconds is one actuation, not 500.
        show = closure_show({LIFTGATE: [(0, 500, DANCE_CMD)]})
        self.assertEqual(usage_for(show, LIFTGATE).count, 1)

    def test_idle_and_stop_are_free(self):
        show = closure_show({LIFTGATE: [(0, 10, STOP_CMD), (20, 10, 0),
                                        (40, 10, STOP_CMD)]})
        self.assertEqual(usage_for(show, LIFTGATE).count, 0)

    def test_open_close_and_dance_all_count(self):
        show = closure_show({LIFTGATE: [(0, 5, OPEN_CMD), (50, 5, DANCE_CMD),
                                        (100, 5, CLOSE_CMD)]})
        self.assertEqual(usage_for(show, LIFTGATE).count, 3)

    def test_dance_time_is_measured(self):
        show = closure_show({LIFTGATE: [(0, 5, OPEN_CMD),
                                        (50, 100, DANCE_CMD)]},
                            step_time=20)
        self.assertEqual(usage_for(show, LIFTGATE).dance_ms, 2000)

    def test_repeated_commands_separated_by_idle_count_separately(self):
        show = closure_show({LEFT_MIRROR: spaced(OPEN_CMD, 4)})
        self.assertEqual(usage_for(show, LEFT_MIRROR).count, 4)

    def test_every_closure_is_reported_even_when_unused(self):
        show = closure_show({})
        self.assertEqual(len(vp.closure_usage(show)),
                         len(vp.CLOSURE_FAMILIES))
        self.assertTrue(all(u.count == 0 for u in vp.closure_usage(show)))


class ClosureBudgetFindingTests(unittest.TestCase):
    def test_over_the_limit_is_a_warning(self):
        show = closure_show({CHARGE_PORT: spaced(OPEN_CMD, 5)})
        findings = find(vp.analyze_closures(show), "closure-limit-exceeded")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, vp.WARNING)
        self.assertEqual(findings[0].occurrences, 2)      # 5 used, limit 3
        self.assertIn("Charge Port", findings[0].summary)

    def test_the_timestamp_points_at_the_first_command_past_the_limit(self):
        show = closure_show({CHARGE_PORT: spaced(OPEN_CMD, 5,
                                                 spacing_frames=50)},
                            step_time=20)
        finding = find(vp.analyze_closures(show), "closure-limit-exceeded")[0]

        # Commands at frames 0, 50, 100, 150, 200; the fourth is the overrun.
        self.assertEqual(finding.first_at_ms, 150 * 20)

    def test_exactly_at_the_limit_is_a_note(self):
        show = closure_show({CHARGE_PORT: spaced(OPEN_CMD, 3)})
        findings = vp.analyze_closures(show)

        self.assertEqual(find(findings, "closure-limit-exceeded"), [])
        reached = find(findings, "closure-limit-reached")
        self.assertEqual(len(reached), 1)
        self.assertEqual(reached[0].severity, vp.INFO)

    def test_under_the_limit_says_nothing(self):
        show = closure_show({CHARGE_PORT: spaced(OPEN_CMD, 2)})
        self.assertEqual(vp.analyze_closures(show), [])

    def test_limits_are_counted_per_individual_closure(self):
        # README.md: "counted separately for each individual closure". Four
        # windows at 4 commands each is fine; one window at 8 is not.
        fine = closure_show({c: spaced(OPEN_CMD, 4) for c in (37, 38, 39, 40)})
        self.assertEqual(find(vp.analyze_closures(fine),
                              "closure-limit-exceeded"), [])

        over = closure_show({LEFT_FRONT_WINDOW: spaced(OPEN_CMD, 8)})
        self.assertEqual(len(find(vp.analyze_closures(over),
                                  "closure-limit-exceeded")), 1)

    def test_mirrors_have_a_larger_budget_than_the_charge_port(self):
        show = closure_show({LEFT_MIRROR: spaced(OPEN_CMD, 5),
                             CHARGE_PORT: spaced(OPEN_CMD, 5)})
        over = find(vp.analyze_closures(show), "closure-limit-exceeded")

        self.assertEqual([f.channels for f in over], [(CHARGE_PORT,)])


class ClosureDanceTests(unittest.TestCase):
    def test_dance_on_a_closure_that_cannot_dance_is_a_warning(self):
        """The reporter's mirrors on a Model 3: README marks Mirrors "-"."""
        show = closure_show({LEFT_MIRROR: [(0, 20, DANCE_CMD)]})
        findings = find(vp.analyze_closures(show),
                        "closure-dance-unsupported")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, vp.WARNING)
        self.assertIn("Mirrors", findings[0].detail)

    def test_door_handles_and_front_doors_also_cannot_dance(self):
        for channel in (LEFT_FRONT_HANDLE, 33):
            show = closure_show({channel: [(0, 20, DANCE_CMD)]})
            self.assertEqual(
                len(find(vp.analyze_closures(show),
                         "closure-dance-unsupported")), 1,
                vp.channel_name(channel))

    def test_a_dancing_closure_is_not_flagged(self):
        show = closure_show({LIFTGATE: [(0, 5, OPEN_CMD),
                                        (800, 20, DANCE_CMD)]})
        self.assertEqual(find(vp.analyze_closures(show),
                              "closure-dance-unsupported"), [])

    def test_dance_while_closed_is_a_warning(self):
        show = closure_show({LIFTGATE: [(0, 20, DANCE_CMD)]})
        findings = find(vp.analyze_closures(show),
                        "closure-dance-without-open")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, vp.WARNING)

    def test_a_close_puts_the_closure_back_in_the_closed_state(self):
        show = closure_show({LIFTGATE: [(0, 5, OPEN_CMD),
                                        (800, 5, CLOSE_CMD),
                                        (1000, 20, DANCE_CMD)]})
        self.assertEqual(len(find(vp.analyze_closures(show),
                                  "closure-dance-without-open")), 1)

    def test_windows_may_dance_without_opening_first(self):
        # README.md: "With the exception of windows".
        show = closure_show({LEFT_FRONT_WINDOW: [(0, 20, DANCE_CMD)]})
        findings = vp.analyze_closures(show)

        self.assertEqual(find(findings, "closure-dance-without-open"), [])
        self.assertEqual(find(findings, "closure-dance-early"), [])

    def test_dance_too_soon_after_open_is_a_note(self):
        # The liftgate takes about 14 s to open; dance after 2 s.
        show = closure_show({LIFTGATE: [(0, 5, OPEN_CMD),
                                        (100, 20, DANCE_CMD)]}, step_time=20)
        findings = find(vp.analyze_closures(show), "closure-dance-early")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, vp.INFO)
        self.assertIn("14 s", findings[0].summary)

    def test_dance_after_a_full_open_is_not_flagged(self):
        show = closure_show({LIFTGATE: [(0, 5, OPEN_CMD),
                                        (800, 20, DANCE_CMD)]}, step_time=20)
        self.assertEqual(find(vp.analyze_closures(show),
                              "closure-dance-early"), [])

    def test_each_family_uses_its_own_open_duration(self):
        # Falcon doors take about 20 s; 15 s is too soon for them.
        show = closure_show({LEFT_FALCON: [(0, 5, OPEN_CMD),
                                           (750, 20, DANCE_CMD)]},
                            step_time=20)
        self.assertEqual(len(find(vp.analyze_closures(show),
                                  "closure-dance-early")), 1)

    def test_long_dances_hit_the_thermal_note(self):
        # README.md recommends ~30 s or less of dancing per show.
        show = closure_show({LIFTGATE: [(0, 5, OPEN_CMD),
                                        (800, 1700, DANCE_CMD)]},
                            frames=3000, step_time=20)
        findings = find(vp.analyze_closures(show), "closure-dance-thermal")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, vp.INFO)

    def test_a_short_dance_does_not(self):
        show = closure_show({LIFTGATE: [(0, 5, OPEN_CMD),
                                        (800, 100, DANCE_CMD)]})
        self.assertEqual(find(vp.analyze_closures(show),
                              "closure-dance-thermal"), [])


class ClosureSpacingTests(unittest.TestCase):
    def test_commands_bunched_together_are_noted(self):
        show = closure_show({CHARGE_PORT: [(0, 2, OPEN_CMD),
                                           (2, 2, CLOSE_CMD)]}, step_time=20)
        findings = find(vp.analyze_closures(show),
                        "closure-commands-bunched")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, vp.INFO)
        self.assertIn("40 ms apart", findings[0].detail)

    def test_well_spaced_commands_are_not(self):
        show = closure_show({CHARGE_PORT: spaced(OPEN_CMD, 3,
                                                 spacing_frames=100)})
        self.assertEqual(find(vp.analyze_closures(show),
                              "closure-commands-bunched"), [])

    def test_the_threshold_is_declared_as_a_judgement(self):
        show = closure_show({CHARGE_PORT: [(0, 2, OPEN_CMD),
                                           (2, 2, CLOSE_CMD)]})
        finding = find(vp.analyze_closures(show),
                       "closure-commands-bunched")[0]
        self.assertIn("judgement", finding.detail)


class ClosureReportingTests(unittest.TestCase):
    def test_the_budget_table_shows_used_and_limit(self):
        show = closure_show({CHARGE_PORT: spaced(OPEN_CMD, 2)})
        text = vp.render_report(show, {"models": []}, verbose=False,
                                closures=vp.analyze_closures(show))

        self.assertIn("Closure command budget", text)
        self.assertIn("Charge Port", text)
        self.assertIn("2 / 3", text)

    def test_unused_closures_are_hidden_unless_verbose(self):
        show = closure_show({CHARGE_PORT: spaced(OPEN_CMD, 2)})
        findings = vp.analyze_closures(show)

        self.assertNotIn("Liftgate", vp.render_report(
            show, {"models": []}, False, closures=findings))
        self.assertIn("Liftgate", vp.render_report(
            show, {"models": []}, True, closures=findings))

    def test_a_show_without_closures_says_so(self):
        show = closure_show({})
        text = vp.render_report(show, {"models": []}, False,
                                closures=vp.analyze_closures(show))
        self.assertIn("does not move any closure", text)

    def test_over_limit_is_marked_in_the_table(self):
        show = closure_show({CHARGE_PORT: spaced(OPEN_CMD, 5)})
        text = vp.render_report(show, {"models": []}, False,
                                closures=vp.analyze_closures(show))
        self.assertIn("over by 2", text)

    def test_report_without_closures_is_unchanged(self):
        show = closure_show({CHARGE_PORT: spaced(OPEN_CMD, 2)})
        self.assertNotIn("Closure command budget",
                         vp.render_report(show, {"models": []}, True))


class ClosureCommandLineTests(InteriorCommandLineTests):
    def test_json_carries_the_closure_budget(self):
        path = self.write_show(closure_show({CHARGE_PORT: spaced(OPEN_CMD, 5)}))
        code, out = self.run_main(path, "--vehicle", "models", "--json")
        payload = json.loads(out)

        self.assertEqual(code, 0)
        budget = {b["name"]: b for b in payload["closures"]["budget"]}
        self.assertEqual(budget["Charge Port"]["commands"], 5)
        self.assertEqual(budget["Charge Port"]["limit"], 3)
        self.assertEqual(budget["Charge Port"]["over_by"], 2)
        self.assertIn("closure-limit-exceeded",
                      [f["code"] for f in payload["closures"]["findings"]])

    def test_strict_fails_on_an_exceeded_limit(self):
        path = self.write_show(closure_show({CHARGE_PORT: spaced(OPEN_CMD, 5)}))
        self.assertEqual(self.run_main(path, "--vehicle", "models")[0], 0)
        self.assertEqual(
            self.run_main(path, "--vehicle", "models", "--strict")[0], 1)


class ShippedExampleClosureTests(unittest.TestCase):
    """Real shows keep the counting rule honest.

    If commands were counted per frame rather than per effect, every one of
    these shows would blow past its limits.
    """

    def test_counting_is_per_effect_not_per_frame(self):
        """The strongest guard on the counting rule.

        A closure effect held for seconds is one actuation. If these were
        counted per frame instead, every one of these shows would be hundreds
        of commands past its limit rather than within a command or two of it.
        """
        for name, show in example_shows():
            for entry in vp.closure_usage(show):
                self.assertLessEqual(
                    entry.count, entry.family.limit + 2,
                    "{}: {} spends {} commands against a limit of {}".format(
                        name, vp.channel_name(entry.channel), entry.count,
                        entry.family.limit))

    def test_the_shipped_examples_trip_exactly_the_known_findings(self):
        """Two shipped shows overrun the documented closure rules.

        Both were found by this check and are left as they are; the point of
        the test is that the rules fire on real files, and that the list does
        not grow silently.

        - lightshow_example_2 places one Dance on a door handle, which
          README.md marks as not supporting Dance.
        - lightshow_example_5 spends 4 charge port commands against a
          documented limit of 3.
        """
        warnings = [(example_label(name), f.code)
                    for name, show in example_shows()
                    for f in vp.analyze_closures(show)
                    if f.severity == vp.WARNING]

        self.assertEqual(set(warnings), {
            ("lightshow_example_2", "closure-dance-unsupported"),
            ("lightshow_example_5", "closure-limit-exceeded"),
        })
        # Cyber Symphony ships one file per car, and all four overrun.
        self.assertEqual(
            sum(1 for _, code in warnings
                if code == "closure-limit-exceeded"), 4)

    def test_the_examples_do_spend_closure_commands(self):
        totals = {name: sum(u.count for u in vp.closure_usage(show))
                  for name, show in example_shows()}
        self.assertTrue(any(totals.values()),
                        "no shipped example moves a closure")

    def test_at_least_one_example_sits_at_a_limit(self):
        # lightshow_example_3 uses all 20 mirror commands on each mirror.
        at_limit = [name for name, show in example_shows()
                    if find(vp.analyze_closures(show),
                            "closure-limit-reached")]
        self.assertTrue(at_limit, "expected a show at a documented limit")


# --------------------------------------------------------------------------
# Vehicle support -- https://github.com/teslamotors/light-show/issues/52
# --------------------------------------------------------------------------

LEFT_TAIL, RIGHT_TAIL, LICENSE_PLATE = 26, 27, 30


def readme_lines():
    with open(os.path.join(REPO_ROOT, "README.md")) as handle:
        return handle.read().splitlines()


def readme_bullets(heading):
    """The bullet list directly under a heading."""
    lines = readme_lines()
    start = next(i for i, line in enumerate(lines)
                 if line.strip().startswith("#") and heading in line)
    bullets = []
    for line in lines[start + 1:]:
        if line.startswith("#"):
            break
        if line.startswith("- "):
            bullets.append(line[2:].strip())
    return bullets


class VehicleSupportTests(unittest.TestCase):
    """The tool's vehicle list is the README's list, or it is wrong.

    Issue 52 asks for a vehicle to be supported. Adding one is a change to
    the README's Supported Vehicles list and a matching profile here; this
    test is what stops the two drifting apart.
    """

    def supported_bullets(self):
        return readme_bullets("Supported Vehicles")

    def test_tool_profiles_match_the_readme_list(self):
        vehicles = [b for b in self.supported_bullets()
                    if not b.startswith("Running Software")]
        self.assertEqual(sorted(vehicles),
                         sorted(p.label for p in vp.VEHICLES.values()))

    def test_the_list_states_a_minimum_software_version(self):
        software = [b for b in self.supported_bullets()
                    if b.startswith("Running Software")]
        self.assertEqual(len(software), 1)
        self.assertIn("2021.44.25", software[0])

    def test_model_s_and_x_are_limited_to_2021_and_newer(self):
        """The boundary issue 52 ran into. A 2020 Model X is outside it."""
        for key in ("models", "modelx"):
            self.assertIn("2021+", vp.VEHICLES[key].label)

    def test_model_3_and_y_carry_no_year_boundary(self):
        for key in ("model3", "modely", "cybertruck"):
            self.assertNotIn("+", vp.VEHICLES[key].label)


class BuildVariantTests(unittest.TestCase):
    def test_model_3_has_the_documented_pre_october_2020_build(self):
        keys = [v.key for v in vp.VEHICLES["model3"].variants]
        self.assertEqual(keys, ["pre-oct-2020"])

    def test_model_y_has_no_build_variants(self):
        # README.md names Model 3 only for the tail light rule, and Model Y
        # is built from the Model 3 profile, so this is easy to get wrong.
        self.assertEqual(vp.VEHICLES["modely"].variants, ())

    def test_other_vehicles_have_no_build_variants(self):
        for key in ("models", "modelx", "cybertruck"):
            self.assertEqual(vp.VEHICLES[key].variants, (), key)

    def test_every_variant_cites_a_readme_section(self):
        for profile in vp.VEHICLES.values():
            for variant in profile.variants:
                self.assertTrue(variant.readme, variant.key)
                self.assertIn(variant.readme, "\n".join(readme_lines()))

    def test_variant_profile_layers_onto_its_parent(self):
        parent = vp.VEHICLES["model3"]
        variant = parent.variants[0]
        derived = vp.variant_profile(parent, variant)

        self.assertEqual(derived.label, variant.label)
        self.assertEqual(derived.key, "model3:pre-oct-2020")
        self.assertEqual(vp.kind_of(derived, LICENSE_PLATE), vp.SLAVED)
        # Inherited, not restated.
        self.assertEqual(vp.kind_of(derived, 13), vp.kind_of(parent, 13))
        self.assertIn(variant.or_groups[0], derived.or_groups)
        self.assertEqual(derived.variants, ())

    def test_the_parent_profile_is_untouched_by_the_variant(self):
        parent = vp.VEHICLES["model3"]
        vp.variant_profile(parent, parent.variants[0])

        self.assertNotEqual(vp.kind_of(parent, LICENSE_PLATE), vp.SLAVED)
        self.assertEqual(len(parent.or_groups), 3)


class BuildVariantFindingTests(unittest.TestCase):
    def test_separately_driven_tails_collapse_on_the_older_build(self):
        show = make_show(300, {
            LEFT_TAIL: [(0, 20, ON_INSTANT)],
            RIGHT_TAIL: [(30, 20, ON_INSTANT)],
        })
        base = vp.analyze(show, vp.VEHICLES["model3"])
        variants = vp.analyze_variants(show, vp.VEHICLES["model3"])

        self.assertEqual(find(base, "or-group-collapse"), [])
        self.assertEqual(len(variants), 1)
        self.assertEqual(len(find(variants[0][1], "or-group-collapse")), 1)

    def test_tails_driven_together_are_fine_on_both_builds(self):
        show = make_show(300, {
            LEFT_TAIL: [(0, 20, ON_INSTANT)],
            RIGHT_TAIL: [(0, 20, ON_INSTANT)],
        })
        _, extra = vp.analyze_variants(show, vp.VEHICLES["model3"])[0]
        self.assertEqual(find(extra, "or-group-collapse"), [])

    def test_the_license_plate_channel_is_reported_as_having_no_effect(self):
        show = make_show(300, {LICENSE_PLATE: [(0, 50, ON_INSTANT)]})
        _, extra = vp.analyze_variants(show, vp.VEHICLES["model3"])[0]
        findings = find(extra, "channel-has-no-effect")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, vp.INFO)
        self.assertIn("tail lights", findings[0].detail)
        # It is not the "no such light" message; the lamp is fitted.
        self.assertEqual(find(extra, "channel-not-present"), [])

    def test_an_unused_license_plate_channel_says_nothing(self):
        show = make_show(300, {LEFT_TAIL: [(0, 20, ON_INSTANT)]})
        _, extra = vp.analyze_variants(show, vp.VEHICLES["model3"])[0]
        self.assertEqual(find(extra, "channel-has-no-effect"), [])

    def test_only_the_difference_from_the_base_report_is_returned(self):
        # Channels 4-6 collapse on every Model 3, so that finding belongs to
        # the base report and must not be repeated under the build.
        show = make_show(300, {
            LEFT_CH4: [(0, 20, ON_INSTANT)],
            LEFT_CH5: [(30, 20, ON_INSTANT)],
        })
        base = vp.analyze(show, vp.VEHICLES["model3"])
        _, extra = vp.analyze_variants(show, vp.VEHICLES["model3"])[0]

        self.assertTrue(find(base, "or-group-collapse"))
        self.assertEqual(extra, [])

    def test_a_show_that_avoids_the_difference_reports_nothing(self):
        show = make_show(300, {LEFT_FRONT_TURN: [(0, 20, ON_INSTANT)]})
        _, extra = vp.analyze_variants(show, vp.VEHICLES["model3"])[0]
        self.assertEqual(extra, [])

    def test_vehicles_without_variants_return_nothing(self):
        show = make_show(300, {LICENSE_PLATE: [(0, 50, ON_INSTANT)]})
        for key in ("models", "modelx", "modely", "cybertruck"):
            self.assertEqual(vp.analyze_variants(show, vp.VEHICLES[key]), [],
                             key)

    def test_a_slaved_channel_does_not_trip_the_ramp_rules(self):
        # 178 is a ramp code; on a channel with no effect it means nothing.
        show = make_show(300, {LICENSE_PLATE: [(0, 5, ON_500)]})
        _, extra = vp.analyze_variants(show, vp.VEHICLES["model3"])[0]

        self.assertEqual(codes(extra), ["channel-has-no-effect"])


class BuildVariantReportingTests(unittest.TestCase):
    def build_show(self):
        return make_show(300, {
            LEFT_TAIL: [(0, 20, ON_INSTANT)],
            RIGHT_TAIL: [(30, 20, ON_INSTANT)],
        })

    def test_the_report_names_the_build(self):
        show = self.build_show()
        text = vp.render_report(
            show, {"model3": vp.analyze(show, vp.VEHICLES["model3"])},
            verbose=False,
            builds={"model3": vp.analyze_variants(show,
                                                  vp.VEHICLES["model3"])})

        self.assertIn("Also on Model 3 built before October 2020:", text)
        self.assertIn("Tail lights and License Plate Lights", text)

    def test_nothing_is_added_when_the_build_behaves_the_same(self):
        show = make_show(300, {LEFT_FRONT_TURN: [(0, 20, ON_INSTANT)]})
        text = vp.render_report(
            show, {"model3": vp.analyze(show, vp.VEHICLES["model3"])},
            verbose=True,
            builds={"model3": vp.analyze_variants(show,
                                                  vp.VEHICLES["model3"])})
        self.assertNotIn("Also on", text)

    def test_builds_are_omitted_entirely_when_not_requested(self):
        show = self.build_show()
        text = vp.render_report(
            show, {"model3": vp.analyze(show, vp.VEHICLES["model3"])},
            verbose=True)
        self.assertNotIn("Also on", text)


class BuildVariantCommandLineTests(InteriorCommandLineTests):
    def build_show(self):
        return make_show(300, {
            LEFT_TAIL: [(0, 20, ON_INSTANT)],
            RIGHT_TAIL: [(30, 20, ON_INSTANT)],
            LICENSE_PLATE: [(0, 50, ON_INSTANT)],
        })

    def test_json_carries_the_build_findings(self):
        path = self.write_show(self.build_show())
        code, out = self.run_main(path, "--vehicle", "model3", "--json")
        payload = json.loads(out)

        builds = payload["vehicles"]["model3"]["builds"]
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]["key"], "pre-oct-2020")
        self.assertIn("channel-has-no-effect",
                      [f["code"] for f in builds[0]["findings"]])

    def test_vehicles_without_builds_report_an_empty_list(self):
        path = self.write_show(self.build_show())
        _, out = self.run_main(path, "--vehicle", "modely", "--json")

        self.assertEqual(
            json.loads(out)["vehicles"]["modely"]["builds"], [])

    def test_strict_fails_on_a_build_only_warning(self):
        path = self.write_show(self.build_show())
        self.assertEqual(self.run_main(path, "--vehicle", "model3")[0], 0)
        self.assertEqual(
            self.run_main(path, "--vehicle", "model3", "--strict")[0], 1)


if __name__ == "__main__":
    unittest.main()
