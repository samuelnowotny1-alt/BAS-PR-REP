"""Analytics helpers for historical BAS trend/statistical data."""

from .statistical_tracking import (
    ComparisonResult,
    StatDataset,
    compare_groups,
    compare_metric_by_group,
    read_stat_dataset,
)

__all__ = [
    "ComparisonResult",
    "StatDataset",
    "compare_groups",
    "compare_metric_by_group",
    "read_stat_dataset",
]
