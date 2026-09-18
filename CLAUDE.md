# CLAUDE.md

Guidance for Claude Code (claude.ai/code) and other agents working in this repository.

## What this repository is

`teslamotors/light-show` distributes the assets Tesla owners use to author custom
vehicle light shows: an xLights show folder describing the car's lights and
closures, example sequences, and a validator for the `.fseq` files xLights
exports.

There is no application to build here. The deliverables are **data files**, and
almost every change is a change to something a car will eventually play.

## Layout

| Path | What it is |
| --- | --- |
| `README.md` | The product documentation. It is the main deliverable for most users; keep it in sync with any behaviour change. |
| `validator.py` | Standalone `.fseq` checker. Pure standard library, Python 3.7+, run by double-click on Windows. |
| `validator-windows.exe`, `validator-macos.zip` | Packaged builds of `validator.py`, produced by `.github/workflows/build.yml`. |
| `xlights/tesla_xlights_show_folder.zip` | **The xLights show folder.** The file that matters is `tesla_xlights_show_folder/xlights_rgbeffects.xml` inside it. |
| `xlights/tesla_xlights_cross_vehicle_folder.zip` | Separate show folder for mapping one show onto five vehicles. |
| `xlights/layer_groups.json` | Declarative spec for the positional "layer" model groups. Source of truth for what the zip contains. |
| `xlights/channel_map.json` | Recorded channel assignment of every model. A regression lock, see below. |
| `tools/xlights_layers.py` | Applies and verifies the two files above against the zip. |
| `tools/vehicle_preview.py` | Reports where a `.fseq` will behave differently on a given vehicle than it does in the xLights preview. |
| `tools/usb_check.py` | Reads a finished USB drive and reports which shows the car will list, and why any other was left out. |
| `tests/` | `unittest` suite, standard library only. |
| `examples/` | Example shows, distributed as zips. |

## The one rule: never move a channel

Shows are exported as `.fseq` files that are just arrays of channel values. A
`.fseq` a user exported last year must keep playing correctly on the same car
this year. That means the mapping from **model name → `StartChannel`** in
`xlights_rgbeffects.xml` is a public API.

`xlights/channel_map.json` records that mapping. `tools/xlights_layers.py verify`
fails if it ever drifts, and CI runs it on every pull request. If you are asked
to make a change that genuinely needs to remap channels, that is a deliberate
breaking change: say so explicitly, and regenerate the file with
`python3 tools/xlights_layers.py fingerprint` as part of the same commit.

Safe to add: model groups and views. They are sequencer-side only — they
reference existing models by name and own no channels.

## Working on the show folder

The show folder is a binary zip, so a diff shows nothing useful. Do not hand-edit
the zip. The workflow is:

```bash
# edit xlights/layer_groups.json, then
python3 tools/xlights_layers.py apply     # write it into the zip
python3 tools/xlights_layers.py verify    # check every invariant
python3 -m unittest discover -s tests     # run the suite
```

`apply` is idempotent and rewrites only the one XML entry, copying every other
entry's compressed stream verbatim — a round trip through `zipfile.writestr()`
re-deflates the 15 MB `.obj` meshes with Python's weaker compressor and adds
about 1 MB to the archive for no reason. CI asserts `apply` leaves the committed
zip byte-identical, which is what keeps the spec and the zip from drifting apart.

### Things that are easy to get wrong

- **Cybertruck preview models duplicate Model S channels.** `CT Left Mirror`,
  `Powered Frunk` and friends exist so the 3D layout can render a second
  vehicle; they deliberately reuse another model's `StartChannel`. Putting one in
  a timeline group drives a single channel from two rows. They are declared in
  `layer_groups.json` under `preview_models` — note that `Powered Frunk` does
  *not* follow the `CT ` naming convention, so a prefix check alone is wrong.
- **Rows within a view should not overlap.** Two rows that resolve to the same
  model race each other at render time.
- **Model groups may contain other model groups.** Prefer composing existing
  groups over restating their members, and keep the graph acyclic.
- **`Backup/` entries inside the zip are historical snapshots.** Leave them alone;
  xLights writes a fresh one each time it opens the folder.

## Vehicle behaviour differs from the preview

The show folder ships **one** superset vehicle model, so the xLights sequencer
always animates every channel as its own instantly-switching light. Real cars do
not all work that way, and the difference is invisible while authoring — it is
the root of most "my show looks wrong on the car" reports, including
[#42](https://github.com/teslamotors/light-show/issues/42).

`tools/vehicle_preview.py` reports these differences for a finished `.fseq`:

```bash
python3 tools/vehicle_preview.py path/to/lightshow.fseq
python3 tools/vehicle_preview.py path/to/lightshow.fseq --vehicle model3 -v
```

The rules it encodes, all of them taken from `README.md`:

- **Channels are OR'd on some vehicles.** On Model 3/Y, Channels 4, 5 and 6
  drive one output per side, and all four aux park / side marker channels drive
  a single output. A group only flashes if *every* channel in it shares an
  off-time; otherwise it sits solid.
- **Ramping is per-vehicle.** Front turn and signature lights are boolean on
  Model S but ramp on Model 3/Y, so a two-frame effect that reads as a crisp
  flash in the preview barely lights the lamp on a Model 3.
- **Channel 4 is the ramp leader.** The ramp duration for Channels 4-6 always
  comes from the Channel 4 effect, never from Channel 5 or 6.
- **Brightness is an enum, not a level.** Outside Cybertruck's full-brightness
  channels, the byte selects a documented effect: 0/10/20/30/70/80/90/100 for
  lights, 0/25/50/75/100 for closures. Anything above 50% is "on". The exact
  percentages are bound to hotkeys in `xlights_keybindings.xml`.
- **Not every light exists on every build.** Front fog and aux park are absent
  from Model 3 Standard Range +, side markers are a North America fitment, and
  rear fog is the opposite.

When code encodes one of these, cite the `README.md` section it came from in a
comment. If the code and the README disagree, that is a bug worth raising rather
than silently picking one. Where the README is simply silent — it describes the
aux park pairing for Model S and Model 3/Y but not Model X — say so in a note
instead of presenting the guess as fact.

## The drive is an interface too

The car finds custom shows by convention, not by a manifest: every `.fseq` at
the top level of a base-level `LightShow` folder is one entry in the picker,
paired with the `.mp3`/`.wav` of the same name. Vehicle software 2023.44.25
made that list hold more than one show, which is
[#48](https://github.com/teslamotors/light-show/issues/48). Nothing in the car
explains a drive it rejected — the show is simply absent, or the dialog title
stays "Light Show" instead of "Custom Light Show" — so every rule the README
states about the drive is a rule a tool has to state back to the owner.

`tools/usb_check.py` does that:

```bash
python3 tools/usb_check.py /Volumes/LIGHTSHOW      # or the LightShow folder
python3 tools/usb_check.py /Volumes/LIGHTSHOW --json --strict
```

Things worth knowing before changing it:

- **It reuses `validator.validate()`** rather than restating the `.fseq`
  limits. A limit should only ever change in one place. This is also why it
  imports the module instead of running the script, which would block on
  `input()`.
- **Severity is a promise about the car.** `ERROR` means the show or the drive
  will not play, and drops the show out of the picker preview; `WARNING` means
  it plays but something is wrong, like 48 kHz audio; `INFO` is a note. Do not
  promote a finding to `ERROR` unless the README says the car rejects it.
- **The audio parsers read headers, never audio.** A file whose header cannot
  be parsed is reported as unread, never as a bad drive; the car is the
  authority on what it can play, and a false rejection is worse than silence.
- **Filesystem detection is best effort** and platform-specific
  (`mount`, `/proc/mounts`, `GetVolumeInformationW`). It must never raise, and
  "unknown" is a perfectly good answer for a folder on a normal disk.
- **Say when the README is silent.** The picker's sort order and the exact
  naming of a map update file are not documented, so those findings say they
  are a guess. Do not quietly harden a guess into a rule.

## Conventions

- **Python**: standard library only, in both `validator.py` and `tools/`. Users
  run these by double-clicking a file; a dependency they have to install is a
  support burden. Target 3.7+.
- **`validator.py` blocks on `input()`** so that double-clicking it on Windows
  leaves the window open. Never call it from a script or a CI step; import
  `validate()` instead.
- **Group naming**: `GRP ` for left/right pairs of one light type, `All ` for the
  multishow-import groups, `LR ` for light-bar halves, `LAYER ` for the
  positional layers. Match the surrounding convention rather than inventing one.
- **Tests**: every check should have a test proving it fails when the thing it
  checks is broken. A check that cannot fail is not a check.
- **README**: user-facing and screenshot-heavy. Images live in `images/` and are
  referenced as `/images/name.png?raw=true`.

## Not in scope unless asked

- Regenerating `validator-windows.exe` / `validator-macos.zip` (maintainers do
  this via the `Build Executable` workflow).
- `xlights/tesla_xlights_cross_vehicle_folder.zip`, which carries five copies of
  the vehicle models and is maintained separately from the main show folder.
