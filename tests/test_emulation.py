import httpx
import pytest

from bas_assistant.emulation import BasEmulationLab, create_emulation_app
from bas_assistant.models import (
    Controller,
    ControllerNetworkAddress,
    Point,
    PointDirection,
    PointKind,
    Project,
    ProjectMetadata,
    Protocol,
)

HTTP_OK = 200
HTTP_BAD_REQUEST = 400
POINT_COUNT = 2
SAT_INSTANCE = 1001
STEP_COUNT = 2
OVERRIDE_VALUE = 55.0


def build_project() -> Project:
    project = Project(metadata=ProjectMetadata(project_id="EMU-1", name="Emulator Test"))
    project.add_controller(
        Controller(
            id="AHU-CTRL-1",
            name="AHU Controller 1",
            vendor="Tridium-ish",
            model="Bench-Controller",
            protocols=[Protocol.BACNET_IP],
            network_addresses=[
                ControllerNetworkAddress(
                    protocol=Protocol.BACNET_IP,
                    address="10.10.10.20",
                    network_number=2001,
                )
            ],
        )
    )
    project.add_point(
        Point(
            name="AHU-1_SAT",
            equipment_id="AHU-1",
            controller_id="AHU-CTRL-1",
            kind=PointKind.SENSOR,
            direction=PointDirection.INPUT,
            units="F",
            bacnet_object_type="AI",
            bacnet_instance=1001,
        )
    )
    project.add_point(
        Point(
            name="AHU-1_SAT-SP",
            equipment_id="AHU-1",
            controller_id="AHU-CTRL-1",
            kind=PointKind.SETPOINT,
            direction=PointDirection.BIDIRECTIONAL,
            units="F",
            bacnet_object_type="AV",
            bacnet_instance=1002,
        )
    )
    return project


def test_emulation_lab_builds_gateway_and_controller_manifest() -> None:
    lab = BasEmulationLab(build_project(), gateway_name="JACE-EMU")

    manifest = lab.manifest()

    assert manifest.project_id == "EMU-1"
    assert manifest.gateway.device_id == "JACE-EMU"
    assert len(manifest.controllers) == 1
    assert manifest.controllers[0].device_id == "AHU-CTRL-1"
    assert manifest.controllers[0].point_count == POINT_COUNT
    assert manifest.controllers[0].points[0].object_instance == SAT_INSTANCE


def test_emulation_step_changes_read_only_sensor_but_not_writable_setpoint() -> None:
    lab = BasEmulationLab(build_project())

    sat = lab.get_point("AHU-1_SAT")
    sat_sp = lab.get_point("AHU-1_SAT-SP")
    baseline_sensor = sat.present_value
    baseline_setpoint = sat_sp.present_value

    lab.step(steps=STEP_COUNT)

    assert lab.tick == STEP_COUNT
    assert lab.get_point("AHU-1_SAT").present_value != baseline_sensor
    assert lab.get_point("AHU-1_SAT-SP").present_value == baseline_setpoint


@pytest.mark.anyio
async def test_emulation_api_supports_snapshot_and_writable_point_override() -> None:
    transport = httpx.ASGITransport(app=create_emulation_app(build_project()))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        snapshot = await client.get("/snapshot")
        assert snapshot.status_code == HTTP_OK
        assert snapshot.json()["project_id"] == "EMU-1"

        write = await client.post("/points/AHU-1_SAT-SP", json={"value": OVERRIDE_VALUE})
        assert write.status_code == HTTP_OK
        assert write.json()["present_value"] == OVERRIDE_VALUE

        read_only_write = await client.post("/points/AHU-1_SAT", json={"value": 60.0})
        assert read_only_write.status_code == HTTP_BAD_REQUEST
