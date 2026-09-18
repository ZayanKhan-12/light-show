# **Running a 4-car show with cross-vehicle animations**

The light shows in this folder use the "Cyber Symphony" music track that is in the Tesla 2024 Holiday Release Light Show.
These 4 shows have been customised to show animations that are coordinated across 4 vehicles such that effects combine to make a unique, unified show.

Each vehicle should be configured to run a scheduled show. See details in the main README.md file on the home page.

The vehicles should be arranged per this illustration:
![Car Setup Graphic](Car_setup.png)

The shows can currently not be edited using the default xLights show folder, and no .xsq ships in this folder.

To read how this show is put together, use the single-car version instead: [../lightshow_example_7_Cyber_Symphony_1_Car.zip](../lightshow_example_7_Cyber_Symphony_1_Car.zip?raw=true) is the same "Cyber Symphony" show arranged for one car and it does include its .xsq. That is the one to open if you are learning the newer mappings, such as the centre screen and the interior RGB segments ([#125](https://github.com/teslamotors/light-show/issues/125)).

If all you have is a .fseq, `tools/fseq_export.py` writes out what it does channel by channel, and `tools/multi_car_check.py` checks a set of per-car shows agrees with itself.

The coordinated show will also work with fewer than 4 vehicles (e.g., 2 vehicles using shows 2 and 3).

### Requirements:
Running Software 2024.44.25.2 (2024 Holiday Release) or newer.
