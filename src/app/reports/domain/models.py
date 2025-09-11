from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class ReportBase(BaseModel):
    # analysis_id: UUID # analysis_id será vinculado después del análisis
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    summary: Optional[str] = None
    recommendations: Optional[str] = None
    # image_urls: List[str] = [] # Cambiamos esto a un identificador de imagen más específico
    image_identifier: Optional[str] = None # Identificador de la imagen principal para este reporte
    # Opcional: si un reporte puede tener múltiples imágenes desde el inicio sin análisis previo:
    # initial_image_identifiers: List[str] = [] 
    raw_analysis_data: Optional[Dict[str, Any]] = None
    analysis_id: Optional[UUID] = None # Hacerlo opcional, se llenará después
    status: str = Field(default="PENDING_ANALYSIS") # Añadir un campo de estado

class ReportCreate(ReportBase):
    # Si queremos requerir el image_identifier al crear, lo ponemos aquí
    image_identifier: str # Requerido al crear un reporte inicial
    title: str = Field(default="Reporte Pendiente de Análisis", min_length=1, max_length=255) # Título por defecto
    # Los otros campos como summary, recommendations son opcionales por ReportBase
    # y se llenarán después del análisis.

class ReportUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    summary: Optional[str] = None
    recommendations: Optional[str] = None
    image_identifier: Optional[str] = None # Permitir actualizar el identificador si es necesario
    raw_analysis_data: Optional[Dict[str, Any]] = None
    analysis_id: Optional[UUID] = None
    status: Optional[str] = None # Permitir actualizar el estado

class Report(ReportBase):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {
        "from_attributes": True
    } 