from dependency_injector import containers, providers

from .alerts.forecast_alerts import ForecastAlertService
from .alerts.rules_engine import RulesEngine
from .alerts.service import AlertService
from .farm.repository import FarmRepository
from .farm.service import FarmService
from .notifications.service import NotificationService
from .reports.repository import SQLAlchemyReportsRepository
from .reports.service import ReportsService
from .storage.local_adapter import LocalFileRepository
from .storage.service import StorageService


class ApplicationContainer(containers.DeclarativeContainer):
    """Business services: farm, reports, alerts, storage, notifications."""

    config = providers.Configuration()
    db_session_factory = providers.Dependency()
    weather_service = providers.Dependency()
    user_repository = providers.Dependency()

    notification_service = providers.Singleton(
        NotificationService, session_factory=db_session_factory, user_repository=user_repository
    )

    farm_repository = providers.Singleton(FarmRepository, session_factory=db_session_factory)
    farm_service = providers.Singleton(
        FarmService, repository=farm_repository, notification_service=notification_service
    )

    reports_repository = providers.Singleton(SQLAlchemyReportsRepository, session_factory=db_session_factory)
    reports_service = providers.Singleton(
        ReportsService, reports_repository=reports_repository, farm_service=farm_service
    )

    file_repository = providers.Singleton(LocalFileRepository, base_path=config.storage.base_data_path)
    storage_service = providers.Singleton(StorageService, file_repository=file_repository)

    rules_engine = providers.Singleton(RulesEngine)
    alert_service = providers.Singleton(AlertService, session_factory=db_session_factory)
    forecast_alert_service = providers.Singleton(
        ForecastAlertService,
        farm_repository=farm_repository,
        weather_service=weather_service,
        alert_service=alert_service,
        rules_engine=rules_engine,
        timezone_name=config.app.timezone,
    )
