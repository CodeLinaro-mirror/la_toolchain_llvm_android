#!/usr/bin/env python3
#
# Copyright (C) 2025 The Android Open Source Project
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
# Sample Usage:
# $ python3 update-patches.py --bug <Bug Number>
#
# If it fails to update some patches due to merge conflicts, fix the conflict
# and commit it then rerun the command with --continue_script
# $ python3 update-patches.py --bug <Bug Number> --continue_script
"""Update local patches"""

import argparse
import copy
from enum import Enum, auto
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Callable, Iterable, List, Optional, Tuple

import context
from llvm_android import android_version, hosts, paths, source_manager, utils
from llvm_android.patch_utils import PatchItem, PatchList
from merge_from_upstream import fetch_upstream, sha_to_revision

_PATCH_DIR = paths.SCRIPTS_DIR / 'patches'
_PATCH_JSON = _PATCH_DIR / 'PATCHES.json'
_TMP_FILE = paths.SCRIPTS_DIR / 'tmp-update-patches.out'
_TMP_LLVM_PROJECT = paths.OUT_DIR / 'llvm-project.tmp'


class LastPatchError:
    patch_path: str
    error: bool

    def __init__(self) -> None:
        self.patch_path = ''
        self.error = False

    def set_patch_path(self, patch_path: str) -> None:
        self.patch_path = patch_path

    def clear_error(self) -> None:
        self.patch_path = ''
        self.error = False

    def extract_error_from_file(self, error_file: str) -> None:
        with open(error_file, 'r') as file:
            line = file.readline().strip()
            self.patch_path = line
            self.error = True

    def save_error_to_file(self, error_file: str) -> None:
        with open(error_file, 'w') as file:
            file.write(f'{self.patch_path}')

    def had_error(self) -> bool:
        return self.error

    def skip_until_error_patch(self, patch_path: str) -> bool:
        return self.error and self.patch_path != patch_path

    def __repr__(self):
        return repr(self.patch_path)


def logger():
    """Returns the module level logger."""
    return logging.getLogger(__name__)


def create_cl(new_patches: PatchList, bug: Optional[str]) -> None:
    """Create a CL automatically for the updated patches (adapted from cherrypick_cl.py)"""
    logger().info('Create CL')

    # Add all files in patches
    file_list = [
        str(paths.SCRIPTS_DIR / 'patches' / p.rel_patch_path)
        for p in new_patches
    ]
    file_string = ' '.join(file_list)
    utils.check_call(['git', 'add', 'patches/', file_string])

    # Add patches' titles that are being updated
    commit_lines = [
        '[patches] Update Patches',
        '',
        'The list of patches updated:',
    ]
    for patch in new_patches:
        commit_lines.append(patch.metadata['title'])
    commit_lines.append('')

    # Add this CL was created by this script
    script = os.path.basename(sys.argv[0])
    argv_deepcopy = ' '.join(copy.deepcopy(sys.argv[1:]))
    auto_msg = f'This change is generated automatically by the script:\n'
    commit_lines += [auto_msg, f' {script} {argv_deepcopy}', '']

    # Add bug if given
    if bug:
        if bug.isnumeric():
            commit_lines += [f'Bug: http://b/{bug}', '']
        else:
            commit_lines += [f'Bug: {bug}', '']

    commit_lines += ['Test: N/A']
    utils.check_call(['git', 'commit', '-m', '\n'.join(commit_lines)])


def find_new_path(patch, patch_list) -> str:
    """Return the next version path for patch"""
    target = re.split(r'(-v\d+)?.patch', patch.rel_patch_path)[0]
    match = ''

    # Find the latest version
    for item in patch_list:
        if item.rel_patch_path.startswith(target):
            match = item.rel_patch_path.removesuffix('.patch')

    # Find the new version number
    if match != target:
        prefix = target + '-v'
        version = int(match.removeprefix(prefix)) + 1
    else:
        version = 2

    return target + f'-v{version}.patch'


def check_if_applicable_patch(patch: PatchItem) -> bool:
    """Check if patch is applicable based on current SVN version"""
    current_version = int(android_version.get_svn_revision_number())

    start_version = patch.start_version
    start_version = start_version if start_version else 0

    end_version = patch.end_version
    end_version = end_version if end_version else current_version + 1

    return start_version <= current_version < end_version


def check_patch(patch: PatchItem) -> bool:
    """Check if patch has an error when applied"""
    logger().debug(f'Patch Check: {patch.rel_patch_path}')
    patch_path = _PATCH_DIR / patch.rel_patch_path

    # Check patch has not drifted
    cmd = ['git', 'apply', '--check', patch_path]
    try:
        utils.check_call(cmd, cwd=_TMP_LLVM_PROJECT)
    except subprocess.CalledProcessError:
        logger().debug(f'Patch needs an update: {patch.rel_patch_path}')
        return True

    return False


# Just apply patches that do not need to be updated so we have the same
# behavior as chromeOS's patch_utils
def apply_patch(patch: PatchItem) -> None:
    logger().debug(f'Apply Patch: {patch.rel_patch_path}')
    patch_path = _PATCH_DIR / patch.rel_patch_path
    apply_cmd = ['git', 'am', '--3way', '--keep-non-patch', patch_path]
    utils.check_call(apply_cmd, cwd=_TMP_LLVM_PROJECT)


def update_patch(
    patch: PatchItem, new_rel_patch_path: str, error: LastPatchError
) -> Tuple[PatchItem, LastPatchError]:
    """Update patch"""
    logger().info(
        f'Update patch: {patch.rel_patch_path} to {new_rel_patch_path}'
    )
    patch_path = _PATCH_DIR / patch.rel_patch_path
    new_patch_path = _PATCH_DIR / new_rel_patch_path

    # Apply patch using 3way merge. This merge might fail due to conflicts so we
    # will merge it locally outside the script then rerun the script with continue_script.
    # In this case, skip the 3way merge and go directly to extracting the patch.
    if not error.had_error():
        logger().debug('Apply patch in 3way merge')
        merge_cmd = ['git', 'am', '--3way', '--keep-non-patch', patch_path]
        utils.check_call(merge_cmd, cwd=_TMP_LLVM_PROJECT)
    else:
        logger().debug('Skipped applying patch')
        # As we found the patch that crashed in the last run, we can clear the error
        error.clear_error()

    # Extract newly applied patch, with context updated to reflect latest LLVM source.
    format_cmd = ['git', 'format-patch', '-1', 'HEAD']
    output = utils.check_output(format_cmd, cwd=_TMP_LLVM_PROJECT)
    output = output.strip()

    # Move patch into patches folder and name it correctly
    new_patch_orig_path = _TMP_LLVM_PROJECT / output
    os.rename(new_patch_orig_path, new_patch_path)

    # Create new patch
    info: Optional[List[str]] = []
    curr_version = int(android_version.get_svn_revision_number())
    start_version = curr_version
    end_version = patch.end_version
    metadata = {'info': info, 'title': patch.title}
    platforms = ['android']
    version_range: Dict[str, Optional[int]] = {
        'from': start_version,
        'until': end_version,
    }
    new_patch = PatchItem(
        metadata, platforms, new_rel_patch_path, version_range
    )
    logger().debug(f'New Patch: {new_patch}')

    # Edit end_version for old patch
    patch.version_range['until'] = curr_version

    return new_patch, error


def update_patches(error: LastPatchError) -> PatchList:
    logger().info('Checking all patches for updates')
    patch_list = PatchList.load_from_file()

    # Setup llvm repo or skip it because there was an error previously during
    # new patch creation so the llvm repo is already setup
    if not error.had_error():
        source_manager.setup_temp_llvm_project(_TMP_LLVM_PROJECT, git_am=True, llvm_rev=None)
        assert os.path.exists(_TMP_LLVM_PROJECT)

    new_patch_list = PatchList()
    update_list = PatchList()
    for index, patch in enumerate(patch_list):
        new_patch_list.append(patch)

        # Skip patches not applicable
        if not check_if_applicable_patch(patch):
            logger().debug(f'Skip Non-Applicable Patch: {patch.rel_patch_path}')
            continue

        # The script crashed in the last run so we had already applied some patches to
        # llvm repo so we can skip them in this run
        if error.skip_until_error_patch(patch.rel_patch_path):
            logger().debug(
                f'Skip Patch Applied in Last Run: {patch.rel_patch_path}'
            )
            continue

        # No need to update cherry-pick patches, which are less prone to patch drift,
        # but we still apply them for consistency
        if patch.rel_patch_path.startswith('cherry/'):
            logger().debug(f'Skip Cherrypick Patch: {patch.rel_patch_path}')
            apply_patch(patch)
            continue

        do_update = check_patch(patch)
        if do_update:
            logger().debug('Found a patch to update')
            new_rel_patch_path = find_new_path(patch, patch_list)
            try:
                new_patch, error = update_patch(
                    patch, new_rel_patch_path, error
                )
            except subprocess.CalledProcessError:
                logger().info('Patch got an error during update')
                # Save patch error into temporary file so the script knows to continue from
                # this patch
                error.set_patch_path(patch.rel_patch_path)
                error.save_error_to_file(_TMP_FILE)

                # During this run, some patches might have been updated. This patch information
                # needs to be available in the next run of this script so we save it back into
                # the json file.
                new_patch_list.extend(patch_list[index + 1 :])
                new_patch_list.sort()
                new_patch_list.save_to_file()

                raise Exception(
                    'New Patch creation cannot be done automatically. Please'
                    f' resolve merge conflicts in {_TMP_FILE} and commit before'
                    ' rerunning the script again with --continue_script'
                )
            new_patch_list.append(new_patch)
            update_list.append(new_patch)
        else:
            apply_patch(patch)

    # Remove the llvm project tmp folder
    utils.check_call(['rm', '-rf', f'{_TMP_LLVM_PROJECT}'])

    new_patch_list.sort()
    new_patch_list.save_to_file()
    if not new_patch_list.check_patches():
        logger().info(f'{_PATCH_JSON} has an issue so undo the git changes')
        return

    return update_list


def parse_args():
    """Parses and returns command line arguments."""
    parser = argparse.ArgumentParser()

    parser.add_argument(
        '--verbose', action='store_true', default=False, help='Enable logging'
    )

    parser.add_argument(
        '--no-create-cl',
        action='store_true',
        default=False,
        help='Create a CL for the updated patches',
    )

    parser.add_argument(
        '--no-verify',
        action='store_true',
        default=False,
        help='Create a CL for the updated patches',
    )

    parser.add_argument('--bug', help='Bug number to attach to CL (if any)')

    parser.add_argument(
        '--continue_script',
        action='store_true',
        default=False,
        help='Continue off from last patch failure',
    )

    return parser.parse_args()


def main():
    args = parse_args()
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level)

    error = LastPatchError()
    if args.continue_script:
        logger().info('Continue the script from last error')
        if not os.path.exists(_TMP_FILE):
            raise Exception(
                'Script did not fail previously because no temporary file:'
                f' {_TMP_FILE}'
            )
        error.extract_error_from_file(_TMP_FILE)
    else:
        logger().info('Starting the script from the beginning')
        if os.path.exists(_TMP_FILE):
            raise Exception(
                f'{_TMP_FILE} exists so the script did fail previously. Re-run'
                ' the script with --continue_script'
            )

    commit_patches = update_patches(error)
    if not len(commit_patches):
        logger().info('No patches need updates')
        return

    if not args.no_verify:
        logger().info('Verifying merge with git am ...')
        source_manager.setup_sources(git_am=True)
        logger().info('Verifying merge with patch ...')
        source_manager.setup_sources()

    if not args.no_create_cl:
        create_cl(commit_patches, args.bug)

    # Remove the temporary file created for continue behavior
    utils.check_call(['rm', '-rf', f'{_TMP_FILE}'])


if __name__ == '__main__':
    main()
