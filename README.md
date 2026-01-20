# AgroAI Crops Agent API

AI-powered precision agronomic technical assistant. A decision support system integrating real-time data (climate, sensors, vision) with a proprietary and localized technical knowledge base.

## Architecture Overview

The application follows a **3-layer architecture** + Auth:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        External Sources                              │
│  (APIs, Sensors, Users, Weather Services)                           │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                      AUTH LAYER (Separate)                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐    │
│  │   Auth Service  │  │  User Service   │  │  JWT Middleware  │    │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘    │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                    CAPA 1: INGESTA                                   │
│  ┌──────────────────────────┐    ┌─────────────────────────────┐    │
│  │       RECEPTION          │    │         QUEUES              │    │
│  │  - REST Endpoints        │───▶│  - IMessageQueue            │    │
│  │  - Adapters (SMN, etc)   │    │  - Redis/Memory impl        │    │
│  │  - Webhooks              │    └───────────┬─────────────────┘    │
│  └──────────────────────────┘                │                      │
│                                              ▼                      │
│                               ┌─────────────────────────────────┐   │
│                               │         MANAGERS                │   │
│                               │  - Event Router                 │   │
│                               │  - Weather Manager              │   │
│                               │  - Image Manager                │   │
│                               └───────────┬─────────────────────┘   │
└───────────────────────────────────────────┼─────────────────────────┘
                                            │
┌───────────────────────────────────────────▼─────────────────────────┐
│                    CAPA 2: AGENTE                                    │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    SEARCH (2 Stages)                         │    │
│  │  ┌─────────────────────┐    ┌─────────────────────────┐     │    │
│  │  │  Index Lookup       │───▶│  Document Search        │     │    │
│  │  │  (Summaries)        │    │  (Full content)         │     │    │
│  │  └─────────────────────┘    └─────────────────────────┘     │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌───────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │   LLM Service     │  │  Rules Engine    │  │  Conversation    │  │
│  │   (Ollama)        │  │  (Deterministic) │  │  Manager         │  │
│  └───────────────────┘  └──────────────────┘  └──────────────────┘  │
└───────────────────────────────────────────┬─────────────────────────┘
                                            │
┌───────────────────────────────────────────▼─────────────────────────┐
│                    CAPA 3: ACCION                                    │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐    │
│  │     Alerts      │  │    Reports      │  │    Storage       │    │
│  │  Notifications  │  │    CRUD         │  │    Files/S3      │    │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │              Commands (Future: IoT Integration)              │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
src/
├── __init__.py                    # Legacy entry point (redirects to main.py)
├── main.py                        # FastAPI app factory (NEW)
├── config/                        # Centralized configuration
│   ├── settings.py                # Configuration loading
│   └── container.py               # Root DI container
│
├── auth/                          # AUTH LAYER
│   ├── api/
│   │   ├── routes.py              # Auth endpoints
│   │   └── dependencies.py        # JWT middleware
│   ├── services/
│   │   ├── auth_service.py
│   │   └── user_service.py
│   ├── adapters/
│   │   ├── jwt_adapter.py
│   │   └── user_repository.py
│   ├── domain/
│   │   ├── models.py
│   │   └── schemas.py
│   └── container.py
│
├── ingestion/                     # LAYER 1: INGESTION
│   ├── reception/                 # Data arrival
│   │   ├── api/
│   │   │   ├── weather_router.py
│   │   │   └── upload_router.py
│   │   └── adapters/
│   │       ├── smn_adapter.py
│   │       └── openweather_adapter.py
│   ├── queues/                    # Queue abstraction
│   │   ├── interfaces.py          # IMessageQueue
│   │   ├── redis_queue.py
│   │   └── memory_queue.py
│   ├── managers/                  # Event processors
│   │   ├── weather_manager.py
│   │   ├── image_manager.py
│   │   └── event_router.py
│   └── container.py
│
├── agent/                         # LAYER 2: AGENT
│   ├── api/
│   │   └── chat_router.py
│   ├── conversation/
│   │   ├── agent_service.py
│   │   └── memory_manager.py
│   ├── search/                    # Two-stage search
│   │   ├── interfaces.py
│   │   ├── index_lookup.py        # Stage 1: summaries
│   │   ├── doc_search.py          # Stage 2: documents
│   │   ├── search_service.py      # Orchestrator
│   │   └── elastic_adapter.py
│   ├── reasoning/
│   │   ├── llm_service.py
│   │   ├── rules_engine.py        # Deterministic rules
│   │   └── diagnosis_service.py
│   └── container.py
│
├── action/                        # LAYER 3: ACTION
│   ├── api/
│   │   ├── reports_router.py
│   │   ├── alerts_router.py
│   │   └── analyze_router.py
│   ├── alerts/
│   │   └── alert_service.py
│   ├── reports/
│   │   ├── report_service.py
│   │   └── report_repository.py
│   ├── storage/
│   │   ├── storage_service.py
│   │   └── local_adapter.py
│   ├── commands/                  # Future: IoT
│   │   └── interfaces.py
│   └── container.py
│
├── shared/                        # Shared between layers
│   ├── domain/
│   │   ├── region.py              # Multi-country support
│   │   └── base.py
│   ├── database/
│   │   ├── postgres.py
│   │   └── timescale.py
│   └── utils/
│       ├── errors.py
│       └── logger.py
│
└── app/                           # LEGACY (to be removed)
    └── ...
```

## Setup and Installation

### Prerequisites

- Python 3.10+
- PostgreSQL 14+ with TimescaleDB extension
- Redis (for queues and caching)
- Elasticsearch/OpenSearch (for two-stage search)
- Ollama (for LLM inference)

### Installation

1. Install Poetry:
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. Install dependencies:
```bash
cd agroai_crops-agent-api
poetry install
```

3. Configure environment:
```bash
cp .env.example .env
# Edit .env with your settings
```

4. Run the application:
```bash
# Development
poetry run uvicorn src.main:app --reload

# Production
poetry run uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API Endpoints

### Authentication
- `POST /api/v1/auth/login` - Login and get JWT token
- `POST /api/v1/auth/signup` - Register new user
- `GET /api/v1/auth/me` - Get current user info

### Weather (Ingestion)
- `GET /api/v1/weather/latest` - Get latest weather data
- `GET /api/v1/weather/current` - Get real-time weather (OpenWeatherMap)
- `POST /api/v1/weather/fetch` - Fetch weather for all zones
- `GET /api/v1/weather/history` - Get historical weather

### Chat (Agent)
- `POST /api/v1/chat` - Send message to agent
- `DELETE /api/v1/chat/memory` - Clear conversation memory
- `GET /api/v1/chat/health` - Agent health check

### Reports (Action)
- `GET /api/v1/reports` - List all reports
- `POST /api/v1/reports` - Create report
- `GET /api/v1/reports/{id}` - Get report by ID
- `PUT /api/v1/reports/{id}` - Update report
- `DELETE /api/v1/reports/{id}` - Delete report

### Analysis (Action)
- `POST /api/v1/analyze` - Analyze crop image

### Alerts (Action)
- `GET /api/v1/alerts` - List alerts
- `POST /api/v1/alerts` - Create alert
- `GET /api/v1/alerts/active` - Get active (unacknowledged) alerts
- `PUT /api/v1/alerts/{id}/acknowledge` - Acknowledge alert

### Upload (Ingestion)
- `POST /api/v1/upload/image` - Upload crop image

## Two-Stage Search System

The search system uses a two-stage approach for efficient document retrieval:

### Stage 1: Index Lookup
- Searches a lightweight index of summaries/categories
- Identifies which document collections are relevant
- Uses Elasticsearch/OpenSearch `agro_summaries` index

### Stage 2: Document Search
- Searches full documents within identified categories
- Applies region filters when applicable
- Uses Elasticsearch/OpenSearch `agro_documents` index

This approach:
- Reduces search space for large document collections
- Improves relevance by focusing on appropriate categories
- Supports multi-country/region filtering

## Multi-Country Support

The architecture supports multi-country deployment without full i18n:

```python
# Region filtering in queries
from src.shared.domain.region import Region, get_region

region = get_region("AR")  # Argentina
documents = await search_service.search(
    query="tratamiento para trips",
    region=region.country_code
)
```

Supported countries:
- AR (Argentina)
- MX (México)
- CO (Colombia)

## Configuration

Configuration is managed through:
1. `config.yml` - Main configuration file
2. Environment variables - Override config values
3. `src/config/settings.py` - Default values

Key configuration sections:
- `app` - Application settings (name, version, CORS)
- `auth` - JWT settings
- `database` - PostgreSQL connection
- `timescale` - TimescaleDB connection
- `queues` - Message queue settings (Redis)
- `search` - Elasticsearch settings
- `weather_data` - Weather service settings

## Development

### Running Tests
```bash
poetry run pytest
```

### Code Formatting
```bash
poetry run black src/
poetry run isort src/
```

### Linting
```bash
poetry run flake8 src/
```

## Migration from Legacy

The legacy code in `src/app/` will be removed in a future version. To migrate:

1. Update imports from `src.app.*` to new paths:
   - `src.app.users` → `src.auth`
   - `src.app.reports` → `src.action.reports`
   - `src.app.storage` → `src.action.storage`
   - `src.app.agent` → `src.agent`
   - `src.app.weather_data` → `src.ingestion`

2. Use new container paths:
   - `Container.users` → `Container.auth`
   - `Container.reports` → `Container.action`
   - `Container.agent` → `Container.agent`

3. Update entry point:
   - Old: `uvicorn src:app`
   - New: `uvicorn src.main:app`

## License

Proprietary - All rights reserved.
