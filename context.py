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

"""
Because the Android LLVM toolchain Python files are never "installed" by
something like pip we need to ensure that the executable scripts can find the
necessary library files.  This script accomplishes that by adding the
appropriate source directory (`toolchains/llvm_android/src`) to the Python
module search path.
"""

from pathlib import Path
import sys


sys.path.append(str((Path(__file__).parent / "src").resolve()))
