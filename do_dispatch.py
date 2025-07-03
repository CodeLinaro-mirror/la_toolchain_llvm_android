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
"""Executes build steps for predefined build targets."""

import argparse
import logging

import context  # pylint: disable=unused-import
from llvm_android.target_definitions import TARGET_DEFS
from llvm_android import (utils)

def logger():
    """Returns the module level logger."""
    return logging.getLogger(__name__)

def parse_args():
    # Parses and returns command line arguments.
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dry-run",
        "-d",
        action="store_true",
        default=False,
        help="Runs the script without running the command")
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        default=False,
        help="List defined branches and their targets")
    parser.add_argument(
        "branch",
        nargs="?",
        help="Branch to look for target in")
    parser.add_argument(
        "target",
        nargs="?",
        help="Name of target to build")

    return parser.parse_args()

def main():
    logging.basicConfig(level=logging.DEBUG)
    args = parse_args()
    if args.list:
        for branch_name in TARGET_DEFS:
            print(f"{branch_name}:")
            for target_name in TARGET_DEFS[branch_name]:
                print(f"\t{target_name}")
            print()
    else:
        if args.branch is None or args.target is None:
            raise RuntimeError(f'branch ({args.branch}) or target ({args.target}) are not specified')

        if args.branch not in TARGET_DEFS:
            raise RuntimeError(f'{args.branch} is not a defined branch')

        if args.target not in TARGET_DEFS[args.branch]:
            raise RuntimeError(f'{args.target} is not a defined target for {args.branch}')

        command = TARGET_DEFS[args.branch][args.target]
        logger().info(f'Dispatching Command: {command}')
        if not args.dry_run:
            utils.check_call(command)

if __name__ == "__main__":
    main()