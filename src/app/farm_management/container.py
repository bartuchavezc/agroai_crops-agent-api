from dependency_injector import containers, providers

# Database session factory (to be provided by the root container)
from src.app.database import get_session_factory

# Repositories
from .infrastructure.repositories import (
    SQLAlchemyAccountRepository,
    SQLAlchemyFieldRepository,
    SQLAlchemyCropMasterRepository,
    SQLAlchemyCropCycleRepository,
    SQLAlchemyReportCampaignRepository
)

# Services
from .service import (
    AccountService,
    FieldService,
    CropMasterService,
    CropCycleService,
    ReportCampaignService
)

class FarmManagementContainer(containers.DeclarativeContainer):
    config = providers.Configuration() # For any farm_management specific configs

    # This session factory will be overridden by the one from the root container typically
    db_session_factory = providers.Singleton(get_session_factory)

    # --- Repositories ---
    account_repository = providers.Factory(
        SQLAlchemyAccountRepository,
        session_factory=db_session_factory
    )
    field_repository = providers.Factory(
        SQLAlchemyFieldRepository,
        session_factory=db_session_factory
    )
    crop_master_repository = providers.Factory(
        SQLAlchemyCropMasterRepository,
        session_factory=db_session_factory
    )
    crop_cycle_repository = providers.Factory(
        SQLAlchemyCropCycleRepository,
        session_factory=db_session_factory
    )
    report_campaign_repository = providers.Factory(
        SQLAlchemyReportCampaignRepository,
        session_factory=db_session_factory
    )

    # --- Services ---
    account_service = providers.Factory(
        AccountService,
        account_repository=account_repository
    )
    field_service = providers.Factory(
        FieldService,
        field_repository=field_repository,
        # account_repository=account_repository # Example if FieldService needed AccountRepository
    )
    crop_master_service = providers.Factory(
        CropMasterService,
        crop_master_repository=crop_master_repository
    )
    crop_cycle_service = providers.Factory(
        CropCycleService,
        crop_cycle_repository=crop_cycle_repository,
        field_repository=field_repository, # As defined in CropCycleService __init__
        crop_master_repository=crop_master_repository # As defined in CropCycleService __init__
    )
    report_campaign_service = providers.Factory(
        ReportCampaignService,
        report_campaign_repository=report_campaign_repository
        # Add report_repository and crop_cycle_repository if needed for validation
        # report_repository= ??? # This would come from ReportsContainer
        # crop_cycle_repository=crop_cycle_repository # Already available here
    ) 