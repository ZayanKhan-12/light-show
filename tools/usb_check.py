#!/usr/bin/env python3
"""Check a USB flash drive that holds one or more custom light shows.

Vehicle software 2023.44.25 added support for keeping several custom shows on
one flash drive, which is what
https://github.com/teslamotors/light-show/issues/48 asked for.  The car finds
them by convention: every `.fseq` at the top level of the base-level
`LightShow` folder is one entry in the picker, and each one is paired with the
`.mp3`/`.wav` that shares its filename.  Nothing tells the owner which of those
conventions a drive has broken -- the show simply does not appear, or the
dialog title stays "Light Show" instead of "Custom Light Show".

This tool reads a drive (or a folder laid out like one) and reports the list of
shows the car will offer, plus the reason any other show was left out.

Usage:
    python3 tools/usb_check.py /Volumes/LIGHTSHOW
    python3 tools/usb_check.py /Volumes/LIGHTSHOW/LightShow
    python3 tools/usb_check.py E:\\ --json
    python3 tools/usb_check.py /Volumes/LIGHTSHOW --strict

Every requirement encoded here is sourced from README.md; the section that
backs each rule is named in the finding's `readme` field so the two stay
reviewable side by side.  Where the README is silent -- the order of the picker
list, the exact naming of a map update file -- the finding says so rather than
presenting the guess as fact.

Requires Python 3.7+ and only the standard library, matching validator.py.
"""

import argparse
import dataclasses
import json
import os
import struct
import subprocess
import sys
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# The .fseq rules live in validator.py and are shared with the packaged
# validator the README points users at.  Import them rather than restating
# them, so a limit only ever changes in one place.
import validator  # noqa: E402

ERROR = "error"
WARNING = "warning"
INFO = "info"

_SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}

# README, "USB flash drive requirements".
SHOW_FOLDER = "LightShow"
FSEQ_EXT = ".fseq"
AUDIO_EXTS = (".wav", ".mp3")

# README, "USB flash drive requirements": a base-level TeslaCam folder stops
# the drive being read as a light show drive.
TESLACAM_FOLDER = "TeslaCam"

# README, "USB flash drive requirements".
SUPPORTED_FILESYSTEMS = {
    "exfat": "exFAT",
    "msdos": "MS-DOS FAT",
    "vfat": "FAT32",
    "fat": "FAT",
    "fat32": "FAT32",
    "ext3": "ext3",
    "ext4": "ext4",
}
# NTFS is called out by name in the README as unsupported.
REJECTED_FILESYSTEMS = {"ntfs": "NTFS"}

# README, "Audio file requirements".
REQUIRED_SAMPLE_RATE = 44100

# README, "USB flash drive requirements": more than one show on a drive needs
# 2023.44.25+, while a single show needs the v11.0 (2021.44.25) baseline from
# "Supported Vehicles".  The drive cannot tell which the car is running.
MULTI_SHOW_SOFTWARE = "2023.44.25"
BASE_SOFTWARE = "v11.0 (2021.44.25)"

# macOS writes these next to the real files on a FAT/exFAT volume.  They are
# not shows, but `._show.fseq` does sit in the folder next to `show.fseq`.
_APPLEDOUBLE_PREFIX = "._"
_IGNORED_NAMES = {".DS_Store", ".Spotlight-V100", ".fseventsd", ".Trashes",
                  "__MACOSX", "System Volume Information", ".TemporaryItems"}

# Files that are plainly part of authoring a show rather than playing it.  The
# repository's own examples ship a .xsq beside the .fseq, so their presence is
# reported as a note, never as a problem.
_AUTHORING_EXTS = (".xsq", ".xml", ".xbkp", ".fseq.bak")


class DriveError(Exception):
    """The drive or folder could not be read at all."""


@dataclasses.dataclass
class Finding:
    severity: str
    code: str
    summary: str
    detail: str
    path: Optional[str] = None
    readme: Optional[str] = None

    def as_dict(self) -> Dict[str, Optional[str]]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Audio:
    path: str
    kind: str                      # "wav" or "mp3"
    sample_rate: Optional[int] = None
    duration_ms: Optional[int] = None
    estimated: bool = False        # duration is an estimate, not a read length
    error: Optional[str] = None    # header could not be parsed


@dataclasses.dataclass
class Show:
    """One entry the car will show in the Light Show picker."""
    name: str
    fseq_path: str
    audio: Optional[Audio] = None
    frame_count: Optional[int] = None
    step_time_ms: Optional[int] = None
    duration_ms: Optional[int] = None
    findings: List[Finding] = dataclasses.field(default_factory=list)

    @property
    def playable(self) -> bool:
        return not any(f.severity == ERROR for f in self.findings)

    def as_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "fseq": self.fseq_path,
            "audio": dataclasses.asdict(self.audio) if self.audio else None,
            "frame_count": self.frame_count,
            "step_time_ms": self.step_time_ms,
            "duration_ms": self.duration_ms,
            "playable": self.playable,
            "findings": [f.as_dict() for f in self.findings],
        }


@dataclasses.dataclass
class DriveReport:
    root: str
    show_folder: Optional[str]
    filesystem: Optional[str]
    shows: List[Show] = dataclasses.field(default_factory=list)
    findings: List[Finding] = dataclasses.field(default_factory=list)

    @property
    def playable_shows(self) -> List[Show]:
        return [s for s in self.shows if s.playable]

    def all_findings(self) -> List[Finding]:
        out = list(self.findings)
        for show in self.shows:
            out.extend(show.findings)
        return out

    def counts(self) -> Dict[str, int]:
        counts = {ERROR: 0, WARNING: 0, INFO: 0}
        for finding in self.all_findings():
            counts[finding.severity] += 1
        return counts

    def as_dict(self) -> Dict[str, object]:
        return {
            "root": self.root,
            "show_folder": self.show_folder,
            "filesystem": self.filesystem,
            "playable_show_count": len(self.playable_shows),
            "shows": [s.as_dict() for s in self.shows],
            "findings": [f.as_dict() for f in self.findings],
            "counts": self.counts(),
        }


# --------------------------------------------------------------------------
# Audio headers
# --------------------------------------------------------------------------
# Both parsers read only what the checks need -- the sample rate, and enough to
# put a length on the file.  Neither decodes audio, so an unusual but valid
# file is reported as "could not read", never as a failure of the drive.


def _read_wav(path: str) -> Audio:
    """Pull the sample rate and length out of a RIFF/WAVE header.

    `wave` from the standard library rejects some otherwise playable files
    (WAVE_FORMAT_EXTENSIBLE, stray chunks), so walk the chunks directly.
    """
    audio = Audio(path=path, kind="wav")
    try:
        with open(path, "rb") as handle:
            riff = handle.read(12)
            if len(riff) < 12 or riff[0:4] != b"RIFF" or riff[8:12] != b"WAVE":
                audio.error = "not a RIFF/WAVE file"
                return audio
            byte_rate = None
            while True:
                header = handle.read(8)
                if len(header) < 8:
                    break
                chunk_id, size = struct.unpack("<4sI", header)
                if chunk_id == b"fmt ":
                    fmt = handle.read(min(size, 16))
                    if len(fmt) >= 16:
                        (_fmt_tag, _channels, sample_rate, byte_rate,
                         _align, _bits) = struct.unpack("<HHIIHH", fmt[:16])
                        audio.sample_rate = sample_rate
                    handle.seek(size - len(fmt), os.SEEK_CUR)
                elif chunk_id == b"data":
                    if byte_rate:
                        audio.duration_ms = int(size * 1000 / byte_rate)
                    break
                else:
                    handle.seek(size, os.SEEK_CUR)
                if size % 2:            # RIFF chunks are word aligned
                    handle.seek(1, os.SEEK_CUR)
    except OSError as error:
        audio.error = str(error)
    if audio.sample_rate is None and audio.error is None:
        audio.error = "no fmt chunk found"
    return audio


# MPEG audio frame header fields, from the bit layout in ISO/IEC 11172-3.
_MPEG_RATES = {
    3: (44100, 48000, 32000),      # MPEG 1
    2: (22050, 24000, 16000),      # MPEG 2
    0: (11025, 12000, 8000),       # MPEG 2.5
}
_MPEG1_LAYER3_BITRATES = (None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160,
                          192, 224, 256, 320, None)
_MPEG2_LAYER3_BITRATES = (None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112,
                          128, 144, 160, None)


def _skip_id3(handle) -> int:
    """Return the offset of the first MPEG frame, skipping an ID3v2 tag."""
    head = handle.read(10)
    if len(head) == 10 and head[0:3] == b"ID3":
        # The size is four 7-bit bytes.
        size = 0
        for byte in head[6:10]:
            size = (size << 7) | (byte & 0x7F)
        return 10 + size
    return 0


def _read_mp3(path: str) -> Audio:
    """Pull the sample rate and an estimated length out of an MP3."""
    audio = Audio(path=path, kind="mp3", estimated=True)
    try:
        file_size = os.path.getsize(path)
        with open(path, "rb") as handle:
            start = _skip_id3(handle)
            handle.seek(start)
            window = handle.read(65536)
            index = _find_frame_sync(window)
            if index is None:
                audio.error = "no MPEG frame header found"
                return audio
            header = window[index:index + 4]
            version_bits = (header[1] >> 3) & 0x03
            bitrate_index = (header[2] >> 4) & 0x0F
            rate_index = (header[2] >> 2) & 0x03
            if version_bits not in _MPEG_RATES or rate_index == 3:
                audio.error = "unrecognised MPEG frame header"
                return audio
            audio.sample_rate = _MPEG_RATES[version_bits][rate_index]

            table = (_MPEG1_LAYER3_BITRATES if version_bits == 3
                     else _MPEG2_LAYER3_BITRATES)
            bitrate_kbps = table[bitrate_index]

            frames = _read_xing_frame_count(window, index, version_bits)
            if frames is not None:
                samples_per_frame = 1152 if version_bits == 3 else 576
                audio.duration_ms = int(
                    frames * samples_per_frame * 1000 / audio.sample_rate)
            elif bitrate_kbps:
                # Constant-bitrate estimate; a VBR file without a Xing header
                # cannot be measured without decoding it.
                audio_bytes = file_size - start - index
                audio.duration_ms = int(audio_bytes * 8 / bitrate_kbps)
    except OSError as error:
        audio.error = str(error)
    return audio


def _find_frame_sync(window: bytes) -> Optional[int]:
    """Index of the first plausible MPEG Layer III frame header."""
    for index in range(len(window) - 4):
        if window[index] != 0xFF or (window[index + 1] & 0xE0) != 0xE0:
            continue
        version_bits = (window[index + 1] >> 3) & 0x03
        layer_bits = (window[index + 1] >> 1) & 0x03
        bitrate_index = (window[index + 2] >> 4) & 0x0F
        rate_index = (window[index + 2] >> 2) & 0x03
        if version_bits == 1 or layer_bits != 1:      # reserved / not Layer III
            continue
        if bitrate_index in (0, 0x0F) or rate_index == 3:
            continue
        return index
    return None


def _read_xing_frame_count(window: bytes, frame_index: int,
                           version_bits: int) -> Optional[int]:
    """Frame count from a Xing/Info header, when the encoder wrote one."""
    # The tag sits at a fixed offset into the first frame, which depends on
    # the MPEG version and whether the stream is mono.
    mono = ((window[frame_index + 3] >> 6) & 0x03) == 3
    if version_bits == 3:
        offset = 17 if mono else 32
    else:
        offset = 9 if mono else 17
    start = frame_index + 4 + offset
    tag = window[start:start + 4]
    if tag not in (b"Xing", b"Info"):
        return None
    flags, = struct.unpack(">I", window[start + 4:start + 8])
    if not flags & 0x01:                              # no frame count present
        return None
    count, = struct.unpack(">I", window[start + 8:start + 12])
    return count or None


def read_audio(path: str) -> Audio:
    if path.lower().endswith(".wav"):
        return _read_wav(path)
    return _read_mp3(path)


# --------------------------------------------------------------------------
# Filesystem detection
# --------------------------------------------------------------------------


def detect_filesystem(path: str) -> Optional[str]:
    """Best-effort filesystem name for the volume `path` sits on.

    Returns None when it cannot be determined, which is the normal answer for
    a folder that is not a mount point.  Never raises.
    """
    try:
        if sys.platform == "win32":
            return _detect_filesystem_windows(path)
        if sys.platform == "darwin":
            return _detect_filesystem_mount(path, _run_mount())
        return _detect_filesystem_proc(path)
    except Exception:                                 # pragma: no cover
        return None


def _run_mount() -> str:
    result = subprocess.run(["/sbin/mount"], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=10)
    return result.stdout.decode("utf-8", "replace")


def _detect_filesystem_mount(path: str, mount_output: str) -> Optional[str]:
    """Parse `mount` output: `/dev/disk4s1 on /Volumes/USB (exfat, local)`."""
    best: Optional[Tuple[int, str]] = None
    real = os.path.realpath(path)
    for line in mount_output.splitlines():
        if " on " not in line or "(" not in line:
            continue
        mount_point = line.split(" on ", 1)[1].rsplit(" (", 1)[0]
        kind = line.rsplit("(", 1)[1].split(",", 1)[0].strip(") ")
        if _is_within(real, mount_point):
            if best is None or len(mount_point) > best[0]:
                best = (len(mount_point), kind)
    return best[1] if best else None


def _detect_filesystem_proc(path: str) -> Optional[str]:
    try:
        with open("/proc/mounts", "r") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    best: Optional[Tuple[int, str]] = None
    real = os.path.realpath(path)
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        mount_point = parts[1].replace("\\040", " ")
        if _is_within(real, mount_point):
            if best is None or len(mount_point) > best[0]:
                best = (len(mount_point), parts[2])
    return best[1] if best else None


def _detect_filesystem_windows(path: str) -> Optional[str]:  # pragma: no cover
    import ctypes

    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if not drive:
        return None
    name = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_ulong()
    max_len = ctypes.c_ulong()
    flags = ctypes.c_ulong()
    fs_name = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(drive + "\\"), name, ctypes.sizeof(name),
        ctypes.byref(serial), ctypes.byref(max_len), ctypes.byref(flags),
        fs_name, ctypes.sizeof(fs_name))
    return fs_name.value if ok else None


def _is_within(path: str, parent: str) -> bool:
    path = os.path.normcase(os.path.normpath(path))
    parent = os.path.normcase(os.path.normpath(parent))
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


# --------------------------------------------------------------------------
# Locating the show folder
# --------------------------------------------------------------------------


def _plural(count: int, noun: str) -> str:
    return "{} {}{}".format(count, noun, "" if count == 1 else "s")


def _entries(path: str) -> List[str]:
    try:
        return sorted(os.listdir(path))
    except OSError as error:
        raise DriveError("Cannot read {}: {}".format(path, error))


def _is_ignorable(name: str) -> bool:
    return name in _IGNORED_NAMES or name.startswith(_APPLEDOUBLE_PREFIX)


def locate_show_folder(root: str) -> Tuple[Optional[str], str, List[Finding]]:
    """Find the `LightShow` folder, returning (folder, drive_root, findings).

    Accepts either the base of the drive or the `LightShow` folder itself, so
    that dragging either one onto the script does the expected thing.
    """
    findings: List[Finding] = []
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise DriveError("{} is not a folder".format(root))

    if os.path.basename(root.rstrip(os.sep)).lower() == SHOW_FOLDER.lower():
        # Pointed straight at the show folder.  Its parent stands in for the
        # base of the drive so the base-level checks still have something to
        # look at.
        return root, os.path.dirname(root.rstrip(os.sep)), findings

    exact = None
    case_variants = []
    for name in _entries(root):
        if not os.path.isdir(os.path.join(root, name)):
            continue
        if name == SHOW_FOLDER:
            exact = os.path.join(root, name)
        elif name.lower() == SHOW_FOLDER.lower():
            case_variants.append(name)

    if exact:
        if case_variants:
            findings.append(Finding(
                WARNING, "SHOW_FOLDER_DUPLICATE",
                "More than one folder is named like {}.".format(SHOW_FOLDER),
                "Found {} alongside the correct {}. The folder name is case "
                "sensitive, so only the exactly-spelled one is read; delete "
                "the others to avoid confusion.".format(
                    ", ".join(sorted(case_variants)), SHOW_FOLDER),
                path=root, readme="USB flash drive requirements"))
        return exact, root, findings

    if case_variants:
        findings.append(Finding(
            ERROR, "SHOW_FOLDER_CASE",
            "The show folder is spelled {}, not {}.".format(
                case_variants[0], SHOW_FOLDER),
            "The folder name is case sensitive. Rename it to exactly "
            "\"{}\". On a case-insensitive filesystem the rename may need "
            "two steps, via a temporary name.".format(SHOW_FOLDER),
            path=os.path.join(root, case_variants[0]),
            readme="USB flash drive requirements"))
        return None, root, findings

    nested = _find_nested_show_folder(root)
    if nested:
        findings.append(Finding(
            ERROR, "SHOW_FOLDER_NOT_AT_BASE",
            "The {} folder is not at the base of the drive.".format(
                SHOW_FOLDER),
            "Found it at {}. The car only looks for a base-level {} folder, "
            "so move it to the top of the drive.".format(
                os.path.relpath(nested, root), SHOW_FOLDER),
            path=nested, readme="USB flash drive requirements"))
        return None, root, findings

    findings.append(Finding(
        ERROR, "SHOW_FOLDER_MISSING",
        "No base-level {} folder.".format(SHOW_FOLDER),
        "Create a folder called \"{}\" at the top level of the drive and put "
        "the .fseq and .mp3/.wav files directly inside it. Without it the "
        "dialog in the car stays titled \"Light Show\" rather than \"Custom "
        "Light Show\".".format(SHOW_FOLDER),
        path=root, readme="USB flash drive requirements"))
    return None, root, findings


def _find_nested_show_folder(root: str, depth: int = 3) -> Optional[str]:
    """Look a few levels down for a folder that was meant to be at the base."""
    frontier = [(root, 0)]
    while frontier:
        current, level = frontier.pop(0)
        if level >= depth:
            continue
        try:
            names = sorted(os.listdir(current))
        except OSError:
            continue
        for name in names:
            path = os.path.join(current, name)
            if not os.path.isdir(path) or _is_ignorable(name):
                continue
            if name.lower() == SHOW_FOLDER.lower():
                return path
            frontier.append((path, level + 1))
    return None


# --------------------------------------------------------------------------
# Drive-level checks
# --------------------------------------------------------------------------


def check_drive_root(root: str) -> List[Finding]:
    findings: List[Finding] = []
    try:
        names = _entries(root)
    except DriveError:
        return findings

    for name in names:
        path = os.path.join(root, name)
        if name.lower() == TESLACAM_FOLDER.lower() and os.path.isdir(path):
            findings.append(Finding(
                ERROR, "TESLACAM_PRESENT",
                "The drive has a base-level {} folder.".format(name),
                "A drive used for Dashcam or Sentry recordings is not read as "
                "a light show drive. Use a separate flash drive, or move the "
                "{} folder off this one.".format(name),
                path=path, readme="USB flash drive requirements"))

    update_like = [n for n in names if _looks_like_update_file(root, n)]
    if update_like:
        findings.append(Finding(
            WARNING, "POSSIBLE_UPDATE_FILES",
            "The drive has base-level files that look like update files.",
            "Found {}. The drive must not carry map or firmware update "
            "files. The README does not name them exactly, so check these by "
            "hand rather than treating this as proof.".format(
                ", ".join(sorted(update_like)[:5])),
            path=root, readme="USB flash drive requirements"))
    return findings


_UPDATE_EXTS = (".tar", ".tar.gz", ".tgz", ".gz", ".bin", ".img", ".iso")
_UPDATE_NAMES = ("teslaupdate", "update", "maps", "mapupdate", "map_update")


def _looks_like_update_file(root: str, name: str) -> bool:
    lowered = name.lower()
    if os.path.isdir(os.path.join(root, name)):
        return lowered in _UPDATE_NAMES
    return lowered.endswith(_UPDATE_EXTS)


def check_filesystem(filesystem: Optional[str], root: str) -> List[Finding]:
    if not filesystem:
        return [Finding(
            INFO, "FILESYSTEM_UNKNOWN",
            "Could not determine the filesystem.",
            "This is expected when checking a folder on a normal disk rather "
            "than a mounted flash drive. Confirm the drive itself is exFAT, "
            "FAT32, MS-DOS FAT, ext3 or ext4 before using it in the car.",
            path=root, readme="USB flash drive requirements")]

    key = filesystem.lower()
    if key in REJECTED_FILESYSTEMS:
        return [Finding(
            ERROR, "FILESYSTEM_UNSUPPORTED",
            "The drive is formatted as {}.".format(REJECTED_FILESYSTEMS[key]),
            "NTFS is not supported. Reformat the drive as exFAT, FAT32, "
            "MS-DOS FAT, ext3 or ext4, which erases it, so copy the shows off "
            "first.", path=root, readme="USB flash drive requirements")]
    if key in SUPPORTED_FILESYSTEMS:
        return [Finding(
            INFO, "FILESYSTEM_OK",
            "The drive is formatted as {}.".format(SUPPORTED_FILESYSTEMS[key]),
            "This is one of the supported formats.",
            path=root, readme="USB flash drive requirements")]
    return [Finding(
        WARNING, "FILESYSTEM_UNRECOGNISED",
        "The drive is formatted as {}, which is not a documented "
        "format.".format(filesystem),
        "Supported formats are exFAT, FAT32, MS-DOS FAT, ext3 and ext4. "
        "NTFS is not supported.",
        path=root, readme="USB flash drive requirements")]


# --------------------------------------------------------------------------
# Show folder checks
# --------------------------------------------------------------------------


def _split_show_folder(show_folder: str) -> Tuple[Dict[str, str],
                                                  Dict[str, List[str]],
                                                  List[str], List[str],
                                                  List[str]]:
    """Sort the show folder into fseqs, audio, subfolders and leftovers."""
    fseqs: Dict[str, str] = {}
    audio: Dict[str, List[str]] = {}
    subfolders: List[str] = []
    sidecars: List[str] = []
    others: List[str] = []

    for name in _entries(show_folder):
        path = os.path.join(show_folder, name)
        if name.startswith(_APPLEDOUBLE_PREFIX):
            sidecars.append(name)
            continue
        if name in _IGNORED_NAMES:
            continue
        if os.path.isdir(path):
            subfolders.append(name)
            continue
        stem, ext = os.path.splitext(name)
        lowered = ext.lower()
        if lowered == FSEQ_EXT:
            fseqs[stem] = path
        elif lowered in AUDIO_EXTS:
            audio.setdefault(stem, []).append(path)
        else:
            others.append(name)
    return fseqs, audio, subfolders, sidecars, others


def check_vehicle_support(shows: List[Show]) -> List[Finding]:
    """What the drive cannot tell you: whether the car can play it.

    Everything else here is checkable from the files. Vehicle support is not,
    and it is the other half of "the car will not play my show", so the
    requirements are stated rather than left to be discovered.
    """
    playable = [s for s in shows if s.playable]
    findings = [Finding(
        INFO, "VEHICLE_SUPPORT",
        "The car must be a supported vehicle running {} or newer.".format(
            BASE_SOFTWARE),
        "Custom shows run on Model S (2021+), Model 3, Model X (2021+), "
        "Model Y and Cybertruck. Playing one is a vehicle capability, so a "
        "vehicle that is not on that list cannot be made to play a show by "
        "changing anything on this drive.",
        readme="Supported Vehicles")]

    if len(playable) > 1:
        findings.append(Finding(
            INFO, "MULTI_SHOW_SOFTWARE",
            "{} shows on one drive needs {} or newer.".format(
                len(playable), MULTI_SHOW_SOFTWARE),
            "Support for more than one custom show on a drive arrived in "
            "{}. On an older vehicle software the extra shows are not "
            "offered; the drive itself is fine.".format(MULTI_SHOW_SOFTWARE),
            readme="USB flash drive requirements"))
    return findings


def check_show_folder(show_folder: str) -> Tuple[List[Show], List[Finding]]:
    fseqs, audio, subfolders, sidecars, others = _split_show_folder(show_folder)
    findings: List[Finding] = []

    if sidecars:
        findings.append(Finding(
            WARNING, "MACOS_SIDECAR_FILES",
            "macOS resource-fork files are sitting next to the shows.",
            "Found {}{}. They are created when copying on a Mac and are not "
            "playable shows. Remove them with `dot_clean /Volumes/YOURDRIVE` "
            "before ejecting.".format(
                ", ".join(sorted(sidecars)[:3]),
                " and others" if len(sidecars) > 3 else ""),
            path=show_folder))

    nested_shows = []
    for name in subfolders:
        path = os.path.join(show_folder, name)
        if _contains_fseq(path):
            nested_shows.append(name)
    if nested_shows:
        findings.append(Finding(
            ERROR, "SHOWS_IN_SUBFOLDER",
            "Shows are in subfolders of {}.".format(SHOW_FOLDER),
            "Found show files under {}. Several shows go side by side in the "
            "{} folder itself, one .fseq and one matching .mp3/.wav per show; "
            "subfolders are not read.".format(
                ", ".join(sorted(nested_shows)[:5]), SHOW_FOLDER),
            path=show_folder, readme="USB flash drive requirements"))

    if others:
        authoring = [n for n in others if n.lower().endswith(_AUTHORING_EXTS)]
        findings.append(Finding(
            INFO, "EXTRA_FILES",
            "{} in the folder {} neither a show nor its audio.".format(
                _plural(len(others), "file"),
                "is" if len(others) == 1 else "are"),
            "Found {}. The car ignores them{}.".format(
                ", ".join(sorted(others)[:5]),
                "; xLights project files are normally kept with the show"
                if authoring else ""),
            path=show_folder))

    if not fseqs:
        findings.append(Finding(
            ERROR, "NO_SHOWS",
            "No .fseq file in {}.".format(SHOW_FOLDER),
            "Export at least one show from xLights into this folder, together "
            "with the .mp3 or .wav it was sequenced against.",
            path=show_folder, readme="USB flash drive requirements"))

    shows = [_build_show(stem, path, audio) for stem, path in sorted(
        fseqs.items(), key=lambda item: item[0].lower())]

    findings.extend(_check_orphan_audio(fseqs, audio))
    findings.extend(_check_case_collisions(fseqs))
    return shows, findings


def _contains_fseq(path: str, depth: int = 3) -> bool:
    for current, dirs, files in os.walk(path):
        if any(f.lower().endswith(FSEQ_EXT) and
               not f.startswith(_APPLEDOUBLE_PREFIX) for f in files):
            return True
        if current[len(path):].count(os.sep) >= depth:
            dirs[:] = []
    return False


def _build_show(stem: str, fseq_path: str,
                audio: Dict[str, List[str]]) -> Show:
    show = Show(name=stem, fseq_path=fseq_path)
    _validate_fseq(show)
    _attach_audio(show, stem, audio)
    return show


def _validate_fseq(show: Show) -> None:
    try:
        with open(show.fseq_path, "rb") as handle:
            results = validator.validate(handle)
    except validator.ValidationError as error:
        show.findings.append(Finding(
            ERROR, "FSEQ_INVALID",
            "{} is not a show the car can play.".format(
                os.path.basename(show.fseq_path)),
            "{}. Re-export it from xLights as FSEQ v2.0 Uncompressed.".format(
                str(error).rstrip(".")),
            path=show.fseq_path, readme="Light Show Sequence Validator Script"))
        return
    except (OSError, struct.error) as error:
        show.findings.append(Finding(
            ERROR, "FSEQ_UNREADABLE",
            "{} could not be read.".format(os.path.basename(show.fseq_path)),
            str(error), path=show.fseq_path))
        return
    show.frame_count = results.frame_count
    show.step_time_ms = results.step_time
    show.duration_ms = int(results.duration_s * 1000)


def _attach_audio(show: Show, stem: str, audio: Dict[str, List[str]]) -> None:
    paths = audio.get(stem)
    if not paths:
        # The pairing is by exact filename, so a case-only difference is a
        # separate, more helpful message than "no audio at all".
        near = [key for key in audio if key.lower() == stem.lower()]
        if near:
            show.findings.append(Finding(
                ERROR, "AUDIO_NAME_MISMATCH",
                "{}{} is paired with audio named {}.".format(
                    stem, FSEQ_EXT, near[0]),
                "The .fseq filename must match the .mp3/.wav filename. Rename "
                "one of them so the two agree, including case.",
                path=show.fseq_path, readme="USB flash drive requirements"))
        else:
            show.findings.append(Finding(
                ERROR, "AUDIO_MISSING",
                "{}{} has no matching .mp3 or .wav.".format(stem, FSEQ_EXT),
                "Copy the audio the show was sequenced against into the same "
                "folder and name it {}.wav or {}.mp3. A show without its "
                "audio is not offered in the car.".format(stem, stem),
                path=show.fseq_path, readme="USB flash drive requirements"))
        return

    if len(paths) > 1:
        show.findings.append(Finding(
            WARNING, "AUDIO_AMBIGUOUS",
            "{} has both a .wav and an .mp3.".format(stem),
            "Found {}. Which one the car picks is not documented; keep one. "
            ".wav is the recommended format.".format(
                ", ".join(sorted(os.path.basename(p) for p in paths))),
            path=os.path.dirname(paths[0]),
            readme="Audio file requirements"))

    # Prefer the .wav when both are present, matching the README's
    # recommendation, so the rest of the report describes that file.
    chosen = sorted(paths, key=lambda p: (not p.lower().endswith(".wav"), p))[0]
    show.audio = read_audio(chosen)
    _check_audio(show)


def _check_audio(show: Show) -> None:
    audio = show.audio
    if audio is None:
        return
    name = os.path.basename(audio.path)
    if audio.error:
        show.findings.append(Finding(
            WARNING, "AUDIO_UNREADABLE",
            "Could not read the header of {}.".format(name),
            "{}. The car may still play it; this check could not confirm the "
            "sample rate.".format(audio.error),
            path=audio.path, readme="Audio file requirements"))
        return

    if audio.sample_rate and audio.sample_rate != REQUIRED_SAMPLE_RATE:
        show.findings.append(Finding(
            WARNING, "AUDIO_SAMPLE_RATE",
            "{} is {} Hz, not {} Hz.".format(
                name, audio.sample_rate, REQUIRED_SAMPLE_RATE),
            "Audio must be encoded at 44.1 kHz; the less common 48 kHz will "
            "not stay in sync with the lights. Re-encode it at 44.1 kHz and "
            "re-export the show against that file.",
            path=audio.path, readme="Audio file requirements"))

    if audio.duration_ms and show.duration_ms:
        drift = audio.duration_ms - show.duration_ms
        if abs(drift) > 1000:
            longer, shorter = (("audio", "sequence") if drift > 0
                               else ("sequence", "audio"))
            show.findings.append(Finding(
                INFO, "LENGTH_MISMATCH",
                "The {} runs {} longer than the {}.".format(
                    longer, _format_duration(abs(drift)), shorter),
                "Sequence {}, audio {}{}. The two are not required to "
                "match, but a large gap usually means the show was sequenced "
                "against a different copy of the track, and a trimmed intro "
                "on one of them is the usual reason the music ends up running "
                "ahead of the lights.".format(
                    _format_duration(show.duration_ms),
                    _format_duration(audio.duration_ms),
                    " (estimated)" if audio.estimated else ""),
                path=audio.path))


def _check_orphan_audio(fseqs: Dict[str, str],
                        audio: Dict[str, List[str]]) -> List[Finding]:
    orphans = sorted(os.path.basename(path)
                     for stem, paths in audio.items() if stem not in fseqs
                     for path in paths)
    if not orphans:
        return []
    return [Finding(
        WARNING, "AUDIO_WITHOUT_SHOW",
        "{} has no matching .fseq.".format(_plural(len(orphans), "audio file")),
        "Found {}. Audio on its own is not a show; export the sequence next "
        "to it or remove the file.".format(", ".join(orphans[:5])),
        readme="USB flash drive requirements")]


def _check_case_collisions(fseqs: Dict[str, str]) -> List[Finding]:
    seen: Dict[str, List[str]] = {}
    for stem in fseqs:
        seen.setdefault(stem.lower(), []).append(stem)
    clashes = [names for names in seen.values() if len(names) > 1]
    if not clashes:
        return []
    return [Finding(
        WARNING, "NAME_COLLISION",
        "Show names differ only by case.",
        "Found {}. exFAT and FAT are case insensitive, so copying these onto "
        "a drive can silently overwrite one with the other, and the picker "
        "would list two entries with the same label.".format(
            "; ".join(", ".join(sorted(names)) for names in clashes)))]


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def check_drive(path: str) -> DriveReport:
    """Check a drive, or a folder laid out like one, and report on it."""
    show_folder, root, findings = locate_show_folder(path)
    filesystem = detect_filesystem(root)

    report = DriveReport(root=root, show_folder=show_folder,
                         filesystem=filesystem)
    report.findings.extend(findings)
    report.findings.extend(check_filesystem(filesystem, root))
    report.findings.extend(check_drive_root(root))

    if show_folder:
        shows, folder_findings = check_show_folder(show_folder)
        report.shows = shows
        report.findings.extend(folder_findings)
        report.findings.extend(check_vehicle_support(shows))

    report.findings.sort(key=lambda f: _SEVERITY_ORDER[f.severity])
    return report


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _format_duration(ms: Optional[int]) -> str:
    """Render a length the way the car's picker does: `3 min 30 sec`."""
    if ms is None:
        return "-"
    total = int(round(ms / 1000.0))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return "{} hr {} min {} sec".format(hours, minutes, seconds)
    if minutes:
        return "{} min {} sec".format(minutes, seconds)
    return "{} sec".format(seconds)


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


def _render_finding(finding: Finding, subject: str = "") -> List[str]:
    out = ["  [{}] {}{}".format(
        _MARKERS[finding.severity], finding.code,
        "  " + subject if subject else "")]
    out.append(_wrap(finding.summary, 76, "    "))
    out.append(_wrap(finding.detail, 76, "      "))
    if finding.readme:
        out.append("      README: {}".format(finding.readme))
    return out


def render_report(report: DriveReport, verbose: bool) -> str:
    out: List[str] = []
    out.append("Drive:       {}{}".format(
        report.root,
        "  ({})".format(report.filesystem) if report.filesystem else ""))
    out.append("Show folder: {}".format(report.show_folder or "not found"))
    out.append("")

    playable = report.playable_shows
    if playable:
        out.append("The car will list {} custom show{}:".format(
            len(playable), "" if len(playable) == 1 else "s"))
        out.append("")
        width = max(len(show.name) for show in playable)
        for index, show in enumerate(playable, start=1):
            audio_name = (os.path.basename(show.audio.path)
                          if show.audio else "-")
            out.append("  {:>2}. {}   {:>14}   {}".format(
                index, show.name.ljust(width),
                _format_duration(show.duration_ms), audio_name))
        out.append("")
        out.append(_wrap(
            "Listed in case-insensitive filename order. The order the car "
            "uses is not documented; the screenshots in issue #48 are "
            "alphabetical, but treat the order above as a guess.", 76, "  "))
        out.append("")

    rejected = [s for s in report.shows if not s.playable]
    if rejected:
        out.append("{} show{} will not appear:".format(
            len(rejected), "" if len(rejected) == 1 else "s"))
        for show in rejected:
            out.append("")
            for finding in show.findings:
                if finding.severity == INFO and not verbose:
                    continue
                out.extend(_render_finding(finding, show.name))
        out.append("")

    show_notes = [(s, f) for s in playable for f in s.findings
                  if verbose or f.severity != INFO]
    if show_notes:
        out.append("Notes on the shows that will play:")
        for show, finding in show_notes:
            out.append("")
            out.extend(_render_finding(finding, show.name))
        out.append("")

    drive_findings = [f for f in report.findings
                      if verbose or f.severity != INFO]
    if drive_findings:
        out.append("The drive itself:")
        for finding in drive_findings:
            out.append("")
            out.extend(_render_finding(finding))
        out.append("")

    counts = report.counts()
    hidden = sum(1 for f in report.all_findings() if f.severity == INFO)
    out.append("{} error(s), {} warning(s), {} note(s).".format(
        counts[ERROR], counts[WARNING], counts[INFO]))
    if hidden and not verbose:
        out.append("Re-run with -v to see the notes.")
    if not counts[ERROR] and not counts[WARNING]:
        out.append("This drive is ready for the car.")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a USB flash drive holding one or more custom light "
                    "shows, and report which shows the car will offer.")
    parser.add_argument("path", nargs="?",
                        help="the drive, or the LightShow folder itself")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON instead of text")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="include the informational notes")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero on warnings as well as errors")
    args = parser.parse_args(argv)

    path = args.path
    if not path:
        path = input("Please enter the path by dragging and dropping the USB "
                     "drive or the LightShow folder: ")
        print("")
        path = path.strip('"').strip("'").strip(" ")

    try:
        report = check_drive(path)
    except (DriveError, OSError) as error:
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
