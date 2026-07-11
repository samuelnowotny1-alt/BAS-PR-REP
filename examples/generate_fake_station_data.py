"""Generate deterministic fake BAS station runtime data from a project file."""

from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

from bas_assistant.models import Point, Project


SEED = 42
INTERVAL_MINUTES = 15
HOURS = 24


def sensor_value(point: Point, minute_index: int) -> float:
    suffix = point.name.split(" ", 1)[-1]
    phase = minute_index / 96 * math.tau

    if "SAT" in suffix:
        return 55 + 1.5 * math.sin(phase) + random.uniform(-0.3, 0.3)
    if "RAT" in suffix:
        return 74 + 2.0 * math.sin(phase - 0.8) + random.uniform(-0.4, 0.4)
    if "MAT" in suffix:
        return 67 + 6.0 * math.sin(phase - 0.4) + random.uniform(-0.5, 0.5)
    if "DAT" in suffix:
        return 57 + 1.0 * math.sin(phase) + random.uniform(-0.2, 0.2)
    if "ZN-T" in suffix:
        return 72 + 1.8 * math.sin(phase - 1.0) + random.uniform(-0.4, 0.4)
    if "AIRFLOW" in suffix:
        mid = point.range_max * 0.7 if point.range_max else 800
        return mid + mid * 0.15 * math.sin(phase) + random.uniform(-20, 20)
    if "SPD" in suffix:
        return 55 + 20 * math.sin(phase) + random.uniform(-1.0, 1.0)
    if "DP" in suffix:
        return 12 + 2.5 * math.sin(phase) + random.uniform(-0.3, 0.3)
    if "CHWS" in suffix:
        return 42 + 0.8 * math.sin(phase) + random.uniform(-0.1, 0.1)
    if "CHWR" in suffix:
        return 56 + 1.2 * math.sin(phase - 0.2) + random.uniform(-0.2, 0.2)
    if "HWS" in suffix and not suffix.endswith("SP"):
        return 168 + 2.5 * math.sin(phase) + random.uniform(-0.4, 0.4)
    if "HWR" in suffix:
        return 150 + 2.0 * math.sin(phase - 0.4) + random.uniform(-0.4, 0.4)
    if "CWS" in suffix:
        return 82 + 2.0 * math.sin(phase) + random.uniform(-0.3, 0.3)
    if "CWR" in suffix:
        return 91 + 2.5 * math.sin(phase - 0.3) + random.uniform(-0.3, 0.3)
    if "KW" in suffix:
        return 75 + 18 * math.sin(phase) + random.uniform(-2.0, 2.0)
    if "PRES" in suffix:
        return 7.5 + 0.4 * math.sin(phase) + random.uniform(-0.1, 0.1)
    if point.range_min is not None and point.range_max is not None:
        midpoint = (point.range_min + point.range_max) / 2
        span = point.range_max - point.range_min
        return midpoint + 0.2 * span * math.sin(phase) + random.uniform(-0.02 * span, 0.02 * span)
    return 50 + random.uniform(-1, 1)


def actuator_or_setpoint_value(point: Point, minute_index: int) -> float:
    suffix = point.name.split(" ", 1)[-1]
    phase = minute_index / 96 * math.tau

    if suffix.endswith("-SP") or suffix.endswith("SP"):
        if point.units == "degF":
            return 55 if "DAT" in suffix else 72
        return point.range_min if point.range_min is not None else 0
    if point.units == "pct":
        return max(0, min(100, 50 + 35 * math.sin(phase)))
    return 1 if math.sin(phase) > 0 else 0


def status_or_alarm_value(point: Point, minute_index: int) -> int:
    suffix = point.name.split(" ", 1)[-1]

    if point.kind.value == "alarm":
        if point.name in {"AHU-2 SMK-ALM", "RTU-1 FLT-ALM"}:
            return 1 if minute_index in {28, 29, 30, 64} else 0
        return 0
    if suffix.endswith("STS") or suffix.endswith("ALM"):
        return 1 if 24 <= minute_index <= 80 else 0
    return 0


def quality_for(point: Point, minute_index: int) -> str:
    if point.name == "AHU-1 MAT" and minute_index in {20, 21}:
        return "questionable"
    if point.name == "VAV-203 AIRFLOW" and minute_index in {54, 55}:
        return "bad"
    return "good"


def current_value(point: Point, minute_index: int) -> float | int:
    kind = point.kind.value
    if kind == "sensor":
        return round(sensor_value(point, minute_index), 2)
    if kind in {"actuator", "setpoint"}:
        return round(actuator_or_setpoint_value(point, minute_index), 2)
    if kind in {"status", "alarm"}:
        return status_or_alarm_value(point, minute_index)
    return 0


def generate(project_path: Path, output_dir: Path) -> None:
    random.seed(SEED)
    project = Project.model_validate_json(project_path.read_text())
    output_dir.mkdir(parents=True, exist_ok=True)

    start = datetime(2026, 7, 10, 0, 0, 0)
    timestamps = [start + timedelta(minutes=INTERVAL_MINUTES * i) for i in range(int(HOURS * 60 / INTERVAL_MINUTES))]

    snapshot_path = output_dir / "station_point_snapshot.csv"
    with snapshot_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "controller_id",
                "equipment_id",
                "point_name",
                "point_kind",
                "units",
                "value",
                "quality",
                "timestamp",
            ]
        )
        minute_index = len(timestamps) - 1
        for point in project.points:
            writer.writerow(
                [
                    point.controller_id or "",
                    point.equipment_id,
                    point.name,
                    point.kind.value,
                    point.units or "",
                    current_value(point, minute_index),
                    quality_for(point, minute_index),
                    timestamps[-1].isoformat(),
                ]
            )

    trends_path = output_dir / "station_trends.csv"
    with trends_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "point_name", "value", "quality"])
        for minute_index, timestamp in enumerate(timestamps):
            for point in project.points:
                writer.writerow(
                    [
                        timestamp.isoformat(),
                        point.name,
                        current_value(point, minute_index),
                        quality_for(point, minute_index),
                    ]
                )

    alarms_path = output_dir / "station_alarms.csv"
    with alarms_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "alarm_name", "point_name", "severity", "state", "value", "limit", "message"])
        writer.writerows(
            [
                [
                    (start + timedelta(hours=7, minutes=15)).isoformat(),
                    "AHU-2 Smoke Shutdown",
                    "AHU-2 SMK-ALM",
                    "high",
                    "active",
                    1,
                    1,
                    "Smoke shutdown alarm active during occupied mode",
                ],
                [
                    (start + timedelta(hours=7, minutes=30)).isoformat(),
                    "AHU-2 Smoke Shutdown",
                    "AHU-2 SMK-ALM",
                    "high",
                    "cleared",
                    0,
                    1,
                    "Smoke shutdown alarm cleared after reset",
                ],
                [
                    (start + timedelta(hours=16)).isoformat(),
                    "RTU-1 Unit Fault",
                    "RTU-1 FLT-ALM",
                    "medium",
                    "active",
                    1,
                    1,
                    "Rooftop unit reported compressor lockout",
                ],
                [
                    (start + timedelta(hours=16, minutes=45)).isoformat(),
                    "RTU-1 Unit Fault",
                    "RTU-1 FLT-ALM",
                    "medium",
                    "cleared",
                    0,
                    1,
                    "Rooftop unit fault cleared after manual reset",
                ],
                [
                    (start + timedelta(hours=11, minutes=30)).isoformat(),
                    "CHLR-1 Differential Pressure Low",
                    "CHLR-1 CHW-DP",
                    "medium",
                    "active",
                    6.8,
                    8.0,
                    "Chilled water differential pressure below expected limit",
                ],
            ]
        )

    controller_path = output_dir / "controller_runtime.csv"
    with controller_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "timestamp",
                "controller_id",
                "online",
                "protocols",
                "equipment_count",
                "owned_points",
                "cpu_load_pct",
                "network_health",
            ]
        )
        for index, controller in enumerate(project.controllers):
            writer.writerow(
                [
                    timestamps[-1].isoformat(),
                    controller.id,
                    "true",
                    ",".join(protocol.value for protocol in controller.protocols),
                    len(controller.serves_equipment_ids),
                    len(controller.owned_point_names),
                    24 + index * 7,
                    "good",
                ]
            )


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    generate(
        repo_root / "examples" / "sample-hvac-project.json",
        repo_root / "examples" / "fake_station",
    )
