#
# Copyright (C) 2025 The Android Open Source Project
#
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
import argparse
from pathlib import Path
from typing import List, Tuple, Dict, Any
import itertools
from dataclasses import dataclass


__doc__ = (
    "This program can be used to better discover and document improvements and"
    " regressions in Android build performance. Build metrics are gathered from"
    " Soong-generated build trace files. This script can be run within a"
    " virtual environment (must install dependencies above), or copied over and"
    " run in Colab (dependencies should already be installed in a Borg"
    " runtime)."
)


def parse_args() -> argparse.Namespace:
    """
    Parse program command line arguments.
    """

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "-a",
        "--paths-a",
        action="append",
        required=True,
        help="Paths to (uncompressed) build.trace files for build A",
    )
    parser.add_argument(
        "-b",
        "--paths-b",
        action="append",
        required=True,
        help="Paths to (uncompressed) build.trace files for build B",
    )
    parser.add_argument(
        "-o",
        "--output_file_path",
        default=Path(__file__).resolve().with_suffix(".html"),
        help=(
            "Path to output analysis to. Defaults to"
            f' {Path(__file__).resolve().with_suffix(".html")}'
        ),
    )
    parser.add_argument(
        "-g",
        "--group-by",
        choices=[Target.NAME_KEY, Target.MODULE_NAME_KEY],
        help="How to group target data into build units",
    )
    parser.add_argument(
        "--include-module-names",
        "--imn",
        action="append",
        help=(
            "Module names to include. E.g."
            ' "out/soong/.intermediates/tools/netsim/netsimd/linux_glibc_x86_64/generated_rust_staticlib/librustlibs.a".'
        ),
    )
    parser.add_argument(
        "--exclude-module-names",
        "--emn",
        action="append",
        help="Module names to exclude.",
    )
    parser.add_argument(
        "--include-module-types",
        "--imt",
        action="append",
        help='Module types to include. E.g. "rust_ffi".',
    )
    parser.add_argument(
        "--exclude-module-types",
        "--emt",
        action="append",
        help="Module types to exclude.",
    )
    parser.add_argument(
        "--include-rule-names",
        "--irn",
        action="append",
        help='Rule names to include. E.g. "rustc".',
    )
    parser.add_argument(
        "--exclude-rule-names",
        "--ern",
        action="append",
        help="Rule names to exclude.",
    )
    parser.add_argument(
        "--include-extensions",
        "--ie",
        action="append",
        help=(
            'Target extensions to include. Include . in extension. E.g. ".jar" to'
            ' include all JAR files. The suffix of an output file is ".o" for a'
            ' compilation rule, or ".so" for a linking rule if the output is a shared'
            " library, or no suffix for a linking rule if the output is a binary."
        ),
    )
    parser.add_argument(
        "--exclude-extensions",
        "--ee",
        action="append",
        help="Target extensions to exclude.",
    )
    parser.add_argument(
        "-s",
        "--remove-lower-than-s",
        help=(
            "Remove all build units (either targets or modules based on -g argument)"
            " with build time lower than this value"
        ),
    )

    args = parser.parse_args()

    return args


@dataclass(frozen=True)
class Filters:
    """
    Filters to apply to build trace files.
    """

    group_by: str | None
    include_module_names: tuple[str] | None
    exclude_module_names: tuple[str] | None
    include_module_types: tuple[str] | None
    exclude_module_types: tuple[str] | None
    include_rule_names: tuple[str] | None
    exclude_rule_names: tuple[str] | None
    include_extensions: tuple[str] | None
    exclude_extensions: tuple[str] | None
    remove_lower_than_s: float | None


class Target:
    """
    Simplest build unit representing a single build target.
    """

    NAME_KEY = "name"
    TIME_S_KEY = "time_s"
    MODULE_NAME_KEY = "module_name"
    MODULE_TYPE_KEY = "module_type"
    RULE_NAME_KEY = "rule_name"
    EXTENSION_KEY = "extension"
    MICROSEC_IN_SEC = 1000000

    def __init__(
        self,
        path: Path,
        time_s: float,
        module_name: str | None,
        module_type: str | None,
        rule_name: str | None,
    ):
        self.name = str(path)
        self.time_s = time_s
        self.module_name = module_name
        self.module_type = module_type
        self.rule_name = rule_name
        self.extension = path.suffix

    def to_dict(self) -> Dict[str, Any]:
        return {
            self.NAME_KEY: self.name,
            self.TIME_S_KEY: self.time_s,
            self.MODULE_NAME_KEY: self.module_name,
            self.MODULE_TYPE_KEY: self.module_type,
            self.RULE_NAME_KEY: self.rule_name,
            self.EXTENSION_KEY: self.extension,
        }


class BuildTrace:
    """
    A grouping of build targets.
    """

    def __init__(
        self,
        name: str,
        targets: List[Target],
    ):
        self.name = name
        self.targets = targets

    def get_targets_copy(self) -> List[Target]:
        return self.targets[:]


class BuildConfiguration:
    """
    A grouping of build traces. Comparisons are done between build configurations.
    """

    GENERIC_BUILD_UNIT_NAME_KEY = "build_unit"
    MOE_KEY = "moe"
    CI_UPPER_KEY = "ci_upper"
    CI_LOWER_KEY = "ci_lower"

    def __init__(self, name: str, build_traces: List[BuildTrace]):
        self.name = name
        self.desc = ", ".join([trace.name for trace in build_traces])
        self.build_traces = build_traces


def compare_android_build_configurations(
    paths_a: List[Path],
    paths_b: List[Path],
    output_file_path: Path,
    filters: Filters,
):
    """
    Compares build performance of two Android build configurations, given two
    sets of Soong-generated build trace files (one for each build
    configuration).

    Generates an HTML report containing various build time visualizations. All
    generated charts are written to a single HTML file at the specified output
    path.
    """

    return


def main():
    args = parse_args()

    paths_a = [Path(path) for path in args.paths_a]
    paths_b = [Path(path) for path in args.paths_b]

    for path in itertools.chain(paths_a, paths_b):
        if not path.exists():
            raise FileNotFoundError(f"The trace file {path} could not be found.")

    def _tuplify(ls: List | None) -> Tuple | None:
        return tuple(ls) if ls else None

    filters = Filters(
        group_by=args.group_by,
        include_module_names=_tuplify(args.include_module_names),
        exclude_module_names=_tuplify(args.exclude_module_names),
        include_module_types=_tuplify(args.include_module_types),
        exclude_module_types=_tuplify(args.exclude_module_types),
        include_rule_names=_tuplify(args.include_rule_names),
        exclude_rule_names=_tuplify(args.exclude_rule_names),
        include_extensions=_tuplify(args.include_extensions),
        exclude_extensions=_tuplify(args.exclude_extensions),
        remove_lower_than_s=float(args.remove_lower_than_s)
        if args.remove_lower_than_s is not None
        else None,
    )

    compare_android_build_configurations(
        paths_a, paths_b, Path(args.output_file_path), filters
    )


if __name__ == "__main__":
    main()
