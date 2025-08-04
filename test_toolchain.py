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
import logging
from subprocess import SubprocessError
import sys
from typing import Any, Dict, List
from pathlib import Path
import time
import argparse
import json
import yaml

import context  # pylint: disable=unused-import
from llvm_android import utils

__doc__ = """
This script supports the automation of on-device testing and benchmarking of the android toolchain.
At the core of this program is an input configuration file specifying the device and test configurations to run.
"""

input_yaml_config_example = """test_configs:
      # One or more test configs to be specified...
      geekbench-twice: # unique user-defined identifier
        type: GEEKBENCH # program-defined value for the test to run (see TestType enum)
        num_samples: 2 # number of times to run this test (defaults to 1 if line not included)
        bin_dir: ~/opt/geekbench/6.1.0/ # Geekbench-specific key-value pair

    device_configs:
      # One or more device configs to be specified...
      brya-cros8-3-4-36-already-leased-flashed: # unique user-defined identifier
        android_target: brya-trunk_staging-userdebug # Same format as specified to lunch command (TARGET_PRODUCT-TARGET_RELEASE-TARGET_BUILD_VARIANT). This is needed to lunch and cross-compile for device.
        adb_serial: localfilesystem:/tmp/corp-adb-helper/chromeos8-row3-rack4-host36/sock # No communication with a lab or management of ADB connections occurs if ADB serial is provided.
      brya-on-desk-flashed:
        android_target: brya-trunk_staging-userdebug
        adb_infer: true # No communication with a lab or management of ADB connections occurs if ADB infer is true (defaults to false). This option will use the singular ADB connection if available through `adb devices`, and error otherwise.
      multiple_bryas:
        android_target: brya-trunk_staging-userdebug
        ota_image_path: ~/opt/android-platform/main/out/dist/brya-ota-user.zip # Path to over-the-air image. The DUT will always be flashed if this is specified.
        device_count: 3 # The number of devices to run tests on under the above specification (defaults to 1 if not provided). This is useful for sampling by board type.
      brya-cros-12-1-53:
        android_target: brya-trunk_staging-userdebug
        host: chromeos8-row12-rack1-host53 # Will lease a DUT with a specific host name (is dependent on the lab used). If neither host nor adb_serial nor adb_infer is provided, DUT is leased by board type (inferred from target).
"""

epilog = f"""Example Usage:
    python test_toolchain.py -o test-results ~/opt/android-platform/main test_toolchain_input.yaml

Example input configuration file (YAML):
    {input_yaml_config_example}

Adding a new test:
    - Maybe add case in TestConfig.from_input_config to get and store test-specific configurations (e.g. bin_dir for Geekbench) from user input. Raise exception if not provided but required.
    - Add static method in TestRunner that takes in a Dut (and maybe more), executes the test, and returns a TestResult with captured results.
    - Add case for test in TestRunner.run_test method that calls the newly added method mentioned above.

Adding a new lab:
    - Implement the abstract methods declared in Lab.
"""


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "config_file",
        help="Path to YAML configuration file.",
    )

    parser.add_argument(
        "-a",
        "--android-root",
        required=True,
        help=(
            "Root of Android source directory. Will be used for envsetup, lunching,"
            " locating utility scripts, and building tests (therefore, may overwrite"
            " out directory)."
        ),
    )

    parser.add_argument(
        "-o",
        "--out-dir",
        default="/tmp/toolchain-test-results",
        help="Directory path where test results will be output to.",
    )

    return parser.parse_args()


class AndroidTarget:
    """
    A class representing an Android build environment.
    The target field is used for lunching. The resulting environemnt is captured in the env field for further use.
    """

    def __init__(self, target: str, android_root: Path):
        self.target = target
        self.android_root = android_root
        self.env = utils.prepare_env(android_root, self.target)

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

    def prep_for_test(self):
        """
        Prepares a device for testing.
        - Reboots device (clears RAM & caches, closes open files, kills lingering processes, etc.).
        - Roots device (needed to run some commands of interest).
        - Push and run device-preparation shell script on device (sets certain Android settings, governers, etc.).
        May raise exception.
        """
        if self.adb_serial is None:
            raise Dut.DutError(
                "Could not prepare device for test because it is not available over"
                " ADB."
            )

        self.reboot()
        self.root_adb()

        script_path = Path("./prep_dut_for_test.sh")
        script_on_device_path = Path(f"/data/local/tmp/{script_path.name}")
        utils.check_call(
            [
                "adb",
                "-s",
                self.adb_serial,
                "push",
                script_path.resolve(),
                script_on_device_path.parent,
            ],
        )
        utils.check_call(
            [
                "adb",
                "-s",
                self.adb_serial,
                "shell",
                "--",
                "chmod",
                "+x",
                script_on_device_path,
                "&&",
                "sh",
                script_on_device_path,
                "&&",
                "rm",
                script_on_device_path,
            ],
        )


class Lab:
    """
    Abstract class for a lab.
    It can be expected that all methods could raise exceptions.
    """

    class LabError(Exception):
        pass

    DEFAULT_LEASE_TIME_MIN = 240

    @staticmethod
    def lease_by_host_name(host_name: str, time_min: int):
        raise NotImplementedError("Subclass must implement abstract method.")

    @staticmethod
    def lease_by_board_type(board_type: str, time_min: int) -> str:
        """Returns host name of leased device."""
        raise NotImplementedError("Subclass must implement abstract method.")

    @staticmethod
    def release(host_name: str):
        raise NotImplementedError("Subclass must implement abstract method.")

    @staticmethod
    def release_all():
        raise NotImplementedError("Subclass must implement abstract method.")

    @staticmethod
    def get_board_type(host_name: str):
        raise NotImplementedError("Subclass must implement abstract method.")


class Swarming(Lab):
    """
    Lab implementation for ChromeOS Swarming. Interaction achieved through the Crosfleet CLI.
    """

    class CrosfleetDutInfo:
        def __init__(self, host_name: str | None, board_type: str | None):
            self.host_name = host_name
            self.board_type = board_type

        @classmethod
        def from_info_cmd(cls, host_name: str) -> "Swarming.CrosfleetDutInfo":
            board_type: str | None = None
            for line in utils.check_output(
                ["crosfleet", "dut", "info", host_name]
            ).splitlines():
                if line is None or "=" not in line:
                    continue
                (key, _, value) = line.partition("=")
                if key == "BOARD":
                    board_type = value.strip()
            return cls(host_name, board_type)

    @staticmethod
    def lease_by_host_name(host_name: str, time_min: int):
        utils.check_call(
            [
                "crosfleet",
                "dut",
                "lease",
                "--host",
                host_name,
                "--minutes",
                str(time_min),
            ]
        )

    @staticmethod
    def lease_by_board_type(board_type: str, time_min: int) -> str:
        host_name = (
            utils.check_output(
                [
                    "crosfleet",
                    "dut",
                    "lease",
                    "-dims",
                    f"version_info_os_type=ANDROID,dut_state=ready,label-board={board_type},label-pool=DUT_POOL_QUOTA",
                    "--minutes",
                    str(time_min),
                ],
            )
            .splitlines()[0]
            .split()[1]
        )
        if host_name is None:
            raise Lab.LabError(
                "The device could not be leased using the provided board type"
                f" {board_type}."
            )
        return host_name

    @staticmethod
    def release(host_name: str):
        # This command sometimes hangs and causes an error. Unsure of the cause.
        utils.subprocess_run(["crosfleet", "dut", "abandon", host_name])

    @staticmethod
    def release_all():
        utils.subprocess_run(["crosfleet", "dut", "abandon"])

    @staticmethod
    def get_board_type(host_name: str):
        return Swarming.CrosfleetDutInfo.from_info_cmd(host_name).board_type


class TestType(enum.Enum):
    """
    Enum of supported tests/benchamrks.
    """

    CTS_BIONIC = "CTS_BIONIC"
    CTS_LIBCORE = "CTS_LIBCORE"
    LIBCXX = "LIBCXX"
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


class TestResult:
    """
    A class for recording arbitrary test results
    """

    def __init__(
        self,
        test_type: TestType,
        data: Dict[str, Any],
        data_formatted: Dict[str, str] | None = None,
    ):
        self.test_type = test_type
        self.data = data
        self.data_formatted = data_formatted


class TestToolchainError(Exception):
    pass


TMP_RESULTS_DIR = Path("/tmp/toolchain-test-results-raw")


class TestRunner:
    """
    Implementations for executing each supported test type.
    - Each method should return a TestResult object to record results.
    - Can expect that each method may throw an exception.
    """

    @staticmethod
    def run_cts(
        dut: Dut,
        test_type: TestType,
        package: str,
    ) -> TestResult:
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
        with results_file.open(encoding="utf-8") as f:
            data = json.load(f)
        return TestResult(test_type, data)

    @staticmethod
    def run_bionic_cts(dut: Dut) -> TestResult:
        return TestRunner.run_cts(dut, TestType.CTS_BIONIC, "CtsBionicTestCases")

    @staticmethod
    def run_libcore_cts(dut: Dut) -> TestResult:
        return TestRunner.run_cts(dut, TestType.CTS_LIBCORE, "CtsLibcoreTestCases")

    @staticmethod
    def run_libcxx(dut: Dut) -> TestResult:
        abi = dut.get_abi()
        match abi:
            case "x86_64":
                target = "x86_64"
            case "x86":
                target = "i386"
            case "arm64-v8a":
                target = "aarch64"
            case "armeabi-v7a" | "armeabi":
                target = "arm"
            case "riscv64":
                target = "riscv64"
            case _:
                raise TestToolchainError(
                    f"Libcxx testing is not supported for device's ABI {abi}."
                )
        libcxx_out_dir = utils.paths.OUT_DIR / f"lib/device-libcxx-{target}"
        utils.check_call(
            [
                "adb",
                "-s",
                dut.adb_serial,
                "push",
                f"{libcxx_out_dir}/lib/libc++.so",
                "/data/local/tmp/libc++/libc++.so",
            ],
        )
        utils.subprocess_run(["ninja", "check-cxx", "check-cxxabi"], cwd=libcxx_out_dir)
        data: Dict[str, Any] = {}
        filenames = [
            libcxx_out_dir / "libcxx/test/test-results.json",
            libcxx_out_dir / "libcxxabi/test/test-results.json",
        ]
        for filename in filenames:
            with open(filename, encoding="utf-8") as f:
                data[str(filename)] = json.load(f)
        return TestResult(TestType.LIBCXX, data)

    @staticmethod
    def run_geekbench(dut: Dut, bin_dir_path: Path) -> TestResult:
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

        with (TMP_RESULTS_DIR / results_file_name).open(encoding="utf-8") as f:
            data = json.load(f)
        data_formatted: Dict[str, str] = {}
        data_formatted["multicore"] = data["multicore_score"]
        data_formatted["single"] = data["score"]
        for section in data["sections"]:
            section_name = section["name"]
            for workload in section["workloads"]:
                data_formatted[f"{section_name} {workload['name']}"] = workload["score"]

        return TestResult(TestType.GEEKBENCH, data, data_formatted)

    @staticmethod
    def run_native_android_benchmark(
        dut: Dut,
        test_type: TestType,
        module: str,
        on_device_bin: Path,
    ) -> TestResult:
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
        with (TMP_RESULTS_DIR / results_file_name).open(encoding="utf-8") as f:
            data = json.load(f)
        data_formatted: Dict[str, Any] = {}
        for benchmark in data["benchmarks"]:
            data_formatted[benchmark["name"]] = benchmark["real_time"]
        return TestResult(test_type, data, data_formatted)

    @staticmethod
    def run_bionic_benchmarks(dut: Dut) -> TestResult:
        return TestRunner.run_native_android_benchmark(
            dut,
            TestType.BENCH_BIONIC,
            "bionic/benchmarks",
            Path("/data/benchmarktest64/bionic-benchmarks/bionic-benchmarks"),
        )

    @staticmethod
    def run_libcore_benchmarks(
        dut: Dut,
    ) -> TestResult:
        return TestRunner.run_native_android_benchmark(
            dut,
            TestType.BENCH_LIBCORE,
            "libcore/",
            Path("/data/benchmarktest64/libjavacore-benchmarks/libjavacore-benchmarks"),
        )


class Config:
    """
    Configuration used to specify devices to test on, and tests to run.
    """

    class ConfigError(Exception):
        pass

    class Test:
        def __init__(
            self,
            test_id: str,
            test_type: TestType,
            num_samples: int,
            test_specific: Dict[str, Any],
        ):
            self.test_id = test_id
            self.test_type = test_type
            self.num_samples = num_samples
            self.test_specific = test_specific

        @classmethod
        def from_input_config(
            cls, test_id, test_config: Dict[str, Any]
        ) -> "Config.Test":
            """
            In practice the test config dict is read from an input configuration file.
            Sane defaults are chosen if key of interest not found in test config dict.
            May raise an exception if required key does not exist or if a value is invalid.
            """
            try:
                test_type = TestType[test_config["type"]]
            except KeyError:
                raise Config.ConfigError(
                    f"Test type {test_config['type']} is not supported. Supported tests"
                    f" are {', '.join([test_type.name for test_type in TestType])}."
                )
            num_samples: int = test_config.get("num_samples", 1)
            if num_samples < 1:
                raise Config.ConfigError(
                    f"Invalid number of samples provided ({num_samples}) for test"
                    f" {test_id}. Must be more than 0."
                )
            test_specific: Dict[str, Any] = {}
            if test_type == TestType.GEEKBENCH:
                bin_dir = test_config.get("bin_dir")
                if bin_dir is None:
                    raise Config.ConfigError(
                        "Geekbench tests require a bin_dir key-value pair specifying"
                        " a directory containing geekbench binaries."
                    )
                bin_dir = Path(bin_dir).expanduser()
                if not bin_dir.exists():
                    raise Config.ConfigError(
                        f"Invalid bin_dir {bin_dir} provided for Geekbench tests."
                    )
                test_specific["bin_dir"] = bin_dir
            return cls(test_id, test_type, num_samples, test_specific)

    class Device:
        def __init__(
            self,
            device_id: str,
            android_target: str,
            host_name: str | None,
            adb_serial: str | None,
            adb_infer: bool,
            device_count: int,
            ota_image_path: Path | None,
        ):
            self.device_id = device_id
            self.android_target = android_target
            self.host_name = host_name
            self.adb_serial = adb_serial
            self.adb_infer = adb_infer
            self.device_count = device_count
            self.ota_image_path = ota_image_path

        @classmethod
        def from_input_config(
            cls, device_id, device_config: Dict[str, Any]
        ) -> "Config.Device":
            """
            In practice the device config dict is read from an input configuration file.
            Sane defaults are chosen if key of interest not found in test config dict.
            May raise an exception if required key does not exist or if a value is invalid.
            """
            android_target: str | None = device_config["android_target"]
            if android_target is None:
                raise Config.ConfigError("Must specify android target for device.")
            host_name: str | None = device_config.get("host_name")
            adb_serial: str | None = device_config.get("adb_serial")
            adb_infer: bool = device_config.get("adb_infer", False)
            device_count: int = device_config.get("device_count", 1)
            if device_count < 1:
                raise Config.ConfigError(
                    f"Invalid number of devices provided ({device_count}) for device"
                    f" {device_id}. Must be more than 0."
                )
            ota_image_path = None
            ota_image_raw_path: str | None = device_config.get("ota_image_path")
            if ota_image_raw_path is not None:
                ota_image_path = Path(ota_image_raw_path).expanduser()
                if not ota_image_path.exists():
                    raise Config.ConfigError(
                        f"Provided OTA image path ({ota_image_path}) was not found."
                    )
            return cls(
                device_id,
                android_target,
                host_name,
                adb_serial,
                adb_infer,
                device_count,
                ota_image_path,
            )

    def __init__(
        self,
        test_configs: List["Config.Test"],
        device_configs: List["Config.Device"],
    ):
        self.test_configs = test_configs
        self.device_configs = device_configs

    @classmethod
    def from_yaml(cls, yaml_config_path: Path) -> "Config":
        """
        Create a Config object from data in input YAML config file.
        May raise exception.
        """
        try:
            with yaml_config_path.resolve().open(encoding="utf-8") as f:
                input_config = yaml.safe_load(f)

            test_configs: List["Config.Test"] = []
            device_configs: List["Config.Device"] = []

            for test_id, input_test_config in input_config["test_configs"].items():
                test_configs.append(
                    cls.Test.from_input_config(test_id, input_test_config)
                )

            for device_id, input_device_config in input_config[
                "device_configs"
            ].items():
                device_configs.append(
                    cls.Device.from_input_config(device_id, input_device_config)
                )

            return cls(test_configs, device_configs)

        except Exception as e:
            raise Config.ConfigError(
                "There was an error reading the provided input config file"
                f" {yaml_config_path}."
            ) from e


def _setup_device(
    device_config: Config.Device,
    android_target: AndroidTarget,
    lab: Lab,
) -> Dut | None:
    dut: Dut | None = None

    try:
        if device_config.adb_serial is None and not device_config.adb_infer:
            # Lease device and create ADB connection
            utils.logger().info("Leasing device.")
            if device_config.host_name is not None:
                lab.lease_by_host_name(
                    device_config.host_name,
                    Lab.DEFAULT_LEASE_TIME_MIN,
                )
                board_type = lab.get_board_type(device_config.host_name)
                if board_type is None:
                    lab.release(device_config.host_name)
                    raise Lab.LabError(
                        "Could not use leased device because it's board type"
                        f" {board_type} is not known."
                    )
                if board_type != android_target.get_board_type():
                    lab.release(device_config.host_name)
                    raise Lab.LabError(
                        "Could not use leased device because it's board type"
                        f" {board_type} is not compatible with the provided"
                        f" target {android_target.target}, which has board type"
                        f" {android_target.get_board_type()}."
                    )
                dut = Dut(android_target, device_config.host_name)
            else:
                board_type = android_target.get_board_type()
                host_name = lab.lease_by_board_type(
                    board_type, Lab.DEFAULT_LEASE_TIME_MIN
                )
                dut = Dut(android_target, host_name)
            utils.logger().info("Creating ADB connection for device.")
            dut.create_adb_connection_over_ssh(android_target.android_root)

        else:
            # ADB serial is provided or can be inferred. No device leasing needed.
            adb_serial = device_config.adb_serial
            if adb_serial is None:
                utils.logger().info("Inferring ADB serial of device.")
                connections = utils.check_output(["adb", "devices"]).splitlines()[1:-1]
                if len(connections) != 1:
                    raise TestToolchainError(
                        "Could not infer ADB serial to use. Ensure that only one device"
                        " is available over ADB."
                    )
                adb_serial, _ = connections[0].split()
            if Dut.get_board_type(adb_serial) != android_target.get_board_type():
                raise Lab.LabError(
                    "Could not use inferred device because it's board type"
                    f" {Dut.get_board_type(adb_serial)} is not compatible with"
                    f" the provided target {android_target.target}, which has"
                    f" board type {android_target.get_board_type()}."
                )
            dut = Dut.local(android_target, adb_serial)

        if device_config.ota_image_path is not None:
            # Flash device if image is provided.
            utils.logger().info("Flashing device.")
            dut.flash(device_config.ota_image_path)
        else:
            # Assume user wants to use current device image
            dut.is_flashed = True

        return dut

    except (SubprocessError, Dut.DutError, Lab.LabError) as e:
        utils.logger().error(e)
        if (
            dut is not None
            and device_config.adb_serial is None
            and not device_config.adb_infer
        ):
            if dut.host_name is not None:
                lab.release(dut.host_name)
            if dut.adb_serial is not None:
                dut.remove_adb_connection()
        return None


def _run_test_on_device(
    test_config: Config.Test,
    dut: Dut,
) -> TestResult:
    if not dut.is_ready_to_test():
        raise TestToolchainError(
            "Test could not be run because the device is not ready for testing."
        )
    dut.prep_for_test()
    match test_config.test_type:
        case TestType.CTS_BIONIC:
            results = TestRunner.run_bionic_cts(dut)
        case TestType.CTS_LIBCORE:
            results = TestRunner.run_libcore_cts(dut)
        case TestType.LIBCXX:
            results = TestRunner.run_libcxx(dut)
        case TestType.GEEKBENCH:
            results = TestRunner.run_geekbench(
                dut, test_config.test_specific["bin_dir"]
            )
        case TestType.BENCH_BIONIC:
            results = TestRunner.run_bionic_benchmarks(dut)
        case TestType.BENCH_LIBCORE:
            results = TestRunner.run_libcore_benchmarks(dut)

    return results


def test_toolchain(config: Config, android_root: Path, results_root: Path, lab: Lab):
    """
    Facilitator of managing devices, invoking test runs, and recording results.
    - Outputs results to provided output directory (out-dir > device-id > test-id > test-id-iteration >
      device-id-iteration > {results.json, results-formatted.json device.json}). A symlink is created
      for the latest test results directory.
    - Iterates through all device configurations, sets up each device, and runs each test configuration.
    - If a device cannot be setup correctly, it is skipped.
    - If a test cannot be run for a given iteration, it is skipped.
    - Devices are cleaned up (when finished with testing and during exceptions).
    """
    results_dir = (
        results_root / f"results-{datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}"
    )
    results_dir.mkdir(parents=True)
    latest_sym_link_path = results_root.resolve() / "latest"
    latest_sym_link_path.unlink(missing_ok=True)
    latest_sym_link_path.symlink_to(results_dir.resolve())
    TMP_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    for device_config in config.device_configs:
        android_target = AndroidTarget(device_config.android_target, android_root)

        for device_iteration in range(device_config.device_count):
            # Device Setup
            utils.logger().info(
                f"Setting up device {device_config.device_id} (iteration"
                f" {device_iteration})."
            )
            dut = _setup_device(device_config, android_target, lab)
            if dut is None:
                utils.logger().error(
                    f"Could not setup device {device_config.device_id} (iteration"
                    f" {device_iteration}). Skipping tests for this device iteration."
                )
                continue

            # Testing...
            for test_config in config.test_configs:
                for test_iteration in range(test_config.num_samples):
                    try:
                        utils.logger().info(
                            f"Running test {test_config.test_id} (iteration"
                            f" {test_iteration}) for device"
                            f" {device_config.device_id} (iteration"
                            f" {device_iteration})."
                        )

                        results = _run_test_on_device(test_config, dut)

                        # Write results
                        test_results_dir = (
                            results_dir
                            / device_config.device_id
                            / test_config.test_id
                            / f"{test_config.test_id}-{test_iteration}"
                            / f"{device_config.device_id}-{device_iteration}"
                        )
                        test_results_dir.mkdir(parents=True)
                        with (
                            (test_results_dir / "device.json")
                            .resolve()
                            .open("w", encoding="utf-8") as f
                        ):
                            json.dump(dut.to_dict(), f, indent=4)
                        with (
                            (test_results_dir / "results.json")
                            .resolve()
                            .open("w", encoding="utf-8") as f
                        ):
                            json.dump(results.data, f, indent=4)
                        if results.data_formatted:
                            with (
                                (test_results_dir / "results-formatted.json")
                                .resolve()
                                .open("w", encoding="utf-8") as f
                            ):
                                json.dump(
                                    results.data_formatted,
                                    f,
                                    indent=4,
                                )
                        utils.logger().info(
                            f"Test results written to {test_results_dir}."
                        )

                    except (SubprocessError, Dut.DutError, TestToolchainError) as e:
                        utils.logger().error(e)
                        utils.logger().error(
                            f"Error running test {test_config.test_id} (iteration"
                            f" {test_iteration}) for device"
                            f" {device_config.device_id} (iteration"
                            f" {device_iteration}). Skipping and proceeding to next"
                            " iteration."
                        )

            # Device cleanup...
            if device_config.adb_serial is None and not device_config.adb_infer:
                if dut.host_name:
                    lab.release(dut.host_name)
                if dut.adb_serial:
                    dut.remove_adb_connection()

    utils.logger().info(
        f"Testing complete. Results written to {results_dir.resolve()}."
    )


def main():
    logging.basicConfig(level=logging.DEBUG)

    args = parse_args()

    android_root = Path(args.android_root).expanduser()
    if not android_root.exists():
        raise Exception("Android root path not found.")

    config_file = Path(args.config_file).expanduser()
    if not config_file.exists():
        raise Exception("Input configuration file path not found.")

    out_dir = Path(args.out_dir).expanduser()
    if not out_dir.exists():
        out_dir.mkdir(parents=True, exist_ok=True)

    config = Config.from_yaml(config_file)
    lab = Swarming()

    test_toolchain(config, android_root, out_dir, lab)


if __name__ == "__main__":
    main()
