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

from __future__ import annotations
import collections
import dataclasses
from dataclasses import dataclass
import json
import logging
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from llvm_android import paths


@dataclass
class PatchItem:
    metadata: Dict[str, Any]
    # metadata['info']: Optional[List[str]]
    # metadata['title']: str
    platforms: List[str]
    rel_patch_path: str
    version_range: Dict[str, Optional[int]]
    # version_range['from']: Optional[int]
    # version_range['until']: Optional[int]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PatchItem:
        return PatchItem(
            metadata=d['metadata'],
            platforms=d['platforms'],
            rel_patch_path=d['rel_patch_path'],
            version_range=d['version_range'])

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self, dict_factory=collections.OrderedDict)

    @property
    def title(self) -> str:
        return self.metadata['title']

    @property
    def is_local_patch(self) -> bool:
        return not self.rel_patch_path.startswith('cherry/')

    @property
    def sha(self) -> str:
        m = re.match(r'cherry/(.+)\.patch', self.rel_patch_path)
        assert m, self.rel_patch_path
        return m.group(1)

    @property
    def revert_sha(self) -> str:
        m = re.match(r'Revert-(.+)(?:-v\d+)?\.patch', self.rel_patch_path)
        assert m, self.rel_patch_path
        return m.group(1)

    @property
    def pr_link(self) -> str:
        for line in open(f'patches/{self.rel_patch_path}'):
            if m := re.match(r'Pull Request: (.+)', line):
                return m.group(1)
        raise Exception(f'No PR link found in: {self.rel_patch_path}')

    @property
    def end_version(self) -> Optional[int]:
        return self.version_range.get('until', None)

    @property
    def start_version(self) -> Optional[int]:
        return self.version_range.get('from', None)

    @property
    def sort_key(self) -> Tuple:
        # Keep local patches at the end of the list, and don't change the
        # relative order between two local patches.
        if self.is_local_patch:
            return (True,)

        # Just before local patches, include patches with no end_version. Sort
        # them by start_version.
        if self.end_version is None:
            return (False, math.inf, self.start_version)

        # At the front of the list, sort upstream patches by ascending order of
        # end_version. Don't reorder patches with the same end_version.
        return (False, self.end_version)

    def __lt__(self, other: PatchItem) -> bool:
        """Used to sort patches in PatchList"""
        return self.sort_key < other.sort_key


class PatchList(list):
    """ a list of PatchItem """

    @staticmethod
    def _get_patch_file(filename: str) -> Path:
        if filename not in ('PATCHES.json', 'TOT.json'):
            raise ValueError(
                f'Invalid patch file name: {filename}. '
                'Must be PATCHES.json or TOT.json.'
            )
        return paths.SCRIPTS_DIR / 'patches' / filename

    @classmethod
    def load_from_file(cls, filename: str = 'PATCHES.json') -> PatchList:
        file_path = cls._get_patch_file(filename)
        with open(file_path, 'r') as fh:
            array = json.load(fh)
        return PatchList(PatchItem.from_dict(d) for d in array)

    def save_to_file(self, filename: str = 'PATCHES.json'):
        file_path = self._get_patch_file(filename)
        array = [patch.to_dict() for patch in self]
        with open(file_path, 'w') as fh:
            json.dump(array, fh, indent=4, separators=(',', ': '), sort_keys=True)
            fh.write('\n')

    def check_patches(self) -> bool:
        patch_files = set()
        for patch in self:
            if not patch.start_version:
                logging.error(f"'{patch.title}' doesn't have a start version")
                return False
            if patch.end_version and patch.end_version <= patch.start_version:
                logging.error(
                    f"'{patch.title}' has end version <= start version. It should be removed.")
                return False
            patch_file = paths.SCRIPTS_DIR / 'patches' / patch.rel_patch_path
            if not patch_file.is_file():
                logging.error(f"{patch_file} used by '{patch.title}' isn't a file")
                return False
            if patch_file in patch_files:
                logging.error(f"{patch_file} is used by multiple patches")
                return False
            patch_files.add(patch_file)
        return True


