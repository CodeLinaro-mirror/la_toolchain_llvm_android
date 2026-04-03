# Android LLVM Toolchain Docker Environment

This directory contains the Docker configuration and scripts used to maintain a
consistent build environment for the Android LLVM toolchain.

## Overview

The Docker image provides all necessary dependencies and tools to ensure
reproducible builds across different environments. It is currently used by:

*   **Android LLVM Build**: The primary build system for the toolchain.
*   **Android LLVM Kokoro Builder**: The CI/CD environment.
*   **LLDB Linux**: Linux-based LLDB testing (see
    [b/495585158](http://b/495585158)).

## Using the Production Environment

To enter the production Docker environment, run the `prod_env.sh` script from
the current directory:

```bash
./prod_env.sh [tag]
```

*   **`tag` (optional)**: Specify a specific image version (e.g., `r584948`). If
    omitted, the default `prod` tag is used.

### Troubleshooting Authentication

If you encounter `gcloud` permission errors when pulling the image,
re-authenticate and configure Docker:

```bash
gcloud auth login
gcloud auth configure-docker us-docker.pkg.dev
```

This is typically a one-time setup.

## Developing and Testing

To test modifications to the Docker environment (e.g., updating the `Dockerfile`
or `requirements.txt`):

1.  Make your changes to the configuration files.
2.  Run the test script to build and enter a local version of the image:
    `./test_env.sh`

## Deployment

New Docker images are built and deployed using Google Cloud Build.

1.  **Submit the build**: `gcloud builds submit --project=google.com:android-llvm-kokoro --timeout 3600s --tag us-docker.pkg.dev/google.com/android-llvm-kokoro/android-llvm/llvm-ubuntu`
2.  **Tag the image**: Once the build completes, tag the new image as `prod` in
    the
    [Cloud Artifact Registry](https://console.cloud.google.com/artifacts/docker/google.com/android-llvm-kokoro/android-llvm/llvm-ubuntu)
    to promote it to production.

## Managing Python Dependencies

The `requirements.txt` file is generated using `pip-tools`. To update or
regenerate it, perform the following steps from the repository root:

1.  Enter the production environment: `docker/prod_env.sh`
2.  Inside the container, install `pip-tools`: `pip install
    --break-system-packages pip-tools`
3.  Define the base requirements (e.g., in `requirements.in`): `echo
    tensorflow-cpu > requirements.in`
4.  Compile the requirements with hashes: `~/.local/bin/pip-compile --upgrade
    --generate-hashes --output-file=requirements.txt requirements.in`
5.  **Manual Cleanup**: Remove the `wheel` entry from the generated
    `requirements.txt`, as it conflicts with the system-installed version.
