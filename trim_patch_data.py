#!/usr/bin/env python3
#
# Copyright (C) 2020 The Android Open Source Project
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

import os
import sys

import context
from llvm_android import android_version, paths, utils
from llvm_android.patch_utils import PatchItem, PatchList

_LLVM_ANDROID_PATH = paths.SCRIPTS_DIR
_PATCH_DIR = _LLVM_ANDROID_PATH / 'patches'
_PATCH_JSON = _PATCH_DIR / 'PATCHES.json'

_SVN_REVISION = (android_version.get_svn_revision_number())


def trim_patches_json():
    """Remove old patches and return list of removed patch files."""
    patch_list = PatchList.load_from_file()
    retain = list()
    trimmed_files = list()
    for patch in patch_list:
        if patch.end_version is None or patch.end_version >= int(_SVN_REVISION):
            retain.append(patch)
        else:
            trimmed_files.append(_PATCH_DIR / patch.rel_patch_path)
    PatchList(retain).save_to_file()
    return trimmed_files


def main():
    if len(sys.argv) > 1:
        print(f'Usage: {sys.argv[0]}')
        print('  Script to remove downstream patches no longer needed for ' +
              'Android LLVM version.')
        return

    # Start a new repo branch before trimming patches.
    os.chdir(_LLVM_ANDROID_PATH)
    branch_name = f'trim-patches-before-{_SVN_REVISION}'
    utils.unchecked_call(['repo', 'abandon', branch_name, '.'])
    utils.check_call(['repo', 'start', branch_name, '.'])

    removed_patches = trim_patches_json()
    if not removed_patches:
        print('No patches to remove')
        return

    # Apply the changes to git and commit.
    utils.check_call(['git', 'add', _PATCH_JSON])
    for patch in removed_patches:
        utils.check_call(['git', 'rm', str(patch)])

    message_lines = [
        f'Remove patch entries older than {_SVN_REVISION}.',
        '',
        'Removed using: python3 trim_patch_data.py',
        'Test: N/A',
    ]
    utils.check_call(['git', 'commit', '-m', '\n'.join(message_lines)])


if __name__ == '__main__':
    main()
