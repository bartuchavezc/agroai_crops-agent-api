from dependency_injector import containers, providers
from google.adk.sessions import DatabaseSessionService

from .conversations.service import ConversationService
from .memory.service import MemoryService
from .providers.credentials_service import CredentialsService
from .providers.encryption import SecretBox
from .providers.gemini import GeminiGateway
from .providers.repository import ProviderCredentialRepository
from .reasoning.diagnosis_service import DiagnosisService
from .runner import AgentRunner
from .tools import ToolDeps


class AgentContainer(containers.DeclarativeContainer):
    """LLM providers (BYOK), conversations, memory, diagnosis and the ADK runner."""

    config = providers.Configuration()
    db_session_factory = providers.Dependency()
    adk_engine = providers.Dependency()
    application = providers.DependenciesContainer()
    weather_service = providers.Dependency()
    profile_service = providers.Dependency()
    search_provider = providers.Dependency()
    nasa_power = providers.Dependency()

    secret_box = providers.Singleton(SecretBox, key=config.security.credentials_encryption_key)
    credential_repository = providers.Singleton(ProviderCredentialRepository, session_factory=db_session_factory)
    credentials_service = providers.Singleton(
        CredentialsService, repository=credential_repository, secret_box=secret_box
    )
    gemini = providers.Singleton(GeminiGateway, credentials_service=credentials_service, config=config.gemini)

    conversation_service = providers.Singleton(
        ConversationService, session_factory=db_session_factory, farm_service=application.farm_service
    )
    memory_service = providers.Singleton(MemoryService, session_factory=db_session_factory, gemini_gateway=gemini)
    session_service = providers.Singleton(DatabaseSessionService, db_engine=adk_engine)

    diagnosis_service = providers.Singleton(
        DiagnosisService,
        gemini=gemini,
        storage_service=application.storage_service,
        reports_service=application.reports_service,
        farm_service=application.farm_service,
        weather_service=weather_service,
        rules_engine=application.rules_engine,
        profile_service=profile_service,
        notification_service=application.notification_service,
        satellite_repository=application.zone_satellite_repository,
        search=search_provider,
        max_image_side=config.gemini.max_image_side,
        deep_default=config.agent.analysis_deep,
    )

    tool_deps = providers.Singleton(
        ToolDeps,
        farm=application.farm_service,
        memory=memory_service,
        weather=weather_service,
        alerts=application.alert_service,
        reports=application.reports_service,
        rules=application.rules_engine,
        gemini=gemini,
        search=search_provider,
        diagnosis=diagnosis_service,
        irrigation=application.irrigation_service,
        inventory=application.inventory_service,
        management=application.management_service,
        planning=application.planning_service,
        satellite=application.satellite_service,
        storage=application.storage_service,
        nasa_power=nasa_power,
    )
    runner = providers.Singleton(
        AgentRunner,
        gemini=gemini,
        session_service=session_service,
        conversations=conversation_service,
        tool_deps=tool_deps,
        farm_service=application.farm_service,
        alert_service=application.alert_service,
        profile_service=profile_service,
        storage_service=application.storage_service,
        reports_service=application.reports_service,
        timezone_name=config.app.timezone,
        max_image_side=config.gemini.max_image_side,
        preflight_enabled=config.agent.preflight,
        preflight_max_tokens=config.agent.preflight_max_tokens,
    )
