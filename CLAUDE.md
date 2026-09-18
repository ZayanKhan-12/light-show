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
| `tools/multi_car_check.py` | Checks that the per-car shows of a cross-vehicle set agree with each other. |
| `tools/docs_check.py` | Checks the documentation's links, file references and the community show list, without touching the network. |
| `tools/sequence_check.py` | Reads a saved xLights `.xsq` and reports what will get in the way later. |
| `tools/channel_probe.py` | Builds a show that lights one channel at a time, to see what each drives on a particular car. |
| `tools/show_folder_check.py` | Checks the folder given to xLights as the show folder, and the audio files in it. |
| `tools/fseq_export.py` | Writes out what a `.fseq` does, one row per effect, with each value decoded. |
| `tools/examples_index.py` | Lists what each example in `examples/` ships; the README table is its output. |
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

### Say what is in the box before someone downloads it

[#87](https://github.com/teslamotors/light-show/issues/87) asks for the `.xsq`
of a show. Nobody could answer it, because `examples/` is sixty megabytes of
archives with no index: the only way to learn what is inside one was to
download it and open it.

`tools/examples_index.py` builds the table now in `README.md`, and a test
asserts every generated line still appears there, so the table cannot drift
from the files. Writing it turned up something the repository never explained:
**examples 4 and 5 ship a `.fseq` with no source, and examples 6 and 7 ship
the source for those same two shows with no `.fseq`.** Anyone wanting to edit
the eight-car Ready for Assault had no way to know its sequence was in a
different archive.

Two things to keep straight in it:

- **"Plays fullest on" is a measurement.** It is the vehicle with the largest
  `coverage()` share, not a claim about what the author intended. Cyber
  Symphony measures fullest on a Model S despite its name, because it does not
  use the light bars.
- **A path segment is a car, a filename is not.** The first version counted
  `Car_setup.jpg` as a car and reported the five-car show as six. `_CAR_FOLDER`
  matches whole directory segments only, with a test for the file that broke
  it.

The request itself is Tesla's to grant: the shows built into the car are
vehicle software, not files here, and the README now says so plainly rather
than leaving the question unanswered for two years.

### "Nothing happened" is usually something you cannot see

[#82](https://github.com/teslamotors/light-show/issues/82) is a Model S owner
who formatted the drive, was recognised by the car, started the show, got out
-- and saw "the windows will roll down and up but the show never start". The
reply is a correct restatement of the whole USB checklist, which is the only
thing anyone could offer, and it does not fit: the windows moving is proof the
sequence reached the car.

The measurement that fits is where a show's lit time actually lands.
`coverage()` counts it per vehicle, and the shipped shows make the point:

- "The Arrival" spends **84% of itself on the Cybertruck light bars**, so a
  Model S plays 17% of it.
- The older single-car shows lose **28-35% on a Cybertruck**, which has no
  Signature lights and no Channels 4-6.

Neither is a defect. Both are the difference between "this show is broken" and
"this show was written for a different car", and nothing here could say which
before.

Things to keep right:

- **Channels 47-175 are a block, not channels.** `CHANNEL_BLOCKS` describes
  the light bars as runs of identical LEDs with the vehicles that have them;
  they are deliberately not in `CHANNELS`, and a test asserts they never
  overlap it. Their ranges are checked against `channel_map.json` and their
  counts against the README's "60 LEDs" and "52".
- **Interior RGB is counted separately, not as missing.** The README does not
  say which builds have the accent segments, so calling them absent would be
  the guess this repository keeps refusing to make.
- **A test written from an assumption about the shipped shows will be wrong.**
  This is the second time: the guess was "every show plays fully on a
  Cybertruck", and the failing test is what turned a one-way observation into
  the symmetry above.

### A show is often the only copy of itself

[#79](https://github.com/teslamotors/light-show/issues/79) asks how to get the
data back out of a `.fseq`. Community sites hand out `.fseq` files with no
`.xsq`, so there is frequently nothing else to work from.

Two answers, and they are for different goals. To **edit** the show, xLights
imports a `.fseq` as a data layer — that is xLights' feature, now written down
in `README.md` where it was missing entirely, and `sequence_check.py` reports
any imported layer so the import can be confirmed. To **read** the show,
`tools/fseq_export.py` writes one row per effect.

The exporter's one rule: **decode only what `README.md` documents.** A light
value that matches a ramp code is named as one, a closure value is named
Open/Dance/Close/Stop, an interior channel reports a component level — and a
value that is *not* one of the documented steps says "60% (on)" rather than
being rounded to the nearest documented effect. Rounding would invent
precision the file does not have, and this tool is most useful to someone
trying to work out what a stranger's show actually does.

It reuses `vehicle_preview`'s reader, channel table and code tables rather
than restating any of them, which is why a new documented effect only has to
be added once.

### Report the fact; do not invent the fault

[#78](https://github.com/teslamotors/light-show/issues/78) is a show whose
music runs ahead of its lights. A repository contributor gave the documented
answer -- the audio must be 44.1 kHz -- and three more owners replied that
theirs already was. The thread then collects guesses, including a rename
ritual and the Dance Moves checkbox.

`usb_check.py` already checks the two causes this repository can speak to, the
sample rate and a length mismatch between the sequence and its audio. What was
missing was the third question an owner needs answered: **when does this show
actually start?**

`Show.first_lit_ms()` answers it, and it is deliberately *not* a finding.
"The Arrival" in `examples/` is dark for its first 5.3 s while the track
opens, so leading darkness is normal and flagging it would call Tesla's
featured show broken. Printed as a fact it does the useful work either way:
it explains a delay that matches, and it rules the file out when the delay
does not.

That is the general shape for a symptom nobody here can reproduce: **check
what is checkable, print the measurement that discriminates, and attribute the
rest.** The Dance Moves reports are in `README.md` as owner reports with no
mechanism claimed, because this repository does not know one.

### Check the shipped shows before deciding a report is unreproducible

[#77](https://github.com/teslamotors/light-show/issues/77) says a Model X
halts a few seconds into any custom show, "even for the one I download from
this git repo", unless Dance Moves is switched off. `README.md` has carried
the cause in "Other notes" all along: moving windows during Model X door
movement can cause false pinch detections, **stopping the light show**. It is
the only closure mistake whose consequence is the whole show ending, and
nothing checked for it.

Writing that check, I first sampled a few `examples/` files, saw no door
commands, and wrote a test asserting no shipped example drives a Model X door.
The test failed. The sample had missed the two **zipped** examples, and both
of them -- including the show featured in vehicles from 2022.44.25 -- open the
powered doors and then move the windows a few seconds later, inside the ~20 s
the doors take. The reporter's shows were the repository's own.

Two habits from that:

- **`example_shows()` walks the zips as well as the loose folders.** Any
  survey of "what do the shipped shows do" has to go through it, not a glob.
  A glob over `examples/**/*.fseq` silently covers only the multi-car sets.
- **When a test written from a sample fails, the sample was wrong before the
  test was.** The failing assertion here was the interesting result, and
  rewriting it to record the real state is what turned an unreproducible
  report into a reproduction.

`pinch_doors` is empty for every vehicle but Model X, because it is the only
supported vehicle with powered doors, and the movement windows come from
"Closure Movement Durations" — which is also why `ClosureFamily` now carries
`close_ms`: a door closing is only risky for the 3 to 8 s it takes, not the 22
an open takes.

### One report is a note, not a model

[#76](https://github.com/teslamotors/light-show/issues/76) is an owner saying
that on their 2022 Model X Plaid, Front Turn and Aux Park are one lamp: orange
from one channel, white from the other, a dimmer mix from both. It is exactly
the kind of detail `README.md` should carry, and the repository already knew
it was missing -- the Model X profile has carried a note saying the aux park
pairing is *assumed* from Model S because the README never states Model X.

What went in: the report, in `README.md` and in the Model X profile's notes,
attributed, with the build it came from and the fact that it is a single
account. What did not go in: an `OrGroup`. Making the tool assert that Front
Turn and Aux Park share an output would turn one owner's observation into
findings on every Model X show, and a wrong one would be worse than the
silence it replaced.

The line to hold: **a single report is documented; a confirmed pattern is
modelled.** If a second Model X owner confirms it, adding the `OrGroup` is a
two-line change and the note becomes its citation.

`tools/channel_probe.py` now takes `13+17` to drive channels together in one
turn, so the three states in that report -- each channel alone, then both --
are a fifteen-second video on any Model X. That is the cheapest way to move a
report from one account to a confirmed pattern, and it is why the probe
exists.

### An approximate number is not a threshold

[#128](https://github.com/teslamotors/light-show/issues/128) is an owner
filming the trunk of a shipped example: it opens, stops after a couple of
seconds and closes again, because a Dance arrives while the liftgate is still
moving. `analyze_closures()` already had a check for exactly that, and it
**missed this case by 500 ms**.

The check compared the Open-to-Dance gap against the movement duration in
`README.md`. Cyber Symphony leaves 14.5 s against a documented 14 s, so it
passed. But that table is headed "Approximate", and
[#72](https://github.com/teslamotors/light-show/issues/72) reports a liftgate
opening in 12 s where it says 14. A documented approximation used as a hard
boundary will pass shows that fail on a different car, which is the whole
failure mode.

`DANCE_MARGIN` is a quarter, and the number is not arbitrary. Every
Open-to-Dance gap in `examples/` measures 0.37x, 0.44x, 0.91x, **1.04x**,
1.34x, 2.62x, 3.37x and 7.27x of its documented duration. The 1.04x is the
liftgate from the issue; the next one up is 1.34x. A quarter is the margin
that separates the case with video evidence from the shows nobody has
complained about. If that ever needs revisiting, re-measure rather than
guess — the survey is a short script over `closure_usage()`.

The general habit: **when a documented figure is labelled approximate, do not
turn it into a `<` comparison.** Either carry a margin or report the margin
you have, and say in the finding which number is documented and which is the
tool's judgement.

### A vague report still has checkable causes

[#75](https://github.com/teslamotors/light-show/issues/75) is one sentence:
"the file doesn't show up when I press custom and then I select file of model
S". It went unanswered for three years, and it is tempting to close as
unclear. Read against `README.md`, "Creating a new sequence", it lands on
step 4 -- choosing the audio for a new Musical Sequence -- and the causes are
finite and checkable from disk:

- **The file type dropdown.** A `.wav` is hidden unless it is set to "xLights
  Audio Files". The README noted this as a trailing clause on step 4 with a
  screenshot, which is a hard place to find when you are searching for a
  symptom rather than reading the steps in order.
- **A format xLights never lists.** `.m4a`, `.aac`, `.flac`, `.wma` do not
  appear however the dropdown is set, and a music library hands out `.m4a` by
  default. The README said "use .mp3 or .wav" but never that everything else
  is invisible.
- **The wrong folder.** "Model S" is the show folder, and if xLights was
  pointed at the zip, the folder above the project directory, or the extra
  folder "Extract All" leaves behind, no Tesla models appear either.

So the answer was a symptom-first section (`When something does not show up in
xLights`) rather than another paragraph inside the numbered steps. When an
issue is vague, work out which documented step it lands on and cover the
causes of that step; do not ask a reporter who left three years ago.

`tools/show_folder_check.py` covers the checkable half. Notes on it:

- **`UNLISTED_AUDIO` is a list of what people actually arrive with**, not an
  attempt at every audio extension. An unknown extension is ignored rather
  than guessed at, because claiming xLights will not list something is a
  claim.
- **It names the folder to select.** The `folder-one-level-up` finding prints
  the full path to paste into File > Select Show Folder, which is the whole
  value of noticing the nesting.
- **It tells the two project folders apart** by counting controllers in
  `xlights_networks.xml`, the same fact `validator.describe_channel_count()`
  uses: one car is 200 channels, the cross-vehicle folder is five of them.

### A mapping report is answered with an instrument, not an edit

[#72](https://github.com/teslamotors/light-show/issues/72) reports that Inner
and Outer Main Beam are swapped on a 2023 Fremont Model 3 RWD. It sat for two
years because nobody could act on it: the reader has no such car, the reporter
had no way to show what they saw, and the one response that must never be made
is the obvious one.

**Do not remap a channel to make a report go away.** `xlights/channel_map.json`
is a public API — every `.fseq` anyone has exported depends on it — and
swapping two entries on one unverified report about one build would break
every existing show on every car. `tools/xlights_layers.py verify` and CI
enforce that, but the instinct is the thing to correct.

What can be done:

- **Give the reporter a way to prove it.** `tools/channel_probe.py` builds a
  show that lights one channel at a time with a tone at each change, so a
  phone video settles the question on the car it is about. The tool checks its
  own output with `validator.validate()` before writing it.
- **Do not adjudicate from the images.** The headlamp diagrams in `images/`
  are photographs with numbered overlays; which end of a lamp is inboard is
  not reliably readable from them, and a confident answer drawn that way would
  be a guess wearing evidence's clothes. Say what the show folder maps and let
  the car settle the rest.
- **Document a confirmed difference, never correct it.** The precedents are
  "Cybertruck Light Remapping" and the pre-October-2020 Model 3 tail lights:
  both are cars where a channel drives something other than its name, recorded
  as a per-vehicle note. `BuildVariant` in `tools/vehicle_preview.py` is where
  one becomes analysable.

Closures are opt-in in the probe and are opened, never danced: an Open costs
one actuation against a limit as low as 3, and the tool says it leaves them
open so nobody walks away from a raised liftgate.

### Not every error here is ours, and not every title is true

[#66](https://github.com/teslamotors/light-show/issues/66) is an owner who
spent a year updating graphics drivers and logging Windows out and back in,
because xLights titles one of its warnings "Graphics Driver Problem". The
message underneath it — "Paste By Cell information missing. You can only
Paste By Time with this data" — is the real one, and the cause is that
pasting by cell needs the cells a timing track's marks create.

Two habits come out of that:

- **Quote the string from the screen, verbatim.** `PASTE_BY_CELL_DIALOG` holds
  the whole sentence so that pasting it into a search reaches the
  explanation, and a test asserts it stays in the finding. The same reason
  `VEHICLE_ERROR` exists in `validator.py`.
- **Say when a title is wrong.** The finding states outright that the graphics
  driver has nothing to do with it. Repeating a misleading label politely is
  how someone loses a year to it.

The root cause was ours, though: `README.md` never introduced timing tracks at
all, while `cross-vehicle-shows/README.md` told people to right-click one. A
reader following the guide end to end never made a timing track, then pasted
by cell. That gap is filled, and the xLights error table sits next to it.

`tools/sequence_check.py` reads the `.xsq`. Things to keep in mind:

- **An `.xsq` is xLights' file, not the vehicle's.** Nothing in this tool is a
  claim about what the car will play; `validator.py` owns that, and the tool
  says so when handed the wrong file. Its checks are the ones traceable to
  `README.md`: the 15-100 ms frame interval, the 4 hour limit, audio on a
  musical sequence, and the timing marks above.
- **What it deliberately does not check** is whether the models a sequence
  uses still exist in the show folder. That depends on which folder the
  sequence was built in — the cross-vehicle folder has entirely different
  model names — so the check would fire on correct sequences. The
  "Sequence Element Mismatch" row in the README covers it in prose instead.
- **xLights bugs go to xLights.** A repo Contributor said so on #66 and was
  right; the README says it too, with a link to their tracker.

### The vehicle's error messages are the repository's problem

[#65](https://github.com/teslamotors/light-show/issues/65) is four owners over
a year hitting "Incorrect number of channels" with nothing to tell them what
it meant. `validator.py` already rejected those files — it just said
"Expected 48 or 200 channels, got 1000", which names the symptom the car
already gave them.

The cause is knowable from the show folders, and `describe_channel_count()`
now says it: a sequence's channel count comes from the folder it was built in.
`tesla_xlights_show_folder` defines one 200-channel controller.
`tesla_xlights_cross_vehicle_folder` defines five, so a sequence exported
straight out of it is 1000 channels — the cross-vehicle export step was
skipped. Any other number means a different show directory entirely.

- **Tie a message to the data it describes.**
  `test_the_cross_vehicle_folder_exports_five_cars` reads
  `xlights_networks.xml` out of the shipped zip and asserts the total is what
  the message claims. If Tesla ships a six-car folder, that test fails rather
  than the message quietly becoming wrong.
- **Name the car's own wording.** `VEHICLE_ERROR` is in every channel-count
  message so that searching the phrase from the screen reaches the
  explanation. `README.md` has a table of the messages owners have reported;
  add to it when a new one is reported, and do not invent entries for errors
  nobody has seen.
- **`validator.py` has tests now** (`tests/test_validator.py`). It is the tool
  the README points at and the one packaged as an .exe, so it had the most
  users and the least coverage. Keep it standard library, 3.7+, and leave the
  blocking `input()` in `__main__` alone.

### A show is channels, not pixels

[#64](https://github.com/teslamotors/light-show/issues/64) asks whether the
headlights can project an arbitrary image. They cannot, and the answer is in
`xlights/channel_map.json` rather than in an opinion: every headlamp model is
`Single Color White` with one node, so the finest thing a show can say about a
headlight is how bright it is. The light bars are the opposite — `Node Single
Color` with 60, 52 and 6 nodes — which is why pixel-level effects belong
there. Answer this class of question from the channel map, and do not
speculate about what the hardware could do if it were driven differently;
that is not something this repository knows.

Note also that "projector" in `README.md` is the headlamp optic type, next to
"reflector". It has never meant image projection, and the confusion is why the
issue was filed.

### Cross-vehicle sets are kept together by length, not frame rate

The other half of #64 — animation running across several parked cars — has
shipped: `cross-vehicle-shows/README.md`, the cross-vehicle show folder, and
three examples. Each car plays its own `.fseq`, started together by scheduling
the show.

`tools/multi_car_check.py` checks a set, and the rule it encodes is easy to
get wrong: **what must match across cars is the total duration and the audio,
not the frame count or the frame interval.**
`examples/lightshow_example_3_The_Arrival_5_Car` runs cars 1 and 3 at 25 ms
and cars 2, 4 and 5 at 50 ms, every car lasting exactly 110.25 s. A check that
compared frame counts would call Tesla's own five-car show broken, so
`test_different_frame_intervals_are_not_a_problem` and a test over the shipped
sets hold that line.

The export step is the reason the tool exists: it is a manual xLights
round trip repeated once per car, five to eight times, and nothing else
checks the result.

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
