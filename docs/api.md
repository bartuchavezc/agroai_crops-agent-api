# AgroAI Crops Agent API - Documentación de APIs

**Base URL:** `/api/v1`  
**Versión:** 0.2.0  
**Content-Type:** `application/json`

---

## Índice

1. [Autenticación](#autenticación)
2. [Weather (Ingesta)](#weather-ingesta)
3. [Upload (Ingesta)](#upload-ingesta)
4. [Chat (Agente)](#chat-agente)
5. [Reports (Acción)](#reports-acción)
6. [Alerts (Acción)](#alerts-acción)
7. [Analysis (Acción)](#analysis-acción)
8. [Health](#health)

---

## Autenticación

### POST /auth/login

Autentica un usuario y devuelve un token JWT.

**Request Body:**

```json
{
  "email": "string",
  "password": "string"
}
```

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| email | string | Sí | Email del usuario |
| password | string | Sí | Contraseña del usuario |

**Response:** `200 OK`

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| access_token | string | Token JWT para autenticación |
| token_type | string | Tipo de token (siempre "bearer") |

**Errores:**

| Código | Descripción |
|--------|-------------|
| 401 | Credenciales inválidas |

**Ejemplo cURL:**

```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "usuario@ejemplo.com", "password": "mipassword123"}'
```

---

### POST /auth/signup

Registra un nuevo usuario y devuelve un token JWT.

**Request Body:**

```json
{
  "email": "string",
  "password": "string",
  "account_id": "uuid",
  "first_name": "string | null",
  "last_name": "string | null",
  "role": "string | null"
}
```

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| email | string (email) | Sí | Email del usuario |
| password | string | Sí | Contraseña del usuario |
| account_id | UUID | Sí | ID de la cuenta asociada |
| first_name | string | No | Nombre del usuario |
| last_name | string | No | Apellido del usuario |
| role | string | No | Rol del usuario |

**Response:** `200 OK`

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Errores:**

| Código | Descripción |
|--------|-------------|
| 400 | Usuario ya existe |

**Ejemplo cURL:**

```bash
curl -X POST "http://localhost:8000/api/v1/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "nuevo@ejemplo.com",
    "password": "password123",
    "account_id": "550e8400-e29b-41d4-a716-446655440000",
    "first_name": "Juan",
    "last_name": "Pérez"
  }'
```

---

### POST /auth/users

Crea un nuevo usuario (endpoint administrativo).

**Request Body:**

```json
{
  "email": "string",
  "password": "string",
  "account_id": "uuid",
  "first_name": "string | null",
  "last_name": "string | null",
  "role": "string | null"
}
```

**Response:** `200 OK`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "email": "nuevo@ejemplo.com",
  "account_id": "550e8400-e29b-41d4-a716-446655440000",
  "first_name": "Juan",
  "last_name": "Pérez",
  "role": "user",
  "created_at": "2025-01-20T10:30:00Z",
  "updated_at": "2025-01-20T10:30:00Z"
}
```

---

### GET /auth/me

Obtiene información del usuario autenticado actual junto con su cuenta.

**Headers:**

| Header | Valor | Requerido |
|--------|-------|-----------|
| Authorization | Bearer {token} | Sí |

**Response:** `200 OK`

```json
{
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440001",
    "email": "usuario@ejemplo.com",
    "account_id": "550e8400-e29b-41d4-a716-446655440000",
    "first_name": "Juan",
    "last_name": "Pérez",
    "role": "admin",
    "created_at": "2025-01-15T08:00:00Z",
    "updated_at": "2025-01-20T10:30:00Z"
  },
  "account": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Finca El Roble",
    "country_code": "AR"
  }
}
```

**Errores:**

| Código | Descripción |
|--------|-------------|
| 401 | Token inválido o expirado |
| 404 | Cuenta no encontrada |

**Ejemplo cURL:**

```bash
curl -X GET "http://localhost:8000/api/v1/auth/me" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

### GET /auth/users/{user_id}

Obtiene un usuario por su ID.

**Path Parameters:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| user_id | UUID | ID del usuario |

**Response:** `200 OK`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "email": "usuario@ejemplo.com",
  "account_id": "550e8400-e29b-41d4-a716-446655440000",
  "first_name": "Juan",
  "last_name": "Pérez",
  "role": "user",
  "created_at": "2025-01-15T08:00:00Z",
  "updated_at": "2025-01-20T10:30:00Z"
}
```

**Errores:**

| Código | Descripción |
|--------|-------------|
| 404 | Usuario no encontrado |

---

## Weather (Ingesta)

### GET /weather/latest

Obtiene los datos meteorológicos más recientes para una ubicación.

**Query Parameters:**

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| latitude | float | Sí | Latitud de la ubicación |
| longitude | float | Sí | Longitud de la ubicación |

**Response:** `200 OK`

```json
{
  "id": 12345,
  "timestamp": "2025-01-20T14:30:00Z",
  "latitude": -34.6037,
  "longitude": -58.3816,
  "temperature": 28.5,
  "humidity": 65.0,
  "precipitation": 0.0,
  "wind_speed": 12.3,
  "wind_direction": 180.0,
  "pressure": 1013.25,
  "soil_moisture": 0.35
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| temperature | float | Temperatura en °C |
| humidity | float | Humedad relativa en % |
| precipitation | float | Precipitación en mm |
| wind_speed | float | Velocidad del viento en m/s |
| wind_direction | float | Dirección del viento en grados |
| pressure | float | Presión atmosférica en hPa |
| soil_moisture | float | Humedad del suelo (0-1) |

**Errores:**

| Código | Descripción |
|--------|-------------|
| 404 | No hay datos meteorológicos disponibles |
| 500 | Error del servidor |

**Ejemplo cURL:**

```bash
curl -X GET "http://localhost:8000/api/v1/weather/latest?latitude=-34.6037&longitude=-58.3816"
```

---

### POST /weather/fetch

Obtiene datos meteorológicos para todas las zonas activas (operación batch).

**Query Parameters:**

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| target_date | string | No | Fecha en formato YYYY-MM-DD (default: fecha actual) |

**Response:** `200 OK`

```json
{
  "message": "Weather data fetched successfully",
  "target_date": "2025-01-20",
  "zones_processed": 15,
  "storage_results": {
    "postgresql": 15,
    "redis_cache": 15,
    "timescaledb": 15
  }
}
```

**Errores:**

| Código | Descripción |
|--------|-------------|
| 400 | Formato de fecha inválido |
| 500 | Error del servidor |

**Ejemplo cURL:**

```bash
curl -X POST "http://localhost:8000/api/v1/weather/fetch?target_date=2025-01-20"
```

---

### GET /weather/current

Obtiene el clima actual en tiempo real desde OpenWeatherMap.

**Query Parameters:**

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| latitude | float | Sí | Latitud de la ubicación |
| longitude | float | Sí | Longitud de la ubicación |

**Response:** `200 OK`

```json
{
  "success": true,
  "data": {
    "temperature": 25.3,
    "feels_like": 26.1,
    "humidity": 70,
    "pressure": 1015,
    "wind_speed": 5.2,
    "wind_direction": 220,
    "description": "nubes dispersas",
    "icon": "03d",
    "visibility": 10000,
    "clouds": 40
  },
  "source": "openweather",
  "cache_ttl_minutes": 15
}
```

**Ejemplo cURL:**

```bash
curl -X GET "http://localhost:8000/api/v1/weather/current?latitude=-34.6037&longitude=-58.3816"
```

---

### GET /weather/current/health

Verifica el estado del servicio de clima actual.

**Response:** `200 OK`

```json
{
  "status": "healthy",
  "message": "OpenWeatherMap API is accessible"
}
```

---

### GET /weather/history

Obtiene el historial de datos meteorológicos.

**Query Parameters:**

| Parámetro | Tipo | Requerido | Default | Descripción |
|-----------|------|-----------|---------|-------------|
| latitude | float | Sí | - | Latitud de la ubicación |
| longitude | float | Sí | - | Longitud de la ubicación |
| hours_back | int | No | 24 | Horas hacia atrás a consultar |

**Response:** `200 OK`

```json
{
  "count": 24,
  "start_time": "2025-01-19T14:30:00",
  "end_time": "2025-01-20T14:30:00",
  "data": [
    {
      "id": 12340,
      "timestamp": "2025-01-19T14:30:00Z",
      "latitude": -34.6037,
      "longitude": -58.3816,
      "temperature": 22.5,
      "humidity": 75.0,
      "precipitation": 0.0,
      "wind_speed": 8.5,
      "wind_direction": 150.0,
      "pressure": 1012.0,
      "soil_moisture": 0.40
    }
  ]
}
```

**Ejemplo cURL:**

```bash
curl -X GET "http://localhost:8000/api/v1/weather/history?latitude=-34.6037&longitude=-58.3816&hours_back=48"
```

---

## Upload (Ingesta)

### POST /upload/image

Sube una imagen de cultivo y crea un reporte inicial.

**Content-Type:** `multipart/form-data`

**Form Data:**

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| image_file | File | Sí | Archivo de imagen (JPEG o PNG, máx 10MB) |

**Response:** `200 OK`

```json
{
  "report_id": "550e8400-e29b-41d4-a716-446655440010",
  "image_identifier": "20250120_143000_abc12345.jpg",
  "status": "PENDING_ANALYSIS",
  "message": "Image uploaded and initial report created successfully."
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| report_id | UUID | ID del reporte creado |
| image_identifier | string | Identificador único de la imagen |
| status | string | Estado del reporte (PENDING_ANALYSIS) |
| message | string | Mensaje de confirmación |

**Errores:**

| Código | Descripción |
|--------|-------------|
| 413 | Imagen demasiado grande (> 10MB) |
| 415 | Tipo de archivo no soportado (solo JPEG/PNG) |
| 500 | Error de almacenamiento |

**Ejemplo cURL:**

```bash
curl -X POST "http://localhost:8000/api/v1/upload/image" \
  -F "image_file=@/path/to/crop_image.jpg"
```

---

## Chat (Agente)

### POST /chat

Envía un mensaje al agente agrícola y recibe una respuesta.

**Request Body:**

```json
{
  "message": "string",
  "context": {
    "region": "string | null",
    "crop": "string | null",
    "field_id": "string | null"
  }
}
```

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| message | string | Sí | Mensaje del usuario (1-4000 caracteres) |
| context | object | No | Contexto opcional para la conversación |
| context.region | string | No | Código de región (AR, MX, CO) |
| context.crop | string | No | Tipo de cultivo |
| context.field_id | string | No | ID del campo/lote |

**Response:** `200 OK`

```json
{
  "response": "Basándome en tu consulta sobre trips en tomate, te puedo indicar que estos insectos...",
  "sources": [
    {
      "id": "doc-123",
      "title": "Manejo Integrado de Trips en Solanáceas",
      "source": "INTA"
    }
  ],
  "metadata": {
    "search_performed": true,
    "documents_found": 3,
    "memory_turns": 2
  }
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| response | string | Respuesta del agente |
| sources | array | Fuentes consultadas |
| metadata.search_performed | boolean | Si se realizó búsqueda |
| metadata.documents_found | int | Documentos encontrados |
| metadata.memory_turns | int | Turnos de conversación en memoria |

**Errores:**

| Código | Descripción |
|--------|-------------|
| 500 | Error interno del agente |

**Ejemplo cURL:**

```bash
curl -X POST "http://localhost:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "¿Cómo puedo controlar los trips en mi cultivo de tomate?",
    "context": {
      "region": "AR",
      "crop": "tomate"
    }
  }'
```

---

### DELETE /chat/memory

Limpia la memoria de conversación de la sesión actual.

**Response:** `200 OK`

```json
{
  "message": "Conversation memory cleared successfully."
}
```

**Ejemplo cURL:**

```bash
curl -X DELETE "http://localhost:8000/api/v1/chat/memory"
```

---

### GET /chat/health

Verifica el estado del agente y sus dependencias.

**Response:** `200 OK`

```json
{
  "status": "healthy",
  "components": {
    "llm": {
      "status": "healthy",
      "model": "gemma:2b",
      "model_available": true
    },
    "search": {
      "status": "healthy",
      "stages": {
        "index_lookup": "operational",
        "document_search": "operational"
      }
    }
  }
}
```

---

## Reports (Acción)

### GET /reports

Lista todos los reportes con paginación.

**Query Parameters:**

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| skip | int | 0 | Registros a saltar |
| limit | int | 100 | Máximo de registros |

**Response:** `200 OK`

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440010",
    "title": "Análisis de cultivo - Lote Norte",
    "summary": "Planta de tomate con signos de deficiencia de nitrógeno",
    "recommendations": "Se recomienda aplicación foliar de urea...",
    "image_identifier": "20250120_143000_abc12345.jpg",
    "raw_analysis_data": {
      "affected_percentage": 25.5,
      "diagnosis": "..."
    },
    "analysis_id": null,
    "status": "ANALYSIS_COMPLETED",
    "created_at": "2025-01-20T14:30:00Z",
    "updated_at": "2025-01-20T15:00:00Z"
  }
]
```

**Ejemplo cURL:**

```bash
curl -X GET "http://localhost:8000/api/v1/reports?skip=0&limit=20"
```

---

### POST /reports

Crea un nuevo reporte.

**Request Body:**

```json
{
  "image_identifier": "string",
  "title": "string | null",
  "summary": "string | null",
  "recommendations": "string | null",
  "raw_analysis_data": "object | null",
  "analysis_id": "uuid | null",
  "status": "string"
}
```

| Campo | Tipo | Requerido | Default | Descripción |
|-------|------|-----------|---------|-------------|
| image_identifier | string | Sí | - | Identificador de la imagen |
| title | string | No | "Reporte Pendiente de Análisis" | Título del reporte |
| summary | string | No | null | Resumen del análisis |
| recommendations | string | No | null | Recomendaciones |
| raw_analysis_data | object | No | null | Datos crudos del análisis |
| status | string | No | "PENDING_ANALYSIS" | Estado del reporte |

**Response:** `201 Created`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440010",
  "title": "Reporte Pendiente de Análisis",
  "summary": null,
  "recommendations": null,
  "image_identifier": "20250120_143000_abc12345.jpg",
  "raw_analysis_data": null,
  "analysis_id": null,
  "status": "PENDING_ANALYSIS",
  "created_at": "2025-01-20T14:30:00Z",
  "updated_at": "2025-01-20T14:30:00Z"
}
```

**Ejemplo cURL:**

```bash
curl -X POST "http://localhost:8000/api/v1/reports" \
  -H "Content-Type: application/json" \
  -d '{
    "image_identifier": "20250120_143000_abc12345.jpg",
    "title": "Análisis Lote Norte"
  }'
```

---

### GET /reports/{report_id}

Obtiene un reporte específico por ID.

**Path Parameters:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| report_id | UUID | ID del reporte |

**Response:** `200 OK`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440010",
  "title": "Análisis de cultivo - Lote Norte",
  "summary": "Planta de tomate con signos de estrés hídrico",
  "recommendations": "Aumentar frecuencia de riego...",
  "image_identifier": "20250120_143000_abc12345.jpg",
  "raw_analysis_data": {
    "affected_percentage": 15.2,
    "diagnosis": {
      "diagnosis": "La planta muestra síntomas de estrés hídrico...",
      "severity": "medium",
      "recommendations": ["Riego", "Mulching"]
    }
  },
  "analysis_id": null,
  "status": "ANALYSIS_COMPLETED",
  "created_at": "2025-01-20T14:30:00Z",
  "updated_at": "2025-01-20T15:00:00Z"
}
```

**Errores:**

| Código | Descripción |
|--------|-------------|
| 404 | Reporte no encontrado |

**Ejemplo cURL:**

```bash
curl -X GET "http://localhost:8000/api/v1/reports/550e8400-e29b-41d4-a716-446655440010"
```

---

### PUT /reports/{report_id}

Actualiza un reporte existente.

**Path Parameters:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| report_id | UUID | ID del reporte |

**Request Body:**

```json
{
  "title": "string | null",
  "summary": "string | null",
  "recommendations": "string | null",
  "image_identifier": "string | null",
  "raw_analysis_data": "object | null",
  "analysis_id": "uuid | null",
  "status": "string | null"
}
```

Todos los campos son opcionales. Solo se actualizan los campos proporcionados.

**Response:** `200 OK`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440010",
  "title": "Análisis actualizado - Lote Norte",
  "summary": "Nuevo resumen actualizado",
  "recommendations": "Nuevas recomendaciones...",
  "image_identifier": "20250120_143000_abc12345.jpg",
  "raw_analysis_data": null,
  "analysis_id": null,
  "status": "REVIEWED",
  "created_at": "2025-01-20T14:30:00Z",
  "updated_at": "2025-01-20T16:00:00Z"
}
```

**Errores:**

| Código | Descripción |
|--------|-------------|
| 404 | Reporte no encontrado |

**Ejemplo cURL:**

```bash
curl -X PUT "http://localhost:8000/api/v1/reports/550e8400-e29b-41d4-a716-446655440010" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Análisis actualizado - Lote Norte",
    "status": "REVIEWED"
  }'
```

---

### DELETE /reports/{report_id}

Elimina un reporte.

**Path Parameters:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| report_id | UUID | ID del reporte |

**Response:** `204 No Content`

**Errores:**

| Código | Descripción |
|--------|-------------|
| 404 | Reporte no encontrado |

**Ejemplo cURL:**

```bash
curl -X DELETE "http://localhost:8000/api/v1/reports/550e8400-e29b-41d4-a716-446655440010"
```

---

## Alerts (Acción)

### GET /alerts

Lista alertas con filtros opcionales.

**Query Parameters:**

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| acknowledged | boolean | null | Filtrar por estado de reconocimiento |
| severity | string | null | Filtrar por severidad (low, medium, high, critical) |
| limit | int | 50 | Máximo de resultados |

**Response:** `200 OK`

```json
[
  {
    "id": "alert-123",
    "title": "Riesgo de helada",
    "message": "Se pronostica temperatura de 2°C para mañana a las 06:00",
    "severity": "high",
    "type": "weather",
    "created_at": "2025-01-20T18:00:00Z",
    "acknowledged": false,
    "acknowledged_at": null,
    "region": "AR",
    "field_id": null
  }
]
```

**Ejemplo cURL:**

```bash
curl -X GET "http://localhost:8000/api/v1/alerts?severity=high&acknowledged=false"
```

---

### POST /alerts

Crea una nueva alerta.

**Request Body:**

```json
{
  "title": "string",
  "message": "string",
  "severity": "string",
  "type": "string",
  "region": "string | null",
  "field_id": "string | null"
}
```

| Campo | Tipo | Requerido | Default | Descripción |
|-------|------|-----------|---------|-------------|
| title | string | Sí | - | Título de la alerta |
| message | string | Sí | - | Mensaje descriptivo |
| severity | string | No | "medium" | Severidad: low, medium, high, critical |
| type | string | Sí | - | Tipo: weather, pest, disease, nutrient, system |
| region | string | No | null | Código de región |
| field_id | string | No | null | ID del campo afectado |

**Response:** `201 Created`

```json
{
  "id": "alert-456",
  "title": "Detección de plaga",
  "message": "Se detectó presencia de trips en el lote norte",
  "severity": "medium",
  "type": "pest",
  "created_at": "2025-01-20T19:00:00Z",
  "acknowledged": false,
  "acknowledged_at": null,
  "region": "AR",
  "field_id": "field-001"
}
```

**Ejemplo cURL:**

```bash
curl -X POST "http://localhost:8000/api/v1/alerts" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Detección de plaga",
    "message": "Se detectó presencia de trips en el lote norte",
    "severity": "medium",
    "type": "pest",
    "region": "AR",
    "field_id": "field-001"
  }'
```

---

### GET /alerts/active

Obtiene todas las alertas no reconocidas (activas).

**Response:** `200 OK`

```json
[
  {
    "id": "alert-123",
    "title": "Riesgo de helada",
    "message": "Se pronostica temperatura de 2°C para mañana",
    "severity": "high",
    "type": "weather",
    "created_at": "2025-01-20T18:00:00Z",
    "acknowledged": false,
    "acknowledged_at": null,
    "region": "AR",
    "field_id": null
  }
]
```

**Ejemplo cURL:**

```bash
curl -X GET "http://localhost:8000/api/v1/alerts/active"
```

---

### GET /alerts/{alert_id}

Obtiene una alerta específica.

**Path Parameters:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| alert_id | string | ID de la alerta |

**Response:** `200 OK`

```json
{
  "id": "alert-123",
  "title": "Riesgo de helada",
  "message": "Se pronostica temperatura de 2°C para mañana a las 06:00",
  "severity": "high",
  "type": "weather",
  "created_at": "2025-01-20T18:00:00Z",
  "acknowledged": false,
  "acknowledged_at": null,
  "region": "AR",
  "field_id": null
}
```

**Errores:**

| Código | Descripción |
|--------|-------------|
| 404 | Alerta no encontrada |

---

### PUT /alerts/{alert_id}/acknowledge

Reconoce una alerta.

**Path Parameters:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| alert_id | string | ID de la alerta |

**Response:** `200 OK`

```json
{
  "id": "alert-123",
  "title": "Riesgo de helada",
  "message": "Se pronostica temperatura de 2°C para mañana a las 06:00",
  "severity": "high",
  "type": "weather",
  "created_at": "2025-01-20T18:00:00Z",
  "acknowledged": true,
  "acknowledged_at": "2025-01-20T19:30:00Z",
  "region": "AR",
  "field_id": null
}
```

**Errores:**

| Código | Descripción |
|--------|-------------|
| 404 | Alerta no encontrada |

**Ejemplo cURL:**

```bash
curl -X PUT "http://localhost:8000/api/v1/alerts/alert-123/acknowledge"
```

---

## Analysis (Acción)

### POST /analyze

Analiza una imagen de cultivo y actualiza el reporte asociado.

**Request Body:**

```json
{
  "report_id": "uuid",
  "image_identifier": "string"
}
```

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| report_id | UUID | Sí | ID del reporte a actualizar |
| image_identifier | string | Sí | Identificador de la imagen a analizar |

**Response:** `200 OK`

```json
{
  "status": "success",
  "report_id": "550e8400-e29b-41d4-a716-446655440010",
  "caption": "Planta de tomate con hojas amarillentas y manchas marrones en el follaje inferior",
  "diagnosis": "La planta presenta síntomas consistentes con deficiencia de nitrógeno y posible inicio de tizón temprano. El amarillamiento de las hojas inferiores junto con las manchas necróticas sugieren una combinación de factores nutricionales y patológicos.",
  "severity": "medium",
  "recommendations": [
    "Monitoreo frecuente recomendado",
    "Considerar tratamiento preventivo",
    "Documentar evolución"
  ],
  "metadata": {
    "affected_percentage": 25.5,
    "rules_triggered": 2
  }
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| status | string | Estado de la operación |
| report_id | string | ID del reporte actualizado |
| caption | string | Descripción generada de la imagen |
| diagnosis | string | Diagnóstico detallado del LLM |
| severity | string | Severidad: low, medium, high, critical |
| recommendations | array | Lista de recomendaciones |
| metadata.affected_percentage | float | Porcentaje de área afectada |
| metadata.rules_triggered | int | Reglas agrícolas activadas |

**Errores:**

| Código | Descripción |
|--------|-------------|
| 400 | Reporte o imagen no encontrados |
| 500 | Error durante el análisis |

**Ejemplo cURL:**

```bash
curl -X POST "http://localhost:8000/api/v1/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "report_id": "550e8400-e29b-41d4-a716-446655440010",
    "image_identifier": "20250120_143000_abc12345.jpg"
  }'
```

---

## Health

### GET /health

Endpoint de verificación de estado del servicio.

**Response:** `200 OK`

```json
{
  "status": "ok"
}
```

**Ejemplo cURL:**

```bash
curl -X GET "http://localhost:8000/health"
```

---

## Códigos de Error Comunes

| Código | Descripción |
|--------|-------------|
| 400 | Bad Request - Datos de entrada inválidos |
| 401 | Unauthorized - Token faltante o inválido |
| 403 | Forbidden - Sin permisos para el recurso |
| 404 | Not Found - Recurso no encontrado |
| 413 | Payload Too Large - Archivo demasiado grande |
| 415 | Unsupported Media Type - Tipo de archivo no soportado |
| 500 | Internal Server Error - Error del servidor |

## Formato de Error

Todos los errores siguen el siguiente formato:

```json
{
  "detail": "Descripción del error"
}
```

Para errores de análisis de cultivos:

```json
{
  "status": "error",
  "error": "Descripción del error",
  "error_code": "codigo_error"
}
```

---

## Autenticación

La mayoría de los endpoints requieren autenticación mediante token JWT.

**Header requerido:**

```
Authorization: Bearer <token>
```

El token se obtiene mediante el endpoint `/auth/login` o `/auth/signup`.

**Duración del token:** Configurable (default: 60 minutos)

---

## Rate Limiting

*No implementado actualmente. Se recomienda implementar en producción.*

---

## Versionado

La API utiliza versionado en la URL: `/api/v1/...`

Cambios futuros que rompan compatibilidad se implementarán en `/api/v2/...`
