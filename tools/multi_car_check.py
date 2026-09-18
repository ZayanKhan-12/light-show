#!/usr/bin/env python3
"""Check a cross-vehicle show: one exported .fseq per car, meant to run as one.

https://github.com/teslamotors/light-show/issues/64 asks for "a continuous
animation across several cars parked side-to-side".  That exists --
cross-vehicle-shows/README.md describes programming one, and examples/ ships
three of them -- but the last step of making one is manual and repeated once
per car: reopen xLights, import the cross-vehicle sequence with that car's
mapping, Render All, save, export.  Five to eight times.  Nothing checks the
result, and the show only works if every car's file agrees with the others.

What has to agree is narrower than it looks.  The cars are started together
and then each plays its own file, so what keeps them in step is the total
duration and the audio track.  The frame interval does not have to match:
examples/lightshow_example_3_The_Arrival_5_Car runs cars 1 and 3 at 25 ms and
cars 2, 4 and 5 at 50 ms, with every car lasting exactly 110.25 s.  A check
that demanded identical frame counts would call Tesla's own five-car show
broken.

Usage:
    python3 tools/multi_car_check.py examples/lightshow_example_3_The_Arrival_5_Car
    python3 tools/multi_car_check.py /Volumes/SHOWS --json
    python3 tools/multi_car_check.py ./my-show --strict

Requires Python 3.7+ and only the standard library, matching validator.py.
"""

import argparse
import dataclasses
import hashlib
import json
import os
import re
import struct
import sys
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (REPO_ROOT, os.path.join(REPO_ROOT, "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# The .fseq limits and the drive layout are defined once, in the tools that
# own them.  Importing keeps a limit or a folder name from being restated.
import validator  # noqa: E402
import usb_check  # noqa: E402

ERROR = "error"
WARNING = "warning"
INFO = "info"

_SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}

# cross-vehicle-shows/README.md: "up to 5 vehicles at once", numbered 1 to 5
# from left to right viewed from the front.  examples/ ships an eight-car
# show, so the number is treated as a note rather than a limit.
DOCUMENTED_CARS = 5

# Cars are started by scheduling the show, so two cars whose files differ in
# length end at different times.  Anything at or above this is visible.
DURATION_TOLERANCE_MS = 100

_CAR_NUMBER = re.compile(r'(\d+)')


class ShowSetError(Exception):
    """The folder could not be read as a set of per-car shows."""


@dataclasses.dataclass
class Finding:
    severity: str
    code: str
    summary: str
    detail: str
    cars: Tuple[str, ...] = ()
    readme: Optional[str] = None

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Car:
    """One car's exported show."""

    name: str
    number: Optional[int]
    folder: str
    fseq_path: Optional[str] = None
    audio_path: Optional[str] = None
    frame_count: Optional[int] = None
    step_time_ms: Optional[int] = None
    channel_count: Optional[int] = None
    duration_ms: Optional[int] = None
    audio_digest: Optional[str] = None
    audio_duration_ms: Optional[int] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.duration_ms is not None

    def as_dict(self) -> dict:
        data = dataclasses.asdict(self)
        data["ok"] = self.ok
        return data


@dataclasses.dataclass
class ShowSet:
    root: str
    cars: List[Car] = dataclasses.field(default_factory=list)
    findings: List[Finding] = dataclasses.field(default_factory=list)

    def counts(self) -> Dict[str, int]:
        counts = {ERROR: 0, WARNING: 0, INFO: 0}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    def as_dict(self) -> dict:
        return {
            "root": self.root,
            "car_count": len(self.cars),
            "cars": [c.as_dict() for c in self.cars],
            "findings": [f.as_dict() for f in self.findings],
            "counts": self.counts(),
        }


# --------------------------------------------------------------------------
# Reading a set
# --------------------------------------------------------------------------


def _show_folder_of(folder: str) -> Optional[str]:
    """The folder holding this car's .fseq, following the drive convention."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None
    for name in names:
        path = os.path.join(folder, name)
        if os.path.isdir(path) and name.lower() == usb_check.SHOW_FOLDER.lower():
            return path
    # A car folder that holds the show files directly is accepted too; the
    # set is what is being checked here, not the drive layout.
    if any(n.lower().endswith(usb_check.FSEQ_EXT) for n in names):
        return folder
    return None


def discover_cars(root: str) -> List[Car]:
    """Every per-car folder under `root`, in car-number order."""
    if not os.path.isdir(root):
        raise ShowSetError("{} is not a folder".format(root))

    cars: List[Car] = []
    for name in sorted(os.listdir(root)):
        folder = os.path.join(root, name)
        if not os.path.isdir(folder) or name.startswith("."):
            continue
        if name.lower() == usb_check.SHOW_FOLDER.lower():
            continue                      # a single drive, not a set
        show_folder = _show_folder_of(folder)
        if show_folder is None:
            continue
        match = _CAR_NUMBER.search(name)
        cars.append(Car(
            name=name,
            number=int(match.group(1)) if match else None,
            folder=show_folder,
        ))
    cars.sort(key=lambda c: (c.number is None, c.number or 0, c.name))
    return cars


def _digest(path: str) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()[:16]


def read_car(car: Car) -> Car:
    """Fill in one car's show details."""
    try:
        names = sorted(os.listdir(car.folder))
    except OSError as error:
        car.error = str(error)
        return car

    shows = [n for n in names if n.lower().endswith(usb_check.FSEQ_EXT)
             and not n.startswith("._")]
    audio = [n for n in names if n.lower().endswith(usb_check.AUDIO_EXTS)
             and not n.startswith("._")]
    if not shows:
        car.error = "no .fseq file"
        return car
    if len(shows) > 1:
        car.error = "{} .fseq files; a car in a set plays one show".format(
            len(shows))
        return car

    car.fseq_path = os.path.join(car.folder, shows[0])
    try:
        with open(car.fseq_path, "rb") as handle:
            results = validator.validate(handle)
            handle.seek(10)
            car.channel_count, = struct.unpack("<I", handle.read(4))
    except validator.ValidationError as error:
        car.error = str(error)
        return car
    except (OSError, struct.error) as error:
        car.error = str(error)
        return car

    car.frame_count = results.frame_count
    car.step_time_ms = results.step_time
    car.duration_ms = int(results.duration_s * 1000)

    if audio:
        car.audio_path = os.path.join(car.folder, audio[0])
        car.audio_digest = _digest(car.audio_path)
        track = usb_check.read_audio(car.audio_path)
        car.audio_duration_ms = track.duration_ms
    return car


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def check_set(root: str) -> ShowSet:
    """Read a folder of per-car shows and report what stops them lining up."""
    cars = [read_car(car) for car in discover_cars(root)]
    show_set = ShowSet(root=os.path.abspath(root), cars=cars)

    if not cars:
        show_set.findings.append(Finding(
            ERROR, "no-cars-found",
            "No per-car shows under {}.".format(root),
            "A cross-vehicle show is one folder per car, each holding a "
            "{} folder with that car's .fseq and audio. See "
            "cross-vehicle-shows/README.md.".format(usb_check.SHOW_FOLDER),
            readme="Programming a show with cross-vehicle animations"))
        return show_set

    for car in cars:
        if car.error:
            show_set.findings.append(Finding(
                ERROR, "car-show-unusable",
                "{} cannot be played: {}".format(car.name, car.error),
                "Every car in the set needs one valid show. Re-export this "
                "car from the cross-vehicle sequence, remembering Render All "
                "before saving.",
                cars=(car.name,),
                readme="Exporting the show"))

    _check_durations(show_set)
    _check_audio(show_set)
    _check_numbering(show_set)
    _check_channel_counts(show_set)
    _check_frame_intervals(show_set)
    show_set.findings.sort(key=lambda f: _SEVERITY_ORDER[f.severity])
    return show_set


def _usable(show_set: ShowSet) -> List[Car]:
    return [c for c in show_set.cars if c.ok]


def _check_durations(show_set: ShowSet) -> None:
    """The one thing that must match: when each car stops."""
    cars = _usable(show_set)
    if len(cars) < 2:
        return
    longest = max(cars, key=lambda c: c.duration_ms)
    shortest = min(cars, key=lambda c: c.duration_ms)
    spread = longest.duration_ms - shortest.duration_ms
    if spread <= DURATION_TOLERANCE_MS:
        return
    show_set.findings.append(Finding(
        ERROR, "duration-mismatch",
        "The cars' shows are not the same length; {} spread across "
        "{} cars.".format(_format_time(spread), len(cars)),
        "The cars are started together and then each plays its own file, so "
        "a difference in length is a difference in when they stop. {} runs "
        "{} and {} runs {}. Re-export the short cars from the same "
        "cross-vehicle sequence.".format(
            shortest.name, _format_time(shortest.duration_ms),
            longest.name, _format_time(longest.duration_ms)),
        cars=tuple(c.name for c in cars),
        readme="Exporting the show"))


def _check_audio(show_set: ShowSet) -> None:
    """Every car plays the music itself; a different file is a different show."""
    cars = [c for c in _usable(show_set) if c.audio_path]
    missing = [c for c in _usable(show_set) if not c.audio_path]
    if missing:
        show_set.findings.append(Finding(
            ERROR, "audio-missing",
            "{} car(s) have no audio file.".format(len(missing)),
            "A car with no matching .mp3 or .wav is not offered in the "
            "vehicle at all: {}.".format(
                ", ".join(c.name for c in missing)),
            cars=tuple(c.name for c in missing),
            readme="USB flash drive requirements"))
    if len(cars) < 2:
        return

    digests = {c.audio_digest for c in cars}
    if len(digests) > 1:
        groups: Dict[str, List[str]] = {}
        for car in cars:
            groups.setdefault(car.audio_digest, []).append(car.name)
        show_set.findings.append(Finding(
            ERROR, "audio-mismatch",
            "The cars are not carrying the same audio file.",
            "Cross-vehicle timing comes from every car playing the same "
            "track. Found {} different files: {}.".format(
                len(groups),
                "; ".join("{} on {}".format(digest[:8], ", ".join(names))
                          for digest, names in sorted(groups.items()))),
            cars=tuple(c.name for c in cars),
            readme="Exporting the show"))

    names = {os.path.basename(c.audio_path) for c in cars}
    if len(names) > 1 and len(digests) == 1:
        show_set.findings.append(Finding(
            INFO, "audio-named-differently",
            "The same audio is filed under {} different names.".format(
                len(names)),
            "The file is identical on every car, so the show still lines up. "
            "Found: {}.".format(", ".join(sorted(names))),
            cars=tuple(c.name for c in cars)))


def _check_numbering(show_set: ShowSet) -> None:
    """cross-vehicle-shows/README.md numbers the cars 1 to 5, left to right."""
    numbered = [c for c in show_set.cars if c.number is not None]
    if not numbered:
        show_set.findings.append(Finding(
            INFO, "cars-not-numbered",
            "The car folders are not numbered.",
            "The guide numbers cars 1 to 5 from left to right seen from the "
            "front, and the mapping used at export is per car number. Naming "
            "the folders 'Car #1' and so on keeps the drives matched to "
            "the positions.",
            cars=tuple(c.name for c in show_set.cars),
            readme="Layout"))
        return

    numbers = sorted(c.number for c in numbered)
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        show_set.findings.append(Finding(
            WARNING, "car-number-repeated",
            "Car number {} is used more than once.".format(
                ", ".join(str(n) for n in duplicates)),
            "Each position in the row is a different export. Two cars with "
            "the same number means one position is missing its own show.",
            cars=tuple(c.name for c in numbered),
            readme="Layout"))

    expected = list(range(1, max(numbers) + 1))
    gaps = [n for n in expected if n not in numbers]
    if gaps:
        show_set.findings.append(Finding(
            WARNING, "car-numbering-gap",
            "No show for car {}.".format(
                ", ".join(str(n) for n in gaps)),
            "The cars are numbered 1 to {} but nothing was found for {}. A "
            "cross-vehicle show does run with fewer cars, but the remaining "
            "shows have to be the ones for the positions actually used.".format(
                max(numbers), ", ".join(str(n) for n in gaps)),
            readme="Layout"))

    if max(numbers) > DOCUMENTED_CARS:
        show_set.findings.append(Finding(
            INFO, "more-cars-than-documented",
            "{} cars; the cross-vehicle folder covers {}.".format(
                max(numbers), DOCUMENTED_CARS),
            "cross-vehicle-shows/README.md describes up to {} vehicles, and "
            "examples/ ships an eight-car show, so a larger set is not a "
            "problem by itself.".format(DOCUMENTED_CARS),
            readme="Programming a show with cross-vehicle animations"))


def _check_channel_counts(show_set: ShowSet) -> None:
    cars = _usable(show_set)
    counts = {c.channel_count for c in cars}
    if len(counts) < 2:
        return
    show_set.findings.append(Finding(
        WARNING, "channel-count-mismatch",
        "The cars were exported from different project folders.",
        "Found {} channel layouts across the set: {}. The cars will still "
        "play, but a {}-channel export cannot drive the light bars or the "
        "interior, so an effect that crosses the row will stop at those "
        "cars.".format(len(counts), sorted(counts), min(counts)),
        cars=tuple(c.name for c in cars)))


def _check_frame_intervals(show_set: ShowSet) -> None:
    """Different intervals are fine, and worth saying so out loud."""
    cars = _usable(show_set)
    intervals = {c.step_time_ms for c in cars}
    if len(intervals) < 2:
        return
    show_set.findings.append(Finding(
        INFO, "frame-interval-mismatch",
        "The cars use {} different frame intervals: {}.".format(
            len(intervals), ", ".join("{} ms".format(i)
                                      for i in sorted(intervals))),
        "This is not a problem. The cars stay together because their shows "
        "are the same length, not because they run at the same rate; "
        "examples/lightshow_example_3_The_Arrival_5_Car mixes 25 ms and "
        "50 ms cars.",
        cars=tuple(c.name for c in cars)))


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _format_time(ms: Optional[int]) -> str:
    if ms is None:
        return "-"
    minutes, rest = divmod(ms, 60000)
    seconds, millis = divmod(rest, 1000)
    if minutes:
        return "{:d}:{:02d}.{:03d}".format(minutes, seconds, millis)
    return "{:d}.{:03d}s".format(seconds, millis)


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


_MARKERS = {ERROR: "ERROR  ", WARNING: "WARNING", INFO: "NOTE   "}


def render_report(show_set: ShowSet, verbose: bool) -> str:
    out: List[str] = ["Show set: {}".format(show_set.root), ""]
    if show_set.cars:
        out.append("{} car(s):".format(len(show_set.cars)))
        out.append("")
        width = max(len(c.name) for c in show_set.cars)
        for car in show_set.cars:
            if car.ok:
                out.append("  {}  {:>10}  {:>3} ms  {:>3} ch  {}".format(
                    car.name.ljust(width), _format_time(car.duration_ms),
                    car.step_time_ms, car.channel_count,
                    os.path.basename(car.audio_path) if car.audio_path
                    else "no audio"))
            else:
                out.append("  {}  {}".format(
                    car.name.ljust(width), car.error or "unreadable"))
        out.append("")

    shown = [f for f in show_set.findings if verbose or f.severity != INFO]
    for finding in shown:
        out.append("  [{}] {}".format(_MARKERS[finding.severity],
                                      finding.code))
        out.append(_wrap(finding.summary, 76, "    "))
        out.append(_wrap(finding.detail, 76, "      "))
        if finding.readme:
            out.append("      README: {}".format(finding.readme))
        out.append("")

    counts = show_set.counts()
    hidden = counts[INFO] if not verbose else 0
    out.append("{} error(s), {} warning(s), {} note(s).".format(
        counts[ERROR], counts[WARNING], counts[INFO]))
    if hidden:
        out.append("Re-run with -v to see the notes.")
    if not counts[ERROR] and not counts[WARNING] and show_set.cars:
        out.append("The cars agree; this set will run as one show.")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that the per-car shows of a cross-vehicle set "
                    "agree with each other.")
    parser.add_argument("path", nargs="?",
                        help="the folder holding one folder per car")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON instead of text")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="include the informational notes")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero on warnings as well as errors")
    args = parser.parse_args(argv)

    path = args.path
    if not path:
        path = input("Please enter the path by dragging and dropping the "
                     "folder holding the per-car shows: ")
        print("")
        path = path.strip('"').strip("'").strip(" ")

    try:
        show_set = check_set(path)
    except (ShowSetError, OSError) as error:
        print(error, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(show_set.as_dict(), indent=2))
    else:
        print(render_report(show_set, args.verbose))

    counts = show_set.counts()
    if counts[ERROR] or (args.strict and counts[WARNING]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
