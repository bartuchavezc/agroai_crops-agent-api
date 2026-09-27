from dotenv import load_dotenv

from src.config.container import Container
from src.config.settings import load_app_config
from src.shared.database import init_database_connections
from src.shared.utils.logger import register_secret


def build_container() -> Container:
    """Load configuration, open the database and return the wired DI container."""
    load_dotenv()
    config = load_app_config()
    register_secret(config["search"]["tavily_api_key"])  # server-side key; user Gemini keys register on use
    init_database_connections(config["database"]["url"], config["database"]["echo"])
    container = Container()
    container.config.from_dict(config)
    return container
