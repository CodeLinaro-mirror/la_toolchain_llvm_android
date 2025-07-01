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
from typing import Any, Dict, List, Tuple
from dataclasses import dataclass
from pathlib import Path
import itertools

from functools import lru_cache
import json

import pandas as pd
import numpy as np
from scipy import stats


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

    @classmethod
    def from_soong_traces(
        cls,
        build_configuration_name: str,
        paths: List[Path],
    ) -> "BuildConfiguration":
        """
        Initialize a build configuration from a list of Soong-generated build trace files.
        """

        traces: List[BuildTrace] = []

        for path in paths:
            targets: List[Target] = []

            with path.open() as file:
                file_data = json.load(file)

                for entry in file_data:
                    if "name" not in entry or "dur" not in entry:
                        continue

                    target_path = Path(entry["name"])
                    time_s = entry["dur"] / Target.MICROSEC_IN_SEC
                    module_name = None
                    module_type = None
                    rule_name = None

                    tags = entry.get("args", {}).get("tags")
                    if tags:
                        module_name = tags.get("module_name")
                        module_type = tags.get("module_type")
                        rule_name = tags.get("rule_name")

                    target = Target(
                        target_path,
                        time_s,
                        module_name,
                        module_type,
                        rule_name,
                    )
                    targets.append(target)

                trace = BuildTrace(str(path), targets)
                traces.append(trace)

        return cls(
            build_configuration_name,
            traces,
        )

    @lru_cache()
    def get_filtered_build_trace_dfs(
        self, filters: Filters
    ) -> List[pd.DataFrame] | None:
        """
        Apply given filters to the build configuration.

        Returns:
            A list of Pandas dataframes, where each DataFrame corresponds to a
            filtered build trace.
            None if there are no build units left after applying filters.

        Consider refactoring this function to a regex-based system.
        - See: https://googleplex-android-review.git.corp.google.com/c/toolchain/llvm_android/+/34313400/comment/a0e9e25f_b4df79d4/
        """

        filtered_traces = []
        for trace in self.build_traces:
            filtered_targets = []
            for target in trace.targets:
                if (
                    (
                        not filters.include_module_names
                        or target.module_name in filters.include_module_names
                    )
                    and (
                        not filters.exclude_module_names
                        or target.module_name not in filters.exclude_module_names
                    )
                    and (
                        not filters.include_module_types
                        or target.module_type in filters.include_module_types
                    )
                    and (
                        not filters.exclude_module_types
                        or target.module_type not in filters.exclude_module_types
                    )
                    and (
                        not filters.include_rule_names
                        or target.rule_name in filters.include_rule_names
                    )
                    and (
                        not filters.exclude_rule_names
                        or target.rule_name not in filters.exclude_rule_names
                    )
                    and (
                        not filters.include_extensions
                        or target.extension in filters.include_extensions
                    )
                    and (
                        not filters.exclude_extensions
                        or target.extension not in filters.exclude_extensions
                    )
                ):
                    filtered_targets.append(target)

            if not filtered_targets:
                continue

            filtered_trace = (
                pd.DataFrame([target.to_dict() for target in filtered_targets])
                .groupby(filters.group_by)[Target.TIME_S_KEY]
                .sum()
                .reset_index()
            )

            filtered_trace.rename(
                columns={filters.group_by: self.GENERIC_BUILD_UNIT_NAME_KEY},
                inplace=True,
            )

            if filters.remove_lower_than_s:
                filtered_trace = filtered_trace[
                    filtered_trace[Target.TIME_S_KEY] > filters.remove_lower_than_s
                ].reset_index()

            if not filtered_trace.empty:
                filtered_traces.append(filtered_trace)

        if not filtered_traces:
            return None

        return filtered_traces


def aggregate_dfs(
    dfs: List[pd.DataFrame], confidence_lvl: float, group_by_key: str, value_key: str
) -> pd.DataFrame:
    """
    Aggregates a list of DataFrames by calculating the mean, margin of error,
    and confidence intervals for a specified value key, grouped by a specific
    group-by key.

    Args:
        dfs: A list of DataFrames to aggregate.
        confidence_lvl: The confidence level for calculating the margin of error
            (e.g., 0.95 for a 95% confidence interval).
        group_by_key: The column name to group the data by.
            (e.g., BuildConfiguration.GENERIC_BUILD_UNIT_NAME_KEY).
        value_key: The column name containing the values to aggregate.
            (e.g., Target.TIME_S_KEY).

    Returns:
        A new DataFrame with the aggregated data, including the mean,
        margin of error, and lower and upper bounds of the confidence interval.
    """

    if not dfs:
        return pd.DataFrame()

    def calc_moe(series: pd.Series) -> float:
        n = len(series)
        if n < 2:
            return 0.0

        t_critical = stats.t.ppf(confidence_lvl + (1 - confidence_lvl) / 2, n - 1)
        std_error = series.std() / np.sqrt(n)

        moe = t_critical * std_error

        return moe

    dfs_concat = pd.concat(dfs, ignore_index=True)

    agg_kwargs = {
        value_key: (value_key, "mean"),
        BuildConfiguration.MOE_KEY: (value_key, calc_moe),
    }

    # Need to do a kwargs expansion here because the columns to aggregate on are dynamicly chosen
    agg = dfs_concat.groupby(group_by_key).agg(**agg_kwargs).reset_index()

    agg[BuildConfiguration.CI_LOWER_KEY] = (
        agg[value_key] + agg[BuildConfiguration.MOE_KEY]
    )
    agg[BuildConfiguration.CI_UPPER_KEY] = (
        agg[value_key] - agg[BuildConfiguration.MOE_KEY]
    )

    return agg


def get_k_largest_relative_diffs(
    df_a: pd.DataFrame,
    suffix_a: str,
    df_b: pd.DataFrame,
    suffix_b: str,
    k: int,
    merge_on_key: str,
    value_key: str,
) -> pd.DataFrame:
    """
    Merges two DataFrames and returns the top K entries with the largest
    relative differences in a given column name.

    Args:
        df_a: The first DataFrame.
        suffix_a: The suffix to append to column names from df_a after merging.
        df_b: The second DataFrame.
        suffix_b: The suffix to append to column names from df_b after merging.
        k: The number of top relative differences to return.
        merge_on_key: The column name to merge the two DataFrames on.
            (e.g., BuildConfiguration.GENERIC_BUILD_UNIT_NAME_KEY).
        value_key: The column name containing the values to compare for differences.
            (e.g., Target.TIME_S_KEY).

    Returns:
        A DataFrame containing the top K entries with the largest relative
        differences, sorted in descending order of relative difference.
    """

    df = pd.merge(
        df_a,
        df_b,
        on=merge_on_key,
        how="inner",
        suffixes=(f"_{suffix_a}", f"_{suffix_b}"),
    )

    df["abs_diff"] = np.abs(
        df[f"{value_key}_{suffix_a}"] - df[f"{value_key}_{suffix_b}"]
    )
    df["avg_time"] = (df[f"{value_key}_{suffix_a}"] + df[f"{value_key}_{suffix_b}"]) / 2
    df["rel_diff"] = df.apply(
        lambda row: (
            row["abs_diff"] / row["avg_time"] if row["avg_time"] != 0 else np.nan
        ),
        axis=1,
    )

    df.drop(columns=["abs_diff", "avg_time"], inplace=True)
    df = df.nlargest(k, "rel_diff")
    df.sort_values(by="rel_diff", ascending=False, inplace=True)
    df.drop(columns=["rel_diff"], inplace=True)

    return df


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

    build_a = BuildConfiguration.from_soong_traces("a", paths_a)
    build_b = BuildConfiguration.from_soong_traces("b", paths_b)

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
