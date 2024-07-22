## Android Clang/LLVM Toolchain


> Quick links:
> * [Android clang build instructions](https://android.googlesource.com/toolchain/llvm_android/+/main/BUILD.md)
> * [Android clang version history](https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+/master/README.md)

Android's clang toolchain is used to build the Android platform, kernel and is also part of the Android NDK.  It also builds various tools and projects in the Android ecosystem.  See [this](https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+/refs/heads/main/README.md) page for a list of current versions used by various projects.

Android clang follows a rolling release schedule based on upstream llvm-project's main branch.  It **does not** correspond to a numbered llvm-project release branch.


### Clang Version

Each clang prebuilt directory has a `clang_source_info.md` (starting with clang-r428724) that mentions the llvm-project commit from which this version is branched.  It also lists cherry-picks from upstream LLVM and downstream changes needed to qualify this prebuilt for the various Android use cases.


### Update Schedule

At any point of time, there is an in-progress attempt to release a new clang.  Due to the complexity of the Android code base and breaking changes from llvm-project, there is no guaranteed schedule or cadence in clang updates.

In practice, there have been an average of 3-4 updates a year (rougly new clang every 3-4 months) for the past several months.

> Subscribe to https://groups.google.com/g/android-llvm to get notified when a clang version is planned and when it is released.


### Android Clang Development

Android clang development happens in the `llvm-toolchain` repo branch in AOSP.  See [here](https://android.googlesource.com/toolchain/llvm_android/+/main/Build.md) for build instructions.

[aosp-llvm-toolchain](https://ci.android.com/builds/branches/aosp-llvm-toolchain/grid) is the public CI build of Android clang toolchain.

clang binaries from this CI branch are checked into three platform-specific projects:

*   [prebuilts/clang/host/linux-x86](https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/)
*   [prebuilts/clang/host/darwin-x86](https://android.googlesource.com/platform/prebuilts/clang/host/darwin-x86/)
*   [prebuilts/clang/host/windows-x86](https://android.googlesource.com/platform/prebuilts/clang/host/windows-x86/)
