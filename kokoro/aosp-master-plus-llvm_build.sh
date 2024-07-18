#!/bin/bash
set -e

TOP=$(cd $(dirname $0)/../../.. && pwd)

function cleanup {
  if [ -f out/dist/logs/error.log ]; then
    cat out/dist/logs/error.log
  fi

  # Kokoro will rsync back everything created by the build. Since we don't care
  # about any artifacts on this build, nuke EVERYTHING at the end of the build.
  rm -rf "${TOP}"/*
}
trap cleanup EXIT

cd $TOP

# Fetch aosp-plus-llvm-master repo
repo init -u https://android.googlesource.com/platform/manifest -b main --depth=1 < /dev/null
repo sync -c

mkdir dist
USE_RBE=true \
RBE_instance="projects/android-dev-builds/instances/default_instance" \
RBE_service="remotebuildexecution.googleapis.com:443" \
RBE_use_gce_credentials=true \
RBE_CXX=false \
RBE_JAVAC=false \
RBE_D8=true \
RBE_D8_EXEC_STRATEGY=remote_local_fallback \
RBE_R8=true \
RBE_R8_EXEC_STRATEGY=remote_local_fallback \
RBE_METALAVA=true \
RBE_METALAVA_EXEC_STRATEGY=remote_local_fallback \
RBE_METALAVA_REMOTE_UPDATE_CACHE=false \
DIST_DIR=dist \
OUT_DIR=out \
prebuilts/python/linux-x86/bin/python3 \
  toolchain/llvm_android/test_compiler.py --build-only \
  --target ${AOSP_BUILD_TARGET}-trunk_staging-userdebug \
  --clang-package-path ${KOKORO_GFILE_DIR} .

