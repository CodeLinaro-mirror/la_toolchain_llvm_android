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
"""Report toolchain build errors"""

from enum import Enum, auto
from typing import List

class ToolchainErrorCode(Enum):
    UNKNOWN_ERROR = auto()
    PATCH_ERROR = auto()
    STAGE1_BUILD_ERROR = auto()
    STAGE1_TEST_ERROR = auto()
    STAGE2_BUILD_ERROR = auto()
    STAGE2_TEST_ERROR = auto()
    RUNTIME_BUILD_ERROR = auto()

class ToolchainError:
    code: ToolchainErrorCode
    msg: str
    def __init__(self, code: ToolchainErrorCode, msg: str) -> None:
        self.code = code
        self.msg = msg

    def __repr__(self):
        return repr(self.code.name + ':' + self.msg)

def combine_toolchain_errors(errs: List[ToolchainError]) -> str:
    return ',\n'.join(map(str, errs))
