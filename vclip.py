import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List


DEFAULT_OUTPUT_PATH = os.getcwd()
FFMPEG_BINARY = os.getenv("FFMPEG_PATH")


def ffmpeg_extract_clip(input_path, output_path, start_time, end_time=None):
    cmd = [FFMPEG_BINARY, "-i", input_path, "-y", "-ss", "{:0.2f}".format(start_time)]
    if end_time:
        cmd.extend(["-t", "{:0.2f}".format(end_time - start_time)])
    cmd.extend(["-async", "1", "-strict", "-2", output_path])

    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def ffmpeg_merge_clips(clips, output_path):
    input_params = []
    for clip in clips:
        input_params.append("-i")
        input_params.append(clip)
    filter_param = generate_filter_param(len(clips))
    merge_cmd = [FFMPEG_BINARY]
    merge_cmd.extend(input_params)
    merge_cmd.extend(['-y', '-filter_complex', '{}'.format(filter_param),
                      '-map', '[v]', '-map', '[a]', output_path])
    proc = subprocess.Popen(merge_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc


# Generates argument string for filter parameter in the ffmpeg command to merge clips
#   This is generated dynamically because it depends on the number of clips being merged
def generate_filter_param(number_of_clips):
    parameter = []
    template1 = "[{}:v:0] [{}:a:0]"
    template2 = "concat=n={}:v=1:a=1 [v] [a]"
    [parameter.append(template1.format(n, n)) for n in range(number_of_clips)]
    return " ".join(parameter) + " " + template2.format(number_of_clips)


class TimePoint:
    def __init__(self, time_endpoint_string):
        time_sections = time_endpoint_string.split(":")
        if len(time_sections) < 1 or len(time_sections) > 3:
            raise InvalidTimeIntervalException("Invalid string: must contain at least minutes and seconds ([M]M:SS)")
        # A seconds value is required
        self.seconds = TimePoint.parse_time_section(time_sections[-1])
        # Minutes and hours are optional so initialize to zero then set if present
        self.minutes = 0
        self.hours = 0
        if len(time_sections) >= 2:
            self.minutes = TimePoint.parse_time_section(time_sections[-2])
        if len(time_sections) == 3:
            self.hours = TimePoint.parse_time_section(time_sections[0])

    def convert_to_seconds(self):
        return self.seconds + (self.minutes * 60) + (self.hours * 60 * 60)

    @staticmethod
    def parse_time_section(time_section_string, max_=60):
        try:
            time_duration = int(time_section_string)
        except ValueError:
            raise InvalidTimeDurationException(f"Value ({time_section_string}) is not a number")
        if not (0 <= time_duration <= max_):
            raise InvalidTimeDurationException(f"Value must be between 0 and ({max_})")
        return time_duration

    def __lt__(self, other_time_point):
        return self.convert_to_seconds() < other_time_point.convert_to_seconds()

    def __gt__(self, other_time_point):
        return self.convert_to_seconds() > other_time_point.convert_to_seconds()

    def __le__(self, other_time_point):
        return self.convert_to_seconds() <= other_time_point.convert_to_seconds()

    def __ge__(self, other_time_point):
        return self.convert_to_seconds() >= other_time_point.convert_to_seconds()

    def __eq__(self, other_time_point):
        return self.convert_to_seconds() == other_time_point.convert_to_seconds()

    def __repr__(self):
        return "{:02d}:{:02d}:{:02d}".format(self.hours, self.minutes, self.seconds)


class TimeInterval:
    def __init__(self, time_interval_string: str):
        if "-" in time_interval_string:
            start_time, end_time = time_interval_string.split("-")
        else:
            start_time = time_interval_string
            end_time = None

        self.start_time = TimePoint(start_time)
        self.end_time = TimePoint(end_time) if end_time else None

    def __len__(self):
        if self.end_time:
            return self.end_time.convert_to_seconds() - self.start_time.convert_to_seconds()
        return 0

    def __repr__(self):
        if not self.end_time:
            return "{}".format(self.start_time)
        return "{}-{}".format(self.start_time, self.end_time)


# Ensure that intervals do not overlap
def validate_intervals(intervals):
    if intervals:
        current_interval_index = 0
        while current_interval_index < len(intervals)-1:
            current_end = intervals[current_interval_index].end_time
            next_start = intervals[current_interval_index+1].start_time
            if current_end and current_end >= next_start:
                raise InvalidTimeIntervalException("Time intervals overlap")
            current_interval_index += 1


def read_proc_stdout(proc, message=None):
    if message:
        print(message)
    while True:
        # Reading stderr and not stdout because that's where ffmpeg is writing its output to
        line = proc.stderr.readline()
        if line == b'' and proc.poll() is not None:
            break


def clip_video(filename: Path, intervals: List[TimeInterval], output_path: Path):
    intervals = sorted(intervals, key=lambda t: t.start_time.convert_to_seconds())
    print("Intervals to clip {}".format(intervals))

    validate_intervals(intervals)

    tmpdir = tempfile.TemporaryDirectory()
    clips = []
    for i, interval in enumerate(intervals):
        clip_filename = Path(f"{tmpdir.name}/tmp{i}{filename.suffix}")
        clips.append(clip_filename.absolute())
        proc = ffmpeg_extract_clip(
            filename,
            clip_filename,
            interval.start_time.convert_to_seconds(),
            interval.end_time.convert_to_seconds() if interval.end_time else None
        )
        read_proc_stdout(proc, "Processing subclip {} out of {}".format(i+1, len(intervals)))
    # If there are multiple clips, merge them
    # TODO: should make this optional (--merge defaulting to True)
    if len(clips) > 1:
        proc = ffmpeg_merge_clips(clips, output_path)
        read_proc_stdout(proc, "Merging subclips")
    else:  # Only one interval parameter was passed so the only clip is the output
        shutil.move(clips[0], output_path)
    print("Result saved to {}".format(output_path))


def display_usage():
    return """
        python3 vclip.py input_video_file_name interval [intervals ...]

        interval format: [HH:][M]M:SS-[HH:][M]M:SS
                         [HH:][M]M:SS
    """


def get_input_path(file_path_arg):
    input_path = Path(file_path_arg).absolute()
    if not input_path.exists():
        raise InputFileNotFoundException(f"Invalid path: {input_path}")
    return input_path


def get_output_path(input_path, output_path=DEFAULT_OUTPUT_PATH):
    filename = Path(input_path)
    output_dir = Path(output_path)
    extension = filename.suffix
    output_file = filename.name.lower().replace(" ", "_").replace(extension, f"_clip{extension}")
    return Path(f"{output_dir.name}/{output_file}").absolute()


def intervals_argument(interval_argument: str) -> TimeInterval:
    return TimeInterval(interval_argument)


def process_arguments(args):
    if args.intervals:
        input_path = get_input_path(args.input_file)
        output_path = get_output_path(input_path, args.output_file)
        clip_video(input_path, args.intervals, output_path)
    elif args.interval_file:
        return "Not supported yet"
    else:
        print("No interval parameters were passed, or intervals file found for {}".format(args.input_file))
        return False


def create_arg_parser():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("input_file", help="video file to clip")
    group = arg_parser.add_mutually_exclusive_group()
    group.add_argument(
        "-i",
        "--intervals",
        nargs="+",
        type=intervals_argument,
        help="intervals [HH:]MM:SS-[HH:]MM:SS [[HH:]MM:SS-[HH:]MM:SS]"
    )
    group.add_argument("-f", "--interval_file", nargs="?", help="file containing one interval per line")
    arg_parser.add_argument("-o", "--output_file", nargs="?", default=".",
                            help="file path for the resulting video file")
    return arg_parser


class ApplicationException(Exception):
    def __init__(self, msg=None):
        print(f"{self.__class__.__name__} {'- ' + msg if msg else ''}")
        sys.exit(1)


class InputFileNotFoundException(ApplicationException):
    pass


class WrongParametersException(ApplicationException):
    pass


class InvalidTimeDurationException(ApplicationException):
    pass


class InvalidTimeIntervalException(ApplicationException):
    pass


class MissingFfmpegLocation(ApplicationException):
    pass


def _validate_ffmpeg_path():
    if FFMPEG_BINARY and pathlib.Path(FFMPEG_BINARY).exists():
        return True
    raise MissingFfmpegLocation


def run():
    _validate_ffmpeg_path()
    arg_parser = create_arg_parser()
    try:
        process_arguments(arg_parser.parse_args())
    except Exception as e:
        print(e)
        sys.exit(1)


if __name__ == "__main__":
    run()
