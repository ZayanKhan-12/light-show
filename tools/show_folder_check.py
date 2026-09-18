#!/usr/bin/env python3
"""Check the folder you gave xLights, and the audio files in it.

https://github.com/teslamotors/light-show/issues/75 says only "the file
doesn't show up when I press custom and then I select file of model S", and
nobody answered it. Following README.md, "Creating a new sequence", that is
step 4 -- choosing the audio for a new Musical Sequence -- and there are two
ordinary reasons a file is not in that list:

  - xLights' file picker has a file type dropdown, and a .wav is hidden
    unless it is set to "xLights Audio Files". The README notes this and
    images/wav_hidden.png shows it.
  - the file is not a format xLights lists at all. An .m4a from a music
    library never appears, however the filter is set.

The other half of the sentence, "model S", is the show folder. If xLights was
pointed at the wrong folder -- the zip, the folder above it, or the extra
folder that "Extract All" leaves behind -- then nothing Tesla appears either.

All of that is checkable from disk:

    python3 tools/show_folder_check.py ~/Downloads/tesla_xlights_show_folder
    python3 tools/show_folder_check.py ~/Downloads --json

Requires Python 3.7+ and only the standard library, matching validator.py.
"""

import argparse
import dataclasses
import json
import os
import sys
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (REPO_ROOT, os.path.join(REPO_ROOT, "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import usb_check  # noqa: E402

ERROR = "error"
WARNING = "warning"
INFO = "info"

_SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}

# What a correctly extracted project folder has at its top level.
RGBEFFECTS = "xlights_rgbeffects.xml"
NETWORKS = "xlights_networks.xml"
REQUIRED_FILES = (RGBEFFECTS, NETWORKS)
EXPECTED_FILES = REQUIRED_FILES + ("xlights_keybindings.xml",)

# README.md, "Audio file requirements": the vehicle plays .mp3 and .wav.
PLAYABLE_AUDIO = usb_check.AUDIO_EXTS
# Formats a music library hands you that xLights will not list. This is not
# every audio extension in existence -- it is the ones people actually arrive
# with, and anything unknown is left alone rather than guessed at.
UNLISTED_AUDIO = (".m4a", ".m4p", ".aac", ".flac", ".wma", ".ogg", ".opus",
                  ".aiff", ".aif", ".alac", ".amr", ".mp4")

# The dropdown in images/wav_hidden.png.
AUDIO_FILE_TYPE = "xLights Audio Files"

# xlights_networks.xml gives one 200-channel controller per car; see
# validator.describe_channel_count().
CHANNELS_PER_CAR = 200


class ShowFolderError(Exception):
    """The path could not be looked at."""


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
class AudioFile:
    name: str
    listed_by_xlights: bool
    sample_rate: Optional[int] = None

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class ShowFolder:
    path: str
    is_show_folder: bool = False
    controllers: int = 0
    channels: int = 0
    models: int = 0
    audio: List[AudioFile] = dataclasses.field(default_factory=list)
    findings: List[Finding] = dataclasses.field(default_factory=list)

    @property
    def cars(self) -> int:
        return self.channels // CHANNELS_PER_CAR if self.channels else 0

    def counts(self) -> Dict[str, int]:
        counts = {ERROR: 0, WARNING: 0, INFO: 0}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "is_show_folder": self.is_show_folder,
            "controllers": self.controllers,
            "channels": self.channels,
            "cars": self.cars,
            "models": self.models,
            "audio": [a.as_dict() for a in self.audio],
            "findings": [f.as_dict() for f in self.findings],
            "counts": self.counts(),
        }


# --------------------------------------------------------------------------
# Finding the project folder
# --------------------------------------------------------------------------


def _entries(path: str) -> List[str]:
    try:
        return sorted(os.listdir(path))
    except OSError as error:
        raise ShowFolderError("Cannot read {}: {}".format(path, error))


def _zip_problem(path: str) -> Optional[str]:
    """Why this .zip cannot be read, or None when it is fine.

    Only the archive is checked, not its contents: a truncated download is
    the failure this is for, and reading every entry of a 41 MB archive to
    say so would be slower than downloading it again.
    """
    try:
        with zipfile.ZipFile(path) as bundle:
            if not bundle.namelist():
                return "The archive is empty."
    except zipfile.BadZipFile as error:
        return "It is not a readable zip archive ({}).".format(error)
    except OSError as error:
        return str(error)
    return None


def looks_like_show_folder(path: str) -> bool:
    return os.path.isfile(os.path.join(path, RGBEFFECTS))


def locate_show_folder(path: str) -> Tuple[Optional[str], List[Finding]]:
    """Find the project folder at or below `path`."""
    findings: List[Finding] = []

    if os.path.isfile(path):
        if path.lower().endswith(".zip"):
            # A download that stopped part way is a file of the right name
            # and the wrong length, which is worth telling apart from simply
            # not having unzipped it yet.
            # https://github.com/teslamotors/light-show/issues/101
            broken = _zip_problem(path)
            if broken:
                findings.append(Finding(
                    ERROR, "download-incomplete",
                    "That .zip cannot be opened.",
                    "{} The usual cause is a download that stopped part way. "
                    "Download it again, and compare the size with the one "
                    "GitHub shows on the file's page before "
                    "unzipping.".format(broken),
                    readme="Getting started with the Tesla xLights project "
                           "directory"))
                return None, findings
            findings.append(Finding(
                ERROR, "not-extracted",
                "That is the .zip, not a folder.",
                "The archive is intact. xLights needs the unzipped project "
                "directory, so extract {} first, then select the folder it "
                "produces.".format(os.path.basename(path)),
                readme="Getting started with the Tesla xLights project "
                       "directory"))
        else:
            findings.append(Finding(
                ERROR, "not-a-folder",
                "{} is a file, not a folder.".format(os.path.basename(path)),
                "Select the unzipped project directory.",
                readme="Getting started with the Tesla xLights project "
                       "directory"))
        return None, findings

    if not os.path.isdir(path):
        raise ShowFolderError("{} does not exist".format(path))

    if looks_like_show_folder(path):
        return path, findings

    # "Extract All" on Windows makes a folder of the same name around the
    # one in the zip, and selecting the outer one finds nothing.
    nested = [name for name in _entries(path)
              if os.path.isdir(os.path.join(path, name))
              and looks_like_show_folder(os.path.join(path, name))]
    if len(nested) == 1:
        inner = os.path.join(path, nested[0])
        findings.append(Finding(
            ERROR, "folder-one-level-up",
            "The project folder is one level down, in {}.".format(nested[0]),
            "Unzipping can leave a folder of the same name around the real "
            "one. In File > Select Show Folder, choose this instead: "
            "{}".format(inner),
            readme="Getting started with the Tesla xLights project "
                   "directory"))
        return inner, findings
    if len(nested) > 1:
        findings.append(Finding(
            ERROR, "several-show-folders",
            "{} project folders are inside this one.".format(len(nested)),
            "Found {}. Select the one you mean, not the folder holding "
            "them.".format(", ".join(nested)),
            readme="Getting started with the Tesla xLights project "
                   "directory"))
        return None, findings

    zips = [name for name in _entries(path) if name.lower().endswith(".zip")
            and "xlights" in name.lower()]
    if zips:
        findings.append(Finding(
            ERROR, "still-zipped",
            "This folder holds {} but nothing is unzipped.".format(zips[0]),
            "Extract it, then select the folder it produces.",
            readme="Getting started with the Tesla xLights project "
                   "directory"))
        return None, findings

    findings.append(Finding(
        ERROR, "not-a-show-folder",
        "No {} here, so xLights will not find the Tesla models.".format(
            RGBEFFECTS),
        "A project folder has {} in it. Download and unzip "
        "tesla_xlights_show_folder.zip, then point File > Select Show Folder "
        "at the unzipped folder.".format(", ".join(EXPECTED_FILES)),
        readme="Getting started with the Tesla xLights project directory"))
    return None, findings


# --------------------------------------------------------------------------
# Reading the project folder
# --------------------------------------------------------------------------


def _read_controllers(folder: str) -> Tuple[int, int]:
    """(controllers, total channels) from xlights_networks.xml."""
    path = os.path.join(folder, NETWORKS)
    if not os.path.isfile(path):
        return 0, 0
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return 0, 0
    controllers = root.findall("Controller")
    channels = sum(int(network.get("MaxChannels", 0))
                   for controller in controllers
                   for network in controller.findall("network"))
    return len(controllers), channels


def _read_models(folder: str) -> int:
    path = os.path.join(folder, RGBEFFECTS)
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return 0
    models = root.find("models")
    return len(list(models)) if models is not None else 0


def _read_audio(folder: str) -> List[AudioFile]:
    files: List[AudioFile] = []
    for name in _entries(folder):
        if name.startswith("."):
            continue
        full = os.path.join(folder, name)
        if not os.path.isfile(full):
            continue
        lowered = os.path.splitext(name)[1].lower()
        if lowered in PLAYABLE_AUDIO:
            track = usb_check.read_audio(full)
            files.append(AudioFile(name=name, listed_by_xlights=True,
                                   sample_rate=track.sample_rate))
        elif lowered in UNLISTED_AUDIO:
            files.append(AudioFile(name=name, listed_by_xlights=False))
    return files


def check_show_folder(path: str) -> ShowFolder:
    """Report what xLights will and will not find in this folder."""
    path = os.path.abspath(os.path.expanduser(path))
    folder, findings = locate_show_folder(path)
    report = ShowFolder(path=folder or path)
    report.findings.extend(findings)

    if folder is None:
        return report

    report.is_show_folder = True
    missing = [name for name in REQUIRED_FILES
               if not os.path.isfile(os.path.join(folder, name))]
    if missing:
        report.findings.append(Finding(
            ERROR, "incomplete-show-folder",
            "The project folder is missing {}.".format(", ".join(missing)),
            "Unzip tesla_xlights_show_folder.zip again and keep the folder "
            "as it comes; the files are not optional.",
            readme="Getting started with the Tesla xLights project "
                   "directory"))

    report.controllers, report.channels = _read_controllers(folder)
    report.models = _read_models(folder)

    if report.cars > 1:
        report.findings.append(Finding(
            INFO, "cross-vehicle-folder",
            "This is the cross-vehicle folder, set up for {} cars.".format(
                report.cars),
            "It is the right folder for programming a show that runs across "
            "several cars, and the wrong one for a single car: a sequence "
            "built here exports {} channels, which one car will not play. "
            "Use tesla_xlights_show_folder for a single-car show.".format(
                report.channels),
            readme="Programming a show with cross-vehicle animations"))

    if report.models == 0:
        report.findings.append(Finding(
            WARNING, "no-models",
            "The project folder has no models in it.",
            "xLights will open it, but the Layout tab will be empty and no "
            "Tesla lights will appear in the sequencer.",
            readme="Getting started with the Tesla xLights project "
                   "directory"))

    report.audio = _read_audio(folder)
    _check_audio(report)
    return report


def _check_audio(report: ShowFolder) -> None:
    unlisted = [a for a in report.audio if not a.listed_by_xlights]
    listed = [a for a in report.audio if a.listed_by_xlights]

    if unlisted:
        report.findings.append(Finding(
            WARNING, "audio-format-not-listed",
            "{} audio file(s) here are a format xLights does not "
            "offer.".format(len(unlisted)),
            "Found {}. These never appear when choosing the audio for a new "
            "sequence, whatever the file type dropdown is set to. Convert to "
            ".wav at 44.1 kHz, or use an .mp3.".format(
                ", ".join(a.name for a in unlisted)),
            readme="Audio file requirements"))

    for track in listed:
        if track.sample_rate and track.sample_rate != 44100:
            report.findings.append(Finding(
                WARNING, "audio-sample-rate",
                "{} is {} Hz, not 44100 Hz.".format(
                    track.name, track.sample_rate),
                "It will sequence, but it will not stay in sync with the "
                "lights on the car.",
                readme="Audio file requirements"))

    if listed:
        report.findings.append(Finding(
            INFO, "audio-file-type-filter",
            "{} audio file(s) here should appear when creating a "
            "sequence.".format(len(listed)),
            'If the picker looks empty anyway, its file type dropdown is set '
            'to one of the FPP options; change it to "{}". Found: '
            "{}.".format(AUDIO_FILE_TYPE,
                         ", ".join(a.name for a in listed)),
            readme="Creating a new sequence"))
    elif not unlisted:
        report.findings.append(Finding(
            INFO, "no-audio-here",
            "There is no audio file in the project folder.",
            "That is fine -- the audio can live anywhere -- but if you meant "
            "to keep it here, this is why the picker is empty.",
            readme="Creating a new sequence"))


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


def render_report(report: ShowFolder, verbose: bool) -> str:
    out = ["Folder: {}".format(report.path)]
    if report.is_show_folder:
        out.append("  {} model(s), {} controller(s), {} channel(s)".format(
            report.models, report.controllers, report.channels))
        if report.audio:
            out.append("  audio: {}".format(", ".join(
                "{}{}".format(a.name, "" if a.listed_by_xlights
                              else " (not listed by xLights)")
                for a in report.audio)))
    out.append("")

    shown = [f for f in report.findings if verbose or f.severity != INFO]
    for finding in shown:
        out.append("  [{}] {}".format(_MARKERS[finding.severity],
                                      finding.code))
        out.append(_wrap(finding.summary, 76, "    "))
        out.append(_wrap(finding.detail, 76, "      "))
        if finding.readme:
            out.append("      README: {}".format(finding.readme))
        out.append("")

    counts = report.counts()
    out.append("{} error(s), {} warning(s), {} note(s).".format(
        counts[ERROR], counts[WARNING], counts[INFO]))
    if counts[INFO] and not verbose:
        out.append("Re-run with -v to see the notes.")
    if report.is_show_folder and not counts[ERROR] and not counts[WARNING]:
        out.append("Give this folder to File > Select Show Folder.")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the folder given to xLights as the show folder, "
                    "and the audio files in it.")
    parser.add_argument("path", nargs="?",
                        help="the unzipped project directory")
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
                     "xLights show folder: ")
        print("")
        path = path.strip('"').strip("'").strip(" ")

    try:
        report = check_show_folder(path)
    except (ShowFolderError, OSError) as error:
        print(error, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(render_report(report, args.verbose))

    counts = report.counts()
    if counts[ERROR] or (args.strict and counts[WARNING]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
