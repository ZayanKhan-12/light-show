#!/usr/bin/env python3
"""Preview how a .fseq light show will actually behave on each Tesla vehicle.

The xLights project ships a single Model S / Cybertruck superset model, so the
sequencer preview always shows the Model S wiring: every channel is its own
light, and every light switches instantly.  Real vehicles differ.  On Model 3/Y
several xLights channels are OR'd onto one physical output, and several lights
that are boolean on Model S ramp instead.  A show that looks correct in the
preview can therefore look wrong on the car, which is what
https://github.com/teslamotors/light-show/issues/42 reports.

This tool reads a .fseq and reports the places where a given vehicle will not
reproduce what the preview showed, without needing the vehicle.

Usage:
    python3 tools/vehicle_preview.py lightshow.fseq
    python3 tools/vehicle_preview.py lightshow.fseq --vehicle model3
    python3 tools/vehicle_preview.py lightshow.fseq --json
    python3 tools/vehicle_preview.py lightshow.fseq --strict   # non-zero exit

Every behaviour encoded here is sourced from README.md; the section that backs
each rule is named in a `readme` note so the two stay reviewable side by side.

Requires Python 3.7+ and only the standard library, matching validator.py.
"""

import argparse
import dataclasses
import json
import struct
import sys
from typing import Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# Channel layout
# --------------------------------------------------------------------------
# Channel numbers are 1-based and taken from the StartChannel values in
# xlights/tesla_xlights_show_folder.zip (xlights_rgbeffects.xml).  These are the
# names the show author sees in the xLights sequencer.

LIGHT = "light"
CLOSURE = "closure"
RGB = "rgb"           # one of three channels forming an interior colour

CHANNELS: Dict[int, Tuple[str, str]] = {
    1: ("Left Outer Main Beam", LIGHT),
    2: ("Right Outer Main Beam", LIGHT),
    3: ("Left Inner Main Beam", LIGHT),
    4: ("Right Inner Main Beam", LIGHT),
    5: ("Left Signature", LIGHT),
    6: ("Right Signature", LIGHT),
    7: ("Left Channel 4", LIGHT),
    8: ("Right Channel 4", LIGHT),
    9: ("Left Channel 5", LIGHT),
    10: ("Right Channel 5", LIGHT),
    11: ("Left Channel 6", LIGHT),
    12: ("Right Channel 6", LIGHT),
    13: ("Left Front Turn", LIGHT),
    14: ("Right Front Turn", LIGHT),
    15: ("Left Front Fog", LIGHT),
    16: ("Right Front Fog", LIGHT),
    17: ("Left Aux Park", LIGHT),
    18: ("Right Aux Park", LIGHT),
    19: ("Left Side Marker", LIGHT),
    20: ("Right Side Marker", LIGHT),
    21: ("Left Side Repeater", LIGHT),
    22: ("Right Side Repeater", LIGHT),
    23: ("Left Rear Turn", LIGHT),
    24: ("Right Rear Turn", LIGHT),
    25: ("Brake Lights", LIGHT),
    26: ("Left Tail", LIGHT),
    27: ("Right Tail", LIGHT),
    28: ("Reverse Lights", LIGHT),
    29: ("Rear Fog Lights", LIGHT),
    30: ("License Plate", LIGHT),
    31: ("Left Falcon Door", CLOSURE),
    32: ("Right Falcon Door", CLOSURE),
    33: ("Left Front Door", CLOSURE),
    34: ("Right Front Door", CLOSURE),
    35: ("Left Mirror", CLOSURE),
    36: ("Right Mirror", CLOSURE),
    37: ("Left Front Window", CLOSURE),
    38: ("Left Rear Window", CLOSURE),
    39: ("Right Front Window", CLOSURE),
    40: ("Right Rear Window", CLOSURE),
    41: ("Liftgate", CLOSURE),
    42: ("Left Front Door Handle", CLOSURE),
    43: ("Left Rear Door Handle", CLOSURE),
    44: ("Right Front Door Handle", CLOSURE),
    45: ("Right Rear Door Handle", CLOSURE),
    46: ("Charge Port", CLOSURE),
}

# --------------------------------------------------------------------------
# The Cybertruck-only channels between the exterior lights and the interior
# --------------------------------------------------------------------------
# Channels 47-175 are the light bars and the suspension. They are named here
# rather than in CHANNELS because they are runs of identical LEDs rather than
# individual lights, and because no other vehicle has any of them: a show that
# spends most of itself on these looks nearly dark on a Model S, which is what
# https://github.com/teslamotors/light-show/issues/82 reads like.
#
# Ranges are the StartChannel and node count of each model in
# xlights/channel_map.json, and match the counts in README.md.


@dataclasses.dataclass
class ChannelBlock:
    name: str
    first: int
    last: int
    vehicles: Tuple[str, ...]
    readme: str

    def __contains__(self, channel: int) -> bool:
        return self.first <= channel <= self.last

    @property
    def channels(self) -> range:
        return range(self.first, self.last + 1)


CHANNEL_BLOCKS: Tuple[ChannelBlock, ...] = (
    ChannelBlock("Front Light Bar", 47, 106, ("cybertruck",),
                 "Cybertruck Light Bar"),
    ChannelBlock("Rear Light Bar", 111, 162, ("cybertruck",),
                 "Cybertruck Light Bar"),
    ChannelBlock("Offroad Light Bar", 167, 172, ("cybertruck",),
                 "Cybertruck Offroad Light Bar"),
    # The model declares two nodes; the second runs into the interior block
    # below, so only the first is treated as suspension here.
    ChannelBlock("Suspension", 175, 175, ("cybertruck",),
                 "Cybertruck Light Bar"),
)


def block_of(channel: int) -> Optional[ChannelBlock]:
    for block in CHANNEL_BLOCKS:
        if channel in block:
            return block
    return None


# --------------------------------------------------------------------------
# Interior RGB
# --------------------------------------------------------------------------
# The cabin lights answer https://github.com/teslamotors/light-show/issues/49,
# which was asked when they did not exist yet.  They do now: README.md,
# "Interior RGB Lights" describes full RGB control of the Center Front Display
# plus five accent segments, and the StartChannel of each one is recorded in
# xlights/channel_map.json.
#
# These channels are unlike every other channel in the file.  Elsewhere a byte
# is an enum of brightness steps; here three consecutive bytes are one colour,
# and any value in them is meaningful.  None of the ramp, boolean or
# brightness rules apply, so they carry their own type and every check that
# walks CHANNELS skips them.


@dataclasses.dataclass
class InteriorSegment:
    """One RGB segment of the cabin: three consecutive channels, R, G, B."""

    name: str
    start: int
    # README.md: the five accent segments exist only "on cars with Interior
    # Accent Lights"; the Center Front Display is the screen itself.
    accent: bool

    @property
    def channels(self) -> Tuple[int, int, int]:
        return (self.start, self.start + 1, self.start + 2)


# StartChannel values from xlights/channel_map.json.  The accent models are
# declared as 50-node strings for the xLights preview but sit three channels
# apart, so one RGB triplet per segment is what reaches the vehicle.
INTERIOR_SEGMENTS: Tuple[InteriorSegment, ...] = (
    InteriorSegment("Center Front Display", 176, accent=False),
    InteriorSegment("Right Rear RGB", 179, accent=True),
    InteriorSegment("Right Front RGB", 182, accent=True),
    InteriorSegment("Center Front RGB", 185, accent=True),
    InteriorSegment("Left Front RGB", 188, accent=True),
    InteriorSegment("Left Rear RGB", 191, accent=True),
)

INTERIOR_FIRST_CHANNEL = INTERIOR_SEGMENTS[0].start
INTERIOR_LAST_CHANNEL = INTERIOR_SEGMENTS[-1].channels[-1]

for _segment in INTERIOR_SEGMENTS:
    for _channel, _component in zip(_segment.channels, ("red", "green", "blue")):
        CHANNELS[_channel] = (
            "{} ({})".format(_segment.name, _component), RGB)
del _segment, _channel, _component


def channel_name(channel: int) -> str:
    entry = CHANNELS.get(channel)
    if entry:
        return entry[0]
    block = block_of(channel)
    if block:
        return "{} LED {}".format(block.name, channel - block.first + 1)
    return "Channel {}".format(channel)


# --------------------------------------------------------------------------
# Effect encoding
# --------------------------------------------------------------------------
# xLights stores an effect's brightness percentage; the vehicle reads the byte.
# The percentages below are the ones bound to the Tesla hotkeys in
# xlights_keybindings.xml, and are documented in README.md under "Ramping light
# channels" and "Definitions for closure movements".

# percent -> (action, ramp duration in ms)
RAMP_CODES: Dict[int, Tuple[str, int]] = {
    0: ("off", 0),
    10: ("off", 500),
    20: ("off", 1000),
    30: ("off", 2000),
    70: ("on", 500),
    80: ("on", 1000),
    90: ("on", 2000),
    100: ("on", 0),
}

# percent -> closure movement
CLOSURE_CODES: Dict[int, str] = {
    0: "Idle",
    25: "Open",
    50: "Dance",
    75: "Close",
    100: "Stop",
}


# README.md: "any brightness setting above 50% will set the light to ON and
# otherwise it will be OFF". 50% of a 255-wide byte is 127.5.
ON_THRESHOLD = 127

# A shared-output light has to sit solid for at least this long before it is
# worth telling the author that their blinking will not be visible.
MIN_SOLID_MS = 1000

# README.md, "Ramping light channels", gives two guarantees and nothing in
# between: an effect at least 50 ms longer than its ramp is guaranteed to
# reach the setpoint, and one at least 100 ms shorter is guaranteed not to.
# Between those two the documentation promises nothing, which is where a light
# doing something the author did not expect tends to come from --
# https://github.com/teslamotors/light-show/issues/89 reads that way.
RAMP_REACH_MARGIN_MS = 50
RAMP_MISS_MARGIN_MS = 100


def to_percent(value: int) -> int:
    """Convert a raw .fseq byte back to the xLights brightness percentage."""
    return int(round(value * 100.0 / 255.0))


# --------------------------------------------------------------------------
# Vehicle profiles
# --------------------------------------------------------------------------

BOOLEAN = "boolean"     # snaps between off and on
RAMPING = "ramping"     # honours the ramp codes above
FULL = "full"           # arbitrary brightness setpoint
ABSENT = "absent"       # no such light on this vehicle
SLAVED = "slaved"       # the light exists but follows another channel


@dataclasses.dataclass
class OrGroup:
    """Several xLights channels driving one physical output."""

    name: str
    channels: Tuple[int, ...]
    readme: str


@dataclasses.dataclass
class BuildVariant:
    """A build of a vehicle that is wired differently from the rest.

    README.md documents these by build date or option rather than by model --
    "Model 3 built before October 2020" is a different car to the tool even
    though the owner calls it a Model 3.  A variant states only its
    differences; everything else comes from the parent profile.
    """

    key: str
    label: str
    readme: str
    # Applied on top of the parent profile.
    kinds: Dict[int, str] = dataclasses.field(default_factory=dict)
    or_groups: Tuple["OrGroup", ...] = ()
    notes: Tuple[str, ...] = ()
    slaved: Dict[int, str] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class VehicleProfile:
    key: str
    label: str
    # Channel behaviour. Channels absent from this map behave as BOOLEAN.
    kinds: Dict[int, str]
    or_groups: Tuple[OrGroup, ...] = ()
    # follower channel -> channel whose effect defines the ramp duration
    ramp_leaders: Dict[int, int] = dataclasses.field(default_factory=dict)
    # channel -> the configuration in which the light is missing
    optional_hardware: Dict[int, str] = dataclasses.field(default_factory=dict)
    notes: Tuple[str, ...] = ()
    # Builds of this vehicle that behave differently, see BuildVariant.
    variants: Tuple[BuildVariant, ...] = ()
    # channel -> what drives the light instead, for SLAVED channels
    slaved: Dict[int, str] = dataclasses.field(default_factory=dict)
    # Doors whose movement makes a moving window risky; see
    # PINCH_DOOR_CHANNELS. Empty for every vehicle that has no powered doors.
    pinch_doors: Tuple[int, ...] = ()


def _merge_text(*maps: Dict[int, str]) -> Dict[int, str]:
    """Same as _merge; named apart so the intent at each call site is clear."""
    merged: Dict[int, str] = {}
    for entry in maps:
        merged.update(entry)
    return merged


def _merge(*maps: Dict[int, str]) -> Dict[int, str]:
    """Combine channel maps; later entries win. Keys are ints, so dict(**) is out."""
    merged: Dict[int, str] = {}
    for entry in maps:
        merged.update(entry)
    return merged


# Shared between Model S, X, 3 and Y: the headlight beams ramp, and the rear
# lighting is boolean.  README.md, "Light Channels with Brightness Control".
_BEAMS_RAMP = {1: RAMPING, 2: RAMPING, 3: RAMPING, 4: RAMPING}

# README.md, "Other notes": "Moving Windows during Model X door movement can
# cause false pinch detections, stopping the light show." The doors in
# question are the powered ones a Model X has and nothing else does, so this
# is the one closure rule whose consequence is the whole show ending rather
# than one closure misbehaving.
PINCH_DOOR_CHANNELS = (31, 32, 33, 34)
WINDOW_CHANNELS = (37, 38, 39, 40)

# Side markers are only fitted in North America, and rear fog only outside it
# (plus North American Model X).  README.md, "Light channel mapping details".
_MARKER_HARDWARE = {
    19: "vehicles outside North America (side markers are a North America fitment)",
    20: "vehicles outside North America (side markers are a North America fitment)",
}

_MODEL_S = VehicleProfile(
    key="models",
    label="Model S (2021+)",
    kinds=_merge(_BEAMS_RAMP, {
        5: BOOLEAN, 6: BOOLEAN,          # Signature is boolean on S/X
        7: RAMPING, 8: RAMPING,          # Channels 4-6 ramp, individually driven
        9: RAMPING, 10: RAMPING,
        11: RAMPING, 12: RAMPING,
        13: BOOLEAN, 14: BOOLEAN,        # Front turn is boolean on S/X
        31: ABSENT, 32: ABSENT,          # no falcon doors
        33: ABSENT, 34: ABSENT,          # no powered front doors
    }),
    or_groups=(
        OrGroup("Left aux park + side marker", (17, 19), "Side Markers and Aux Park"),
        OrGroup("Right aux park + side marker", (18, 20), "Side Markers and Aux Park"),
    ),
    # Channel 4 is the ramp leader on every platform.
    ramp_leaders={9: 7, 11: 7, 10: 8, 12: 8},
    optional_hardware=_merge(_MARKER_HARDWARE, {
        29: "North America vehicles (rear fog is a non-North America fitment)",
    }),
)

_MODEL_X = dataclasses.replace(
    _MODEL_S,
    key="modelx",
    label="Model X (2021+)",
    kinds=_merge(_MODEL_S.kinds, {
        31: BOOLEAN, 32: BOOLEAN,        # falcon doors
        33: BOOLEAN, 34: BOOLEAN,        # powered front doors
        42: ABSENT, 43: ABSENT,          # no powered door handles
        44: ABSENT, 45: ABSENT,
    }),
    # Rear fog is fitted to Model X in North America too.
    optional_hardware=_merge(_MARKER_HARDWARE),
    pinch_doors=PINCH_DOOR_CHANNELS,
    notes=(
        "Aux park and side markers are assumed to share the Model S per-side "
        "pairing; README.md does not state Model X separately.",
        "One owner reports that on a 2022 Model X Plaid the Front Turn and "
        "Aux Park channels are the same lamp -- orange from Front Turn, "
        "white from Aux Park, a dimmer mix from both. That is a single "
        "report and is not modelled here; see issue #76, and "
        "tools/channel_probe.py --group front-turn-aux-park to check your "
        "own car.",
    ),
)

# README.md, "Tail lights and License Plate Lights": on Model 3 built before
# October 2020 the left tail, right tail and license plate lights operate
# together, driven by (Left tail || Right tail), and the License Plate channel
# has no effect at all.  The README names Model 3 only, so this is not applied
# to Model Y.
_MODEL_3_PRE_OCT_2020 = BuildVariant(
    key="pre-oct-2020",
    label="Model 3 built before October 2020",
    readme="Tail lights and License Plate Lights",
    kinds={30: SLAVED},
    slaved={30: "the tail lights"},
    or_groups=(
        OrGroup(
            "Left tail + right tail (also drives the license plate lights)",
            (26, 27),
            "Tail lights and License Plate Lights",
        ),
    ),
    notes=(
        "The License Plate channel has no effect on this build; the license "
        "plate lights follow the tail lights instead.",
    ),
)

_MODEL_3 = VehicleProfile(
    key="model3",
    label="Model 3",
    kinds=_merge(_BEAMS_RAMP, {
        5: RAMPING, 6: RAMPING,          # Signature ramps on 3/Y
        7: RAMPING, 8: RAMPING,          # Channels 4-6, but see or_groups
        9: RAMPING, 10: RAMPING,
        11: RAMPING, 12: RAMPING,
        13: RAMPING, 14: RAMPING,        # Front turn ramps on 3/Y
        31: ABSENT, 32: ABSENT,
        33: ABSENT, 34: ABSENT,
        42: ABSENT, 43: ABSENT,
        44: ABSENT, 45: ABSENT,
    }),
    or_groups=(
        OrGroup("Left Channels 4-6", (7, 9, 11), "Ramping Channels 4-6"),
        OrGroup("Right Channels 4-6", (8, 10, 12), "Ramping Channels 4-6"),
        OrGroup(
            "Aux park + side markers (all four)",
            (17, 18, 19, 20),
            "Side Markers and Aux Park",
        ),
    ),
    ramp_leaders={9: 7, 11: 7, 10: 8, 12: 8},
    optional_hardware=_merge(_MARKER_HARDWARE, {
        15: "Model 3 Standard Range + (no front fog fitted)",
        16: "Model 3 Standard Range + (no front fog fitted)",
        17: "Model 3 Standard Range + (no aux park fitted)",
        18: "Model 3 Standard Range + (no aux park fitted)",
        29: "North America vehicles (rear fog is a non-North America fitment)",
        41: "vehicles without a power liftgate",
    }),
    notes=(
        "On Model 3 built before October 2020 the left tail, right tail and "
        "license plate lights operate together, and the License Plate channel "
        "has no effect at all.",
        "Owners report that on the refreshed Model 3 (\"Highland\") the Inner "
        "and Outer Main Beam channels are the other way round and Signature "
        "does nothing, and a Model 3 owner reports the same beam swap on a "
        "2023 car. Two accounts on two builds, neither confirmed and neither "
        "modelled here; see issues #113 and #72, and "
        "tools/channel_probe.py --group headlights to check your own car.",
    ),
    variants=(_MODEL_3_PRE_OCT_2020,),
)

_MODEL_Y = dataclasses.replace(
    _MODEL_3,
    key="modely",
    label="Model Y",
    # Front fog, aux park and a power liftgate are fitted across the Model Y
    # range, so only the region-dependent lights stay optional.
    optional_hardware=_merge(_MARKER_HARDWARE, {
        29: "North America vehicles (rear fog is a non-North America fitment)",
    }),
    notes=(),
    # The tail light rule above is documented for Model 3 only.
    variants=(),
)

_CYBERTRUCK = VehicleProfile(
    key="cybertruck",
    label="Cybertruck",
    kinds=_merge(_BEAMS_RAMP, {
        5: ABSENT, 6: ABSENT,            # no signature
        7: ABSENT, 8: ABSENT,            # no channels 4-6
        9: ABSENT, 10: ABSENT,
        11: ABSENT, 12: ABSENT,
        13: RAMPING, 14: RAMPING,        # front turn ramps
        19: RAMPING, 20: RAMPING,        # front side markers ramp
        23: FULL, 24: FULL,              # rear turn
        25: FULL,                        # brake
        31: ABSENT, 32: ABSENT,
        33: ABSENT, 34: ABSENT,
        42: ABSENT, 43: ABSENT,
        44: ABSENT, 45: ABSENT,
    }),
    notes=(
        "Channel 41 drives the powered frunk rather than a liftgate.",
        "Left/Right Tail drive the reverse lights, and Left/Right Side "
        "Repeater drive the rear side markers.",
    ),
)

VEHICLES: Dict[str, VehicleProfile] = {
    p.key: p for p in (_MODEL_S, _MODEL_X, _MODEL_3, _MODEL_Y, _CYBERTRUCK)
}


def kind_of(profile: VehicleProfile, channel: int) -> str:
    return profile.kinds.get(channel, BOOLEAN)


# --------------------------------------------------------------------------
# .fseq reading
# --------------------------------------------------------------------------


class ShowError(Exception):
    pass


@dataclasses.dataclass
class Show:
    channel_count: int
    frame_count: int
    step_time_ms: int
    data: bytes

    @property
    def duration_ms(self) -> int:
        return self.frame_count * self.step_time_ms

    def first_lit_ms(self) -> Optional[int]:
        """When anything first comes on.

        A show can begin with darkness on purpose -- "The Arrival" in
        examples/ is dark for its first 5.3 s while the track opens -- so this
        is a fact to report rather than a fault. It is the number to compare
        against when a show looks like it starts late:
        https://github.com/teslamotors/light-show/issues/78.
        """
        width = self.channel_count
        for frame in range(self.frame_count):
            if any(self.data[frame * width:(frame + 1) * width]):
                return frame * self.step_time_ms
        return None

    def series(self, channel: int) -> bytes:
        """All frames for one 1-based channel, as raw bytes."""
        return self.data[channel - 1::self.channel_count]


def read_fseq(path: str) -> Show:
    """Parse a V2 uncompressed .fseq, the format the vehicle accepts."""
    with open(path, "rb") as handle:
        header = handle.read(24)
        if len(header) < 24 or header[:4] != b"PSEQ":
            raise ShowError("Unknown file format, expected FSEQ v2.0")
        offset, = struct.unpack("<H", header[4:6])
        channel_count, frame_count, step_time = struct.unpack("<IIB", header[10:19])
        compression, = struct.unpack("<B", header[20:21])
        if compression != 0:
            raise ShowError("Expected file format to be V2 Uncompressed")
        if channel_count not in (48, 200):
            raise ShowError(
                "Expected 48 or 200 channels, got {}".format(channel_count))
        if frame_count < 1 or step_time < 15:
            raise ShowError("Unknown file format, expected FSEQ v2.0")
        handle.seek(offset)
        data = handle.read(channel_count * frame_count)
    if len(data) < channel_count * frame_count:
        raise ShowError(
            "File is truncated: expected {} bytes of frame data, got {}".format(
                channel_count * frame_count, len(data)))
    return Show(channel_count, frame_count, step_time, data)


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

ERROR = "error"
WARNING = "warning"
INFO = "info"

_SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}


@dataclasses.dataclass
class Finding:
    severity: str
    code: str
    summary: str
    detail: str
    channels: Tuple[int, ...] = ()
    first_at_ms: Optional[int] = None
    occurrences: int = 1

    def as_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "summary": self.summary,
            "detail": self.detail,
            "channels": [
                {"channel": c, "name": channel_name(c)} for c in self.channels
            ],
            "first_at_ms": self.first_at_ms,
            "occurrences": self.occurrences,
        }


@dataclasses.dataclass
class Run:
    """A stretch of frames holding one constant value."""

    value: int
    start_frame: int
    frames: int

    @property
    def percent(self) -> int:
        return to_percent(self.value)


def runs_of(series: Sequence[int]) -> List[Run]:
    out: List[Run] = []
    if not series:
        return out
    current = Run(series[0], 0, 1)
    for index in range(1, len(series)):
        value = series[index]
        if value == current.value:
            current.frames += 1
        else:
            out.append(current)
            current = Run(value, index, 1)
    out.append(current)
    return out


def _ms(frames: int, step_time_ms: int) -> int:
    return frames * step_time_ms


def _timestamp(frame: int, step_time_ms: int) -> int:
    return frame * step_time_ms


def _check_ramp_reachability(
    show: Show, profile: VehicleProfile, findings: List[Finding]
) -> None:
    """Ramping lights need an effect longer than the ramp to reach full output.

    On Model S the front turn signals and signature lights are boolean, so a
    two-frame effect reads as a crisp flash in the xLights preview.  On Model 3
    the same channels ramp, and that two-frame effect only gets a few percent
    of the way to full brightness - which is why the flash at the start of the
    show in issue #42 was barely visible on the car.
    """
    for channel in sorted(CHANNELS):
        if CHANNELS[channel][1] != LIGHT:
            continue
        if kind_of(profile, channel) != RAMPING:
            continue
        # The sequencer preview always models a Model S. A channel that is
        # boolean there but ramping here is a difference the author cannot see.
        preview_is_instant = kind_of(_MODEL_S, channel) == BOOLEAN

        short: List[Tuple[Run, str, int, int]] = []
        unsure: List[Tuple[Run, str, int, int]] = []
        for run in runs_of(show.series(channel)):
            code = RAMP_CODES.get(run.percent)
            if code is None:
                continue
            action, ramp_ms = code
            if ramp_ms == 0:
                continue  # instant effects have nothing to truncate
            held_ms = _ms(run.frames, show.step_time_ms)
            if held_ms <= ramp_ms - RAMP_MISS_MARGIN_MS:
                short.append((run, action, ramp_ms, held_ms))
            elif held_ms < ramp_ms + RAMP_REACH_MARGIN_MS:
                unsure.append((run, action, ramp_ms, held_ms))

        if unsure:
            run, action, ramp_ms, held_ms = unsure[0]
            findings.append(Finding(
                severity=INFO,
                code="ramp-duration-indeterminate",
                summary="{name}: {count} ramping effect(s) are held for a "
                        "length README.md does not promise a result "
                        "for".format(
                            name=channel_name(channel), count=len(unsure)),
                detail=(
                    "An effect at least {reach} ms longer than its ramp is "
                    "guaranteed to reach the setpoint, and one at least "
                    "{miss} ms shorter is guaranteed not to. The first of "
                    "these is a 'turn {action}; {ramp} ms' effect held for "
                    "{held} ms, which is neither, so what the light does is "
                    "not specified. Hold it for {need} ms or more, or "
                    "{under} ms or less, depending on which you want."
                ).format(reach=RAMP_REACH_MARGIN_MS,
                         miss=RAMP_MISS_MARGIN_MS, action=action,
                         ramp=ramp_ms, held=held_ms,
                         need=ramp_ms + RAMP_REACH_MARGIN_MS,
                         under=ramp_ms - RAMP_MISS_MARGIN_MS),
                channels=(channel,),
                first_at_ms=_timestamp(run.start_frame, show.step_time_ms),
                occurrences=len(unsure),
            ))

        if not short:
            continue

        # Report against the effect that gets furthest from its setpoint.
        run, action, ramp_ms, held_ms = min(short, key=lambda s: s[3] / s[2])
        reach = int(round(100.0 * held_ms / ramp_ms))
        # Only an effect that dies well short of its setpoint looks wrong; one
        # that gets most of the way there is a rounding detail, not a defect.
        if reach < 50:
            severity = ERROR if preview_is_instant else WARNING
        else:
            severity = INFO

        if preview_is_instant:
            preview_note = (
                "{name} is boolean on Model S, so the preview renders these "
                "effects as an instant switch. On {label} the same effect "
                "ramps instead.".format(
                    name=channel_name(channel), label=profile.label)
            )
        else:
            preview_note = (
                "{name} ramps on {label}, and these effects end before the "
                "ramp they ask for has finished.".format(
                    name=channel_name(channel), label=profile.label)
            )

        findings.append(Finding(
            severity=severity,
            code="ramp-too-short",
            summary="{name}: {count} ramping effect(s) end before the ramp "
                    "completes on {label}".format(
                        name=channel_name(channel), count=len(short),
                        label=profile.label),
            detail=(
                "{preview} The shortest is a 'turn {action}; {ramp} ms' effect "
                "held for only {held} ms, so the light gets about {reach}% of "
                "the way to its setpoint before the effect ends. Hold the "
                "effect for at least {need} ms to reach the setpoint, or use "
                "an instant effect (0% or 100%) so it looks the same on every "
                "vehicle. See README.md, \"Ramping light channels\"."
            ).format(
                preview=preview_note,
                action=action,
                ramp=ramp_ms,
                held=held_ms,
                reach=reach,
                need=ramp_ms + 50,
            ),
            channels=(channel,),
            first_at_ms=_timestamp(run.start_frame, show.step_time_ms),
            occurrences=len(short),
        ))


def _or_union(show: Show, channels: Sequence[int]) -> List[int]:
    """Per-frame maximum across the channels sharing one physical output."""
    serieses = [show.series(c) for c in channels]
    if len(serieses) == 1:
        return list(serieses[0])
    return [max(values) for values in zip(*serieses)]


def _longest_on_span(union: Sequence[int]) -> Tuple[int, int]:
    """Length and start frame of the longest stretch where the output is lit."""
    longest = longest_start = 0
    current = start = 0
    for frame, value in enumerate(union):
        if value > ON_THRESHOLD:
            if current == 0:
                start = frame
            current += 1
            if current > longest:
                longest, longest_start = current, start
        else:
            current = 0
    return longest, longest_start


def _check_or_groups(
    show: Show, profile: VehicleProfile, findings: List[Finding]
) -> None:
    """Channels wired to one output cannot show the independent preview.

    Two separate problems fall out of this. The channels may be driven with
    different patterns, in which case the preview shows separate lights where
    the car has one; and the OR'd result may never go off, in which case a
    sequence that flashes in the preview sits solid on the car.
    """
    for group in profile.or_groups:
        members = [c for c in group.channels if c <= show.channel_count]
        if len(members) < 2:
            continue
        serieses = {c: show.series(c) for c in members}
        used = [c for c in members if any(serieses[c])]
        if not used:
            continue  # group unused by this show

        # 1. Do the members disagree? Compare on/off state frame by frame.
        # Only meaningful once the show drives more than one of them: a group
        # whose other channels are empty has nothing to collapse together.
        disagreements = 0
        first_disagreement = None
        for frame, values in enumerate(zip(*(serieses[c] for c in members))):
            on = [v > ON_THRESHOLD for v in values]
            if any(on) and not all(on):
                disagreements += 1
                if first_disagreement is None:
                    first_disagreement = frame
        if disagreements and len(used) > 1:
            findings.append(Finding(
                severity=WARNING,
                code="or-group-collapse",
                summary="{} share one output on {}, but this show drives "
                        "them separately".format(group.name, profile.label),
                detail=(
                    "The sequencer animates these {count} channels as {count} "
                    "separate lights. On {label} they are wired to one output, "
                    "so for {frames} frames ({ms} ms) the preview shows only "
                    "part of the group lit while the car lights the whole "
                    "shared lamp. Whichever of these channels you sequence, "
                    "the light appears in the same place on the car. See "
                    "README.md, \"{readme}\"."
                ).format(
                    count=len(members),
                    label=profile.label,
                    frames=disagreements,
                    ms=_ms(disagreements, show.step_time_ms),
                    readme=group.readme,
                ),
                channels=tuple(members),
                first_at_ms=_timestamp(first_disagreement, show.step_time_ms),
                occurrences=disagreements,
            ))

        # 2. Does the OR'd output ever get a chance to go off?
        # A group only glows unexpectedly when *every* member has some off time
        # inside the span yet their union has none - the case README.md warns
        # about with its "ord_channel_not_ok" example. If any member is simply
        # held on across the span then the solid output is what was asked for.
        union = _or_union(show, members)
        longest, longest_start = _longest_on_span(union)
        solid_ms = _ms(longest, show.step_time_ms)
        if solid_ms < MIN_SOLID_MS:
            continue
        span = slice(longest_start, longest_start + longest)
        states = [[v > ON_THRESHOLD for v in serieses[c][span]] for c in members]
        every_member_rests = all(not all(state) for state in states)
        someone_blinks = any(any(state) and not all(state) for state in states)
        if not (every_member_rests and someone_blinks):
            continue
        findings.append(Finding(
            severity=ERROR,
            code="or-group-never-off",
            summary="{} stays lit for {} ms on {} even though every channel "
                    "in it goes off".format(
                        group.name, solid_ms, profile.label),
            detail=(
                "These channels share one output on {label}, so the lamp is on "
                "whenever any of them is on. Each channel does go off during "
                "this stretch, but never at the same time as the others, so "
                "the blinking visible in the preview becomes a single {ms} ms "
                "glow on the car. Leave a gap that is blank on every channel "
                "in the group to make the light actually flash. See README.md, "
                "\"Light channel mapping recommendations\"."
            ).format(label=profile.label, ms=solid_ms),
            channels=tuple(members),
            first_at_ms=_timestamp(longest_start, show.step_time_ms),
            occurrences=1,
        ))


def _check_ramp_leaders(
    show: Show, profile: VehicleProfile, findings: List[Finding]
) -> None:
    """Channels 5 and 6 take their ramp duration from Channel 4.

    If Channel 4 has no effect at the moment Channel 5 or 6 starts ramping, the
    duration is whatever Channel 4 last defined, which is rarely what the
    author saw in the preview.
    """
    for follower, leader in sorted(profile.ramp_leaders.items()):
        if max(follower, leader) > show.channel_count:
            continue
        follower_series = show.series(follower)
        leader_series = show.series(leader)
        offenders = 0
        first = None
        for run in runs_of(follower_series):
            code = RAMP_CODES.get(run.percent)
            if code is None or code[1] == 0:
                continue  # instant effects do not need a duration
            if leader_series[run.start_frame] == 0:
                offenders += 1
                if first is None:
                    first = run.start_frame
        if offenders:
            findings.append(Finding(
                severity=WARNING,
                code="ramp-leader-missing",
                summary="{} ramps {} time(s) while {} has no effect to define "
                        "the duration".format(
                            channel_name(follower), offenders,
                            channel_name(leader)),
                detail=(
                    "On every vehicle the ramp duration for Channels 4-6 comes "
                    "from the Channel 4 effect, never from Channel 5 or 6. With "
                    "{leader} empty, these ramps run for whatever duration "
                    "{leader} last specified. Place a matching ramping effect "
                    "on {leader} - a 'turn off' ramp works even when you do not "
                    "want {leader} lit. See README.md, \"Ramping Channels 4-6\"."
                ).format(leader=channel_name(leader)),
                channels=(follower, leader),
                first_at_ms=_timestamp(first, show.step_time_ms),
                occurrences=offenders,
            ))


def _check_absent_channels(
    show: Show, profile: VehicleProfile, findings: List[Finding]
) -> None:
    """Channels the vehicle has no light for, or only has in some builds."""
    for channel in sorted(CHANNELS):
        if channel > show.channel_count:
            continue
        # Interior RGB is reported per segment by analyze_interior(), not per
        # channel; a colour is three channels and "Left Rear RGB (green) is
        # not fitted" would be three findings saying one thing.
        if CHANNELS[channel][1] == RGB:
            continue
        series = show.series(channel)
        if not any(series):
            continue
        first_on = next(i for i, v in enumerate(series) if v)
        if kind_of(profile, channel) == SLAVED:
            findings.append(Finding(
                severity=INFO,
                code="channel-has-no-effect",
                summary="{} has no effect on {}".format(
                    channel_name(channel), profile.label),
                detail=(
                    "The light is fitted, but on this build it follows {by} "
                    "rather than its own channel, so driving it here changes "
                    "nothing. Sequence {by} instead."
                ).format(by=profile.slaved.get(channel, "another channel")),
                channels=(channel,),
                first_at_ms=_timestamp(first_on, show.step_time_ms),
            ))
        elif kind_of(profile, channel) == ABSENT:
            findings.append(Finding(
                severity=INFO,
                code="channel-not-present",
                summary="{} is not fitted to {}".format(
                    channel_name(channel), profile.label),
                detail=(
                    "This show drives the channel, but {label} has no such "
                    "light or closure and no other output is substituted for "
                    "it. The commands are ignored on this vehicle."
                ).format(label=profile.label),
                channels=(channel,),
                first_at_ms=_timestamp(first_on, show.step_time_ms),
            ))
        elif channel in profile.optional_hardware:
            findings.append(Finding(
                severity=INFO,
                code="channel-optional-hardware",
                summary="{} is missing on some {} builds".format(
                    channel_name(channel), profile.label),
                detail=(
                    "This channel does nothing on {missing}. Avoid relying on "
                    "it for beats that need to land on every car."
                ).format(missing=profile.optional_hardware[channel]),
                channels=(channel,),
                first_at_ms=_timestamp(first_on, show.step_time_ms),
            ))


def _check_boolean_ramps(
    show: Show, profile: VehicleProfile, findings: List[Finding]
) -> None:
    """Ramp codes placed on channels that cannot ramp on this vehicle."""
    for channel in sorted(CHANNELS):
        if channel > show.channel_count or CHANNELS[channel][1] != LIGHT:
            continue
        if kind_of(profile, channel) != BOOLEAN:
            continue
        ramped = 0
        first = None
        for run in runs_of(show.series(channel)):
            code = RAMP_CODES.get(run.percent)
            if code is not None and code[1] != 0:
                ramped += 1
                if first is None:
                    first = run.start_frame
        if ramped:
            findings.append(Finding(
                severity=INFO,
                code="ramp-ignored",
                summary="{} cannot ramp on {}; {} ramping effect(s) snap "
                        "instead".format(
                            channel_name(channel), profile.label, ramped),
                detail=(
                    "Brightness above 50% switches the light fully on and "
                    "anything below switches it off, so these effects look "
                    "instant here even though they ramp on other vehicles."
                ),
                channels=(channel,),
                first_at_ms=_timestamp(first, show.step_time_ms),
                occurrences=ramped,
            ))


# --------------------------------------------------------------------------
# Closure command budget
# --------------------------------------------------------------------------
# https://github.com/teslamotors/light-show/issues/50 was filed when a show
# overran the old whole-show command limit ("more than 241%").  That limit is
# gone -- README.md, "General Limitations of Custom Shows" says the limit on
# the number of commands has been removed -- but the per-closure actuation
# limits in the closure table are still real, still counted separately for
# each individual closure, and nothing in this repository counts them.
#
# README.md, "Closures Command Limitations": "All closures have actuation
# limits listed in the table above. Only Open, Close, and Dance count towards
# the actuation limits."

# Percentages come from CLOSURE_CODES, so the two cannot drift apart.
_CLOSURE_BY_NAME = {name: percent for percent, name in CLOSURE_CODES.items()}
OPEN = _CLOSURE_BY_NAME["Open"]
DANCE = _CLOSURE_BY_NAME["Dance"]
CLOSE = _CLOSURE_BY_NAME["Close"]
STOP = _CLOSURE_BY_NAME["Stop"]

# Idle and Stop are free; everything else is an actuation.
COUNTED_COMMANDS = (OPEN, DANCE, CLOSE)

# README.md, "Other notes": dancing for ~30 s or less per show is recommended
# before thermal limits stop the closure.
DANCE_THERMAL_MS = 30000

# The README's example of commands "spaced very close together" is 20 ms. It
# does not give a threshold, so this one is a judgement, not a documented rule.
BUNCHED_COMMAND_MS = 100

# "Closure Movement Durations" is headed "Approximate", and #72 reports a
# liftgate opening in 12 s where the table says 14. A Dance that clears the
# documented time by a hair is therefore not safe: it works on the car it was
# authored on and fails on the next one.
#
# https://github.com/teslamotors/light-show/issues/128 is that failure, filmed:
# the trunk opens, stops and closes again. The show behind it asks the liftgate
# to Dance 14.5 s after its Open against a documented 14 s -- 1.04x, and the
# only gap below 1.34x in examples/ that is not already under the documented
# time. A quarter is the margin that separates the two.
DANCE_MARGIN = 0.25


@dataclasses.dataclass
class ClosureFamily:
    """A row of the closure table in README.md."""

    name: str
    # "Command Limit Per Show", counted separately for each closure.
    limit: int
    # "Supports Dance?"
    dance: bool
    # "Closure Movement Durations", the approximate time to reach open.
    open_ms: int
    # Windows are the documented exception to "Dance needs an open closure".
    dance_needs_open: bool = True
    # "Closure Movement Durations" again, for the way back.
    close_ms: int = 0

    @property
    def longest_movement_ms(self) -> int:
        return max(self.open_ms, self.close_ms)


_FALCON_DOORS = ClosureFamily("Falcon Doors", limit=6, dance=True,
                              open_ms=20000, close_ms=8000)
_FRONT_DOORS = ClosureFamily("Front Doors", limit=6, dance=False,
                             open_ms=22000, close_ms=3000)
_MIRRORS = ClosureFamily("Mirrors", limit=20, dance=False, open_ms=2000,
                         close_ms=2000)
_WINDOWS = ClosureFamily("Windows", limit=6, dance=True, open_ms=4000,
                         dance_needs_open=False, close_ms=4000)
_LIFTGATE = ClosureFamily("Liftgate", limit=6, dance=True, open_ms=14000,
                          close_ms=4000)
_DOOR_HANDLES = ClosureFamily("Door Handles", limit=20, dance=False,
                              open_ms=2000, close_ms=2000)
_CHARGE_PORT = ClosureFamily("Charge Port", limit=3, dance=True, open_ms=2000,
                             close_ms=2000)


CLOSURE_FAMILIES: Dict[int, ClosureFamily] = {
    31: _FALCON_DOORS, 32: _FALCON_DOORS,
    33: _FRONT_DOORS, 34: _FRONT_DOORS,
    35: _MIRRORS, 36: _MIRRORS,
    37: _WINDOWS, 38: _WINDOWS, 39: _WINDOWS, 40: _WINDOWS,
    41: _LIFTGATE,
    42: _DOOR_HANDLES, 43: _DOOR_HANDLES, 44: _DOOR_HANDLES,
    45: _DOOR_HANDLES,
    46: _CHARGE_PORT,
}


@dataclasses.dataclass
class ClosureUsage:
    """What a show spends on one individual closure."""

    channel: int
    family: ClosureFamily
    commands: List[Run]                 # the Open/Close/Dance runs, in order
    dance_ms: int

    @property
    def count(self) -> int:
        return len(self.commands)

    @property
    def over_by(self) -> int:
        return max(0, self.count - self.family.limit)

    def as_dict(self) -> dict:
        return {
            "channel": self.channel,
            "name": channel_name(self.channel),
            "family": self.family.name,
            "commands": self.count,
            "limit": self.family.limit,
            "over_by": self.over_by,
            "dance_ms": self.dance_ms,
        }


def closure_usage(show: Show) -> List[ClosureUsage]:
    """Count the actuations this show spends on every closure."""
    usage: List[ClosureUsage] = []
    for channel in sorted(CLOSURE_FAMILIES):
        if channel > show.channel_count:
            continue
        runs = runs_of(show.series(channel))
        commands = [r for r in runs if r.percent in COUNTED_COMMANDS]
        dance_ms = sum(r.frames for r in runs if r.percent == DANCE) \
            * show.step_time_ms
        usage.append(ClosureUsage(
            channel=channel,
            family=CLOSURE_FAMILIES[channel],
            commands=commands,
            dance_ms=dance_ms,
        ))
    return usage


def analyze_closures(show: Show) -> List[Finding]:
    """Report closures that overrun their documented actuation budget."""
    findings: List[Finding] = []
    for entry in closure_usage(show):
        if not entry.commands:
            continue
        _check_closure_budget(show, entry, findings)
        _check_closure_dance(show, entry, findings)
        _check_bunched_commands(show, entry, findings)
    findings.sort(key=lambda f: (
        _SEVERITY_ORDER[f.severity],
        f.first_at_ms if f.first_at_ms is not None else 0,
    ))
    return findings


def _check_closure_budget(show: Show, entry: ClosureUsage,
                          findings: List[Finding]) -> None:
    name = channel_name(entry.channel)
    limit = entry.family.limit
    if entry.over_by:
        # The command that first goes past the limit is the interesting one.
        overrun = entry.commands[limit]
        findings.append(Finding(
            severity=WARNING,
            code="closure-limit-exceeded",
            summary="{} uses {} commands; the limit is {} per show".format(
                name, entry.count, limit),
            detail=(
                "README.md gives {family} an actuation limit of {limit} per "
                "show, counted separately for each individual closure, and "
                "only Open, Close and Dance count towards it. This show "
                "spends {count}, so {over} past the documented budget and "
                "cannot be relied on."
            ).format(family=entry.family.name, limit=limit,
                     count=entry.count,
                     over=_plural(entry.over_by, "command", verb=True)),
            channels=(entry.channel,),
            first_at_ms=_timestamp(overrun.start_frame, show.step_time_ms),
            occurrences=entry.over_by,
        ))
    elif entry.count == limit:
        findings.append(Finding(
            severity=INFO,
            code="closure-limit-reached",
            summary="{} is exactly at its {}-command limit".format(
                name, limit),
            detail=(
                "There is no room left for another Open, Close or Dance on "
                "this closure. Adding one would push the show past the "
                "documented budget."
            ),
            channels=(entry.channel,),
            first_at_ms=_timestamp(entry.commands[0].start_frame,
                                   show.step_time_ms),
            occurrences=entry.count,
        ))


def _check_closure_dance(show: Show, entry: ClosureUsage,
                         findings: List[Finding]) -> None:
    """Dance requests the closure will not honour."""
    family = entry.family
    dances = [r for r in entry.commands if r.percent == DANCE]
    if not dances:
        return

    name = channel_name(entry.channel)
    if not family.dance:
        findings.append(Finding(
            severity=WARNING,
            code="closure-dance-unsupported",
            summary="{} does not support Dance; {} will not move it".format(
                name, _plural(len(dances), "request")),
            detail=(
                'README.md marks {family} as "-" in the "Supports Dance?" '
                "column. Use Open and Close requests to make this closure "
                "move during the show. Each of those still counts against "
                "the {limit}-command limit."
            ).format(family=family.name, limit=family.limit),
            channels=(entry.channel,),
            first_at_ms=_timestamp(dances[0].start_frame, show.step_time_ms),
            occurrences=len(dances),
        ))
        return

    if family.dance_needs_open:
        _check_dance_follows_open(show, entry, dances, findings)

    if entry.dance_ms > DANCE_THERMAL_MS:
        findings.append(Finding(
            severity=INFO,
            code="closure-dance-thermal",
            summary="{} dances for {}, longer than the recommended "
                    "30 s".format(name, _format_time(entry.dance_ms)),
            detail=(
                "README.md recommends dancing for ~30 s or less per show. "
                "Past the thermal limit the closure stops moving until it "
                "cools down, and how soon that happens depends on ambient "
                "temperature among other things."
            ),
            channels=(entry.channel,),
            first_at_ms=_timestamp(dances[0].start_frame, show.step_time_ms),
        ))


def _check_dance_follows_open(show: Show, entry: ClosureUsage,
                              dances: Sequence[Run],
                              findings: List[Finding]) -> None:
    """README.md: a closure only honours Dance once it is already open."""
    name = channel_name(entry.channel)
    open_ms = entry.family.open_ms
    last_open: Optional[Run] = None
    unopened: List[Run] = []
    early: List[Tuple[Run, int]] = []

    for run in entry.commands:
        if run.percent == OPEN:
            last_open = run
        elif run.percent == CLOSE:
            last_open = None
        elif run.percent == DANCE:
            if last_open is None:
                unopened.append(run)
                continue
            gap = (run.start_frame - last_open.start_frame) * show.step_time_ms
            if gap < open_ms * (1 + DANCE_MARGIN):
                early.append((run, gap))

    if unopened:
        findings.append(Finding(
            severity=WARNING,
            code="closure-dance-without-open",
            summary="{} is asked to Dance while closed, {}".format(
                name, _plural(len(unopened), "time")),
            detail=(
                "README.md: closures other than windows will not honour a "
                "Dance request unless the closure is already open. Add an "
                "Open ahead of the Dance, and leave about {open_s} s for the "
                "movement to finish."
            ).format(open_s=open_ms // 1000),
            channels=(entry.channel,),
            first_at_ms=_timestamp(unopened[0].start_frame, show.step_time_ms),
            occurrences=len(unopened),
        ))

    if early:
        run, gap = early[0]
        wanted = int(open_ms * (1 + DANCE_MARGIN))
        findings.append(Finding(
            severity=INFO,
            code="closure-dance-early",
            summary="{} is asked to Dance {} after its Open, which takes "
                    "about {} s".format(
                        name, _format_time(gap), entry.family.open_ms // 1000),
            detail=(
                "A closure other than a window only honours Dance once it is "
                "already open, and the movement durations in README.md are "
                "approximate: #72 reports a liftgate opening in 12 s where "
                "the table says 14. Leaving only the documented time is "
                "therefore not enough, which is what "
                "https://github.com/teslamotors/light-show/issues/128 filmed "
                "-- the trunk opens, stops and closes again. Aim for {} or "
                "more between the Open and the Dance."
            ).format(_format_time(wanted)),
            channels=(entry.channel,),
            first_at_ms=_timestamp(run.start_frame, show.step_time_ms),
            occurrences=len(early),
        ))


def _check_bunched_commands(show: Show, entry: ClosureUsage,
                            findings: List[Finding]) -> None:
    """Commands too close together to move the closure, but still counted."""
    bunched = []
    for first, second in zip(entry.commands, entry.commands[1:]):
        gap = (second.start_frame - first.start_frame) * show.step_time_ms
        if gap < BUNCHED_COMMAND_MS:
            bunched.append((second, gap))
    if not bunched:
        return
    run, gap = bunched[0]
    findings.append(Finding(
        severity=INFO,
        code="closure-commands-bunched",
        summary="{} has {} less than {} ms after the previous one".format(
            channel_name(entry.channel), _plural(len(bunched), "command"),
            BUNCHED_COMMAND_MS),
        detail=(
            "README.md: commands spaced very close together will not cause "
            "much visible movement and use up the command limits quickly. "
            "The closest pair here is {gap} ms apart. The {threshold} ms "
            "threshold is this tool's judgement; the README only gives 20 ms "
            "as an example."
        ).format(gap=gap, threshold=BUNCHED_COMMAND_MS),
        channels=(entry.channel,),
        first_at_ms=_timestamp(run.start_frame, show.step_time_ms),
        occurrences=len(bunched),
    ))


# --------------------------------------------------------------------------
# Interior RGB analysis
# --------------------------------------------------------------------------
# These findings are about the show, not about one vehicle: README.md says the
# accent segments exist "on cars with Interior Accent Lights" without naming
# which builds those are, so there is nothing here to report per vehicle.


@dataclasses.dataclass
class SegmentUsage:
    """What a show does with one interior segment."""

    segment: InteriorSegment
    colours: int                        # distinct colours, black excluded
    changes: int                        # colour changes, black included
    lit_frames: int
    first_lit_ms: Optional[int]

    @property
    def lit(self) -> bool:
        return self.lit_frames > 0

    def as_dict(self) -> dict:
        return {
            "name": self.segment.name,
            "channels": list(self.segment.channels),
            "accent": self.segment.accent,
            "lit": self.lit,
            "colours": self.colours,
            "changes": self.changes,
            "lit_frames": self.lit_frames,
            "first_lit_ms": self.first_lit_ms,
        }


def interior_usage(show: Show) -> List[SegmentUsage]:
    """Measure every interior segment. Empty when the show has no cabin data."""
    if show.channel_count < INTERIOR_LAST_CHANNEL:
        return []

    usage: List[SegmentUsage] = []
    for segment in INTERIOR_SEGMENTS:
        red, green, blue = (show.series(c) for c in segment.channels)
        colours = set()
        changes = 0
        lit_frames = 0
        first_lit = None
        previous = None
        for frame in range(show.frame_count):
            colour = (red[frame], green[frame], blue[frame])
            if colour != previous:
                changes += 1
                previous = colour
            if colour != (0, 0, 0):
                colours.add(colour)
                lit_frames += 1
                if first_lit is None:
                    first_lit = frame
        usage.append(SegmentUsage(
            segment=segment,
            colours=len(colours),
            changes=changes,
            lit_frames=lit_frames,
            first_lit_ms=(None if first_lit is None
                          else _timestamp(first_lit, show.step_time_ms)),
        ))
    return usage


def analyze_interior(show: Show) -> List[Finding]:
    """Report what this show does, or could do, with the interior lights."""
    findings: List[Finding] = []
    usage = interior_usage(show)

    if not usage:
        # A 48-channel export predates the interior lights entirely.  This is
        # the answer to issue #49 for anyone whose show cannot reach them.
        findings.append(Finding(
            severity=INFO,
            code="interior-not-in-export",
            summary="This show has no interior lighting data",
            detail=(
                "The cabin is driven by channels {first}-{last}, which only "
                "exist in a {full}-channel export; this show has {count}. "
                "Re-create or import it in the current xLights show folder to "
                "reach the Center Front Display and the accent segments. See "
                'README.md, "Interior RGB Lights".'
            ).format(first=INTERIOR_FIRST_CHANNEL, last=INTERIOR_LAST_CHANNEL,
                     full=200, count=show.channel_count),
        ))
        return findings

    display = [u for u in usage if not u.segment.accent]
    accents = [u for u in usage if u.segment.accent]
    display_lit = [u for u in display if u.lit]
    accents_lit = [u for u in accents if u.lit]

    if not display_lit and not accents_lit:
        findings.append(Finding(
            severity=INFO,
            code="interior-unused",
            summary="The interior lights stay dark for the whole show",
            detail=(
                "This export can drive {total} interior segments -- {names} "
                "-- and never does. The Center Front Display alone lights up "
                'the whole cabin. See README.md, "Interior RGB Lights".'
            ).format(total=len(usage),
                     names=", ".join(u.segment.name for u in usage)),
            channels=tuple(
                c for u in usage for c in u.segment.channels),
        ))
        return findings

    if accents_lit and not display_lit:
        findings.append(Finding(
            severity=WARNING,
            code="interior-accents-without-display",
            summary="Only the accent lights are driven, and they are optional "
                    "hardware",
            detail=(
                "{count} accent segment(s) are used while the Center Front "
                "Display stays black. README.md says the accent segments "
                'exist only "on cars with Interior Accent Lights", so on a '
                "car without them nothing in the cabin responds. The display "
                "is brighter than the accents and the README recommends "
                "operating them together."
            ).format(count=len(accents_lit)),
            channels=tuple(
                c for u in accents_lit for c in u.segment.channels),
            first_at_ms=min(u.first_lit_ms for u in accents_lit),
        ))

    if display_lit and not accents_lit:
        findings.append(Finding(
            severity=INFO,
            code="interior-display-only",
            summary="The Center Front Display is used but the accent segments "
                    "are not",
            detail=(
                "This works on every car that has the display, which is the "
                "safe choice. The five accent segments -- {names} -- are "
                "available as well on cars fitted with Interior Accent "
                "Lights."
            ).format(names=", ".join(u.segment.name for u in accents)),
            channels=display[0].segment.channels,
            first_at_ms=display_lit[0].first_lit_ms,
        ))

    if accents_lit and len(accents_lit) < len(accents):
        dark = [u.segment.name for u in accents if not u.lit]
        findings.append(Finding(
            severity=INFO,
            code="interior-partial-accents",
            summary="{} of {} accent segments stay dark".format(
                len(dark), len(accents)),
            detail=(
                "{names} are never driven. This is only worth a look if the "
                "effect was meant to cover the whole cabin."
            ).format(names=", ".join(dark)),
            channels=tuple(
                c for u in accents if not u.lit for c in u.segment.channels),
        ))

    findings.sort(key=lambda f: (
        _SEVERITY_ORDER[f.severity],
        f.first_at_ms if f.first_at_ms is not None else 0,
    ))
    return findings


def variant_profile(profile: VehicleProfile,
                    variant: BuildVariant) -> VehicleProfile:
    """The parent profile with the variant's differences applied."""
    return dataclasses.replace(
        profile,
        key="{}:{}".format(profile.key, variant.key),
        label=variant.label,
        kinds=_merge(profile.kinds, variant.kinds),
        or_groups=profile.or_groups + variant.or_groups,
        notes=variant.notes,
        variants=(),
        slaved=_merge_text(profile.slaved, variant.slaved),
    )


def _finding_key(finding: Finding) -> Tuple:
    return (finding.code, finding.channels, finding.first_at_ms)


def analyze_variants(
    show: Show, profile: VehicleProfile
) -> List[Tuple[BuildVariant, List[Finding]]]:
    """What each documented build adds to the base vehicle's report.

    Only the difference is returned. An owner of one of these builds needs to
    know what is true for them and not for the rest of the range; repeating
    the whole report for each build would bury it.
    """
    if not profile.variants:
        return []
    base = {_finding_key(f) for f in analyze(show, profile)}
    out: List[Tuple[BuildVariant, List[Finding]]] = []
    for variant in profile.variants:
        extra = [f for f in analyze(show, variant_profile(profile, variant))
                 if _finding_key(f) not in base]
        out.append((variant, extra))
    return out


def _check_windows_during_door_movement(
    show: Show, profile: VehicleProfile, findings: List[Finding]
) -> None:
    """README.md: this is the one thing that stops the show outright.

    "Moving Windows during Model X door movement can cause false pinch
    detections, stopping the light show." A door keeps moving after its
    command, for the duration in "Closure Movement Durations", so the window
    to avoid is the command plus that movement, not the command alone.
    """
    if not profile.pinch_doors:
        return

    moving: List[Tuple[int, int, int, str]] = []
    for channel in profile.pinch_doors:
        if channel > show.channel_count:
            continue
        family = CLOSURE_FAMILIES[channel]
        for run in runs_of(show.series(channel)):
            if run.percent not in COUNTED_COMMANDS:
                continue
            start = run.start_frame * show.step_time_ms
            if run.percent == OPEN:
                length = family.open_ms
            elif run.percent == CLOSE:
                length = family.close_ms
            else:
                length = family.longest_movement_ms
            moving.append((start, start + length, channel,
                           CLOSURE_CODES[run.percent]))
    if not moving:
        return

    clashes: List[Tuple[int, int, int]] = []
    for channel in WINDOW_CHANNELS:
        if channel > show.channel_count:
            continue
        for run in runs_of(show.series(channel)):
            if run.percent not in COUNTED_COMMANDS:
                continue
            start = run.start_frame * show.step_time_ms
            end = start + run.frames * show.step_time_ms
            for door_start, door_end, door_channel, _ in moving:
                if start < door_end and door_start < end:
                    clashes.append((start, channel, door_channel))
                    break

    if not clashes:
        return
    first_at, window, door = min(clashes)
    findings.append(Finding(
        severity=WARNING,
        code="window-during-door-movement",
        summary="{} moves while {} is still moving, {} time(s)".format(
            channel_name(window), channel_name(door), len(clashes)),
        detail=(
            "README.md: moving windows during {label} door movement can cause "
            "false pinch detections, which stop the show rather than just "
            "that closure. A door keeps moving for up to {seconds} s after "
            "its command, so leave the windows alone until it has finished."
        ).format(label=profile.label,
                 seconds=max(CLOSURE_FAMILIES[c].longest_movement_ms
                             for c in profile.pinch_doors) // 1000),
        channels=(window, door),
        first_at_ms=first_at,
        occurrences=len(clashes),
    ))


# --------------------------------------------------------------------------
# How much of a show a vehicle can actually show
# --------------------------------------------------------------------------


@dataclasses.dataclass
class Coverage:
    """Where a show's lit time lands on one vehicle."""

    fitted: int = 0            # channels this vehicle has
    not_fitted: int = 0        # channels it does not
    optional: int = 0          # interior RGB, which depends on the options

    @property
    def total(self) -> int:
        return self.fitted + self.not_fitted + self.optional

    @property
    def not_fitted_share(self) -> float:
        return self.not_fitted / self.total if self.total else 0.0

    def as_dict(self) -> dict:
        return {
            "fitted": self.fitted,
            "not_fitted": self.not_fitted,
            "optional": self.optional,
            "total": self.total,
            "not_fitted_share": round(self.not_fitted_share, 4),
        }


def coverage(show: Show, profile: VehicleProfile) -> Coverage:
    """Count lit frames by whether this vehicle has the channel at all.

    Interior RGB is counted apart from the rest: README.md says the accent
    segments exist "on cars with Interior Accent Lights" without saying which
    builds, so calling them missing would be a guess.
    """
    result = Coverage()
    for channel in range(1, show.channel_count + 1):
        lit = sum(1 for value in show.series(channel) if value)
        if not lit:
            continue
        entry = CHANNELS.get(channel)
        if entry and entry[1] == RGB:
            result.optional += lit
            continue
        block = block_of(channel)
        if block is not None:
            if profile.key in block.vehicles:
                result.fitted += lit
            else:
                result.not_fitted += lit
            continue
        if entry is None:
            continue                      # unmapped, nothing to claim
        if kind_of(profile, channel) == ABSENT:
            result.not_fitted += lit
        else:
            result.fitted += lit
    return result


# More than this much of a show landing on channels the vehicle does not have
# is the difference between "some effects are missing" and "it looks like
# nothing happened", which is how issue #82 describes it.
MOSTLY_NOT_FITTED = 0.5


def _check_coverage(show: Show, profile: VehicleProfile,
                    findings: List[Finding]) -> None:
    result = coverage(show, profile)
    if result.total == 0 or result.not_fitted_share <= MOSTLY_NOT_FITTED:
        return

    missing_blocks = sorted({
        block.name for channel in range(1, show.channel_count + 1)
        for block in (block_of(channel),)
        if block is not None and profile.key not in block.vehicles
        and any(show.series(channel))})
    findings.append(Finding(
        severity=WARNING,
        code="mostly-not-fitted",
        summary="{:.0f}% of this show drives channels {} does not "
                "have".format(result.not_fitted_share * 100, profile.label),
        detail=(
            "The show will play, but most of what it does is on lights this "
            "vehicle has no equivalent for{blocks}, so it can look as though "
            "very little is happening. This is a property of the show rather "
            "than a fault in it -- a show written around the Cybertruck light "
            "bars has most of itself there."
        ).format(blocks=(": " + ", ".join(missing_blocks)) if missing_blocks
                 else ""),
        occurrences=result.not_fitted,
    ))


def analyze(show: Show, profile: VehicleProfile) -> List[Finding]:
    """Return everything about this show that will surprise the author."""
    findings: List[Finding] = []
    _check_or_groups(show, profile, findings)
    _check_ramp_reachability(show, profile, findings)
    _check_ramp_leaders(show, profile, findings)
    _check_boolean_ramps(show, profile, findings)
    _check_absent_channels(show, profile, findings)
    _check_windows_during_door_movement(show, profile, findings)
    _check_coverage(show, profile, findings)
    findings.sort(key=lambda f: (
        _SEVERITY_ORDER[f.severity],
        f.first_at_ms if f.first_at_ms is not None else 0,
    ))
    return findings


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _plural(count: int, noun: str, verb: bool = False) -> str:
    """"1 command is" / "2 commands are", for finding text."""
    text = "{} {}{}".format(count, noun, "" if count == 1 else "s")
    if verb:
        text += " is" if count == 1 else " are"
    return text


def _format_time(ms: Optional[int]) -> str:
    if ms is None:
        return "-"
    minutes, rest = divmod(ms, 60000)
    seconds, millis = divmod(rest, 1000)
    return "{:d}:{:02d}.{:03d}".format(minutes, seconds, millis)


def _wrap(text: str, width: int, indent: str) -> str:
    words = text.split()
    lines: List[str] = []
    current = indent
    for word in words:
        if len(current) + len(word) + 1 > width and current.strip():
            lines.append(current.rstrip())
            current = indent
        current += word + " "
    if current.strip():
        lines.append(current.rstrip())
    return "\n".join(lines)


_MARKERS = {ERROR: "ERROR  ", WARNING: "WARNING", INFO: "INFO   "}


def render_interior(usage: List[SegmentUsage],
                    findings: List[Finding], verbose: bool) -> List[str]:
    """The cabin section. Vehicle-independent, so it is rendered once."""
    out: List[str] = ["-" * 72, "Interior RGB", "-" * 72]
    if not usage:
        out.append("  This export cannot drive the interior lights.")
    else:
        lit = [u for u in usage if u.lit]
        if not lit:
            out.append("  No interior segment is driven by this show.")
        for entry in usage:
            if not entry.lit and not verbose:
                continue
            if entry.lit:
                out.append("  {:<22}{:>5} colour(s),{:>6} change(s), "
                           "first lit {}".format(
                               entry.segment.name, entry.colours,
                               entry.changes,
                               _format_time(entry.first_lit_ms)))
            else:
                out.append("  {:<22} not driven".format(entry.segment.name))
    for finding in findings:
        if finding.severity == INFO and not verbose:
            continue
        out.append("")
        out.append("  [{}] {}".format(_MARKERS[finding.severity],
                                      finding.code))
        out.append(_wrap(finding.summary, 76, "    "))
        out.append(_wrap(finding.detail, 76, "      "))
    hidden = sum(1 for f in findings if f.severity == INFO)
    if hidden and not verbose:
        out.append("")
        out.append("  {} interior note(s) hidden; re-run with -v to see "
                   "them.".format(hidden))
    out.append("")
    return out


def render_closures(usage: List[ClosureUsage], findings: List[Finding],
                    verbose: bool) -> List[str]:
    """The closure budget table. Limits do not vary by vehicle."""
    out: List[str] = ["-" * 72, "Closure command budget", "-" * 72]
    used = [u for u in usage if u.commands]
    if not used:
        out.append("  This show does not move any closure.")
    for entry in (usage if verbose else used):
        if entry.over_by:
            note = "over by {}".format(entry.over_by)
        elif entry.commands and entry.count == entry.family.limit:
            note = "at the limit"
        else:
            note = ""
        out.append("  {:<24}{:>4} / {:<4} {:<14}{}".format(
            channel_name(entry.channel), entry.count, entry.family.limit,
            entry.family.name, note).rstrip())
    for finding in findings:
        if finding.severity == INFO and not verbose:
            continue
        out.append("")
        out.append("  [{}] {}".format(_MARKERS[finding.severity],
                                      finding.code))
        out.append(_wrap(finding.summary, 76, "    "))
        out.append(_wrap(finding.detail, 76, "      "))
    hidden = sum(1 for f in findings if f.severity == INFO)
    if hidden and not verbose:
        out.append("")
        out.append("  {} closure note(s) hidden; re-run with -v to see "
                   "them.".format(hidden))
    out.append("")
    return out


def _render_vehicle_finding(finding: Finding, indent: str = "  ") -> List[str]:
    out = ["{}[{}] {} at {}".format(
        indent, _MARKERS[finding.severity], finding.code,
        _format_time(finding.first_at_ms))]
    out.append(_wrap(finding.summary, 76, indent + "  "))
    out.append(_wrap(finding.detail, 76, indent + "    "))
    if finding.channels:
        out.append(indent + "    channels: " + ", ".join(
            "{} ({})".format(channel_name(c), c) for c in finding.channels))
    return out


def render_report(show: Show, results: Dict[str, List[Finding]], verbose: bool,
                  interior: Optional[List[Finding]] = None,
                  closures: Optional[List[Finding]] = None,
                  builds: Optional[Dict[str, List[Tuple[
                      BuildVariant, List[Finding]]]]] = None) -> str:
    out: List[str] = []
    out.append("{} frames, {} ms per frame, total duration {}.".format(
        show.frame_count, show.step_time_ms, _format_time(show.duration_ms)))
    first_lit = show.first_lit_ms()
    if first_lit is None:
        out.append("Nothing in this show is ever lit.")
    elif first_lit:
        out.append("First light at {}; the show is dark before that.".format(
            _format_time(first_lit)))
    out.append("")
    if interior is not None:
        out.extend(render_interior(interior_usage(show), interior, verbose))
    if closures is not None:
        out.extend(render_closures(closure_usage(show), closures, verbose))
    for key, findings in results.items():
        profile = VEHICLES[key]
        errors = sum(1 for f in findings if f.severity == ERROR)
        warnings = sum(1 for f in findings if f.severity == WARNING)
        infos = len(findings) - errors - warnings
        out.append("=" * 72)
        out.append("{}  -  {} error(s), {} warning(s), {} note(s)".format(
            profile.label, errors, warnings, infos))
        out.append("=" * 72)
        spread = coverage(show, profile)
        if spread.total:
            out.append("  {:.0f}% of the lit time lands on lights this "
                       "vehicle has{}.".format(
                           100 * spread.fitted / spread.total,
                           "" if not spread.optional else
                           ", {:.0f}% on interior segments that depend on the "
                           "options".format(
                               100 * spread.optional / spread.total)))
        if not findings:
            out.append("  This show renders the same way the xLights preview "
                       "shows it.")
        for finding in findings:
            if finding.severity == INFO and not verbose:
                continue
            out.append("")
            out.extend(_render_vehicle_finding(finding))
        if infos and not verbose:
            out.append("")
            out.append("  {} vehicle-configuration note(s) hidden; re-run with "
                       "-v to see them.".format(infos))
        for variant, extra in (builds or {}).get(key, ()):
            shown = [f for f in extra if verbose or f.severity != INFO]
            if not extra:
                continue
            out.append("")
            out.append("  Also on {}:".format(variant.label))
            out.append("  " + "-" * 70)
            for finding in shown:
                out.append("")
                out.extend(_render_vehicle_finding(finding, indent="    "))
            hidden = len(extra) - len(shown)
            if hidden:
                out.append("")
                out.append("    {} note(s) hidden; re-run with -v to see "
                           "them.".format(hidden))
            out.append("")
            out.append(_wrap(
                "See README.md, \"{}\".".format(variant.readme), 76, "    "))
        for note in profile.notes:
            out.append("")
            out.append(_wrap("Note: " + note, 76, "  "))
        out.append("")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview how a .fseq light show behaves on each Tesla "
                    "vehicle, and flag where it will differ from the xLights "
                    "Model S preview.")
    parser.add_argument("fseq", nargs="?", help="path to the .fseq show file")
    parser.add_argument(
        "--vehicle", action="append", choices=sorted(VEHICLES),
        help="limit the report to one vehicle (repeatable; default: all)")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON instead of text")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="include vehicle-configuration notes")
    parser.add_argument(
        "--strict", action="store_true",
        help="exit non-zero if any error or warning is reported")
    args = parser.parse_args(argv)

    path = args.fseq
    if not path:
        path = input(
            "Please enter the path by dragging and dropping the .fseq file: ")
        print("")
        path = path.strip('"').strip("'").strip(" ")

    try:
        show = read_fseq(path)
    except (ShowError, OSError) as error:
        print(error, file=sys.stderr)
        return 2

    keys = args.vehicle or sorted(VEHICLES)
    results = {key: analyze(show, VEHICLES[key]) for key in keys}
    interior = analyze_interior(show)
    closures = analyze_closures(show)
    builds = {key: analyze_variants(show, VEHICLES[key]) for key in keys}

    if args.json:
        print(json.dumps({
            "file": path,
            "frame_count": show.frame_count,
            "step_time_ms": show.step_time_ms,
            "duration_ms": show.duration_ms,
            "first_lit_ms": show.first_lit_ms(),
            "interior": {
                "segments": [u.as_dict() for u in interior_usage(show)],
                "findings": [f.as_dict() for f in interior],
            },
            "closures": {
                "budget": [u.as_dict() for u in closure_usage(show)],
                "findings": [f.as_dict() for f in closures],
            },
            "vehicles": {
                key: {
                    "label": VEHICLES[key].label,
                    "coverage": coverage(show, VEHICLES[key]).as_dict(),
                    "findings": [f.as_dict() for f in findings],
                    "builds": [
                        {
                            "key": variant.key,
                            "label": variant.label,
                            "readme": variant.readme,
                            "findings": [f.as_dict() for f in extra],
                        }
                        for variant, extra in builds.get(key, ())
                    ],
                }
                for key, findings in results.items()
            },
        }, indent=2))
    else:
        print(render_report(show, results, args.verbose, interior, closures,
                            builds))

    build_findings = [f for entries in builds.values()
                      for _, extra in entries for f in extra]
    if args.strict and any(
        f.severity in (ERROR, WARNING)
        for findings in list(results.values()) + [interior, closures,
                                                  build_findings]
        for f in findings
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
