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
"""Stubs Generation Code"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import (
    List,
    Optional,
    TextIO,
)

from llvm_android import (configs, paths, utils)

@dataclass
class Symbol:
    """A symbol definition from a symbol file."""
    name: str

class ParseError(RuntimeError):
    """An error that occurred while parsing a symbol file."""

class SymbolFileParser:
    """Parses symbol files."""
    def __init__(self, input_file: TextIO) -> None:
        self.input_file = input_file
        self.current_line: Optional[str] = None

    def parse(self) -> List[Symbol]:
        """Parses the symbol file and returns a list of symbols."""
        symbols: List[Symbol] = []
        while self.next_line():
            assert self.current_line is not None
            if '{' in self.current_line:
                symbols.extend(self.parse_section())
            else:
                raise ParseError(
                    f'Unexpected contents at top level: {self.current_line}')

        return symbols

    def parse_section(self) -> List[Symbol]:
        """Parses a single section and returns the symbols defined in it."""
        assert self.current_line is not None
        symbols: List[Symbol] = []
        global_scope = True
        while self.next_line():
            if '}' in self.current_line:
                return symbols
            elif ':' in self.current_line:
                visibility = self.current_line.split(':')[0].strip()
                if visibility == 'local':
                    global_scope = False
                elif visibility == 'global':
                    global_scope = True
                else:
                    raise ParseError('Unknown visiblity label: ' + visibility)
            elif global_scope:
                symbols.append(self.parse_symbol())
            else:
                # Only global symbols are important to make stubs
                pass
        raise ParseError('Unexpected EOF in a block.')

    def parse_symbol(self) -> Symbol:
        """Parses a single symbol line and returns a Symbol object."""
        assert self.current_line is not None
        if ';' not in self.current_line:
            raise ParseError(
                'Expected ; to terminate symbol: ' + self.current_line)
        if '*' in self.current_line:
            raise ParseError(
                'Wildcard global symbols are not permitted.')
        # Line is now in the format "<symbol-name>;"
        name, _, _ = self.current_line.strip().partition(';')
        return Symbol(name)

    def next_line(self) -> str:
        """Returns the next non-empty non-comment line.

        A return value of '' indicates EOF.
        """
        line = self.input_file.readline()
        while not line.strip() or line.strip().startswith('#'):
            line = self.input_file.readline()

            # We want to skip empty lines, but '' indicates EOF.
            if not line:
                break
        self.current_line = line
        return self.current_line

def generate_stubs(stubs_file: Optional[Path], symbol_file: Path):
    paths.STUBS_PATH.mkdir(parents=True, exist_ok=True)

    # Use default filename ("stubs.c") if nothing was given
    if not stubs_file:
        stubs_file = paths.STUBS_PATH / "stubs.c"

    # Parse the symbol file for all symbols needed to be stubbed
    with symbol_file.open('r') as symbol_file_text:
        symbols = SymbolFileParser(symbol_file_text).parse()

    # Create stubs for each symbol
    with stubs_file.open('w') as src_file:
        for symbol in symbols:
            src_file.write(f'void {symbol.name}() {{}}\n')

def generate_library(src_file: Path, library_file: Path, config: configs.AndroidConfig):
    # Generate command to build shared library from stubs
    utils.check_output([
        str(paths.CLANG_PREBUILT_DIR / 'bin' / 'clang'),
        f'--target={config.stubs_triple}',
        f'--sysroot={config.stubs_sysroot}',
        '-Wno-builtin-requires-header',
        '-Wno-incompatible-library-redeclaration',
        '-Wno-invalid-noreturn',
        "-shared",
        "-fPIC",
        str(src_file),
        "-o",
        str(library_file),
    ])