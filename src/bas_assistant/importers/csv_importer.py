"""Importers - normalize source files into structured models."""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from ..generators.graphics import GraphicsGenerator
from ..models import (
    Controller,
    Equipment,
    EquipmentType,
    Point,
    PointDirection,
    PointKind,
    PointSource,
    Project,
    ProjectMetadata,
    Protocol,
    SourceDocument,
)
from ..models.equipment import EquipmentTemplateRef


class ImportResult(BaseModel):
    """Result of an import operation."""

    success: bool
    message: str
    equipment_count: int = 0
    points_count: int = 0
    controllers_count: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CSVImporter:
    """Import project data from CSV files."""

    def __init__(self, project: Project):
        self.project = project

    def import_equipment_schedule(self, csv_path: Path, source_doc_id: str) -> ImportResult:
        """Import equipment from equipment schedule CSV."""
        errors = []
        warnings = []
        count = 0

        try:
            df = self._read_tabular_file(csv_path)
        except Exception as e:
            return ImportResult(
                success=False,
                message=f"Failed to read schedule: {e}",
                errors=[str(e)],
            )

        required_cols = {"Equipment ID", "Equipment Type"}
        if not required_cols.issubset(set(df.columns)):
            missing = required_cols - set(df.columns)
            return ImportResult(
                success=False,
                message=f"Missing required columns: {missing}",
                errors=[f"Missing columns: {missing}"],
            )

        for _, row in df.iterrows():
            try:
                equip_id = str(row.get("Equipment ID", "")).strip()
                equip_type_str = str(row.get("Equipment Type", "")).strip()

                if not equip_id or not equip_type_str:
                    warnings.append(f"Row {count+1}: Missing Equipment ID or Type")
                    continue

                try:
                    equip_type = EquipmentType(equip_type_str.upper())
                except ValueError:
                    equip_type = EquipmentType.CUSTOM
                    warnings.append(f"Equipment '{equip_id}': Unknown type '{equip_type_str}', using CUSTOM")

                equipment = Equipment(
                    id=equip_id,
                    type=equip_type,
                    subtype=str(row.get("Subtype", "")).strip() or None,
                    building=str(row.get("Building", "")).strip() or None,
                    floor=str(row.get("Floor", "")).strip() or None,
                    room=str(row.get("Room", "")).strip() or None,
                    served_area=str(row.get("Served Area", "")).strip() or None,
                    controller_id=str(row.get("Controller ID", "")).strip() or None,
                    design_cfm=self._parse_float(row.get("Design CFM")),
                    design_tonnage=self._parse_float(row.get("Design Tonnage")),
                    design_gpm=self._parse_float(row.get("Design GPM")),
                    design_kw=self._parse_float(row.get("Design kW")),
                    voltage=str(row.get("Voltage", "")).strip() or None,
                    phase=self._parse_int(row.get("Phase")),
                    status=str(row.get("Status", "design")).strip(),
                    notes=str(row.get("Notes", "")).strip() or None,
                    tags=[t.strip() for t in (self._parse_str(row.get("Tags")) or "").split(",") if t.strip()],
                )

                parent_id = str(row.get("Parent Equipment", "")).strip()
                if parent_id:
                    equipment.parent_equipment_id = parent_id

                children_str = str(row.get("Child Equipment", "")).strip()
                if children_str:
                    equipment.child_equipment_ids = [c.strip() for c in children_str.split(",")]

                points_str = str(row.get("Points", "")).strip()
                if points_str:
                    equipment.point_names = [p.strip() for p in points_str.split(",")]

                graphic_sections = self._parse_str(row.get("Graphic Sections"))
                if graphic_sections:
                    valid_sections, invalid_sections = GraphicsGenerator.parse_ahu_graphic_sections(graphic_sections)
                    if invalid_sections:
                        warnings.append(
                            f"Equipment '{equip_id}': ignored invalid graphic sections {', '.join(invalid_sections)}"
                        )
                    graphic_sections = ",".join(valid_sections)
                if graphic_sections:
                    equipment.template = EquipmentTemplateRef(
                        template_name="graphic_layout",
                        parameters={"graphic_sections": graphic_sections},
                    )

                self.project.add_equipment(equipment)
                count += 1

            except Exception as e:
                errors.append(f"Row {count+1} (equip {equip_id}): {e}")

        return ImportResult(
            success=len(errors) == 0,
            message=f"Imported {count} equipment items",
            equipment_count=count,
            errors=errors,
            warnings=warnings,
        )

    def import_point_list(self, csv_path: Path, source_doc_id: str) -> ImportResult:
        """Import points from point list CSV."""
        errors = []
        warnings = []
        count = 0

        try:
            df = self._read_tabular_file(csv_path)
        except Exception as e:
            return ImportResult(
                success=False,
                message=f"Failed to read point list: {e}",
                errors=[str(e)],
            )

        required_cols = {"Point Name", "Equipment ID", "Point Kind", "Direction"}
        if not required_cols.issubset(set(df.columns)):
            missing = required_cols - set(df.columns)
            return ImportResult(
                success=False,
                message=f"Missing required columns: {missing}",
                errors=[f"Missing columns: {missing}"],
            )

        for _, row in df.iterrows():
            try:
                point_name = self._parse_str(row.get("Point Name")) or ""
                equip_id = self._parse_str(row.get("Equipment ID")) or ""
                kind_str = (self._parse_str(row.get("Point Kind")) or "").lower()
                direction_str = (self._parse_str(row.get("Direction")) or "").lower()

                if not point_name or not equip_id:
                    warnings.append(f"Row {count+1}: Missing Point Name or Equipment ID")
                    continue

                if not self.project.get_equipment(equip_id):
                    errors.append(f"Point '{point_name}': Equipment '{equip_id}' not found")
                    continue

                kind_map = {
                    "sensor": PointKind.SENSOR,
                    "actuator": PointKind.ACTUATOR,
                    "setpoint": PointKind.SETPOINT,
                    "status": PointKind.STATUS,
                    "alarm": PointKind.ALARM,
                    "parameter": PointKind.PARAMETER,
                    "derived": PointKind.DERIVED,
                }
                kind = kind_map.get(kind_str, PointKind.SENSOR)

                dir_map = {
                    "input": PointDirection.INPUT,
                    "output": PointDirection.OUTPUT,
                    "in": PointDirection.INPUT,
                    "out": PointDirection.OUTPUT,
                    "ai": PointDirection.INPUT,
                    "ao": PointDirection.OUTPUT,
                    "bi": PointDirection.INPUT,
                    "bo": PointDirection.OUTPUT,
                }
                direction = dir_map.get(direction_str, PointDirection.INPUT)

                source_str = (self._parse_str(row.get("Source")) or "point_list").lower()
                source_map = {
                    "point_list": PointSource.POINT_LIST,
                    "bacnet": PointSource.BACNET,
                    "modbus": PointSource.MODBUS,
                    "drawing": PointSource.DRAWING,
                    "submittal": PointSource.SUBMITTAL,
                    "sequence": PointSource.SEQUENCE,
                    "manual": PointSource.MANUAL,
                }
                source = source_map.get(source_str, PointSource.POINT_LIST)

                point = Point(
                    name=point_name,
                    equipment_id=equip_id,
                    controller_id=self._parse_str(row.get("Controller ID")),
                    kind=kind,
                    direction=direction,
                    units=self._parse_str(row.get("Units")),
                    unit_system=self._parse_str(row.get("Unit System")),
                    range_min=self._parse_float(row.get("Range Min")),
                    range_max=self._parse_float(row.get("Range Max")),
                    bacnet_object_type=self._parse_str(row.get("BACnet Object Type")),
                    bacnet_instance=self._parse_int(row.get("BACnet Instance")),
                    modbus_register=self._parse_int(row.get("Modbus Register")),
                    modbus_type=self._parse_str(row.get("Modbus Type")),
                    source=source,
                    source_reference=self._parse_str(row.get("Source Reference")),
                    description=self._parse_str(row.get("Description")),
                    tags=[t.strip() for t in (self._parse_str(row.get("Tags")) or "").split(",") if t.strip()],
                )

                self.project.add_point(point)
                count += 1

            except Exception as e:
                errors.append(f"Row {count+1} (point {point_name}): {e}")

        return ImportResult(
            success=len(errors) == 0,
            message=f"Imported {count} points",
            points_count=count,
            errors=errors,
            warnings=warnings,
        )

    def import_controller_schedule(self, csv_path: Path, source_doc_id: str) -> ImportResult:
        """Import controllers from controller schedule CSV."""
        errors = []
        warnings = []
        count = 0

        try:
            df = self._read_tabular_file(csv_path)
        except Exception as e:
            return ImportResult(
                success=False,
                message=f"Failed to read controller schedule: {e}",
                errors=[str(e)],
            )

        required_cols = {"Controller ID"}
        if not required_cols.issubset(set(df.columns)):
            missing = required_cols - set(df.columns)
            return ImportResult(
                success=False,
                message=f"Missing required columns: {missing}",
                errors=[f"Missing columns: {missing}"],
            )

        source_doc = SourceDocument(
            id=source_doc_id,
            name=csv_path.name,
            type="controller_schedule",
            path=str(csv_path),
            imported_at=datetime.now(),
        )
        self.project.source_documents.append(source_doc)

        for _, row in df.iterrows():
            try:
                ctrl_id = str(row.get("Controller ID", "")).strip()
                if not ctrl_id:
                    warnings.append(f"Row {count+1}: Missing Controller ID")
                    continue

                protocols_str = str(row.get("Protocols", "")).strip()
                protocols = []
                if protocols_str:
                    for p in protocols_str.split(","):
                        p = p.strip()
                        try:
                            protocols.append(Protocol(p))
                        except ValueError:
                            warnings.append(f"Controller '{ctrl_id}': Unknown protocol '{p}'")

                controller = Controller(
                    id=ctrl_id,
                    name=str(row.get("Name", "")).strip() or None,
                    vendor=str(row.get("Vendor", "")).strip() or None,
                    model=str(row.get("Model", "")).strip() or None,
                    firmware_version=str(row.get("Firmware", "")).strip() or None,
                    type=str(row.get("Type", "generic")).strip(),
                    protocols=protocols,
                    panel_location=str(row.get("Panel Location", "")).strip() or None,
                    electrical_panel=str(row.get("Electrical Panel", "")).strip() or None,
                    circuit=str(row.get("Circuit", "")).strip() or None,
                    status=str(row.get("Status", "design")).strip(),
                    notes=str(row.get("Notes", "")).strip() or None,
                )

                ip = str(row.get("IP Address", "")).strip()
                if ip:
                    from ..models.controller import ControllerNetworkAddress
                    controller.network_addresses.append(ControllerNetworkAddress(
                        protocol=Protocol.BACNET_IP,
                        address=ip,
                        network_number=None,
                    ))

                mstp_mac = self._parse_str(
                    row.get("MS/TP MAC")
                    or row.get("MSTP MAC")
                    or row.get("MAC Address")
                )
                mstp_network = self._parse_int(row.get("Network Number"))
                if mstp_mac:
                    from ..models.controller import ControllerNetworkAddress
                    controller.network_addresses.append(ControllerNetworkAddress(
                        protocol=Protocol.BACNET_MSTP,
                        address=mstp_mac,
                        network_number=mstp_network,
                    ))

                equip_str = str(row.get("Serves Equipment", "")).strip()
                if equip_str:
                    controller.serves_equipment_ids = [e.strip() for e in equip_str.split(",")]

                points_str = str(row.get("Owned Points", "")).strip()
                if points_str:
                    controller.owned_point_names = [p.strip() for p in points_str.split(",")]

                ui = self._parse_int(row.get("Universal Inputs"))
                di = self._parse_int(row.get("Digital Inputs"))
                ao = self._parse_int(row.get("Analog Outputs"))
                do = self._parse_int(row.get("Digital Outputs"))
                total = self._parse_int(row.get("Total Points"))

                if any(v is not None for v in [ui, di, ao, do, total]):
                    from ..models.controller import ControllerIOCapacity
                    controller.io_capacity = ControllerIOCapacity(
                        universal_inputs=ui or 0,
                        digital_inputs=di or 0,
                        analog_outputs=ao or 0,
                        digital_outputs=do or 0,
                        total_points=total or (ui or 0) + (di or 0) + (ao or 0) + (do or 0),
                    )

                self.project.add_controller(controller)
                count += 1

            except Exception as e:
                errors.append(f"Row {count+1} (controller {ctrl_id}): {e}")

        return ImportResult(
            success=len(errors) == 0,
            message=f"Imported {count} controllers",
            controllers_count=count,
            errors=errors,
            warnings=warnings,
        )

    def _read_tabular_file(self, file_path: Path) -> pd.DataFrame:
        suffix = file_path.suffix.lower()
        if suffix == ".csv":
            return pd.read_csv(file_path)
        if suffix in {".xlsx", ".xls", ".xlsm"}:
            return pd.read_excel(file_path)
        raise ValueError(f"Unsupported tabular format: {suffix or 'unknown'}")

    def _parse_float(self, value) -> float | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _parse_int(self, value) -> int | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None

    def _parse_str(self, value) -> str | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        s = str(value).strip()
        return s if s else None


class JSONImporter:
    """Import project data from JSON files."""

    def __init__(self, project: Project):
        self.project = project

    def import_project(self, json_path: Path) -> ImportResult:
        """Import full project from JSON."""
        try:
            with open(json_path) as f:
                data = json.load(f)
        except Exception as e:
            return ImportResult(success=False, message=f"Failed to read JSON: {e}", errors=[str(e)])

        if "metadata" in data:
            self.project.metadata = ProjectMetadata(**data["metadata"])

        equip_count = 0
        for equip_data in data.get("equipment", []):
            try:
                equip = Equipment(**equip_data)
                self.project.add_equipment(equip)
                equip_count += 1
            except Exception as e:
                return ImportResult(success=False, message=f"Equipment import failed: {e}", errors=[str(e)])

        point_count = 0
        for point_data in data.get("points", []):
            try:
                point = Point(**point_data)
                self.project.add_point(point)
                point_count += 1
            except Exception as e:
                return ImportResult(success=False, message=f"Point import failed: {e}", errors=[str(e)])

        ctrl_count = 0
        for ctrl_data in data.get("controllers", []):
            try:
                ctrl = Controller(**ctrl_data)
                self.project.add_controller(ctrl)
                ctrl_count += 1
            except Exception as e:
                return ImportResult(success=False, message=f"Controller import failed: {e}", errors=[str(e)])

        return ImportResult(
            success=True,
            message="Imported project from JSON",
            equipment_count=equip_count,
            points_count=point_count,
            controllers_count=ctrl_count,
        )


def create_sample_csvs(output_dir: Path) -> None:
    """Create sample CSV templates for import."""
    output_dir.mkdir(parents=True, exist_ok=True)

    equip_template = pd.DataFrame([{
        "Equipment ID": "AHU-1",
        "Equipment Type": "AHU",
        "Subtype": "VAV",
        "Building": "Main",
        "Floor": "1",
        "Room": "Mechanical",
        "Served Area": "Floor 1",
        "Controller ID": "MPC-1",
        "Parent Equipment": "",
        "Child Equipment": "VAV-101,VAV-102",
        "Points": "AHU-1 SAT,AHU-1 MAT,AHU-1 RAT,AHU-1 SF CMD",
        "Design CFM": 10000,
        "Design Tonnage": 25,
        "Design GPM": 50,
        "Design kW": 15,
        "Voltage": "460",
        "Phase": 3,
        "Status": "design",
        "Graphic Sections": "outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge",
        "Notes": "Main AHU for floor 1",
        "Tags": "ahu,main",
    }])
    equip_template.to_csv(output_dir / "equipment_schedule.csv", index=False)

    point_template = pd.DataFrame([{
        "Point Name": "AHU-1 SAT",
        "Equipment ID": "AHU-1",
        "Point Kind": "sensor",
        "Direction": "input",
        "Units": "degF",
        "Unit System": "IP",
        "Range Min": 40,
        "Range Max": 120,
        "Controller ID": "MPC-1",
        "BACnet Object Type": "AI",
        "BACnet Instance": 1,
        "Modbus Register": "",
        "Modbus Type": "",
        "Source": "point_list",
        "Source Reference": "Row 1",
        "Description": "Supply Air Temperature",
        "Tags": "temperature,supply,ahu",
    }])
    point_template.to_csv(output_dir / "point_list.csv", index=False)

    ctrl_template = pd.DataFrame([{
        "Controller ID": "MPC-1",
        "Name": "Main Plant Controller 1",
        "Vendor": "Johnson Controls",
        "Model": "MPC-8000",
        "Firmware": "12.3",
        "Type": "MPC",
        "Protocols": "BACnet/IP,BACnet/MSTP",
        "IP Address": "192.168.1.10",
        "MS/TP MAC": "11",
        "Network Number": 2001,
        "Panel Location": "Mechanical Room",
        "Electrical Panel": "MP-1",
        "Circuit": "12",
        "Serves Equipment": "AHU-1,CHWP-1",
        "Owned Points": "AHU-1 SAT,AHU-1 MAT,AHU-1 RAT,AHU-1 SF CMD",
        "Universal Inputs": 16,
        "Digital Inputs": 8,
        "Analog Outputs": 4,
        "Digital Outputs": 8,
        "Total Points": 36,
        "Status": "design",
        "Notes": "Main plant controller",
    }])
    ctrl_template.to_csv(output_dir / "controller_schedule.csv", index=False)


__all__ = ["CSVImporter", "ImportResult", "JSONImporter", "create_sample_csvs"]
