#!/usr/bin/env python3
"""List what is in examples/, including which shows ship an editable source.

https://github.com/teslamotors/light-show/issues/87 asks for the .xsq of a
show. It is a fair question that nobody could answer from the repository,
because there was no way to see what examples/ holds without downloading
sixty megabytes of archives and opening each one. Some shows ship a .fseq and
its .xsq, some ship only one of the two, and the built-in shows in the car are
not here at all.

    python3 tools/examples_index.py              # a markdown table
    python3 tools/examples_index.py --json

The table in README.md is this output, and CI checks the two still agree.

Requires Python 3.7+ and only the standard library, matching validator.py.
"""

import argparse
import dataclasses
import json
import os
import re
import sys
import tempfile
import zipfile
from typing import List, Optional, Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (REPO_ROOT, os.path.join(REPO_ROOT, "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import vehicle_preview as vp  # noqa: E402

EXAMPLES_DIR = os.path.join(REPO_ROOT, "examples")

FSEQ_EXT = ".fseq"
SOURCE_EXT = ".xsq"
AUDIO_EXTS = (".wav", ".mp3")

# The vehicles a show is checked against when working out which one it suits.
CANDIDATE_VEHICLES = ("models", "modelx", "model3", "modely", "cybertruck")


@dataclasses.dataclass
class Example:
    name: str
    packaging: str                 # "zip" or "folder"
    cars: int = 0
    shows: int = 0
    sources: int = 0
    audio: int = 0
    duration_ms: Optional[int] = None
    suits: Optional[str] = None
    suits_share: float = 0.0

    @property
    def has_source(self) -> bool:
        return self.sources > 0

    @property
    def has_show(self) -> bool:
        return self.shows > 0

    def as_dict(self) -> dict:
        data = dataclasses.asdict(self)
        data["has_source"] = self.has_source
        data["has_show"] = self.has_show
        return data


def _members(path: str) -> List[str]:
    """Every file in an example, zipped or loose, as plain names."""
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as bundle:
            return [n for n in bundle.namelist() if not n.endswith("/")]
    found: List[str] = []
    for current, _, files in os.walk(path):
        for name in files:
            found.append(os.path.join(current, name))
    return found


def _first_fseq_bytes(path: str) -> Optional[bytes]:
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as bundle:
            for name in sorted(bundle.namelist()):
                if name.lower().endswith(FSEQ_EXT):
                    return bundle.read(name)
        return None
    for name in sorted(_members(path)):
        if name.lower().endswith(FSEQ_EXT):
            with open(name, "rb") as handle:
                return handle.read()
    return None


# A per-car folder, e.g. "Car #1". Matched on whole path segments only, so
# that Car_setup.jpg beside them is not counted as a car.
_CAR_FOLDER = re.compile(r"^car[ _#-]*\d+$", re.IGNORECASE)


def _car_count(members: Sequence[str]) -> int:
    """How many cars a set is for, from its per-car folders."""
    cars = set()
    for name in members:
        parts = name.replace("\\", "/").split("/")
        for part in parts[:-1]:              # directories only
            if _CAR_FOLDER.match(part):
                cars.add(part.lower())
    return len(cars)


def describe(path: str) -> Example:
    name = os.path.basename(path)
    if name.lower().endswith(".zip"):
        name = name[:-4]
    example = Example(
        name=name,
        packaging="zip" if path.lower().endswith(".zip") else "folder")

    members = _members(path)
    lowered = [m.lower() for m in members]
    example.shows = sum(1 for m in lowered if m.endswith(FSEQ_EXT))
    example.sources = sum(1 for m in lowered if m.endswith(SOURCE_EXT))
    example.audio = sum(1 for m in lowered if m.endswith(AUDIO_EXTS))
    example.cars = _car_count(members) or 1

    blob = _first_fseq_bytes(path)
    if blob is None:
        return example

    handle = tempfile.NamedTemporaryFile(suffix=FSEQ_EXT, delete=False)
    handle.write(blob)
    handle.close()
    try:
        show = vp.read_fseq(handle.name)
    except (vp.ShowError, OSError):
        return example
    finally:
        os.unlink(handle.name)

    example.duration_ms = show.duration_ms
    # Which vehicle shows the most of it. This is what the channels say,
    # not a statement about what the author intended.
    best, best_share = None, -1.0
    for key in CANDIDATE_VEHICLES:
        spread = vp.coverage(show, vp.VEHICLES[key])
        share = (spread.fitted / spread.total) if spread.total else 0.0
        if share > best_share:
            best, best_share = key, share
    example.suits = vp.VEHICLES[best].label if best else None
    example.suits_share = round(best_share, 4)
    return example


def collect(directory: str = EXAMPLES_DIR) -> List[Example]:
    entries = []
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if name.lower().endswith(".zip") or (
                os.path.isdir(path) and _members(path)):
            entries.append(describe(path))
    return entries


def _duration(ms: Optional[int]) -> str:
    if ms is None:
        return "-"
    minutes, seconds = divmod(int(round(ms / 1000.0)), 60)
    return "{}:{:02d}".format(minutes, seconds)


def render_markdown(examples: Sequence[Example]) -> str:
    lines = [
        "| Example | Cars | Show (.fseq) | Source (.xsq) | Length | Plays fullest on |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for example in examples:
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            example.name,
            example.cars,
            "yes" if example.has_show else "no",
            "yes" if example.has_source else "no",
            _duration(example.duration_ms),
            "{} ({:.0f}%)".format(example.suits, example.suits_share * 100)
            if example.suits else "-"))
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="List what each example in examples/ ships.")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of a markdown table")
    args = parser.parse_args(argv)

    try:
        examples = collect()
    except OSError as error:
        print(error, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([e.as_dict() for e in examples], indent=2))
    else:
        print(render_markdown(examples))
    return 0


if __name__ == "__main__":
    sys.exit(main())
