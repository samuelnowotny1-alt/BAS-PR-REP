"""Logic generator - generates logic diagrams from equipment and sequences."""

from pathlib import Path
from typing import Optional
import json

from ..models import (
    Project, Equipment, Point, PointKind, EquipmentType,
    LogicDiagram, LogicBlock, LogicSignal, LogicParameter, LogicConnection,
)


class LogicGenerator:
    """Generates structured logic diagrams from project data."""

    def __init__(self, project: Project):
        self.project = project
        self.diagrams: dict[str, LogicDiagram] = {}

    def generate_all(self) -> dict[str, LogicDiagram]:
        """Generate logic for all equipment with sequences."""
        for equip in self.project.equipment:
            if equip.sequence_ref or equip.type in self._supported_types():
                self._generate_equipment_logic(equip)
        return self.diagrams

    def _supported_types(self) -> set[EquipmentType]:
        return {
            EquipmentType.AHU, EquipmentType.RTU, EquipmentType.VAV,
            EquipmentType.CHILLER, EquipmentType.BOILER, EquipmentType.COOLING_TOWER,
            EquipmentType.PUMP_HW, EquipmentType.PUMP_CHW, EquipmentType.PUMP_CW,
        }

    def _generate_equipment_logic(self, equip: Equipment) -> LogicDiagram:
        points = self.project.get_points_for_equipment(equip.id)
        diagram = LogicDiagram(
            diagram_id=f"logic_{equip.id.lower()}",
            name=f"{equip.id} Control Logic",
            equipment_id=equip.id,
            description=f"Control logic for {equip.type.value} {equip.id}",
            metadata={"equipment_type": equip.type.value},
        )

        if equip.type == EquipmentType.AHU:
            self._generate_ahu_logic(diagram, equip, points)
        elif equip.type == EquipmentType.VAV:
            self._generate_vav_logic(diagram, equip, points)
        elif equip.type == EquipmentType.CHILLER:
            self._generate_chiller_logic(diagram, equip, points)
        elif equip.type == EquipmentType.BOILER:
            self._generate_boiler_logic(diagram, equip, points)
        elif equip.type in (EquipmentType.PUMP_HW, EquipmentType.PUMP_CHW, EquipmentType.PUMP_CW):
            self._generate_pump_logic(diagram, equip, points)
        elif equip.type == EquipmentType.RTU:
            self._generate_rtu_logic(diagram, equip, points)
        elif equip.type == EquipmentType.COOLING_TOWER:
            self._generate_cooling_tower_logic(diagram, equip, points)
        else:
            self._generate_generic_logic(diagram, equip, points)

        self.diagrams[diagram.diagram_id] = diagram
        return diagram

    def _find_point(self, points: list[Point], name_fragment: str) -> Optional[str]:
        """Find a point by name fragment."""
        for p in points:
            if name_fragment.lower() in p.name.lower():
                return p.name
        return None

    def _generate_ahu_logic(self, diagram: LogicDiagram, equip: Equipment, points: list[Point]) -> None:
        """Generate AHU control logic."""

        # 1. MODE SELECTION
        mode_block = LogicBlock(
            block_id="mode_select",
            block_type="mode",
            name="AHU Mode Selection",
            description="Determines operating mode: Off, Warmup, Cooldown, Occupied, Unoccupied",
            signals=[
                LogicSignal(name="occ_command", data_type="boolean", description="Occupancy command from schedule", is_input=True),
                LogicSignal(name="oa_temp", data_type="analog", description="Outside air temperature", units="degF", point_ref=self._find_point(points, "OAT"), is_input=True),
                LogicSignal(name="sat_sp", data_type="analog", description="Supply air temp setpoint", units="degF", is_output=True),
                LogicSignal(name="mode", data_type="enum", description="Current mode: off/warmup/cooldown/occupied/unoccupied", is_output=True),
                LogicSignal(name="enable_fan", data_type="boolean", description="Fan enable command", is_output=True),
            ],
            parameters=[
                LogicParameter(name="warmup_oa_threshold", value="40", data_type="analog", description="OA temp to enable warmup", units="degF", min_value=30, max_value=60),
                LogicParameter(name="cooldown_oa_threshold", value="75", data_type="analog", description="OA temp to enable cooldown", units="degF", min_value=60, max_value=85),
            ],
            position=(0.1, 0.1),
        )
        diagram.add_block(mode_block)

        # 2. SUPPLY FAN CONTROL
        fan_block = LogicBlock(
            block_id="fan_control",
            block_type="start_stop",
            name="Supply Fan Control",
            description="Start/stop supply fan with flow proof and safety interlocks",
            signals=[
                LogicSignal(name="fan_cmd", data_type="boolean", description="Fan start command from mode", is_input=True),
                LogicSignal(name="fan_status", data_type="boolean", description="Fan status (proof)", point_ref=self._find_point(points, "SF STATUS"), is_input=True),
                LogicSignal(name="fan_vfd_speed", data_type="analog", description="VFD speed command", units="%", is_output=True, point_ref=self._find_point(points, "SF CMD")),
                LogicSignal(name="fan_alarm", data_type="boolean", description="Fan fail alarm", is_output=True),
                LogicSignal(name="fan_runtime", data_type="analog", description="Fan runtime hours", units="hrs", is_output=True),
            ],
            parameters=[
                LogicParameter(name="proof_timeout", value="30", data_type="analog", description="Flow proof timeout", units="sec", min_value=10, max_value=120),
                LogicParameter(name="min_speed", value="20", data_type="analog", description="Minimum VFD speed", units="%", min_value=10, max_value=50),
                LogicParameter(name="max_speed", value="100", data_type="analog", description="Maximum VFD speed", units="%", min_value=80, max_value=100),
            ],
            position=(0.1, 0.3),
        )
        diagram.add_block(fan_block)
        diagram.add_connection(LogicConnection(from_block="mode_select", from_signal="enable_fan", to_block="fan_control", to_signal="fan_cmd"))

        # 3. SUPPLY AIR TEMP CONTROL (PID)
        sat_block = LogicBlock(
            block_id="sat_control",
            block_type="pid",
            name="Supply Air Temperature Control",
            description="PID control of SAT via cooling/heating valves",
            signals=[
                LogicSignal(name="sat", data_type="analog", description="Supply air temperature", units="degF", point_ref=self._find_point(points, "SAT"), is_input=True),
                LogicSignal(name="sat_sp", data_type="analog", description="SAT setpoint from mode logic", is_input=True),
                LogicSignal(name="clg_valve_cmd", data_type="analog", description="Cooling valve command", units="%", is_output=True, point_ref=self._find_point(points, "CLG VALVE")),
                LogicSignal(name="htg_valve_cmd", data_type="analog", description="Heating valve command", units="%", is_output=True, point_ref=self._find_point(points, "HTG VALVE")),
                LogicSignal(name="sat_error", data_type="analog", description="SAT error (SP - PV)", units="degF", is_output=True),
            ],
            parameters=[
                LogicParameter(name="kp", value="0.5", data_type="analog", description="Proportional gain", min_value=0.1, max_value=5.0),
                LogicParameter(name="ki", value="0.02", data_type="analog", description="Integral gain", units="1/sec", min_value=0.001, max_value=0.1),
                LogicParameter(name="kd", value="0", data_type="analog", description="Derivative gain", units="sec", min_value=0, max_value=10),
                LogicParameter(name="deadband", value="1.0", data_type="analog", description="Deadband", units="degF", min_value=0.5, max_value=5.0),
                LogicParameter(name="output_min", value="0", data_type="analog", description="Minimum output", units="%", min_value=0, max_value=20),
                LogicParameter(name="output_max", value="100", data_type="analog", description="Maximum output", units="%", min_value=80, max_value=100),
            ],
            position=(0.4, 0.1),
        )
        diagram.add_block(sat_block)
        diagram.add_connection(LogicConnection(from_block="mode_select", from_signal="sat_sp", to_block="sat_control", to_signal="sat_sp"))

        # 4. ECONOMIZER
        econ_block = LogicBlock(
            block_id="economizer",
            block_type="economizer",
            name="Airside Economizer",
            description="Free cooling using outside air when conditions permit",
            signals=[
                LogicSignal(name="oa_temp", data_type="analog", description="Outside air temp", units="degF", point_ref=self._find_point(points, "OAT"), is_input=True),
                LogicSignal(name="oa_hum", data_type="analog", description="Outside air humidity", units="%RH", point_ref=self._find_point(points, "OA HUM"), is_input=True),
                LogicSignal(name="ra_temp", data_type="analog", description="Return air temp", units="degF", point_ref=self._find_point(points, "RAT"), is_input=True),
                LogicSignal(name="ra_hum", data_type="analog", description="Return air humidity", units="%RH", point_ref=self._find_point(points, "RA HUM"), is_input=True),
                LogicSignal(name="econ_enable", data_type="boolean", description="Economizer enabled", is_output=True),
                LogicSignal(name="damper_cmd", data_type="analog", description="OA damper command", units="%", is_output=True, point_ref=self._find_point(points, "OA DAMPER")),
                LogicSignal(name="econ_savings", data_type="analog", description="Estimated economizer savings", units="ton-hr", is_output=True),
            ],
            parameters=[
                LogicParameter(name="high_limit_temp", value="70", data_type="analog", description="High temp lockout", units="degF", min_value=60, max_value=80),
                LogicParameter(name="high_limit_enthalpy", value="28", data_type="analog", description="High enthalpy lockout", units="BTU/lb", min_value=22, max_value=32),
                LogicParameter(name="diff_temp_enable", value="2", data_type="analog", description="Differential temp enable", units="degF", min_value=1, max_value=10),
                LogicParameter(name="diff_enthalpy_enable", value="2", data_type="analog", description="Differential enthalpy enable", units="BTU/lb", min_value=1, max_value=5),
            ],
            position=(0.4, 0.3),
        )
        diagram.add_block(econ_block)

        # 5. FREEZE PROTECTION
        freeze_block = LogicBlock(
            block_id="freeze_protection",
            block_type="freeze_protection",
            name="Freeze Protection",
            description="Protects coils from freezing",
            signals=[
                LogicSignal(name="sat", data_type="analog", description="Supply air temp", units="degF", is_input=True),
                LogicSignal(name="mat", data_type="analog", description="Mixed air temp", units="degF", point_ref=self._find_point(points, "MAT"), is_input=True),
                LogicSignal(name="freeze_stat", data_type="boolean", description="Freeze stat status", point_ref=self._find_point(points, "FREEZE STAT"), is_input=True),
                LogicSignal(name="htg_valve_override", data_type="analog", description="Heating valve override open", units="%", is_output=True),
                LogicSignal(name="fan_stop", data_type="boolean", description="Stop fan on freeze", is_output=True),
                LogicSignal(name="freeze_alarm", data_type="boolean", description="Freeze alarm", is_output=True),
            ],
            parameters=[
                LogicParameter(name="sat_trip", value="35", data_type="analog", description="SAT trip setpoint", units="degF", min_value=32, max_value=45),
                LogicParameter(name="mat_trip", value="38", data_type="analog", description="MAT trip setpoint", units="degF", min_value=35, max_value=50),
                LogicParameter(name="override_position", value="100", data_type="analog", description="Valve override position", units="%", min_value=50, max_value=100),
            ],
            position=(0.7, 0.1),
        )
        diagram.add_block(freeze_block)

        # 6. HIGH/LOW STATIC PROTECTION
        static_block = LogicBlock(
            block_id="static_protection",
            block_type="high_limit",
            name="Static Pressure Protection",
            description="Protects ductwork from over/under pressurization",
            signals=[
                LogicSignal(name="duct_sp", data_type="analog", description="Duct static pressure", units="inWC", point_ref=self._find_point(points, "DUCT SP"), is_input=True),
                LogicSignal(name="fan_speed_limit", data_type="analog", description="Fan speed limit", units="%", is_output=True),
                LogicSignal(name="high_static_alarm", data_type="boolean", description="High static alarm", is_output=True),
                LogicSignal(name="low_static_alarm", data_type="boolean", description="Low static alarm", is_output=True),
            ],
            parameters=[
                LogicParameter(name="high_limit", value="4.0", data_type="analog", description="High static limit", units="inWC", min_value=2.0, max_value=6.0),
                LogicParameter(name="low_limit", value="0.2", data_type="analog", description="Low static limit", units="inWC", min_value=0.05, max_value=1.0),
                LogicParameter(name="high_limit_action", value="ramp_down", data_type="enum", description="Action on high limit: ramp_down/shutdown"),
                LogicParameter(name="low_limit_action", value="alarm_only", data_type="enum", description="Action on low limit: alarm_only/ramp_up"),
            ],
            position=(0.7, 0.3),
        )
        diagram.add_block(static_block)

        # 7. SMOKE/FIRE INTERLOCKS
        smoke_block = LogicBlock(
            block_id="smoke_interlock",
            block_type="interlock",
            name="Smoke/Fire Interlocks",
            description="Shutdown on smoke detector or fire alarm",
            signals=[
                LogicSignal(name="duct_smoke", data_type="boolean", description="Duct smoke detector", point_ref=self._find_point(points, "DUCT SMOKE"), is_input=True),
                LogicSignal(name="area_smoke", data_type="boolean", description="Area smoke detector", point_ref=self._find_point(points, "AREA SMOKE"), is_input=True),
                LogicSignal(name="fire_alarm", data_type="boolean", description="Fire alarm system", point_ref=self._find_point(points, "FIRE ALARM"), is_input=True),
                LogicSignal(name="shutdown", data_type="boolean", description="Shutdown command", is_output=True),
                LogicSignal(name="smoke_alarm", data_type="boolean", description="Smoke alarm", is_output=True),
            ],
            parameters=[
                LogicParameter(name="shutdown_delay", value="0", data_type="analog", description="Shutdown delay", units="sec", min_value=0, max_value=30),
            ],
            position=(0.7, 0.5),
        )
        diagram.add_block(smoke_block)

        # 8. STANDARD ALARMS
        self._add_standard_alarms(diagram, equip, points)

    def _generate_vav_logic(self, diagram: LogicDiagram, equip: Equipment, points: list[Point]) -> None:
        """Generate VAV box control logic."""

        # VAV Flow Control (PID)
        flow_block = LogicBlock(
            block_id="flow_control",
            block_type="pid",
            name="VAV Flow Control",
            description="PID control of damper for airflow setpoint",
            signals=[
                LogicSignal(name="flow", data_type="analog", description="Measured airflow", units="CFM", point_ref=self._find_point(points, "FLOW"), is_input=True),
                LogicSignal(name="flow_sp", data_type="analog", description="Airflow setpoint", units="CFM", is_input=True),
                LogicSignal(name="damper_cmd", data_type="analog", description="Damper command", units="%", is_output=True, point_ref=self._find_point(points, "DAMPER CMD")),
            ],
            parameters=[
                LogicParameter(name="kp", value="1.0", data_type="analog", description="Proportional gain", min_value=0.1, max_value=10),
                LogicParameter(name="ki", value="0.1", data_type="analog", description="Integral gain", units="1/sec", min_value=0.01, max_value=1),
                LogicParameter(name="deadband", value="25", data_type="analog", description="Flow deadband", units="CFM", min_value=10, max_value=100),
            ],
            position=(0.4, 0.1),
        )
        diagram.add_block(flow_block)

        # Temperature Control (reheat)
        temp_block = LogicBlock(
            block_id="temp_control",
            block_type="pid",
            name="Zone Temperature Control",
            description="PID control of reheat valve for zone temperature",
            signals=[
                LogicSignal(name="zone_temp", data_type="analog", description="Zone temperature", units="degF", point_ref=self._find_point(points, "ZT"), is_input=True),
                LogicSignal(name="zone_temp_sp", data_type="analog", description="Zone temp setpoint", units="degF", is_input=True),
                LogicSignal(name="reheat_valve", data_type="analog", description="Reheat valve command", units="%", is_output=True, point_ref=self._find_point(points, "REHEAT VALVE")),
            ],
            parameters=[
                LogicParameter(name="kp", value="2.0", data_type="analog", description="Proportional gain", min_value=0.5, max_value=10),
                LogicParameter(name="ki", value="0.05", data_type="analog", description="Integral gain", units="1/sec", min_value=0.01, max_value=0.5),
                LogicParameter(name="deadband", value="0.5", data_type="analog", description="Temp deadband", units="degF", min_value=0.25, max_value=2),
            ],
            position=(0.4, 0.3),
        )
        diagram.add_block(temp_block)

        self._add_standard_alarms(diagram, equip, points)

    def _generate_chiller_logic(self, diagram: LogicDiagram, equip: Equipment, points: list[Point]) -> None:
        """Generate chiller plant logic."""
        blocks = [
            ("chiller_mode", "mode", "Chiller Mode Selection"),
            ("chiller_staging", "staging", "Chiller Staging"),
            ("chw_temp_control", "pid", "CHW Supply Temp Control"),
            ("cond_control", "pid", "Condenser Water Temp Control"),
            ("chiller_safeties", "interlock", "Chiller Safeties"),
        ]
        for bid, btype, name in blocks:
            diagram.add_block(LogicBlock(block_id=bid, block_type=btype, name=name, position=(0.1 + len(diagram.blocks)*0.2, 0.1)))

        self._add_standard_alarms(diagram, equip, points)

    def _generate_boiler_logic(self, diagram: LogicDiagram, equip: Equipment, points: list[Point]) -> None:
        """Generate boiler plant logic."""
        blocks = [
            ("boiler_mode", "mode", "Boiler Mode Selection"),
            ("boiler_staging", "staging", "Boiler Staging"),
            ("hws_temp_control", "pid", "HWS Temp Control"),
            ("boiler_safeties", "interlock", "Boiler Safeties"),
        ]
        for bid, btype, name in blocks:
            diagram.add_block(LogicBlock(block_id=bid, block_type=btype, name=name, position=(0.1 + len(diagram.blocks)*0.2, 0.1)))

        self._add_standard_alarms(diagram, equip, points)

    def _generate_pump_logic(self, diagram: LogicDiagram, equip: Equipment, points: list[Point]) -> None:
        """Generate pump logic (HW/CHW/CW)."""
        blocks = [
            ("pump_mode", "mode", "Pump Mode Selection"),
            ("pump_lead_lag", "lead_lag", "Lead/Lag Control"),
            ("vfd_control", "pid", "VFD Pressure/Flow Control"),
            ("pump_safeties", "interlock", "Pump Safeties"),
        ]
        for bid, btype, name in blocks:
            diagram.add_block(LogicBlock(block_id=bid, block_type=btype, name=name, position=(0.1 + len(diagram.blocks)*0.2, 0.1)))

        self._add_standard_alarms(diagram, equip, points)

    def _generate_rtu_logic(self, diagram: LogicDiagram, equip: Equipment, points: list[Point]) -> None:
        """Generate RTU logic (similar to AHU but packaged)."""
        self._generate_ahu_logic(diagram, equip, points)

    def _generate_cooling_tower_logic(self, diagram: LogicDiagram, equip: Equipment, points: list[Point]) -> None:
        """Generate cooling tower logic."""
        blocks = [
            ("ct_mode", "mode", "Cooling Tower Mode"),
            ("fan_staging", "staging", "Fan Staging"),
            ("cw_temp_control", "pid", "CW Temp Control"),
            ("ct_safeties", "interlock", "Cooling Tower Safeties"),
        ]
        for bid, btype, name in blocks:
            diagram.add_block(LogicBlock(block_id=bid, block_type=btype, name=name, position=(0.1 + len(diagram.blocks)*0.2, 0.1)))

        self._add_standard_alarms(diagram, equip, points)

    def _generate_generic_logic(self, diagram: LogicDiagram, equip: Equipment, points: list[Point]) -> None:
        """Generate generic logic for unknown equipment types."""
        block = LogicBlock(
            block_id="generic_control",
            block_type="custom",
            name=f"{equip.type.value} Control",
            description=f"Generic control logic for {equip.id}",
            position=(0.5, 0.5),
        )
        diagram.add_block(block)
        self._add_standard_alarms(diagram, equip, points)

    def _add_standard_alarms(self, diagram: LogicDiagram, equip: Equipment, points: list[Point]) -> None:
        """Add standard alarm blocks for all sensor/actuator points."""
        for point in points:
            if point.kind in (PointKind.SENSOR, PointKind.ACTUATOR):
                alarm_block = LogicBlock(
                    block_id=f"alarm_{point.name.lower().replace(' ', '_').replace('-', '_')}",
                    block_type="alarm",
                    name=f"Alarm: {point.name}",
                    description=f"High/low limit alarm for {point.name}",
                    signals=[
                        LogicSignal(name=point.name, data_type="analog", description=f"Value for {point.name}", units=point.units, point_ref=point.name, is_input=True),
                        LogicSignal(name=f"{point.name}_high_alm", data_type="boolean", description="High limit alarm", is_output=True),
                        LogicSignal(name=f"{point.name}_low_alm", data_type="boolean", description="Low limit alarm", is_output=True),
                    ],
                    parameters=[
                        LogicParameter(name="high_limit", value=str(point.range_max or 100), data_type="analog", description="High alarm limit", units=point.units or ""),
                        LogicParameter(name="low_limit", value=str(point.range_min or 0), data_type="analog", description="Low alarm limit", units=point.units or ""),
                        LogicParameter(name="deadband", value="1", data_type="analog", description="Alarm deadband", units=point.units or ""),
                        LogicParameter(name="delay", value="30", data_type="analog", description="Alarm delay", units="sec", min_value=0, max_value=300),
                    ],
                    position=(0.9, 0.1 + len(diagram.blocks) * 0.02),
                )
                diagram.add_block(alarm_block)

    def to_json(self, output_dir: Path) -> list[Path]:
        """Export logic diagrams as JSON files."""
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = []

        for diagram in self.diagrams.values():
            path = output_dir / f"{diagram.diagram_id}.json"
            with open(path, "w") as f:
                json.dump(self._diagram_to_dict(diagram), f, indent=2, default=str)
            paths.append(path)

        # Combined file
        combined_path = output_dir / "all_logic_diagrams.json"
        with open(combined_path, "w") as f:
            json.dump([self._diagram_to_dict(d) for d in self.diagrams.values()], f, indent=2, default=str)
        paths.append(combined_path)

        return paths

    def to_niagara_sequences(self, output_dir: Path) -> list[Path]:
        """Export as Niagara sequence modules (simplified)."""
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = []

        for diagram in self.diagrams.values():
            path = output_dir / f"{diagram.diagram_id}_niagara.json"
            niagara_format = self._diagram_to_niagara(diagram)
            with open(path, "w") as f:
                json.dump(niagara_format, f, indent=2)
            paths.append(path)

        return paths

    def _diagram_to_dict(self, diagram: LogicDiagram) -> dict:
        return {
            "diagram_id": diagram.diagram_id,
            "name": diagram.name,
            "equipment_id": diagram.equipment_id,
            "description": diagram.description,
            "version": diagram.version,
            "created_at": diagram.created_at.isoformat() if hasattr(diagram.created_at, 'isoformat') else str(diagram.created_at),
            "created_by": diagram.created_by,
            "blocks": [
                {
                    "block_id": b.block_id,
                    "type": b.block_type,
                    "name": b.name,
                    "description": b.description,
                    "signals": [
                        {
                            "name": s.name,
                            "type": s.data_type,
                            "description": s.description,
                            "units": s.units,
                            "default": s.default_value,
                            "min": s.min_value,
                            "max": s.max_value,
                            "point_ref": s.point_ref,
                            "is_input": s.is_input,
                            "is_output": s.is_output,
                            "is_parameter": s.is_parameter,
                        }
                        for s in b.signals
                    ],
                    "parameters": [
                        {
                            "name": p.name,
                            "value": p.value,
                            "type": p.data_type,
                            "description": p.description,
                            "units": p.units,
                            "min": p.min_value,
                            "max": p.max_value,
                            "tunable": p.tunable,
                        }
                        for p in b.parameters
                    ],
                    "position": b.position,
                    "enabled": b.enabled,
                    "metadata": b.metadata,
                }
                for b in diagram.blocks
            ],
            "connections": [
                {
                    "from_block": c.from_block,
                    "from_signal": c.from_signal,
                    "to_block": c.to_block,
                    "to_signal": c.to_signal,
                }
                for c in diagram.connections
            ],
            "metadata": diagram.metadata,
        }

    def _diagram_to_niagara(self, diagram: LogicDiagram) -> dict:
        return {
            "name": diagram.name,
            "type": "sequence",
            "equipment": diagram.equipment_id,
            "blocks": [
                {
                    "id": b.block_id,
                    "type": b.block_type,
                    "name": b.name,
                    "inputs": [s.name for s in b.signals if s.is_input],
                    "outputs": [s.name for s in b.signals if s.is_output],
                    "parameters": {p.name: p.value for p in b.parameters},
                }
                for b in diagram.blocks
            ],
            "wires": [
                {"from": f"{c.from_block}.{c.from_signal}", "to": f"{c.to_block}.{c.to_signal}"}
                for c in diagram.connections
            ],
        }


def generate_logic(project: Project, output_dir: Path) -> dict:
    """Convenience function to generate all logic outputs."""
    generator = LogicGenerator(project)
    generator.generate_all()

    return {
        "json": generator.to_json(output_dir / "logic_json"),
        "niagara": generator.to_niagara_sequences(output_dir / "logic_niagara"),
    }


__all__ = ["LogicGenerator", "generate_logic"]