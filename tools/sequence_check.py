#!/usr/bin/env python3
"""Check an xLights sequence (.xsq) before it becomes a show.

https://github.com/teslamotors/light-show/issues/66 reports a dialog that
reads "Graphics Driver Problem: Paste By Cell information missing. You can
only Paste By Time with this data." The owner updated their graphics driver
and logged Windows out and back in every few minutes for a year. The title is
xLights' own, and it is misleading: nothing about it involves the graphics
driver. Paste By Cell pastes into the cells made by the marks on a timing
track, and a sequence with no timing marks has no cells to paste into.

The .xsq records its timing tracks, its frame interval and its length, so that
is checkable here rather than guessed at in a thread:

    python3 tools/sequence_check.py lightshow.xsq
    python3 tools/sequence_check.py lightshow.xsq --json
    python3 tools/sequence_check.py lightshow.xsq --strict

An .xsq is xLights' file, not the vehicle's, so nothing here is a rule about
what the car will play -- validator.py owns that. These are the things that
make a sequence awkward to work on or impossible to export cleanly, and every
one of them cites the README section it comes from.

Requires Python 3.7+ and only the standard library, matching validator.py.
"""

import argparse
import dataclasses
import json
import os
import sys
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Sequence

ERROR = "error"
WARNING = "warning"
INFO = "info"

_SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}

# README.md, "Getting started with the Tesla xLights project directory":
# "any value between 15ms and 100ms is supported by the vehicle, but 20ms is
# recommended for nearly all use cases".
MIN_FRAME_MS = 15
MAX_FRAME_MS = 100
RECOMMENDED_FRAME_MS = 20

# README.md, "General Limitations of Custom Shows".
MAX_DURATION_S = 4 * 60 * 60

# The wording xLights puts on the dialog in issue #66, kept verbatim so that
# searching the phrase from the screen reaches this explanation.
PASTE_BY_CELL_DIALOG = (
    "Graphics Driver Problem: Paste By Cell information missing. "
    "You can only Paste By Time with this data.")


class SequenceError(Exception):
    """The file could not be read as an xLights sequence."""


@dataclasses.dataclass
class Finding:
    severity: str
    code: str
    summary: str
    detail: str
    readme: Optional[str] = None

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class TimingTrack:
    name: str
    marks: int

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Sequence_:
    path: str
    xlights_version: str = ""
    frame_ms: Optional[int] = None
    duration_s: Optional[float] = None
    media_file: str = ""
    sequence_type: str = ""
    model_elements: int = 0
    timing_tracks: List[TimingTrack] = dataclasses.field(default_factory=list)
    # Data layers imported into the sequence, by source. xLights gives every
    # sequence one auto-generated layer; an imported .fseq adds another.
    data_layers: List[str] = dataclasses.field(default_factory=list)
    findings: List[Finding] = dataclasses.field(default_factory=list)

    @property
    def total_marks(self) -> int:
        return sum(track.marks for track in self.timing_tracks)

    def counts(self) -> Dict[str, int]:
        counts = {ERROR: 0, WARNING: 0, INFO: 0}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "xlights_version": self.xlights_version,
            "frame_ms": self.frame_ms,
            "duration_s": self.duration_s,
            "media_file": self.media_file,
            "sequence_type": self.sequence_type,
            "model_elements": self.model_elements,
            "timing_tracks": [t.as_dict() for t in self.timing_tracks],
            "data_layers": list(self.data_layers),
            "total_marks": self.total_marks,
            "findings": [f.as_dict() for f in self.findings],
            "counts": self.counts(),
        }


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def _text(head: Optional[ET.Element], tag: str) -> str:
    if head is None:
        return ""
    return (head.findtext(tag) or "").strip()


def _frame_ms(value: str) -> Optional[int]:
    """xLights writes the frame interval as "25 ms"."""
    digits = "".join(c for c in value if c.isdigit())
    return int(digits) if digits else None


def read_sequence(path: str) -> Sequence_:
    """Parse the parts of an .xsq this tool reasons about."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise SequenceError("{} is not readable as XML: {}".format(
            path, error))
    except OSError as error:
        raise SequenceError(str(error))

    if root.tag != "xsequence":
        raise SequenceError(
            "{} is not an xLights sequence (root element is <{}>, expected "
            "<xsequence>). The .xsq is the sequence you edit; the .fseq the "
            "car plays is checked with validator.py.".format(path, root.tag))

    head = root.find("head")
    sequence = Sequence_(
        path=path,
        xlights_version=_text(head, "version"),
        frame_ms=_frame_ms(_text(head, "sequenceTiming")),
        media_file=_text(head, "mediaFile"),
        sequence_type=_text(head, "sequenceType"),
    )
    duration = _text(head, "sequenceDuration")
    try:
        sequence.duration_s = float(duration) if duration else None
    except ValueError:
        sequence.duration_s = None

    layers = root.find("DataLayers")
    for layer in (layers if layers is not None else []):
        source = (layer.get("source") or "").strip()
        # Every sequence carries one of these whether or not anything was
        # imported; it is not a data layer the author added.
        if source and source != "<auto-generated>":
            sequence.data_layers.append(source)

    effects = root.find("ElementEffects")
    for element in (effects if effects is not None else []):
        if element.get("type") == "timing":
            marks = sum(len(list(layer)) for layer in element)
            sequence.timing_tracks.append(
                TimingTrack(name=element.get("name") or "", marks=marks))
        else:
            sequence.model_elements += 1
    return sequence


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def check_sequence(path: str) -> Sequence_:
    sequence = read_sequence(path)
    _check_timing_marks(sequence)
    _check_frame_interval(sequence)
    _check_duration(sequence)
    _check_media(sequence)
    sequence.findings.sort(key=lambda f: _SEVERITY_ORDER[f.severity])
    return sequence


def _check_timing_marks(sequence: Sequence_) -> None:
    """Issue #66: no marks means no cells, and Paste By Cell cannot work."""
    if sequence.total_marks == 0:
        sequence.findings.append(Finding(
            WARNING, "no-timing-marks",
            "This sequence has no timing marks, so Paste By Cell cannot be "
            "used.",
            'Pasting by cell pastes into the cells a timing track divides the '
            'sequence into. With no marks there are no cells, and xLights '
            'reports that as "{}" -- a misleading title, since the graphics '
            'driver has nothing to do with it. Either choose Paste By Time in '
            'the toolbar, or add a timing track from the xLights Timing '
            'menu and put marks on it.'.format(PASTE_BY_CELL_DIALOG),
            readme="Working with timing tracks"))
        return

    empty = [t for t in sequence.timing_tracks if t.marks == 0]
    if empty:
        sequence.findings.append(Finding(
            INFO, "empty-timing-track",
            "{} timing track(s) have no marks.".format(len(empty)),
            "Found {}. Pasting by cell while one of these is the active "
            "track behaves as though the sequence had no timing at "
            "all.".format(", ".join(repr(t.name) for t in empty)),
            readme="Working with timing tracks"))


def _check_frame_interval(sequence: Sequence_) -> None:
    interval = sequence.frame_ms
    if interval is None:
        sequence.findings.append(Finding(
            WARNING, "frame-interval-unknown",
            "The sequence does not record a frame interval.",
            "xLights writes this as sequenceTiming in the .xsq. Without it "
            "there is no way to tell what the exported show will run at.",
            readme="Getting started with the Tesla xLights project directory"))
        return

    if interval < MIN_FRAME_MS or interval > MAX_FRAME_MS:
        sequence.findings.append(Finding(
            ERROR, "frame-interval-unsupported",
            "The frame interval is {} ms; the vehicle supports {} to "
            "{} ms.".format(interval, MIN_FRAME_MS, MAX_FRAME_MS),
            "A show exported at this interval will not play. Create the "
            "sequence again with a supported interval; {} ms is recommended "
            "for nearly all use cases.".format(RECOMMENDED_FRAME_MS),
            readme="Getting started with the Tesla xLights project directory"))
    elif interval != RECOMMENDED_FRAME_MS:
        sequence.findings.append(Finding(
            INFO, "frame-interval-not-recommended",
            "The frame interval is {} ms rather than the recommended "
            "{} ms.".format(interval, RECOMMENDED_FRAME_MS),
            "This is supported and shows do ship at other intervals; the "
            "maximum show size does not depend on the interval.",
            readme="Getting started with the Tesla xLights project directory"))


def _check_duration(sequence: Sequence_) -> None:
    if sequence.duration_s is None:
        return
    if sequence.duration_s > MAX_DURATION_S:
        sequence.findings.append(Finding(
            ERROR, "duration-too-long",
            "The sequence is {:.0f} s; the maximum is 4 hours.".format(
                sequence.duration_s),
            "A show longer than 4 hours is rejected by the vehicle.",
            readme="General Limitations of Custom Shows"))


def _check_media(sequence: Sequence_) -> None:
    if sequence.sequence_type.lower() == "media" and not sequence.media_file:
        sequence.findings.append(Finding(
            WARNING, "no-media-file",
            "This is a musical sequence with no audio file attached.",
            "The sequence was created as a Musical Sequence but records no "
            "media file, so there is nothing to sequence against and nothing "
            "to copy onto the drive beside the .fseq.",
            readme="USB flash drive requirements"))
        return

    if sequence.media_file and not os.path.exists(sequence.media_file):
        sequence.findings.append(Finding(
            INFO, "media-file-not-on-this-machine",
            "The audio is referenced by a path from the machine that made "
            "the sequence.",
            "xLights stores the full path, so opening someone else's "
            "sequence asks for the audio again. This is normal for a "
            "downloaded show. Path recorded: {}".format(sequence.media_file)))


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


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


def render_report(sequence: Sequence_, verbose: bool) -> str:
    out: List[str] = [
        "Sequence: {}".format(sequence.path),
        "  xLights {}, {} ms frames, {}".format(
            sequence.xlights_version or "version not recorded",
            sequence.frame_ms if sequence.frame_ms else "?",
            "{:.1f} s".format(sequence.duration_s)
            if sequence.duration_s else "length not recorded"),
        "  {} model element(s), {} timing track(s), {} mark(s)".format(
            sequence.model_elements, len(sequence.timing_tracks),
            sequence.total_marks),
        "",
    ]
    if sequence.data_layers:
        out.insert(3, "  imported data layer(s): {}".format(
            ", ".join(os.path.basename(s) for s in sequence.data_layers)))
    if sequence.timing_tracks and verbose:
        out.append("Timing tracks:")
        for track in sequence.timing_tracks:
            out.append("  {:<24} {:>5} mark(s)".format(
                repr(track.name), track.marks))
        out.append("")

    shown = [f for f in sequence.findings if verbose or f.severity != INFO]
    for finding in shown:
        out.append("  [{}] {}".format(_MARKERS[finding.severity],
                                      finding.code))
        out.append(_wrap(finding.summary, 76, "    "))
        out.append(_wrap(finding.detail, 76, "      "))
        if finding.readme:
            out.append("      README: {}".format(finding.readme))
        out.append("")

    counts = sequence.counts()
    out.append("{} error(s), {} warning(s), {} note(s).".format(
        counts[ERROR], counts[WARNING], counts[INFO]))
    if counts[INFO] and not verbose:
        out.append("Re-run with -v to see the notes.")
    if not counts[ERROR] and not counts[WARNING]:
        out.append("This sequence is in good shape.")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check an xLights .xsq sequence for the things that make "
                    "it awkward to work on or impossible to export cleanly.")
    parser.add_argument("sequence", nargs="?", help="path to the .xsq file")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON instead of text")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="include the timing tracks and the notes")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero on warnings as well as errors")
    args = parser.parse_args(argv)

    path = args.sequence
    if not path:
        path = input(
            "Please enter the path by dragging and dropping the .xsq file: ")
        print("")
        path = path.strip('"').strip("'").strip(" ")

    try:
        sequence = check_sequence(path)
    except (SequenceError, OSError) as error:
        print(error, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(sequence.as_dict(), indent=2))
    else:
        print(render_report(sequence, args.verbose))

    counts = sequence.counts()
    if counts[ERROR] or (args.strict and counts[WARNING]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
