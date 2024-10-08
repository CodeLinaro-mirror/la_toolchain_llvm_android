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
# pylint: disable=invalid-name
import os
import sys
import re
from pathlib import Path
import tempfile

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../.."))

import context
from llvm_android import (mapfile, paths)

def build_sanitizer_map_file(san: str, arch: str, lib_dir: Path, section_name: str, tmp_dir: Path) -> tuple[Path, int]:
    # map_file example: libclang_rt.hwasan-aarch64-android.map.txt
    lib_file = Path(lib_dir / f'libclang_rt.{san}-{arch}-android.so')
    map_file = Path(tmp_dir / f'libclang_rt.{san}-{arch}-android.map.txt')
    num_symbols_annotated = mapfile.create_map_file(lib_file, map_file, section_name)
    return (map_file, num_symbols_annotated)


def get_latest_san_path() -> Path:
    lib_clang_dir = os.path.join(paths.NDK_BASE, "toolchains/llvm/prebuilt/linux-x86_64/lib/clang")
    clang_ver = os.listdir(lib_clang_dir)[0]
    # prebuilts/ndk/releases/r27/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/18/lib/linux/libclang_rt.tsan-riscv64-android.so
    san_dir = Path(os.path.join(lib_clang_dir, clang_ver, "lib/linux/"))
    return san_dir

def grep_file(filename, pattern) -> int:
    num_symbols_annotated = 0
    with open(filename, 'r') as file:
        for line in file:
            if re.search(pattern, line):
                num_symbols_annotated += 1
    return num_symbols_annotated

def grep_systemapi(filename) -> int:
    return grep_file(filename, "# systemapi llndk")

def grep_apex(filename) -> int:
    return grep_file(filename, "# apex llndk")

def mapfile_test(tmp_dir: Path):
    lib_dir: Path = get_latest_san_path()
    arch = 'aarch64'

    tmp_dir_Path = Path(tmp_dir)
    (asan_map_file, num_symbols_annotated) = build_sanitizer_map_file('asan', arch, lib_dir, 'ASAN', tmp_dir_Path)
    assert(grep_systemapi(asan_map_file) == num_symbols_annotated)
    (ubsan_map_file, num_symbols_annotated) = build_sanitizer_map_file('ubsan_standalone', arch, lib_dir, 'ASAN', tmp_dir_Path)
    assert(grep_systemapi(ubsan_map_file) == num_symbols_annotated)
    (tsan_map_file, num_symbols_annotated) = build_sanitizer_map_file('tsan', arch, lib_dir, 'TSAN', tmp_dir_Path)
    assert(grep_systemapi(tsan_map_file) == num_symbols_annotated)
    (hwsan_map_file, num_symbols_annotated) =  build_sanitizer_map_file('hwasan', arch, lib_dir, 'ASAN', tmp_dir_Path)
    assert(grep_apex(hwsan_map_file) == num_symbols_annotated)

if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as tmp_dir:
        mapfile_test(tmp_dir)
