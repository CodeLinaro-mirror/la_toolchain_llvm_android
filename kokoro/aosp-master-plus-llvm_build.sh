#!/bin/bash
set -e

TOP=$(cd $(dirname $0)/../../.. && pwd)

function cleanup {
  # Kokoro will rsync back everything created by the build. Since we don't care
  # about any artifacts on this build, nuke EVERYTHING at the end of the build.
  rm -rf "${TOP}"/*
}
trap cleanup EXIT

cd $TOP

# Fetch aosp-main repo
repo init -u https://android.googlesource.com/platform/manifest -b main --depth=1 < /dev/null
repo sync -c

# Apply local patches
for filename in toolchain/llvm_android/kokoro/tot-patches/*.patch; do
  patch -p1 < ${filename}
done

mkdir dist
DIST_DIR=dist \
OUT_DIR=out \
prebuilts/python/linux-x86/bin/python3 \
  toolchain/llvm_android/test_compiler.py --build-only \
  --target ${AOSP_BUILD_TARGET}-trunk_staging-userdebug \
  --module sync \
  --clang-package-path ${KOKORO_GFILE_DIR} .

