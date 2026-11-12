"""What queues the agent's background work by itself: a lot just sown gets its tracking plan, and every zone analysis
(the photos of the guided walk) sends the lots of that zone to be re-planned with what it saw."""
import logging
from dataclasses import replace
from uuid import UUID

from src.shared.domain.actor import Actor

from .service import LongTaskService

logger = logging.getLogger(__name__)


class LongTaskHooks:
    def __init__(self, tasks: LongTaskService, tracking_service, farm_service, reports_service):
        self.tasks = tasks
        self.tracking = tracking_service
        self.farm = farm_service
        self.reports = reports_service

    async def lot_sown(self, actor: Actor, lot_id: UUID) -> None:
        lot = await self.farm.get_lot(actor, lot_id)
        await self.tasks.create(replace(actor, via="system"), "plan_lots",
                                f"Planificar el seguimiento: {lot.label or 'lote recién sembrado'}",
                                {"lot_ids": [str(lot_id)], "reason": "Lote recién sembrado"})

    async def zone_analyzed(self, actor: Actor, report_id: UUID) -> None:
        """Each lot of the analyzed zone that already has a plan is re-planned with the analysis as observation;
        lots without a plan get one."""
        report = await self.reports.get_report(actor, report_id)
        if report.status != "ANALYSIS_COMPLETED" or not report.zone_id:
            return
        lot_ids = list(report.lot_ids or [])
        if not lot_ids:
            return
        planned = {p.lot_id for p in await self.tracking.list_plans(actor, lot_ids)}
        observation = f"Análisis de zona del {report.created_at:%d/%m} (reporte {report.id}): " + \
            (report.summary or report.title or "sin resumen")[:600]
        for lot_id in lot_ids:
            if lot_id in planned:
                await self.tasks.create(actor, "replan_lot", "Corregir el plan con el análisis de la zona",
                                        {"lot_ids": [str(lot_id)], "observation": observation, "replan": True})
        unplanned = [str(i) for i in lot_ids if i not in planned]
        if unplanned:
            await self.tasks.create(actor, "plan_lots", "Planificar el seguimiento de los lotes de la zona",
                                    {"lot_ids": unplanned, "reason": observation})
