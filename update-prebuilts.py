#!/usr/bin/env python3
#
# Copyright (C) 2017 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# pylint: disable=not-callable

"""Update the prebuilt clang from the build server."""

import argparse
import inspect
import logging
import os
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

import context  # pylint: disable=unused-import
from llvm_android import utils, paths


def logger():
    """Returns the module level logger."""
    return logging.getLogger(__name__)


class ArgParser(argparse.ArgumentParser):
    def __init__(self) -> None:
        super(ArgParser, self).__init__(
            description=inspect.getdoc(sys.modules[__name__]))

        self.add_argument(
            'build', metavar='BUILD',
            help='Build number to pull from the build server.')

        self.add_argument(
            '-b', '--bug', help='Bug to reference in commit message.')

        self.add_argument(
            '-br', '--branch', help='Branch to fetch from (or automatic).')

        self.add_argument(
            '--use-current-branch', action='store_true',
            help='Do not repo start a new branch for the update.')

        self.add_argument(
            '--skip-fetch',
            '-sf',
            action='store_true',
            default=False,
            help='Skip the fetch, and only do the extraction step')

        self.add_argument(
            '--skip-cleanup',
            '-sc',
            action='store_true',
            default=False,
            help='Skip the cleanup, and leave intermediate files')

        self.add_argument(
            '--overwrite', action='store_true',
            help='Remove/overwrite any existing prebuilt directories.')

        self.add_argument(
            '--no-validity-check', action='store_true',
            help='Skip validity checks on the prebuilt binaries.')

        self.add_argument(
            '--update-in-kernel-branch-dir',
            help="""Kernel branch directory. If given, update clang prebuilt
                    in the kernel branch, like aosp-common-android16-6.12""")

        host_choices = ['darwin-x86', 'linux-x86', 'windows-x86']
        self.add_argument(
            '--host', metavar='HOST_OS',
            choices=host_choices,
            help=f'Update prebuilts only for HOST_OS (one of {host_choices}).')

        self.add_argument(
            '--repo-upload', action='store_true',
            help='Upload prebuilts CLs to gerrit using \'repo upload\'')

        self.add_argument(
            '--hashtag', metavar='HASHTAGS',
            help='Extra hashtags (comma separated) during \'repo upload\'')

    def parse_args(self, args=None, namespace=None) -> argparse.Namespace:
        args = super().parse_args(args, namespace)
        if args.update_in_kernel_branch_dir:
            assert not args.overwrite, """Overwriting clang prebuilt in the
                kernel branch isn't allowed in order to avoid affecting release
                branches."""
            assert args.host == 'linux-x86', """Only need linux-x86 host when
                updating clang prebuilt in the kernel branch."""
        return args


def extract_clang_info(clang_dir):
    version_file_path = os.path.join(clang_dir, 'AndroidVersion.txt')
    with open(version_file_path) as version_file:
        # e.g. for contents: ['7.0.1', 'based on r326829']
        contents = [l.strip() for l in version_file.readlines()]
        full_version = contents[0]
        major_version = full_version.split('.')[0]
        revision = contents[1].split()[-1]
        return full_version, major_version, revision


def symlink_to_linux_resource_dir(install_dir):
    # Assume we're in a Darwin (non-linux) prebuilt dir.  Find the Clang version
    # string.  Pick the longest string, if there's more than one.
    version_dirs = os.listdir(os.path.join(install_dir, 'lib', 'clang'))
    if version_dirs:
        version_dirs.sort(key=len)
    version_dir = version_dirs[-1]

    symlink_dir = os.path.join(install_dir, 'lib', 'clang', version_dir,
                               'lib')
    link_src = os.path.join('/'.join(['..'] * 6), 'linux-x86', symlink_dir,
                            'linux')
    link_dst = 'linux'

    # 'cd' to symlink_dir and create a symlink from link_dst to link_src
    prebuilt_dir = os.getcwd()
    os.chdir(symlink_dir)
    os.symlink(link_src, link_dst)
    os.chdir(prebuilt_dir)


def validity_check(host, install_dir, clang_version_major):
    # Make sure the official toolchain (non llvm-next) is built with PGO
    # profiles.
    if host == 'linux-x86':
        realClangPath = os.path.join(install_dir, 'bin', 'clang-' + clang_version_major)
        strings = utils.check_output([realClangPath, '--version'])
        llvm_next = strings.find('ANDROID_LLVM_NEXT') != -1

        if not llvm_next:
            has_pgo = ('+pgo' in strings) and ('-pgo' not in strings)
            if not has_pgo:
                logger().error('The Clang binary is not built with PGO profiles.')
                return False
            has_bolt = ('+bolt' in strings) and ('-bolt' not in strings)
            if not has_bolt:
                logger().error('The Clang binary is not built with BOLT profiles.')
                return False
            has_lto = ('+lto' in strings) and ('-lto' not in strings)
            if not has_lto:
                logger().error('The Clang binary is not built with LTO.')
                return False
            has_mlgo = ('+mlgo' in strings) and ('-mlgo' not in strings)
            if not has_mlgo:
                logger().error('The Clang binary is not built with MLGO support.')
                return False

    # Check that all the files listed in remote_toolchain_inputs are valid
    if host == 'linux-x86':
        with open(os.path.join(install_dir, 'bin', 'remote_toolchain_inputs')) as inputs_file:
            files = [line.strip() for line in inputs_file.readlines()]
            fail = False
            for f in files:
                if not os.path.exists(os.path.join(install_dir, 'bin', f)):
                    logger().error(f'remote_toolchain_inputs malformed, {f} does not exist')
                    fail = True
            if fail:
                return False

    return True


def format_bug(bug):
    """Formats a bug for use in a commit message.

    Bugs might be a number, in which case they're a buganizer reference to be
    formatted. If not, assume the user knows what they're doing and just return
    the string as-is.
    """
    if bug.isnumeric():
        return f'http://b/{bug}'
    return bug


def rewrite_manifest(manifest: str, aosp_manifest: str):
    """Rewrites the manifest to use the aosp remote and mirror branches."""
    tree = ET.parse(manifest)
    root = tree.getroot()

    remote = root.find('remote')
    if remote is None or remote.get('name') != 'goog':
        raise ValueError("Expected remote 'goog'")
    remote.set('name', 'aosp')
    remote.set('fetch', 'https://android.googlesource.com/')
    remote.set('review', 'https://android.googlesource.com/')

    default = root.find('default')
    if default is not None:
        default.set('remote', 'aosp')
        revision = default.get('revision')
        if not revision:
            raise ValueError("revision attribute not found")
        default.set('revision', f'mirror-goog-{revision}')

    for project in root.findall('project'):
        project.set('remote', 'aosp')
        upstream = project.get('upstream')
        if not upstream:
            raise ValueError("upstream attribute not found")
        project.set('upstream', f'mirror-goog-{upstream}')

    ET.indent(tree, space="  ", level=0)
    tree.write(aosp_manifest, encoding='utf-8', xml_declaration=True)


def update_clang(prebuilt_dir: Path, host, build_number, use_current_branch,
                 download_dir, bug, manifest, aosp_manifest, overwrite, do_validity_check,
                 is_testing):
    prebuilt_dir = prebuilt_dir / 'clang' / 'host' / host
    os.chdir(prebuilt_dir)

    if not use_current_branch:
        branch_name = f'update-clang-{build_number}'
        utils.unchecked_call(
            ['repo', 'abandon', branch_name, '.'])
        utils.check_call(
            ['repo', 'start', branch_name, '.'])

    package = f'{download_dir}/clang-{build_number}-{host}.tar.xz'

    # Handle legacy versions of packages (like those from aosp/llvm-r365631).
    if not os.path.exists(package) and host == 'windows-x86':
        package = f'{download_dir}/clang-{build_number}-windows-x86-64.tar.xz'

    build_info_file = f'{download_dir}/BUILD_INFO-{host}'
    manifest_file = f'{download_dir}/{manifest}'
    aosp_manifest_file = f'{download_dir}/{aosp_manifest}'

    utils.extract_tarball(prebuilt_dir, package)

    extract_subdir = 'clang-' + build_number
    clang_version_full, clang_version_major, svn_revision = extract_clang_info(extract_subdir)

    # Install into clang-<svn_revision>.  Suffixes ('a', 'b', 'c' etc.), if any,
    # are included in the svn_revision.
    install_subdir = 'clang-' + svn_revision
    install_clang_directory(extract_subdir, install_subdir, overwrite)

    # Linux prebuilts need to include a few libraries from the linux_musl artifacts
    if host == 'linux-x86':
        musl_install_subdir = install_subdir + '/musl'
        musl_package = f'{download_dir}/clang-{build_number}-linux_musl-x86.tar.xz'
        if os.path.exists(extract_subdir):
            shutil.rmtree(extract_subdir)
        musl_files = [
            "--wildcards",
            "*/lib/libclang.so*",
            "*/lib/*/libc++.so*",
            "*/lib/libc_musl.so",
            "*/lib/aarch64-unknown-linux-musl/libc++.a",
            "*/lib/aarch64-unknown-linux-musl/libc++abi.a",
            "*/lib/x86_64-unknown-linux-musl/libc++.a",
            "*/lib/x86_64-unknown-linux-musl/libc++abi.a",
        ]
        tar_content = utils.check_output(['tar', '-tf', str(musl_package)])
        if 'libjemalloc5.so' in tar_content:
            musl_files.append("*/lib/libjemalloc5.so")
        if 'LICENSE.musl' in tar_content:
            musl_files.append("*/lib/LICENSE.musl")

        utils.extract_tarball(prebuilt_dir, musl_package, musl_files)
        install_clang_directory(extract_subdir, musl_install_subdir, overwrite)

        for triple in ('aarch64-unknown-linux-musl', 'x86_64-unknown-linux-musl'):
            # Move archives.
            src_dir = Path(musl_install_subdir) / 'lib' / triple
            dest_dir = Path(install_subdir) / 'lib' / 'clang' / clang_version_major / 'lib' / triple
            dest_dir.mkdir(exist_ok=True)  # The x86_64 triple will already exist.
            for name in ('libc++.a', 'libc++abi.a'):
                shutil.move(src_dir / name, dest_dir / name)

    # Some platform tests (e.g. system/bt/profile/sdp) build directly with
    # coverage instrumentation and rely on the driver to pick the correct
    # profile runtime.  Symlink the Linux resource dir from the Linux toolchain
    # into the Darwin toolchain so the runtime is found by the Darwin Clang
    # driver.
    if host == 'darwin-x86':
        symlink_to_linux_resource_dir(install_subdir)

    if do_validity_check:
        if not validity_check(host, install_subdir, clang_version_major):
            sys.exit(1)

    shutil.copy(build_info_file, str(prebuilt_dir / install_subdir / 'BUILD_INFO'))
    shutil.copy(manifest_file, str(prebuilt_dir / install_subdir))
    shutil.copy(aosp_manifest_file, str(prebuilt_dir / install_subdir))

    utils.check_call(['git', 'add', install_subdir])

    # If there is no difference with the new files, we are already done.
    diff = utils.unchecked_call(['git', 'diff', '--cached', '--quiet'])
    if diff == 0:
        logger().info('Bypassed commit with no diff')
        return

    message_lines = [
        f'Update prebuilt Clang to {svn_revision} ({clang_version_full}).',
        '',
        f'clang {clang_version_full} (based on {svn_revision}) from build {build_number}.'
    ]
    if is_testing:
        message_lines.append('Note: This prebuilt is from testing branch.')
    if bug is not None:
        message_lines.append('')
        message_lines.append(f'Bug: {format_bug(bug)}')
    message_lines.append('Test: N/A')
    message = '\n'.join(message_lines)
    utils.check_call(['git', 'commit', '-m', message])


def install_clang_directory(extract_subdir: str, install_subdir: str, overwrite: bool):
    if os.path.exists(install_subdir):
        if overwrite:
            logger().info('Removing/overwriting existing path: %s',
                          install_subdir)
            shutil.rmtree(install_subdir)
        else:
            logger().info('Cannot remove/overwrite existing path: %s',
                          install_subdir)
            sys.exit(1)
    os.rename(extract_subdir, install_subdir)


def main():
    args = ArgParser().parse_args()
    logging.basicConfig(level=logging.DEBUG)

    do_fetch = not args.skip_fetch
    do_cleanup = not args.skip_cleanup

    if do_fetch or args.repo_upload:
        utils.check_gcertstatus()

    download_dir = os.path.realpath('.download')
    if do_fetch:
        if os.path.isdir(download_dir):
            shutil.rmtree(download_dir)
        os.makedirs(download_dir)

    os.chdir(download_dir)

    targets_map = {'darwin-x86': 'llvm_darwin_mac',
                   'linux-arm64': 'llvm_linux_arm64',
                   'linux-x86': 'llvm_linux',
                   'windows-x86': 'llvm_windows_x86_64'}
    hosts = [args.host] if args.host else targets_map.keys()
    targets = [targets_map[h] for h  in hosts]
    if 'linux-x86' in hosts:
        targets.append('llvm_linux_musl')

    build_info = 'BUILD_INFO'
    clang_pattern = 'clang-*.tar.xz'
    manifest = f'manifest_{args.build}.xml'
    aosp_manifest = f'aosp_{manifest}'

    branch = args.branch
    if branch is None:
        output = utils.check_output(['/google/bin/releases/android/ab/ab.par',
                                     'get',
                                     '--raw', # prevent color text
                                     '--bid', args.build,
                                     '--target', 'llvm_linux'])
        # Example output is:
        #   aosp-llvm-toolchain linux 6732143 complete True
        branch = output.split()[0]

    logger().info('Using branch: %s', branch)
    is_testing = branch == 'aosp-llvm-toolchain-testing'

    try:
        if do_fetch:
            utils.fetch_artifact(branch, targets[0], args.build, manifest)
            rewrite_manifest(manifest, aosp_manifest)
            for host in hosts:
                target = targets_map[host]
                utils.fetch_artifact(branch, target, args.build, build_info)
                os.rename(f'{download_dir}/{build_info}', f'{download_dir}/{build_info}-{host}')
            for target in targets:
                utils.fetch_artifact(branch, target, args.build, clang_pattern)

        if args.update_in_kernel_branch_dir:
            prebuilt_dir = Path(args.update_in_kernel_branch_dir) / 'prebuilts'
        else:
            prebuilt_dir = paths.PREBUILTS_DIR
        for host in hosts:
            update_clang(prebuilt_dir, host, args.build, args.use_current_branch,
                         download_dir, args.bug, manifest, aosp_manifest, args.overwrite,
                         not args.no_validity_check, is_testing)

        if args.repo_upload:
            topic = f'clang-prebuilt-{args.build}'
            if is_testing:
                topic = topic.replace('prebuilt', 'testing-prebuilt')

            for host in hosts:
                utils.prebuilt_repo_upload(prebuilt_dir, host, topic, args.hashtag, is_testing)
    finally:
        if do_cleanup:
            shutil.rmtree(download_dir)

    return 0


if __name__ == '__main__':
    main()
