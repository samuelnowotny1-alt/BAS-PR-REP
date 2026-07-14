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
