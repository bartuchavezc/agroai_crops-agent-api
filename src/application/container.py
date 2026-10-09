from dependency_injector import containers, providers

from .alerts.field_rules import FieldAlertRulesService
from .alerts.forecast_alerts import ForecastAlertService
from .alerts.rules_engine import RulesEngine
from .alerts.service import AlertService
from .farm.summary import FieldSummaryService
from .farm.timeline import ZoneTimelineService
from .farm.repository import FarmRepository
from .farm.service import FarmService
from .inventory.repository import SeedLotRepository
from .inventory.service import InventoryService
from .irrigation.service import EvapotranspirationService
from .management.repository import ManagementRepository
from .management.service import ManagementService
from .notifications.service import NotificationService
from .planning.progress import CycleProgressService
from .planning.repository import PlanningRepository
from .planning.service import PlanningService
from .reports.repository import SQLAlchemyReportsRepository
from .reports.service import ReportsService
from .satellite.ingest import SatelliteIngestService
from .satellite.repository import SatelliteSeriesRepository, ZoneSatelliteRepository
from .satellite.service import ZoneSatelliteService
from .soil_data.repository import SoilDataRepository

from .soil_data.service import SoilContextService
from .soil_data.soilgrids_repository import SoilGridsRepository
from .storage.local_adapter import LocalFileRepository
from .storage.service import StorageService


class ApplicationContainer(containers.DeclarativeContainer):
    """Business services: farm, reports, alerts, storage, notifications, irrigation, inventory,
    management, planning, satellite."""

    config = providers.Configuration()
    db_session_factory = providers.Dependency()
    weather_service = providers.Dependency()
    user_repository = providers.Dependency()
    copernicus = providers.Dependency()

    notification_service = providers.Singleton(
        NotificationService, session_factory=db_session_factory, user_repository=user_repository
    )

    soil_data_repository = providers.Singleton(SoilDataRepository, session_factory=db_session_factory)
    soilgrids_repository = providers.Singleton(SoilGridsRepository, session_factory=db_session_factory)
    soil_context_service = providers.Singleton(
        SoilContextService,
        repository=soil_data_repository,
        soilgrids=soilgrids_repository,
    )

    farm_repository = providers.Singleton(FarmRepository, session_factory=db_session_factory)
    farm_service = providers.Singleton(
        FarmService,
        repository=farm_repository,
        notification_service=notification_service,
        soil_context_service=soil_context_service,
    )

    reports_repository = providers.Singleton(SQLAlchemyReportsRepository, session_factory=db_session_factory)
    reports_service = providers.Singleton(
        ReportsService, reports_repository=reports_repository, farm_service=farm_service
    )

    file_repository = providers.Singleton(LocalFileRepository, base_path=config.storage.base_data_path)
    storage_service = providers.Singleton(StorageService, file_repository=file_repository)

    rules_engine = providers.Singleton(RulesEngine)
    alert_service = providers.Singleton(AlertService, session_factory=db_session_factory, farm_service=farm_service)
    field_alert_rules_service = providers.Singleton(
        FieldAlertRulesService, session_factory=db_session_factory, farm_service=farm_service,
        rules_engine=rules_engine,
    )
    forecast_alert_service = providers.Singleton(
        ForecastAlertService,
        farm_repository=farm_repository,
        weather_service=weather_service,
        alert_service=alert_service,
        rules_engine=rules_engine,
        timezone_name=config.app.timezone,
        field_rules=field_alert_rules_service,
    )

    irrigation_service = providers.Singleton(
        EvapotranspirationService,
        farm_service=farm_service,
        farm_repository=farm_repository,
        weather_service=weather_service,
        alert_service=alert_service,
        rules_engine=rules_engine,
        field_rules=field_alert_rules_service,
    )

    seed_lot_repository = providers.Singleton(SeedLotRepository, session_factory=db_session_factory)
    inventory_service = providers.Singleton(
        InventoryService, repository=seed_lot_repository, farm_service=farm_service
    )

    management_repository = providers.Singleton(ManagementRepository, session_factory=db_session_factory)
    management_service = providers.Singleton(
        ManagementService, repository=management_repository, farm_service=farm_service
    )

    planning_repository = providers.Singleton(PlanningRepository, session_factory=db_session_factory)
    planning_service = providers.Singleton(
        PlanningService,
        repository=planning_repository,
        farm_service=farm_service,
        notification_service=notification_service,
        management_service=management_service,
        inventory_service=inventory_service,
        timezone_name=config.app.timezone,
    )

    field_summary_service = providers.Singleton(
        FieldSummaryService, farm_service=farm_service, reports_service=reports_service,
        planning_service=planning_service, alert_service=alert_service, irrigation_service=irrigation_service,
    )
    zone_timeline_service = providers.Singleton(
        ZoneTimelineService, farm_service=farm_service, reports_service=reports_service,
        planning_repository=planning_repository,
    )
    cycle_progress_service = providers.Singleton(
        CycleProgressService, farm_service=farm_service, planning_service=planning_service,
        reports_service=reports_service,
    )

    zone_satellite_repository = providers.Singleton(ZoneSatelliteRepository, session_factory=db_session_factory)
    satellite_series_repository = providers.Singleton(SatelliteSeriesRepository, session_factory=db_session_factory)
    satellite_ingest_service = providers.Singleton(
        SatelliteIngestService,
        repository=satellite_series_repository,
        copernicus=copernicus,
        backfill_years=config.satellite.backfill_years,
        batch_pu_budget=config.satellite.batch_pu_budget,
        on_demand_pu_budget=config.satellite.on_demand_pu_budget,
        s1_enabled=config.satellite.s1_enabled,
        s1_orbit_direction=config.satellite.s1_orbit_direction,
    )
    satellite_service = providers.Singleton(
        ZoneSatelliteService,
        farm_service=farm_service,
        farm_repository=farm_repository,
        repository=zone_satellite_repository,
        series_repository=satellite_series_repository,
        ingest=satellite_ingest_service,
        min_valid_fraction=config.satellite.min_valid_fraction,
        field_rules=field_alert_rules_service,
        copernicus=copernicus,
        storage_service=storage_service,
        alert_service=alert_service,
        rules_engine=rules_engine,
    )
