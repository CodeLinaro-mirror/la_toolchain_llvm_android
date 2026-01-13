#
# Copyright (C) 2020 The Android Open Source Project
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
"""Constants and helper functions for hosts."""
import enum
import platform
import sys

@enum.unique
class Host(enum.Enum):
    """Enumeration of supported hosts."""
    Darwin = 'darwin'
    Linux = 'linux'
    Windows = 'windows'
    Android = 'android'
    Baremetal = 'baremetal'

    @property
    def is_android(self) -> bool:
        """Returns True if the given host is Android."""
        return self == Host.Android

    @property
    def is_windows(self) -> bool:
        """Returns True if the given host is Windows."""
        return self == Host.Windows

    @property
    def is_darwin(self) -> bool:
        """Returns True if the given host is Darwin."""
        return self == Host.Darwin

    @property
    def is_linux(self) -> bool:
        """Returns True if the given host is Linux."""
        return self == Host.Linux

    @property
    def os_tag(self) -> str:
        """Returns the os tag of current Host."""
        return {
            Host.Darwin: 'darwin',
            Host.Linux: 'linux',
            Host.Windows: 'windows',
        }[self]

    @property
    def os_tag_musl(self) -> str:
        """Returns the os tag of current Host, using musl if the Host is Linux."""
        return 'linux_musl' if self is Host.Linux else self.os_tag

    @property
    def crt_dir(self) -> str:
        """Returns the subdirectory under lib for runtimes."""
        return {
            Host.Android: 'linux',
            Host.Baremetal: 'baremetal',
            Host.Linux: 'linux',
        }[self]


@enum.unique
class Arch(enum.Enum):
    """Enumeration of supported arches."""
    ARM = 'arm'
    AARCH64 = 'aarch64'
    AARCH64_LFI = 'aarch64_lfi'
    I386 = 'i386'
    X86_64 = 'x86_64'
    RISCV64 = 'riscv64'

    @property
    def llvm_arch(self) -> str:
        """Converts to llvm arch."""
        return {
            Arch.ARM: 'arm',
            Arch.AARCH64: 'aarch64',
            Arch.AARCH64_LFI: 'aarch64_lfi',
            Arch.I386: 'i686',
            Arch.X86_64: 'x86_64',
            Arch.RISCV64: 'riscv64'
        }[self]

    @property
    def arch_tag(self) -> str:
        """Returns tthe arch tag of current Arch."""
        return {
            Arch.AARCH64: 'arm64',
            Arch.ARM:  'arm',
            Arch.X86_64: 'x86',
            Arch.I386: 'x86',
        }[self]


@enum.unique
class Armv81MMainFpu(enum.Enum):
    """Enumeration of supported Armv8.1-M mainline FPUs."""
    NONE = 'nofp'
    SINGLE = 'fp'
    DOUBLE = 'fp.dp'

    @property
    def llvm_fpu(self) -> str:
        """Converts to llvm FPU name."""
        return {
            Armv81MMainFpu.NONE: 'none',
            Armv81MMainFpu.SINGLE: 'fp-armv8-fullfp16-sp-d16',
            Armv81MMainFpu.DOUBLE: 'fp-armv8-fullfp16-d16',
        }[self]

    @property
    def llvm_float_abi(self) -> str:
        """Converts to llvm float-abi."""
        return 'soft' if self == Armv81MMainFpu.NONE else 'hard'


def _get_default_host() -> Host:
    """Returns the Host matching the current machine."""
    if sys.platform.startswith('linux'):
        return Host.Linux
    if sys.platform.startswith('darwin'):
        return Host.Darwin
    if sys.platform.startswith('win'):
        return Host.Windows
    raise RuntimeError('Unsupported host: {}'.format(sys.platform))


def _get_default_arch() -> Arch:
    """Returns the Arch matching the current machine."""
    if platform.machine() == 'aarch64':
        return Arch.AARCH64
    return Arch.X86_64


_BUILD_OS_TYPE: Host = _get_default_host()
_BUILD_ARCH_TYPE: Arch = _get_default_arch()

def build_host() -> Host:
    """Returns the cached Host matching the current machine."""
    global _BUILD_OS_TYPE  # pylint: disable=global-statement
    return _BUILD_OS_TYPE


def build_arch() -> Arch:
    """Returns the cached Arch matching the current machine."""
    global _BUILD_ARCH_TYPE  # pylint: disable=global-statement
    return _BUILD_ARCH_TYPE


def build_tag() -> str:
    """Returns the directory to use for prebuilts for the current machine."""
    return tag(build_host(), build_arch())


def tag(host: Host, arch: Arch) -> str:
    """Returns the directory to use for prebuilts for the given host and arch."""
    return host.os_tag + '-' + arch.arch_tag


def musl_build_tag() -> str:
    """Returns the directory use for musl prebuilts for the current machine."""
    return musl_tag(build_host(), build_arch())


def musl_tag(host: Host, arch: Arch) -> str:
    """Returns the directory use for musl prebuilts for the given host and arch."""

    # X86_64 has separate prebuilts for musl, arm64 always uses musl.
    if arch == Arch.X86_64:
        return host.os_tag_musl + '-' + arch.arch_tag
    return tag(host, arch)
