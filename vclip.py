import os
import sys
import argparse
import subprocess
import tempfile
import shutil


DEFAULT_OUTPUT_PATH = os.getcwd()
FFMPEG_BINARY = "/usr/bin/ffmpeg"


def ffmpeg_extract_clip(filename, start_time, end_time, output_path):
    cmd = [FFMPEG_BINARY, "-i", filename, "-y",
           "-ss", "{:0.2f}".format(start_time), "-t", "{:0.2f}".format(end_time - start_time),
           "-async", "1", "-strict", "-2", output_path]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc


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
            raise InvalidTimeIntervalException("Invalid string: must contain at least minutes and seconds (MM:SS)")
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

    def __repr__(self):
        return "{}:{}:{}".format(self.hours, self.minutes, self.seconds)

    @staticmethod
    def parse_time_section(time_section_string, max_=60):
        try:
            time_duration = int(time_section_string)
        except ValueError:
            raise InvalidTimeDurationException("time duration ({}) value not a number".format(time_section_string))
        if time_duration > max_:
            raise InvalidTimeDurationException("time duration value exceeds maximum ({})".format(max_))
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


class TimePointEnd:
    def __init__(self):
        self.seconds = None
        self.minutes = None
        self.hours = None

    def convert_to_seconds(self):
        return None

    def __repr__(self):
        return "End of Video"


class TimeInterval:
    def __init__(self, time_interval_string):
        try:
            start_time, end_time = time_interval_string.split("-")
        except ValueError:
            raise InvalidTimeIntervalException("not a valid time interval")

        self.start_time = TimePoint(start_time)
        if end_time == "end":
            self.end_time = TimePointEnd()
        else:
            self.end_time = TimePoint(end_time)

    def __repr__(self):
        return "{}-{}".format(self.start_time, self.end_time)


# Ensure that intervals do not overlap
def validate_intervals(intervals):
    if intervals:
        current_interval_index = 0
        while current_interval_index < len(intervals)-1:
            current_end = intervals[current_interval_index].end_time
            next_start = intervals[current_interval_index+1].start_time
            print("VALIDATING {} {}".format(current_end, next_start))
            if current_end >= next_start:
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


def clip_video(filename, intervals, output_path):
    intervals = [TimeInterval(interval_string) for interval_string in intervals]
    # Sort by start time to ensure intervals are in chronological order
    intervals = sorted(intervals, key=lambda t: t.start_time.convert_to_seconds())
    print("Intervals to clip {}".format(intervals))
    validate_intervals(intervals)
    tmpdir = tempfile.TemporaryDirectory()
    clips = []
    for i, interval in enumerate(intervals):
        clip_filename = os.path.join(tmpdir.name, "tmp{}.mp4".format(i))
        clips.append(clip_filename)
        proc = ffmpeg_extract_clip(filename, interval.start_time.convert_to_seconds(),
                                   interval.end_time.convert_to_seconds(), clip_filename)
        read_proc_stdout(proc, "Processing subclip {} out of {}".format(i+1, len(intervals)))
    if len(clips) > 1:
        proc = ffmpeg_merge_clips(clips, output_path)
        read_proc_stdout(proc, "Merging subclips")
    else:  # Only one interval parameter was passed so the only clip is the output
        shutil.move(clips[0], output_path)
    print("Result saved to {}".format(output_path))


def display_usage():
    return """
        python3 vclip.py input_video_file_name interval [intervals ...]

        interval format: [HH:]MM:SS-[HH:]MM:SS
                         [HH:]MM:SS-end
    """


def check_file_exists(filepath):
    if not os.path.isfile(filepath):
        print("Invalid file path: {}".format(filepath))
        sys.exit(-1)


def get_input_path(file_path_arg):
    return os.path.abspath(file_path_arg)


def get_output_path(input_path):
    filename = os.path.basename(input_path)
    output_dir = DEFAULT_OUTPUT_PATH
    output_file = filename.lower().replace(" ", "_").replace(".mp4", "_clip.mp4")
    return os.path.join(output_dir, output_file)


def process_arguments(args):
    if not args.input_file:
        print("should error before getting here")
        print(display_usage())
        return False
    if args.interval_file and args.intervals:
        #TODO: pick one to override and just print a warning
        print("Can only accept time interval parameters via command line arguments or file, not both")
        print(display_usage())
        return False
    if args.intervals:
        input_path = get_input_path(args.input_file)
        output_path = get_output_path(input_path)
        check_file_exists(input_path)
        clip_video(input_path, args.intervals, output_path)
    elif args.interval_file:
        print("checking that {} is a legit file and has intervals".format(args.interval_file))
        return "Not supported yet"
    else:
        print("No interval parameters were passed, or intervals file found for {}".format(args.input_file))
        return False


def create_arg_parser():
    arg_parser = argparse.ArgumentParser()
    # The only positional argument is the file name of the source video file to clip
    arg_parser.add_argument("input_file", help="video file to clip")
    arg_parser.add_argument("-i", "--intervals", nargs="*",
                            help="intervals [HH:]MM:SS-[HH:]MM:SS [[HH:]MM:SS-[HH:]MM:SS]")
    arg_parser.add_argument("-f", "--interval_file",
                            help="file containing one interval per line")
    arg_parser.add_argument("-o", "--output_file",
                            help="file path for the resulting video file")
    return arg_parser


def run():
    arg_parser = create_arg_parser()
    process_arguments(arg_parser.parse_args())


class CustomException(Exception):
    def __init__(self, msg):
        print("Error: {}".format(msg))
        sys.exit(1)


class WrongParametersException(CustomException):
    pass


class InvalidTimeDurationException(CustomException):
    pass


class InvalidTimeIntervalException(CustomException):
    pass


if __name__ == "__main__":
    run()
