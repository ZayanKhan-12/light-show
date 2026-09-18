# **Tesla Light Show xLights Guide**

Welcome to the Tesla Light Show xLights guide! You can create and run your own light shows on Tesla vehicles.

<img src="/images/xlights_overview.png?raw=true" width="1000" />

## Running a custom show on a vehicle
A custom show can be run on a supported vehicle by loading it via a USB flash drive. Create and share your shows with others! A single show can be shared and run on any supported vehicle; they are not model-specific. The sequence data is stored in a .fseq file and the music comes from your choice of .mp3 or .wav.
### <a name="download_a_show"></a>Download a Show
Custom shows are shared by the community. These sites host shows to download:

<!-- community-shows: alphabetical, one "- [Name](https://url)" per line. See tools/docs_check.py. -->
- [TeslaLightShare.io](https://teslalightshare.io/)
- [TeslaLightShows.io](https://www.teslalightshows.io/)
- [XLightShows](https://xlightshows.io/)
<!-- /community-shows -->

The list is alphabetical and is not a ranking. These sites are run by the community: Tesla does not operate, review or endorse them, and what each one offers is between you and the site. To have a site added, open a [pull request](https://github.com/teslamotors/light-show/pulls) adding it to the list above.

A downloaded show is a binary file from a stranger. Check one before you use it:

```
python3 validator.py lightshow.fseq          # is it a show the car can play?
python3 tools/vehicle_preview.py lightshow.fseq --vehicle model3
python3 tools/usb_check.py /Volumes/LIGHTSHOW
```

Screenshots from two of the sites:

<a href="https://xlightshows.io/"><img src="/images/xlightshows_screenshot.png?raw=true" width="1000"/></a>

<a href="https://teslalightshare.io/"><img src="/images/tesla_light_share_screenshot.png?raw=true" width="1000"/></a>

### Supported Vehicles
- Model S (2021+)
- Model 3
- Model X (2021+)
- Model Y
- Cybertruck
- Running Software v11.0 (2021.44.25) or newer

Both the vehicle and the software version have to qualify. Model S and Model X are supported from the 2021 refresh onwards, so an earlier car is not on the list however new its software is, and a listed vehicle still needs v11.0 (2021.44.25) or newer.

Playing a custom show is a vehicle capability. It cannot be enabled by the show file, by the USB flash drive, or by anything in this repository, so there is no workaround to try if your vehicle is not listed above. Requests to support another vehicle belong in an [issue](https://github.com/teslamotors/light-show/issues) for the maintainers.

### USB flash drive requirements
- Must contain a base-level folder called "LightShow" (without quotation marks and case sensitive).
- The LightShow folder must contain at least 2 files:
  - a show .fseq file
  - a show .mp3 or .wav file (wav is recommended)
- The fseq filename must match the mp3/wav filenames
    - E.g., show1.fseq/show1.wav can exist with show2.fseq/show2.mp3
- <a name="multiple_shows"></a>Multiple shows can be stored on 1 USB drive (2023.44.25+ Vehicle Software)
    - Put every show directly in the same LightShow folder, side by side. Shows in subfolders are not found.
    - Each show is one .fseq plus the .mp3/.wav of the same name; the vehicle lists each pair as its own entry.
    - The name shown in the picker is the filename, so name the files the way you want them to read on screen.
    - [usb_check.py](#usb_check) reports which shows a drive will offer, and why any other was left out.

  ```
  LightShow/
    blue-da-ba-dee-by-eiffel-65.fseq
    blue-da-ba-dee-by-eiffel-65.wav
    darude-sandstorm.fseq
    darude-sandstorm.mp3
    nz-lightshow-2023.fseq
    nz-lightshow-2023.mp3
  ```
- Must be formatted as exFAT, FAT 32 (for Windows), MS-DOS FAT (for Mac), ext3, or ext4. NTFS is currently not supported.
- Must **not** contain a base-level TeslaCam folder.
- Must **not** contain any map update or firmware update files.
### Running the custom light show on a vehicle
- Insert the flash drive into one of the front USB, USB-C ports, or glovebox USB port, then wait a few seconds.
- In Toybox, select Light Show and tap Schedule Show.

    <img src="/images/start_show_button.png?raw=true" width="315" />

- If the files on the USB flash drive meet the requirements, then the custom shows will be available to select from the drop-down menu.

    <img src="/images/multi_select_usb.png?raw=true" widtht="442" />

### Light Show Community
[reddit.com/r/TeslaLightShow/](https://www.reddit.com/r/TeslaLightShow/)

### Debug
- If the popup title is "Light Show" instead of "Custom Light Show", then the requirements are not being met for the USB flash drive formatting and/or required folder and files. [usb_check.py](#usb_check) reports which requirement a drive is missing.
- If Toybox has no Light Show entry at all, check the vehicle and software version against [Supported Vehicles](#supported-vehicles) before looking at the drive.
- Error messages will be provided if the required files exist but there is a problem with the light show sequence file. The ones owners have reported are listed below.

### <a name="vehicle_errors"></a>Error messages from the vehicle
Run [validator.py](#light-show-sequence-validator-script) on a show before taking it to the car; it checks the same things and explains what it finds.

| Message on the screen | What it means |
| --- | --- |
| ```Incorrect number of channels``` | The .fseq has a channel count other than 48 or 200. A count that is a multiple of 200 - 1000 is the usual one - is a [cross-vehicle sequence](#cross_vehicle) exported as a single file instead of once per car. Any other number means the sequence was built in a different xLights show directory. `validator.py` names which of the two it is. |

Two things that are **not** causes, although both come up:

- **The number of commands in a show.** That limit was [removed](#show_limits). A show is no longer rejected for being too large.
- **A show that plays on one car but not another.** The .fseq is not model-specific; a show that plays on one supported vehicle will load on any of them. If the vehicle differs, check it against [Supported Vehicles](#supported-vehicles) instead.

Audio that will not play or drifts out of sync is a separate problem: the file has to be [44.1 kHz](#audio-file-requirements), which [usb_check.py](#usb_check) checks along with the rest of the drive.

## <a name="show_limits"></a>General Limitations of Custom Shows
- The maximum duration for a custom Tesla xLights show is 4 hours.
- The limit on number of commands during a custom show has been removed. This was the whole-show budget that older versions of the validator reported as a "memory usage" percentage; light channels are no longer counted against anything, so a show can no longer be too large to play.
- Individual closures do still have actuation limits. They are listed in the [Closures channels](#closures) table, only Open, Close and Dance count towards them, and they are counted separately for each closure. The [Vehicle Preview Script](#vehicle_preview) reports how much of each closure's budget a show spends.

### <a name="what_a_show_controls"></a>What a custom show controls
A show is an array of channel values, one value per lamp per frame. It is not an image.

- **Each headlight is a single channel.** The Outer Main Beam, Inner Main Beam and the rest are one channel each, so a show sets how bright a lamp is and nothing finer. No channel addresses the elements inside a headlamp, so a show cannot put a word, a logo or a picture through one.
- **"Projector" here means the optics, not projection.** The [light channel locations](#light_locations) are given for reflector and projector headlamps; that is the lamp type fitted to the car, not an image projector.
- **Individually addressable LEDs do exist, on the light bars.** The [Cybertruck front light bar](#cybertruck-light-bar) has 60 controllable LEDs and the rear has 52, and the offroad bar has six segments. Pixel-level effects belong there, and xLights' own effects can be placed directly on them. The [interior RGB segments](#interior_rgb) take a colour each.
- **Animation across several cars is supported.** See [cross-vehicle shows](#cross_vehicle).
## Audio file requirements
You can use both the mp3 and wav format (.wav is recommended).
Make sure the file is encoded with a sample rate of 44.1 kHz; less common 48 kHz files won't properly sync to the light show.

## <a name="getting_started"></a>Getting started with the Tesla xLights project directory
1. Visit [xLights Downloads](https://xlights.org/releases/) to download and install the xLights application.
2. Download and unzip [tesla_xlights_show_folder.zip](xlights/tesla_xlights_show_folder.zip?raw=true), which is the Tesla xLights bare project directory.
   - It is recommended to keep the project directory structure as-is and leave all files in their default locations.
3. Open the xLights application.
4. **IMPORTANT:** In File > Preferences > Sequences > FSEQ Version, select "V2 Uncompressed".

    <img src="/images/v2_uncompressed.png?raw=true" width="500" />

5. In File > Select Show Folder, navigate to and select the unzipped project directory, then select Open.
6. Select the Layout tab to view the Tesla 3D vehicle model.
7. Make sure that the 3D preview checkbox is selected.

    <img src="/images/3d_preview.png?raw=true" width="750" />

8. Select the Sequencer tab.

    <img src="/images/xlights_layout.png?raw=true" width="950" />

9. Note that the previewed Tesla Model S combined with the Cybertruck include the superset of lights and closures that are needed for all supported vehicles, and should be used to generate shows for all vehicle types. See [light channel locations](#light-channel-locations) for information about where the lights are on each vehicle.

## Opening the example sequence
An example sequence is provided that can be run on the vehicle and/or opened in xLights. These instructions cover how to open it in xLights.
1. Follow the [getting started](#getting_started) instructions to set up the xLights project.
2. Download and unzip the example light show:
[lightshow_example_1_elevator_music.zip](examples/lightshow_example_1_elevator_music.zip?raw=true)
or
[lightshow_example_2_Max_Carlisle_Auld_Lang_Syne_In_the_City.zip](examples/lightshow_example_2_Max_Carlisle_Auld_Lang_Syne_In_the_City.zip?raw=true).
3. In File > Open Sequence, navigate to the unzipped folder and select the ```lightshow.xsq``` example file, then select Open.
4. In the Sequencer tab, double click groups in the timeline to reveal individual left / right control.

     <img src="/images/xlights_demo_track.png?raw=true" width="900" />

## Creating a new sequence
1. Follow the [getting started](#getting_started) instructions to set up the xLights project.
2. Select File > New Sequence
3. Select Musical Sequence
4. Navigate to your chosen .wav or mp3 file, select it, then select Open. Note that .wav files may be hidden unless file type is set to xLights Audio Files.

    <img src="/images/wav_hidden.png?raw=true" width="450" />

5. In the Wizard tab select Custom
6. Change the Frame interval to 20ms then select OK.

     <img src="/images/sequence_setting_20ms.png?raw=true" width="500" />

    Note: any value between 15ms and 100ms is supported by the vehicle, but 20ms is recommended for nearly all use cases. The [maximum show size limits](#show_limits) do not depend on the frame interval.

7. Select Quick Start and wait for the sequencer to load
8. In the top left of the timeline, select a view in the view selector. "Group View" groups channels by light type, ["Layer View"](#layer_view) groups them by position on the vehicle, and "Old View" is the pre-update layout.

    <img src="/images/groups_select_view.png?raw=true" width="450" />

9. If using the recommended "Group View", you can double click the light groups to reveal and hide individual left/right control. Placing light effects in the group object will activate both the left and right light

    <img src="/images/groups_left_right.png?raw=true" width="450" />

10. If using the old view, double click on "GRP Tesla Model S" to view all channels

    <img src="/images/all_lights_closures_old.png?raw=true" width="450" />

11. For more information on the workflow of creating xLights sequences, please use existing online resources. The rest of these instructions contain Tesla-specific information for show creators.

## <a name="timing_tracks"></a>Working with timing tracks
A timing track is the row of marks along the top of the timeline that divides the sequence into cells, usually on the beat. Nothing forces you to add one, but a lot of xLights works off it: the marks are what effects snap to, what "Divide Timings" splits, and what **Paste By Cell** pastes into. Add one from the xLights Timing menu before you start placing effects, and put marks on it.

A sequence with no marks has no cells, which is worth knowing because of the message it produces:

### Error messages in xLights
These come from xLights rather than from the vehicle. xLights bugs belong in the [xLights issue tracker](https://github.com/smeighan/xLights/issues); what is listed here is the ones that are really about how a Tesla sequence is set up.

| Message on the screen | What it means |
| --- | --- |
| ```Graphics Driver Problem: Paste By Cell information missing. You can only Paste By Time with this data.``` | Nothing to do with the graphics driver, despite the title. Pasting by cell needs the cells that a [timing track's](#timing_tracks) marks create, and this sequence has none. Either switch to Paste By Time in the toolbar, or add a timing track with marks on it. |
| ```Sequence Element Mismatch``` | The sequence refers to a model the current show folder does not have. It is [expected on a few older shows](#converting-old-show-files) that programmed the rear light bar pixel by pixel; choose "Delete this element from the sequence" to carry on. |

To check a sequence before exporting it, run [sequence_check.py](#sequence_check).

### <a name="not_showing_up"></a>When something does not show up in xLights
**The audio file is not in the list when creating a sequence.** Two reasons, in order of likelihood:

- The picker's file type dropdown is set to one of the FPP options. Set it to "xLights Audio Files" and the file appears - this is the note on step 4 of [creating a new sequence](#creating-a-new-sequence), and the [screenshot](#creating-a-new-sequence) shows the dropdown.
- The file is not a format xLights lists at all. Only .mp3 and .wav are offered; an .m4a, .aac, .flac or .wma never appears however the dropdown is set, which is easy to hit because music libraries hand out .m4a. Convert it to a 44.1 kHz .wav.

**The Tesla vehicle, models or light groups are not there.** xLights is pointed at the wrong folder. The project directory is the folder containing `xlights_rgbeffects.xml`; unzipping often leaves a folder of the same name wrapped around it, and selecting the outer one finds nothing.

[show_folder_check.py](#show_folder_check) tells these apart:

```
python3 tools/show_folder_check.py ~/Downloads/tesla_xlights_show_folder
```

## <a name="show_folder_check"></a>Show Folder Check Script
`tools/show_folder_check.py` looks at the folder you gave xLights and reports what xLights will find in it:

```
python3 tools/show_folder_check.py path/to/tesla_xlights_show_folder
python3 tools/show_folder_check.py ~/Downloads -v
```

It reports a path that is still a .zip, a project folder one level below the one you picked (naming the folder to select instead), a folder that is not a project directory at all, and a missing `xlights_rgbeffects.xml` or `xlights_networks.xml`. It also lists the audio files in the folder, separating the ones xLights will offer from the ones it will not, and says when a folder is the [cross-vehicle](#cross_vehicle) one rather than the single-car project directory.

## <a name="sequence_check"></a>Sequence Check Script
`tools/sequence_check.py` reads a saved .xsq and reports what would get in the way later:

```
python3 tools/sequence_check.py lightshow.xsq
python3 tools/sequence_check.py lightshow.xsq -v      # list the timing tracks
```

It reports a sequence with no timing marks, a frame interval outside the supported 15-100 ms, a sequence longer than the 4 hour limit, and a musical sequence with no audio attached. It reads the .xsq you edit; the .fseq the car plays is checked with [validator.py](#light-show-sequence-validator-script).

### <a name="layer_view"></a>Grouping channels by position: "Layer View"
"Group View" is organized by *light type* — one row for both front turn signals,
one row for both mirrors, and so on. That is the right layout when you want the
left and right of a light to behave as a pair, but it makes "light up everything
on the front left of the car" a matter of placing the same effect on a dozen
separate rows.

"Layer View" is organized by *position on the vehicle* instead. Each row is a
region of the car, so a single effect covers everything in that region:

| Layer | Contains |
| --- | --- |
| `LAYER Front Left` | Every front-left exterior light: main beams, signature, channels 4-6, turn, fog, aux park and side marker |
| `LAYER Front Right` | The mirror image of the above |
| `LAYER Rear Left` | Left side repeater, rear turn and tail light |
| `LAYER Rear Right` | The mirror image of the above |
| `LAYER Rear Center` | Brake lights, reverse lights, rear fog and license plate — the rear lights with no independent left/right control |
| `LAYER All Doors` | Front doors and falcon doors |

`LAYER Front Left` and `LAYER Front Right` together contain exactly the same
lights as the existing "Front" group, and the three rear layers together contain
exactly the "Rear" group, so nothing is left out and nothing is covered twice.
Double click any layer to expand it and control the individual lights inside.

Three more layers are available from the Layout tab for anyone building a custom
view. They are not rows in "Layer View" because they overlap the rows above:

- `LAYER Left Side` — the whole left flank, front and rear, including the Cybertruck light bar segments
- `LAYER Right Side` — the mirror image
- `LAYER All Closures` — every moving closure: doors, windows, mirrors, door handles, liftgate and charge port

Closures still move at their own pace, so see [closure movement durations](#closure_movement_durations)
before putting a fast effect on `LAYER All Doors` or `LAYER All Closures`.

## Light Show Sequence Validator Script
A Python [validator.py](validator.py) script is provided to help check if your custom light show sequence meets these limitations, without needing a Tesla vehicle.

Windows user can run validator.py by double clicking the file. Drag and drop the .fseq file into the new window.

## Checking the xLights show folder
The show folder ships as a .zip, so its contents cannot be reviewed from a diff.
Two files in `xlights/` describe what is inside it:

- `layer_groups.json` — the model groups and view added for position-based layers
- `channel_map.json` — the channel every model is assigned to

`tools/xlights_layers.py` keeps the .zip and those files in agreement:

```
python3 tools/xlights_layers.py verify   # check the show folder (run by CI)
python3 tools/xlights_layers.py apply    # write layer_groups.json into the .zip
```

`verify` fails if any model's channel assignment changes, which is what protects
.fseq files exported from earlier versions of this project from silently
breaking. Contributors changing the show folder should run it before opening a
pull request; it needs only Python 3.7+ and no packages.

## <a name="cross_vehicle"></a>Cross-vehicle shows
A show can run across several cars parked side by side, with effects that sweep from one car to the next. [cross-vehicle-shows/README.md](cross-vehicle-shows/README.md) covers programming one, and three finished examples ship in [examples/](examples): "The Arrival" on 5 cars, "Ready for Assault" on 8, and "Cyber Symphony" on 4. Each example folder has a diagram of how to park the cars.

The last step of making one is manual and repeated once per car: reopen xLights, import the cross-vehicle sequence with that car's mapping, Render All, save, export. `tools/multi_car_check.py` checks the result:

```
python3 tools/multi_car_check.py my-show-folder
```

Given a folder holding one folder per car, it reports anything that stops the set running as one show: cars whose shows are different lengths, a car carrying different audio from the rest, a missing car in the row, or a car exported from a different project folder. Note that the cars do **not** have to use the same frame interval - they stay together because their shows are the same length. "The Arrival" runs two of its five cars at 25 ms and three at 50 ms.

## Checking the documentation
This guide is held together by links: cross-references between its own sections,
images, the tools, the example archives, and the [community show list](#download_a_show).
`tools/docs_check.py` checks them without touching the network:

```
python3 tools/docs_check.py          # run by CI
python3 tools/docs_check.py -v       # include the notes
```

It reports a cross-reference that points at a section which no longer exists, a
link to a file that is not in the repository, an external link that is not https
or that carries a tracking parameter, and a community list that has fallen out of
alphabetical order or gained a duplicate. It never fetches a URL, so whether a
third-party site is up is not something a pull request here can fail on.

Users who do not have Python installed can instead use [validator-windows.exe](validator-windows.exe?raw=true) or [validator-macos](validator-macos.zip?raw=true) (on macOS, run with Ctrl + Left Click -> Open).

Alternatively, run:
```
python validator.py lightshow.fseq
```
macOS users should use this command instead:
```
python3 validator.py lightshow.fseq
```

Expected output looks like:
```
> python validator.py lightshow.fseq
Found 2247 frames, step time of 20 ms for a total duration of 0:00:44.940000.
```

## <a name="usb_check"></a>USB Drive Check Script
A drive that does not meet the [USB flash drive requirements](#usb-flash-drive-requirements) fails quietly: the show is missing from the list, or the dialog stays titled "Light Show" instead of "Custom Light Show", with nothing to say which rule was broken. This matters most with [several shows on one drive](#multiple_shows), where one mis-named file removes one entry from the picker and leaves the rest working.

A Python [usb_check.py](tools/usb_check.py) script reads a finished drive and reports the list of shows the vehicle will offer, plus the reason for anything left out:
```
python3 tools/usb_check.py /Volumes/LIGHTSHOW
```
On Windows, pass the drive letter (```python tools\usb_check.py E:\```); you can also point it at the LightShow folder itself, or run it with no argument and drag the drive onto the window. Add ```-v``` for the informational notes, ```--json``` for machine-readable output, or ```--strict``` to exit non-zero on warnings as well as errors.

It checks the base-level LightShow folder and its spelling, the .fseq/audio pairing for every show, each sequence against the same rules as [validator.py](#light-show-sequence-validator-script), the 44.1 kHz audio requirement, the drive's format, and the absence of a TeslaCam folder.

Expected output looks like:
```
> python3 tools/usb_check.py /Volumes/LIGHTSHOW
Drive:       /Volumes/LIGHTSHOW  (exfat)
Show folder: /Volumes/LIGHTSHOW/LightShow

The car will list 2 custom shows:

   1. darude-sandstorm              3 min 34 sec   darude-sandstorm.mp3
   2. nz-lightshow-2023             1 min 50 sec   nz-lightshow-2023.mp3

1 show will not appear:

  [ERROR  ] AUDIO_MISSING  knight-rider-theme-kitt
    knight-rider-theme-kitt.fseq has no matching .mp3 or .wav.
      Copy the audio the show was sequenced against into the same folder
      and name it knight-rider-theme-kitt.wav or knight-rider-theme-kitt.mp3.
      A show without its audio is not offered in the car.
      README: USB flash drive requirements

1 error(s), 0 warning(s), 1 note(s).
```

## <a name="vehicle_preview"></a>Vehicle Preview Script
The xLights project ships a single Model S / Cybertruck superset model, so the sequencer preview always animates every channel as its own instantly-switching light. Real vehicles differ: on Model 3/Y several channels are OR'd onto one physical output, and several lights that are boolean on Model S ramp instead. A show that looks right in the preview can therefore look wrong on the car.

A Python [vehicle_preview.py](tools/vehicle_preview.py) script reports where a given show will not reproduce what the preview showed, for every supported vehicle, without needing the vehicle:
```
python3 tools/vehicle_preview.py lightshow.fseq
```
To look at one vehicle only, and to include the per-configuration notes:
```
python3 tools/vehicle_preview.py lightshow.fseq --vehicle model3 -v
```
The vehicle keys are ```models```, ```modelx```, ```model3```, ```modely``` and ```cybertruck```. Add ```--json``` for machine-readable output, or ```--strict``` to exit non-zero when anything is reported, which is useful in a build pipeline.

The report opens with an [Interior RGB](#interior_rgb) section, which is the same on every vehicle: it lists what the show does with the Center Front Display and the five accent segments, and says so when a show cannot reach them at all.

Where a vehicle has builds that are wired differently, the report adds an "Also on ..." block under that vehicle listing only what changes for those cars. The one the README documents is Model 3 built before October 2020, whose tail and license plate lights share an output:

```
Model 3  -  0 error(s), 0 warning(s), 0 note(s)
========================================================================
  This show renders the same way the xLights preview shows it.

  Also on Model 3 built before October 2020:
  ----------------------------------------------------------------------

    [WARNING] or-group-collapse at 0:00.000
      Left tail + right tail (also drives the license plate lights) share
      one output on Model 3 built before October 2020, but this show drives
      them separately
```

A Closure command budget section follows it, also the same on every vehicle. Each closure has its own [actuation limit](#closures) for a show, and the xLights preview will happily animate a closure far past it, so the budget is easy to overrun without noticing:

```
------------------------------------------------------------------------
Closure command budget
------------------------------------------------------------------------
  Left Mirror               20 / 20   Mirrors       at the limit
  Right Mirror              20 / 20   Mirrors       at the limit
  Left Front Window          2 / 6    Windows
  Liftgate                   3 / 6    Liftgate
  Charge Port                3 / 3    Charge Port   at the limit
```

Expected output looks like, running against [lightshow_example_2](examples/lightshow_example_2_Max_Carlisle_Auld_Lang_Syne_In_the_City.zip?raw=true):
```
> python3 tools/vehicle_preview.py lightshow.fseq --vehicle model3
5762 frames, 20 ms per frame, total duration 1:55.240.

========================================================================
Model 3  -  4 error(s), 7 warning(s), 19 note(s)
========================================================================

  [ERROR  ] or-group-never-off at 0:25.240
    Left Channels 4-6 stays lit for 4060 ms on Model 3 even though every
    channel in it goes off
      These channels share one output on Model 3, so the lamp is on
      whenever any of them is on. Each channel does go off during this
      stretch, but never at the same time as the others, so the blinking
      visible in the preview becomes a single 4060 ms glow on the car.
      Leave a gap that is blank on every channel in the group to make the
      light actually flash. See README.md, "Light channel mapping
      recommendations".
      channels: Left Channel 4 (7), Left Channel 5 (9), Left Channel 6 (11)
...
```

### What the script reports
| Code | Meaning |
| --- | --- |
| ```or-group-collapse``` | Channels that the preview animates separately are wired to one output on this vehicle, and the show drives them differently. See [light channel mapping details](#light_channel_mapping_details). |
| ```or-group-never-off``` | Channels sharing one output blink at different times but never leave a shared gap, so the light sits solid instead of flashing. |
| ```ramp-too-short``` | A ramping effect ends long before the ramp completes, so the light never gets near its setpoint. Most often a channel that is boolean on Model S but ramping on Model 3/Y. |
| ```ramp-leader-missing``` | Channel 5 or 6 ramps while Channel 4 has no effect to define the duration. See [Ramping Channels 4-6](#ramping_channels_4_6). |
| ```ramp-ignored``` | A ramping effect on a channel that is boolean on this vehicle, so it switches instantly here. |
| ```channel-not-present``` | The show drives a light or closure this vehicle does not have. |
| ```channel-optional-hardware``` | The light is missing on some builds of this vehicle, for example front fog on Model 3 Standard Range +. |
| ```channel-has-no-effect``` | The light is fitted but follows another channel on this build, so its own channel does nothing. |
| ```interior-not-in-export``` | The show has no [interior RGB](#interior_rgb) channels, because it was exported from an older project directory. |
| ```interior-unused``` | The show can drive the interior lights and leaves every segment dark. |
| ```interior-accents-without-display``` | Only the optional accent segments are driven, so nothing lights up in a car without Interior Accent Lights. |
| ```interior-display-only``` | The Center Front Display is used and the accent segments are not, which works on every equipped car. |
| ```interior-partial-accents``` | Some accent segments are driven and others stay dark. |
| ```closure-limit-exceeded``` | A closure is given more Open/Close/Dance commands than its [documented limit](#closures) for one show. |
| ```closure-limit-reached``` | A closure is exactly at its limit, with no room for another command. |
| ```closure-dance-unsupported``` | A Dance request on a closure the table marks as not supporting Dance, such as the mirrors or door handles. |
| ```closure-dance-without-open``` | A Dance request while the closure is closed. Everything except windows must be opened first. |
| ```closure-dance-early``` | A Dance request too soon after its Open, counting the [movement duration](#closure_movement_durations) plus a quarter for margin, because those durations are approximate. |
| ```closure-dance-thermal``` | More than the recommended ~30 s of dancing on one closure. |
| ```closure-commands-bunched``` | Commands close enough together to spend the budget without moving the closure much. |

## Boolean Light Channels
Most lights available on the vehicle can only turn on or off instantly, which corresponds to 0% or 100% brightness of an 'Effect' in xLights.
- For off, use blank space in the xLights timeline
- For on, place *Turn On; Instant* (hotkey: 'F' on your keyboard)

The minimum on-time for boolean light channels to produce light is 15ms, although human eyes will have a hard time seeing anything this short! Minimum on-time or off-time of 100ms generally makes the show more pleasing to look at.

In this example, the Left Front Fog turns on and off 3x:

<img src="/images/on_effect_example.png?raw=true" width="550" />

## <a name="ramping_lights"></a>Light Channels with Brightness Control
Some channels can have a slow ramp in the intensity during turn-on or turn-off, to create graceful visual effects. Some even allow for full brightness control:
| Channel | Model S | Model X | Model 3/Y | Cybertruck |
| --- | --- | --- | --- | --- |
| Outer Main Beam  | Ramping on LED reflector headlights; <br> Boolean on LED projector headlights | Ramping on LED reflector headlights; <br> Boolean on LED projector headlights | Ramping on LED reflector headlights; <br> Boolean on LED projector headlights | Ramping |
| Inner Main Beam | Ramping | Ramping | Ramping | Ramping |
| Signature | Boolean | Boolean | Ramping | - |
| Channels 4-6 | Ramping | Ramping | Ramping | - |
| Front Turn | Boolean | Boolean | Ramping | Ramping |
| Front Side Markers | Boolean | Boolean | Boolean | Ramping |
| Front Light Bar | - | - | - | Full Brightness Control |
| Offroad Light Bar | - | - | - | Full Brightness Control |
| Rear Light Bar | - | - | - | Full Brightness Control |
| Brake Light | Boolean | Boolean | Boolean | Full Brightness Control |
| Rear Turn | Boolean | Boolean | Boolean | Full Brightness Control |
| Bed Lights | - | - | - | Boolean |

Cybertruck Bed Lights always ramp on and off with a 500 ms duration, even with 'Turn on/off; Instant' effects.

### Ramping light channels
To command a light to turn on or off and follow a ramp profile, place the effect with the corresponding keyboard shortcut:

| Ramping Function | xLights Effect Brightness | Hotkey
| ------ | ----------- | ----------- |
| Turn off; Instant | 0% | *empty timeline* |
| Turn off; 500 ms | 10% | W |
| Turn off; 1000 ms | 20% | S |
| Turn off; 2000 ms | 30% | X |
| Turn on; 500 ms | 70% | E |
| Turn on; 1000 ms | 80% | D |
| Turn on; 2000 ms | 90% | C |
| Turn on; Instant | 100% | F |

The keyboard layout is designed to be easy to use. Note that the effect types are grouped into vertical keyboard rows and sorted by duration.

<img src="/images/keyboard_shortcuts.png?raw=true" width="800" />

#### Other notes
- Ramping can only prolong the time it takes to fully turn a light on or turn off. It is not possible to command a steady-state brightness setpoint between 0% and 100% intensity.
- If an xLights effect is longer than the ramping duration, then the light will stay at 0% or 100% intensity after it finishes ramping.
- Ramping effects can end early or be reversed before completion, and the light will immediately start following the new profile that is commanded.
- To guarantee that a light reaches the 0% or 100% setpoint, the xLights effect must have a duration at least 50ms greater than the ramp duration. Conversely, to guarantee that a light does not fully reach the 0% or 100% setpoint, the xLights effect must have a duration at least 100ms less than the ramp duration.
- Ramping Channels 4-6 have some unique aspects compared to other lights in order to use them effectively - see notes in [Ramping Channels 4-6](#ramping_channels_4_6).

#### Ramping light examples
- Left inner main beam, *Turn on; 2000 ms*, effect duration 1s: causes the light to ramp from 0% to 50% intensity over 1s, then instantly turn off (because of the empty timeline).

    <img src="/images/ramp_example_1.png?raw=true" height="180" />

- Left inner main beam, *Turn on; 2000 ms*, effect duration 4s: causes the light to ramp from 0% to 100% intensity over 2s, then stay at 100% intensity for 2s, then instantly turn off after 4s.

    <img src="/images/ramp_example_2.png?raw=true" height="180" />

- Left inner main beam, *Turn on; 2000 ms* for 2.06s, *Turn off; 2000 ms* for 1.9s, *Turn on; 2000 ms* for 2.06s: causes light to ramp to 100% intensity, then down close to, but not reaching, 0% intensity, then back up to 100% intensity, then instantly turn off.

    <img src="/images/ramp_example_3.png?raw=true" height="180" />

### Full Brightness Control Channels
Some lights on Cybertruck have full brightness control. Their brightness always corresponds to the value set in xLights.
- Place an 'On' Effect using the shortcut _F_. Lights can be set to a steady-state brightness setpoint between 0% and 100% intensity using the 'Brightness' slider in the 'Colors' window.

    <img src="/images/brightness_slider.png?raw=true" width="500" />
    
- Custom ramp durations can be achieved using 'Value Curves'. The menu is opened when clicking the green arrow next to the brightness slider. To create a basic ramp, select 'Ramp' from the drop-down list and set the start/end duration to 0%/100%. The light will reach 0%/100% brightness at the end of the 'On' effect.

  <img src="/images/value_curve.png?raw=true" width="900" />
  
- Value Curves can also be used to create more advanced custom brightness effects. Keep in mind that the maximum brightness is 100.
- On cars without full brightness control, any brightness setting above 50% will set the light to ON and otherwise it will be OFF.

## <a name="light_locations"></a>Light Channel Locations
The following tables and images help show which channels are controlled on each car. Some vehicles have lights that do not exist, or have multiple lights driven by the same control output - see notes in [Light channel mapping details](#light_channel_mapping_details) for this information.
| Light Channel Name | Identifier in image - Model S/X | Identifier in image - Model 3/Y |
| --- | --- | --- |
| Outer Main Beam | 1 | 1 |
| Inner Main Beam | 2 | 2 |
| Signature | 3 | 3 |
| Channel 4 | 4 | 4-6 |
| Channel 5 | 5 | 4-6 |
| Channel 6 | 6 | 4-6 |
| Front Turn | 7 | 7 |
| Front Fog | 8 | 8 |
| Aux Park | 9 | 9 |
| Side Marker | 10 | 10 |

### Model 3/Y with LED reflector lamps
<img src="/images/3_headlights_reflector.png?raw=true" width="900"/><br>

### Model 3/Y with LED projector lamps
<img src="/images/3_headlights_projector.png?raw=true" width="900"/><br>

### Model S with LED reflector lamps
<img src="/images/s_headlights_reflector.png?raw=true" width="900"/><br>

### Model S with LED projector lamps
<img src="/images/s_headlights_projector.png?raw=true" width="900"/><br>

### Model X
<img src="/images/x_headlights.png?raw=true" width="900"/><br>

### Cybertruck

<img src="/images/cybertruck_front.png?raw=true" width="900"/><br>
<img src="/images/cybertruck_rear.png?raw=true" width="900"/><br>
<img src="/images/lightbar_rear.png?raw=true" width="900"/><br>

## <a name="closures"></a>Closures channels
In custom xLights shows, the following closures can be commanded:
| Channel | Model S | Model X | Model 3/Y | Cybertruck | Supports Dance? | Command Limit Per Show |
| --- | --- | --- | --- | --- | --- | --- |
| Liftgate | Yes | Yes | Only vehicles with power liftgate | Yes (Frunk) | Yes | 6 |
| Mirrors | Yes | Yes | Yes | Yes | - | 20 |
| Charge Port | Yes | Yes | Yes | Yes | Yes | 3 |
| Windows | Yes | Yes | Yes | Yes | Yes | 6 |
| Door Handles | Yes | - | - | - | - | 20 |
| Front Doors | - | Yes | - | - | - | 6 |
| Falcon Doors | - | Yes | - | - | Yes | 6 |

To command a closure to move in a particular manner, place an effect with the following keyboard shortcuts:

| Closure Movement | xLights Effect Brightness |
| --- | --- |
| Idle | *empty timeline* |
| Open | Q |
| Dance | A |
| Close | Z |
| Stop | F |

### Definitions for closure movements:
- **Idle:** The closure will stop, unless the closure is in the middle of an Open or Close in which case that movement will finish first.
- **Open:** The closure will open and then stop once fully opened.
- **Dance:** Get your party on! The closure will oscillate between 2 predefined positions. For the charge port, Dance causes the charge port LED to flash in rainbow colors.
- **Close:** The closure will close and then stop once fully closed.
- **Stop:** The closure will immediately stop.

### Other notes
- For closures that do not support Dance, it's recommended to use Open and Close requests to cause movement during the show.
- It's recommended to avoid closing windows during the show so that music stays more audible. Music only plays from the cabin speakers during the show.
- Closures can only dance for a limited time before encountering thermal limits. This depends on multiple factors including ambient temperature, etc. If thermal limits are encountered, the given closure will stop moving until it cools down. Dancing for ~30s or less per show is recommended.
- Moving Windows during Model X door movement can cause false pinch detections, stopping the light show.

### Closures Command Limitations
- All closures have actuation limits listed in the table above. Only Open, Close, and Dance count towards the actuation limits. The limits are counted separately for each individual closure.
- With the exception of windows, closures will not honor Dance requests unless the respective closure is already in the open position. The show creator must account for this by adding a delay between Open and Dance requests. Refer to [Closure Movement Durations](#closure_movement_durations) for more information.
    - Leave margin, not just the listed time. Those durations are approximate and vary between cars, so a Dance placed right at the end of one can arrive while the closure is still moving on a different vehicle. Owners have reported a trunk opening, stopping and closing again from a Dance that cleared the documented time by half a second ([#128](https://github.com/teslamotors/light-show/issues/128)). [vehicle_preview.py](#vehicle_preview) reports a gap with less than 25% margin.
- The charge port door will automatically close if 2 minutes have elapsed since opening.
- Closure commands spaced very close together (eg, 20ms) will not cause much visible movement, and will use up the command limits quickly. Leave reasonable time between commands to see the best effects.
- To count what a finished show actually spends, run the [Vehicle Preview Script](#vehicle_preview). It prints each closure's commands against its limit and flags Dance requests a closure will not honor.

### Closures Command xLights Notes
- For Idle, Open, Close, and Stop, there is no minimum xLights effect duration in order for the command to take effect. For example, the following sequence has a liftgate open command with duration of only 1s ahead of the dance that comes later, and this is sufficient to open the liftgate all the way:

    <img src="/images/open_and_dance.png?raw=true" width="850" />

- For Dance, the xLights effect must persist until the dancing is desired to stop.

### <a name="closure_movement_durations"></a>Closure Movement Durations
| Closure Movement | Approximate Duration (s) |
| --- | --- |
| Open Liftgate | 14 |
| Close Liftgate | 4 |
| Open Front Doors | 22 |
| Close Front Doors | 3 |
| Open Falcon Doors | 20 |
| Close Falcon Doors | 8 |
| Windows | 4 |
| Mirrors, Door Handles, Charge Port | 2 |

These are approximate and owners have reported different times on particular builds. If the timing matters to your show, measure it on the car with [channel_probe.py](#channel_probe) rather than relying on the table.

## Tips for platform-agnostic light shows
### Light channel mapping recommendations
- The [vehicle preview script](#vehicle_preview) reports where a finished show will differ from the xLights preview on each vehicle, which covers most of the cases below automatically.
- Not all vehicles have all types of lights installed. When turning on/off lights in sync with key parts of the music's beat, try to use lights that are installed on all vehicle variants.
- Not all vehicles have individual control over every light. In these cases, multiple xLights channels are OR'd together to decide whether to turn on a given group of lights. These are outlined in the section below.
- For lights that are controlled by multiple OR'd channels, keep in mind that some shared off-time on **all** of the OR'd channels is required to cause an apparent flash of the light.
    - This example will cause Aux Park lights to turn on constantly on Model 3/Y:

        <img src="/images/ord_channel_not_ok.png?raw=true" width="900" />

    - This example will cause the Aux Park lights to flash on Model 3/Y (note the blank time between each box compared to the other example):

        <img src="/images/ord_channel_ok.png?raw=true" width="900" />

### <a name="light_channel_mapping_details"></a>Light channel mapping details
#### <a name="channel_probe"></a>Checking what a channel drives on your car
The tables above are the mapping the show folder uses. If a channel appears to drive a different light on your vehicle, the way to find out is to light the channels one at a time and watch:

```
python3 tools/channel_probe.py probe --group headlights
```

That writes `probe.fseq` and `probe.wav` and prints the order it used:

```
   1. 0:01.000 - 0:04.000   channel   1  Left Outer Main Beam
   2. 0:05.000 - 0:08.000   channel   2  Right Outer Main Beam
   3. 0:09.000 - 0:12.000   channel   3  Left Inner Main Beam
   4. 0:13.000 - 0:16.000   channel   4  Right Inner Main Beam
```

Copy both files into a `LightShow` folder, play the show and film the car; a tone sounds as each channel comes on, so the video lines up with the schedule. `--group lights` walks every light channel, `--channels 1-6` takes an explicit list, and `--include-closures` adds closures - which are left out by default because each one costs an [actuation](#closures) and is left open at the end.

To find out whether two channels drive the same lamp, drive them together with a `+`: `--channels 13,17,13+17` lights the left front turn, then the left aux park, then both at once.

The same probe times a closure: open the liftgate and the video shows how long it takes on that car.

#### Reporting a channel mapping difference
If the probe shows a channel driving something other than its name, please [open an issue](https://github.com/teslamotors/light-show/issues) with the vehicle, its build date and factory, the headlamp type if it is a front light, and the probe schedule next to what you saw.

A confirmed difference is **documented for that vehicle**, not corrected by changing the channel. The mapping from a light to its channel is what every .fseq already exported depends on, so moving one would break existing shows on every car. That is why differences are recorded as notes instead - see [Cybertruck Light Remapping](#cybertruck-light-remapping) and [Tail lights and License Plate Lights](#tail-lights-and-license-plate-lights) for the ones documented so far.

#### Side Markers and Aux Park
- Side markers are only installed in North America vehicles
- Aux park are not installed in Model 3 Standard Range +
- On Model 3/Y, all aux park and side markers operate together. They will activate during ```(Left side marker || Left aux park || Right side marker || Right aux park)``` requests from xLights.
- On Model S, aux park and side markers operate together, but they have independent left/right control. They will activate during the following requests from xLights:
   - Left side: ```(Left side marker || Left aux park)```
   - Right side: ```(Right side marker || Right aux park)```
- Model X is not described above, and one owner report is the only account of it here. On a 2022 Model X Plaid, Front Turn (7) and Aux Park (9) were reported to be the same lamp, lit orange by Front Turn, white by Aux Park, and a dimmer orange-yellow by both together ([#76](https://github.com/teslamotors/light-show/issues/76)). That has not been confirmed on other builds. If you have a Model X, you can check it in about fifteen seconds and say what you see on that issue:

    ```
    python3 tools/channel_probe.py probe --group front-turn-aux-park
    ```

    The probe lights Front Turn on its own, then Aux Park on its own, then both together, so a phone video shows whether they are one lamp or two.

#### <a name="ramping_channels_4_6"></a>Ramping Channels 4-6
- For Model S/X:
    - Individual on/off control is supported for each channel
    - Only a single ramping duration is allowed between all 3 channels.
    - The ramping duration for all 3 is defined only by the effect placed in xLights for Channel 4.
- For Model 3/Y:
    - All 3 of these channels are combined into a single output on the vehicle, see [light channel locations](#light_locations).
    - The on/off state is OR'd together between all 3 channels: ```(Channel 4 || Channel 5 || Channel 6)```.
    - The ramping duration is defined by the effect placed in xLights for Channel 4.
- Because channel 4 acts as the leader for setting ramping duration on all platforms, a ramping effect must sometimes be included on Channel 4 even when Channel 4 is not turned on.
    - In this example, each channel blinks 3x and ramps down after its last blink. Notice how an *Turn Off, 500ms* effect is added always on Channel 4, even when it's Channel 5 or Channel 6 that were turned on.

        <img src="/images/channel_4_6_example.png?raw=true" width="850"/>

    - In this example, Channel 4 & 6 ramp up and ramp down again. Notice how Channel 6 has the *Turn On; Instantly* effect while Channel 4 defines the effect to be *Turn On; 1000ms* for both channels.

        <img src="/images/channel_4_6_example_2.png?raw=true" width="850"/>


#### Front Fog
- Front fog lights are installed in all vehicles except Model 3 Standard Range +.
- Vehicles without front fog lights will not use any other light in place of front fog lights.

#### Rear Fog
- Rear fog lights are installed in non-North America vehicles, and North America Model X.
- Vehicles without rear fog lights will not use any other light in place of rear fog lights.

#### Tail lights and License Plate Lights
- On Model 3 built before October 2020: left tail, right tail, and license plate lights operate together. They will activate during ```(Left tail || Right tail)``` requests from xLights - note that the license plate lights xLights channel will have no effect on these vehicles.

#### Cybertruck Light Bar
- The front light bar has 60 individually controllable LEDs each.
- The rear light bar has 52 individually controllable LEDs each. 
- It's recommended to use xLights' integreated effects to program the light bar. Good ones for getting started are: Curtain, Bars, Marble, Morph and On. Most effects can be customized using the 'Effect Settings' Window. The visualization will display all effects accurately, but keep in mind that the lights are very diffused.

    <img src="/images/xlights_integrated_effects.png?raw=true" width="1000" />

    <img src="/images/effect_settings.png?raw=true" width="500" />
    
- The front light bar is grouped intro three segments: Left, Center, Right. Left/Right are the outer angled portions of the front light bar. The segments can be accessed by double clicking on the light bar in the timeline.

    <img src="/images/lightbar_timeline.png?raw=true" width="900" />
    
- The rear light bar is grouped into the same three segments: Left, Center, Right:
    - The center segment includes all 52 LEDs located on the bed door.
    - In last year's release, 4 LEDs were mistakenly assigned to the left and right segments. These segments are now empty but have been retained for backward compatibility.
        - On a very small amount of exisiting shows, this might generate a "Sequence Element Mismatch" warning when opening them with the updated xLights configuration.
        - You can proceed to open the show by selecting "Delete this element from the sequence".
- Even the individual LEDs can be programmed by double clicking on the segments (Left, Center, Right) in the timeline.

#### Cybertruck Offroad Light Bar
- The offroad light bar is an optional upgrade. Most Cybertrucks won't have them installed.
- The offroad light bar consists of six segments. Two side-facing ditch lights, four forward-facing lights.
- The LEDs can be controlled individually by double clicking the Offroad Light Bar in the timeline, then double clicking 'Strand 1'.

#### Cybertruck Light Remapping
To make old light shows look as good as possible on the new Cybertruck's lights, the following channels are remapped:
- Reverse Lights are activated with L/R Tail in xLights for individual L/R control.
- L/R Rear Side Markers are activated with L/R Side Repeaters in xLights.
- Powered Frunk is activated by Liftgate in xLights.
- Frunk Light is activated by Aux Park in xLights.
- Bed Lights are activated with Reverse Light in xLights.
- L/R Rear Turn Signals have been disabled.

#### <a name="interior_rgb"></a>Interior RGB Lights
- There is full RGB control over the color of the Center Front Display.
    - This visibly lights up the entire interior, even when the show is viewed from outside.
- On cars with Interior Accent Lights, there is full RGB control over each of the five segments:
  - Center Front RGB, L/R Front/Rear RGB
- All Interior RGB Lights, including the screen are grouped into "All Interior RGB".
    - The groups can be expanded by double clicking for individual control over the segments.
    - The Front Display is brighter than the Accent lights. For most effects, it is recommended to operate them together.
- In xLights, recommended effects for RGB effects are: Color Wash, On.
    - Note: By right-clicking on colors in the Color window, custom color curves can be created with the "On"" effect.
- Each segment is three consecutive channels in the exported .fseq - red, green and blue - starting at channel 176:

    | Segment | Channels |
    | --- | --- |
    | Center Front Display | 176-178 |
    | Right Rear RGB | 179-181 |
    | Right Front RGB | 182-184 |
    | Center Front RGB | 185-187 |
    | Left Front RGB | 188-190 |
    | Left Rear RGB | 191-193 |

    - Unlike the light channels, these bytes are not brightness steps. Every value of each component is a meaningful part of the color.
    - A show exported from an older project directory has only 48 channels and no interior data at all. See [Converting old show files](#converting-old-show-files) to bring one forward.
- To see what a finished show does with the cabin, run the [Vehicle Preview Script](#vehicle_preview). It lists every segment with the colors and timings it found, and flags a show that drives only the optional accent segments.

<img src="/images/rgb_interior.png?raw=true" width="800" />

## Converting old show files
Old show files only need to be converted to edit them with the updated xLights configuration. Old light shows can be played without issues on updated Teslas.
All old .xsq and .fseq files are compatible with this light show update.
- On a very small amount of exisiting shows, there might appear a "Sequence Element Mismatch" warning when opening them with the updated xLights configuration.
- You can proceed to open the show by selecting "Delete this element from the sequence".
- This only affects shows which programmed the rear light bar LEDs pixel by pixel.
### Pre-2023 update
All old .xsq and .fseq files are fully compatible with this light show update. You can edit older .xsq files instantly without converting them. Keep in mind that there is no backwards compatibility, once you save them, you won't be able to open them with the old project folder anymore.
### Pre-2022 update
- Create a new folder for the converted project and copy the old audio file over.
- Create a new sequence with the audio file from the new folder.
- Select Import -> Import Effects and choose your old .xsq file.

    <img src="/images/convert_import.png?raw=true" width="500" />

- In "Map Channels" Window, select "Load Mapping" and choose "2022_mapping.xmap" located in the tesla_xlights_show_folder.

    <img src="/images/convert_load_mapping.png?raw=true" width="800" />

- Press "Ok", the old sequence will import. It's recommended to use the "Old View" for working with converted files.

    <img src="/images/convert_old_view.png?raw=true" width="1000" />

- Press "Render All" to see the imported effects in the preview.

    <img src="/images/convert_render_all.png?raw=true" width="300" />

