#!/usr/bin/env python3
"""Write out what a .fseq actually does, channel by channel.

https://github.com/teslamotors/light-show/issues/79 asks how to get the data
back out of a .fseq. There are two answers and this is the second one.

The first is xLights': open a sequence and import the .fseq as a data layer,
which is what you want if the goal is to edit the show again. README.md now
describes it.

The second is this, for when the goal is to read the show rather than edit it
-- to see what a download actually drives, to diff two shows, or to rebuild an
effect by hand. Community sites hand out .fseq files with no .xsq beside them,
so a show is often the only copy of itself.

    python3 tools/fseq_export.py lightshow.fseq
    python3 tools/fseq_export.py lightshow.fseq --channels 1-6
    python3 tools/fseq_export.py lightshow.fseq --json -o show.json

Each row is one stretch of frames holding one value on one channel, with the
effect that value means: the ramp codes for a light, Open/Dance/Close/Stop for
a closure, a component level for interior RGB. Nothing is interpreted beyond
what README.md documents.

Requires Python 3.7+ and only the standard library, matching validator.py.
"""

import argparse
import csv
import io
import json
import os
import sys
from typing import Dict, List, Optional, Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (REPO_ROOT, os.path.join(REPO_ROOT, "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import vehicle_preview as vp  # noqa: E402

FIELDS = ("channel", "name", "kind", "start_ms", "end_ms", "duration_ms",
          "frames", "value", "percent", "effect")


def describe_effect(channel: int, value: int) -> str:
    """What README.md says this byte means on this channel."""
    percent = vp.to_percent(value)
    _, kind = vp.CHANNELS.get(channel, ("", vp.LIGHT))

    if kind == vp.RGB:
        return "level {}".format(value)
    if kind == vp.CLOSURE:
        return vp.CLOSURE_CODES.get(percent, "undocumented ({}%)".format(
            percent))

    code = vp.RAMP_CODES.get(percent)
    if code is not None:
        action, ramp_ms = code
        return action if not ramp_ms else "{} over {} ms".format(
            action, ramp_ms)
    # Not one of the documented steps; say so rather than rounding it.
    return "{}% (on)".format(percent) if value > vp.ON_THRESHOLD \
        else "{}% (off)".format(percent)


def export(show: vp.Show, channels: Optional[Sequence[int]] = None,
           include_off: bool = False) -> List[Dict[str, object]]:
    """One row per stretch of frames holding one value."""
    wanted = list(channels) if channels else list(
        range(1, show.channel_count + 1))
    rows: List[Dict[str, object]] = []
    for channel in wanted:
        if channel < 1 or channel > show.channel_count:
            continue
        name, kind = vp.CHANNELS.get(
            channel, ("Channel {}".format(channel), vp.LIGHT))
        for run in vp.runs_of(show.series(channel)):
            if run.value == 0 and not include_off:
                continue
            start = run.start_frame * show.step_time_ms
            rows.append({
                "channel": channel,
                "name": name,
                "kind": kind,
                "start_ms": start,
                "end_ms": start + run.frames * show.step_time_ms,
                "duration_ms": run.frames * show.step_time_ms,
                "frames": run.frames,
                "value": run.value,
                "percent": vp.to_percent(run.value),
                "effect": describe_effect(channel, run.value),
            })
    rows.sort(key=lambda r: (r["start_ms"], r["channel"]))
    return rows


def render_csv(rows: Sequence[Dict[str, object]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def render_json(show: vp.Show, rows: Sequence[Dict[str, object]]) -> str:
    return json.dumps({
        "channel_count": show.channel_count,
        "frame_count": show.frame_count,
        "step_time_ms": show.step_time_ms,
        "duration_ms": show.duration_ms,
        "first_lit_ms": show.first_lit_ms(),
        "rows": list(rows),
    }, indent=2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write out what a .fseq does, one row per effect.")
    parser.add_argument("fseq", nargs="?", help="path to the .fseq show file")
    parser.add_argument("--channels",
                        help="limit to these channels, e.g. 1-6 or 13,17")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of CSV")
    parser.add_argument("--include-off", action="store_true",
                        help="include the stretches where a channel is at 0")
    parser.add_argument("-o", "--output",
                        help="write to this file instead of standard output")
    args = parser.parse_args(argv)

    path = args.fseq
    if not path:
        path = input(
            "Please enter the path by dragging and dropping the .fseq file: ")
        print("")
        path = path.strip('"').strip("'").strip(" ")

    try:
        show = vp.read_fseq(path)
    except (vp.ShowError, OSError) as error:
        print(error, file=sys.stderr)
        return 2

    channels: Optional[List[int]] = None
    if args.channels:
        try:
            channels = [c for step in _parse(args.channels) for c in step]
        except ValueError as error:
            print(error, file=sys.stderr)
            return 2

    rows = export(show, channels, include_off=args.include_off)
    text = (render_json(show, rows) if args.json else render_csv(rows))

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as error:
            print(error, file=sys.stderr)
            return 2
        print("Wrote {} row(s) to {}".format(len(rows), args.output))
    else:
        sys.stdout.write(text)
    return 0


def _parse(text: str) -> List[Sequence[int]]:
    """"1-6,13" into channel groups, reusing the probe's spelling."""
    groups: List[Sequence[int]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part.lstrip("-"):
            first, _, last = part.partition("-")
            try:
                low, high = int(first), int(last)
            except ValueError:
                raise ValueError("{!r} is not a channel range".format(part))
            groups.append(list(range(low, high + 1)))
        else:
            try:
                groups.append([int(part)])
            except ValueError:
                raise ValueError("{!r} is not a channel".format(part))
    return groups


if __name__ == "__main__":
    sys.exit(main())
