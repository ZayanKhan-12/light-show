#!/usr/bin/env python3
"""Run the right checks for whatever you have, and say which layer is at fault.

There are now nine tools here and no obvious place to start, which matters
because most "it does not work" reports cannot be acted on: they do not say
whether the drive, the file, the vehicle or the car's software is the problem.

https://github.com/teslamotors/light-show/issues/98 is the clearest example of
why that distinction is worth drawing. The show is accepted, the screen says
"enjoy the show", and then the car crashes -- which means the drive and the
file were fine by the time it failed, and nothing in this repository can fix
what did. That is a useful thing to be able to establish in one command.

    python3 tools/diagnose.py /Volumes/LIGHTSHOW
    python3 tools/diagnose.py lightshow.fseq
    python3 tools/diagnose.py lightshow.xsq
    python3 tools/diagnose.py ~/Downloads/tesla_xlights_show_folder

It runs the checks that apply, prints what they found, and ends with what has
been ruled out and what is left.

Requires Python 3.7+ and only the standard library, matching validator.py.
"""

import argparse
import json
import os
import sys
from typing import List, Optional, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (REPO_ROOT, os.path.join(REPO_ROOT, "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import multi_car_check  # noqa: E402
import sequence_check  # noqa: E402
import show_folder_check  # noqa: E402
import usb_check  # noqa: E402
import vehicle_preview  # noqa: E402

# The layers a show passes through, outermost first. Each one is only worth
# looking at once the one before it is sound.
DRIVE = "the USB drive"
SHOW_FILE = "the show file"
VEHICLE_FIT = "the show against your vehicle"
SEQUENCE = "the xLights sequence"
SHOW_FOLDER = "the xLights show folder"
VEHICLE_SOFTWARE = "the car's software"


class DiagnoseError(Exception):
    """Nothing here knows what to do with that path."""


def identify(path: str) -> str:
    """What kind of thing the user pointed at."""
    if os.path.isfile(path):
        lowered = path.lower()
        if lowered.endswith(".fseq"):
            return "show"
        if lowered.endswith(".xsq"):
            return "sequence"
        raise DiagnoseError(
            "{} is not something this can check. Give it a .fseq, a .xsq, a "
            "USB drive, or an xLights show folder.".format(
                os.path.basename(path)))

    if not os.path.isdir(path):
        raise DiagnoseError("{} does not exist".format(path))

    if show_folder_check.looks_like_show_folder(path):
        return "show folder"
    if multi_car_check.discover_cars(path):
        return "cross-vehicle set"
    return "drive"


def check_drive(path: str) -> Tuple[str, List[str], bool]:
    report = usb_check.check_drive(path)
    lines = usb_check.render_report(report, verbose=False).splitlines()
    return DRIVE, lines, report.counts()[usb_check.ERROR] == 0


def check_show(path: str, vehicle: Optional[str]) -> List[Tuple[str, List[str], bool]]:
    show = vehicle_preview.read_fseq(path)
    keys = [vehicle] if vehicle else sorted(vehicle_preview.VEHICLES)
    results = {k: vehicle_preview.analyze(show, vehicle_preview.VEHICLES[k])
               for k in keys}
    interior = vehicle_preview.analyze_interior(show)
    closures = vehicle_preview.analyze_closures(show)
    builds = {k: vehicle_preview.analyze_variants(
        show, vehicle_preview.VEHICLES[k]) for k in keys}
    text = vehicle_preview.render_report(show, results, False, interior,
                                         closures, builds)
    worst = any(f.severity == vehicle_preview.ERROR
                for group in results.values() for f in group)
    return [(VEHICLE_FIT, text.splitlines(), not worst)]


def check_sequence(path: str) -> Tuple[str, List[str], bool]:
    sequence = sequence_check.check_sequence(path)
    lines = sequence_check.render_report(sequence, verbose=False).splitlines()
    return SEQUENCE, lines, sequence.counts()[sequence_check.ERROR] == 0


def check_folder(path: str) -> Tuple[str, List[str], bool]:
    report = show_folder_check.check_show_folder(path)
    lines = show_folder_check.render_report(report, False).splitlines()
    return SHOW_FOLDER, lines, report.counts()[show_folder_check.ERROR] == 0


def check_set(path: str) -> Tuple[str, List[str], bool]:
    show_set = multi_car_check.check_set(path)
    lines = multi_car_check.render_report(show_set, False).splitlines()
    return "the cross-vehicle set", lines, \
        show_set.counts()[multi_car_check.ERROR] == 0


def run(path: str, vehicle: Optional[str] = None
        ) -> Tuple[str, List[Tuple[str, List[str], bool]]]:
    """Run whatever applies, returning (kind, [(layer, output, ok), ...])."""
    kind = identify(path)
    stages: List[Tuple[str, List[str], bool]] = []

    if kind == "show":
        stages.extend(check_show(path, vehicle))
    elif kind == "sequence":
        stages.append(check_sequence(path))
    elif kind == "show folder":
        stages.append(check_folder(path))
    elif kind == "cross-vehicle set":
        stages.append(check_set(path))
    else:
        stages.append(check_drive(path))
        report = usb_check.check_drive(path)
        for show in report.playable_shows:
            stages.extend(check_show(show.fseq_path, vehicle))
    return kind, stages


def conclude(stages: Sequence[Tuple[str, List[str], bool]]) -> List[str]:
    """What has been ruled out, and what that leaves."""
    failed = [layer for layer, _, ok in stages if not ok]
    checked = [layer for layer, _, _ in stages]
    out: List[str] = ["=" * 72, "What this rules out", "=" * 72]

    if failed:
        out.append("  Something here is wrong: {}.".format(
            ", ".join(sorted(set(failed)))))
        out.append("  Fix that before looking any further out; the errors "
                   "above say what.")
        return out

    out.append("  Checked and sound: {}.".format(", ".join(checked)))
    out.append("")
    out.append("  If the car still misbehaves, the remaining layer is")
    out.append("  {}, which nothing in this repository can "
               "change.".format(VEHICLE_SOFTWARE))
    out.append("  Symptoms that land there include the show")
    out.append("  starting and then stopping, the screen crashing, or the "
               "car refusing a")
    out.append("  drive every check here passes. Those belong with Tesla "
               "rather than in")
    out.append("  this issue tracker; see CONTRIBUTING.md.")
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the checks that apply to whatever you have, and say "
                    "which layer any problem is at.")
    parser.add_argument("path", nargs="?",
                        help="a drive, a .fseq, a .xsq, or an xLights show "
                             "folder")
    parser.add_argument("--vehicle", choices=sorted(vehicle_preview.VEHICLES),
                        help="limit the vehicle report to one vehicle")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON instead of text")
    args = parser.parse_args(argv)

    path = args.path
    if not path:
        path = input("Please enter the path by dragging and dropping what you "
                     "want checked: ")
        print("")
        path = path.strip('"').strip("'").strip(" ")
    path = os.path.abspath(os.path.expanduser(path))

    try:
        kind, stages = run(path, args.vehicle)
    except (DiagnoseError, multi_car_check.ShowSetError,
            sequence_check.SequenceError, show_folder_check.ShowFolderError,
            usb_check.DriveError, vehicle_preview.ShowError, OSError) as error:
        print(error, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "path": path,
            "kind": kind,
            "stages": [{"layer": layer, "ok": ok, "output": output}
                       for layer, output, ok in stages],
            "all_clear": all(ok for _, _, ok in stages),
        }, indent=2))
        return 0 if all(ok for _, _, ok in stages) else 1

    print("Looking at {}: {}".format(kind, path))
    print("")
    for layer, output, _ in stages:
        print("-" * 72)
        print("Checking {}".format(layer))
        print("-" * 72)
        print("\n".join(output))
        print("")
    print("\n".join(conclude(stages)))
    return 0 if all(ok for _, _, ok in stages) else 1


if __name__ == "__main__":
    sys.exit(main())
