#!/usr/bin/env python3
#
# Copyright (C) 2025 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# pylint: disable=not-callable
"""Update PGO and BOLT profiles."""

import argparse
import contextlib
import glob
import inspect
import logging
import os
import shutil
import sys

import context  # pylint: disable=unused-import
from llvm_android import utils, paths

PGO_PROFILE_PATTERN = 'pgo-*.tar.xz'
BOLT_PROFILE_PATTERN = 'bolt-*.tar.xz'

def logger():
    """Returns the module level logger."""
    return logging.getLogger(__name__)


class ArgParser(argparse.ArgumentParser):
    def __init__(self) -> None:
        super(ArgParser, self).__init__(
            description=inspect.getdoc(sys.modules[__name__]))

        self.add_argument(
            '-b', '--bug', help='Bug to reference in commit message.')

        self.add_argument(
            '--repo-upload', action='store_true',
            help='Upload profiles CL to gerrit using \'repo upload\'')

    def parse_args(self, args=None, namespace=None) -> argparse.Namespace:
        return super().parse_args(args, namespace)


def format_bug(bug):
    """Formats a bug for use in a commit message.

    Bugs might be a number, in which case they're a buganizer reference to be
    formatted. If not, assume the user knows what they're doing and just return
    the string as-is.
    """
    if bug.isnumeric():
        return f'http://b/{bug}'
    return bug


def update_profiles(download_dir, build_number, bug):
    profiles_dir = paths.PREBUILTS_DIR / 'clang' / 'host' / 'linux-x86' / 'profiles'

    with contextlib.chdir(profiles_dir):
        # First, delete the old profiles.
        for f in glob.glob(PGO_PROFILE_PATTERN):
            os.remove(f)
        for f in glob.glob(BOLT_PROFILE_PATTERN):
            os.remove(f)

        # Replace with the downloaded new profiles.
        shutil.copy(glob.glob(f'{download_dir}/{PGO_PROFILE_PATTERN}')[0], '.')
        shutil.copy(glob.glob(f'{download_dir}/{BOLT_PROFILE_PATTERN}')[0], '.')

        utils.check_call(['git', 'add', '.'])
        message_lines = [f'Check in profiles from build {build_number}']
        message_lines.append('')
        if bug is not None:
            message_lines.append(f'Bug: {format_bug(bug)}')
        message_lines.append('Test: N/A')
        message = '\n'.join(message_lines)
        utils.check_call(['git', 'commit', '-m', message])

def main():
    args = ArgParser().parse_args()
    logging.basicConfig(level=logging.DEBUG)

    utils.check_gcertstatus()

    download_dir = os.path.realpath('.download')
    if os.path.isdir(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir)

    os.chdir(download_dir)

    try:
        branch = 'git_main-llvm-toolchain'
        target = 'llvm_linux'
        build_id = utils.get_latest_green_build(branch, target)
        logger().info('Using the latest green build: %s', build_id)
        utils.fetch_artifact(branch, target, build_id, PGO_PROFILE_PATTERN)
        utils.fetch_artifact(branch, target, build_id, BOLT_PROFILE_PATTERN)

        update_profiles(download_dir, build_id, args.bug)

        if args.repo_upload:
            topic = f'profiles-update-{build_id}'
            prebuilt_dir = paths.PREBUILTS_DIR
            host = 'linux-x86'
            utils.prebuilt_repo_upload(prebuilt_dir, host, topic, None, False)

    finally:
        shutil.rmtree(download_dir)

    return 0


if __name__ == '__main__':
    main()
