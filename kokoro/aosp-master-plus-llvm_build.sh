#!/bin/bash
set -e

TOP=$(cd $(dirname $0)/../../.. && pwd)

# Kokoro will rsync back everything created by the build. Since we don't care
# about any artifacts on this build, nuke EVERYTHING at the end of the build.
function cleanup {
  rm -rf "${TOP}"/*
}
trap cleanup EXIT

cd $TOP

# Fetch aosp-plus-llvm-master repo
repo init -u https://android.googlesource.com/platform/manifest -b main --depth=1 < /dev/null
repo sync -c

mkdir dist
DIST_DIR=dist OUT_DIR=out prebuilts/python/linux-x86/bin/python3 \
  toolchain/llvm_android/test_compiler.py --build-only --no-mlgo \
  --target ${AOSP_BUILD_TARGET}-trunk_staging-userdebug \
  --clang-package-path ${KOKORO_GFILE_DIR} .
