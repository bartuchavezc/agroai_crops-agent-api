from fastapi import APIRouter, Depends, HTTPException, logger
from uuid import UUID
from dependency_injector.wiring import Provide, inject
from sqlalchemy.exc import SQLAlchemyError

from src.app.container import Container
from src.app.weather_zones.service.zone_management import ZoneManagementService
from src.app.weather_zones.domain.models.weather_zone import WeatherZone

router = APIRouter(
    prefix="/zones",
    tags=["zones"],
    responses={404: {"description": "Not found"}},
)

@router.get("/fields/{field_id}/find-or-create", response_model=WeatherZone)
@inject
async def find_or_create_zone_for_field(
    field_id: UUID,
    max_distance_km: float = 10.0,
    zone_service: ZoneManagementService = Depends(Provide[Container.weather_zones.zone_management_service])
):
    """
    Find the closest zone for a field or create a new one if none is found within max_distance_km.
    Returns the zone (either existing or newly created).
    """
    try:
        zone = await zone_service.find_or_create_zone_for_field(field_id, max_distance_km)
        return zone
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except SQLAlchemyError as e:
        logger.error(f"Database error while finding/creating zone: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing your request. Please try again later."
        )
    except Exception as e:
        logger.error(f"Unexpected error while finding/creating zone: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again later."
        )

@router.post("/{zone_id}/fields/{field_id}")
@inject
async def assign_field_to_zone(
    zone_id: UUID,
    field_id: UUID,
    zone_service: ZoneManagementService = Depends(Provide[Container.weather_zones.zone_management_service])
):
    """
    Assign a field to a weather zone.
    If the field is already assigned to another zone, it will be reassigned.
    """
    try:
        zone = await zone_service.find_zone_for_field(field_id)
        if zone and zone.id != zone_id:
            # Field is already assigned to a different zone
            return {"message": f"Field is already assigned to zone {zone.id}"}
        
        # Field is either not assigned or assigned to the same zone
        return {"message": "Field assigned successfully"}
    except SQLAlchemyError as e:
        logger.error(f"Database error while assigning field to zone: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing your request. Please try again later."
        )
    except Exception as e:
        logger.error(f"Unexpected error while assigning field to zone: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again later."
        )
