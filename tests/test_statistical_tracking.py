import pandas as pd
import pyreadstat

from bas_assistant.analytics import (
    compare_groups,
    compare_metric_by_group,
    read_stat_dataset,
)


def test_pyreadstat_reader_loads_sav_file_and_metadata(tmp_path):
    frame = pd.DataFrame(
        {
            "period": ["baseline", "baseline", "optimized", "optimized"],
            "fan_kw": [10.0, 10.5, 8.0, 8.2],
            "sat_error": [1.1, 1.0, 0.4, 0.5],
        }
    )
    path = tmp_path / "trend_summary.sav"
    pyreadstat.write_sav(frame, path)

    dataset = read_stat_dataset(path)

    assert dataset.source_path == path
    assert list(dataset.frame.columns) == ["period", "fan_kw", "sat_error"]
    assert dataset.metadata.number_rows == 4


def test_compare_metric_by_group_detects_significant_building_metric_change():
    frame = pd.DataFrame(
        {
            "period": ["baseline"] * 12 + ["optimized"] * 12,
            "fan_kw": [10.0, 10.2, 9.9, 10.1, 10.3, 9.8, 10.0, 10.2, 10.1, 9.9, 10.2, 10.0]
            + [8.0, 8.1, 7.9, 8.2, 8.0, 8.1, 7.8, 8.2, 8.0, 8.1, 7.9, 8.0],
        }
    )

    result = compare_metric_by_group(
        frame,
        metric="fan_kw",
        group_column="period",
        baseline_group="baseline",
        comparison_group="optimized",
    )

    assert result.baseline_count == 12
    assert result.comparison_count == 12
    assert result.direction == "decrease"
    assert result.mean_difference < -1.8
    assert result.percent_difference < -18.0
    assert result.is_significant
    assert result.p_value < 0.05


def test_compare_groups_accepts_pyreadstat_supported_file(tmp_path):
    frame = pd.DataFrame(
        {
            "mode": ["cooling"] * 6 + ["economizer"] * 6,
            "fan_kw": [7.9, 8.0, 8.2, 8.1, 7.8, 8.0, 6.0, 6.2, 5.9, 6.1, 6.0, 6.2],
            "sat_error": [1.3, 1.2, 1.4, 1.1, 1.2, 1.3, 0.7, 0.6, 0.8, 0.7, 0.6, 0.7],
        }
    )
    path = tmp_path / "building_modes.dta"
    pyreadstat.write_dta(frame, path)

    results = compare_groups(
        path,
        metrics=["fan_kw", "sat_error"],
        group_column="mode",
        baseline_group="cooling",
        comparison_group="economizer",
    )

    assert [result.metric for result in results] == ["fan_kw", "sat_error"]
    assert all(result.direction == "decrease" for result in results)
    assert all(result.is_significant for result in results)
