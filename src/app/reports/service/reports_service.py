from typing import List, Optional
from uuid import UUID
from src.app.reports.domain.models import Report, ReportCreate, ReportUpdate
from src.app.reports.domain.repositories import ReportsRepository

class ReportsService:
    def __init__(self, reports_repository: ReportsRepository, config: Optional[dict] = None):
        self.reports_repository = reports_repository
        self.config = config if config else {} # Store the config
        # Get tool messages, defaulting to an empty dict if not found
        self.tool_messages = self.config.get("agent_llm", {}).get("tool_messages", {})

    async def create_report(self, report_create: ReportCreate) -> Report:
        # Aquí podría ir lógica adicional antes de crear el reporte,
        # como validaciones complejas, notificaciones, etc.
        return await self.reports_repository.create(report_create)

    async def get_report_by_id(self, report_id: UUID) -> Optional[Report]:
        return await self.reports_repository.get_by_id(report_id)

    async def list_reports(self, skip: int = 0, limit: int = 100) -> List[Report]:
        return await self.reports_repository.list_all(skip=skip, limit=limit)

    async def update_report(self, report_id: UUID, report_update: ReportUpdate) -> Optional[Report]:
        # Lógica de negocio antes de actualizar, si es necesaria
        return await self.reports_repository.update(report_id, report_update)

    async def delete_report(self, report_id: UUID) -> Optional[Report]:
        # Lógica de negocio antes de eliminar, si es necesaria
        return await self.reports_repository.delete(report_id)

    async def get_reports_summary_for_agent(self, user_id: Optional[str] = None, limit: int = 5) -> str:
        """
        Fetches a summary of the most recent reports for a user, formatted for an LLM agent.
        If user_id is provided, it will try to filter reports for that user (assuming repository supports it).
        """
        reports = await self.reports_repository.list_all(skip=0, limit=limit)

        if not reports:
            return self.tool_messages.get("reports_summary_none_found", "No reports found.")

        summary_lines = [self.tool_messages.get("reports_summary_header", "Here is a summary of the most recent reports:")] 
        for report in reports:
            created_at_str = report.created_at.strftime('%Y-%m-%d') if hasattr(report, 'created_at') and report.created_at else 'N/A'
            
            line = self.tool_messages.get("report_detail_prefix", "- Report ID: {report_id}, Created: {created_at}").format(
                report_id=report.id, created_at=created_at_str
            )

            if hasattr(report, 'crop_name') and report.crop_name:
                line += self.tool_messages.get("report_detail_crop",", Crop: {crop_name}").format(crop_name=report.crop_name)
            if hasattr(report, 'image_filename') and report.image_filename:
                line += self.tool_messages.get("report_detail_image",", Imagen: {image_filename}").format(image_filename=report.image_filename)
            
            finding_text = None
            if hasattr(report, 'diagnosis') and report.diagnosis:
                finding_text = self.tool_messages.get("report_detail_finding", " - Hallazgo: {finding}").format(finding=report.diagnosis)
            elif hasattr(report, 'analysis_summary') and report.analysis_summary:
                finding_text = self.tool_messages.get("report_detail_summary", " - Resumen: {summary}").format(summary=report.analysis_summary)
            
            if finding_text:
                line += finding_text
            else:
                line += self.tool_messages.get("report_detail_no_details", " - (Detalles no disponibles)")
            summary_lines.append(line)
        
        return "\n".join(summary_lines)