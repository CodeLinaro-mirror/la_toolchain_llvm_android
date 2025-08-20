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
import math

import pandas as pd
import numpy as np
from scipy import stats

from bokeh import layouts
from bokeh import plotting
from bokeh import transform
from bokeh import models
from bokeh.models import ranges

__doc__ = (
    "This program can be used to better discover and document improvements and"
    " regressions in Android build performance. Build metrics are gathered from"
    " Soong-generated build trace files. This script can be run within a virtual"
    " environment (must install dependencies above), or copied over and run in Colab"
    " (dependencies should already be installed in a Borg runtime). Results are written"
    " to build-a-b-comparison.{json, html}, and {build-a, build-b}.json"
)

example_usage = """
Examples:
    python %(prog)s -a build.trace.a.1 -a build.trace.a.2 -b build.trace.b.1 -b build.trace.b.2 --ie .o --ie .so -s 60
"""


def parse_args() -> argparse.Namespace:
    """
    Parse program command line arguments.
    """

    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=example_usage,
        formatter_class=argparse.RawTextHelpFormatter,
    )

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
        "--output-dir-path",
        default=Path(__file__).parent.resolve(),
        help=(
            "Directory path to output analysis to. Defaults to"
            f" {Path(__file__).parent.resolve()}"
        ),
    )
    parser.add_argument(
        "-g",
        "--group-by",
        choices=[
            Target.NAME_KEY,
            Target.MODULE_NAME_KEY,
            Target.MODULE_TYPE_KEY,
            Target.RULE_NAME_KEY,
            Target.EXTENSION_KEY,
        ],
        default=Target.NAME_KEY,
        help=(
            f"How to group target data into build units. Default is {Target.NAME_KEY}."
        ),
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
            " with build time lower than this value (s)"
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
    merge_on_key: str,
    value_key: str,
    k: int | None = None,
) -> pd.DataFrame:
    """
    Merges two DataFrames and returns the top K entries with the largest
    relative differences in a given column name.

    Args:
        df_a: The first DataFrame.
        suffix_a: The suffix to append to column names from df_a after merging.
        df_b: The second DataFrame.
        suffix_b: The suffix to append to column names from df_b after merging.
        merge_on_key: The column name to merge the two DataFrames on.
            (e.g., BuildConfiguration.GENERIC_BUILD_UNIT_NAME_KEY).
        value_key: The column name containing the values to compare for differences.
            (e.g., Target.TIME_S_KEY).
        k: The number of top relative differences to return. None means return all.

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
    if k is not None:
        df = df.nlargest(k, "rel_diff")
    df.sort_values(by="rel_diff", ascending=False, inplace=True)
    df.drop(columns=["rel_diff"], inplace=True)

    return df


FIGURE_WIDTH = 900
FIGURE_HEIGHT = 900


def get_bar_chart_comparison(
    build_a: BuildConfiguration,
    build_b: BuildConfiguration,
    filters: Filters,
    limit: int = 10,
    confidence_lvl: float = 0.95,
) -> plotting.figure:
    """
    Generates a bar chart comparing build times between two different build
    configurations, showing only the top K (limit) build units with the largest
    relative differences.

    The traces of a build configuration are first filtered before being
    aggregated to calculate mean build times and confidence intervals.

    The y-axis shows build times, and the x-axis shows build unit names. Each
    build unit name has side-by-side bars, one for each build configuration,
    each with a confidence interval.
    """

    a_filtered_build_trace_dfs = build_a.get_filtered_build_trace_dfs(filters)
    b_filtered_build_trace_dfs = build_b.get_filtered_build_trace_dfs(filters)

    if a_filtered_build_trace_dfs is None or b_filtered_build_trace_dfs is None:
        return plotting.figure()

    a_agg_df = aggregate_dfs(
        a_filtered_build_trace_dfs,
        confidence_lvl,
        BuildConfiguration.GENERIC_BUILD_UNIT_NAME_KEY,
        Target.TIME_S_KEY,
    )
    b_agg_df = aggregate_dfs(
        b_filtered_build_trace_dfs,
        confidence_lvl,
        BuildConfiguration.GENERIC_BUILD_UNIT_NAME_KEY,
        Target.TIME_S_KEY,
    )

    merged_df = get_k_largest_relative_diffs(
        a_agg_df,
        build_a.name,
        b_agg_df,
        build_b.name,
        BuildConfiguration.GENERIC_BUILD_UNIT_NAME_KEY,
        Target.TIME_S_KEY,
        limit,
    )

    if a_agg_df.empty or b_agg_df.empty:
        return plotting.figure()

    build_unit_names = list(merged_df[BuildConfiguration.GENERIC_BUILD_UNIT_NAME_KEY])

    data = {
        "build_unit_names": build_unit_names,
        "a": merged_df[f"{Target.TIME_S_KEY}_{build_a.name}"].to_list(),
        "b": merged_df[f"{Target.TIME_S_KEY}_{build_b.name}"].to_list(),
        "moe_a": merged_df[f"{BuildConfiguration.MOE_KEY}_{build_a.name}"].to_list(),
        "moe_b": merged_df[f"{BuildConfiguration.MOE_KEY}_{build_b.name}"].to_list(),
        "ci_lower_a": (
            merged_df[f"{BuildConfiguration.CI_LOWER_KEY}_{build_a.name}"].to_list()
        ),
        "ci_upper_a": (
            merged_df[f"{BuildConfiguration.CI_UPPER_KEY}_{build_a.name}"].to_list()
        ),
        "ci_lower_b": (
            merged_df[f"{BuildConfiguration.CI_LOWER_KEY}_{build_b.name}"].to_list()
        ),
        "ci_upper_b": (
            merged_df[f"{BuildConfiguration.CI_UPPER_KEY}_{build_b.name}"].to_list()
        ),
    }

    source = models.ColumnDataSource(data=data)

    fig = plotting.figure(
        x_range=build_unit_names,
        y_range=ranges.Range1d(0, max(max(data["a"]), max(data["b"])) * 1.1),
        title=(
            f"Build Time Comparison\nGrouped by {filters.group_by}\n{limit} largest"
            " relative differences shown"
        ),
        width=FIGURE_WIDTH,
        height=FIGURE_HEIGHT,
    )

    bar_width = 0.2

    vbar_glyph_a = fig.vbar(
        x=transform.dodge("build_unit_names", -bar_width / 2, range=fig.x_range),
        top="a",
        source=source,
        width=bar_width,
        color="#17a589",
        legend_label=f"Build {build_a.name} ({build_a.desc})",
    )
    vbar_glyph_b = fig.vbar(
        x=transform.dodge("build_unit_names", bar_width / 2, range=fig.x_range),
        top="b",
        source=source,
        width=bar_width,
        color="#abb2b9",
        legend_label=f"Build {build_b.name} ({build_b.desc})",
    )

    ci_desc = f"Margin of Error (Confidence Level {confidence_lvl})"

    fig.segment(
        x0=transform.dodge("build_unit_names", -bar_width, range=fig.x_range),
        x1=transform.dodge("build_unit_names", 0, range=fig.x_range),
        y0="ci_lower_a",
        y1="ci_lower_a",
        source=source,
        line_color="black",
        legend_label=ci_desc,
    )

    fig.segment(
        x0=transform.dodge("build_unit_names", -bar_width, range=fig.x_range),
        x1=transform.dodge("build_unit_names", 0, range=fig.x_range),
        y0="ci_upper_a",
        y1="ci_upper_a",
        source=source,
        line_color="black",
        legend_label=ci_desc,
    )

    fig.segment(
        x0=transform.dodge("build_unit_names", 0, range=fig.x_range),
        x1=transform.dodge("build_unit_names", bar_width, range=fig.x_range),
        y0="ci_lower_b",
        y1="ci_lower_b",
        source=source,
        line_color="black",
        legend_label=ci_desc,
    )

    fig.segment(
        x0=transform.dodge("build_unit_names", 0, range=fig.x_range),
        x1=transform.dodge("build_unit_names", bar_width, range=fig.x_range),
        y0="ci_upper_b",
        y1="ci_upper_b",
        source=source,
        line_color="black",
        legend_label=ci_desc,
    )

    fig.xgrid.grid_line_color = None
    fig.xaxis.major_label_orientation = math.pi / 2
    fig.xaxis.major_label_text_font_size = "16px"

    fig.legend.location = "top_left"
    fig.add_layout(fig.legend[0], "above")

    fig.xaxis.formatter = models.CustomJSTickFormatter(
        code="return tick.split('/').pop()"
    )

    fig.add_tools(
        models.HoverTool(
            tooltips=[
                ("Build Unit", "@build_unit_names"),
                (f"Build {build_a.name} Time (s)", "@a{0.2f} ± @moe_a"),
                (f"Build {build_b.name} Time (s)", "@b{0.2f} ± @moe_b"),
            ],
            renderers=[vbar_glyph_a, vbar_glyph_b],
        ),
    )

    return fig


def get_bar_chart(
    build: BuildConfiguration,
    filters: Filters,
    limit: int = 10,
    confidence_lvl: float = 0.95,
) -> plotting.figure:
    """
    Generates a bar chart showing the build units with the K (limit) largest
    build times of a given build configuration.

    The traces of a build configuration are first filtered before being
    aggregated to calculate mean build times and confidence intervals.

    The y-axis shows build times, and the x-axis shows build unit names. Each
    build unit name has a bar with a confidence interval.
    """

    filtered_build_trace_dfs = build.get_filtered_build_trace_dfs(filters)

    if filtered_build_trace_dfs is None:
        return plotting.figure()

    merged_df = aggregate_dfs(
        filtered_build_trace_dfs,
        confidence_lvl,
        BuildConfiguration.GENERIC_BUILD_UNIT_NAME_KEY,
        Target.TIME_S_KEY,
    )

    total_time_s = merged_df[Target.TIME_S_KEY].sum()

    k_largest_units_df = merged_df.nlargest(limit, Target.TIME_S_KEY).sort_values(
        by=Target.TIME_S_KEY, ascending=False
    )

    build_unit_names = k_largest_units_df[
        BuildConfiguration.GENERIC_BUILD_UNIT_NAME_KEY
    ].to_list()

    data = {
        "build_unit_names": build_unit_names,
        "time_s": k_largest_units_df[Target.TIME_S_KEY].to_list(),
        "moe": k_largest_units_df[BuildConfiguration.MOE_KEY].to_list(),
        "ci_lower": k_largest_units_df[BuildConfiguration.CI_LOWER_KEY].to_list(),
        "ci_upper": k_largest_units_df[BuildConfiguration.CI_UPPER_KEY].to_list(),
    }

    source = models.ColumnDataSource(data=data)

    fig = plotting.figure(
        x_range=build_unit_names,
        y_range=ranges.Range1d(0, max(data["time_s"]) * 1.1),
        title=(
            f"Largest Build Times for Build {build.name} ({build.desc})\nTotal build"
            f" time (min): {total_time_s/60:.2f}\nGrouped by"
            f" {filters.group_by}\n{limit} largest build times shown"
        ),
        width=FIGURE_WIDTH,
        height=FIGURE_HEIGHT,
    )

    bar_width = 0.6

    bar_glyph = fig.vbar(
        x="build_unit_names",
        top="time_s",
        source=source,
        width=bar_width,
        color="#8e44ad",
        legend_label=f"Build {build.name} ({build.desc})",
    )

    ci_desc = f"Margin of Error (Confidence Level {confidence_lvl})"

    fig.segment(
        x0=transform.dodge("build_unit_names", -bar_width / 2, range=fig.x_range),
        x1=transform.dodge("build_unit_names", bar_width / 2, range=fig.x_range),
        y0="ci_lower",
        y1="ci_lower",
        source=source,
        line_color="black",
        legend_label=ci_desc,
    )
    fig.segment(
        x0=transform.dodge("build_unit_names", -bar_width / 2, range=fig.x_range),
        x1=transform.dodge("build_unit_names", bar_width / 2, range=fig.x_range),
        y0="ci_upper",
        y1="ci_upper",
        source=source,
        line_color="black",
        legend_label=ci_desc,
    )

    fig.xgrid.grid_line_color = None
    fig.xaxis.major_label_orientation = math.pi / 2
    fig.xaxis.major_label_text_font_size = "16px"

    fig.legend.location = "top_left"
    fig.add_layout(fig.legend[0], "above")

    fig.xaxis.formatter = models.CustomJSTickFormatter(
        code="return tick.split('/').pop();"
    )

    fig.add_tools(
        models.HoverTool(
            tooltips=[
                ("Build Unit", "@build_unit_names"),
                ("Time (s)", "@time_s{0.2f} ± @moe{0.2f}"),
                ("Confidence Interval", "(@ci_lower{0.2f} - @ci_upper{0.2f})"),
            ],
            renderers=[bar_glyph],
        ),
    )

    return fig


def write_builds_to_json(
    build_a: BuildConfiguration,
    build_b: BuildConfiguration,
    filters: Filters,
    output_dir: Path,
    confidence_lvl: float = 0.95,
):
    """
    Writes filtered and sorted build configuration data/comparisons to JSON
    files in the provided output directory.
    A file is created for build a, build b, and an a-b comparison.
    """

    a_filtered_build_trace_dfs = build_a.get_filtered_build_trace_dfs(filters)
    b_filtered_build_trace_dfs = build_b.get_filtered_build_trace_dfs(filters)
    if a_filtered_build_trace_dfs is None or b_filtered_build_trace_dfs is None:
        return

    a_agg_df = aggregate_dfs(
        a_filtered_build_trace_dfs,
        confidence_lvl,
        BuildConfiguration.GENERIC_BUILD_UNIT_NAME_KEY,
        Target.TIME_S_KEY,
    )
    b_agg_df = aggregate_dfs(
        b_filtered_build_trace_dfs,
        confidence_lvl,
        BuildConfiguration.GENERIC_BUILD_UNIT_NAME_KEY,
        Target.TIME_S_KEY,
    )
    merged_df = get_k_largest_relative_diffs(
        a_agg_df,
        build_a.name,
        b_agg_df,
        build_b.name,
        BuildConfiguration.GENERIC_BUILD_UNIT_NAME_KEY,
        Target.TIME_S_KEY,
    )

    for name, df, sort_by in [
        (build_a.name, a_agg_df, Target.TIME_S_KEY),
        (build_b.name, b_agg_df, Target.TIME_S_KEY),
        (f"{build_a.name}-{build_b.name}-comparison", merged_df, None),
    ]:
        if df.empty:
            continue
        df.rename(
            columns={BuildConfiguration.GENERIC_BUILD_UNIT_NAME_KEY: filters.group_by},
            inplace=True,
        )
        if sort_by is not None:
            df = df.sort_values(by=Target.TIME_S_KEY, ascending=False)
        df.to_json(output_dir / f"build-{name}.json", orient="records", indent=4)


def compare_android_build_configurations(
    paths_a: List[Path], paths_b: List[Path], output_dir: Path, filters: Filters
):
    """
    Compares build performance of two Android build configurations, given two
    sets of Soong-generated build trace files (one for each build
    configuration).

    Generates a report containing various build time data/visualizations. All
    generated logs/charts are written to the specified output directory.
    """

    build_a = BuildConfiguration.from_soong_traces("a", paths_a)
    build_b = BuildConfiguration.from_soong_traces("b", paths_b)

    plotting.output_file(
        output_dir / f"build-{build_a.name}-{build_b.name}-comparison.html"
    )
    plotting.save(
        layouts.column(
            get_bar_chart_comparison(build_a, build_b, filters),
            models.Div(text="", width=1, height=60),
            get_bar_chart(build_a, filters),
            models.Div(text="", width=1, height=60),
            get_bar_chart(build_b, filters),
        )
    )

    write_builds_to_json(
        build_a,
        build_b,
        filters,
        output_dir,
    )


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
        remove_lower_than_s=(
            float(args.remove_lower_than_s)
            if args.remove_lower_than_s is not None
            else None
        ),
    )

    output_dir = Path(args.output_dir_path).expanduser()
    if not output_dir.exists() or not output_dir.is_dir():
        raise ValueError("Provided output directory path could not be found.")

    compare_android_build_configurations(paths_a, paths_b, output_dir, filters)


if __name__ == "__main__":
    main()
