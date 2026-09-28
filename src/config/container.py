from dependency_injector import containers
from dependency_injector import providers as di

from src.agent.container import AgentContainer
from src.application.container import ApplicationContainer
from src.auth.container import AuthLayerContainer
from src.providers.container import ProvidersContainer
from src.shared.database import get_adk_engine, get_session_factory


class Container(containers.DeclarativeContainer):
    """Layers: providers (external data) <- application (business) <- agent (LLM). Auth is transversal."""

    config = di.Configuration()

    db_session_factory = di.Singleton(get_session_factory)
    adk_engine = di.Singleton(get_adk_engine)

    auth = di.Container(AuthLayerContainer, config=config.auth, db_session_factory=db_session_factory)
    data_providers = di.Container(ProvidersContainer, config=config, db_session_factory=db_session_factory)
    application = di.Container(
        ApplicationContainer,
        config=config,
        db_session_factory=db_session_factory,
        weather_service=data_providers.weather_service,
        user_repository=auth.user_repository,
        copernicus=data_providers.copernicus,
    )
    agent = di.Container(
        AgentContainer,
        config=config,
        db_session_factory=db_session_factory,
        adk_engine=adk_engine,
        application=application,
        weather_service=data_providers.weather_service,
        profile_service=auth.profile_service,
        search_provider=data_providers.search,
        nasa_power=data_providers.nasa_power,
    )
