#!/usr/bin/env python3
#
# Copyright (C) 2024 The Android Open Source Project
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

import argparse
import sys
from typing import List, Optional
from fetch_kokoro_prebuilts import check_valid_build, check_valid_path, fetch_prebuilts, get_build_number
from utils import check_tools


def parse_args(sys_argv: Optional[List[str]]):
    """Parse the command line arguments."""

    parser = argparse.ArgumentParser(description="Fetch prebuilts from kokoro.")

    parser.add_argument("good", type=str, nargs=1, help="good SHA")
    parser.add_argument("bad", type=str, nargs=1, help="bad SHA")
    parser.add_argument(
        "target",
        type=str,
        nargs=1,
        help="Target Clang path (e.g. ANDROID_TOP/prebuilts/clang/linux-x86/)",
    )
    return parser.parse_args(sys_argv)


def get_result(num: str):
    """Testing the build manually and get the result from users."""
    print(f"\nTesting build {num}...")
    res = input("Is build " + num + " a good build?  [y/n]:")
    while res != "y" and res != "n":
        res = input("Please enter y or n:")
    return res


def bisect(start: int, end: int, target: str):
    """Find the build number which might be the root cause by bisection.

    Users need to verify manually. If it is a good build, enter 'y'.
    Otherwise, enter 'n'. After narrowing the range repeatedly, the
    possible root cause will be found.

    Args:
        start: the build id which is a good build.
        bad: the build id which is a bad build.
        target: the target path to download the prebuilts.

    Returns:
        The build number combo that might be the culprit(s).
    """
    if start >= end - 1:
        return (end, end)
    mid = (start + end) // 2
    result = fetch_prebuilts(str(mid), target)
    if result:
        res = get_result(str(mid))
        if res == "y":
            return bisect(mid, end, target)
        else:
            return bisect(start, mid, target)
    else:
        # Mid point build is broken, find the neighbouring good build
        left = mid - 1
        while start < left:
            result = fetch_prebuilts(str(left), target)
            if result:
                break
            left = left - 1

        right = mid + 1
        while right < end:
            result = fetch_prebuilts(str(right), target)
            if result:
                break
            right = right + 1

        if start == left:
            if end != right:
                res = get_result(str(right))
                if res == "y":
                    return bisect(right, end, target)
            return (left + 1, right)

        else:
            res = get_result(str(left))
            if res == "y":
                if end == right:
                    return (left + 1, end)
                else:
                    res = get_result(str(right))
                    if res == "y":
                        return bisect(right, end, target)
                    else:
                        return (left + 1, right)
            else:
                return bisect(start, left, target)


def main(sys_argv: List[str]):
    check_tools(True)
    args_output = parse_args(sys_argv)

    good = get_build_number(args_output.good[0])
    bad = get_build_number(args_output.bad[0])
    target = args_output.target[0]

    check_valid_path(target)
    check_valid_build(good)
    check_valid_build(bad)

    start = int(good)
    end = int(bad)

    if start >= end:
        err_msg = (
            f"{good} is not smaller than {bad}. Please pass a valid combo."
        )
        raise Exception(err_msg)

    result = bisect(start, end, target)
    if result[0] == result[1]:
        print(f"The culprit is build {result[0]}.")
    else:
        print(
            f"The culprit is in the range from build {result[0]} to"
            f" {result[1]}."
        )


if __name__ == "__main__":
    main(sys.argv[1:])
