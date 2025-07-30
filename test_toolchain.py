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

from datetime import datetime
import enum
import sys
from typing import Any, Dict
from pathlib import Path
import time
import subprocess

import context  # pylint: disable=unused-import
from llvm_android import utils


def prepare_env(android_root_path: Path, android_target: str) -> Dict[str, str]:
    # TODO(tynasello), this logic exists in test_compiler. Can factor out into utils module.
    env: Dict[str, str] = {}
    try:
        env_out = utils.check_output(
            [
                "bash",
                "-c",
                f". ./build/envsetup.sh;lunch {android_target} >/dev/null;env",
            ],
            cwd=android_root_path.resolve(),
        )
    except subprocess.CalledProcessError:
        raise RuntimeError("Failed to lunch " + android_target)
    for line in env_out.splitlines():
        if not line:
            continue
        (key, _, value) = line.partition("=")
        value = value.strip()
        env[key] = value
    return env


class AndroidTarget:
    """
    A class representing an Android build environment.
    The target field is used for lunching. The resulting environemnt is captured in the env field for further use.
    """

    def __init__(self, target: str, android_root: Path):
        self.target = target
        self.android_root = android_root
        self.env = prepare_env(android_root, self.target)

    def get_board_type(self) -> str:
        # Additional edge cases may be needed here
        return self.target.split("-")[0]

    def to_dict(self) -> Dict[str, str]:
        return {"target": self.target, "android_root": str(self.android_root)}


class Dut:
    """
    Device Under Test (DUT)

    A Dut must have an Android target to build and use tests/benchmarks for the
    correct target image. For example, CTS is built through m, which requires
    the target being build for to be lunched.

    Through calling setup methods a DUT will be modified to have a host name
    (for tracking with lab), and an ADB serial (for remote control).
    """

    class DutError(Exception):
        pass

    MAX_REBOOT_WAIT_S = 300

    def __init__(self, android_target: AndroidTarget, host_name: str | None = None):
        self.android_target = android_target
        self.host_name = host_name
        self.adb_serial: str | None = None
        self.is_flashed = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "android_target": self.android_target.to_dict(),
            "host_name": self.host_name,
            "adb_serial": self.adb_serial,
            "is_flashed": self.is_flashed,
        }

    @classmethod
    def local(
        cls,
        android_target: AndroidTarget,
        adb_serial: str,
    ) -> "Dut":
        """
        Create a DUT representing a local device (ADB serial is already known).
        """
        dut = cls(android_target)
        dut.adb_serial = adb_serial
        return dut

    @staticmethod
    def get_board_type(adb_serial: str) -> str:
        """
        Returns board name of device available over provided ADB serial.
        - Should be a universal name, e.g. brya.
        May raise exception.
        """
        return utils.check_output(
            [
                "adb",
                "-s",
                adb_serial,
                "shell",
                "getprop ro.product.name",
            ],
        ).strip()

    def get_abi(self) -> str:
        """
        Returns ABI of device. Device must be available over ADB.
        - ABI is one of x86_64, x86, arm64-v8a, armeabi-v7a, armeabi, riscv64.
        May raise exception.
        """
        if self.adb_serial is None:
            raise Dut.DutError(
                "Could not get ABI for device because it is not available over ADB."
            )
        return utils.check_output(
            [
                "adb",
                "-s",
                self.adb_serial,
                "shell",
                "getprop ro.product.cpu.abi",
            ],
        ).strip()

    def is_ready_to_test(self) -> bool:
        return self.adb_serial is not None and self.is_flashed

    def create_adb_connection_over_ssh(self, android_root: Path):
        """
        Create an ADB connection over SSH for device by using it's host name.
        May raise exception.
        """
        if self.host_name is None:
            raise Dut.DutError(
                "Could not create ADB connection over SSH for device because no host"
                " name is set."
            )

        utils.check_call(
            [
                (
                    android_root
                    / "tools/vendor/google_prebuilts/arc/corp-adb-helper.py"
                ).resolve(),
                "-f",
                "-j",
                "ssh-dev-e-cr",
                self.host_name,
            ],
        )

        for device_output in utils.check_output(["adb", "devices"]).splitlines()[1:]:
            if device_output is None:
                continue
            dut_serial, _ = device_output.split()
            if self.host_name in dut_serial:
                self.adb_serial = dut_serial
                return

        raise Dut.DutError(
            "Could not create ADB connection for device using host name"
            f" {self.host_name}."
        )

    def remove_adb_connection(self):
        """
        Remove ADB connection of device.
        May throw exception
        """
        if self.adb_serial is None:
            raise Dut.DutError(
                "Could not remove ADB connection for device because it is not"
                " available over ADB."
            )
        utils.check_call(["adb", "disconnect", self.adb_serial])

    def flash(self, ota_image_path: Path):
        """
        Flash the device over ADB using the provided over-the-air (OTA) image and reboot the device.
        May throw exception.
        """
        if self.adb_serial is None:
            raise Dut.DutError(
                "Could not flash device because it is not available over ADB."
            )

        utils.check_call(
            [
                sys.executable,
                (
                    self.android_target.android_root
                    / "system/update_engine/scripts/update_device.py"
                ).resolve(),
                "-s",
                self.adb_serial,
                ota_image_path,
            ],
        )

        self.reboot()

    def root_adb(self):
        """
        Root the device ADB connection. This is needed to run some commands of interest.
        May raise exception.
        """
        if self.adb_serial is None:
            raise Dut.DutError(
                "Could not root device because it is not available over ADB."
            )
        utils.check_call(["adb", "-s", self.adb_serial, "root"])

    def reboot(self):
        """
        Reboot device and use an exponential backoff while waiting for device to come back online
        (with a max accumulated wait time of Dut.MAX_REBOOT_WAIT_S seconds).
        May raise exception.
        """
        if self.adb_serial is None:
            raise Dut.DutError(
                "Could not reboot device because it is not available over ADB."
            )

        utils.check_call(
            ["adb", "-s", self.adb_serial, "reboot"],
        )

        retry_count = 0
        delay_s = 3
        delay_s_acc = 0

        while delay_s_acc < Dut.MAX_REBOOT_WAIT_S:
            devices_output = utils.check_output(
                ["adb", "devices"],
            )
            for device_output in devices_output.splitlines()[1:]:
                if not device_output:
                    continue
                dut_serial, dut_status = device_output.split()
                if dut_serial == self.adb_serial and dut_status == "device":
                    self.is_flashed = True
                    return

            utils.logger().info(
                f"Attempt {retry_count + 1} at rebooting device: Device is still"
                f" offline, retrying in {delay_s} seconds..."
            )
            time.sleep(delay_s)

            delay_s_acc += delay_s
            delay_s *= 2
            retry_count += 1

        raise Dut.DutError(
            "Device did not come back online after rebooting. Not waiting any longer."
        )


class TestType(enum.Enum):
    """
    Enum of supported tests/benchamrks.
    """

    CTS_BIONIC = "CTS_BIONIC"
    CTS_LIBCORE = "CTS_LIBCORE"
    GEEKBENCH = "GEEKBENCH"
    BENCH_BIONIC = "BENCH_BIONIC"
    BENCH_LIBCORE = "BENCH_LIBCORE"


# Test type groupings
CTS = set([TestType.CTS_BIONIC, TestType.CTS_LIBCORE])
NATIVE_ANDROID_BENCHMARKS = set(
    [
        TestType.BENCH_BIONIC,
        TestType.BENCH_LIBCORE,
    ]
)


class TestToolchainError(Exception):
    pass


TMP_RESULTS_DIR = Path("/tmp/toolchain-test-results-raw")


class TestRunner:
    """
    Implementations for executing each supported test type.
    - Can expect that each method may throw an exception.
    """

    @staticmethod
    def run_cts(
        dut: Dut,
        test_type: TestType,
        package: str,
    ):
        if test_type not in CTS:
            raise TestToolchainError(
                f"The provided test {test_type} is not a supported CTS test."
            )
        # May want to output results as they become available.
        out = utils.capture_output(
            ["atest", "-s", dut.adb_serial, package],
            cwd=dut.android_target.android_root.resolve(),
            env=dut.android_target.env,
        )
        # Unideal, but cannot find another way to set or find outputted result file.
        results_file = Path(out.splitlines()[0].split(" ")[-1]) / "test_result"

    @staticmethod
    def run_bionic_cts(dut: Dut):
        TestRunner.run_cts(dut, TestType.CTS_BIONIC, "CtsBionicTestCases")

    @staticmethod
    def run_libcore_cts(dut: Dut):
        TestRunner.run_cts(dut, TestType.CTS_LIBCORE, "CtsLibcoreTestCases")

    @staticmethod
    def run_geekbench(dut: Dut, bin_dir_path: Path):
        abi = dut.get_abi()
        match abi:
            case "x86_64":
                exe_name = "geekbench_x86_64"
            case "arm64-v8a":
                exe_name = "geekbench_aarch64"
            case _:
                raise TestToolchainError(
                    f"Geekbench is not supported for device's ABI {abi}."
                )
        geekbench_files = [
            bin_dir_path / "geekbench.plar",
            bin_dir_path / "geekbench-workload.plar",
            bin_dir_path / exe_name,
        ]
        for file in geekbench_files:
            if not file.exists():
                raise TestToolchainError(
                    "Could not find required geekbench binaries (specifically,"
                    f" {file} could not be found)."
                )
        on_device_bin_dir_path = Path("/data/local/tmp/geekbench")
        results_file_name = f'{TestType.GEEKBENCH.name}-{datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}.json'
        on_device_results_path = Path("/data/local/tmp") / results_file_name

        utils.check_call(
            [
                "adb",
                "-s",
                dut.adb_serial,
                "shell",
                "mkdir",
                "-p",
                on_device_bin_dir_path,
            ]
        )
        utils.check_call(
            [
                "adb",
                "-s",
                dut.adb_serial,
                "push",
                *[path.resolve() for path in geekbench_files],
                on_device_bin_dir_path,
            ],
        )
        utils.check_call(
            [
                "adb",
                "-s",
                dut.adb_serial,
                "shell",
                "chmod",
                "u+x",
                on_device_bin_dir_path / exe_name,
            ],
        )
        utils.subprocess_run(
            [
                "adb",
                "-s",
                dut.adb_serial,
                "shell",
                "--",
                on_device_bin_dir_path / exe_name,
                "--no-upload",
                "--save",
                on_device_results_path,
            ],
        )
        utils.check_call(
            [
                "adb",
                "-s",
                dut.adb_serial,
                "pull",
                on_device_results_path,
                TMP_RESULTS_DIR.resolve(),
            ]
        )
        utils.check_call(
            [
                "adb",
                "shell",
                "rm",
                "-rf",
                on_device_bin_dir_path,
                on_device_results_path,
            ]
        )

    @staticmethod
    def run_native_android_benchmark(
        dut: Dut,
        test_type: TestType,
        module: str,
        on_device_bin: Path,
    ):
        if test_type not in NATIVE_ANDROID_BENCHMARKS:
            raise TestToolchainError(
                f"The provided test {test_type} is not a supported native Android"
                " benchmark."
            )
        utils.check_call(
            ["mmma", module],
            cwd=dut.android_target.android_root.resolve(),
            env=dut.android_target.env,
        )
        utils.check_call(
            ["adb", "-s", dut.adb_serial, "sync", "data"],
            cwd=dut.android_target.android_root.resolve(),
            env=dut.android_target.env,
        )
        results_file_name = (
            f'{test_type.name}-{datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}.json'
        )
        on_device_results_path = Path("/data/local/tmp") / results_file_name
        utils.subprocess_run(
            [
                "adb",
                "-s",
                dut.adb_serial,
                "shell",
                on_device_bin,
                "--",
                f"--benchmark_out={on_device_results_path}",
                "--benchmark_out_format=json",
            ],
        )
        utils.check_call(
            [
                "adb",
                "-s",
                dut.adb_serial,
                "pull",
                on_device_results_path,
                TMP_RESULTS_DIR.resolve(),
            ]
        )

    @staticmethod
    def run_bionic_benchmarks(dut: Dut):
        TestRunner.run_native_android_benchmark(
            dut,
            TestType.BENCH_BIONIC,
            "bionic/benchmarks",
            Path("/data/benchmarktest64/bionic-benchmarks/bionic-benchmarks"),
        )

    @staticmethod
    def run_libcore_benchmarks(
        dut: Dut,
    ):
        TestRunner.run_native_android_benchmark(
            dut,
            TestType.BENCH_LIBCORE,
            "libcore/",
            Path("/data/benchmarktest64/libjavacore-benchmarks/libjavacore-benchmarks"),
        )


def main():
    # TODO(tynasello)
    pass


if __name__ == "__main__":
    main()
