# API v1

Base: `/api/v1`. Todo requiere `Authorization: Bearer <token>` salvo login/signup y `/health`.
Los errores de dominio responden `{"detail": "...", "error_code": "..."}`.

| error_code | HTTP | Qué hacer en el cliente |
|---|---|---|
| `PROVIDER_KEY_MISSING` | 409 | Pedir al usuario su API key de Gemini |
| `PROVIDER_KEY_INVALID` | 409 | La key fue rechazada: pedir una nueva |
| `PROVIDER_QUOTA_EXCEEDED` | 429 | Cuota del free tier agotada: reintentar más tarde |
| `permission_denied` | 403 | El rol no permite la operación |
| `not_found` | 404 | No existe o es de otra cuenta |

## Auth y cuenta
| Método | Ruta | Notas |
|---|---|---|
| POST | `/auth/signup` | Crea cuenta + usuario `owner`. Desactivado salvo `ALLOW_PUBLIC_SIGNUP=true`. Acepta `country` (`AR` por defecto, `MX`), `timezone` (IANA; el cliente debe mandar `Intl.DateTimeFormat().resolvedOptions().timeZone`) y `locale` (`es-AR`, `es-MX`): si faltan se completan según el país |
| POST | `/auth/login` | Email sin distinguir mayúsculas. Los 401 repetidos por IP los banea fail2ban (`deploy/fail2ban`) |
| POST | `/auth/password` | Cambia la propia contraseña; invalida todos los tokens anteriores y devuelve uno nuevo |
| GET | `/auth/me` | `{user, account}`; `user` incluye `country`, `timezone` y `locale` |
| PATCH | `/auth/me` | `{country?: AR\|MX\|CO, timezone?, locale?}`: dónde está la persona. Define la voz del agente (voseo argentino / tuteo mexicano o colombiano), el hemisferio, las autoridades de referencia y la hora local. Cambiar solo el país lleva zona horaria y locale a los de ese país |
| GET / POST | `/auth/users` | Miembros de la cuenta / alta de `tecnico` o `staff` (solo owner). Si el alta no manda `country`, el miembro hereda país, zona horaria y locale del owner |
| GET | `/auth/users/{id}` | Solo misma cuenta |
| PATCH | `/auth/users/{id}/role` | Solo owner |
| DELETE | `/auth/users/{id}` | Solo owner: da de baja al miembro (no puede loguearse, sus tokens dejan de valer) |
| POST | `/auth/enroll` | Cuestionario q1..q10 → perfil del agente |
| GET | `/auth/profile`, `/auth/profile/context` | |

## BYOK
| Método | Ruta | Notas |
|---|---|---|
| GET | `/me/provider-credentials/gemini` | `{configured, key_last4, last_validated_at}` |
| PUT | `/me/provider-credentials/gemini` | `{api_key}`; se valida contra Gemini y se guarda cifrada |
| DELETE | `/me/provider-credentials/gemini` | |

Modelos (con la key de cada usuario): el ida y vuelta del chat usa la cadena **chat**
(`GEMINI_CHAT_MODEL`, por defecto `gemini-3.5-flash-lite`, + `GEMINI_CHAT_FALLBACK_MODELS`). La cadena de
**análisis** (`GEMINI_MODEL` + `GEMINI_FALLBACK_MODELS`) se usa para los análisis con foto (diagnóstico,
seguimiento por cultivo y por zona, suelo, cosecha), el plano y la imagen satelital, los turnos de chat que
traen foto, y la herramienta `expert_field_analysis` del agente (lectura de clima/suelo/satelital/riego/solar).
`ChatResponse.metadata.model` informa el modelo principal del turno. `metadata.usage` (opcional) trae los tokens del turno sumados sobre todas sus llamadas al modelo: `{llm_calls, prompt_tokens, cached_tokens, output_tokens, thinking_tokens}`; falta si el proveedor no informó uso.

## Farm management (acepta rutas con y sin `/` final)
| Método | Ruta | Permisos |
|---|---|---|
| GET | `/farm-management/overview` | Campos + ciclos activos + última actividad |
| GET / POST | `/farm-management/fields` | POST: owner/tecnico |
| GET / PUT / DELETE | `/farm-management/fields/{id}` | PUT/DELETE: owner/tecnico |
| GET / POST | `/farm-management/crop-masters?q=` | Catálogo global + de la cuenta. `q` también busca por los nombres de otros países (`i18n`: `{"es-MX": "Jitomate"}`, `variety_i18n`); `name`/`variety` siguen siendo el valor neutro y el respaldo |
| GET / DELETE | `/farm-management/crop-masters/{id}` | Solo se borran los de la cuenta |
| GET / POST | `/farm-management/fields/{id}/zones` | Zonas del campo (`cajon`, `cantero`, `invernadero`, `hidroponia`): `{type, number?, name?, notes?, layout_object_id?, length_m?, width_m?, soil?}` → `label` "Cantero 3", `area_m2`. El número es del usuario y se puede cambiar; sin `number` toma el siguiente libre. `soil` `{nitrogen, potassium, carbon, ph, notes, updated_at}` pisa el suelo del campo (sustrato, compost). POST: owner/tecnico |
| POST | `/farm-management/fields/{id}/zones/renumber` | `{numbers: {zone_id: número}}`: renumera varias zonas a la vez (p. ej. intercambiar 4 y 1); solo la numeración final tiene que ser única por tipo. owner/tecnico |
| PUT / DELETE | `/farm-management/zones/{id}` | owner/tecnico. Al borrar, sus lotes quedan en el campo sin esa zona |
| GET / POST | `/farm-management/lots?field_id=&status=&zone_id=` | Lotes: una tanda de un cultivo sembrada junta. `{field_id, crop_master_id, zone_ids[] (o zone_id), season? "26/27", number?, planting_date?, transplant_date?, quantity?, unit?, status, plan_id?, origin_lot_id?}`; `status` planned\|seedbed\|planted\|growing\|harvesting\|harvested\|failed. La lectura suma `zone_id` (la primera zona) y `label` "T26/27 · Cantero 2 · L2". POST: owner/tecnico |
| GET / PUT / DELETE | `/farm-management/lots/{id}` | |
| GET / POST | `/farm-management/events?field_id=&zone_id=&lot_id=&type=&since=&until=&before=&limit=` | La bitácora: cualquier rol registra. `{field_id, zone_id?, lot_ids[]? (o lot_id), type, occurred_at?, quantity?, unit?, notes?}`; en una zona alcanza a todos los lotes que crecen ahí, sin zona ni lotes a todo el campo. La lectura trae `lot_ids` (los lotes alcanzados, fijados al registrar). `type`: irrigation, fertilization, pest_control, sowing, transplant, harvest, inspection, observation, soil_prep, amendment, pruning, weeding, photo. Productos y dosis van como texto en `notes`. `lot_id` filtra todo lo que alcanzó al lote; `before` pagina hacia atrás |
| PUT / DELETE | `/farm-management/events/{id}` | Autor u owner/tecnico |
| GET | `/farm-management/log?field_id=\|zone_id=\|lot_id=&type=&since=&before=&limit=` | La bitácora por día de un campo, una zona o un lote (uno solo): `{days: [{date, items: [{kind: event\|analysis\|task, at, title, detail, type, quantity, unit, zone_id, lot_ids, source, image_identifier, data}]}], next_before}`. La de un lote incluye lo registrado en su zona o en todo el campo mientras estaba, y los análisis que lo cubrieron |

Tipos de evento: `sowing, transplant, irrigation, fertilization, treatment, pruning, weeding, pest_sighting,
disease_sighting, harvest, observation, photo`. Estados de ciclo: `planned, planted, growing, harvested, failed`.

## Chat y conversaciones
| Método | Ruta | Notas |
|---|---|---|
| POST | `/chat` | `{message, conversation_id?, image_identifier?, context: {field_id?}, retry_message_id?}` → `{response, sources[], metadata{conversation_id, tool_calls[], search_performed, model, usage?}}` |
| POST | `/chat/stream` | Mismo body, SSE: `meta`, `tool_call`, `tool_result`, `delta`, `done`, `error`. El mensaje del usuario se guarda antes de responder; si el cliente se desconecta la respuesta sigue y se guarda igual |
| GET / POST | `/chat/conversations` | Las del usuario (privadas) |
| GET / PATCH / DELETE | `/chat/conversations/{id}` | PATCH: `{title?, archived?, field_id?}` |
| GET | `/chat/conversations/{id}/messages?limit=&before=` | Cada mensaje trae `status`: `complete`, `pending` (se está generando: volver a consultar) o `error` (+`error_code`; reintentar con `retry_message_id` = id del último mensaje del usuario) |
| POST | `/chat/conversations/{id}/stop` | Detiene la respuesta en curso; lo generado se conserva |
| DELETE | `/chat/memory?conversation_id=` | Deprecado |
| GET | `/chat/proposals/{id}` | Propuesta de cambios que armó el agente (`propose_changes`, llega como adjunto `{type: "proposal", proposal_id}`): `{id, title, status: pending\|applied\|rejected\|failed, operations[], preview[], result?}`. Nada se escribe hasta confirmar |
| POST | `/chat/proposals/{id}/apply` | `{excluded: [índices]}` (los ítems destildados). Aplica en orden; deja una nota en la conversación para el siguiente turno. 400 si ya se decidió |
| POST | `/chat/proposals/{id}/reject` | La descarta (también deja la nota) |

## Cambios en lote
Varias escrituras de una vez, por los mismos servicios que las rutas individuales (mismos permisos). Operación:
`{op: create|update|delete, entity: zone|lot|event|seed_lot|task|reminder|plan|plan_crop|stage, id?, data}`; en `data`
`"$N"` es el id que creó la operación N. Si una falla, se borra lo que el conjunto creó y el resto se saltea; los
cambios a registros existentes hechos antes del error quedan (no es una transacción única).

| Método | Ruta | Notas |
|---|---|---|
| POST | `/changes/preview` | `{operations[]}` → `{ok, items[{index, title, before?, after?, error?}]}`. No escribe |
| POST | `/changes` | `{operations[], excluded?[]}` → `{applied, failed, undone, items[{index, op, entity, ok, id?, error?, skipped, undone}]}` |

## Memoria del agente (compartida por cuenta)
`GET /agent/memories`, `GET /agent/memories/search?q=`, `DELETE /agent/memories/{id}`

## Imágenes, reportes y diagnóstico
| Método | Ruta | Notas |
|---|---|---|
| POST | `/upload/image` | multipart `image_file`, opcional `field_id`, `lot_id` → `{report_id, image_identifier}` |
| POST | `/upload/zone-tracking` | Seguimiento diario de una zona: multipart `zone_id` + 1-4 `image_files` → un reporte `periodic` con `zone_id`, `lot_ids` (ciclos activos de la zona) e `image_identifiers`; se analiza en segundo plano (`raw_analysis_data.llm_structured_zone`: resumen + una evaluación por cultivo) |
| POST | `/analyze` | `{report_id, image_identifier?, deep?}` → diagnóstico estructurado (Gemini multimodal). El análisis recibe fisiología vegetal, la ficha y la guía de plagas de cada cultivo del lote, NDVI/NDWI históricos, clima de 30 días, suelo y registros previos. `deep` (por defecto `ANALYSIS_DEEP`, activo) agrega una segunda pasada que busca fuentes en la web (Tavily) y refina el análisis; las fuentes quedan en `raw_analysis_data.research` y el diagnóstico las cita en `additional_notes`. Los análisis de suelo no usan `deep` |
| GET / POST | `/reports?field_id=&lot_id=&zone_id=&report_type=&since=&until=` | `lot_id` incluye los seguimientos de zona que cubrieron ese ciclo |
| GET / PUT / DELETE | `/reports/{id}` | `raw_analysis_data.llm_structured_diagnosis` |

## Planificación y recordatorios
Un recordatorio es un aviso, nunca se «completa»: cualquier rol los crea; planes, etapas y siembras: owner/tecnico.
Cuando vence llega como notificación in-app (`type: "reminder"`, `entity_type: "reminder"`, con `zone_id`/`lot_id`)
al correr `python -m src.batch reminders` (servicio `reminders` del compose, cada 5 min); con `assigned_to` solo le
llega a ese integrante, si no a toda la cuenta. `status`: `activo` (avisa), `pausado`, `terminado` (uno solo ya
enviado o una serie pasada su `until`). Lo que el usuario ve y descarta es la notificación
(`DELETE /notifications/{id}`, `POST /notifications/clear?read_only=`). El trabajo con responsable y estado son las
tareas (`/tasks`).

| Método | Ruta | Notas |
|---|---|---|
| GET / POST | `/planning/reminders?status=&since=&until=&field_id=&zone_id=&lot_id=&plan_id=&assigned_to=&before=` | `{title, due_at, description?, recurrence: none\|daily\|weekly\|every_n_days, interval_days?, until?, assigned_to?, field_id?, zone_id?, lot_id?, plan_id?}`. `assigned_to=<id>` = los suyos + los sin asignar; `none` = sin asignar |
| PUT / DELETE | `/planning/reminders/{id}` | PUT parcial: reprogramar (`due_at`, vuelve a avisar), pausar/reactivar (`status`), cambiar texto o recurrencia. DELETE: manager o quien lo creó |
| GET / POST | `/tasks?field_id=&zone_id=&lot_id=&plan_id=&status=&open_only=&assigned_to=` | Tareas: `{title, description?, field_id?, zone_id?, lot_id?, plan_id?, due_date?, assigned_to?, status: pendiente\|en_curso\|bloqueada\|hecha\|cancelada, result_event_type?}`. `zone_id` trae también las de sus lotes. Cualquier rol crea y actualiza |
| GET / PUT / DELETE | `/tasks/{id}` | Pasar a `hecha` con `result_event_type` lo registra en la bitácora (zona o lote); un `transplant` o `sowing` además avanza el lote. Las hechas aparecen en `/farm-management/log`. DELETE: owner/tecnico |
| GET | `/planning/calendar?since=&until=&field_id=` | Fechas locales inclusivas, hasta 400 días. `items`: recordatorios con sus recurrencias expandidas (desde la ocurrencia actual: las anteriores no se guardaron), siembras planificadas y etapas en su día de inicio; `ranges`: las etapas de planes activos como tramos |
| GET | `/planning/lots/{id}/progress` | `expected_pct`, `current_stage`, `next_stage_at` (según el plan del ciclo o la plantilla del cultivo) y `status` ok\|late\|affected\|unknown con `reason` y `evidence_report_id` (último análisis completado que cubrió el ciclo) |
| GET / POST | `/planning/plans?field_id=&status=` | `{name, kind: ciclo\|largo, field_id?, zone_ids[]?, objectives?, start_date?, end_date?, notes?, stages[], crops[]}`. Un plan general (`largo`) es la intención («Plan Cantero 1: hoja y raíz fina»): objetivos, zonas, etapas y cultivos; `ciclo` es el plan por etapas de un lote |
| GET / PUT / DELETE | `/planning/plans/{id}` | GET con `zone_ids`, `stages`, `crops`, `lots` (los que planificó o sembró), `tasks` y `reminders`. Archivar o borrar termina sus recordatorios activos y cancela sus tareas abiertas |
| POST | `/planning/plans/{id}/stages` | `{name, stage, start_date, end_date?, remind?}` — `PUT/DELETE /planning/stages/{id}` |
| POST | `/planning/plans/{id}/crops` | Un cultivo del plan: `{crop_master_id, mode: single\|staggered\|perennial, start_date, count?, every_days?, quantity? (por siembra), unit?, zone_ids[]? (por defecto las del plan), seed_lot_id?}`. Cada siembra queda como lote `planned` con su tarea «Sembrar» en la fecha. `DELETE /planning/plan-crops/{id}` lo quita con sus lotes aún planificados |
| POST | `/planning/lots/{id}/sow` | Un lote planificado se sembró: `{sown_on?, consume_seed_lot=true}` lo planta, registra la siembra en la bitácora, descuenta el lote de semillas, cierra su tarea y genera su plan por etapas. Marcar hecha su tarea «Sembrar» hace lo mismo |
| GET / POST | `/planning/lots/{id}/stage-plan` | GET: propuesta de etapas + recordatorios del ciclo según la plantilla del cultivo (germinación, traspaso, etapas clave, posible cosecha, cosecha estimada). POST: la guarda (regenerar reemplaza lo generado; los hechos quedan) |

## Alertas
`GET /alerts?acknowledged=&severity=&field_id=`, `POST /alerts`, `GET /alerts/active`, `GET/DELETE /alerts/{id}`,
`PUT /alerts/{id}/acknowledge`. Las alertas del pronóstico tienen `source: "smn"` y `rule_id`.

## Satélite (Copernicus)
| Método | Ruta | Notas |
|---|---|---|
| GET | `/satellite/fields/{id}/status?refresh=` | `refresh=false`: lectura pura (sin llamar a Copernicus ni escribir alertas). Trae `previous_ndvi_mean`, `previous_date`, `ndvi_delta` y `min_valid_fraction`. Última pasada sin nubes + `analysis` (cada índice vs lo normal de esa semana y vs el año pasado, tendencia, etapa de la curva, señal de radar, advertencias) + alertas. Actualiza la serie desde Copernicus solo si tiene más de 12 h y hay cupo on-demand |
| GET | `/satellite/fields/{id}/series?metric=ndvi&metrics=&since=&until=` | Serie guardada (sin llamar a Copernicus): tabla semanal (crudo, suavizado, normal p10/p50/p90, año pasado), pasadas y radar. `metrics=ndvi,ndmi` devuelve `weekly_by_metric` (y `weekly` es la primera). Cada pasada de `passes` trae `discarded` y `discard_reason` (`clouds`\|`shadow`\|`nodata`; `unknown` en pasadas guardadas antes de registrar la causa). `until` solo recorta la salida; `include_masked=true` suma las fechas totalmente nubladas (sin valores) |
| POST | `/satellite/fields/{id}/sync` | Fuerza la actualización de la serie (respeta el cupo mensual) |
| GET / POST | `/satellite/fields/{id}/image?layer=&date=&window_days=`, `/render-map` | Mapa de vigor **dibujado con los píxeles que guardamos** (no llama a Copernicus). `layer`: `ndvi` (por defecto), `ndmi`, `ndwi`, `rgb`. Por defecto es la **mediana píxel a píxel** de las pasadas de los últimos `window_days` (15, hasta 45) hasta la última que tenemos, usando solo los píxeles que cada pasada vio limpios: una nube en una pasada se completa con otra, y lo que ninguna vio limpio queda transparente. Con `date`, esa pasada sola (404 si no guardamos su imagen). Devuelve `{image_identifier, bbox, layer, date, window_days, coverage, passes_used}`; sin imágenes guardadas todavía, `image_identifier` es null. `POST /render-map` la redibuja (también local) |
| GET | `/satellite/fields/{id}/boundary-base-image` | Imagen color real para dibujar el borde del campo |

## Clima
| Método | Ruta | Notas |
|---|---|---|
| GET | `/weather/current?latitude=&longitude=` | OpenWeather, cache 15 min |
| GET | `/weather/latest`, `/weather/history?hours_back=` | Observaciones guardadas |
| GET | `/weather/forecast?latitude=&longitude=&days=` | Pronóstico SMN: `daily[]` + `hourly[]` |
| GET | `/weather/current/health` | |

## Admin de plataforma (panel `agroai_admin`)
Solo para los emails de `PLATFORM_ADMIN_EMAILS` (sin distinguir mayúsculas); cualquier otro usuario recibe 404.
Se loguea con `/auth/login` como cualquier usuario. Solo agregados y metadata: nunca el texto de los chats, las
fotos, la memoria del agente ni las keys.

| Método | Ruta | Notas |
|---|---|---|
| GET | `/admin/me` | Identidad del admin (sirve para validar el acceso) |
| GET | `/admin/overview?days=30` | KPIs: usuarios (roles, estado, onboarding, DAU/WAU/MAU, BYOK), cuentas, perfiles, fotos y diagnósticos, conversaciones, sesiones de uso, agente (tools), huertas (superficie, ciclos, cultivos, eventos), alertas, adopción por módulo y salud del sistema |
| GET | `/admin/timeseries?days=30` | Serie diaria (zona `APP_TIMEZONE`): altas, usuarios activos, mensajes, conversaciones, sesiones, fotos, eventos |
| GET | `/admin/users` | Cada usuario con cuenta, rol, estado, última actividad y contadores de uso |
| GET | `/admin/accounts` | Cada cuenta con miembros por rol, campos, superficie, ciclos, fotos, chats y última actividad |

Definiciones: **actividad** = mensaje al agente, foto subida o evento cargado a mano. **Sesión** = mensajes de un
usuario (y respuestas del agente) separados por menos de 30 min; su largo va del primer mensaje a la última
respuesta. **Foto** = cada `POST /upload/image` (crea un reporte) + las fotos del plano de cada campo.

## Suelo de la zona (`field.soil_context`)

Además de los datos de INTA (Argentina), `soil_context.soilgrids` trae la estimación de ISRIC SoilGrids por profundidad
(0-5, 5-15 y 15-30 cm): pH, carbono orgánico (g/kg), nitrógeno (g/kg) y CEC (cmol(c)/kg), con `resolution_m` y, si el
píxel del campo no tiene dato (urbano o agua), `distance_km` al píxel válido más cercano usado en su lugar. Es una
estimación regional de ~1 km, no un análisis de laboratorio.

Los datos salen de las tablas `soilgrids_grids` y `soilgrids_tiles` de la propia base (sin llamadas externas). Fuera de
las grillas cargadas no hay estimación. Hay que importar los rasters en cada ambiente después de migrar:

    uv run python -m src.scripts.import_soilgrids --dir raw_data/downloads/soilgrids [--depths ...] [--regions ...]

## Rediseño del front: lo que se agregó

Todo es aditivo: parámetros y campos opcionales; un cliente que no los usa no nota diferencia.

| Método | Ruta | |
|---|---|---|
| GET | `/farm-management/fields/{id}/summary` | El inicio del campo en una llamada: `status` (ok\|attention\|alert\|unknown) y `status_reasons`, `zones` (con sus cultivos activos y `last_analysis`: resumen, salud, foto), `unzoned_cycles`, `alerts` activas, `reminders_today` (pendientes hasta el fin del día local, vencidos incluidos) e `irrigation` (null si no hay coordenadas o no hay datos del clima) |
| GET | `/farm-management/fields/{id}/snapshot?season=` | El estado actual del campo (la tarjeta «Estado actual» y la herramienta `get_farm_snapshot`): `zones` (con `lots` activos, `ph` propio o del campo y `last_entry` de la bitácora), `unzoned_lots`, `lots_by_status` (todos los lotes), `recent_log`, `next_tasks` (abiertas por fecha) y `open_tasks`, `reminders_today`, `ph` del campo y `last_analysis` |
| GET | `/farm-management/zones/{id}` | La zona |
| GET | `/irrigation/fields/{id}/recommendation` | Ahora con `suggested_mm` y `next_irrigation_date` (también por cultivo): el día en que el balance hídrico supera el umbral de déficit, con el pronóstico de lluvia (`null` si no hace falta en 7 días) |
| GET / PATCH | `/alerts/fields/{id}/alert-rules[/{rule_id}]` | Cada regla con `enabled`, `threshold` vigente, `default_threshold`, rango y unidad. PATCH (owner/tecnico): `{enabled?}` o `{threshold?}` (`null` vuelve al valor por defecto). Los jobs, el análisis y el agente lo respetan |
| GET | `/management/budget/categories` | Categorías sugeridas con clave estable y etiqueta en el idioma de la persona. Un texto que coincide con una clave o etiqueta se guarda como la clave |
| GET | `/management/budget/summary?cycle_id=&crop_master_id=` | Con `cycle_id`: `cost_per_plant`, `break_even_kg`, `expected_revenue` y `margin` (null si faltan `plant_count`, `expected_yield_kg` o `expected_price` del ciclo). Los totales van en la moneda de la cuenta (`currency`); lo cargado en otra va aparte en `other_currencies` |
| GET | `/upload/image/{id}?max_side=320` | Miniatura JPEG (32 a 1536 px), generada una vez y guardada junto al original |

Datos nuevos: `lots.plant_count`, `expected_yield_kg`, `expected_price` (por kg); `accounts.currency`
(según el país del owner: ARS, MXN, COP) y `budget_entries.currency` (opcional); país `CO`.

Textos del back: los que genera el sistema (alertas, recordatorios, notificaciones) están en español neutro (sin
voseo); donde el vocabulario difiere por país (por ejemplo almácigo/semillero) se adapta al crear el texto, y los
nombres de cultivo salen en el idioma de la persona. Los textos ya guardados no se reescriben.
