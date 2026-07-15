from pathlib import Path

import pandas as pd

from bas_assistant.importers import CSVImporter
from bas_assistant.models import (
    Controller,
    ControllerIOCapacity,
    ControllerNetworkAddress,
    Equipment,
    EquipmentType,
    MappingReviewDecision,
    Point,
    PointDirection,
    PointKind,
    PointSource,
    Project,
    ProjectMetadata,
    Protocol,
    SourceDocument,
)
from bas_assistant.validation import ValidationEngine


def build_project(project_id: str = "validation-project") -> Project:
    return Project(
        metadata=ProjectMetadata(
            project_id=project_id,
            name="Validation Project",
        )
    )


def find_result(report, rule_id: str, object_id: str):
    return next(result for result in report.results if result.rule_id == rule_id and result.object_id == object_id)


def test_validation_uses_effective_mappings_for_equipment_and_points() -> None:
    project = build_project("mapped-project")
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id=None,
        )
    )
    project.points.append(
        Point(
            name="AHU-1 SAT",
            equipment_id="AHU-1",
            controller_id=None,
            kind=PointKind.SENSOR,
            direction=PointDirection.INPUT,
            units="degF",
        )
    )
    project.review_state.mapping_decisions.append(
        MappingReviewDecision(
            mapping_key="equipment-controller:AHU-1",
            mapped_to="MPC-1",
        )
    )

    report = ValidationEngine().validate(project)

    assert find_result(report, "COMP-001", "AHU-1").passed is True
    assert find_result(report, "COMP-003", "AHU-1 SAT").passed is True
    assert find_result(report, "CONS-001", "AHU-1 SAT").passed is True


def test_validation_flags_points_that_do_not_resolve_to_existing_controller() -> None:
    project = build_project("missing-controller-project")
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-404",
        )
    )
    project.points.append(
        Point(
            name="AHU-1 SAT",
            equipment_id="AHU-1",
            controller_id=None,
            kind=PointKind.SENSOR,
            direction=PointDirection.INPUT,
            units="degF",
        )
    )

    report = ValidationEngine().validate(project)

    point_controller = find_result(report, "COMP-003", "AHU-1 SAT")
    point_consistency = find_result(report, "CONS-001", "AHU-1 SAT")
    equipment_controller = find_result(report, "COMP-001", "AHU-1")

    assert point_controller.passed is False
    assert point_consistency.passed is False
    assert equipment_controller.passed is False
    assert "does not resolve to an existing controller" in point_controller.message


def test_pressure_validation_does_not_treat_setpoint_suffix_as_pressure() -> None:
    project = build_project("pressure-heuristics-project")
    project.controllers.append(Controller(id="MPC-1", type="MPC"))
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
        )
    )
    project.points.extend(
        [
            Point(
                name="AHU-1 DAT-SP",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.SETPOINT,
                direction=PointDirection.OUTPUT,
                units="degF",
            ),
            Point(
                name="AHU-1 STATIC-PRESS",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.SENSOR,
                direction=PointDirection.INPUT,
                units="degF",
            ),
        ]
    )

    report = ValidationEngine().validate(project)

    assert find_result(report, "ENG-003", "AHU-1 DAT-SP").passed is True
    assert find_result(report, "ENG-003", "AHU-1 STATIC-PRESS").passed is False


def test_protocol_completeness_rules_require_paired_bacnet_and_modbus_fields() -> None:
    project = build_project("protocol-completeness-project")
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP, Protocol.MODBUS_TCP],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
        )
    )
    project.points.extend(
        [
            Point(
                name="AHU-1 SAT",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.SENSOR,
                direction=PointDirection.INPUT,
                units="degF",
                bacnet_object_type="AI",
            ),
            Point(
                name="AHU-1 SF-CMD",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.ACTUATOR,
                direction=PointDirection.OUTPUT,
                modbus_register=40001,
            ),
        ]
    )

    report = ValidationEngine().validate(project)

    assert find_result(report, "PROTO-004", "AHU-1 SAT").passed is False
    assert find_result(report, "PROTO-005", "AHU-1 SF-CMD").passed is False


def test_controller_network_and_capacity_rules_flag_actionable_issues() -> None:
    project = build_project("controller-health-project")
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[
                ControllerNetworkAddress(
                    protocol=Protocol.MODBUS_TCP,
                    address="10.1.2.3",
                )
            ],
            io_capacity=ControllerIOCapacity(
                universal_inputs=4,
                digital_inputs=4,
                analog_outputs=2,
                digital_outputs=2,
                total_points=8,
            ),
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
        )
    )
    for suffix in ("SAT", "DAT", "MAT", "RAT", "SF-STS", "SF-CMD", "CHW-VLV-CMD", "OAT", "SPARE-1"):
        project.points.append(
            Point(
                name=f"AHU-1 {suffix}",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.SENSOR if "STS" not in suffix and "CMD" not in suffix else PointKind.STATUS,
                direction=PointDirection.INPUT,
                units="degF",
            )
        )

    report = ValidationEngine().validate(project)

    assert find_result(report, "PROTO-006", "MPC-1").passed is False
    assert find_result(report, "CAP-001", "MPC-1").passed is False
    assert find_result(report, "CAP-002", "MPC-1").passed is False


def test_controller_requires_network_address_for_network_protocols() -> None:
    project = build_project("controller-network-project")
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
        )
    )

    report = ValidationEngine().validate(project)

    assert find_result(report, "COMP-006", "MPC-1").passed is False


def test_sequence_references_missing_points_are_flagged(tmp_path: Path) -> None:
    project = build_project("sequence-coverage-project")
    sequence_path = tmp_path / "ahu_sequence.txt"
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status. AHU-1 SAT shall maintain 55F. AHU-1 LOW-SAT-ALM shall alarm.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
            owned_point_names=["AHU-1 SF-CMD"],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 sequence.txt",
        )
    )
    project.points.append(
        Point(
            name="AHU-1 SF-CMD",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=PointKind.ACTUATOR,
            direction=PointDirection.OUTPUT,
        )
    )

    report = ValidationEngine().validate(project)

    missing_refs = find_result(report, "COMP-007", "AHU-1")
    control_coverage = find_result(report, "CONS-006", "AHU-1")
    assert missing_refs.passed is False
    assert "SF-STS" in missing_refs.message
    assert "LOW-SAT-ALM" in missing_refs.message
    assert control_coverage.passed is False

    engine = ValidationEngine()
    engine.validate(project)
    coverage = engine.sequence_coverage_for_equipment(project, "AHU-1")

    assert coverage["status"] == "attention"
    assert coverage["documents"] == ["AHU-1 sequence.txt"]
    assert "AHU-1 SF-CMD" in coverage["matched_refs"]
    assert "AHU-1 SF-STS" in coverage["missing_refs"]
    assert any(check["label"] == "Status/proof point" and check["passed"] is False for check in coverage["coverage_checks"])


def test_sequence_aliases_match_structured_point_name_variants(tmp_path: Path) -> None:
    project = build_project("sequence-alias-project")
    sequence_path = tmp_path / "ahu_alias_sequence.txt"
    sequence_path.write_text(
        "AHU-1 SAT shall maintain 55F. AHU-1 SF-STS shall prove status. AHU-1 DAT-SP shall reset by OAT.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 alias sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 alias sequence.txt",
        )
    )
    project.points.extend(
        [
            Point(
                name="AHU-1 SUPPLY AIR TEMP",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.SENSOR,
                direction=PointDirection.INPUT,
                units="degF",
            ),
            Point(
                name="AHU-1 SUPPLY FAN STATUS",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.STATUS,
                direction=PointDirection.INPUT,
            ),
            Point(
                name="AHU-1 DISCHARGE AIR TEMP SETPOINT",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.SETPOINT,
                direction=PointDirection.OUTPUT,
                units="degF",
            ),
            Point(
                name="AHU-1 OAT",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.SENSOR,
                direction=PointDirection.INPUT,
                units="degF",
            ),
        ]
    )

    engine = ValidationEngine()
    engine.validate(project)
    coverage = engine.sequence_coverage_for_equipment(project, "AHU-1")

    assert "AHU-1 SAT" in coverage["matched_refs"]
    assert "AHU-1 SF-STS" in coverage["matched_refs"]
    assert "AHU-1 DAT-SP" in coverage["matched_refs"]
    assert "AHU-1 SAT" not in coverage["missing_refs"]
    assert "AHU-1 SF-STS" not in coverage["missing_refs"]


def test_point_ref_normalization_collapses_common_hvac_aliases() -> None:
    engine = ValidationEngine()

    assert engine._normalize_point_ref("AHU-1 Supply Air Temp") == "AHU-1 SAT"
    assert engine._normalize_point_ref("AHU-1 Supply Fan Status") == "AHU-1 SF-STS"
    assert engine._normalize_point_ref("AHU-1 Discharge Air Temp Setpoint") == "AHU-1 DAT-SP"
    assert engine._normalize_point_ref("AHU-1 Valve Position Command") == "AHU-1 VLV-CMD"
    assert engine._normalize_point_ref("AHU-1 Occupied Mode") == "AHU-1 OCC-MODE"
    assert engine._normalize_point_ref("VAV-101 Zone Temp") == "VAV-101 ZN-T"
    assert engine._normalize_point_ref("VAV-101 Room Temperature Setpoint") == "VAV-101 ZN-SP"
    assert engine._normalize_point_ref("VAV-101 Damper Position Feedback") == "VAV-101 DMP-POS"
    assert engine._normalize_point_ref("VAV-101 CFM SP") == "VAV-101 FLOW-SP"


def test_sequence_coverage_accepts_semantic_command_and_status_families(tmp_path: Path) -> None:
    project = build_project("sequence-semantic-family-project")
    sequence_path = tmp_path / "semantic_sequence.txt"
    sequence_path.write_text(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status. AHU-1 SAT shall maintain 55F. AHU-1 LOW-SAT-ALM shall alarm.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 semantic sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 semantic sequence.txt",
        )
    )
    project.points.extend(
        [
            Point(
                name="AHU-1 SUPPLY FAN ENABLE",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.ACTUATOR,
                direction=PointDirection.OUTPUT,
            ),
            Point(
                name="AHU-1 RUN PROOF",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.STATUS,
                direction=PointDirection.INPUT,
            ),
            Point(
                name="AHU-1 SUPPLY AIR TEMP",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.SENSOR,
                direction=PointDirection.INPUT,
                units="degF",
            ),
            Point(
                name="AHU-1 LOW-SAT-FAULT",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.STATUS,
                direction=PointDirection.INPUT,
            ),
            Point(
                name="AHU-1 SAT-SP",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.SETPOINT,
                direction=PointDirection.OUTPUT,
                units="degF",
            ),
        ]
    )

    engine = ValidationEngine()
    engine.validate(project)
    coverage = engine.sequence_coverage_for_equipment(project, "AHU-1")

    assert coverage["status"] == "covered"
    assert coverage["missing_refs"] == []
    assert all(check["passed"] for check in coverage["coverage_checks"] if check["required"])


def test_sequence_mode_and_schedule_intent_requires_matching_mode_points(tmp_path: Path) -> None:
    project = build_project("sequence-mode-project")
    sequence_path = tmp_path / "mode_sequence.txt"
    sequence_path.write_text(
        "During occupied hours, the supply fan runs continuously. During unoccupied hours, the unit is off.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="AHU-1 mode sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
            sequence_ref="AHU-1 mode sequence.txt",
        )
    )
    project.points.extend(
        [
            Point(
                name="AHU-1 OCCUPANCY MODE",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.STATUS,
                direction=PointDirection.INPUT,
            ),
            Point(
                name="AHU-1 TIME SCHEDULE",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.STATUS,
                direction=PointDirection.INPUT,
            ),
        ]
    )

    engine = ValidationEngine()
    engine.validate(project)
    coverage = engine.sequence_coverage_for_equipment(project, "AHU-1")

    assert "OCC-MODE" in coverage["matched_refs"]
    assert "SCH" in coverage["matched_refs"]
    assert any(check["label"] == "Mode/schedule point" and check["passed"] is True for check in coverage["coverage_checks"])


def test_vav_zone_airflow_and_damper_aliases_match_structured_variants(tmp_path: Path) -> None:
    project = build_project("vav-sequence-alias-project")
    sequence_path = tmp_path / "vav_sequence.txt"
    sequence_path.write_text(
        "VAV-101 zone temperature shall maintain setpoint. VAV-101 room temperature setpoint shall reset by schedule. VAV-101 damper position feedback shall prove command. VAV-101 CFM SP shall reset with occupancy.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="VAV-101 sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.controllers.append(
        Controller(
            id="VAV-1",
            type="MPC",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.20")],
        )
    )
    project.equipment.append(
        Equipment(
            id="VAV-101",
            type=EquipmentType.VAV,
            controller_id="VAV-1",
            sequence_ref="VAV-101 sequence.txt",
        )
    )
    project.points.extend(
        [
            Point(
                name="VAV-101 ZN-T",
                equipment_id="VAV-101",
                controller_id="VAV-1",
                kind=PointKind.SENSOR,
                direction=PointDirection.INPUT,
                units="degF",
            ),
            Point(
                name="VAV-101 ZN-SP",
                equipment_id="VAV-101",
                controller_id="VAV-1",
                kind=PointKind.SETPOINT,
                direction=PointDirection.OUTPUT,
                units="degF",
            ),
            Point(
                name="VAV-101 DMP-POS",
                equipment_id="VAV-101",
                controller_id="VAV-1",
                kind=PointKind.STATUS,
                direction=PointDirection.INPUT,
                units="pct",
            ),
            Point(
                name="VAV-101 FLOW-SP",
                equipment_id="VAV-101",
                controller_id="VAV-1",
                kind=PointKind.SETPOINT,
                direction=PointDirection.OUTPUT,
                units="cfm",
            ),
            Point(
                name="VAV-101 TIME SCHEDULE",
                equipment_id="VAV-101",
                controller_id="VAV-1",
                kind=PointKind.STATUS,
                direction=PointDirection.INPUT,
            ),
        ]
    )

    engine = ValidationEngine()
    engine.validate(project)
    coverage = engine.sequence_coverage_for_equipment(project, "VAV-101")

    assert "VAV-101 ZN-T" in coverage["matched_refs"]
    assert "VAV-101 ZN-SP" in coverage["matched_refs"]
    assert "VAV-101 DMP-POS" in coverage["matched_refs"]
    assert "VAV-101 FLOW-SP" in coverage["matched_refs"]


def test_reheat_economizer_and_staging_aliases_match_structured_variants(tmp_path: Path) -> None:
    project = build_project("plant-sequence-alias-project")
    sequence_path = tmp_path / "plant_sequence.txt"
    sequence_path.write_text(
        "AHU-1 economizer dampers shall modulate based on outside air temperature and mixed air temperature. "
        "VAV-101 reheat valve command shall modulate to maintain zone temperature setpoint. "
        "BLR-1 staging shall rotate lead lag weekly.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="plant sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.controllers.extend(
        [
            Controller(
                id="MPC-1",
                type="MPC",
                protocols=[Protocol.BACNET_IP],
                network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
            ),
            Controller(
                id="BLR-CTRL",
                type="MPC",
                protocols=[Protocol.BACNET_IP],
                network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.30")],
            ),
        ]
    )
    project.equipment.extend(
        [
            Equipment(
                id="AHU-1",
                type=EquipmentType.AHU,
                controller_id="MPC-1",
                sequence_ref="plant sequence.txt",
            ),
            Equipment(
                id="VAV-101",
                type=EquipmentType.VAV,
                controller_id="MPC-1",
                sequence_ref="plant sequence.txt",
            ),
            Equipment(
                id="BLR-1",
                type=EquipmentType.BOILER,
                controller_id="BLR-CTRL",
                sequence_ref="plant sequence.txt",
            ),
        ]
    )
    project.points.extend(
        [
            Point(
                name="AHU-1 DMP-CMD",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.ACTUATOR,
                direction=PointDirection.OUTPUT,
                units="pct",
            ),
            Point(
                name="AHU-1 OAT",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.SENSOR,
                direction=PointDirection.INPUT,
                units="degF",
            ),
            Point(
                name="AHU-1 MAT",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.SENSOR,
                direction=PointDirection.INPUT,
                units="degF",
            ),
            Point(
                name="VAV-101 HTG-CMD",
                equipment_id="VAV-101",
                controller_id="MPC-1",
                kind=PointKind.ACTUATOR,
                direction=PointDirection.OUTPUT,
                units="pct",
            ),
            Point(
                name="VAV-101 ZN-T",
                equipment_id="VAV-101",
                controller_id="MPC-1",
                kind=PointKind.SENSOR,
                direction=PointDirection.INPUT,
                units="degF",
            ),
            Point(
                name="VAV-101 ZN-SP",
                equipment_id="VAV-101",
                controller_id="MPC-1",
                kind=PointKind.SETPOINT,
                direction=PointDirection.OUTPUT,
                units="degF",
            ),
            Point(
                name="BLR-1 STAGE-CMD",
                equipment_id="BLR-1",
                controller_id="BLR-CTRL",
                kind=PointKind.ACTUATOR,
                direction=PointDirection.OUTPUT,
            ),
            Point(
                name="BLR-1 LEAD-LAG",
                equipment_id="BLR-1",
                controller_id="BLR-CTRL",
                kind=PointKind.STATUS,
                direction=PointDirection.INPUT,
            ),
        ]
    )

    engine = ValidationEngine()
    engine.validate(project)
    ahu_coverage = engine.sequence_coverage_for_equipment(project, "AHU-1")
    vav_coverage = engine.sequence_coverage_for_equipment(project, "VAV-101")
    boiler_coverage = engine.sequence_coverage_for_equipment(project, "BLR-1")

    assert "AHU-1 DMP-CMD" in ahu_coverage["matched_refs"]
    assert "VAV-101 HTG-CMD" in vav_coverage["matched_refs"]
    assert "BLR-1 STAGE-CMD" in boiler_coverage["matched_refs"]
    assert any(check["label"] == "Staging/rotation point" and check["passed"] is True for check in boiler_coverage["coverage_checks"])


def test_mixed_sequence_document_attributes_requirements_to_correct_equipment(tmp_path: Path) -> None:
    project = build_project("mixed-sequence-project")
    sequence_path = tmp_path / "mixed_sequence.txt"
    sequence_path.write_text(
        "AHU-1 supply fan command shall start on occupancy. "
        "VAV-101 zone temperature shall maintain setpoint. "
        "VAV-101 damper position shall prove airflow.",
        encoding="utf-8",
    )
    project.source_documents.append(
        SourceDocument(
            id="seq-1",
            name="mixed sequence.txt",
            type="sequence",
            path=str(sequence_path),
        )
    )
    project.controllers.extend(
        [
            Controller(
                id="MPC-1",
                type="MPC",
                protocols=[Protocol.BACNET_IP],
                network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.10")],
            ),
            Controller(
                id="VAV-1",
                type="MPC",
                protocols=[Protocol.BACNET_IP],
                network_addresses=[ControllerNetworkAddress(protocol=Protocol.BACNET_IP, address="192.168.10.20")],
            ),
        ]
    )
    project.equipment.extend(
        [
            Equipment(id="AHU-1", type=EquipmentType.AHU, controller_id="MPC-1", sequence_ref="mixed sequence.txt"),
            Equipment(id="VAV-101", type=EquipmentType.VAV, controller_id="VAV-1", sequence_ref="mixed sequence.txt"),
        ]
    )
    project.points.extend(
        [
            Point(
                name="AHU-1 SF-CMD",
                equipment_id="AHU-1",
                controller_id="MPC-1",
                kind=PointKind.ACTUATOR,
                direction=PointDirection.OUTPUT,
            ),
            Point(
                name="VAV-101 ZN-T",
                equipment_id="VAV-101",
                controller_id="VAV-1",
                kind=PointKind.SENSOR,
                direction=PointDirection.INPUT,
                units="degF",
            ),
            Point(
                name="VAV-101 ZN-SP",
                equipment_id="VAV-101",
                controller_id="VAV-1",
                kind=PointKind.SETPOINT,
                direction=PointDirection.OUTPUT,
                units="degF",
            ),
            Point(
                name="VAV-101 DMP-POS",
                equipment_id="VAV-101",
                controller_id="VAV-1",
                kind=PointKind.STATUS,
                direction=PointDirection.INPUT,
                units="pct",
            ),
            Point(
                name="VAV-101 AIRFLOW",
                equipment_id="VAV-101",
                controller_id="VAV-1",
                kind=PointKind.SENSOR,
                direction=PointDirection.INPUT,
                units="cfm",
            ),
        ]
    )

    engine = ValidationEngine()
    engine.validate(project)
    ahu_coverage = engine.sequence_coverage_for_equipment(project, "AHU-1")
    vav_coverage = engine.sequence_coverage_for_equipment(project, "VAV-101")

    assert "AHU-1 SF-CMD" in ahu_coverage["matched_refs"]
    assert "VAV-101 ZN-T" not in ahu_coverage["matched_refs"]
    assert "VAV-101 ZN-T" in vav_coverage["matched_refs"]
    assert "AHU-1 SF-CMD" not in vav_coverage["matched_refs"]
    assert "start_stop" in ahu_coverage["requirement_types"]
    assert "pid" in vav_coverage["requirement_types"]


def test_sequence_derived_points_require_source_reference() -> None:
    project = build_project("sequence-traceability-project")
    project.controllers.append(
        Controller(
            id="MPC-1",
            type="MPC",
        )
    )
    project.equipment.append(
        Equipment(
            id="AHU-1",
            type=EquipmentType.AHU,
            controller_id="MPC-1",
        )
    )
    project.points.append(
        Point(
            name="AHU-1 SAT-SP",
            equipment_id="AHU-1",
            controller_id="MPC-1",
            kind=PointKind.SETPOINT,
            direction=PointDirection.OUTPUT,
            source=PointSource.SEQUENCE,
        )
    )

    report = ValidationEngine().validate(project)

    assert find_result(report, "COMP-008", "AHU-1 SAT-SP").passed is False


def test_csv_importer_normalizes_sequence_reference_and_provenance(tmp_path: Path) -> None:
    project = build_project("import-normalization-project")
    equipment_csv = tmp_path / "equipment.csv"
    point_csv = tmp_path / "points.csv"
    pd.DataFrame(
        [
            {
                "Equipment ID": "AHU-1",
                "Equipment Type": "AHU",
                "Controller ID": "MPC-1",
                "Sequence Reference": "AHU-1 sequence.txt",
            }
        ]
    ).to_csv(equipment_csv, index=False)
    pd.DataFrame(
        [
            {
                "Point Name": "AHU-1 SAT",
                "Equipment ID": "AHU-1",
                "Point Kind": "sensor",
                "Direction": "input",
                "Source": "sequence",
            }
        ]
    ).to_csv(point_csv, index=False)

    importer = CSVImporter(project)
    importer.import_equipment_schedule(equipment_csv, "equip-doc")
    importer.import_point_list(point_csv, "point-doc")

    equipment = project.get_equipment("AHU-1")
    point = project.get_point("AHU-1 SAT")
    assert equipment is not None
    assert point is not None
    assert equipment.sequence_ref == "AHU-1 sequence.txt"
    assert equipment.provenance["source_doc_id"] == "equip-doc"
    assert point.provenance["source_doc_id"] == "point-doc"
    assert point.source_reference == "point-doc:row-1"
