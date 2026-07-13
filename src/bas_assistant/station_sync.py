"""Station sync planning and probing for Niagara stations."""

from __future__ import annotations

import ssl
from base64 import b64encode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import Project
from .models.station_sync import (
    StationConnectionConfig,
    StationProbeResult,
    StationSyncPlan,
    StationSyncPlanItem,
    StationSyncProtocol,
)


class StationSyncService:
    """Build sync plans and probe Niagara station endpoints."""

    def build_plan(self, project: Project, config: StationConnectionConfig | None) -> StationSyncPlan:
        active_config = config or StationConnectionConfig()
        items: list[StationSyncPlanItem] = []
        warnings: list[str] = []

        for controller in project.controllers:
            items.append(
                StationSyncPlanItem(
                    category="controller",
                    name=controller.id,
                    action="Upsert device container",
                    ord_path=f"station:|slot:/Drivers/BacnetNetwork/{controller.id}",
                    details=f"Prepare Niagara device slot for {controller.id}.",
                )
            )

        for equip in project.equipment:
            items.append(
                StationSyncPlanItem(
                    category="equipment",
                    name=equip.id,
                    action="Upsert equipment record",
                    ord_path=(
                        "station:|slot:/Config/Equipment/"
                        f"{equip.building or 'DefaultBuilding'}/{equip.floor or 'DefaultFloor'}/{equip.id}"
                    ),
                    details=f"Prepare equipment hierarchy and PX navigation for {equip.id}.",
                )
            )
            if not equip.controller_id:
                warnings.append(f"{equip.id} has no controller assignment; live sync cannot bind its points cleanly.")

        for point in project.points:
            controller_id = point.controller_id or "Unassigned"
            items.append(
                StationSyncPlanItem(
                    category="point",
                    name=point.name,
                    action="Upsert control point",
                    ord_path=f"station:|slot:/Drivers/BacnetNetwork/{controller_id}/Points/{point.name}",
                    details=f"Prepare Niagara point binding for {point.name}.",
                )
            )

        for equip in project.equipment:
            if project.get_points_for_equipment(equip.id):
                items.append(
                    StationSyncPlanItem(
                        category="px",
                        name=equip.id,
                        action="Publish PX page",
                        ord_path=f"station:|slot:/Px/Equipment/{equip.id}",
                        details=f"Prepare PX page export for {equip.id}.",
                    )
                )

        if active_config.protocol == StationSyncProtocol.FILE_EXPORT:
            warnings.append("File Export mode does not talk to the station directly; it prepares import artifacts only.")
        if active_config.protocol == StationSyncProtocol.OBIX_HTTP and not active_config.host:
            warnings.append("No station host configured; connection tests and live sync are unavailable.")

        summary = (
            f"{len(project.controllers)} controllers, {len(project.equipment)} equipment records, "
            f"{len(project.points)} points, {sum(1 for e in project.equipment if project.get_points_for_equipment(e.id))} PX pages."
        )
        return StationSyncPlan(
            target=active_config.target.value,
            protocol=active_config.protocol.value,
            summary=summary,
            items=items,
            warnings=warnings,
        )

    def probe(self, config: StationConnectionConfig, password: str | None = None) -> StationProbeResult:
        if config.protocol != StationSyncProtocol.OBIX_HTTP:
            return StationProbeResult(
                success=False,
                endpoint=config.obix_url(),
                message="Probe is only implemented for oBIX/HTTP mode.",
            )

        if not config.host:
            return StationProbeResult(
                success=False,
                endpoint=config.obix_url(),
                message="Station host is required before probing.",
            )

        endpoint = config.obix_url()
        request = Request(endpoint, method="GET")
        request.add_header("Accept", "application/xml,text/xml,*/*")
        if config.username and password:
            token = b64encode(f"{config.username}:{password}".encode("utf-8")).decode("ascii")
            request.add_header("Authorization", f"Basic {token}")

        context = None
        if not config.verify_tls:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        try:
            with urlopen(request, timeout=config.timeout_seconds, context=context) as response:
                status_code = getattr(response, "status", None)
                return StationProbeResult(
                    success=True,
                    endpoint=endpoint,
                    status_code=status_code,
                    message="Station endpoint responded.",
                )
        except HTTPError as exc:
            return StationProbeResult(
                success=False,
                endpoint=endpoint,
                status_code=exc.code,
                message=f"Station returned HTTP {exc.code}.",
            )
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            return StationProbeResult(
                success=False,
                endpoint=endpoint,
                message=f"Connection failed: {reason}",
            )


__all__ = ["StationSyncService"]
