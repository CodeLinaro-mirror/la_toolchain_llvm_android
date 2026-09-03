# Code Review Guide for `toolchain/llvm_android/kokoro`

This guide establishes the review criteria, security mandates, operational invariants, anti-patterns, and verification standards for the Continuous Integration (CI) configuration, container runtime execution, and downstream Android integration pipelines located in `toolchain/llvm_android/kokoro`.

---

## 1. Code Review Focus Areas

Reviewers must evaluate changes across several critical operational, security, and architectural boundaries:

### A. Unprivileged Container Execution & BCID L3 Compliance (`common.cfg`)
* **BCID Level 3 Security Restrictions**: Kokoro builders enforce Build Chain Integrity Daemon (BCID) Level 3 compliance. Under BCID L3, containers must run unprivileged. Changes to `toolchain/llvm_android/kokoro/common.cfg` must **NEVER** re-introduce `docker_privileged: true`.
* **Unprivileged User Context**: The container runtime is configured with `docker_user: "nobody"`. All build orchestration scripts must assume an unprivileged host execution environment lacking `CAP_SYS_ADMIN` and access to host devices.
* **Sandbox Limitations**: Because nested user and PID namespaces are disallowed in unprivileged Docker containers, containerized sandboxing utilities (such as NSJail) cannot function. Build targets or genrules requiring nested namespaces (e.g., certain secure VM firmware targets) must be explicitly disabled or bypassed during CI runs.

### B. User Impersonation & Workspace UID/GID Remapping (`llvm_build.sh`)
* **Host Volume Ownership Alignment**: When containers initialize under root (`$EUID == 0`), files created in the workspace volume mount inherit root ownership. This causes subsequent workspace cleanups and host-side artifact archiving to fail with permission denied errors.
* **Dynamic Remapping Sequence**: In `toolchain/llvm_android/kokoro/llvm_build.sh`, the script must check `$EUID`:
  ```bash
  if (( $EUID == 0 )); then
    LOCAL_UID=`stat -c '%u' ${TOP}`
    LOCAL_GID=`stat -c '%g' ${TOP}`
    groupadd -g ${LOCAL_GID} build
    useradd -u ${LOCAL_UID} -g ${LOCAL_GID} -d ${TOP} build
    su build -c $0 $@
    exit 0
  fi
  ```
  Reviewers must verify that any new build scripts or wrapper entry points preserve this UID/GID detection and `su` delegation before creating build directories or invoking build processes.

### C. Explicit SCM Symlink Reconstruction (`main-plus-llvm_build.sh`)
* **Repo vs. Explicit SCM Checkout**: Standard Android builds rely on `repo` to create necessary top-level symlinks in `build/` pointing into `build/make/`. Kokoro uses explicit SCM checkout, which fetches repositories independently without running the `repo` manifest link steps.
* **Mandatory Symlink Generation**: Prior to invoking compiler tests or Android platform builds, `toolchain/llvm_android/kokoro/main-plus-llvm_build.sh` must reconstruct these symlinks:
  ```bash
  for f in CleanSpec.mk buildspec.mk.default core envsetup.sh target tools; do
    ln -sf make/$f build/$f
  done
  ```
  Reviewers must reject any integration build script modifications that omit this symlink reconstruction, as builds will immediately fail looking for `build/core` or `buildspec.mk`.

### D. Top-of-Tree (ToT) Patches Lifecycle & Hygiene (`tot-patches/`)
* **Temporary Compatibility Stopgaps**: Upstream LLVM development moves continuously at Top-of-Tree, introducing new language constraints, stricter C++ standard conformance rules, and API changes. Android platform release branches remain locked to specific milestones. The `toolchain/llvm_android/kokoro/tot-patches/` directory houses transient patches required to keep locked Android platform trees building against experimental or ToT compilers.
* **Patch Path Normalization (`-p1` from `$TOP`)**: All patches placed in `toolchain/llvm_android/kokoro/tot-patches/` must be generated relative to the top of the Android checkout (`TOP`). They must apply cleanly using `patch -p1 < ${filename}` from `${TOP}`. Sub-repository relative paths (e.g., paths omitting `toolchain/` or `external/`) break the automated iteration loop.
* **Deprecation and Retirement Rules**:
  * Every patch in `tot-patches/` must reference an upstream tracking issue or platform bug.
  * When upstream fixes land in the Android platform baseline (such as following a quarterly platform release roll), the temporary patch **MUST** be promptly purged.
  * Patches must be self-contained and not depend on interactive user prompts during `patch` execution.

### E. Multi-Architecture Matrix & Sanitizer Coverage (`*.cfg`)
* **Configuration Coverage**: Toolchain validation must span the full matrix of production and sanitizer configurations:
  * Baseline ARM64: `toolchain/llvm_android/kokoro/aosp_cf_arm64_phone.cfg`
  * Full MTE (Memory Tagging Extension): `toolchain/llvm_android/kokoro/aosp_cf_arm64_phone_fullmte.cfg`
  * HWASan (Hardware-assisted AddressSanitizer): `toolchain/llvm_android/kokoro/aosp_cf_arm64_phone_hwasan.cfg`
  * RISC-V 64-bit: `toolchain/llvm_android/kokoro/aosp_cf_riscv64_phone.cfg`
  * x86_64: `toolchain/llvm_android/kokoro/aosp_cf_x86_64_phone.cfg`
* **Test Invocation Parameters**: Integration scripts must invoke `toolchain/llvm_android/test_compiler.py` with:
  * `--build-only`: CI builds focus on compilation validity and build break detection.
  * `--target ${AOSP_BUILD_TARGET}-aosp_current-userdebug`: Binds to the supported platform release target.
  * `--module sync`: Enforces platform sync targets for quick compiler verification.
  * `--clang-package-path ${KOKORO_GFILE_DIR}`: Ingests the prebuilt Clang package distributed via Kokoro GFile storage.

### F. Artifact Scoping & Builder Timeout Management
* **Strict Artifact Scoping**:
  * Toolchain builds (`linux.cfg`, `linux-tot.cfg`): Target `git/dist/*` to preserve deployable compiler packages.
  * Integration builds (`aosp_cf_*.cfg`): Must restrict artifact harvesting strictly to `git/out/error.log`. Archiving full distribution or output directories in Android integration builds causes severe rsync overhead, stalls the worker, and exhausts storage.
* **GCS Destination Root**: All artifacts must upload to the designated storage bucket `android-llvm-kokoro-ci-artifacts`.
* **Execution Timeouts**: Platform builds must enforce `timeout_mins: 240`. Normal builds finish well within 180 minutes; excessive timeouts prevent timely cancellation of hung build jobs.

---

## 2. Anti-Patterns & Common Pitfalls

Reviewers must flag and reject any CL containing the following patterns:

### A. Re-enabling Privileged Docker Mode
* **Anti-Pattern**: Setting `docker_privileged: true` in `toolchain/llvm_android/kokoro/common.cfg` to resolve namespace or permission errors.
* **Correct Practice**: Resolve permissions through unprivileged UID/GID remapping or bypass nested sandboxes that require kernel capabilities. Privileged containers violate BCID Level 3 compliance and will fail security audits.

### B. Workspace Root File Ownership Pollution
* **Anti-Pattern**: Omitting the UID/GID remapping check in shell scripts and executing build tools directly as root in the container.
* **Pitfall**: Any file created in mounted host directories remains owned by `root:root`. Subsequent CI phases or host cleanup routines fail with permission denied errors, corrupting shared builder workspaces.

### C. Non-Hermetic Python Invocation
* **Anti-Pattern**: Executing `python3` from the system environment (`/usr/bin/python3`) inside Kokoro build scripts.
* **Correct Practice**: Explicitly invoke the hermetic prebuilt Python binary:
  ```bash
  $TOP/prebuilts/python/linux-x86/bin/python3 toolchain/llvm_android/test_compiler.py ...
  ```
  Host system Python packages can drift, introducing subtle build discrepancies or missing dependency errors.

### D. Subproject-Relative or Malformed `tot-patches`
* **Anti-Pattern**: Creating patches relative to internal git subtrees (e.g., `git format-patch` executed inside `external/libcxx/` without path adjustments).
* **Pitfall**: When `toolchain/llvm_android/kokoro/main-plus-llvm_build.sh` applies the patch from `${TOP}` with `patch -p1`, the file paths fail to match the top-level tree layout, causing immediate CI build failures.

### E. Stale Patch Accumulation
* **Anti-Pattern**: Merging temporary patches into `tot-patches/` and neglecting to track them for removal once platform releases merge upstream changes.
* **Pitfall**: Overlapping, stale patches eventually conflict with mainline branch changes, causing build breaks during future tree syncs.

### F. Over-Broad Artifact Globs in Integration Jobs
* **Anti-Pattern**: Specifying `git/out/*` or `git/dist/*` inside `toolchain/llvm_android/kokoro/aosp_cf_*.cfg`.
* **Pitfall**: Archiving Android build trees transfers dozens of gigabytes over the network, leading to Kokoro worker timeouts and false-positive test failures.

### G. Omitting SCM Symlink Reconstruction
* **Anti-Pattern**: Adding new entry scripts for Android build testing without replicating the `ln -sf make/$f build/$f` loop.
* **Pitfall**: Builds fail during early build system initialization with errors regarding missing `CleanSpec.mk` or `build/core`.

---

## 3. Invariants & Safety Mandates

Reviewers must strictly enforce the following non-negotiable invariants:

### A. BCID Level 3 Unprivileged Container Mandate
* **Mandate**: All Kokoro build jobs must execute in an unprivileged container environment (`docker_privileged` omitted or false).
* **Rationale**: Security boundary enforcement for the automated build supply chain.

### B. Hermetic Python Runtime Guarantee
* **Mandate**: All build invocations calling Python scripts (`build.py`, `test_compiler.py`) must invoke `$TOP/prebuilts/python/linux-x86/bin/python3`.
* **Rationale**: Prevents host container Python version drift from compromising build determinism.

### C. Workspace Ownership Preservation
* **Mandate**: Any containerized build script executing as root must drop privileges via `su` to a dynamically generated user matching the host UID/GID of `${TOP}`.
* **Rationale**: Guarantees all created artifacts and directories are cleanly readable and removable by the host CI agent.

### D. Root-Relative `-p1` Patch Uniformity
* **Mandate**: Every patch in `toolchain/llvm_android/kokoro/tot-patches/` must apply cleanly from `${TOP}` with `-p1`.
* **Rationale**: The build driver automatically iterates over `tot-patches/*.patch` without per-patch parameter customization.

### E. Targeted Artifact Minimization
* **Mandate**: Integration builds must only archive `git/out/error.log`. Toolchain builds must only archive `git/dist/*`.
* **Rationale**: Protects storage infrastructure and prevents CI upload timeout aborts.

### F. Deterministic SCM Build Symlink Provisioning
* **Mandate**: All explicit SCM Android build entry points must recreate the standard `build/make` symlinks before triggering `soong_ui` or `make`.
* **Rationale**: Android build systems require symlinks in `build/` that are not generated outside `repo` checkouts.

---

## 4. Verification & Testing Standards

Before submitting changes to `toolchain/llvm_android/kokoro`, authors must complete the following verification steps:

### A. Local Container Validation
* Launch the production container locally using `toolchain/llvm_android/docker/prod_env.sh` to replicate the unprivileged Kokoro environment:
  ```bash
  toolchain/llvm_android/docker/prod_env.sh
  ```
* Ensure UID and GID mapping operates cleanly and permissions inside `/tmpfs/src/git` match the host workstation owner.

### B. Patch Dry-Run Verification
* For any added or modified patch in `tot-patches/`, execute a dry run from the Android repository root:
  ```bash
  patch -p1 --dry-run < toolchain/llvm_android/kokoro/tot-patches/<patch_name>.patch
  ```
* Verify that the patch applies cleanly with zero offset warnings or rejected hunks.

### C. Integration Test Compiler Dry-Run
* Test the integration workflow using `toolchain/llvm_android/test_compiler.py`:
  ```bash
  prebuilts/python/linux-x86/bin/python3 \
    toolchain/llvm_android/test_compiler.py --build-only \
    --target aosp_cf_arm64_phone-aosp_current-userdebug \
    --module sync \
    --clang-package-path <path_to_clang_package_dir> .
  ```
* Confirm that missing SCM symlinks are present and the build proceeds past initial Soong bootstrap.

### D. Kokoro Configuration Proto Syntax Check
* Validate that all modified `.cfg` files follow the Kokoro build configuration protobuf schema:
  * Verify all string literals are enclosed in quotes.
  * Check that `build_file` references valid relative repository paths (e.g., `git/toolchain/llvm_android/kokoro/...`).
  * Ensure `timeout_mins` does not exceed 240 minutes.

---

> Recorded Revision Hash: c58dd95f2b4669ed109b04b9a2b8e73e1f6f98ef
