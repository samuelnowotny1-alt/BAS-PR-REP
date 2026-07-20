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
    devices: list[EmulatedDevice]


class PointWriteRequest(BaseModel):
    """Point write payload for the REST API."""

    value: bool | float | int | str


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
        self.weather = {
            "outdoor_air_temp": 91.0,
            "outdoor_air_humidity": 58.0,
            "wind_mph": 7.5,
            "cloud_cover_pct": 24.0,
            "conditions": "sunny",
        }

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
            devices=devices,
        )

    def step(self, steps: int = 1) -> EmulationSnapshot:
        for _ in range(max(steps, 0)):
            self.tick += 1
            self._step_weather()
            for device in self.controllers:
                for point in device.points:
                    if point.writable:
                        continue
                    point.present_value = self._next_value(point)
        return self.snapshot()

    def _step_weather(self) -> None:
        diurnal = math.sin(self.tick / 18.0)
        humidity_wave = math.sin((self.tick + 5) / 23.0)
        wind_wave = math.sin((self.tick + 9) / 11.0)
        cloud_wave = math.sin((self.tick + 17) / 14.0)
        outdoor_air_temp = round(88.0 + (diurnal * 9.0), 1)
        outdoor_air_humidity = round(54.0 + (humidity_wave * 11.0), 1)
        wind_mph = round(max(1.5, 6.5 + (wind_wave * 4.5)), 1)
        cloud_cover_pct = round(max(0.0, min(100.0, 35.0 + (cloud_wave * 38.0))), 1)
        if cloud_cover_pct > 72:
            conditions = "overcast"
        elif outdoor_air_humidity > 66 and cloud_cover_pct > 48:
            conditions = "humid"
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

    def _next_value(self, point: EmulatedPoint) -> bool | float | int | str:
        equipment_points = self._equipment_points(point.equipment_id)
        point_name = _normalize_token(point.point_name)
        baseline_numeric = float(point.baseline_value) if isinstance(point.baseline_value, (int, float)) else 0.0
        fan_enabled = self._point_value(equipment_points, ("SF-CMD", "SUPPLY FAN CMD"), default=False) or (
            self._point_value(equipment_points, ("SF-VFD-SPD", "SUPPLY FAN SPD"), default=0.0) > 5
        )
        cooling_cmd = float(self._point_value(equipment_points, ("CHW-VLV-CMD", "CC_V", "COOL"), default=0.0))
        heating_cmd = float(self._point_value(equipment_points, ("HW-VLV-CMD", "HC_V", "HEAT"), default=0.0))
        oa_cmd = float(self._point_value(equipment_points, ("OA-DMP-CMD", "OAD_P", "OUTSIDE AIR DAMPER"), default=18.0))
        dat_sp = float(self._point_value(equipment_points, ("DAT-SP", "SAT-SP", "SUPPLY TEMP SP"), default=55.0))
        zone_sp = float(self._point_value(equipment_points, ("ZN-T-SP", "ZONE TEMP SP"), default=72.0))
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

        if isinstance(point.baseline_value, bool):
            if "SFSTS" in point_name or "SFSTATUS" in point_name or "FANSTATUS" in point_name:
                return bool(fan_enabled)
            if "ALM" in point_name or point.kind == "alarm":
                alarm_trip = cooling_cmd > 92 and outdoor_air_humidity > 66 and fan_enabled
                return bool(alarm_trip or ((self.tick + point.object_instance) % 37 == 0))
            if "DMPR" in point_name and ("STS" in point_name or "PROOF" in point_name):
                return oa_cmd > 5
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
            if "ZONETEMP" in point_name or "ZNT" in point_name or "SPACETEMP" in point_name:
                zone_load = math.sin((self.tick + (point.object_instance % 13)) / 8.0) * 1.6
                return round(zone_sp + zone_load, 2)
            if "CFM" in point_name or "AIRFLOW" in point_name or "FLOW" in point_name:
                return round((self._point_value(equipment_points, ("DMPR_P", "DMPR-CMD"), default=48.0) / 100.0) * 1850.0, 0)
            if "RHV" in point_name or "REHEAT" in point_name:
                return round(max(0.0, min(100.0, heating_cmd)), 1)
            if "OAD" in point_name or "OADMP" in point_name:
                return round(max(5.0, min(100.0, oa_cmd)), 1)
            if "SPD" in point_name or "VFD" in point_name:
                return round(self._point_value(equipment_points, ("SF-VFD-SPD",), default=45.0), 1)
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
