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

### The community list is a list, not a recommendation

`README.md`, "Download a Show" links sites the community runs, and people ask
to be added — [#62](https://github.com/teslamotors/light-show/issues/62) is one
such request. Two rules keep that answerable:

- **Whether a site belongs on the list is a maintainer's decision.** Nothing in
  this repository can verify that a site is free, ad-free, non-commercial or
  well behaved, and those things change without notice. Do not repeat a site's
  own claims in the README, and do not rank the entries. Add the name and the
  URL, alphabetically, and let the reader judge.
- **The shape of the list is mechanical, so it is checked.** The entries sit
  between `<!-- community-shows: -->` markers, and `tools/docs_check.py` fails
  a pull request that makes the list unsorted, duplicated, or something other
  than one `- [Name](https://url)` per line. Alphabetical order is the only
  thing keeping the list from reading as a ranking.

`tools/docs_check.py` covers the rest of the documentation too — anchors that
resolve, files that exist, https links without tracking parameters. It
**deliberately never fetches a URL**. A third-party site being down is not a
reason a pull request here should fail, and nobody working in this repository
could fix it.

### Which car, and which build of it

[#52](https://github.com/teslamotors/light-show/issues/52) asks for a 2020
Model X to be supported. It is not: `README.md`, "Supported Vehicles" lists
Model S and Model X from 2021 onwards. Playing a custom show is a vehicle
capability, so no change to a show file, a drive or this repository can grant
it, and a request to add a vehicle is a decision for the maintainers rather
than something to implement. Say that plainly instead of looking for a
workaround.

What this repository can keep honest is the boundary itself:

- **The supported list has one home.** `test_tool_profiles_match_the_readme_list`
  asserts the labels in `VEHICLES` are exactly the vehicle bullets under
  "Supported Vehicles". Adding a vehicle means editing the README and adding a
  profile in the same change, and the test fails until both are done.
- **Model year is part of the label.** "Model S (2021+)" and
  "Model X (2021+)" carry the boundary a reader needs; do not shorten them.

Below the model is the build. The README describes cars that are wired
differently within one model — "Model 3 built before October 2020", "Model 3
Standard Range +", North America fitments — and an owner calls all of them a
Model 3. `BuildVariant` states only the differences and
`analyze_variants()` reports **only what the base report does not already
say**, so an owner of an older car sees the handful of things that are true
for them rather than a second copy of the whole report.

- **Variants do not inherit.** `_MODEL_Y` is built with
  `dataclasses.replace(_MODEL_3, ...)`, so a variant added to Model 3 reaches
  Model Y unless it is cleared. The README documents the tail light rule for
  Model 3 only, and a test holds Model Y to an empty variant list.
- **`SLAVED` is not `ABSENT`.** On a pre-October-2020 Model 3 the license
  plate lamp is fitted and lit — it just follows the tail lights, so its own
  channel does nothing. Reporting it as "not fitted" would contradict the
  README, which says the lamp activates with `(Left tail || Right tail)`.
- **A variant cites the README section it comes from**, and a test asserts
  that section still exists in the file.

### The interior is a different kind of channel

The cabin lights are the answer to
[#49](https://github.com/teslamotors/light-show/issues/49), which was asked in
2022 and answered "no" because they did not exist yet. They do now:
`README.md`, "Interior RGB Lights" gives full RGB control of the Center Front
Display plus five accent segments, and `tools/vehicle_preview.py` reports what
a show does with them.

What makes them different from every other channel in the file:

- **Three channels are one colour.** Channels 176-193 are six segments of
  red/green/blue, starting at 176. The `StartChannel` of each one is recorded
  in `xlights/channel_map.json`, and a test asserts the two agree — that file
  is the source of truth, not the constant in the tool.
- **The byte is not the brightness enum.** Everywhere else a value decodes
  through `RAMP_CODES`/`CLOSURE_CODES`; here every value of every component is
  meaningful colour. 178 is "Turn on; 500 ms" on a light channel and simply a
  red level on an interior one. They carry the `RGB` channel kind, and every
  check that walks `CHANNELS` skips that kind. Adding a check that forgets to
  is the easiest bug to introduce here, so `InteriorIsolationTests` asserts no
  per-vehicle finding ever cites a channel at or above 176.
- **Segment, not channel, is the unit.** "Left Rear RGB (green) is not fitted"
  would be three findings saying one thing, so the interior is analysed by
  `analyze_interior()` and reported once, above the per-vehicle sections.
- **The findings are vehicle-independent on purpose.** The README says the
  accent segments exist "on cars with Interior Accent Lights" without naming
  which builds those are, so there is nothing to report per vehicle. Do not
  guess a vehicle list; the display is the segment that is safe to rely on,
  which is why a show that drives only the accents gets a warning.
- **Only a 200-channel export has them.** A 48-channel show has no interior
  data at all, which is what `interior-not-in-export` says.

### Closures have a budget; lights no longer do

[#50](https://github.com/teslamotors/light-show/issues/50) was filed when a
show overran the old whole-show command limit — the reporter saw "more than
241%". That number came from `validator.py` itself, which used to carry
`MEMORY_LIMIT = 681` and count state changes in four buckets per frame. It was
raised to 3500 and then removed; `README.md`, "General Limitations of Custom
Shows" now says the command limit is gone. Do not resurrect it.

What did not go away is the per-closure actuation limit in the "Closures
channels" table, and `analyze_closures()` in `tools/vehicle_preview.py` counts
against it. The rules, all from `README.md`:

- **Only Open, Close and Dance count**, and the limits are "counted separately
  for each individual closure" — each of the four windows has its own 6, not a
  shared one. `COUNTED_COMMANDS` is derived from `CLOSURE_CODES` so the
  percentages cannot drift apart.
- **A command is an effect, not a frame.** One Dance held for ten seconds is
  one actuation. Counting frames instead would put every shipped example
  hundreds of commands over its limit, which is what
  `test_counting_is_per_effect_not_per_frame` exists to catch.
- **Dance is not universal.** Mirrors, door handles and front doors are marked
  "-" in the "Supports Dance?" column; a Dance there does nothing, which is
  what the issue's reporter hit on a Model 3.
- **Dance needs an open closure, windows excepted**, and the open takes the
  time given in "Closure Movement Durations" — 14 s for a liftgate, 22 s for
  front doors.
- **Two shipped examples already break these rules**, and the tests record
  that rather than hiding it: `lightshow_example_2` dances a door handle, and
  `lightshow_example_5` spends 4 charge port commands against a limit of 3.
  If you change the counting, that list is what tells you whether you changed
  the meaning.

Severity here follows the documentation's own confidence. A hard limit being
exceeded is a `WARNING`; the timing rules are `INFO`, because the movement
durations are documented as approximate and shipped shows do cut them fine.
The 100 ms bunching threshold is this tool's judgement and says so in its own
detail text — the README only offers 20 ms as an example.

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
