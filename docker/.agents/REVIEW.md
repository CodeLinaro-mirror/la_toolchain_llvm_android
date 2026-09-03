# Code Review Guidelines for Android LLVM Docker Environment

This document defines review criteria, architectural invariants, common pitfalls, and verification standards for changes to the Docker build environment located in `toolchain/llvm_android/docker`.

## 1. Code Review Focus Areas

- **Reproducibility & Pinned Dependencies**:
  - The base image in `toolchain/llvm_android/docker/Dockerfile` must be pinned to an immutable digest (`FROM ubuntu@sha256:...`) rather than mutable release tags (e.g., `ubuntu:24.04`) to prevent upstream image drift.
  - Debian/Ubuntu package archives must be pinned via a snapshot timestamp (`APT::Snapshot "YYYYMMDDTHHMMSSZ";` in `/etc/apt/apt.conf.d/50snapshot`). Any snapshot date bump must be audited to verify package consistency and compatibility.
  - Python dependencies in `toolchain/llvm_android/docker/requirements.txt` must include cryptographic hashes for all packages and target architectures (`--require-hashes`).
- **Image Layer Cleanliness & Footprint**:
  - Every `apt-get update` invocation must be paired in the same `RUN` layer with package installation and subsequent cleanup (`rm -rf /var/lib/apt/lists/*`).
  - Always use `--no-install-recommends` during `apt-get install` to avoid pulling unnecessary packages into the image.
  - Temporary files and pip caches (`/tmp/requirements.txt`, `/root/.cache/pip`) must be purged in the same `RUN` command where installation occurs.
- **Host Integration & Permission Mapping (`prod_env.sh`, `test_env.sh`)**:
  - The container runner scripts (`toolchain/llvm_android/docker/prod_env.sh` and `test_env.sh`) must map the host user UID and GID (`--user ${LOCAL_UID}:${LOCAL_GID}`) using temporary `/etc/passwd` and `/etc/group` files mounted read-only.
  - Reviewers must ensure containers never execute as `root` in shared or mounted directories to avoid corrupting file permissions in the host source checkout.
  - Workspace volume mounts must resolve the repository root (`BASE_DIR`) relative to the script location and mount it to `/tmpfs/src/git/` to match standard build environment layout.
- **Toolchain Target Dependencies**:
  - The container must provide all prerequisites needed across build targets:
    - 32-bit runtimes: `gcc-multilib`, `libc6-dev-i386-cross`.
    - MinGW / Windows cross-builds: `lbzip2`.
    - Android and LLVM build utilities: `git`, `make`, `patch`, `pkg-config`, `python3`, `python3-pip`, `repo`, `rsync`, `ssh`, `unzip`, `xz-utils`, `zip`, `libssl-dev`.
  - Machine learning optimization models in LLVM require TensorFlow. The environment variable `TENSORFLOW_INSTALL` in `toolchain/llvm_android/docker/Dockerfile` must accurately point to the Python site-packages directory (`/usr/local/lib/python3.12/dist-packages/tensorflow`).
- **Python Dependency Compilation**:
  - Updates to Python packages must be compiled via `pip-tools` (`pip-compile --generate-hashes`) from an input specification (`requirements.in`).
  - The `wheel` package must be excluded from `requirements.txt` to avoid collisions with the Ubuntu system-provided package.

## 2. Anti-Patterns & Common Pitfalls

- **Floating Image Tags or Moving Mirrors**: Using unpinned base images (`FROM ubuntu:latest`) or standard unversioned APT sources without snapshot pinning. This breaks build determinism across different build dates.
- **Manual Modification of `requirements.txt`**: Hand-editing Python package versions without regenerating hashes across supported wheels, which causes `--require-hashes` verification failures.
- **Retaining `wheel` in `requirements.txt`**: Leaving `wheel` in the compiled requirements file, causing conflicts during pip installation with the Ubuntu system package under `--break-system-packages`.
- **Interactive Prompts During Image Build**: Forgetting `DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC` when installing timezone-sensitive packages such as `tzdata`, causing container builds to hang.
- **Accidental Removal of Transitive Tools**: Removing packages previously provided by meta-packages (e.g. `xz-utils` or `lbzip2` after removing `build-essential`) without verifying all toolchain pipelines (intermediate tarball decompression, mingw packaging).
- **Hardcoding Local Paths or Infrastructure Secrets**: Embedding workstation-specific paths, private registry URLs, or internal build credentials in scripts or Dockerfiles.
- **Broken Path Resolution in Shell Scripts**: Modifying `SCRIPT_DIR` or `BASE_DIR` computations without testing execution from various working directories (e.g., running `./docker/test_env.sh` from the repository root vs. running `./test_env.sh` from `toolchain/llvm_android/docker`).

## 3. Invariants & Safety Mandates

- **Local & Remote Build Parity**: Building the image locally via `toolchain/llvm_android/docker/test_env.sh` must produce an environment identical to images deployed to build automation infrastructure.
- **Non-Root Execution**: Container processes must always run under the invoking user's UID and GID. No build artifact generated within a container mount should be owned by `root`.
- **Strict Cryptographic Integrity**: All external assets—Ubuntu base image, APT repository snapshot, and Python dependencies—must be cryptographically verified via sha256 digests or hash checks.
- **Canonical Workspace Path**: The repository root must always mount to `/tmpfs/src/git/` inside the container with `--workdir /tmpfs/src/git/` to preserve script and toolchain path assumptions.
- **Public & AOSP Hygiene**: Dockerfiles, helper scripts, and documentation in `toolchain/llvm_android/docker` must remain strictly public-safe and independent of private internal infrastructure.

## 4. Verification & Testing Standards

- **Local Image Build**: Run `toolchain/llvm_android/docker/test_env.sh` to build the container image from scratch, verifying that APT snapshots resolve and pip requirements pass hash checks cleanly:
  ```bash
  toolchain/llvm_android/docker/test_env.sh
  ```
- **Container Environment Checks**: Within the spawned test container, verify essential toolchain dependencies:
  - Verify Python and TensorFlow integration:
    ```bash
    python3 -c "import tensorflow as tf; print(tf.__version__)"
    test -d "${TENSORFLOW_INSTALL}"
    ```
  - Verify 32-bit compilation capability:
    ```bash
    echo 'int main() { return 0; }' | gcc -m32 -x c - -o /tmp/test32
    ```
  - Verify required build utilities:
    ```bash
    lbzip2 --version && xz --version && repo --version
    ```
  - Verify builder git configuration required by `repo`:
    ```bash
    git config user.name && git config user.email
    ```
- **Toolchain Bootstrap Build**: Run a bootstrap build inside the container to confirm that build tools function end-to-end:
  ```bash
  python3 toolchain/llvm_android/build.py --bootstrap-build-only
  ```

> Recorded Revision Hash: c58dd95f2b4669ed109b04b9a2b8e73e1f6f98ef
