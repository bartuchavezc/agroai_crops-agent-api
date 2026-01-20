# src/ingestion/managers/image_manager.py
"""
Image manager - processes image upload events.

Handles:
- Image upload notifications
- Triggering analysis workflows
- Image metadata management
"""
import logging
from typing import Any, Dict, Optional

from ..queues.interfaces import Message, MessagePriority

logger = logging.getLogger(__name__)


class ImageManager:
    """
    Manager for image upload processing.
    
    Coordinates between storage, reports, and analysis services.
    """
    
    def __init__(
        self,
        queue=None,
        storage_service=None,
        reports_service=None,
    ):
        """
        Initialize image manager.
        
        Args:
            queue: Message queue for publishing events
            storage_service: Storage service for image operations
            reports_service: Reports service for report management
        """
        self.queue = queue
        self.storage_service = storage_service
        self.reports_service = reports_service
    
    async def handle_message(self, message: Message) -> Any:
        """
        Handle incoming image message.
        
        Args:
            message: Message to process
            
        Returns:
            Processing result
        """
        payload = message.payload
        
        if message.type == "image.uploaded":
            return await self.process_upload(
                report_id=payload.get("report_id"),
                image_identifier=payload.get("image_identifier"),
            )
        elif message.type == "image.analyze":
            return await self.trigger_analysis(
                report_id=payload.get("report_id"),
                image_identifier=payload.get("image_identifier"),
            )
        else:
            logger.warning(f"Unknown image message type: {message.type}")
            return None
    
    async def process_upload(
        self,
        report_id: str,
        image_identifier: str,
    ) -> Dict[str, Any]:
        """
        Process an uploaded image.
        
        Args:
            report_id: Associated report ID
            image_identifier: Image storage identifier
            
        Returns:
            Processing result
        """
        try:
            logger.info(f"Processing upload for report {report_id}, image {image_identifier}")
            
            # Get image metadata
            if self.storage_service:
                metadata = await self.storage_service.get_image_metadata(image_identifier)
                logger.debug(f"Image metadata: {metadata}")
            
            # Update report status
            if self.reports_service:
                await self.reports_service.update_report_status(
                    report_id, "UPLOADED"
                )
            
            # Queue analysis request
            if self.queue:
                from ..queues.interfaces import Message
                analysis_message = Message(
                    type="image.analyze",
                    payload={
                        "report_id": report_id,
                        "image_identifier": image_identifier,
                    },
                    priority=MessagePriority.NORMAL,
                )
                await self.queue.publish("agent.analysis", analysis_message)
                logger.info(f"Queued analysis request for report {report_id}")
            
            return {
                "status": "processed",
                "report_id": report_id,
                "image_identifier": image_identifier,
            }
            
        except Exception as e:
            logger.error(f"Error processing upload: {e}")
            return {
                "status": "error",
                "error": str(e),
            }
    
    async def trigger_analysis(
        self,
        report_id: str,
        image_identifier: str,
    ) -> Dict[str, Any]:
        """
        Trigger image analysis (forwards to agent layer).
        
        Args:
            report_id: Report ID
            image_identifier: Image identifier
            
        Returns:
            Result indicating analysis was triggered
        """
        try:
            logger.info(f"Triggering analysis for report {report_id}")
            
            # Update report status
            if self.reports_service:
                await self.reports_service.update_report_status(
                    report_id, "ANALYZING"
                )
            
            # Publish to agent layer queue
            if self.queue:
                message = Message(
                    type="analysis.request",
                    payload={
                        "report_id": report_id,
                        "image_identifier": image_identifier,
                    },
                    priority=MessagePriority.NORMAL,
                )
                await self.queue.publish("agent.analysis", message)
            
            return {
                "status": "analysis_triggered",
                "report_id": report_id,
            }
            
        except Exception as e:
            logger.error(f"Error triggering analysis: {e}")
            return {
                "status": "error",
                "error": str(e),
            }
    
    async def get_image_status(self, image_identifier: str) -> Optional[Dict[str, Any]]:
        """
        Get the current status of an image.
        
        Args:
            image_identifier: Image identifier
            
        Returns:
            Status dictionary or None
        """
        if not self.storage_service:
            return None
        
        try:
            exists = await self.storage_service.image_exists(image_identifier)
            if not exists:
                return None
            
            metadata = await self.storage_service.get_image_metadata(image_identifier)
            return {
                "exists": True,
                "identifier": image_identifier,
                "metadata": metadata,
            }
            
        except Exception as e:
            logger.error(f"Error getting image status: {e}")
            return None
