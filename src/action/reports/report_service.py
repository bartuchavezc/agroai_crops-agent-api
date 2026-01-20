# src/action/reports/report_service.py
"""
Reports service.
"""
from typing import List, Optional
from uuid import UUID
import logging

from .schemas import Report, ReportCreate, ReportUpdate
from .report_repository import ReportsRepository

logger = logging.getLogger(__name__)


class ReportsService:
    """Service for managing reports."""
    
    def __init__(
        self,
        reports_repository: ReportsRepository,
        config: Optional[dict] = None
    ):
        """
        Initialize reports service.
        
        Args:
            reports_repository: Repository for report persistence
            config: Optional configuration dict
        """
        self.reports_repository = reports_repository
        self.config = config or {}
        self.tool_messages = self.config.get("agent_llm", {}).get("tool_messages", {})

    async def create_report(self, report_create: ReportCreate) -> Report:
        """
        Create a new report.
        
        Args:
            report_create: Report creation data
            
        Returns:
            Created report
        """
        return await self.reports_repository.create(report_create)

    async def get_report_by_id(self, report_id: UUID) -> Optional[Report]:
        """
        Get a report by ID.
        
        Args:
            report_id: Report UUID
            
        Returns:
            Report if found, None otherwise
        """
        return await self.reports_repository.get_by_id(report_id)

    async def list_reports(self, skip: int = 0, limit: int = 100) -> List[Report]:
        """
        List all reports with pagination.
        
        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            
        Returns:
            List of reports
        """
        return await self.reports_repository.list_all(skip=skip, limit=limit)

    async def update_report(
        self,
        report_id: UUID,
        report_update: ReportUpdate
    ) -> Optional[Report]:
        """
        Update an existing report.
        
        Args:
            report_id: Report UUID
            report_update: Update data
            
        Returns:
            Updated report if found, None otherwise
        """
        return await self.reports_repository.update(report_id, report_update)

    async def delete_report(self, report_id: UUID) -> Optional[Report]:
        """
        Delete a report.
        
        Args:
            report_id: Report UUID
            
        Returns:
            Deleted report if found, None otherwise
        """
        return await self.reports_repository.delete(report_id)

    async def update_report_status(self, report_id: UUID, status: str) -> Optional[Report]:
        """
        Update only the report status.
        
        Args:
            report_id: Report UUID
            status: New status
            
        Returns:
            Updated report if found
        """
        return await self.update_report(report_id, ReportUpdate(status=status))

    async def get_reports_summary_for_agent(
        self,
        user_id: Optional[str] = None,
        limit: int = 5
    ) -> str:
        """
        Get a summary of recent reports formatted for the agent.
        
        Args:
            user_id: Optional user filter
            limit: Maximum reports to include
            
        Returns:
            Formatted summary string
        """
        reports = await self.reports_repository.list_all(skip=0, limit=limit)

        if not reports:
            return self.tool_messages.get(
                "reports_summary_none_found",
                "No reports found."
            )

        summary_lines = [
            self.tool_messages.get(
                "reports_summary_header",
                "Here is a summary of the most recent reports:"
            )
        ]
        
        for report in reports:
            created_at_str = (
                report.created_at.strftime('%Y-%m-%d')
                if hasattr(report, 'created_at') and report.created_at
                else 'N/A'
            )
            
            line = self.tool_messages.get(
                "report_detail_prefix",
                "- Report ID: {report_id}, Created: {created_at}"
            ).format(report_id=report.id, created_at=created_at_str)

            # Add additional details if available
            if hasattr(report, 'summary') and report.summary:
                line += f" - {report.summary[:100]}..."
            else:
                line += self.tool_messages.get(
                    "report_detail_no_details",
                    " - (Details not available)"
                )
            
            summary_lines.append(line)
        
        return "\n".join(summary_lines)
