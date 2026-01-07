#
# Copyright (C) 2017 The Android Open Source Project
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

import contextlib
import datetime
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from typing import Dict, List

from llvm_android import constants, paths

ORIG_ENV = dict(os.environ)

def logger():
    """Returns the module level logger."""
    return logging.getLogger(__name__)


def subprocess_run(cmd, *args, **kwargs):
    """subprocess.run with logging."""
    logger().debug('subprocess.run:%s %s',
                  datetime.datetime.now().strftime("%H:%M:%S"),
                  cmd if isinstance(cmd, str) else list2cmdline(cmd))
    if kwargs.pop('dry_run', None):
        return None
    return subprocess.run(cmd, *args, **kwargs, text=True)

def capture_output(cmd, *args, **kwargs):
    """subprocess capture output with logging."""
    return subprocess_run(cmd, *args, **kwargs, capture_output=True).stdout

def unchecked_call(cmd, *args, **kwargs):
    """subprocess.call with logging."""
    return subprocess_run(cmd, *args, **kwargs).returncode


def check_call(cmd, *args, **kwargs):
    """subprocess.check_call with logging."""
    return subprocess_run(cmd, *args, **kwargs, check=True)


def check_output(cmd, *args, **kwargs):
    """subprocess.check_output with logging."""
    return subprocess_run(cmd, *args, **kwargs, check=True, stdout=subprocess.PIPE).stdout


def create_tarball(source_dir, input, output):
    xz_env = os.environ.copy()
    xz_env["XZ_OPT"] = "-T0"
    check_call([
        'tar', '-cJC', str(source_dir),
        '-f', str(output),
        *map(str, input)
    ], env=xz_env)
    # print sha of tarball for debugging
    check_call(['shasum', str(output)])


def extract_tarball(output_dir, input, args=[]):
    xz_env = os.environ.copy()
    xz_env["XZ_OPT"] = "-T0"
    # print sha of tarball for debugging
    check_call(['shasum', str(input)])
    check_call(['tar', '-xC', str(output_dir), '-f', str(input)] + args, env=xz_env)


def is_available_mac_ver(ver: str) -> bool:
    """Returns whether a version string is equal to or under MAC_MIN_VERSION."""
    _parse_version = lambda ver: list(int(v) for v in ver.split('.'))
    return _parse_version(ver) <= _parse_version(constants.MAC_MIN_VERSION)


def list2cmdline(args: List[str]) -> str:
    """Joins arguments into a Bourne-shell cmdline.

    Like shlex.join from Python 3.8, but is flexible about the argument type.
    Each argument can be a str, a bytes, or a path-like object. (subprocess.call
    is similarly flexible.)

    Similar to the undocumented subprocess.list2cmdline, but does Bourne-style
    escaping rather than MSVCRT escaping.
    """
    return ' '.join([shlex.quote(os.fsdecode(arg)) for arg in args])


def create_script(script_path: Path, cmd: List[str], env: Dict[str, str]) -> None:
    with script_path.open('w') as outf:
        outf.write('#!/bin/sh\n')
        for k, v in env.items():
            if v != ORIG_ENV.get(k):
                outf.write(f'export {k}="{v}"\n')
        outf.write(list2cmdline(cmd) + ' "$@"\n')
    script_path.chmod(0o755)


def check_gcertstatus() -> None:
    """Ensure gcert valid for > 1 hour."""
    try:
        check_call([
            'gcertstatus', '-quiet', '-check_ssh=false', '-check_remaining=1h'
        ])
    except subprocess.CalledProcessError:
        print('Run prodaccess before executing this script.')
        raise


@contextlib.contextmanager
def chdir_context(directory):
    prev_dir = os.getcwd()
    try:
        os.chdir(directory)
        yield
    finally:
        os.chdir(prev_dir)


def prebuilt_repo_upload(prebuilt_dir: Path, host: str, topic: str, hashtag: str, is_testing: bool):
    """ Upload CL in a prebuilt clang dir. """
    prebuilt_dir = prebuilt_dir / 'clang' / 'host' / host
    if hashtag:
        hashtag = hashtag + ',' + topic
    else:
        hashtag = topic
    cmd = ['repo', 'upload', '.',
           '--current-branch',
           '--yes', # Answer yes to all safe prompts
           '--verify', # Run upload hooks without prompting.
           '-o', 'uploadvalidator~skip', # Ignore blocked keyword checker
           f'--push-option=topic={topic}',
           f'--hashtag={hashtag}',]
    if is_testing:
        # -2 a testing prebuilt so we don't accidentally submit it.
        cmd.append('--label=Code-Review-2')
    check_output(cmd, cwd=prebuilt_dir)


def clean_out_dir():
    """Delete files from older build (paths.OUT_DIR) but retain paths.OUT_DIR /
    prebuilt_cached, which is input for a chained build.
    """

    for child in paths.OUT_DIR.iterdir():
        if child.name == 'prebuilt_cached':
            continue
        logger().info(f'removing {child} in {paths.OUT_DIR}')
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def check_gsutil():
    cmd = ['gsutil', 'version']
    try:
        subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except FileNotFoundError:
        return False


def check_stubby():
    cmd = ['stubby', '--version']
    try:
        subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except FileNotFoundError:
        return False


def check_tools(use_sha: bool):
    if not check_gsutil():
        print(
            'Fatal: gsutil not installed! Please go to'
            ' https://cloud.google.com/storage/docs/gsutil_install to install'
            ' gsutil',
            file=sys.stderr,
        )
        sys.exit(1)

    if use_sha and not check_stubby():
        print(
            'Fatal: stubby not found. This is only available on gLinux'
            ' (Googlers only). Use --build_id instead',
            file=sys.stderr,
        )
        sys.exit(1)

def prepare_env(android_root: Path, android_target: str) -> Dict[str, str]:
    try:
        env_out = check_output(
            [
                "bash",
                "-c",
                ". ./build/envsetup.sh;lunch " + android_target + " >/dev/null && env",
            ],
            cwd=android_root.resolve(),
        )
    except subprocess.CalledProcessError:
        raise RuntimeError("Failed to lunch " + android_target)

    env: Dict[str, str] = {}
    for line in env_out.splitlines():
        if "=" not in line:
            continue
        (key, _, value) = line.partition("=")
        value = value.strip()
        env[key] = value

    return env


def fetch_artifact(branch: str, target: str, build: str, pattern: str):
    """Fetches artifact from the build server."""
    fetch_artifact_path = '/google/data/ro/projects/android/fetch_artifact'
    cmd = [fetch_artifact_path, f'--branch={branch}',
           f'--target={target}', f'--bid={build}', pattern]
    check_call(cmd)


def get_latest_green_build(branch: str, target: str) -> str:
    """Return the latest green build id."""
    cmd = [
      '/google/data/ro/projects/android/ab',
      'lkgb',
      '--branch',
      branch,
      '--target',
      target,
    ]
    output = check_output(cmd)
    return output.split()[2]

def get_executable_segment_flags(binary_path: Path) -> str:
    """Return the flags of the executable segment of a binary."""
    readelf_path = paths.CLANG_PREBUILT_DIR / 'bin' / 'llvm-readelf'
    try:
        output = check_output([readelf_path, '-lW', binary_path])
        # Match LOAD segments, skip 5 columns (Offset..MemSiz), capture Flags
        # Return the first flag string containing 'E' found, or empty string
        return next((m.group(1).strip()
                     for m in re.finditer(r"^\s*LOAD\s+(?:0x[\da-f]+\s+){5}(.*?)\s+0x",
                     output, re.M | re.I)
                     if 'E' in m.group(1)), "")
    except Exception as e:
        raise RuntimeError(f"Failed to read executable segment flags for {binary_path}: {e}")
