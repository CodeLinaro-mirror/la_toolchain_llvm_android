# Code Review Guidelines for Kernel Boot Tests (`kernel-boot-tests`)

This document defines code review criteria, architectural invariants, security rules, anti-patterns, and verification standards for changes to the standalone compiler qualification test harness located in `toolchain/llvm_android/kernel-boot-tests`. It is structured for both human engineers and automated review agents (such as `droid_reviewer`).

---

## 1. Code Review Focus Areas

### 1.1 Scope & Architectural Purpose
- **Harness Scope**: `toolchain/llvm_android/kernel-boot-tests` provides an isolated developer validation harness for cross-compiling upstream Linux kernels and verifying their bootability under QEMU emulation using candidate Clang toolchains.
- **Independence & Decoupling**: The harness operates outside standard Android platform build engines (Soong/Kati) and presubmit bots. Reviewers must ensure the subsystem remains self-contained, lightweight, and free of unnecessary dependencies on the Android build system.

### 1.2 Shell Script Rigor & Execution Discipline
- **Strict Error Handling**: All scripts must execute under strict Bash error modes (`set -eu` or `set -exu`):
  - `-e`: Exit immediately on command error or non-zero status.
  - `-u`: Treat unset variables as an error.
  - `-x`: Print trace of commands (where execution transparency is required for debugging).
- **Quote Hygiene & Word Splitting**: Every variable expansion representing a file path, URL, or compiler argument must be double-quoted (e.g., `"$1"`, `"$output_filename"`, `"$clang"`). Reviewers must reject unquoted variable expansions that risk word splitting or pathname expansion.
- **Argument Validation**: Scripts must validate incoming arguments explicitly before use (e.g., `${1:?Missing path to clang compiler}` or `test -n "$clang"`).
- **Subshell Containment & Directory Navigation**: Avoid loose `cd` commands that drift working directory state across scripts. Directory changes should be isolated in subshells `(cd ... && ...)` or include explicit return paths and trap handlers.

### 1.3 Path Canonicalization & Portability
- **Pre-Navigation Path Resolution**: Compiler binaries and input images are often specified via relative paths from the current working directory. Scripts must canonicalize all paths to absolute paths (`readlink -f "$1"`) before changing directories (e.g., prior to entering `linux/`).
- **POSIX Portability vs. Bashisms**: Preflight checks must avoid non-standard shell utilities. Prefer `command -v <cmd>` over `which <cmd>` for checking executable existence across diverse host environments.

### 1.4 Network Asset Ingestion & Cryptographic Verification
- **Immutable Checksums**: Every external artifact downloaded via network (`fetch.sh`) must require a mandatory, cryptographically strong checksum (`sha1sum` or `sha256sum`). Downloads without checksum verification must be rejected.
- **Secure Network Transports**: Network fetch operations must use HTTPS (`https://`) rather than unauthenticated, plaintext protocols (such as `git://`).
- **Shallow Cloning**: Kernel source acquisition via `arm64.build-kernel.sh` must use shallow git fetches (`--depth 1`) to minimize network bandwidth and local disk consumption.

### 1.5 QEMU Virtualization Model & Test Oracle Mechanics
- **Virtualization Target**: The harness tests ARM64 virtualization (`qemu-system-aarch64 -machine virt -cpu cortex-a57 -m 512 -nographic`).
- **UART Console Routing**: Boot arguments (`console=ttyAMA0 earlyprintk=ttyAMA0 root=/dev/vda`) must align strictly with the PL011 UART hardware emulation of the ARM `virt` machine model.
- **Test Oracle Contract**:
  - The guest userspace init script issues an explicit reboot command upon successful initialization.
  - QEMU is launched with `-no-reboot`, which instructs QEMU to exit cleanly with status code `0` when the guest triggers a reboot.
  - Reviewers must ensure the `-no-reboot` parameter and rootfs contract are preserved, as this serves as the primary automated pass/fail oracle.
- **Execution Timeout & Process Isolation**: QEMU must always be wrapped with `timeout` (e.g., `timeout 10s`) to terminate hung kernels or bootloader freezes with a non-zero exit code.
- **Terminal Unbuffering**: The harness uses `unbuffer` (from `expect`) to ensure serial console logs stream in real-time without pty buffer starvation.

---

## 2. Anti-Patterns & Common Pitfalls

- **Unquoted Variables in Shell Conditionals**:
  - *Anti-pattern*: `test -n $clang` or `test -e $kernel_image`.
  - *Consequence*: If `$clang` is unset or empty, `test -n $clang` reduces to `test -n`, which returns exit code `0` (success), silently bypassing validation. If a path contains spaces, `test -e $path` fails with `too many arguments`.
  - *Remedy*: Always quote variable expansions: `test -n "$clang"` and `test -e "$kernel_image"`.
- **Unquoted Array / Argument Forwarding**:
  - *Anti-pattern*: `fetch $@` in `fetch.sh`.
  - *Consequence*: Unquoted `$@` performs word splitting on arguments containing whitespace or shell metacharacters.
  - *Remedy*: Always use `fetch "$@"`.
- **Validating Checksums Post-Boot on Mutated Filesystems**:
  - *Anti-pattern*: Computing the cryptographic checksum of the uncompressed ext2 rootfs after booting QEMU.
  - *Consequence*: QEMU mounts the ext2 drive read-write (`-hda $rootfs`), mutating ext2 superblocks, mount counters, and journal timestamps during boot. Any post-boot checksum verification will fail.
  - *Remedy*: Always verify the checksum on the compressed archive (`rootfs.ext2.gz`) prior to extraction, and cache the uncompressed target (`[[ ! -e "$output_filename" ]]`).
- **Unencrypted Transport Protocols**:
  - *Anti-pattern*: Cloning from `git://git.kernel.org/...`.
  - *Consequence*: The plaintext `git://` protocol lacks transport-layer authentication and integrity, and it is routinely blocked by corporate network firewalls and proxy gateways.
  - *Remedy*: Use `https://android.googlesource.com/...` or approved HTTPS mirror.
- **Omission of Execution Timeouts**:
  - *Anti-pattern*: Running `qemu-system-aarch64` directly without `timeout`.
  - *Consequence*: A kernel panic, infinite spinlock loop, or initialization hang leaves the emulator running indefinitely, locking build nodes or developer terminals.
  - *Remedy*: Always enforce a hard execution ceiling via `timeout <duration>`.
- **Missing Cross-Compilation Host Dependencies**:
  - *Anti-pattern*: Assuming `aarch64-linux-gnu-` toolchain binaries (`as`, `ld`) or kernel build prerequisites (`bc`, `bison`, `flex`, `libssl-dev`) are available without validating them in `check-dependencies.sh`.
  - *Consequence*: `arm64.build-kernel.sh` fails deep into the kernel compilation stage with cryptic missing-tool errors.
  - *Remedy*: Expand preflight checks in `check-dependencies.sh` or adopt `LLVM=1` in the kernel make invocation where host GNU binutils are not available.
- **Polluting Git Workspace with Build Artifacts**:
  - *Anti-pattern*: Creating intermediate build files (`linux/`, `*.ext2`, `*.ext2.gz`) without registering them in `toolchain/llvm_android/kernel-boot-tests/.gitignore`.
  - *Consequence*: Large kernel trees and binary disk images get flagged as untracked files, leading to accidental commits into the toolchain repository.
  - *Remedy*: Maintain strict `.gitignore` rules for all generated artifacts.

---

## 3. Invariants & Safety Mandates

- **Mandatory Cryptographic Verification**:
  - Any external binary, image, or archive downloaded across the network MUST be validated against a known cryptographic digest (`sha1sum` or `sha256sum`) before extraction or execution.
- **Determinism of the Exit Oracle**:
  - The boot qualification test MUST produce a deterministic exit code: `0` for boot success (via guest reboot + `-no-reboot`), non-zero for failure, crash, or timeout. Custom console parsing scripts must never supersede this basic process exit contract.
- **Canonical Absolute Compiler Paths**:
  - The path to the candidate compiler passed to `qualify_clang.sh` or `arm64.build-kernel.sh` must be resolved to an absolute canonical path (`readlink -f`) prior to any directory changes.
- **Public & AOSP Data Minimization Mandate**:
  - Code, comments, commit messages, and documentation must strictly exclude internal corporate links (`go/`), internal bug numbers (`b/`), corporate email addresses/LDAPs, or non-public infrastructure names. All external references must point to public trackers, public Git repositories, or upstream projects.
- **Top-of-Tree Relative Paths**:
  - All documentation and review guidelines must reference files relative to the repository root (e.g., `toolchain/llvm_android/kernel-boot-tests/...`). Workstation-specific absolute paths are strictly forbidden.

---

## 4. Verification & Testing Standards

- **Static Analysis & Shellcheck Validation**:
  - All modified or newly introduced shell scripts must pass `shellcheck` with zero warnings:
    ```bash
    shellcheck toolchain/llvm_android/kernel-boot-tests/*.sh
    ```
  - Specific checks: verify no SC2086 (unquoted variables), SC2155 (masking return values), or SC2164 (unhandled cd failures).
- **Preflight Dependency Verification**:
  - Verify that host prerequisites are properly checked:
    ```bash
    ./toolchain/llvm_android/kernel-boot-tests/check-dependencies.sh
    ```
  - Ensure clear diagnostic output and non-zero exit code if any required tool is absent.
- **Asset Fetch & Integrity Smoke Test**:
  - Verify that `fetch.sh` correctly downloads, verifies, and decompresses test payloads:
    ```bash
    ./toolchain/llvm_android/kernel-boot-tests/fetch.sh \
      <rootfs-archive-url> \
      test.rootfs.ext2 \
      dbe4136f0b4a0d2180b93fd2a3b9a784f9951d10
    ```
  - Verify that re-running `fetch.sh` skips download when the uncompressed file already exists.
  - Verify that providing an invalid SHA checksum causes immediate failure and non-zero exit.
- **End-to-End Compiler Qualification Run**:
  - Execute full qualification against a built Clang binary:
    ```bash
    ./toolchain/llvm_android/kernel-boot-tests/qualify_clang.sh <path-to-clang>
    ```
  - Verify that the Linux kernel compiles cleanly (`linux/arch/arm64/boot/Image.gz` is produced).
  - Verify that QEMU boots to userspace and cleanly terminates within the 10-second timeout window with exit code `0`.
- **Working Tree Cleanliness**:
  - Verify that generated artifacts (`linux/`, `*.ext2`, `*.ext2.gz`) remain ignored by Git:
    ```bash
    git status --porcelain toolchain/llvm_android/kernel-boot-tests/
    ```
  - No untracked build artifacts should appear in the status output.

> Recorded Revision Hash: c58dd95f2b4669ed109b04b9a2b8e73e1f6f98ef
