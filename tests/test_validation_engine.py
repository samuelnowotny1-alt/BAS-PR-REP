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
    Project,
    ProjectMetadata,
    Protocol,
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
