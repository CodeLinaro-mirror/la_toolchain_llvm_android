# Code Review Guide for `toolchain/llvm_android`

This guide establishes the mandatory review criteria, architectural invariants, common anti-patterns, and testing requirements for changes to the Android LLVM toolchain build orchestration, patch management, and compiler packaging infrastructure.

---

## 1. Code Review Focus Areas

Reviewers must evaluate changes across several critical architectural and logic boundaries:

### A. Downstream Patch Management & Upstream Parity (`toolchain/llvm_android/patches/`)
* **Minimal Downstream Divergence**: Downstream patches must be strictly minimized. Every patch added to `toolchain/llvm_android/patches/` must reference an upstream LLVM GitHub Pull Request URL (`Pull Request: github.com/llvm/llvm-project/pull/<PR>`) or upstream commit SHA (`cherry/<full_sha>.patch`).
* **Android-Only Patches**: Patches that cannot be merged upstream require explicit documentation justifying downstream divergence and must reference an issue in the public issue tracker.
* **Manifest Version Range Bounds**: In `toolchain/llvm_android/patches/PATCHES.json` and `toolchain/llvm_android/patches/TOT.json`, entries must specify valid version bounds:
  * `version_range.from`: SVN revision where the patch was introduced or must begin applying.
  * `version_range.until`: SVN revision when the patch landed upstream or was superseded. `until` must be strictly greater than `from`. When the toolchain rolls past `until`, the patch is automatically skipped.
* **Automated Generation**: Patch CLs must be created via `toolchain/llvm_android/cherrypick_cl.py` to ensure consistent metadata, proper sort order, and adherence to `toolchain/llvm_android/cherrypick_cl_hook.py`.

### B. Multi-Host Build Matrix & Sysroot Isolation (`toolchain/llvm_android/src/llvm_android/configs.py`)
* **Host Compatibility**: The toolchain supports Linux (`glibc 2.17` and `musl`), macOS (universal Mach-O `arm64` and `x86_64`), and Windows (`MinGW-w64` and `MSVC`). Changes to build logic or flags must never break non-Linux hosts. Use explicit host guards (`hosts.Host.Linux`, `hosts.Host.Darwin`, `hosts.Host.Windows`).
* **Hermetic Sysroot Anchoring**: Compiler and runtime builds must anchor headers and libraries to hermetic prebuilts (`prebuilts/gcc/`, `prebuilts/build-tools/sysroots/`, `paths.SYSROOTS`). Never allow unmanaged system headers or libraries from developer host environments to leak into builds.
* **Debug & Reproducibility Prefix Mapping**: All target configurations must preserve `-ffile-prefix-map={paths.ANDROID_DIR}/=` and `-fdebug-prefix-map` to ensure local workspace directories do not contaminate prebuilt binaries or debug symbols.

### C. Multi-Stage Pipeline & Optimization Strategy (`toolchain/llvm_android/do_build.py`, `builders.py`)
* **Stage Separation**:
  * **Stage 1 (Bootstrap)**: Statically links C++ runtimes (`-static-libstdc++`, `-static-libgcc`) and Zstd (`libzstd.a`) to build an unoptimized host compiler without dynamic glibc version dependencies. Assertions and testing are disabled by default.
  * **Stage 2 (Production)**: Built by Stage 1 using ThinLTO (`LLVM_ENABLE_LTO=Thin`), Profile-Guided Optimization (`--pgo`), Machine Learning Guided Optimization (`--mlgo`), and BOLT (`--bolt`).
* **Linker Job Concurrency**: ThinLTO parallel link jobs must be bounded (`LLVM_PARALLEL_LINK_JOBS = min(multiprocessing.cpu_count() // 2, 16)`) to avoid workstation and CI memory exhaustion.
* **Musl Host Memory Scaling**: Linux musl host builds must bundle `libjemalloc5.so` and configure `DT_RUNPATH` to `$ORIGIN/../lib` to mitigate multi-threaded ThinLTO heap lock contention and memory fragmentation.
* **BOLT Post-Link Passes**: Binary layout optimizations (`-reorder-blocks=ext-tsp`, `-reorder-functions=cdsort`, `-split-functions`) must only be applied to final Stage 2 binaries after branch trace collection.

### D. Target Runtime Libraries & ABI Segregation (`DeviceLibcxxBuilder`, `LibUnwindBuilder`, `BuiltinsBuilder`)
* **Platform vs. NDK Segregation**:
  * **Platform Runtimes** (`platform`, `platform_noexcept`): Target the Android OS (minimum API 30+). Dynamically link to the system unwinder exported by Bionic's `libc.so` (`-unwindlib=none`), enable packed dynamic relocations (`-Wl,--pack-dyn-relocs=android+relr`), and statically link the demangler. `platform_noexcept` statically links `c++_static_noexcept.a` for early boot and the Bionic dynamic loader.
  * **NDK Runtimes** (`ndk`): Target third-party apps (minimum API 23+). Must use the dedicated ABI namespace `__ndk1` (`LIBCXX_ABI_NAMESPACE=__ndk1`) to prevent One Definition Rule (ODR) collisions between app dependencies, and link hermetic `libunwind.a`.
* **Symbol Visibility**:
  * Builtins compiled for the NDK must hide internal symbols (`COMPILER_RT_BUILTINS_HIDE_SYMBOLS=TRUE`).
  * Platform builtins for ARM32 and x86 must provide exported variants (`-exported`) so `libc.so` can re-export legacy compiler builtins.
  * `libunwind` must provide `libunwind-exported.a` with frame header caching for platform libc, while NDK `libunwind.a` hides symbols and disables frame header caching to maintain backward compatibility across older Android releases.

### E. Compiler Wrappers & Bisection Infrastructure
* **Toolchain Wrappers**: Production compilers install the Go `llvm_android_wrapper` as `clang` and `clang++`, intercepting flags for remote build execution (RBE), bisection, and clang-tidy. Direct symlinks like `clang-cl` point directly to `clang-real` to preserve MSVC compatibility.
* **Bisection Support**: Modifications affecting wrapper flags or binary execution must maintain compatibility with `toolchain/llvm_android/bisect_driver.py` and `toolchain/llvm_android/bisect_build.py`.

---

## 2. Anti-Patterns & Common Pitfalls

Reviewers should flag the following recurring issues:

### A. Non-Hermetic Python Execution
* **Anti-Pattern**: Invoking Python scripts with system `/usr/bin/python3` or directly running `toolchain/llvm_android/do_build.py`.
* **Correct Practice**: Always launch through `toolchain/llvm_android/build.py`, which invokes `toolchain/llvm_android/py3_utils.py` to bind execution strictly to the hermetic prebuilt Python runtime (`prebuilts/build-tools/path/<host>/python3`). Never introduce third-party Python module dependencies outside the checked-in standard library.

### B. Patch Manifest Inconsistencies & Invalid Ranges
* **Anti-Pattern**: Manually editing `toolchain/llvm_android/patches/PATCHES.json` without verifying patch formatting, creating invalid version intervals (e.g., `until <= from`), or failing to run `toolchain/llvm_android/cherrypick_cl.py`.
* **Pitfall**: Applying revert patches out of chronological order. Reverts must always be sorted with the most recent commit reverted first to avoid patch conflicts in `git-am`.
* **Pitfall**: Leaving stale patches in the queue after a compiler roll instead of purging expired patches via `toolchain/llvm_android/trim_patch_data.py`.

### C. Host Path Leakage in Prebuilts and Metadata
* **Anti-Pattern**: Hardcoding absolute workstation paths or unmapped directory references in CMake flags, environment variables, or toolchain wrapper inputs (`bin/remote_toolchain_inputs`).
* **Correct Practice**: Rely strictly on `toolchain/llvm_android/src/llvm_android/paths.py` relative resolution, `$ORIGIN` runtime library paths, and `-ffile-prefix-map`.

### D. Packaging Regressions Under Conditional Flags
* **Anti-Pattern**: Generating backwards-compatibility symlinks (such as `libc++.so.1` or `libc++abi.so.1`) unconditionally during packaging without guarding on `with_runtimes`.
* **Pitfall**: When `--skip-runtimes` is active, target runtime directories do not exist; un-guarded directory accesses cause packaging failures (`FileNotFoundError`).
* **Pitfall**: Forgetting Windows dual-library requirements: MinGW linkers expect `libclang.dll.a`, while MSVC tools and Rust bindings expect `libclang.lib`. Both must be produced and packaged.

### E. 16 KB Page Alignment Omissions
* **Anti-Pattern**: Introducing new 64-bit Android device target configurations without enforcing 16 KB page alignment.
* **Correct Practice**: All 64-bit Android targets (`AndroidAArch64Config`, `AndroidX64Config`, `AndroidAArch64LFIConfig`) must explicitly pass:
  ```
  -Wl,-z,max-page-size=16384
  -Wl,-z,common-page-size=16384
  -D__BIONIC_NO_PAGE_SIZE_MACRO
  ```
  Omitting these options causes segmentation faults and relocation errors on 16 KB Android kernels.

---

## 3. Invariants & Safety Mandates

Reviewers must reject any change that violates these foundational system invariants:

### A. Non-Execute-Only (.text) Segments on AArch64 Runtimes
* **Mandate**: Shared runtime libraries on AArch64 (`libclang_rt.*.so`, `libc++.so`) **MUST NEVER** be marked execute-only (`XOM`). Executable segments must possess both Read and Execute permissions (`flags != "E"`).
* **Rationale**: Hardware-assisted AddressSanitizer (HWASan) tag checks and literal pools reside inside `.text` executable segments. Execute-only protection prevents constant pool lookups, resulting in catastrophic segmentation faults at runtime.
* **Enforcement**: `check_execute_only_runtime_libraries()` in `toolchain/llvm_android/do_build.py` programmatically parses ELF program headers of all packaged AArch64 runtime libraries and halts packaging if execute-only segments are detected.

### B. Arm64 Security Baseline: PAC and BTI
* **Mandate**: All 64-bit ARM device target compilations must enforce `-mbranch-protection=standard`.
* **Rationale**: This enables Pointer Authentication (PAC return address signing with Key A via `-msign-return-address=non-leaf`) and Branch Target Identification (BTI landing pad instructions `bti c`/`bti j`), preventing control-flow hijacking and ROP/JOP attacks.

### C. Fortify Source Level 3 & Stack Protection
* **Mandate**: All Android target runtime libraries built by `LLVMRuntimeBuilder` must enforce `-D_FORTIFY_SOURCE=3` and `-fstack-protector-strong`.
* **Rationale**: Fortify Level 3 leverages Clang's `__builtin_dynamic_object_size` to perform runtime buffer boundary verification across dynamically sized objects and pointer arithmetic.

### D. Lightweight Fault Isolation (LFI) Sandboxing Boundaries
* **Mandate**: When compiling LFI sandbox targets (`aarch64_lfi-linux-android`), the compiler must enforce:
  1. Confinement to a 4 GB virtual address space.
  2. Register reservation: `x27` as the sandbox base pointer, with `w26` and `w28` masking index offsets before memory loads and stores.
  3. Disabling outline atomics (`-mno-outline-atomics`) to prevent atomic helper calls from escaping the sandbox.
  4. Linking strictly against minimal stub definitions (`toolchain/llvm_android/lfi/libc_symbols.txt`, `libdl_symbols.txt`).

### E. Relocatability and RPATH Integrity
* **Mandate**: Host binaries and shared libraries must link with relative RPATHs (`$ORIGIN` and `$ORIGIN/../lib`) and never contain absolute dynamic linker references. Prebuilts must operate identically regardless of install prefix.

---

## 4. Verification & Testing Standards

Before approving any change to `toolchain/llvm_android`, reviewers must verify that the following test gates have passed:

### A. Pre-Upload Linting and Hook Validation
All CLs must pass repository pre-upload checks:
```bash
# Run pre-upload checks manually or verify via repo upload
pylint --rcfile=toolchain/llvm_android/pylintrc toolchain/llvm_android/*.py
python3 toolchain/llvm_android/cherrypick_cl_hook.py "<commit_message>" <modified_files>
```

### B. Patch Queue Sanity Checks
Whenever `toolchain/llvm_android/patches/PATCHES.json` or `TOT.json` is modified:
```bash
# Verify JSON schema, version intervals, and patch file existence (import context adds src/ to sys.path)
python3 -c "import context; from llvm_android.patch_utils import PatchList; assert PatchList.load_from_file('PATCHES.json').check_patches()"
python3 -c "import context; from llvm_android.patch_utils import PatchList; assert PatchList.load_from_file('TOT.json').check_patches()"

# Verify patches apply cleanly via both git-am and standard patch
python3 -c "import context; from llvm_android import source_manager; source_manager.setup_sources(git_am=True); source_manager.setup_sources()"
```

### C. Toolchain Build Smoke Tests
* **Stage 1 Fast Sanity**:
  ```bash
  python3 toolchain/llvm_android/build.py --bootstrap-build-only
  ```
  Validates that host bootstrap toolchain, CMake scripts, and static dependencies (`zstd`) configure and build cleanly without running long Stage 2 optimization pipelines.
* **Stage 2 Build Verification**:
  ```bash
  # For logic or configuration changes
  python3 toolchain/llvm_android/build.py --no-lto --no-mlgo --skip-tests
  ```
  Verifies that Stage 2 Clang, LLD, target sysroots, device runtimes, and packaging routines finish with zero errors.

### D. Upstream Test Suite Regression Testing
When modifying compiler options, patches, or builder definitions:
```bash
# Stage 2 regression tests (check-llvm, check-clang, check-clang-tools) execute automatically during standard Stage 2 builds:
python3 toolchain/llvm_android/build.py

# To selectively force test execution against the Stage 1 bootstrap compiler (for bootstrap diagnostics):
# python3 toolchain/llvm_android/build.py --run-tests-stage1
```
Ensures that standard LLVM regression tests (`check-llvm`, `check-clang`, `check-clang-tools`) pass without regressions.

### E. Platform Integration & Device Qualification (`do_test_compiler.py`, `test_toolchain.py`)
* **Platform Build Test**:
  ```bash
  python3 toolchain/llvm_android/do_test_compiler.py <android_root> \
      --clang-path out/install/linux-x86/clang-dev \
      --build-only -t aosp_arm64-trunk_staging-userdebug
  ```
  Confirms that the newly generated compiler successfully builds Android platform targets without unexpected warnings or compile-time failures.
* **Clang-Tidy Verification**:
  Run `do_test_compiler.py` with `--with-tidy` to ensure the compiler wrapper intercepts and invokes clang-tidy without errors.
* **Device Benchmark Qualification**:
  For compiler updates or backend optimization changes, execute on-device benchmarking suites via `toolchain/llvm_android/test_toolchain.py`. Connected devices must be initialized using `toolchain/llvm_android/prep_dut_for_test.sh` to lock CPU governors and eliminate thermal throttling variations.

---

> Recorded Revision Hash: c58dd95f2b4669ed109b04b9a2b8e73e1f6f98ef
