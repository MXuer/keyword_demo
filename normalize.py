# encoding: utf-8

'''

@author: ZiqiLiu


@file: normalize.py

@time: 2017/6/26 上午10:19

@desc:
'''

# !/usr/bin/env python

import subprocess
import os
import re
import sys
import logging

import argparse


# -------------------------------------------------------------------------------------------------

logger = logging.getLogger('ffmpeg_normalize')
logger.setLevel(logging.DEBUG)

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.ERROR)

formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)


# -------------------------------------------------------------------------------------------------

def which(program):

    def is_exe(fpath):
        found = os.path.isfile(fpath) and os.access(fpath, os.X_OK)
        if not found and sys.platform == 'win32':
            fpath = fpath + ".exe"
            found = os.path.isfile(fpath) and os.access(fpath, os.X_OK)
        return found

    fpath, _ = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None


def run_command(cmd, raw=True):
    logger.info(cmd)
    """
    Generic function to run a command.
    Set raw to pass the actual command.
    Set dry to just print and don't actually run.

    Returns stdout + stderr.
    """
    logger.debug("[command] {0}".format(cmd))

    if raw:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, shell=True,
                             universal_newlines=True)
    else:
        p = subprocess.Popen(cmd.split(" "), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True)

    stdout, stderr = p.communicate()

    if p.returncode == 0:
        return (stdout + stderr)
    else:
        logger.error("error running command: {}".format(cmd))
        logger.error(str(stderr))
        raise SystemExit("Failed running a command")


# -------------------------------------------------------------------------------------------------

class InputFile(object):
    """
    Class that holds a file, its streams and adjustments
    """

    def __init__(self, path, args):
        self.args = args
        self.write_to_dir = self.args['dir'] is not None
        self.extra_options = self.args['extra_options']
        self.force = self.args['force'] is not None
        self.max = self.args['max'] is not None
        self.ebu = self.args['ebu'] is not None
        self.format = self.args['format']
        self.prefix = self.args['prefix']
        self.target_level = float(self.args['level'])
        self.threshold = float(self.args['threshold'])

        # Find ffmpeg command in PATH
        self.ffmpeg_cmd = which('ffmpeg')
        if not self.ffmpeg_cmd:
            if which('avconv'):
                logger.error(
                    "avconv is not supported anymore. Please install ffmpeg from http://ffmpeg.org instead.")
                raise SystemExit("No ffmpeg installed")
            else:
                raise SystemExit("Could not find ffmpeg in your $PATH")

        if self.max and self.ebu:
            raise SystemExit("Either --max or --ebu have to be specified.")

        if self.ebu and (
                    (self.target_level > -5.0) or (self.target_level < -70.0)):
            raise SystemExit(
                "Target levels for EBU R128 must lie between -70 and -5")

        self.skip = False  # whether the file should be skipped

        self.mean_volume = None
        self.max_volume = None
        self.adjustment = None
        self.hist = []
        self.main_volume = None

        self.input_file = path
        self.dir, self.filename = os.path.split(self.input_file)
        self.basename = os.path.splitext(self.filename)[0]

        # by default, the output path is the same as the input file's one
        self.output_file = None
        self.output_filename = None
        self.output_dir = self.dir

        self.set_output_filename()

    def set_output_filename(self):
        """
        Set all the required output filenames and paths
        """

        # by default, output filename is the input filename, plus the format chosen (default: WAV)
        self.output_filename = os.path.splitext(self.filename)[
                                   0] + "." + self.format

        # if writing to a directory, change the output path by using the prefix
        if self.write_to_dir:
            self.output_dir = os.path.join(self.dir, self.prefix)
        else:
            # if not, the output filename is prefixed (this is the default behavior)
            self.output_filename = self.prefix + "-" + self.output_filename

        # create the output dir if necessary
        if self.output_dir and not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        # create the actual file path for the output file
        self.output_file = os.path.join(self.output_dir, self.output_filename)

        logger.debug("writing result in " + self.output_file)

        if self.output_file == self.input_file:
            raise SystemExit(
                "output file is the same as input file, cannot proceed")

        # some checks
        if not self.force and os.path.exists(self.output_file):
            logger.warning(
                "output file " + self.output_file + " already exists, skipping. Use -f to force overwriting.")
            self.skip = True

    def get_mean(self):
        """
        Use ffmpeg with volumedetect filter to get the mean volume of the input file.
        """
        if sys.platform == 'win32':
            nul = "NUL"
        else:
            nul = "/dev/null"

        cmd = '"' + self.ffmpeg_cmd + '" -i "' + self.input_file + '" -filter:a "volumedetect" -vn -sn -f null ' + nul

        output = run_command(cmd)
        logger.info(output)
        logger.debug(output)

        mean_volume_matches = re.findall(r"mean_volume: ([\-\d\.]+) dB", output)
        if mean_volume_matches:
            self.mean_volume = float(mean_volume_matches[0])
        else:
            raise ValueError("could not get mean volume for " + self.input_file)

        max_volume_matches = re.findall(r"max_volume: ([\-\d\.]+) dB", output)
        if max_volume_matches:
            self.max_volume = float(max_volume_matches[0])
        else:
            raise ValueError("could not get max volume for " + self.input_file)

        hist = re.findall(r"(histogram_([\d]+)db: ([\-\d\.]+))", output)
        self.hist = [(float(i[1]), float(i[2])) for i in hist]
        self.hist = sorted(self.hist, key=lambda a: a[0])

        for h in self.hist:
            if h[1] > 3:
                self.main_volume = -h[0]
                break

        logger.info("mean volume: " + str(self.mean_volume))
        logger.info("max volume: " + str(self.max_volume))

    def set_adjustment(self):
        """
        Set the adjustment gain based on chosen option and mean/max volume
        """
        if self.max:
            self.adjustment = 0 + self.target_level - self.max_volume
            logger.info("file needs " + str(
                self.adjustment) + " dB gain to reach maximum")
        else:
            self.adjustment = self.target_level - self.main_volume
            logger.info('main volume peak at %f dB' % self.main_volume)
            logger.info("file needs " + str(
                self.adjustment) + " dB gain to reach target main volume " + str(
                self.target_level) + " dB")

        if self.max_volume + self.adjustment > 0:
            logger.info(
                "adjusting " + self.filename + " will lead to clipping of " + str(
                    self.max_volume + self.adjustment) + "dB")
        if self.adjustment < self.threshold:
            logger.info("gain of " + str(
                self.adjustment) + " is below threshold, will not adjust file")
            self.skip = True

    def adjust_volume(self):
        """
        Apply gain to the input file and write to the output file or folder.
        """
        if self.skip:
            logger.error("Cannot run adjustment, file should be skipped")

        cmd = '"' + self.ffmpeg_cmd + '" -y -i "' + self.input_file + '" '

        if self.ebu:
            chosen_filter = 'loudnorm=' + str(self.target_level) + ' '
        else:
            chosen_filter = 'volume=' + str(self.adjustment) + 'dB '

        # when outputting a file, disable video and subtitles
        cmd += '-vn -sn -filter:a ' + chosen_filter

        # any extra options passed to ffmpeg
        if self.extra_options:
            cmd += self.extra_options + ' '

        cmd += '"' + self.output_file + '"'

        run_command(cmd)


class FFmpegNormalize(object):
    """
    ffmpeg-normalize class.
    """

    def __init__(self, args):
        # Set arguments
        self.args = args
        print(args)
        self.debug = self.args['debug'] is not None
        self.verbose = self.args['verbose'] is not None

        if self.debug:
            stream_handler.setLevel(logging.DEBUG)
        elif self.verbose:
            stream_handler.setLevel(logging.INFO)

        logger.debug(self.args)

        # Checks
        self.input_files = []
        if self.args['input_file'] is None:
            raise ('no input file')
        self.create_input_files(self.args['input_file'])

    def create_input_files(self, input_files):
        """
        Remove nonexisting input files
        """
        to_remove = []

        for input_file in input_files:
            if not os.path.exists(input_file):
                logger.error(
                    "file " + input_file + " does not exist, will skip")
                to_remove.append(input_file)

        for input_file in to_remove:
            input_files = [f for f in self.input_files if f != input_file]

        self.file_count = len(input_files)

        for input_file in input_files:
            self.input_files.append(InputFile(input_file, self.args))

    def run(self):
        """
        Run the normalization procedures
        """
        count = 0
        for input_file in self.input_files:
            count = count + 1

            if input_file.skip:
                continue

            logger.info("reading file " + str(count) + " of " + str(
                self.file_count) + " - " + input_file.filename)

            if self.args["ebu"] is None:
                input_file.get_mean()
                input_file.set_adjustment()

            input_file.adjust_volume()
            logger.info("normalized file written to " + input_file.output_file)


# -------------------------------------------------------------------------------------------------

def main():
    # parser = argparse.ArgumentParser()
    #
    # parser.add_argument('-l', '--level',
    #                     help='dB level to normalize to [default: -26]',
    #                     default=-26, type=float)
    # parser.add_argument('-b', '--ebu', nargs='*',
    #                     help='Normalize according to EBU R128 (ffmpeg `loudnorm` filter)')
    # parser.add_argument('-m', '--max', nargs='*',
    #                     help='Normalize to the maximum (peak) volume instead of RMS')
    # parser.add_argument('-t', '--threshold',
    #                     help='dB threshold below which the audio will be not adjusted [default: 0.5]',
    #                     type=float,
    #                     default=0)
    # parser.add_argument('-e', '--extra-options',
    #                     help='Set extra options passed to ffmpeg (e.g. `-b:a 192k` to set audio bitrate)')
    # parser.add_argument('-f', '--force', nargs='*',
    #                     help='Force overwriting existing files')
    # parser.add_argument('-p', '--prefix',
    #                     help='Prefix for normalized files or output folder name [default: normalized]')
    # parser.add_argument('-o', '--dir', nargs='*',
    #                     help="Create an output folder under the input file's directory with the prefix")
    # parser.add_argument('-v', '--verbose', nargs='*',
    #                     help='Enable verbose output')
    # parser.add_argument('-d', '--debug', nargs='*',
    #                     help='Show debug output')
    # parser.add_argument('-i', '--input_file', nargs='*',
    #                     help='input')
    # parser.add_argument('--format', default='wav',
    #                     help='format [default:wav')
    # args = parser.parse_args().__dict__

    args = {'level': -4.0,
            'ebu': None,
            'max': None,
            'threshold': 0,
            'extra_options': '-ar 16000',
            'force': [],
            'prefix': 'normalized',
            'dir': None,
            'verbose': 0,
            'debug': None,
            'input_file': ['temp.wav'],
            'format': 'wav'}
    # print(args)
    ffmpeg_normalize = FFmpegNormalize(args)
    ffmpeg_normalize.run()


if __name__ == '__main__':
    # read temp.wav from current dir and output normalized-temp.wav
    main()
