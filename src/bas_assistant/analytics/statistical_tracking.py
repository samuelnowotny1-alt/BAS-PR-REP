"""Read statistical files and compare historical building data.

The reader uses pyreadstat for SPSS/SAS/Stata-style statistical files. The
comparison helpers intentionally stay dependency-light: they use pandas plus a
normal approximation to Welch's t statistic, which is enough for BAS screening
and regression testing. More advanced modeling can later plug in scipy/statsmodels
without changing the public result shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erfc, isfinite, sqrt
from pathlib import Path
from typing import Any

import pandas as pd
import pyreadstat


@dataclass(frozen=True)
class StatDataset:
    """Tabular statistical data plus pyreadstat metadata."""

    frame: pd.DataFrame
    metadata: Any
    source_path: Path


@dataclass(frozen=True)
class ComparisonResult:
    """Comparison of one numeric metric across two groups/time periods."""

    metric: str
    group_column: str
    baseline_group: str
    comparison_group: str
    baseline_count: int
    comparison_count: int
    baseline_mean: float
    comparison_mean: float
    mean_difference: float
    percent_difference: float | None
    baseline_std: float
    comparison_std: float
    standard_error: float
    test_statistic: float
    p_value: float
    alpha: float

    @property
    def is_significant(self) -> bool:
        """Whether the observed difference is significant at ``alpha``."""
        return self.p_value < self.alpha

    @property
    def direction(self) -> str:
        """Direction of change from baseline to comparison."""
        if self.mean_difference > 0:
            return "increase"
        if self.mean_difference < 0:
            return "decrease"
        return "no_change"

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API/report use."""
        return {
            "metric": self.metric,
            "group_column": self.group_column,
            "baseline_group": self.baseline_group,
            "comparison_group": self.comparison_group,
            "baseline_count": self.baseline_count,
            "comparison_count": self.comparison_count,
            "baseline_mean": self.baseline_mean,
            "comparison_mean": self.comparison_mean,
            "mean_difference": self.mean_difference,
            "percent_difference": self.percent_difference,
            "baseline_std": self.baseline_std,
            "comparison_std": self.comparison_std,
            "standard_error": self.standard_error,
            "test_statistic": self.test_statistic,
            "p_value": self.p_value,
            "alpha": self.alpha,
            "is_significant": self.is_significant,
            "direction": self.direction,
        }


def read_stat_dataset(path: str | Path, *, apply_value_formats: bool = False) -> StatDataset:
    """Read an SPSS/SAS/Stata statistical dataset with pyreadstat.

    Supported extensions:
    - ``.sav`` / ``.zsav`` via ``read_sav``
    - ``.dta`` via ``read_dta``
    - ``.sas7bdat`` via ``read_sas7bdat``
    - ``.xpt`` via ``read_xport``
    """
    source_path = Path(path)
    suffix = source_path.suffix.lower()

    if suffix in {".sav", ".zsav"}:
        frame, metadata = pyreadstat.read_sav(
            source_path,
            apply_value_formats=apply_value_formats,
        )
    elif suffix == ".dta":
        frame, metadata = pyreadstat.read_dta(
            source_path,
            apply_value_formats=apply_value_formats,
        )
    elif suffix == ".sas7bdat":
        frame, metadata = pyreadstat.read_sas7bdat(
            source_path,
            apply_value_formats=apply_value_formats,
        )
    elif suffix == ".xpt":
        frame, metadata = pyreadstat.read_xport(
            source_path,
            apply_value_formats=apply_value_formats,
        )
    else:
        raise ValueError(f"Unsupported statistical file extension: {suffix}")

    return StatDataset(frame=frame, metadata=metadata, source_path=source_path)


def compare_metric_by_group(
    frame: pd.DataFrame,
    *,
    metric: str,
    group_column: str,
    baseline_group: str,
    comparison_group: str,
    alpha: float = 0.05,
) -> ComparisonResult:
    """Compare one metric between two groups using Welch-style statistics.

    This is intended for questions like:

    - pre/post optimization fan power
    - occupied cooling performance this month vs baseline month
    - AHU discharge-air temperature error under similar operating mode

    Group values are compared as strings so categorical data imported from
    statistical packages behaves predictably.
    """
    _require_columns(frame, [metric, group_column])

    working = frame[[metric, group_column]].copy()
    working[metric] = pd.to_numeric(working[metric], errors="coerce")
    working[group_column] = working[group_column].astype(str)
    working = working.dropna(subset=[metric, group_column])

    baseline = working.loc[working[group_column] == str(baseline_group), metric]
    comparison = working.loc[working[group_column] == str(comparison_group), metric]

    if baseline.empty:
        raise ValueError(f"No rows found for baseline group {baseline_group!r}")
    if comparison.empty:
        raise ValueError(f"No rows found for comparison group {comparison_group!r}")

    baseline_count = int(baseline.count())
    comparison_count = int(comparison.count())
    baseline_mean = float(baseline.mean())
    comparison_mean = float(comparison.mean())
    baseline_std = float(baseline.std(ddof=1)) if baseline_count > 1 else 0.0
    comparison_std = float(comparison.std(ddof=1)) if comparison_count > 1 else 0.0

    standard_error = _welch_standard_error(
        baseline_std=baseline_std,
        baseline_count=baseline_count,
        comparison_std=comparison_std,
        comparison_count=comparison_count,
    )
    mean_difference = comparison_mean - baseline_mean
    test_statistic = mean_difference / standard_error if standard_error else 0.0
    p_value = _two_sided_normal_p_value(test_statistic) if standard_error else 1.0
    percent_difference = (
        (mean_difference / baseline_mean) * 100.0
        if baseline_mean != 0 and isfinite(baseline_mean)
        else None
    )

    return ComparisonResult(
        metric=metric,
        group_column=group_column,
        baseline_group=str(baseline_group),
        comparison_group=str(comparison_group),
        baseline_count=baseline_count,
        comparison_count=comparison_count,
        baseline_mean=baseline_mean,
        comparison_mean=comparison_mean,
        mean_difference=mean_difference,
        percent_difference=percent_difference,
        baseline_std=baseline_std,
        comparison_std=comparison_std,
        standard_error=standard_error,
        test_statistic=test_statistic,
        p_value=p_value,
        alpha=alpha,
    )


def compare_groups(
    source: pd.DataFrame | str | Path | StatDataset,
    *,
    metrics: list[str],
    group_column: str,
    baseline_group: str,
    comparison_group: str,
    alpha: float = 0.05,
) -> list[ComparisonResult]:
    """Compare multiple numeric metrics in a dataframe or pyreadstat-supported file."""
    frame = _coerce_frame(source)
    return [
        compare_metric_by_group(
            frame,
            metric=metric,
            group_column=group_column,
            baseline_group=baseline_group,
            comparison_group=comparison_group,
            alpha=alpha,
        )
        for metric in metrics
    ]


def _coerce_frame(source: pd.DataFrame | str | Path | StatDataset) -> pd.DataFrame:
    if isinstance(source, pd.DataFrame):
        return source
    if isinstance(source, StatDataset):
        return source.frame
    return read_stat_dataset(source).frame


def _require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(missing)}")


def _welch_standard_error(
    *,
    baseline_std: float,
    baseline_count: int,
    comparison_std: float,
    comparison_count: int,
) -> float:
    if baseline_count < 1 or comparison_count < 1:
        return 0.0
    variance = (baseline_std**2 / baseline_count) + (comparison_std**2 / comparison_count)
    return sqrt(variance) if variance > 0 else 0.0


def _two_sided_normal_p_value(test_statistic: float) -> float:
    """Two-sided normal-approximation p-value for a z/t-like statistic."""
    return erfc(abs(test_statistic) / sqrt(2.0))
