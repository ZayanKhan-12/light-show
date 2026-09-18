---
name: Something the car does
about: A show that will not play, plays wrongly, or stops part way
title: ''
labels: ''
assignees: ''
---

This tracker cannot reach the people who own the vehicle software, so please
report it through Tesla service as well. It is still worth writing down here
so other owners can find it.

**Vehicle**

Model, year, and the software version from Controls > Software.

**What happened**

What you did, what the screen said, and what the car did.

**What the checks say**

Running this rules out the drive, the file and the show before the car is
blamed, which is the part nobody else can do for you:

```
python3 tools/diagnose.py /Volumes/YOURDRIVE
```

If it ends by saying everything it checked is sound, paste that - it is the
useful half of the report.

**If a light behaved differently from the documentation**

`tools/channel_probe.py` builds a show that lights one channel at a time with
a tone at each change, so a phone video shows what your car actually does.
Include the schedule it printed.
