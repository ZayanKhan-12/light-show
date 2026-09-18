# Requires Python 3.7+
import dataclasses
import struct
import sys
import datetime

class ValidationError(Exception):
    pass

# A sequence's channel count is decided by the xLights show folder it was
# built in, not by the effects in it. tesla_xlights_show_folder defines one
# 200-channel controller; the folder before the 2023 update defined 48. The
# cross-vehicle folder defines one controller per car, so a sequence exported
# straight out of it comes to CARS x 200 channels instead of one car's worth.
#
# The vehicle reports anything else as "Incorrect number of channels", which
# is https://github.com/teslamotors/light-show/issues/65.
VALID_CHANNEL_COUNTS = (48, 200)
CHANNELS_PER_CAR = 200
VEHICLE_ERROR = "Incorrect number of channels"


def describe_channel_count(channel_count):
    """Explain a channel count the vehicle will not accept."""
    lines = [f"Expected 48 or 200 channels, got {channel_count}."]

    cars, remainder = divmod(channel_count, CHANNELS_PER_CAR)
    if remainder == 0 and cars > 1:
        lines.append(
            f"That is {cars} x {CHANNELS_PER_CAR} channels, so this looks like "
            "a cross-vehicle sequence exported as one file. A cross-vehicle "
            "show is exported once per car, importing the sequence with that "
            "car's mapping; see cross-vehicle-shows/README.md, "
            '"Exporting the show".')
    else:
        lines.append(
            "The channel count comes from the xLights show folder the "
            "sequence was built in. The Tesla project folder gives 200, and "
            "the folder from before the 2023 update gave 48. Another number "
            "means the sequence was built against a different layout: check "
            "that your xLights show directory is tesla_xlights_show_folder.")

    lines.append(f'The vehicle reports this as "{VEHICLE_ERROR}".')
    return " ".join(lines)

@dataclasses.dataclass
class ValidationResults:
    frame_count: int
    step_time: int
    duration_s: int

def validate(file):
    """Checks format and length of the provided .fseq file"""
    magic = file.read(4)
    start, minor, major = struct.unpack("<HBB", file.read(4))
    file.seek(10)
    channel_count, frame_count, step_time = struct.unpack("<IIB", file.read(9))
    file.seek(20)
    compression_type, = struct.unpack("<B", file.read(1))

    if (magic != b'PSEQ') or (start < 24) or (frame_count < 1) or (step_time < 15):
        raise ValidationError("Unknown file format, expected FSEQ v2.0")
    if channel_count not in VALID_CHANNEL_COUNTS:
        raise ValidationError(describe_channel_count(channel_count))
    if compression_type != 0:
        raise ValidationError("Expected file format to be V2 Uncompressed")
    duration_s = (frame_count * step_time / 1000)
    if duration_s > 4*60*60:
        raise ValidationError(f"Expected total duration to be less than 4 hours, got {datetime.timedelta(seconds=duration_s)}")
    if ((minor != 0) and (minor != 2)) or (major != 2):
        print("")
        print(f"WARNING: FSEQ version is {major}.{minor}. Only version 2.0 and 2.2 have been validated.")
        print(f"If the car fails to read this file, download an older version of XLights at https://github.com/smeighan/xLights/releases")
        print(f"Please report this message at https://github.com/teslamotors/light-show/issues")
        print("")
   
    return ValidationResults(frame_count, step_time, duration_s)

if __name__ == "__main__":
    # Expected usage: python3 validator.py lightshow.fseq

    # Check if a file argument is provided
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = input("Please enter the path by dragging and dropping the .fseq file: ")
        print("")
        file_path = file_path.strip('"') # Remove surrounding quotes if they exist (Windows)
        file_path = file_path.strip(' ') # Remove spaces (macOS)
        
    with open(file_path, "rb") as file:
        try:
            results = validate(file)
        except ValidationError as e:
            print(e)
            input("Press Enter to exit...")
            sys.exit(1)

    print(f"Found {results.frame_count} frames, step time of {results.step_time} ms for a total duration of {datetime.timedelta(seconds=results.duration_s)}.")
    input("Press Enter to exit...")
