"""Project-backed BAS lab emulation helpers."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from pathlib import Path

    from .models import Point, Project

BACNET_MAX_INSTANCE = 4_194_302


class EmulatedPoint(BaseModel):
    """Runtime point state exposed by the emulator."""

    point_name: str
    equipment_id: str
    controller_id: str
    kind: str
    direction: str
    object_type: str
    object_instance: int
    units: str | None = None
    writable: bool = False
    present_value: bool | float | int | str
    baseline_value: bool | float | int | str


class EmulatedDevice(BaseModel):
    """Gateway or controller device."""

    device_id: str
    role: str
    display_name: str
    bacnet_device_instance: int
    protocol: str
    address: str | None = None
    network_number: int | None = None
    vendor: str | None = None
    model: str | None = None
    parent_device_id: str | None = None
    point_count: int = 0
    points: list[EmulatedPoint] = Field(default_factory=list)


class EmulationManifest(BaseModel):
    """Static lab manifest derived from a BAS project."""

    generated_at: datetime
    project_id: str
    project_name: str
    gateway: EmulatedDevice
    controllers: list[EmulatedDevice]


class EmulationSnapshot(BaseModel):
    """Serializable runtime snapshot for the lab."""

    generated_at: datetime
    tick: int
    project_id: str
    weather: dict[str, bool | float | int | str] = Field(default_factory=dict)
    station: dict[str, Any] = Field(default_factory=dict)
    devices: list[EmulatedDevice]


class PointWriteRequest(BaseModel):
    """Point write payload for the REST API."""

    value: bool | float | int | str


class ScenarioWriteRequest(BaseModel):
    """Scenario change payload for the REST API."""

    scenario: str


class WeatherWriteRequest(BaseModel):
    """Weather override payload for the REST API."""

    mode: str = "manual"
    outdoor_air_temp: float | None = None
    outdoor_air_humidity: float | None = None
    wind_mph: float | None = None
    cloud_cover_pct: float | None = None
    conditions: str | None = None


class ControllerWriteRequest(BaseModel):
    """Controller state change payload for the REST API."""

    state: str


class ReadOnlyPointError(ValueError):
    """Raised when the emulator rejects a write to a read-only point."""


def _stable_instance(*parts: str) -> int:
    seed = "::".join(parts).encode("utf-8")
    digest = hashlib.sha1(seed).hexdigest()
    return int(digest[:8], 16) % BACNET_MAX_INSTANCE + 1


def _normalize_token(value: str) -> str:
    """Collapse BAS point labels into a delimiter-agnostic token."""
    return re.sub(r"[^A-Z0-9]+", "", value.upper())


def _protocol_for_controller(project: Project, controller_id: str) -> str:
    controller = project.get_controller(controller_id)
    if controller is None:
        return "BACnet/IP"
    if controller.protocols:
        return controller.protocols[0].value
    if controller.network_addresses:
        return controller.network_addresses[0].protocol.value
    return "BACnet/IP"


def _address_for_controller(project: Project, controller_id: str) -> tuple[str | None, int | None]:
    controller = project.get_controller(controller_id)
    if controller is None or not controller.network_addresses:
        return None, None
    address = controller.network_addresses[0]
    return address.address, address.network_number


def _object_type_for_point(point: Point) -> str:
    if point.bacnet_object_type:
        return point.bacnet_object_type
    if point.kind.value in {"sensor", "trend"}:
        return "AI"
    if point.kind.value in {"setpoint", "parameter", "calculated", "derived"}:
        return "AV"
    if point.kind.value in {"actuator"}:
        return "AO"
    if point.kind.value in {"status", "alarm", "schedule"}:
        return "BV"
    return "AV"


def _baseline_value(point: Point, object_type: str) -> bool | float | int | str:
    if object_type.startswith("B"):
        return False

    units = (point.units or "").strip().lower()
    name = point.name.lower()
    default = 50.0

    if "temp" in name or units in {"f", "deg f", "°f"}:
        default = 72.0
    elif units in {"c", "deg c", "°c"}:
        default = 22.0
    elif "%" in units or units in {"percent", "pct", "rh"}:
        default = 45.0
    elif "pressure" in name or units in {"in-wc", "pa", "psi"}:
        default = 1.5
    elif "flow" in name or units in {"cfm", "gpm"}:
        default = 0.0
    elif point.kind.value == "setpoint":
        default = 72.0
    elif point.kind.value == "actuator":
        default = 0.0

    return default


def _writable(point: Point, object_type: str) -> bool:
    if point.direction.value in {"output", "bidirectional"}:
        return True
    return object_type in {"AO", "AV", "BO", "BV", "MSV", "MSO"}


def _controller_ids_for_project(project: Project) -> list[str]:
    discovered = {controller.id for controller in project.controllers}
    for equipment in project.equipment:
        controller_id = project.effective_equipment_controller_id(equipment)
        if controller_id:
            discovered.add(controller_id)
    for point in project.points:
        controller_id = project.effective_point_controller_id(point)
        if controller_id:
            discovered.add(controller_id)
    return sorted(discovered)


class BasEmulationLab:
    """Deterministic BAS lab state with lightweight point simulation."""

    def __init__(self, project: Project, gateway_name: str = "JACE-EMU") -> None:
        self.project = project
        self.gateway_name = gateway_name
        self.tick = 0
        self.gateway, self.controllers = self._build_devices()
        self.scenarios: dict[str, dict[str, Any]] = {
            "occupied": {
                "label": "Occupied Cooling",
                "schedule_mode": "occupied",
                "description": "Normal daytime operation with moderate cooling demand.",
                "weather": {"outdoor_air_temp": 88.0, "outdoor_air_humidity": 54.0, "wind_mph": 6.0, "cloud_cover_pct": 28.0, "conditions": "sunny"},
                "zone_sp": 72.0,
                "dat_sp": 55.0,
            },
            "hot_humid": {
                "label": "Hot Humid Peak",
                "schedule_mode": "occupied",
                "description": "Peak summer load with elevated humidity and stronger cooling demand.",
                "weather": {"outdoor_air_temp": 96.0, "outdoor_air_humidity": 69.0, "wind_mph": 4.5, "cloud_cover_pct": 46.0, "conditions": "humid"},
                "zone_sp": 72.0,
                "dat_sp": 54.0,
            },
            "morning_warmup": {
                "label": "Morning Warmup",
                "schedule_mode": "warmup",
                "description": "Early start with lower outdoor air and active heating sequence.",
                "weather": {"outdoor_air_temp": 48.0, "outdoor_air_humidity": 63.0, "wind_mph": 8.0, "cloud_cover_pct": 38.0, "conditions": "cool"},
                "zone_sp": 71.0,
                "dat_sp": 62.0,
            },
            "freeze_alarm": {
                "label": "Freeze Protection",
                "schedule_mode": "alarm",
                "description": "Low mixed air and freeze-protection response with fan shutdown logic.",
                "weather": {"outdoor_air_temp": 19.0, "outdoor_air_humidity": 71.0, "wind_mph": 15.0, "cloud_cover_pct": 84.0, "conditions": "freeze"},
                "zone_sp": 70.0,
                "dat_sp": 65.0,
            },
            "fan_failure": {
                "label": "Supply Fan Failure",
                "schedule_mode": "fault",
                "description": "Commanded operation with no proof, driving station alarm behavior.",
                "weather": {"outdoor_air_temp": 86.0, "outdoor_air_humidity": 58.0, "wind_mph": 5.0, "cloud_cover_pct": 22.0, "conditions": "fault"},
                "zone_sp": 72.0,
                "dat_sp": 55.0,
            },
        }
        self.active_scenario = "hot_humid"
        self.weather_mode = "scenario"
        self.manual_overrides: set[str] = set()
        self.controller_states: dict[str, str] = {device.device_id: "online" for device in self.controllers}
        self.controller_health: dict[str, float] = {device.device_id: 100.0 for device in self.controllers}
        self.zone_offsets: dict[str, float] = {}
        self.weather = {
            "outdoor_air_temp": 91.0,
            "outdoor_air_humidity": 58.0,
            "wind_mph": 7.5,
            "cloud_cover_pct": 24.0,
            "conditions": "sunny",
        }
        self._apply_scenario_defaults(self.active_scenario, reset_overrides=False)

    def _build_devices(self) -> tuple[EmulatedDevice, list[EmulatedDevice]]:
        project_id = self.project.metadata.project_id
        gateway = EmulatedDevice(
            device_id=self.gateway_name,
            role="gateway",
            display_name=f"{self.gateway_name} ({project_id})",
            bacnet_device_instance=_stable_instance(project_id, self.gateway_name, "gateway"),
            protocol="BACnet/IP",
            address="127.0.0.1",
            vendor="BAS Assistant",
            model="Pi Lab Gateway",
        )

        controllers: list[EmulatedDevice] = []
        for controller_id in _controller_ids_for_project(self.project):
            controller = self.project.get_controller(controller_id)
            protocol = _protocol_for_controller(self.project, controller_id)
            address, network_number = _address_for_controller(self.project, controller_id)
            controller_points = self.project.get_points_for_controller(controller_id)
            points = [self._build_point(point, controller_id) for point in controller_points]
            device = EmulatedDevice(
                device_id=controller_id,
                role="controller",
                display_name=controller.name if controller and controller.name else controller_id,
                bacnet_device_instance=_stable_instance(project_id, controller_id, "controller"),
                protocol=protocol,
                address=address,
                network_number=network_number,
                vendor=controller.vendor if controller else None,
                model=controller.model if controller else None,
                parent_device_id=gateway.device_id,
                point_count=len(points),
                points=points,
            )
            controllers.append(device)

        gateway.point_count = sum(device.point_count for device in controllers)
        return gateway, controllers

    def _build_point(self, point: Point, controller_id: str) -> EmulatedPoint:
        object_type = _object_type_for_point(point)
        present_value = _baseline_value(point, object_type)
        return EmulatedPoint(
            point_name=point.name,
            equipment_id=point.equipment_id,
            controller_id=controller_id,
            kind=point.kind.value,
            direction=point.direction.value,
            object_type=object_type,
            object_instance=point.bacnet_instance
            or _stable_instance(self.project.metadata.project_id, point.name, object_type),
            units=point.units,
            writable=_writable(point, object_type),
            present_value=present_value,
            baseline_value=present_value,
        )

    def manifest(self) -> EmulationManifest:
        return EmulationManifest(
            generated_at=datetime.now(UTC),
            project_id=self.project.metadata.project_id,
            project_name=self.project.metadata.name,
            gateway=self.gateway.model_copy(deep=True),
            controllers=[device.model_copy(deep=True) for device in self.controllers],
        )

    def snapshot(self) -> EmulationSnapshot:
        devices = [
            self.gateway.model_copy(deep=True),
            *[device.model_copy(deep=True) for device in self.controllers],
        ]
        return EmulationSnapshot(
            generated_at=datetime.now(UTC),
            tick=self.tick,
            project_id=self.project.metadata.project_id,
            weather=dict(self.weather),
            station=self.station_summary(),
            devices=devices,
        )

    def step(self, steps: int = 1) -> EmulationSnapshot:
        for _ in range(max(steps, 0)):
            self.tick += 1
            self._step_weather()
            self._apply_station_logic()
            for device in self.controllers:
                for point in device.points:
                    if point.writable:
                        continue
                    point.present_value = self._next_value(point)
        return self.snapshot()

    def station_summary(self) -> dict[str, Any]:
        points = self.list_points()
        alarms = [point for point in points if point.kind == "alarm" and bool(point.present_value)]
        overrides = sorted(self.manual_overrides)
        controller_summaries = []
        for controller in self.controllers:
            point_count = len(controller.points)
            writable_count = sum(1 for point in controller.points if point.writable)
            overridden_count = sum(1 for point in controller.points if point.point_name in self.manual_overrides)
            controller_summaries.append(
                {
                    "controller_id": controller.device_id,
                    "display_name": controller.display_name,
                    "state": self.controller_states.get(controller.device_id, "online"),
                    "health_pct": round(self.controller_health.get(controller.device_id, 100.0), 1),
                    "point_count": point_count,
                    "writable_count": writable_count,
                    "override_count": overridden_count,
                    "protocol": controller.protocol,
                    "address": controller.address,
                    "network_number": controller.network_number,
                }
            )
        return {
            "scenario_id": self.active_scenario,
            "scenario_label": self.scenarios.get(self.active_scenario, {}).get("label", self.active_scenario),
            "scenario_description": self.scenarios.get(self.active_scenario, {}).get("description", ""),
            "schedule_mode": self.scenarios.get(self.active_scenario, {}).get("schedule_mode", "occupied"),
            "weather_mode": self.weather_mode,
            "device_count": len(self.controllers) + 1,
            "point_count": len(points),
            "alarm_count": len(alarms),
            "override_count": len(overrides),
            "active_alarms": [point.point_name for point in alarms[:8]],
            "overrides": overrides[:12],
            "controllers": controller_summaries,
            "available_scenarios": [
                {"id": scenario_id, "label": details["label"], "description": details["description"]}
                for scenario_id, details in self.scenarios.items()
            ],
        }

    def _step_weather(self) -> None:
        if self.weather_mode == "manual":
            return
        scenario_weather = self.scenarios.get(self.active_scenario, {}).get("weather", {})
        base_temp = float(scenario_weather.get("outdoor_air_temp", 88.0))
        base_humidity = float(scenario_weather.get("outdoor_air_humidity", 54.0))
        base_wind = float(scenario_weather.get("wind_mph", 6.5))
        base_cloud = float(scenario_weather.get("cloud_cover_pct", 35.0))
        diurnal = math.sin(self.tick / 18.0)
        humidity_wave = math.sin((self.tick + 5) / 23.0)
        wind_wave = math.sin((self.tick + 9) / 11.0)
        cloud_wave = math.sin((self.tick + 17) / 14.0)
        outdoor_air_temp = round(base_temp + (diurnal * 4.5), 1)
        outdoor_air_humidity = round(max(10.0, min(100.0, base_humidity + (humidity_wave * 6.0))), 1)
        wind_mph = round(max(0.5, base_wind + (wind_wave * 2.0)), 1)
        cloud_cover_pct = round(max(0.0, min(100.0, base_cloud + (cloud_wave * 18.0))), 1)
        if cloud_cover_pct > 72:
            conditions = "overcast"
        elif outdoor_air_humidity > 66 and cloud_cover_pct > 48:
            conditions = "humid"
        elif outdoor_air_temp < 32:
            conditions = "freeze"
        elif outdoor_air_temp > 92:
            conditions = "hot"
        else:
            conditions = "sunny"
        self.weather = {
            "outdoor_air_temp": outdoor_air_temp,
            "outdoor_air_humidity": outdoor_air_humidity,
            "wind_mph": wind_mph,
            "cloud_cover_pct": cloud_cover_pct,
            "conditions": conditions,
        }

    def set_scenario(self, scenario: str) -> EmulationSnapshot:
        if scenario not in self.scenarios:
            raise KeyError(scenario)
        self.active_scenario = scenario
        self.weather_mode = "scenario"
        self._apply_scenario_defaults(scenario, reset_overrides=True)
        return self.snapshot()

    def set_weather(self, payload: WeatherWriteRequest) -> EmulationSnapshot:
        mode = payload.mode.strip().lower() if payload.mode else "manual"
        if mode == "scenario":
            self.weather_mode = "scenario"
            self._step_weather()
            return self.snapshot()
        self.weather_mode = "manual"
        for key in ("outdoor_air_temp", "outdoor_air_humidity", "wind_mph", "cloud_cover_pct", "conditions"):
            value = getattr(payload, key)
            if value is not None:
                self.weather[key] = value
        return self.snapshot()

    def set_controller_state(self, controller_id: str, state: str) -> EmulationSnapshot:
        controller = next((device for device in self.controllers if device.device_id == controller_id), None)
        if controller is None:
            raise KeyError(controller_id)
        normalized = state.strip().lower()
        if normalized not in {"online", "degraded", "offline", "alarm"}:
            raise ValueError(state)
        self.controller_states[controller_id] = normalized
        self.controller_health[controller_id] = {
            "online": 100.0,
            "degraded": 62.0,
            "offline": 0.0,
            "alarm": 28.0,
        }[normalized]
        return self.snapshot()

    def clear_overrides(self) -> EmulationSnapshot:
        self.manual_overrides.clear()
        self._apply_scenario_defaults(self.active_scenario, reset_overrides=False)
        return self.snapshot()

    def reset(self) -> EmulationSnapshot:
        self.tick = 0
        self.weather_mode = "scenario"
        self.manual_overrides.clear()
        self.controller_states = {device.device_id: "online" for device in self.controllers}
        self.controller_health = {device.device_id: 100.0 for device in self.controllers}
        self._apply_scenario_defaults(self.active_scenario, reset_overrides=False)
        return self.snapshot()

    def _apply_scenario_defaults(self, scenario: str, *, reset_overrides: bool) -> None:
        details = self.scenarios.get(scenario, {})
        if reset_overrides:
            self.manual_overrides.clear()
        self.weather.update(details.get("weather", {}))
        self.zone_offsets = {
            "occupied": {"VAV-101": 0.4, "VAV-102": 0.8, "VAV-103": 1.6, "VAV-104": -0.6},
            "hot_humid": {"VAV-101": 1.4, "VAV-102": 1.8, "VAV-103": 2.6, "VAV-104": 0.6},
            "morning_warmup": {"VAV-101": -2.4, "VAV-102": -2.0, "VAV-103": -1.6, "VAV-104": -2.8},
            "freeze_alarm": {"VAV-101": -3.2, "VAV-102": -2.8, "VAV-103": -2.5, "VAV-104": -3.4},
            "fan_failure": {"VAV-101": 2.0, "VAV-102": 2.2, "VAV-103": 2.6, "VAV-104": 1.8},
        }.get(scenario, {})
        self._write_if_not_overridden("AHU-1 DAT SP", details.get("dat_sp", 55.0))
        for equipment in ("VAV-101", "VAV-102", "VAV-103", "VAV-104"):
            self._write_if_not_overridden(f"{equipment} ZT SP", details.get("zone_sp", 72.0))
        if scenario == "morning_warmup":
            self._write_if_not_overridden("AHU-1 HTG VALVE", 48.0)
            self._write_if_not_overridden("AHU-1 CLG VALVE", 0.0)
            self._write_if_not_overridden("AHU-1 OA DAMPER", 12.0)
            self._write_if_not_overridden("AHU-1 SF CMD", 42.0)
        elif scenario == "freeze_alarm":
            self._write_if_not_overridden("AHU-1 HTG VALVE", 100.0)
            self._write_if_not_overridden("AHU-1 CLG VALVE", 0.0)
            self._write_if_not_overridden("AHU-1 OA DAMPER", 0.0)
            self._write_if_not_overridden("AHU-1 SF CMD", 0.0)
        elif scenario == "fan_failure":
            self._write_if_not_overridden("AHU-1 SF CMD", 76.0)
            self._write_if_not_overridden("AHU-1 OA DAMPER", 32.0)
            self._write_if_not_overridden("AHU-1 CLG VALVE", 66.0)
            self._write_if_not_overridden("AHU-1 HTG VALVE", 0.0)
        else:
            self._write_if_not_overridden("AHU-1 HTG VALVE", 0.0)
            self._write_if_not_overridden("AHU-1 OA DAMPER", 24.0 if scenario == "occupied" else 28.0)
            self._write_if_not_overridden("AHU-1 CLG VALVE", 52.0 if scenario == "occupied" else 74.0)
            self._write_if_not_overridden("AHU-1 SF CMD", 68.0 if scenario == "occupied" else 82.0)

    def _apply_station_logic(self) -> None:
        zone_sp = self._avg_point(("ZT SP",), default=float(self.scenarios.get(self.active_scenario, {}).get("zone_sp", 72.0)))
        zone_temp = self._avg_zone_temperature(default=zone_sp)
        zone_error = zone_temp - zone_sp
        outdoor_air_temp = float(self.weather["outdoor_air_temp"])
        outdoor_air_humidity = float(self.weather["outdoor_air_humidity"])
        demand = max(0.0, min(1.0, 0.45 + (zone_error * 0.22) + max(outdoor_air_temp - 75.0, 0.0) / 40.0))
        humid_penalty = max(0.0, (outdoor_air_humidity - 55.0) / 55.0)
        if self.active_scenario == "morning_warmup":
            fan_cmd = 45.0
            clg_valve = 0.0
            htg_valve = max(30.0, 58.0 - max(outdoor_air_temp - 45.0, 0.0))
            oa_damper = 10.0
        elif self.active_scenario == "freeze_alarm":
            fan_cmd = 0.0
            clg_valve = 0.0
            htg_valve = 100.0
            oa_damper = 0.0
        elif self.active_scenario == "fan_failure":
            fan_cmd = 76.0
            clg_valve = min(100.0, 68.0 + demand * 18.0)
            htg_valve = 0.0
            oa_damper = 30.0
            self.controller_states["MPC-1"] = "alarm"
            self.controller_health["MPC-1"] = 24.0
        else:
            fan_cmd = min(100.0, 52.0 + demand * 38.0)
            clg_valve = min(100.0, 22.0 + demand * 58.0 + humid_penalty * 16.0)
            htg_valve = max(0.0, 28.0 - (outdoor_air_temp - 48.0) * 1.7)
            oa_damper = min(100.0, max(12.0, 16.0 + demand * 24.0 - humid_penalty * 7.0))
        self._write_if_not_overridden("AHU-1 SF CMD", round(fan_cmd, 1))
        self._write_if_not_overridden("AHU-1 OA DAMPER", round(oa_damper, 1))
        self._write_if_not_overridden("AHU-1 CLG VALVE", round(clg_valve, 1))
        self._write_if_not_overridden("AHU-1 HTG VALVE", round(htg_valve, 1))
        self._write_if_not_overridden("AHU-1 RA DAMPER", round(max(0.0, 100.0 - oa_damper), 1))
        self._write_if_not_overridden("AHU-1 EA DAMPER", round(max(5.0, oa_damper * 0.75), 1))
        self._write_if_not_overridden("AHU-1 SF VFD SPD", round(max(fan_cmd - 3.0, 0.0), 1))

        base_flow = max(fan_cmd / 100.0, 0.1)
        for equipment_id in ("VAV-101", "VAV-102", "VAV-103", "VAV-104"):
            zone_target = self._point_by_name(f"{equipment_id} ZT SP")
            zone_setpoint = float(zone_target.present_value) if zone_target and isinstance(zone_target.present_value, (int, float)) else zone_sp
            offset = self.zone_offsets.get(equipment_id, 0.0)
            simulated_zone_temp = zone_setpoint + offset + math.sin((self.tick + len(equipment_id)) / 9.0) * 0.9
            error = simulated_zone_temp - zone_setpoint
            damper = min(100.0, max(18.0, 38.0 + (error * 26.0) + demand * 18.0))
            reheat = 0.0 if error >= 0.0 else min(100.0, abs(error) * 40.0 + (18.0 if self.active_scenario in {"morning_warmup", "freeze_alarm"} else 0.0))
            flow_sp = round((base_flow * (700.0 if equipment_id == "VAV-104" else 950.0)) + damper * 6.0, 0)
            self._write_if_not_overridden(f"{equipment_id} DAMPER", round(damper, 1))
            self._write_if_not_overridden(f"{equipment_id} FLOW SP", flow_sp)
            self._write_if_not_overridden(f"{equipment_id} REHEAT CMD", round(reheat, 1))

        for controller_id in list(self.controller_states):
            if self.active_scenario != "fan_failure" or controller_id != "MPC-1":
                state = self.controller_states.get(controller_id, "online")
                self.controller_health[controller_id] = {"online": 100.0, "degraded": 62.0, "offline": 0.0, "alarm": 28.0}.get(state, 100.0)

    def _next_value(self, point: EmulatedPoint) -> bool | float | int | str:
        controller_state = self.controller_states.get(point.controller_id, "online")
        if controller_state == "offline":
            if isinstance(point.baseline_value, bool):
                return False
            if point.kind in {"status", "alarm"}:
                return False
            return 0.0 if isinstance(point.baseline_value, (int, float)) else point.baseline_value

        equipment_points = self._equipment_points(point.equipment_id)
        point_name = _normalize_token(point.point_name)
        baseline_numeric = float(point.baseline_value) if isinstance(point.baseline_value, (int, float)) else 0.0
        fan_enabled = self._point_value(equipment_points, ("SF-CMD", "SUPPLY FAN CMD"), default=False) or (
            self._point_value(equipment_points, ("SF-VFD-SPD", "SUPPLY FAN SPD"), default=0.0) > 5
        )
        cooling_cmd = float(self._point_value(equipment_points, ("CLG VALVE", "CHW-VLV-CMD", "CC_V", "COOL"), default=0.0))
        heating_cmd = float(self._point_value(equipment_points, ("HTG VALVE", "HW-VLV-CMD", "HC_V", "HEAT"), default=0.0))
        oa_cmd = float(self._point_value(equipment_points, ("OA DAMPER", "OA-DMP-CMD", "OAD_P", "OUTSIDE AIR DAMPER"), default=18.0))
        dat_sp = float(self._point_value(equipment_points, ("DAT SP", "DAT-SP", "SAT-SP", "SUPPLY TEMP SP"), default=55.0))
        zone_sp = float(self._point_value(equipment_points, ("ZT SP", "ZN-T-SP", "ZONE TEMP SP"), default=72.0))
        outdoor_air_temp = float(self.weather["outdoor_air_temp"])
        outdoor_air_humidity = float(self.weather["outdoor_air_humidity"])
        return_air_temp = round(zone_sp + 2.2 + math.sin((self.tick + (point.object_instance % 9)) / 7.0), 2)
        mixed_air_temp = round(((outdoor_air_temp * (oa_cmd / 100.0)) + (return_air_temp * (1.0 - (oa_cmd / 100.0)))), 2)
        supply_air_temp = round(
            dat_sp
            - (cooling_cmd * 0.065)
            + (heating_cmd * 0.055)
            + (0.4 if fan_enabled else 1.4),
            2,
        )
        if controller_state == "degraded":
            supply_air_temp = round(supply_air_temp + 1.1, 2)
            mixed_air_temp = round(mixed_air_temp + 0.6, 2)

        if isinstance(point.baseline_value, bool):
            if "SFSTS" in point_name or "SFSTATUS" in point_name or "FANSTATUS" in point_name:
                return bool(fan_enabled and self.active_scenario != "fan_failure")
            if "ALM" in point_name or point.kind == "alarm":
                alarm_trip = (
                    self.active_scenario in {"freeze_alarm", "fan_failure"}
                    or controller_state == "alarm"
                    or (cooling_cmd > 92 and outdoor_air_humidity > 66 and fan_enabled)
                )
                return bool(alarm_trip or ((self.tick + point.object_instance) % 37 == 0))
            if "DMPR" in point_name and ("STS" in point_name or "PROOF" in point_name):
                return oa_cmd > 5
            if "OCC" in point_name:
                return self.scenarios.get(self.active_scenario, {}).get("schedule_mode") in {"occupied", "warmup"}
            if point.kind in {"alarm", "status"}:
                return bool((self.tick + point.object_instance) % 10 == 0)
            return point.baseline_value
        if isinstance(point.baseline_value, (int, float)):
            if "OAT" in point_name or "OUTSIDEAIRTEMP" in point_name:
                return outdoor_air_temp
            if "OAH" in point_name or "OAHUM" in point_name or "OUTSIDEAIRHUM" in point_name:
                return outdoor_air_humidity
            if "RAT" in point_name or "RETURNAIRTEMP" in point_name:
                return return_air_temp
            if "MAT" in point_name or "MIXEDAIRTEMP" in point_name:
                return mixed_air_temp
            if "SAT" in point_name or "DAT" in point_name or "DISCHARGEAIRTEMP" in point_name:
                return supply_air_temp
            if "FILTERDP" in point_name:
                return round(0.42 + (float(self._point_value(equipment_points, ("SF CMD",), default=55.0)) / 100.0) * 0.85, 2)
            if "DUCTSP" in point_name:
                return round(0.65 + (float(self._point_value(equipment_points, ("SF CMD",), default=55.0)) / 100.0) * 1.35, 2)
            if "ZONETEMP" in point_name or "ZNT" in point_name or "SPACETEMP" in point_name:
                equipment_offset = self.zone_offsets.get(point.equipment_id, 0.0)
                zone_load = math.sin((self.tick + (point.object_instance % 13)) / 8.0) * 0.9
                return round(zone_sp + equipment_offset + zone_load, 2)
            if "CFM" in point_name or "AIRFLOW" in point_name or "FLOW" in point_name:
                return round((self._point_value(equipment_points, ("DAMPER", "DMPR_P", "DMPR-CMD"), default=48.0) / 100.0) * 1850.0, 0)
            if "RHV" in point_name or "REHEAT" in point_name:
                return round(max(0.0, min(100.0, float(self._point_value(equipment_points, ("REHEAT CMD", "RHT"), default=heating_cmd)))), 1)
            if "OAD" in point_name or "OADMP" in point_name or "DAMPER" in point_name:
                damper_value = float(self._point_value(equipment_points, ("DAMPER", "OA DAMPER", "OA-DMP", "DMPR-CMD"), default=oa_cmd))
                return round(max(0.0, min(100.0, damper_value)), 1)
            if "SPD" in point_name or "VFD" in point_name:
                return round(float(self._point_value(equipment_points, ("SF VFD SPD", "SF-VFD-SPD",), default=45.0)), 1)
            if "VALVE" in point_name or "VLV" in point_name:
                if "CHW" in point_name or "COOL" in point_name:
                    return round(cooling_cmd, 1)
                if "HW" in point_name or "HEAT" in point_name or "RHT" in point_name:
                    return round(heating_cmd, 1)
            if point.kind not in {"sensor", "trend", "derived", "calculated"}:
                return point.baseline_value
            amplitude = max(abs(baseline_numeric) * 0.05, 1.0)
            offset = math.sin((self.tick + (point.object_instance % 11)) / 3.0) * amplitude
            return round(baseline_numeric + offset, 2)
        return point.baseline_value

    def _point_by_name(self, point_name: str) -> EmulatedPoint | None:
        for point in self.list_points():
            if point.point_name == point_name:
                return point
        return None

    def _write_if_not_overridden(self, point_name: str, value: bool | float | int | str) -> None:
        if point_name in self.manual_overrides:
            return
        point = self._point_by_name(point_name)
        if point is not None and point.writable:
            point.present_value = value

    def _avg_point(self, fragments: tuple[str, ...], *, default: float) -> float:
        values: list[float] = []
        for point in self.list_points():
            normalized_name = _normalize_token(point.point_name)
            if any(_normalize_token(fragment) in normalized_name for fragment in fragments) and isinstance(point.present_value, (int, float)):
                values.append(float(point.present_value))
        if not values:
            return default
        return sum(values) / len(values)

    def _avg_zone_temperature(self, *, default: float) -> float:
        values: list[float] = []
        for point in self.list_points():
            normalized_name = _normalize_token(point.point_name)
            if ("ZNT" in normalized_name or "ZONETEMP" in normalized_name) and isinstance(point.present_value, (int, float)):
                values.append(float(point.present_value))
        if not values:
            return default
        return sum(values) / len(values)

    def _equipment_points(self, equipment_id: str) -> dict[str, EmulatedPoint]:
        return {
            _normalize_token(point.point_name): point
            for device in self.controllers
            for point in device.points
            if point.equipment_id == equipment_id
        }

    def _point_value(
        self,
        equipment_points: dict[str, EmulatedPoint],
        fragments: tuple[str, ...],
        *,
        default: bool | float | int,
    ) -> bool | float | int:
        normalized_fragments = tuple(_normalize_token(fragment) for fragment in fragments)
        for name, point in equipment_points.items():
            if any(fragment in name for fragment in normalized_fragments):
                return point.present_value  # type: ignore[return-value]
        return default

    def list_points(self) -> list[EmulatedPoint]:
        return [point for device in self.controllers for point in device.points]

    def get_point(self, point_name: str) -> EmulatedPoint:
        for point in self.list_points():
            if point.point_name == point_name:
                return point
        raise KeyError(point_name)

    def write_point(self, point_name: str, value: bool | float | int | str) -> EmulatedPoint:
        point = self.get_point(point_name)
        if not point.writable:
            raise ReadOnlyPointError(point_name)
        point.present_value = value
        self.manual_overrides.add(point_name)
        return point

    def write_output(self, output_dir: Path) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "lab_manifest.json"
        snapshot_path = output_dir / "runtime_snapshot.json"
        controllers_path = output_dir / "controllers"
        controllers_path.mkdir(exist_ok=True)

        manifest_path.write_text(self.manifest().model_dump_json(indent=2), encoding="utf-8")
        snapshot_path.write_text(self.snapshot().model_dump_json(indent=2), encoding="utf-8")
        for controller in self.controllers:
            device_path = controllers_path / f"{controller.device_id}.json"
            device_path.write_text(controller.model_dump_json(indent=2), encoding="utf-8")

        return {
            "manifest": manifest_path,
            "snapshot": snapshot_path,
            "controllers_dir": controllers_path,
        }


def create_emulation_app(project: Project, gateway_name: str = "JACE-EMU") -> FastAPI:  # noqa: C901
    """Create a lightweight REST emulator app for Pi-based lab testing."""

    lab = BasEmulationLab(project=project, gateway_name=gateway_name)
    app = FastAPI(title="BAS Assistant Emulator", version="0.1.0")
    app.state.lab = lab

    def _json_devices() -> list[dict[str, Any]]:
        return [
            lab.gateway.model_dump(mode="json"),
            *[device.model_dump(mode="json") for device in lab.controllers],
        ]

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "project_id": lab.project.metadata.project_id, "tick": lab.tick}

    @app.get("/manifest")
    async def manifest() -> dict[str, Any]:
        return lab.manifest().model_dump(mode="json")

    @app.get("/snapshot")
    async def snapshot() -> dict[str, Any]:
        return lab.snapshot().model_dump(mode="json")

    @app.post("/step")
    async def step(steps: int = 1) -> dict[str, Any]:
        return lab.step(steps=steps).model_dump(mode="json")

    @app.post("/scenario")
    async def scenario(request: ScenarioWriteRequest) -> dict[str, Any]:
        try:
            return lab.set_scenario(request.scenario).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown scenario {request.scenario}") from exc

    @app.post("/weather")
    async def weather(request: WeatherWriteRequest) -> dict[str, Any]:
        return lab.set_weather(request).model_dump(mode="json")

    @app.post("/controllers/{controller_id}")
    async def controller_state(controller_id: str, request: ControllerWriteRequest) -> dict[str, Any]:
        try:
            return lab.set_controller_state(controller_id, request.state).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown controller {controller_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid controller state {exc}") from exc

    @app.post("/reset")
    async def reset() -> dict[str, Any]:
        return lab.reset().model_dump(mode="json")

    @app.post("/overrides/clear")
    async def clear_overrides() -> dict[str, Any]:
        return lab.clear_overrides().model_dump(mode="json")

    @app.get("/devices")
    async def devices() -> dict[str, Any]:
        return {"devices": _json_devices()}

    @app.get("/devices/{device_id}")
    async def device(device_id: str) -> dict[str, Any]:
        if device_id == lab.gateway.device_id:
            return lab.gateway.model_dump(mode="json")
        for controller in lab.controllers:
            if controller.device_id == device_id:
                return controller.model_dump(mode="json")
        raise HTTPException(status_code=404, detail=f"Unknown device {device_id}")

    @app.get("/points")
    async def points() -> dict[str, Any]:
        return {"points": [point.model_dump(mode="json") for point in lab.list_points()]}

    @app.get("/points/{point_name}")
    async def point(point_name: str) -> dict[str, Any]:
        try:
            return lab.get_point(point_name).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown point {point_name}") from exc

    @app.post("/points/{point_name}")
    async def write_point(point_name: str, request: PointWriteRequest) -> dict[str, Any]:
        try:
            return lab.write_point(point_name, request.value).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown point {point_name}") from exc
        except ReadOnlyPointError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Point {exc} is read-only in the emulator",
            ) from exc

    return app
