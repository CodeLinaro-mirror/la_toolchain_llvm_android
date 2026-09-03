# Windows Platform Test Harness Code Review Guide

## 1. Code Review Focus Areas

This component provides the testing harness for validating Windows cross-compiled host binaries and libraries built in the Android Open Source Project (AOSP) on a Linux host using Wine (`toolchain/llvm_android/test/platform/run_windows_tests.sh`). Reviewers should focus on the following primary architectural and operational domains:

- **Component Scope & Dual-Architecture Coverage**:
  - *Multilib Support*: The harness targets both 32-bit (`windows_x86`) and 64-bit (`windows_x86_64`) Windows Portable Executable (PE) binaries.
  - *Validation Modes*: The test harness executes two distinct validation passes:
    1. **Smoke Tests (`run_smoke_tests`)**: Invokes executables with basic flags (typically `--help`) to verify dynamic link resolution, process initialization, and proper termination with expected exit codes.
    2. **Google Test Suites (`run_gtests`)**: Runs full native unit test binaries (`aapt2_tests.exe`, `build_version_test.exe`, `fastboot_test.exe`, `libaapt_tests.exe`, `libbase_test32.exe`/`libbase_test64.exe`, `libsplit-select_tests.exe`, `simpleperf_unit_test.exe`, `ziparchive-tests.exe`) and captures execution output to disk.

- **Dynamic Link Resolution & DLL Staging (`copy_dlls`)**:
  - *Staging Directory Isolation*: Windows dynamic library resolution depends on DLLs being colocated in the executable directory, current working directory, or on the Windows `Path`. The harness creates dedicated staging directories (`windows-test-dir/32` and `windows-test-dir/64`) and copies required runtime DLLs prior to test execution.
  - *MinGW & Cross-Runtime Dependencies*: Staged DLLs include C/C++ runtimes (`libwinpthread-1.dll` from `prebuilts/gcc/linux-x86/host/x86_64-w64-mingw32-4.8/`), core system libraries (`libbase.dll`, `liblog.dll`), compression libraries (`libz-host.dll`, `libziparchive.dll`, `liblzma.dll`), IPC/serialization (`libprotobuf-cpp-lite.dll`, `AdbWinApi.dll`), and compiler runtimes (`libclang_android.dll`, `libLLVM_android.dll`, `libbcc.dll`, `libbcinfo.dll`). Reviewers must verify that any new DLL dependencies added to Windows tools are explicitly staged.
  - *Test Data Staging*: Certain tests require data directories colocated with the test binary (e.g., `system/libziparchive/testdata` or `system/extras/simpleperf/testdata`). Reviewers must ensure test fixtures are staged alongside the test executables or passed via appropriate flags.

- **Wine Execution & Environment Variable Injection**:
  - *Windows `Path` vs. Linux `PATH`*: Under Wine on Linux, environment variables are case-sensitive. The harness passes `Path=$TMP_DIR_32 wine ...` or `Path=$TMP_DIR_64 wine ...`. This sets the Windows search path without overwriting the Linux host's `PATH` variable (which would break host commands like `wine` itself).
  - *Working Directory Assumptions*: Binary execution assumes invocation from the root of the Android checkout. Reviewers must ensure path arguments passed to Wine binaries (e.g., `-t system/extras/simpleperf/testdata`) resolve correctly from the Android build root.

- **Exit Code Assertions & Non-Zero Codes**:
  - *Smoke Test Exit Codes*: Windows CLI utilities do not universally return `0` when passed `--help`. Several utilities exit with code `1` or `2` when printing usage information (e.g., `aapt.exe` returns `2`, `dexdump.exe` returns `2`, `etc1tool.exe` returns `1`, `zipalign.exe` returns `2`). The harness defines entries as `<path>;<expected_exit_code>`. Reviewers must ensure exit code assertions match tool specifications.
  - *Unit Test Failure Tracking*: Several gtest binaries currently fail specific test cases when run under Wine emulation, resulting in non-zero exit codes (e.g., exit code `1`). Reviewers must verify that hardcoded non-zero exit code expectations do not mask genuine regressions.

- **Build System Intermediate Coupling**:
  - *Intermediate Path Fragility*: The script references intermediate build paths across Soong (`out/soong/.intermediates/...`) and legacy Make (`out/host/windows-x86/obj/...` and `out/host/windows-x86/obj64/...`). Reviewers must inspect changes to intermediate paths when modules migrate between build systems or when module variants change.

---

## 2. Anti-Patterns & Common Pitfalls

- **Overwriting Host `PATH` Instead of Wine `Path`**:
  - *Pitfall*: Changing `Path=$TMP_DIR` to `PATH=$TMP_DIR` or `export PATH=...`. In Linux shells, `PATH` is the host executable search path. Overwriting it prevents the shell from finding `wine`, `cp`, `rm`, `sed`, or other required utilities.
  - *Review Check*: Ensure the script strictly uses `Path=$TMP_DIR_<arch> wine ...` to supply the Windows loader search path without perturbing the host environment.

- **Masking Complete Test Suite Failures with Permissive Exit Codes**:
  - *Pitfall*: Specifying an expected exit code of `1` (e.g., `"libbase_test32.exe;1"`) without validating the test output text. If a regression causes the binary to crash immediately during initialization or fail 100% of tests, an assertion for exit code `1` will still pass.
  - *Review Check*: Reviewers must verify that changes expecting non-zero exit codes correlate with known, documented test failures in the generated log files rather than masking broader crashes.

- **Cross-Architecture DLL Contamination**:
  - *Pitfall*: Copying a 32-bit DLL into the 64-bit staging directory (`windows-test-dir/64`) or vice versa. When Wine attempts to load a 32-bit DLL into a 64-bit process, it aborts with `STATUS_INVALID_IMAGE_FORMAT` (`0xc000007b`).
  - *Review Check*: Verify that `dlls_32` only sources from 32-bit build directories (`windows_x86`, `obj`, `lib32`) and `dlls_64` only sources from 64-bit build directories (`windows_x86_64`, `obj64`, `bin`).

- **Unchecked Stderr Suppression Hiding Loader Failures**:
  - *Pitfall*: Redirecting both stdout and stderr to `/dev/null` during smoke tests (`2>/dev/null > /dev/null`). If a tool fails to start due to a missing DLL (`err:module:import_dll Library ... not found`) or Wine configuration error, the error output is completely discarded, making failure diagnosis difficult.
  - *Review Check*: Verify that failure handlers (`fail_panic_exit_code`) print sufficient diagnostics or retain logs so missing library imports can be identified immediately.

- **Linux vs. Windows Path and Case Sensitivity Mismatches**:
  - *Pitfall*: Windows filesystems are case-insensitive, but Linux filesystems under Wine are case-sensitive. Specifying mismatched casing in file names or DLL imports succeeds on native Windows but fails under Wine.
  - *Review Check*: Ensure all file names, directory paths, and command-line arguments match on-disk casing exactly.

- **Fragile Intermediate Path Coupling**:
  - *Pitfall*: Adding new Windows binaries by directly hardcoding deeply nested Soong intermediate paths without checking if the module has a standardized output location or packaging rule.
  - *Review Check*: Verify whether the target binary path is stable across Soong updates and build configurations.

---

## 3. Invariants & Safety Mandates

- **Strict Architecture Segregation**:
  - 32-bit (`x86`) and 64-bit (`x86_64`) Windows binaries, DLLs, and test outputs MUST remain strictly isolated in `$TMP_DIR/32` and `$TMP_DIR/64`. Cross-architecture linking or staging is strictly prohibited.
- **Tree-Root Anchoring (Relative Paths)**:
  - All test script invocations and file paths MUST be anchored to the Android build tree root (`$ANDROID_BUILD_TOP`). Absolute workstation paths are strictly prohibited in the script, review guidelines, and test configurations.
- **Hermetic Staging Directory Lifecycle**:
  - Staging directories (`windows-test-dir/`) MUST be completely wiped and recreated on every test execution via `clean_tmp_dirs` and `make_tmp_dirs` to prevent state contamination from previous runs.
- **Persistent Output Logging for Test Auditing**:
  - Every gtest execution MUST capture its stdout and stderr into a dedicated log file (`windows-test-dir/<arch>/<exe_basename>.txt`) to allow automated parsing and post-run regression analysis.
- **Public Safety & Data Minimization**:
  - No internal corporate URLs (`go/`), internal issue tracker identifiers (`b/`), internal LDAP usernames, or non-public build infrastructure configurations may appear in the test scripts, documentation, or commit messages.

---

## 4. Verification & Testing Standards

- **Host Prerequisites**:
  - Wine must be installed on the Linux host machine:
    ```bash
    sudo apt install wine64 wine32
    ```
  - For headless CI environments, ensure Wine does not attempt to launch interactive GUI prompts (e.g., configure `WINEDEBUG=-all` and isolate `WINEPREFIX`).

- **Build Prerequisites**:
  - Before running the test script, cross-compile the Windows host modules from the root of the Android source tree:
    ```bash
    m native-host-cross
    ```
  - Verify that the target binaries and DLLs exist in `out/soong/.intermediates/` and `out/host/windows-x86/`.

- **Executing the Test Suite**:
  - Run the test harness from the root of the Android checkout:
    ```bash
    bash toolchain/llvm_android/test/platform/run_windows_tests.sh
    ```
  - The script will copy 32-bit DLLs to `windows-test-dir/32`, 64-bit DLLs to `windows-test-dir/64`, run smoke tests, and execute gtest suites.

- **Validating Results & Known Failures**:
  - Output logs for each unit test are stored in `windows-test-dir/*/*.txt`.
  - Validate the list of known failing tests by extracting Google Test failure summaries:
    ```bash
    grep "listed below" windows-test-dir/*/*.txt | sed "s/32\// /g" | sed "s/64\// /g" | sort -k 2
    ```
  - Compare the output against the baseline of known Windows test limitations. Any newly failing test or unexpected exit code change must be investigated prior to approving CLs.

> Recorded Revision Hash: c58dd95f2b4669ed109b04b9a2b8e73e1f6f98ef
