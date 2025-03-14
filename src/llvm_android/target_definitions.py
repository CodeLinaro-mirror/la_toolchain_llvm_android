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

# Flags Order (based on how the flags were in original GCL):
# toolchain/llvm_android/build.py
# --bootstrap-use=
# --musl
# --lto
# --pgo
# --bolt
# --mlgo
# --package-stage2-install
# --create-tar
# --enable-assertions
# --debug
# --no-build=
# --skip-runtimes
# --skip-tests
# --bootstrap-build-only
# --builders-package
# --build-name
# --no-incremental
#
# toolchain/llvm_android/test_compiler.py
# --build-only
# --target
# --no-clean-built-target
# --no-pgo
# --generate-bolt-profile
# --generate-clang-profile
# --module dist
# --module droid
# --module platform_tests
# --module tidy-soong_subset
# --with-tidy
# --clang-package-path
# ./

# yapf: disable
TARGET_DEFS: dict[str, dict[str, list[str]]] = {
    "aosp-llvm-toolchain": {
        "llvm_darwin_mac": [
            "toolchain/llvm_android/build.py",
            "--lto",
            "--pgo",
            "--create-tar",
            "--builders-package",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "llvm_linux": [
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
        "llvm_linux_bootstrap": [
            "toolchain/llvm_android/build.py",
            "--mlgo",
            "--bootstrap-build-only",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "llvm_linux_builders": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--create-tar",
            "--no-build=windows",
            "--builders-package",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "llvm_linux_debug": [
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
        "llvm_linux_fastbuild": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--mlgo",
            "--create-tar",
            "--no-build=windows",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "llvm_linux_musl": [
            "toolchain/llvm_android/build.py",
            "--musl",
            "--lto",
            "--create-tar",
            "--no-build=windows",
            "--builders-package",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "llvm_windows_x86": [
            "toolchain/llvm_android/build.py",
            "--no-build=linux,windows-x86-64",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "llvm_windows_x86_64": [
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
        "llvm_windows_x86_64_fastbuild": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--create-tar",
            "--no-build=linux",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
    },

    "aosp-master-plus-llvm": {
        "aosp_cf_arm64_phone-eng": [
            "toolchain/llvm_android/test_compiler.py",
            "--build-only",
            "--target", "aosp_cf_arm64_phone-trunk_staging-eng",
            "--no-clean-built-target",
            "--module", "dist",
            "--module", "droid",
            "--clang-package-path", "out/prebuilt_cached/clang-prebuilt",
            "./",
        ],
        "aosp_cf_arm64_phone-userdebug": [
            "toolchain/llvm_android/test_compiler.py",
            "--build-only",
            "--target", "aosp_cf_arm64_phone-trunk_staging-userdebug",
            "--no-clean-built-target",
            "--module", "dist",
            "--module", "droid",
            "--clang-package-path", "out/prebuilt_cached/clang-prebuilt",
            "./",
        ],
        "aosp_cf_riscv64_phone-userdebug": [
            "toolchain/llvm_android/test_compiler.py",
            "--build-only",
            "--target", "aosp_cf_riscv64_phone-trunk_staging-userdebug",
            "--no-clean-built-target",
            "--module", "dist",
            "--module", "droid",
            "--clang-package-path", "out/prebuilt_cached/clang-prebuilt",
            "./",
        ],
        "aosp_cf_x86_64_phone-userdebug": [
            "toolchain/llvm_android/test_compiler.py",
            "--build-only",
            "--target", "aosp_cf_x86_64_phone-trunk_staging-userdebug",
            "--no-clean-built-target",
            "--module", "dist",
            "--module", "droid",
            "--module", "platform_tests",
            "--clang-package-path", "out/prebuilt_cached/clang-prebuilt",
            "./",
        ],
        "Clang-PGO": [
            "toolchain/llvm_android/test_compiler.py",
            "--build-only",
            "--target", "aosp_raven-trunk_staging-userdebug",
            "--no-clean-built-target",
            "--generate-clang-profile",
            "./",
        ],
        "Clang-BOLT": [
            "toolchain/llvm_android/test_compiler.py",
            "--build-only",
            "--target", "aosp_raven-trunk_staging-userdebug",
            "--no-clean-built-target",
            "--generate-bolt-profile",
            "./",
        ],
        "linux_bootstrap": [
            "toolchain/llvm_android/build.py",
            "--mlgo",
            "--bootstrap-build-only",
            "--no-incremental",
        ],
        "linux_fastbuild": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--mlgo",
            "--package-stage2-install",
            "--create-tar",
            "--no-build=windows",
            "--no-incremental",
        ],
        "LLVM-Kythe": [
            "toolchain/llvm_android/kythe_xref.py",
            BUILD_NAME,
        ]
    },

    "git_llvm-toolchain": {
        "llvm_darwin_mac": [
            "toolchain/llvm_android/build.py",
            "--lto",
            "--pgo",
            "--create-tar",
            "--builders-package",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "llvm_linux": [
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
        "llvm_linux_bootstrap": [
            "toolchain/llvm_android/build.py",
            "--mlgo",
            "--bootstrap-build-only",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "llvm_linux_builders": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--create-tar",
            "--no-build=windows",
            "--builders-package",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "llvm_linux_debug": [
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
        "llvm_linux_fastbuild": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--mlgo",
            "--create-tar",
            "--no-build=windows",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "llvm_linux_musl": [
            "toolchain/llvm_android/build.py",
            "--musl",
            "--lto",
            "--create-tar",
            "--no-build=windows",
            "--builders-package",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "llvm_windows_x86": [
            "toolchain/llvm_android/build.py",
            "--no-build=linux,windows-x86-64",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
        "llvm_windows_x86_64": [
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
        "llvm_windows_x86_64_fastbuild": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--create-tar",
            "--no-build=linux",
            "--build-name", BUILD_NAME,
            "--no-incremental",
        ],
    },

    "git_main-plus-llvm": {
        "aosp_cf_arm64_phone-eng": [
            "toolchain/llvm_android/test_compiler.py",
            "--build-only",
            "--target", "aosp_cf_arm64_phone-trunk_staging-eng",
            "--no-clean-built-target",
            "--module", "dist",
            "--module", "droid",
            "--clang-package-path", "out/prebuilt_cached/clang-prebuilt",
            "./",
        ],
        "aosp_cf_arm64_phone-userdebug": [
            "toolchain/llvm_android/test_compiler.py",
            "--build-only",
            "--target", "aosp_cf_arm64_phone-trunk_staging-userdebug",
            "--no-clean-built-target",
            "--module", "dist",
            "--module", "droid",
            "--clang-package-path", "out/prebuilt_cached/clang-prebuilt",
            "./",
        ],
        "aosp_cf_riscv64_phone-userdebug": [
            "toolchain/llvm_android/test_compiler.py",
            "--build-only",
            "--target", "aosp_cf_riscv64_phone-trunk_staging-userdebug",
            "--no-clean-built-target",
            "--module", "dist",
            "--module", "droid",
            "--clang-package-path", "out/prebuilt_cached/clang-prebuilt",
            "./",
        ],
        "aosp_cf_x86_64_phone-userdebug": [
            "toolchain/llvm_android/test_compiler.py",
            "--build-only",
            "--target", "aosp_cf_x86_64_phone-trunk_staging-userdebug",
            "--no-clean-built-target",
            "--module", "dist",
            "--module", "droid",
            "--module", "platform_tests",
            "--clang-package-path", "out/prebuilt_cached/clang-prebuilt",
            "./",
        ],
        "Clang-PGO": [
            "toolchain/llvm_android/test_compiler.py",
            "--build-only",
            "--target", "aosp_raven-trunk_staging-userdebug",
            "--no-clean-built-target",
            "--generate-clang-profile",
            "./",
        ],
        "Clang-BOLT": [
            "toolchain/llvm_android/test_compiler.py",
            "--build-only",
            "--target", "aosp_raven-trunk_staging-userdebug",
            "--no-clean-built-target",
            "--generate-bolt-profile",
            "./",
        ],
        "linux_bootstrap": [
            "toolchain/llvm_android/build.py",
            "--mlgo",
            "--bootstrap-build-only",
            "--no-incremental",
        ],
        "linux_fastbuild": [
            "toolchain/llvm_android/build.py",
            "--bootstrap-use=out/prebuilt_cached/artifacts/linux_bootstrap/stage1-install.tar.xz",
            "--mlgo",
            "--package-stage2-install",
            "--create-tar",
            "--no-build=windows",
            "--no-incremental",
        ],
        "LLVM-Kythe": [
            "toolchain/llvm_android/kythe_xref.py",
            BUILD_NAME,
        ]
    }
}
# yapf: enable