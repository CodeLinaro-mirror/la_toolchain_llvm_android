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
"""Target Definitions for Android LLVM Toolchain builds"""

import os

BUILD_NAME = os.environ.get("BUILD_NAME", "dev")

# yapf: disable
TARGET_DEFS: dict[str, dict[str, list[str]]] = {
    "aosp-llvm-toolchain": {
        "darwin-mac": [
            "toolchain/llvm_android/build.py",
            "--lto",
            "--pgo",
            "--create-tar",
            "--builders-package",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "linux": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--lto",
            "--pgo",
            "--bolt",
            "--mlgo",
            "--create-tar",
            "--no-build=windows",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "linux_bootstrap": [
            "toolchain/llvm_android/build.py",
            "--mlgo",
            "--bootstrap-build-only",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "linux_builders": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--create-tar",
            "--builders-package",
            "--no-build=windows",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "linux_debug": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--create-tar",
            "--enable-assertions",
            "--debug",
            "--no-build=windows,lldb",
            "--skip-runtimes",
            "--skip-tests",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "linux_fastbuild": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--mlgo",
            "--create-tar",
            "--no-build=windows",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "linux_musl": [
            "toolchain/llvm_android/build.py",
            "--musl",
            "--lto",
            "--create-tar",
            "--no-build=windows",
            "--builders-package",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "windows_x86": [
            "toolchain/llvm_android/build.py",
            "--no-build=linux,windows-x86-64",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "windows_x86_64": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--lto",
            "--pgo",
            "--create-tar",
            "--no-build=linux",
            "--builders-package",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "windows_x86_64_fastbuild": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--create-tar",
            "--no-build=linux",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
    }
}
# yapf: enable