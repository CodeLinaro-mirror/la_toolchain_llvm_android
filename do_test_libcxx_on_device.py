#!/usr/bin/env python3
#
# Copyright (C) 2025 The Android Open Source Project
#

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
import logging
import subprocess

import context

from llvm_android import paths, utils


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="test_libcxx_on_device.py",
        description="Script to test libcxx/libcxxabi on a user-configured device over ADB",
    )

    parser.add_argument(
        "-s", "--serial", help="Serial of running Android device", required=True
    )

    args = parser.parse_args()

    return args


def main() -> None:
    logging.basicConfig(level=logging.DEBUG)

    args = parse_args()
    serial = args.serial

    try:
        device_supported_abis = (
            utils.check_call(
                ["adb", "-s", serial, "shell", "getprop ro.product.cpu.abilist"],
                capture_output=True,
            )
            .stdout.strip()
            .split(",")
        )

    except subprocess.CalledProcessError as e:
        utils.logger().error(f"Failed to get ABI list for device with serial: {serial}")
        raise e

    target = None

    # acloud supports all abis, but x86_64 is the fastest (most cloudtop hosts are x86_64 and arm must be emulated), so check for it first
    if "x86_64" in device_supported_abis:
        target = "x86_64"
    elif "x86" in device_supported_abis:
        target = "i386"
    elif "arm64-v8a" in device_supported_abis:
        target = "aarch64"
    elif "armeabi-v7a" in device_supported_abis or "armeabi" in device_supported_abis:
        target = "arm"
    # Only other supported target is riscv64

    if target is None:
        utils.logger().error(f"ABI of device is not supported")
        return

    build_path = f"{paths.OUT_DIR}/lib/device-libcxx-{target}"

    utils.check_call(
        ["adb", "-s", serial, "shell", "rm", "-rf", "/data/local/tmp/adb_run"]
    )
    utils.check_call(
        ["adb", "-s", serial, "shell", "rm", "-rf", "/data/local/tmp/libc++"]
    )
    utils.check_call(
        ["adb", "-s", serial, "shell", "mkdir", "-p", "/data/local/tmp/adb_run"]
    )
    utils.check_call(
        [
            "adb",
            "-s",
            serial,
            "push",
            f"{build_path}/lib/libc++.so",
            "/data/local/tmp/libc++/libc++.so",
        ],
    )

    utils.logger().info(f"Testing libcxx and libcxxabi on target device ({build_path})")
    utils.check_call("ninja check-cxx check-cxxabi", shell=True, cwd=build_path)


if __name__ == "__main__":
    main()
