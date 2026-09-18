#!/usr/bin/env python3
"""Build a show that lights one channel at a time, to see what each one drives.

https://github.com/teslamotors/light-show/issues/72 reports that on a 2023
Fremont Model 3 RWD the Inner and Outer Main Beam channels are the other way
round. Nobody replied for two years, and there was no way for anyone to.
Whoever reads it has no such car, the reporter has no way to show what they
saw, and the one thing that must never happen is a remap of the show folder on
an unverified report: the model-to-StartChannel mapping is what every .fseq
ever exported depends on.

What was missing is a way to answer the question on the car it is about. This
builds a show that turns on one channel at a time, in a printed order, with a
tone in the audio at each change. Play it, film the car, and the video says
which lamp each channel drives on that vehicle.

    python3 tools/channel_probe.py probe --group headlights
    python3 tools/channel_probe.py probe --channels 1,2,3,4 --on-ms 4000
    python3 tools/channel_probe.py probe --group lights --json

It writes probe.fseq and probe.wav, ready to copy into a LightShow folder, and
checks the result with validator.py before it finishes.

Closures are left out unless asked for: they have documented actuation limits
and thermal limits, and a probe is not worth spending them on by accident.

Requires Python 3.7+ and only the standard library, matching validator.py.
"""

import argparse
import dataclasses
import io
import json
import math
import os
import struct
import sys
import wave
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (REPO_ROOT, os.path.join(REPO_ROOT, "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import validator  # noqa: E402
import vehicle_preview  # noqa: E402

# The .fseq the vehicle reads, written in the plainest form validator.py
# accepts: FSEQ v2.0, uncompressed, no metadata block.
HEADER_BYTES = 32
FSEQ_MAJOR = 2
FSEQ_MINOR = 0

# README.md, "Getting started with the Tesla xLights project directory".
DEFAULT_STEP_MS = 20
# README.md, "Audio file requirements": 44.1 kHz, or the show drifts.
SAMPLE_RATE = 44100

DEFAULT_ON_MS = 3000
DEFAULT_GAP_MS = 1000
# A tone at each change, so the video has an audible marker to count from.
TONE_MS = 250
TONE_HZ = 880

# README.md, "General Limitations of Custom Shows".
MAX_DURATION_S = 4 * 60 * 60

LIGHT = vehicle_preview.LIGHT
CLOSURE = vehicle_preview.CLOSURE
RGB = vehicle_preview.RGB

# Full brightness. README.md: anything above 50% is on.
ON_VALUE = 255
# README.md, "Definitions for closure movements": 25% is Open.
CLOSURE_OPEN_VALUE = 64


class ProbeError(Exception):
    """The probe could not be built as asked."""


@dataclasses.dataclass
class Step:
    """One turn: a channel, or several driven together.

    Several at once is how you compare lights that may share a lamp --
    https://github.com/teslamotors/light-show/issues/76 reports Front Turn
    and Aux Park as one lamp on a Model X, orange from one channel, white
    from the other and a dimmer mix from both.
    """

    channels: Tuple[int, ...]
    name: str
    kind: str
    start_ms: int
    end_ms: int

    def as_dict(self) -> dict:
        data = dataclasses.asdict(self)
        data["channels"] = list(self.channels)
        return data


@dataclasses.dataclass
class Probe:
    steps: List[Step]
    channel_count: int
    step_ms: int
    frame_count: int

    @property
    def duration_ms(self) -> int:
        return self.frame_count * self.step_ms

    def as_dict(self) -> dict:
        return {
            "channel_count": self.channel_count,
            "step_ms": self.step_ms,
            "frame_count": self.frame_count,
            "duration_ms": self.duration_ms,
            "steps": [s.as_dict() for s in self.steps],
        }


# --------------------------------------------------------------------------
# Choosing channels
# --------------------------------------------------------------------------


def _channels_of_kind(kind: str) -> List[int]:
    return sorted(c for c, (_, k) in vehicle_preview.CHANNELS.items()
                  if k == kind)


# The group that answers issue #72 is "headlights": the four beam channels
# whose order is in question, kept adjacent so a video is easy to read.
GROUPS: Dict[str, List[int]] = {
    "headlights": [1, 2, 3, 4],
    # Issue #76: on a Model X these were reported to be one lamp.
    "front-turn-aux-park": [13, 17, 14, 18],
    "front": [c for c in _channels_of_kind(LIGHT) if c <= 22],
    "lights": _channels_of_kind(LIGHT),
    "closures": _channels_of_kind(CLOSURE),
    "all": _channels_of_kind(LIGHT) + _channels_of_kind(CLOSURE),
}


def parse_channels(text: str) -> List[Tuple[int, ...]]:
    """Parse a channel spec into one entry per turn.

    "1,2"    two turns, one channel each
    "1-4"    four turns
    "13+17"  one turn driving both channels at once
    """
    steps: List[Tuple[int, ...]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "+" in part:
            together: List[int] = []
            for piece in part.split("+"):
                piece = piece.strip()
                try:
                    together.append(int(piece))
                except ValueError:
                    raise ProbeError("{!r} is not a channel".format(piece))
            steps.append(tuple(together))
            continue
        if "-" in part.lstrip("-"):
            first, _, last = part.partition("-")
            try:
                low, high = int(first), int(last)
            except ValueError:
                raise ProbeError("{!r} is not a channel range".format(part))
            if low > high:
                raise ProbeError("{!r} counts backwards".format(part))
            steps.extend((c,) for c in range(low, high + 1))
            continue
        try:
            steps.append((int(part),))
        except ValueError:
            raise ProbeError("{!r} is not a channel".format(part))
    return steps


def resolve_channels(group: Optional[str], explicit: Optional[str],
                     include_closures: bool) -> List[Tuple[int, ...]]:
    if explicit:
        channels = parse_channels(explicit)
    else:
        channels = [(c,) for c in GROUPS[group or "headlights"]]

    if not include_closures and not (group == "closures"):
        channels = [
            step for step in channels
            if not any(
                vehicle_preview.CHANNELS.get(c, ("", LIGHT))[1] == CLOSURE
                for c in step)]

    seen, ordered = set(), []
    for step in channels:
        if step in seen:
            continue
        seen.add(step)
        ordered.append(step)

    if not ordered:
        raise ProbeError(
            "No channels selected. Closures are left out unless you pass "
            "--include-closures, because every Open, Close or Dance counts "
            "against that closure's limit for the show.")
    return ordered


def _describe(channel: int) -> Tuple[str, str]:
    entry = vehicle_preview.CHANNELS.get(channel)
    if entry is None:
        return ("Channel {}".format(channel), LIGHT)
    return entry


# --------------------------------------------------------------------------
# Building the show
# --------------------------------------------------------------------------


def build_probe(channels: Sequence[Sequence[int]],
                on_ms: int = DEFAULT_ON_MS,
                gap_ms: int = DEFAULT_GAP_MS,
                step_ms: int = DEFAULT_STEP_MS,
                channel_count: int = 200) -> Probe:
    """Lay out one channel at a time, each on for `on_ms`."""
    if step_ms < 15 or step_ms > 100:
        raise ProbeError(
            "The frame interval must be between 15 and 100 ms; got "
            "{}.".format(step_ms))
    if on_ms < step_ms:
        raise ProbeError(
            "Each channel has to be on for at least one frame "
            "({} ms).".format(step_ms))
    if channel_count not in validator.VALID_CHANNEL_COUNTS:
        raise ProbeError(validator.describe_channel_count(channel_count))

    flat = [c for step in channels for c in step]
    over = [c for c in flat if c > channel_count or c < 1]
    if over:
        raise ProbeError(
            "Channel(s) {} are outside a {}-channel show.".format(
                ", ".join(str(c) for c in over), channel_count))

    steps: List[Step] = []
    cursor = gap_ms                       # a gap first, so filming can settle
    for step_channels in channels:
        described = [_describe(c) for c in step_channels]
        name = " + ".join(n for n, _ in described)
        kind = CLOSURE if any(k == CLOSURE for _, k in described) else LIGHT
        steps.append(Step(channels=tuple(step_channels), name=name, kind=kind,
                          start_ms=cursor, end_ms=cursor + on_ms))
        cursor += on_ms + gap_ms

    frame_count = max(1, int(math.ceil(cursor / step_ms)))
    duration_s = frame_count * step_ms / 1000.0
    if duration_s > MAX_DURATION_S:
        raise ProbeError(
            "That probe would run {:.0f} s; the maximum show length is 4 "
            "hours. Use fewer channels or a shorter --on-ms.".format(
                duration_s))
    return Probe(steps=steps, channel_count=channel_count, step_ms=step_ms,
                 frame_count=frame_count)


def render_fseq(probe: Probe) -> bytes:
    """A V2 uncompressed .fseq, the form validator.py documents."""
    header = bytearray(HEADER_BYTES)
    header[0:4] = b"PSEQ"
    struct.pack_into("<H", header, 4, HEADER_BYTES)   # data offset
    header[6] = FSEQ_MINOR
    header[7] = FSEQ_MAJOR
    struct.pack_into("<H", header, 8, HEADER_BYTES)   # standard header length
    struct.pack_into("<IIB", header, 10, probe.channel_count,
                     probe.frame_count, probe.step_ms)
    header[20] = 0                                    # uncompressed

    data = bytearray(probe.channel_count * probe.frame_count)
    for step in probe.steps:
        first = step.start_ms // probe.step_ms
        last = step.end_ms // probe.step_ms
        for channel in step.channels:
            _, kind = _describe(channel)
            value = CLOSURE_OPEN_VALUE if kind == CLOSURE else ON_VALUE
            for frame in range(first, min(last, probe.frame_count)):
                data[frame * probe.channel_count + (channel - 1)] = value
    return bytes(header) + bytes(data)


def render_wav(probe: Probe) -> bytes:
    """Silence with a tone at the start of each channel's turn."""
    total = int(SAMPLE_RATE * probe.duration_ms / 1000.0)
    samples = bytearray(total * 2)
    tone_samples = int(SAMPLE_RATE * TONE_MS / 1000.0)
    for step in probe.steps:
        offset = int(SAMPLE_RATE * step.start_ms / 1000.0)
        for index in range(min(tone_samples, max(0, total - offset))):
            # A short fade keeps the tone from clicking.
            fade = min(1.0, min(index, tone_samples - index) / 200.0)
            value = int(12000 * fade
                        * math.sin(2 * math.pi * TONE_HZ * index / SAMPLE_RATE))
            struct.pack_into("<h", samples, (offset + index) * 2, value)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(samples))
    return buffer.getvalue()


def write_probe(probe: Probe, base_path: str) -> Tuple[str, str]:
    """Write <base>.fseq and <base>.wav, and check the show is playable."""
    base = base_path[:-5] if base_path.lower().endswith(".fseq") else base_path
    fseq_bytes = render_fseq(probe)

    # The repository's own checker has the last word on the file it produces.
    validator.validate(io.BytesIO(fseq_bytes))

    fseq_path = base + ".fseq"
    wav_path = base + ".wav"
    with open(fseq_path, "wb") as handle:
        handle.write(fseq_bytes)
    with open(wav_path, "wb") as handle:
        handle.write(render_wav(probe))
    return fseq_path, wav_path


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _format_time(ms: int) -> str:
    minutes, rest = divmod(ms, 60000)
    seconds, millis = divmod(rest, 1000)
    return "{:d}:{:02d}.{:03d}".format(minutes, seconds, millis)


def render_schedule(probe: Probe, fseq_path: str, wav_path: str) -> str:
    out = [
        "Wrote {} and {}".format(os.path.basename(fseq_path),
                                 os.path.basename(wav_path)),
        "  {} channel(s), {} ms frames, {} long".format(
            len(probe.steps), probe.step_ms,
            _format_time(probe.duration_ms)),
        "",
        "Copy both files into a LightShow folder on the drive, play the show",
        "and film the car. A tone sounds as each channel comes on.",
        "",
    ]
    width = max((len(s.name) for s in probe.steps), default=0)
    for index, step in enumerate(probe.steps, start=1):
        out.append("  {:>2}. {} - {}   {:>9}  {}".format(
            index, _format_time(step.start_ms), _format_time(step.end_ms),
            "+".join(str(c) for c in step.channels),
            step.name.ljust(width)))
    closures = [s for s in probe.steps if s.kind == CLOSURE]
    if closures:
        out.append("")
        out.append("  {} closure(s) are opened and left open; close them "
                   "yourself afterwards.".format(len(closures)))
        out.append("  Each Open counts once against that closure's limit for "
                   "the show.")
    out.append("")
    out.append("If a channel lights something other than its name, say so on "
               "the issue")
    out.append("with the vehicle, its build date and this schedule. Channel "
               "assignments")
    out.append("are never remapped: a confirmed difference is documented for "
               "that vehicle.")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a show that lights one channel at a time, to see "
                    "what each channel drives on a particular vehicle.")
    parser.add_argument("output", nargs="?", default="probe",
                        help="base name for the .fseq and .wav (default: probe)")
    parser.add_argument("--group", choices=sorted(GROUPS),
                        help="a named set of channels (default: headlights)")
    parser.add_argument("--channels",
                        help="explicit channels, e.g. 1,2,3 or 1-6; "
                             "13+17 drives both at once")
    parser.add_argument("--on-ms", type=int, default=DEFAULT_ON_MS,
                        help="how long each channel stays on")
    parser.add_argument("--gap-ms", type=int, default=DEFAULT_GAP_MS,
                        help="dark time between channels")
    parser.add_argument("--step-ms", type=int, default=DEFAULT_STEP_MS,
                        help="frame interval")
    parser.add_argument("--channel-count", type=int, default=200,
                        choices=sorted(validator.VALID_CHANNEL_COUNTS),
                        help="show layout to export (default: 200)")
    parser.add_argument(
        "--include-closures", action="store_true",
        help="also probe closures; each Open counts against that closure's "
             "limit for the show")
    parser.add_argument("--json", action="store_true",
                        help="emit the schedule as JSON")
    args = parser.parse_args(argv)

    try:
        channels = resolve_channels(args.group, args.channels,
                                    args.include_closures)
        probe = build_probe(channels, on_ms=args.on_ms, gap_ms=args.gap_ms,
                            step_ms=args.step_ms,
                            channel_count=args.channel_count)
        fseq_path, wav_path = write_probe(probe, args.output)
    except (ProbeError, validator.ValidationError) as error:
        print(error, file=sys.stderr)
        return 2
    except OSError as error:
        print(error, file=sys.stderr)
        return 2

    if args.json:
        payload = probe.as_dict()
        payload["fseq"] = fseq_path
        payload["wav"] = wav_path
        print(json.dumps(payload, indent=2))
    else:
        print(render_schedule(probe, fseq_path, wav_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
