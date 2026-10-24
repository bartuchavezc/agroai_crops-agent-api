"""
Discarding a report, everything it left included: a zone done with the wrong photos must not stay in the zone's
history, its follow-ups or the photo gallery. Used by DELETE /reports/{id} and by a zone upload that replaces the
day's earlier one (the guided walk's "rehacer").
"""
import logging
from uuid import UUID

from src.shared.domain.actor import Actor

logger = logging.getLogger(__name__)


class ReportDiscardService:
    def __init__(self, reports_service, followup_service, storage_service):
        self.reports = reports_service
        self.followups = followup_service
        self.storage = storage_service

    async def discard(self, actor: Actor, report_id: UUID) -> None:
        """The report, what its analysis wrote about follow-ups, and its photos (only after the report is gone, so
        a failure leaves nothing pointing at a missing photo)."""
        report = await self.reports.deletable(actor, report_id)
        await self.followups.forget_report(actor, report.id)
        await self.reports.delete_report(actor, report.id)
        photos = report.image_identifiers or ([report.image_identifier] if report.image_identifier else [])
        for identifier in dict.fromkeys(photos):
            try:
                await self.storage.delete_image(actor, identifier)
            except Exception:  # noqa: BLE001 - an orphan file is harmless; the report is already gone
                logger.warning(f"Could not delete photo {identifier} of discarded report {report_id}")
