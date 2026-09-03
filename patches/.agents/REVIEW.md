# Code Review Guidelines for Android LLVM Patches Subsystem

This document establishes code review criteria, governance policies, risk analysis, architectural invariants, and verification standards for changes to the patch management subsystem in `toolchain/llvm_android/patches`. It is intended for both human reviewers and automated review agents (such as `droid_reviewer`).

---

## 1. Code Review Focus Areas

### 1.1 Review Philosophy & Governance
- **Upstream-First Principle**: Every downstream patch in the Android LLVM compiler toolchain introduces ongoing maintenance overhead during compiler upgrades. Direct upstream acceptance into `llvm/llvm-project` is always the primary objective.
- **Patch Classification & Acceptance Criteria**:
  - **Upstream Cherry-Picks (`toolchain/llvm_android/patches/cherry/<sha>.patch`)**: Accepted only when the change has merged into upstream `llvm/llvm-project` or is actively progressing through upstream review in an open Pull Request. Patches must be added using `toolchain/llvm_android/cherrypick_cl.py`.
  - **Local Persistent Overrides (`toolchain/llvm_android/patches/*.patch`)**: Restricted strictly to Android-specific system requirements (e.g. Bionic C library integration quirks, NDK demangler library isolation, custom runtime CMake flag injection) or critical emergency hotfixes when upstream fixes cannot land in time for a platform release.
  - **Tip-of-Tree Overrides (`toolchain/llvm_android/patches/TOT.json`)**: Reserved exclusively for experimental fixes required when building against tip-of-tree LLVM (`is_llvm_next()`).
- **Lifecycle & Expiration Rules**:
  - Upstream cherry-picks must specify finite, bounded version intervals `[from, until)`. The `until` bound must match the upstream Subversion/Git commit sequence number. When the toolchain baseline advances past `until`, the patch naturally expires and is pruned via `toolchain/llvm_android/trim_patch_data.py`.
  - Local overrides (`until: null`) represent permanent maintenance liabilities. Reviewers must require clear architectural justification and an active plan for eventual upstreaming or deprecation.

### 1.2 Critical Review Checklist
- **Registry Metadata (`PATCHES.json` / `TOT.json`)**:
  - `rel_patch_path`: Must match the exact path relative to `toolchain/llvm_android/patches/`. Upstream cherry-picks must be placed in `cherry/`.
  - `version_range.from`: Must match the base toolchain SVN revision where the patch begins applying.
  - `version_range.until`: Must be populated with the upstream SVN revision for cherry-picks. Must be `null` only for permanent local patches.
  - `version_range` Invariant: When `until` is present, `from < until` must strictly hold. Equal or inverted bounds (`until <= from`) will fail validation.
  - `platforms`: Must explicitly define target platforms (standard value: `["android"]`).
  - `metadata.title`: Must summarize the change clearly. Upstream cherry-picks must follow the format `[UPSTREAM] <commit title> (#<PR>)`.
  - Deterministic Ordering: Patches must follow `PatchList.sort()` ordering—upstream cherry-picks sorted by ascending `until` version; open-ended upstream patches sorted next by `from` version; local overrides anchored at the end preserving relative order.
- **Git Unified Diff Hygiene**:
  - Patches must be generated in standard unified diff format (`git format-patch`).
  - Patch headers must include original author attribution, commit timestamp, commit message, and upstream tracking links (e.g. `Pull Request: github.com/llvm/llvm-project/pull/<PR>`).
  - Hunk cleanliness: Diffs must be minimal and tightly scoped. Verify no accidental whitespace reformatting of adjacent LLVM code, no leftover merge conflict markers (`<<<<<<<`, `=======`), and no unrelated file edits.
- **3-Way Merge Cleanliness & Rebase Evolution**:
  - Patches must apply cleanly both via `git am --3way` and the standard `patch` utility.
  - When updating patches across compiler rolls (`update-patches.py`), version suffixes increment (e.g. `<patch>-v2.patch`). Reviewers must inspect the diff between versions to ensure semantic intent was preserved and upstream refactorings were not accidentally overwritten.

---

## 2. Anti-Patterns & Common Pitfalls

- **Unbounded Cherry-Picks (`until: null`)**:
  - Omitting the `until` version ceiling on upstream cherry-picks causes them to persist indefinitely. Once the base compiler rolls past the upstream commit, the patch will attempt to re-apply already merged changes, triggering merge collisions or duplicate symbol definitions.
- **Orphaned or Unreferenced Patch Files**:
  - Committing `.patch` files into `toolchain/llvm_android/patches/` without adding them to `PATCHES.json`.
  - Removing an entry from `PATCHES.json` without deleting the associated `.patch` file, or leaving an entry in `PATCHES.json` whose file has been deleted. Both violate `PatchList.check_patches()`.
  - Referencing the same patch file across multiple entries in `PATCHES.json`.
- **Subtle ABI & Bionic Breakages**:
  - Modifying headers or runtime components in `libc++`, `libc++abi`, `libunwind`, or `compiler-rt` that alter exported symbol names, struct alignments, or memory layout across Android API levels and NDK consumers.
  - Assuming glibc-specific runtime behaviors (e.g. glibc pthread internals, non-standard printf format specifiers) that break Android Bionic or musl host environments.
  - Prematurely dropping legacy platform compatibility (e.g. removing `<stdatomic.h>` support before C++23).
- **Optimization Pipeline & Profile Disruption (PGO, BOLT, LTO)**:
  - Applying code-generation or middle-end optimization modifications that invalidate profile matching in Profile-Guided Optimization (PGO) or disrupt Link-Time Optimization (LTO).
  - Introducing binary layout changes that exceed post-link optimization thresholds in BOLT without adjusting allocation sizes.
- **Sanitizer & Security Mitigation Collisions**:
  - Altering compiler intrinsics or standard library algorithms without accounting for sanitizer instrumentation (ASan, HWASan, UBSan, integer sanitizers) or control-flow integrity (CFI).
  - Example: Failing to apply `_LIBCPP_NO_SANITIZE` to bitwise intrinsics (e.g. `__libcpp_blsr`) or iterator past-the-end pointer arithmetic, resulting in false-positive security crashes.
  - Regressing hardware security mitigations like PAC/BTI, SafeStack, or ShadowCallStack across architectures.
- **Manual Hand-Editing of `PATCHES.json`**:
  - Manually editing `PATCHES.json` without running `patch_utils.py`, leading to JSON formatting violations, broken sort keys, or duplicate records.

---

## 3. Invariants & Safety Mandates

- **Public & Upstream Provenance**:
  - Every patch must cite public provenance: an upstream Git commit SHA, an upstream GitHub Pull Request, or a public issue tracker URL (such as `github.com/android/ndk/issues/<id>`).
  - Patches, metadata, and commit messages must strictly exclude internal corporate links, internal bug numbers, private hostnames, or corporate usernames/LDAPs.
- **Strict Monotonic Bounds**:
  - For all bounded entries, `version_range.from < version_range.until` must hold unconditionally.
- **Dual-Engine Patch Application**:
  - Every patch registered in `PATCHES.json` must be capable of applying cleanly through both `git am --3way` and standard `patch`.
- **Sandbox Staging Isolation**:
  - Patches must never be applied in-place to `toolchain/llvm-project`. Staging must always take place in `out/llvm-project.tmp` via copy-on-write (`reflink`).
  - Source updates to `paths.LLVM_PATH` must use checksummed synchronization (`rsync -c --delete`) to ensure unmodified files preserve modification timestamps, preventing unnecessary Ninja rebuild cascades.
- **Registry & Disk 1:1 Correspondence**:
  - Every entry in `PATCHES.json` must resolve to an existing `.patch` file on disk, and every `.patch` file in `toolchain/llvm_android/patches/` (and its subdirectories) must be registered in exactly one entry in `PATCHES.json` or `TOT.json`.

---

## 4. Verification & Testing Standards

- **Metadata & Registry Integrity Verification**:
  - Validate `PATCHES.json` structure, bounds, file existence, and uniqueness:
    ```bash
    python3 -c "from llvm_android.patch_utils import PatchList; pl = PatchList.load_from_file(); assert pl.check_patches(), 'PATCHES.json validation failed'"
    ```
- **Dual-Engine Application Testing**:
  - Verify that the patch set applies cleanly in both Git 3-way merge mode and standard patch mode:
    ```bash
    python3 -c "from llvm_android import source_manager; source_manager.setup_sources(git_am=True); source_manager.setup_sources()"
    ```
  - Inspect `out/clang_source_info.md` to confirm that the new or updated patch appears under applied patches without failures or unexpected skips.
- **Bootstrap Compiler Build**:
  - Execute a stage 1 bootstrap build to ensure the patched LLVM source tree compiles cleanly with the host toolchain:
    ```bash
    python3 toolchain/llvm_android/build.py --bootstrap-build-only
    ```
- **Multi-Environment & Cross-Target Compatibility**:
  - For runtime library changes (`libc++`, `compiler-rt`, `libunwind`):
    - Verify target builds across Android architectures: `arm64`, `arm`, `x86_64`, and `riscv64`.
    - Verify host builds succeed across both Linux (glibc and musl) and Darwin platforms.
- **Presubmit CI & Commit Message Formatting**:
  - All changes must pass toolchain presubmit validation.
  - Commit messages generated by `toolchain/llvm_android/cherrypick_cl.py` or `update-patches.py` must include the upstream reference, automated generation notice, bug tracking link, and test field:
    ```text
    [patches] Cherry pick CLs for: <Summary of problem/feature>

    <commit_sha_short> <Commit Title> (#<PR_number>)

    This change is generated automatically by the script:
      cherrypick_cl.py --sha <commit_sha>

    Bug: github.com/llvm/llvm-project/issues/<issue>
    Test: presubmit
    ```

> Recorded Revision Hash: c58dd95f2b4669ed109b04b9a2b8e73e1f6f98ef
