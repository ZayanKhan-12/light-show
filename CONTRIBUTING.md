# Contributing

This repository holds the things an owner needs to build a custom light show:
the xLights project directory, example shows, and the scripts that check a
show or a drive before it goes near a car.

It does not hold the light show feature itself. That is vehicle software, and
the most common reason an issue here goes unanswered for a year is that nobody
reading it can act on it. This page is about telling those apart.

## Work out which layer you are looking at

A show passes through four of them, and each one is only worth examining once
the one before it is sound:

| Layer | What goes wrong there | Check it with |
| --- | --- | --- |
| The USB drive | The show is not offered, or the dialog says "Light Show" instead of "Custom Light Show" | `tools/usb_check.py` |
| The show file | The car shows an error such as "Incorrect number of channels" | `validator.py` |
| The show against your vehicle | It plays, but looks wrong, sparse or unfinished | `tools/vehicle_preview.py` |
| The car's software | It plays and then stops, the screen crashes, or a drive every check passes is refused | Nothing here |

One command runs whichever of those apply:

```
python3 tools/diagnose.py /Volumes/LIGHTSHOW
python3 tools/diagnose.py lightshow.fseq
```

It ends by saying what it ruled out, which is the single most useful thing to
put in a report.

## Where to send each kind of report

**The xLights project, the examples, the scripts or the documentation here.**
Open an issue or a pull request in this repository. Say which file, what you
expected, and what happened.

**The car.** A show that starts and stops, a screen that crashes, a vehicle
that does not offer custom shows at all, or a light that does not match its
channel: these are vehicle software or vehicle hardware, and this tracker
cannot reach the people who own them. Report them through Tesla service or
the in-car voice command, and include the vehicle, its software version, and
what you were doing. Posting them here as well is reasonable if you want other
owners to find them, but do not expect a fix to come from here.

**xLights itself.** Crashes, dialogs, rendering and the sequencer belong in
the [xLights tracker](https://github.com/smeighan/xLights/issues). Some
xLights messages are really about how a Tesla sequence is set up; those are
listed under "Error messages in xLights" in the README.

**A light that behaves differently from the documentation on your car.** These
are worth reporting, and they are worth reporting *with evidence*, because
nobody else has your build. `tools/channel_probe.py` builds a show that lights
one channel at a time with a tone at each change, so a phone video says what
your car actually does. Include the vehicle, its build date and factory, and
the schedule the probe printed.

## What a change here needs

- **Python is standard library only**, targeting 3.7, in `validator.py` and
  everything in `tools/`. People run these by double-clicking them; a
  dependency they have to install is a support burden.
- **Every check needs a test that fails when the thing it checks is broken.**
  A check that cannot fail is not a check.
- **Cite the documentation.** Where a rule comes from `README.md`, name the
  section in the finding, so the code and the guide stay reviewable side by
  side. Where the README is silent, say so rather than presenting a guess as
  fact.
- **Channel assignments are a public API.** The mapping from a light to its
  channel is what every `.fseq` anyone has exported depends on. A confirmed
  per-vehicle difference is documented, never corrected by moving a channel.
- Run the suite before opening a pull request:

  ```
  python3 -m unittest discover -s tests
  python3 tools/xlights_layers.py verify
  python3 tools/docs_check.py
  ```

`CLAUDE.md` holds the longer version of all of this, including the traps that
have caught people before.
