# AgroAI Crops Agent API

Asistente agronómico para huertas y cultivos. Cada cuenta (una familia, un equipo) comparte campos, ciclos
de cultivo, eventos, alertas y la memoria del agente. Cada usuario conecta **su propia API key de Gemini**
(BYOK, free tier de Google AI Studio), así nadie agota la cuota de otro.

## Arquitectura

```
src/
├── admin/         métricas de negocio de solo lectura para el panel agroai_admin (PLATFORM_ADMIN_EMAILS)
├── auth/          transversal: cuentas, usuarios con rol (owner | tecnico | staff), JWT, onboarding
├── providers/     datos externos
│   └── weather/   OpenWeather (actual), ETL del SMN (smn.py), hypertables de TimescaleDB
├── application/   lógica de negocio
│   ├── farm/      campos, catálogo de cultivos, ciclos, eventos
│   ├── reports/   reportes / diagnósticos
│   ├── alerts/    alertas, motor de reglas, alertas proactivas por pronóstico
│   ├── applications/  registro de aplicaciones auditable (versiones, carencias) y cuaderno PDF/CSV
│   ├── supplies/  insumos en stock (fitosanitarios, fertilizantes, sustratos) y su libro de movimientos
│   ├── proactive/ lluvia en la bitácora, resúmenes diario/semanal, Web Push y preferencias de avisos
│   └── storage/   subida de imágenes y audios (separados por cuenta)
├── agent/         IA
│   ├── providers/ Gemini BYOK: keys cifradas (Fernet), gateway, endpoints
│   ├── conversations/  conversaciones privadas por usuario + endpoint de chat
│   ├── memory/    memoria del agente (tsvector + pgvector, fusión RRF), compartida por cuenta
│   ├── tools/     tools del agente (atadas al usuario autenticado)
│   ├── reasoning/ diagnóstico multimodal con salida estructurada (/analyze)
│   ├── nudges.py  el asistente escribe primero: señales abiertas, decide el modelo, límites de la persona
│   └── runner.py  turno de Google ADK (texto, foto o audio transcripto)
├── config/        settings, container DI, bootstrap
├── main.py        FastAPI
└── batch.py       jobs batch (SMN + alertas, recordatorios, serie satelital, proactivo)
```

Dependencias entre capas: `agent → application → providers`. `auth` y `shared` son transversales.

**Infra:** un servidor Python (imagen única: `api` + `worker`) y un PostgreSQL con **TimescaleDB** (series de
clima) y **pgvector** (memoria). Migraciones con Alembic. Las sesiones de Google ADK viven en el schema `adk`.

### El agente
- Google ADK 2.x + Gemini (default `gemini-flash-latest`, multimodal). El modelo se instancia en cada turno con
  la key del usuario que habla (`client_kwargs={"api_key": ...}`); nunca se usa `GOOGLE_API_KEY` global.
- Tools: campos/ciclos/eventos (escritura según rol), memoria (`remember_fact`, `recall_facts`, `forget_fact`),
  clima (`get_current_weather`, `get_forecast`), alertas, guardar diagnóstico y búsqueda web de Google.
- Las tools son closures ligadas al usuario autenticado: el modelo no puede elegir sobre qué cuenta actuar.
- Conversaciones tradicionales: cada usuario tiene varias, privadas; 1 conversación = 1 sesión de ADK.

### SMN
`src/providers/weather/smn.py` es el ETL completo del pronóstico WRF del Servicio Meteorológico Nacional
(bucket público `s3://smn-ar-wrf`): busca el último ciclo completo, descarga los archivos horarios (cada
`SMN_HOURLY_STEP` h hasta 72 h) y diarios (Tmin/Tmax), empareja las coordenadas de los campos con la celda más
cercana de la grilla (cacheada en disco) y carga `weather_forecasts`. Después, `ForecastAlertService` evalúa
las reglas (helada, calor, riesgo fúngico, lluvia fuerte) y crea alertas deduplicadas, sin LLM.

```bash
python -m src.batch smn                   # una vez
python -m src.batch smn --every-hours 6   # loop (servicio `worker` del compose)
python -m src.batch reminders --every-minutes 5   # recordatorios vencidos → notificaciones (servicio `reminders`)
```

### Satélite (Copernicus)
Cada campo tiene una serie temporal en `field_satellite_observations`: una fila por pasada real de
Sentinel-2 L2A (NDVI con desvío y percentiles, NDRE, NDMI, EVI, NDWI y la fracción del campo sin nubes) y de
Sentinel-1 (VV/VH, cross-ratio y RVI, para los períodos nublados), con `UNIQUE (field_id, observed_on, source)`
y upsert. La Statistical API devuelve hasta un año de pasadas en una llamada (intervalo P1D), así que el
backfill de varios años son pocas llamadas por campo. `src/application/satellite/analytics.py` calcula al
leer la serie suavizada, lo normal de cada semana para ese campo (años previos), la anomalía contra eso y
contra el año pasado, y las etapas de la curva; las reglas `satellite_*` generan alertas como "este campo va
peor que el año pasado".

Los créditos del free tier (10.000 unidades/mes) se miden con el header de cada respuesta y se guardan en
`copernicus_usage`, con un cupo mensual para el batch y otro para lo que pide el usuario. El job programado
está apagado (`SATELLITE_INGEST_ENABLED=false`) hasta medir el costo real con un campo:

```bash
python -m src.scripts.copernicus_measure --field-id <uuid>   # costo real por campo y cuántos entran
python -m src.batch satellite                                # backfill + pasadas nuevas + alertas, una vez
python -m src.batch satellite --every-hours 24               # loop (servicio `satellite` del compose)
python -m src.batch satellite-backfill --years 5             # extender la historia y guardar los píxeles de toda la serie
```

**Imágenes: se guardan una vez y se dibujan siempre desde lo nuestro.** Por cada pasada de Sentinel-2 se pide a
Copernicus un recorte pequeño del campo (bandas + clasificación de nubes SCL) y se guarda comprimido en
`field_satellite_chips` (`src/application/satellite/chips.py`). El job diario guarda las pasadas de los últimos
20 días; `satellite-backfill` completa las de toda la serie. Los mapas (`ndvi`, `ndmi`, `ndwi`, `rgb`) se calculan
localmente con la mediana píxel a píxel de los últimos 15 días, usando solo los píxeles limpios de cada pasada,
así que mostrar una imagen no llama a Copernicus ni gasta créditos.

### Registro auditable y asistente proactivo
- **Bitácora con lo que no se hizo**: cada entrada es `done` o `skipped` con su motivo («no regué: llovió»); la lluvia
  la escribe el sistema (Open-Meteo, fuente `system`). Los lotes guardan lo sembrado y su cantidad viva sale de las
  pérdidas y los conteos; una resiembra es un lote nuevo que reemplaza (en parte) al anterior.
- **Aplicaciones** (`application/applications`): borrador → confirmada; una confirmada no se edita ni se borra (las
  correcciones y anulaciones son versiones con motivo). Los productos se copian como texto formal del registro SENASA
  (o escritos a mano y marcados «no verificado»), con dosis, carencia leída de la etiqueta, clima de esa hora y
  evidencia (audio, foto). Descuenta stock y deja cada lote tratado con «no cosechar hasta»; `/applications/export`
  da el cuaderno en PDF o CSV.
- **Audio**: `POST /upload/audio` y `audio_identifier` en `/chat`: Gemini lo transcribe, el turno corre con el texto y
  el audio queda como evidencia.
- **Proactivo** (`python -m src.batch proactive --every-minutes 15`): lluvia cada 6 h, resumen a la tarde (y el
  semanal el domingo) para owner/tecnico, y dos chequeos por día (`NUDGE_WINDOWS`) más uno por hora para lo urgente.
  El código junta señales abiertas; una llamada por cuenta (con la key de un owner) decide si escribir, a quién y qué
  —o callarse—; el máximo de mensajes por día y el horario de silencio de cada persona se aplican después. El mensaje
  queda en una conversación y Web Push (`VAPID_*`) lo lleva al teléfono. `/nudges/log` muestra cada decisión.

## Puesta en marcha

```bash
cp .env.example .env        # completar AUTH_SECRET_KEY, CREDENTIALS_ENCRYPTION_KEY, OPENWEATHER_API_KEY
docker compose up --build   # db → migrate → api (:8000) + worker + reminders
```

Documentación interactiva (solo con `DEV_MODE=true`): http://localhost:8000/docs · Resumen de endpoints: [docs/api.md](docs/api.md)

Flujo mínimo: `POST /auth/signup` → `PUT /me/provider-credentials/gemini` (la key de
https://aistudio.google.com/apikey) → `POST /farm-management/fields` → `POST /chat`.

## Desarrollo

```bash
uv sync
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn src.main:app --reload
uv run pytest          # los tests de integración crean y migran la base `agroai_test`
uv run ruff check src tests
```

Nueva migración: `uv run alembic revision --autogenerate -m "..."` (revisar el archivo generado).

## Datos que hay que cargar después de migrar

- `uv run python -m src.scripts.seed_products`: registros de productos (SENASA, HRAC).
- `uv run python -m src.scripts.import_soilgrids --dir raw_data/downloads/soilgrids`: SoilGrids (pH, carbono, nitrógeno,
  CEC) en tiles geocodificados dentro de Postgres. Sin esto no hay estimación de suelo por coordenadas.
- `uv run python -m src.scripts.eval_agent_routing`: evaluación opcional con el modelo real (gasta cuota).
