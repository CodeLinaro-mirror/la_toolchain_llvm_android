# Code Review Guidelines for Android LLVM Build Subsystem (`src/llvm_android`)

This document establishes architectural review criteria, safety invariants, anti-patterns, and testing mandates for changes within `toolchain/llvm_android/src/llvm_android`. It serves as the primary technical specification for human reviewers and automated code review agents (e.g., `droid_reviewer`).

---

## 1. Code Review Focus Areas

### 1.1 Multi-Stage Pipeline Architecture & Isolation
The Android LLVM build infrastructure orchestrates a multi-stage compilation pipeline defined across `base_builders.py` and `builders.py`:
- **Stage 1 Bootstrap (`Stage1Builder`)**: Compiles a functional host compiler (`clang`, `lld`, basic tools) using prebuilt Clang from `prebuilts/clang/host/`. Stage 1 binaries must never be shipped or used directly as release artifacts.
- **Stage 2 Release Toolchain (`Stage2Builder`)**: Compiles the release-grade host compiler utilizing Stage 1 artifacts. Stage 2 incorporates Link-Time Optimization (LTO), Profile-Guided Optimization (PGO), BOLT optimization, and Machine Learning Guided Optimization (MLGO).
- **Device & Target Runtimes (`LLVMRuntimeBuilder` subclasses)**: Compiles runtime libraries (`compiler-rt`, `libcxx`, `libcxxabi`, `libunwind`, `tsan`, `libomp`) for Android devices and host targets using the Stage 2 compiler.
- **Flag & Definition Boundary Isolation**: Reviewers must verify that CMake defines, compilation flags (`cflags`, `cxxflags`), and link flags (`ldflags`) do not leak across stages:
  - Stage 2 optimization flags (e.g., `-Wl,-q` for BOLT, PGO profile directives) must never contaminate Stage 1.
  - Device runtimes must strictly use isolated target definitions (`RUNTIMES_<triple>_*` and `BUILTINS_<triple>_*` in `LLVMBuilder.cmake_defines`) and must never inherit host build flags or host include/library search paths.
  - External host library dependencies (`libxml2`, `zstd`, `xz`, `ncurses`, `libedit`) built via `CMakeBuilder` or `AutoconfBuilder` must be linked into host tools only, never into device runtimes.

### 1.2 Multi-Target & Cross-Compilation Matrix
All target configurations inherit from `Config` and `_BaseConfig` in `configs.py`:
- **Host Configurations**:
  - **Linux (`LinuxConfig`, `LinuxMuslConfig`)**: Must account for both glibc and musl sysroots. Musl builds require `-D_LARGEFILE64_SOURCE=1`, `-include stdc-predef.h`, compiler-rt builtins, and explicit bundling of `libc_musl.so` and `libjemalloc5.so`.
  - **Darwin (`DarwinConfig`)**: Targets macOS host systems. Must enforce universal binaries (`arm64;x86_64`), respect `constants.MAC_MIN_VERSION`, disable iOS/tvOS/watchOS compiler-rt builds, and adjust dynamic library install IDs via `install_name_tool`.
  - **Windows (`MinGWConfig`, `MSVCConfig`)**: Windows builds run cross-compiled on Linux. Reviewers must ensure `LLVM_ENABLE_PLUGINS=OFF` to prevent exceeding the PE/COFF symbol export limit (65,535 symbols), include required WinHTTP compatibility definitions, configure proper exception models (`-fsjlj-exceptions` for 32-bit), and normalize case sensitivity via `win_sdk.py`.
- **Device & Baremetal Configurations**:
  - **Android Device (`AndroidConfig`)**: Supports `arm`, `arm64`, `arm64_lfi`, `i386`, `x86_64`, and `riscv64`. Reviewers must verify exact triple generation (`base_llvm_triple` + `api_level`), appropriate NDK architecture mapping (`ndk_arch`), and correct sysroot binding (`paths.SYSROOTS / ('platform' | 'ndk') / arch`).
  - **Baremetal (`BaremetalConfig`)**: Targets ARM and AArch64 baremetal targets (`BaremetalArmv6MConfig`, `BaremetalArmv8MBaseConfig`, `BaremetalArmv81MMainConfig`, `BaremetalAArch64Config`). Reviewers must verify accurate FPU configurations (`Armv81MMainFpu`) and float ABIs (`soft` vs `hard`).

### 1.3 Hermeticity & Path Canonicalization
The build framework enforces strict hermeticity. Ambient workstation state or host distribution packages must never affect the build:
- **Canonical Path Registry (`paths.py`)**: All paths must resolve through `paths.py` relative to `paths.ANDROID_DIR` or `paths.OUT_DIR`. Reviewers must reject hardcoded paths, string-based path concatenations without `Path` objects, or references derived from current working directory (`os.getcwd()`).
- **Tool Resolution**: Compilers, linkers, python runtimes, and build tools must come exclusively from `prebuilts/`:
  - Python: `paths.get_python_executable()`, `paths.get_python_include_dir()`, `paths.get_python_lib()`.
  - Build engines: `paths.CMAKE_BIN_PATH`, `paths.NINJA_BIN_PATH`, `paths.MAKE_BIN_PATH`, `paths.BISON_BIN_PATH`.
- **Reproducible Path Mapping**: Every target configuration in `configs.py` must include `-ffile-prefix-map=${paths.ANDROID_DIR}/=` in `cflags` to strip local workspace directory structures from debug info and binary symbols.
- **Dynamic Linking & RPATH**: Binaries must find dependent shared libraries hermetically:
  - Linux: `-Wl,-rpath,\$ORIGIN:\$ORIGIN/../lib/<triple>` and `-static-libgcc`.
  - Darwin: `@rpath` addressing validated via `LibInfo.update_lib_id()`.

### 1.4 Source Management & Patch Lifecycle
Source preparation and patch application are governed by `source_manager.py` and `patch_utils.py`:
- **Copy-on-Write Staging**: Source setup (`setup_sources`) must stage into a temporary directory (`paths.OUT_DIR / 'llvm-project.tmp'`) using copy-on-write (`cp --reflink=auto` on Linux or `cp -c` on Darwin) before updating `paths.LLVM_PATH`.
- **Timestamp Preservation**: Updates from temporary staging to `paths.LLVM_PATH` must use checksummed synchronization (`rsync -r --delete --links -c ...`). Reviewers must ensure direct file writing into `paths.LLVM_PATH` is forbidden, as modifying timestamps unnecessarily triggers massive Ninja rebuild cascades.
- **Patch Schema & Sorting (`patch_utils.py`)**: All patches listed in `toolchain/llvm_android/patches/PATCHES.json` or `TOT.json` must pass `PatchList.check_patches()`:
  - Upstream cherry-picks must reside in `cherry/`, have valid `start_version` and `end_version`, satisfy `start_version < end_version`, and sort in ascending order of `end_version`.
  - Local patches must reside at the end of the list and preserve relative ordering.

### 1.5 Android Security, Hardening & ABI Standards
- **16KB Page Alignment**: To support 16KB ELF alignment on Android devices, `configs.py` must enforce `-Wl,-z,max-page-size=16384` and `-Wl,-z,common-page-size=16384` alongside `-D__BIONIC_NO_PAGE_SIZE_MACRO` for `hosts.Arch.AARCH64`, `hosts.Arch.X86_64`, and `hosts.Arch.AARCH64_LFI`.
- **Fortification & Stack Protection**: Device runtimes (`LLVMRuntimeBuilder`) for Android must inject `-fstack-protector-strong` and `-D_FORTIFY_SOURCE=3` (excluding builtins/compiler-rt/tsan where incompatible).
- **Branch Protection**: `AndroidAArch64Config` must pass `-mbranch-protection=standard` for PAC/BTI security.
- **Custom Assertion Handler**: Stage 2 and runtime builds must pass `LIBCXX_ASSERTION_HANDLER_FILE` pointing to `libcxx/vendor/android/android_assertion_handler.in` when present.
- **Sanitizer Mapfiles (`mapfile.py`)**: Sanitizer runtimes (`asan`, `hwasan`, `ubsan_standalone`, `tsan`) must generate symbol mapfiles via `SanitizerMapFileBuilder` and `mapfile.py` to annotate exported symbols for APEX and LLNDK stability.

---

## 2. Anti-Patterns & Common Pitfalls

### 2.1 Cross-Stage & Host-to-Device Flag Pollution
- **Leaking Host Flags to Device Runtimes**: Adding a compiler or linker flag to `LLVMBaseBuilder` or `_BaseConfig` without gating on target OS, causing host-specific flags (e.g., `-march=x86-64-v2`, `-fuse-ld=lld`, glibc headers) to break Android device runtime compilation.
- **Inadvertent PGO/BOLT Instrumentation of Stage 1**: Propagating `--pgo` or `--bolt` flags into `Stage1Builder`. Stage 1 must remain uninstrumented to avoid profiling overhead and dependency loops during bootstrapping.
- **Applying Optimization Flags to Baremetal Targets**: Passing POSIX-specific or OS-specific flags (like `-pie`, `-fPIC`, or page-size options) to `BaremetalConfig`.

### 2.2 Path Resolution & Filesystem Anti-Patterns
- **Local Machine Absolute Paths**: Hardcoding `/tmp`, `/usr/include`, or any absolute filesystem paths. All paths must be instantiated via `paths.py` relative to `ANDROID_DIR` or `OUT_DIR`.
- **String Concatenation for Paths**: Using string formatting or `os.path.join` on strings instead of standard `pathlib.Path` operator `/`.
- **Assuming Execution CWD**: Writing code that assumes the current working directory is the workspace root or script directory. Commands executed via `utils.check_call` must explicitly pass `cwd=<Path>`.
- **Direct Modification of LLVM Source Tree**: Creating or editing files directly in `paths.LLVM_PATH` rather than applying changes via `source_manager.py` patches or build output directories, which invalidates build caching.

### 2.3 Sysroot & Triple Drift
- **Mismatched Triple & Architecture**: Providing an LLVM target triple that diverges from the sysroot structure (e.g., using `arm-linux-androideabi` for 32-bit ARM compiler flags when `armv7a-linux-androideabi` is required for libc++ test driver consistency).
- **API Level Regression**: Hardcoding outdated API levels. Android platform runtimes default to API 30, NDK runtimes default to API 23, RISC-V 64 requires API 35, and TSAN requires API 24+.
- **Missing Architecture Flags**: Omitting architecture-specific tuning flags when overriding `cflags` in concrete configs (e.g., missing `-march=armv7-a` on ARM or `-march=x86-64-v2` on Linux x86_64).

### 2.4 Musl & Windows Cross-Compilation Traps
- **Missing Musl Runtime Dependencies**: Adding a new host binary dependency without ensuring `libc_musl.so` and `libjemalloc5.so` are copied into the builder install directory (`_install_lib_deps` in `base_builders.py`).
- **Enabling LLVM Plugins on Windows**: Setting `LLVM_ENABLE_PLUGINS=ON` on Windows builders (`MinGWConfig`, `MSVCConfig`), which triggers DLL link failures due to PE/COFF symbol table limits.
- **Missing Case Normalization in Windows SDK**: Modifying `win_sdk.py` or MSVC include handling without preserving case-insensitive symlinks in `win_sdk._prepare()`, causing Linux cross-compilation builds to fail on case-sensitive filesystems.
- **Missing WinHTTP Defines**: Forgetting MinGW compatibility defines (`WINHTTP_FLAG_SECURE_PROTOCOL_TLS1_3`, `WINHTTP_OPTION_ENABLE_HTTP_PROTOCOL`, `WINHTTP_PROTOCOL_FLAG_HTTP2`) required when compiling Windows networking support.

### 2.5 Builder Registry & Orchestration Failures
- **Bypassing `BuilderRegistry`**: Calling `builder._build_config()` directly rather than `builder.build()`, bypassing `@BuilderRegistry.register_and_build` and breaking filter functions (`--no-build`, `--skip-runtimes`).
- **Desynchronized CI Target Definitions**: Modifying flags or builder behaviors in `do_build.py` or `builders.py` without updating `target_definitions.py` (`TARGET_DEFS`), causing CI builds to invoke outdated CLI options.

---

## 3. Invariants & Safety Mandates

- **Hermetic Tooling Mandate**: Zero host distribution dependencies. All compilers, linkers, assemblers, python interpreters, CMake, Ninja, and sysroots must originate from `paths.PREBUILTS_DIR` or intermediate output stages.
- **Workspace-Agnostic Output**: Generated compiler artifacts and intermediate invocation scripts must be byte-for-byte identical regardless of the workstation checkout location. File prefix mapping (`-ffile-prefix-map`) must be active for all targets.
- **16KB Page Size Alignment**: All Android 64-bit ELF targets (`arm64`, `x86_64`, `arm64_lfi`) must strictly enforce 16KB common and max page sizes (`-Wl,-z,max-page-size=16384`, `-Wl,-z,common-page-size=16384`).
- **Patch Integrity & Bounds Monotonicity**: Every patch tracked in `patch_utils.py` must have an existing file, unique attribution, and strict monotonic revision bounds (`start_version < end_version` when bounded).
- **Public & AOSP Data Confidentiality**: Under no circumstances may internal shortlinks, internal issue tracker identifiers, corporate LDAPs, or non-public build infrastructure hostnames be introduced into source code, comments, or generated documentation.
- **Deterministic Builder Lifecycle**: Builders must always generate `cmake_invocation.sh` and `config_invocation.sh` scripts in `output_dir` prior to execution, capturing exact flags and environment state for auditability.

---

## 4. Verification & Testing Standards

### 4.1 Unit Testing & Static Verification
Before submitting code reviews, reviewers must verify all internal unit tests pass:
- **Mapfile Unit Tests**:
  ```bash
  python3 toolchain/llvm_android/src/llvm_android/mapfile_test.py
  ```
- **Patch Registry Schema Validation**:
  ```bash
  python3 -c "from llvm_android.patch_utils import PatchList; pl = PatchList.load_from_file(); assert pl.check_patches(), 'PATCHES.json validation failed'"
  ```

### 4.2 Fastbuild & Bootstrap Validation
For architectural or builder framework modifications:
- **Stage 1 Bootstrap Build**:
  Ensure toolchain bootstrapping and basic project configuration remain unbroken:
  ```bash
  python3 toolchain/llvm_android/build.py --bootstrap-build-only --no-incremental
  ```
- **Fastbuild Host Verification**:
  Validate Stage 2 CMake configuration, tool dependency wiring, and compilation without running long-running optimizations:
  ```bash
  python3 toolchain/llvm_android/build.py --no-build=windows --skip-tests --skip-runtimes --build-name=review-test --no-incremental
  ```

### 4.3 Invocation Script Auditing
Reviewers should verify the generated invocation scripts in the output directory:
- Inspect `out/stage1/cmake_invocation.sh` and `out/stage2/cmake_invocation.sh` to confirm CMake flags, library paths, and compiler defines match expectations.
- Inspect `out/lib/<target>-install/` to verify dynamic library SONAMEs, symlinks, and license placements (`LICENSE.musl`, etc.).

### 4.4 Multi-Platform & Runtime Verification
When altering `configs.py`, `base_builders.py`, or `builders.py`:
- **Cross-Host Sanity Check**: Verify configuration instantiation across all supported hosts:
  ```bash
  python3 -c "from llvm_android import configs; [c.cflags for c in [configs.LinuxConfig(), configs.LinuxMuslConfig(), configs.DarwinConfig(), configs.MinGWConfig()]]"
  ```
- **Android Target Matrix Check**: Verify device configuration generation:
  ```bash
  python3 -c "from llvm_android import configs; [c.cflags for c in configs.android_configs()]"
  ```
- **Compiler Test Suite Execution**:
  For changes modifying code generation or runtime configurations, ensure Ninja check targets pass:
  ```bash
  ninja -C out/stage1 check-clang check-llvm check-clang-tools
  ```

> Recorded Revision Hash: c58dd95f2b4669ed109b04b9a2b8e73e1f6f98ef
