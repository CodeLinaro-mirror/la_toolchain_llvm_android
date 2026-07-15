# Android Clang/LLVM Toolchain

## Project Overview
This project contains the build scripts and tooling used to manage the Android Clang/LLVM toolchain.

## Key Directories
- **`toolchain/llvm_android/`** (this directory): The core build system project.
    - `build.py`: Main entry point for the build script.
    - **`src/llvm_android/`**: Implementation details of the build system.
    - **`patches/`**: Patches applied to the upstream LLVM source.
        - `PATCHES.json`: Metadata tracking patches for specific versions.
        - `TOT.json`: Metadata tracking patches for the upstream TOT (top of the tree) version.
        - `*.patch`: Local Android LLVM modifications.
        - `cherry/*.patch`: Backported upstream changes.
    - **`kokoro/`**: Configuration files for the Kokoro CI system.
    - **`docker/`**: Docker environment configurations.
- **`toolchain/llvm-project/`**: LLVM source code for stable releases; does not track upstream `main`.
- **`external/toolchain-utils/`**: Shared utilities for ChromeOS and Android toolchains.
- **`prebuilts/`**: Prebuilt binaries required for the build.
- **`out/`**: Default output directory.
    - `out/llvm-project/`: Patched LLVM source code used for the toolchain build.

## Bug Component IDs
The main bug component ID for the Android LLVM project is 117395. LLVM top of trunk testing related build issues uses a sub-component and its ID is 1268429.

## Android LLVM Versioning
Upstream LLVM is versioned using Git SHAs. Android LLVM uses a numeric versioning system in the format of `r*****`, which tracks the number of changes since the project's beginning. This is possible because upstream LLVM enforces a linear history without branching.

Use `external/toolchain-utils/py/bin/llvm_tools/git_llvm_rev` to convert between upstream SHAs and Android numeric versions.
