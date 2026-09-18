#!/usr/bin/env python3
"""Check the documentation's links, without touching the network.

README.md is the main deliverable of this repository, and it is held together
by links: cross-references between its own sections, images, the tools, the
example archives, and a list of community sites that
https://github.com/teslamotors/light-show/issues/62 asked to be added to.
Every one of those can rot silently -- a heading gets renamed, a file moves,
someone appends a tracking parameter to a URL, or the community list quietly
becomes a ranking.

This checks what can be checked from the repository alone:

    - every "](#anchor)" resolves to a heading or <a name> in the same file
    - every repo-relative link and image exists on disk
    - external links are https and carry no tracking parameters
    - the community show list stays alphabetical, unique and well formed

It deliberately does not fetch anything. Whether a third-party site is up is
not this repository's business to assert on every pull request, and a check
that depends on someone else's uptime fails for reasons nobody here can fix.

Usage:
    python3 tools/docs_check.py
    python3 tools/docs_check.py --json
    python3 tools/docs_check.py --strict     # warnings fail too

Requires Python 3.7+ and only the standard library, matching validator.py.
"""

import argparse
import dataclasses
import json
import os
import re
import sys
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ERROR = "error"
WARNING = "warning"
INFO = "info"

_SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}

# The community list is delimited so it can be checked without guessing at
# where a prose section starts and ends.
COMMUNITY_START = "<!-- community-shows:"
COMMUNITY_END = "<!-- /community-shows -->"
COMMUNITY_ENTRY = re.compile(r'^- \[([^\]]+)\]\((https://[^)\s]+)\)$')

# Parameters that turn a plain link into a tracked one.
TRACKING_PARAMETERS = ("utm_source", "utm_medium", "utm_campaign", "utm_term",
                       "utm_content", "fbclid", "gclid", "mc_cid", "mc_eid",
                       "ref_src", "igshid")

# ?raw=true is how GitHub serves a file from a blob URL; it is not tracking.
ALLOWED_PARAMETERS = ("raw",)

# A documented command, e.g. "python3 tools/usb_check.py" or
# "python3 validator.py".  Commands live in code fences rather than links, so
# nothing else here notices when one names a script that has been renamed.
_COMMAND = re.compile(r'python3?\s+((?:tools/)?[A-Za-z0-9_]+\.py)')

_MARKDOWN_LINK = re.compile(r'\[[^\]]*\]\(([^)]+)\)')
_HTML_REFERENCE = re.compile(r'(?:src|href)="([^"]+)"')
_HEADING = re.compile(r'^#+\s+(.*)$')
_ANCHOR_NAME = re.compile(r'<a\s+name="([^"]+)"')
_INLINE_HTML = re.compile(r'<[^>]+>')


@dataclasses.dataclass
class Finding:
    severity: str
    code: str
    summary: str
    detail: str
    file: str
    line: Optional[int] = None

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def heading_slug(heading: str) -> str:
    """GitHub's anchor for a heading: lowercase, punctuation dropped."""
    slug = _INLINE_HTML.sub("", heading).strip().lower()
    slug = re.sub(r'[^\w\s-]', "", slug)
    return re.sub(r'\s+', "-", slug.strip())


def markdown_files(root: str = REPO_ROOT) -> List[str]:
    """Every tracked .md file, as paths relative to the repository root."""
    out: List[str] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in sorted(files):
            if name.lower().endswith(".md"):
                out.append(os.path.relpath(os.path.join(current, name), root))
    return sorted(out)


def references(text: str) -> List[Tuple[int, str]]:
    """Every link target in the file, with the line it appears on."""
    found: List[Tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _MARKDOWN_LINK.finditer(line):
            found.append((number, match.group(1).strip()))
        for match in _HTML_REFERENCE.finditer(line):
            found.append((number, match.group(1).strip()))
    return found


def anchors(text: str) -> set:
    """Anchor names this file defines, both headings and explicit <a name>."""
    defined = set(_ANCHOR_NAME.findall(text))
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            defined.add(heading_slug(match.group(1)))
    return defined


def resolve(reference: str, containing_file: str) -> str:
    """Repository-relative path a link points at."""
    path = reference.split("#")[0].split("?")[0]
    if path.startswith("/"):
        return path.lstrip("/")
    return os.path.normpath(
        os.path.join(os.path.dirname(containing_file), path))


def check_file(relative_path: str, root: str = REPO_ROOT) -> List[Finding]:
    with open(os.path.join(root, relative_path), encoding="utf-8") as handle:
        text = handle.read()

    findings: List[Finding] = []
    defined = anchors(text)

    for line, reference in references(text):
        if reference.startswith("#"):
            name = reference[1:]
            if name not in defined:
                findings.append(Finding(
                    ERROR, "anchor-not-found",
                    "No anchor named \"{}\" in this file.".format(name),
                    "The link points at a section that does not exist. "
                    "Headings become anchors with their punctuation removed "
                    "and spaces turned into hyphens; an explicit "
                    "<a name=\"...\"></a> also works.",
                    file=relative_path, line=line))
            continue

        if reference.startswith(("http://", "https://")):
            findings.extend(_check_external(reference, relative_path, line))
            continue

        if reference.startswith("mailto:"):
            continue

        target = resolve(reference, relative_path)
        if not target:
            continue
        if not os.path.exists(os.path.join(root, target)):
            findings.append(Finding(
                ERROR, "path-not-found",
                "{} does not exist.".format(target),
                "The documentation links to a file that is not in the "
                "repository. Renaming or moving a file means updating the "
                "places that point at it.",
                file=relative_path, line=line))
    return findings


def _check_external(url: str, relative_path: str, line: int) -> List[Finding]:
    findings: List[Finding] = []
    if url.startswith("http://"):
        findings.append(Finding(
            WARNING, "insecure-link",
            "{} is not https.".format(url),
            "Readers follow these links from the repository's front page. "
            "Use the https:// form.",
            file=relative_path, line=line))

    query = url.split("?", 1)[1] if "?" in url else ""
    for parameter in query.split("&"):
        name = parameter.split("=", 1)[0]
        if not name or name in ALLOWED_PARAMETERS:
            continue
        if name.lower() in TRACKING_PARAMETERS:
            findings.append(Finding(
                WARNING, "tracking-parameter",
                "{} carries a {} parameter.".format(url, name),
                "Links in the documentation should not attribute readers to "
                "a campaign. Link to the plain URL.",
                file=relative_path, line=line))
    return findings


def _marker_lines(text: str) -> Tuple[Optional[int], Optional[int]]:
    """Line numbers of the list markers, or None when the file has no list.

    A marker only counts when it opens its own line. Documentation that
    mentions the markers in prose -- CLAUDE.md does -- is not a list.
    """
    start = end = None
    for number, line in enumerate(text.splitlines(), start=1):
        if start is None and line.startswith(COMMUNITY_START):
            start = number
        elif start is not None and line.startswith(COMMUNITY_END):
            end = number
            break
    return start, end


def community_entries(text: str) -> List[Tuple[int, str, str]]:
    """The (line, name, url) entries of the community show list."""
    start, end = _marker_lines(text)
    if start is None:
        return []
    lines = text.splitlines()
    last = (end - 1) if end else len(lines)
    entries: List[Tuple[int, str, str]] = []
    for number in range(start + 1, last + 1):
        line = lines[number - 1].rstrip()
        if not line.strip():
            continue
        match = COMMUNITY_ENTRY.match(line)
        entries.append((number, match.group(1), match.group(2))
                       if match else (number, "", line))
    return entries


def check_commands(relative_path: str, root: str = REPO_ROOT) -> List[Finding]:
    """Scripts named in documented commands have to exist."""
    with open(os.path.join(root, relative_path), encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    findings: List[Finding] = []
    seen = set()
    for number, line in enumerate(lines, start=1):
        for script in _COMMAND.findall(line):
            if script in seen:
                continue
            seen.add(script)
            if not os.path.isfile(os.path.join(root, script)):
                findings.append(Finding(
                    ERROR, "command-not-found",
                    "{} is not in the repository.".format(script),
                    "A command in the documentation runs this script. "
                    "Renaming a tool means updating the places that tell "
                    "people to run it.",
                    file=relative_path, line=number))
    return findings


def check_community_list(relative_path: str,
                         root: str = REPO_ROOT) -> List[Finding]:
    """The list of community sites, which grows by request.

    Issue #62 is one of those requests. The list is only fair if it stays
    mechanically ordered, so the checks here are about form, never about
    which site deserves to be on it -- that is a maintainer's call.
    """
    with open(os.path.join(root, relative_path), encoding="utf-8") as handle:
        text = handle.read()
    start, end = _marker_lines(text)
    if start is None:
        return []
    if end is None:
        return [Finding(
            ERROR, "community-list-unterminated",
            "The community list has no closing marker.",
            "Add {} after the last entry.".format(COMMUNITY_END),
            file=relative_path, line=start)]

    findings: List[Finding] = []
    entries = community_entries(text)
    if not entries:
        return [Finding(
            WARNING, "community-list-empty",
            "The community list has no entries.",
            "The markers are present but nothing is between them.",
            file=relative_path)]

    names: List[str] = []
    seen_hosts: Dict[str, str] = {}
    for line, name, url in entries:
        if not name:
            findings.append(Finding(
                ERROR, "community-list-format",
                "Entry is not a plain markdown link.",
                "Every entry is one line, \"- [Name](https://url)\". Found: "
                "{}".format(url),
                file=relative_path, line=line))
            continue
        names.append(name)
        host = url.split("//", 1)[1].split("/", 1)[0].lower()
        host = host[4:] if host.startswith("www.") else host
        if host in seen_hosts:
            findings.append(Finding(
                ERROR, "community-list-duplicate",
                "{} is listed twice.".format(host),
                "Already listed as {}.".format(seen_hosts[host]),
                file=relative_path, line=line))
        else:
            seen_hosts[host] = name

    ordered = sorted(names, key=str.lower)
    if names != ordered:
        findings.append(Finding(
            ERROR, "community-list-unsorted",
            "The community list is not in alphabetical order.",
            "The order is the only thing keeping the list from being read as "
            "a ranking. Expected: {}.".format(", ".join(ordered)),
            file=relative_path))
    return findings


def check_unreferenced_images(root: str = REPO_ROOT) -> List[Finding]:
    """Images carried by the repository that nothing links to."""
    images_dir = os.path.join(root, "images")
    if not os.path.isdir(images_dir):
        return []

    used = set()
    for relative_path in markdown_files(root):
        with open(os.path.join(root, relative_path),
                  encoding="utf-8") as handle:
            text = handle.read()
        for _, reference in references(text):
            if reference.startswith(("http", "#", "mailto:")):
                continue
            used.add(resolve(reference, relative_path))

    orphans = sorted(
        name for name in os.listdir(images_dir)
        if os.path.join("images", name) not in used
        and not name.startswith("."))
    if not orphans:
        return []
    return [Finding(
        INFO, "unreferenced-image",
        "{} image(s) in images/ are not referenced by any document.".format(
            len(orphans)),
        "They may be kept on purpose, linked from elsewhere, or left over. "
        "Found: {}.".format(", ".join(orphans)),
        file="images/")]


def check_all(root: str = REPO_ROOT) -> List[Finding]:
    findings: List[Finding] = []
    for relative_path in markdown_files(root):
        findings.extend(check_file(relative_path, root))
        findings.extend(check_commands(relative_path, root))
        findings.extend(check_community_list(relative_path, root))
    findings.extend(check_unreferenced_images(root))
    findings.sort(key=lambda f: (_SEVERITY_ORDER[f.severity], f.file,
                                 f.line or 0))
    return findings


def render(findings: Sequence[Finding], checked: Sequence[str],
           verbose: bool) -> str:
    out: List[str] = ["Checked {} document(s): {}".format(
        len(checked), ", ".join(checked)), ""]
    shown = [f for f in findings if verbose or f.severity != INFO]
    for finding in shown:
        location = finding.file
        if finding.line:
            location += ":{}".format(finding.line)
        out.append("[{:7s}] {}  {}".format(
            finding.severity.upper(), location, finding.code))
        out.append("    " + finding.summary)
        out.append("      " + finding.detail)
        out.append("")
    counts = {level: sum(1 for f in findings if f.severity == level)
              for level in (ERROR, WARNING, INFO)}
    out.append("{} error(s), {} warning(s), {} note(s).".format(
        counts[ERROR], counts[WARNING], counts[INFO]))
    if counts[INFO] and not verbose:
        out.append("Re-run with -v to see the notes.")
    if not counts[ERROR] and not counts[WARNING]:
        out.append("Documentation links are consistent.")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the documentation's internal links, file "
                    "references and the community show list.")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON instead of text")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="include the informational notes")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero on warnings as well as errors")
    args = parser.parse_args(argv)

    findings = check_all()
    checked = markdown_files()

    if args.json:
        print(json.dumps({
            "documents": checked,
            "findings": [f.as_dict() for f in findings],
        }, indent=2))
    else:
        print(render(findings, checked, args.verbose))

    if any(f.severity == ERROR for f in findings):
        return 1
    if args.strict and any(f.severity == WARNING for f in findings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
