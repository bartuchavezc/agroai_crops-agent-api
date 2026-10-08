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
| POST | `/auth/signup` | Crea cuenta + usuario `owner`. Desactivado salvo `ALLOW_PUBLIC_SIGNUP=true` |
| POST | `/auth/login` | Email sin distinguir mayúsculas. Los 401 repetidos por IP los banea fail2ban (`deploy/fail2ban`) |
| POST | `/auth/password` | Cambia la propia contraseña; invalida todos los tokens anteriores y devuelve uno nuevo |
| GET | `/auth/me` | `{user, account}` |
| GET / POST | `/auth/users` | Miembros de la cuenta / alta de `tecnico` o `staff` (solo owner) |
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
`ChatResponse.metadata.model` informa el modelo principal del turno.

## Farm management (acepta rutas con y sin `/` final)
| Método | Ruta | Permisos |
|---|---|---|
| GET | `/farm-management/overview` | Campos + ciclos activos + última actividad |
| GET / POST | `/farm-management/fields` | POST: owner/tecnico |
| GET / PUT / DELETE | `/farm-management/fields/{id}` | PUT/DELETE: owner/tecnico |
| GET / POST | `/farm-management/crop-masters?q=` | Catálogo global + de la cuenta |
| GET / DELETE | `/farm-management/crop-masters/{id}` | Solo se borran los de la cuenta |
| GET / POST | `/farm-management/fields/{id}/zones` | Zonas del campo (`cajon`, `cantero`, `invernadero`, `hidroponia`), numeradas por tipo: `{type, number?, name?, notes?, layout_object_id?}` → `label` "Cantero 3". POST: owner/tecnico; sin `number` toma el siguiente libre |
| PUT / DELETE | `/farm-management/zones/{id}` | owner/tecnico. Al borrar, sus ciclos quedan en el campo sin zona |
| GET / POST | `/farm-management/crop-cycles?field_id=&status=&zone_id=` | POST: owner/tecnico. `zone_id` opcional (de una zona del mismo campo) |
| GET / PUT / DELETE | `/farm-management/crop-cycles/{id}` | |
| GET / POST | `/farm-management/events?field_id=&type=&since=` | Cualquier rol registra eventos |
| PUT / DELETE | `/farm-management/events/{id}` | Autor u owner/tecnico |

Tipos de evento: `sowing, transplant, irrigation, fertilization, treatment, pruning, weeding, pest_sighting,
disease_sighting, harvest, observation, photo`. Estados de ciclo: `planned, planted, growing, harvested, failed`.

## Chat y conversaciones
| Método | Ruta | Notas |
|---|---|---|
| POST | `/chat` | `{message, conversation_id?, image_identifier?, context: {field_id?}, retry_message_id?}` → `{response, sources[], metadata{conversation_id, tool_calls[], search_performed, model}}` |
| POST | `/chat/stream` | Mismo body, SSE: `meta`, `tool_call`, `tool_result`, `delta`, `done`, `error`. El mensaje del usuario se guarda antes de responder; si el cliente se desconecta la respuesta sigue y se guarda igual |
| GET / POST | `/chat/conversations` | Las del usuario (privadas) |
| GET / PATCH / DELETE | `/chat/conversations/{id}` | PATCH: `{title?, archived?, field_id?}` |
| GET | `/chat/conversations/{id}/messages?limit=&before=` | Cada mensaje trae `status`: `complete`, `pending` (se está generando: volver a consultar) o `error` (+`error_code`; reintentar con `retry_message_id` = id del último mensaje del usuario) |
| POST | `/chat/conversations/{id}/stop` | Detiene la respuesta en curso; lo generado se conserva |
| DELETE | `/chat/memory?conversation_id=` | Deprecado |

## Memoria del agente (compartida por cuenta)
`GET /agent/memories`, `GET /agent/memories/search?q=`, `DELETE /agent/memories/{id}`

## Imágenes, reportes y diagnóstico
| Método | Ruta | Notas |
|---|---|---|
| POST | `/upload/image` | multipart `image_file`, opcional `field_id`, `crop_cycle_id` → `{report_id, image_identifier}` |
| POST | `/upload/zone-tracking` | Seguimiento diario de una zona: multipart `zone_id` + 1-4 `image_files` → un reporte `periodic` con `zone_id`, `crop_cycle_ids` (ciclos activos de la zona) e `image_identifiers`; se analiza en segundo plano (`raw_analysis_data.llm_structured_zone`: resumen + una evaluación por cultivo) |
| POST | `/analyze` | `{report_id, image_identifier?}` → diagnóstico estructurado (Gemini multimodal) |
| GET / POST | `/reports?field_id=&crop_cycle_id=&zone_id=&report_type=` | `crop_cycle_id` incluye los seguimientos de zona que cubrieron ese ciclo |
| GET / PUT / DELETE | `/reports/{id}` | `raw_analysis_data.llm_structured_diagnosis` |

## Planificación y recordatorios
Recordatorios: cualquier rol crea y marca hechos; planes, etapas y siembras: owner/tecnico. Un recordatorio vencido
llega como notificación in-app (`type: "reminder"`, `entity_type: "reminder"`) cuando corre
`python -m src.batch reminders` (servicio `reminders` del compose, cada 5 min); con `assigned_to` solo le llega a
ese integrante, si no a toda la cuenta.

| Método | Ruta | Notas |
|---|---|---|
| GET / POST | `/planning/reminders?status=&since=&until=&field_id=&crop_cycle_id=&plan_id=&assigned_to=` | `{title, due_at, description?, recurrence: none\|daily\|weekly\|every_n_days, interval_days?, until?, assigned_to?, field_id?, zone_id?, crop_cycle_id?, plan_id?}`. `assigned_to=<id>` = los suyos + los sin asignar; `none` = sin asignar |
| PUT / DELETE | `/planning/reminders/{id}` | PUT parcial (posponer = cambiar `due_at`). DELETE: manager o quien lo creó |
| POST | `/planning/reminders/{id}/complete` | Uno recurrente pasa a su próxima ocurrencia (y termina después de `until`) |
| GET / POST | `/planning/plans?field_id=&status=` | `{name, kind: ciclo\|largo, field_id?, zone_id?, start_date?, end_date?, notes?, stages[], sowings[]}`; cada siembra crea su recordatorio |
| GET / PUT / DELETE | `/planning/plans/{id}` | GET con `stages`, `sowings`, `reminders`. Archivar o borrar cancela los recordatorios pendientes |
| POST | `/planning/plans/{id}/stages` | `{name, stage, start_date, end_date?, remind?}` — `PUT/DELETE /planning/stages/{id}` |
| POST | `/planning/plans/{id}/sowings` | `{crop_master_id, sow_date, zone_id?, quantity?, unit?, seed_lot_id?}` — `PUT/DELETE /planning/sowings/{id}` |
| POST | `/planning/plans/{id}/sowings/staggered` | Siembra escalonada: `{crop_master_id, start_date, count, every_days, total_quantity?, unit?, zone_id?, seed_lot_id?}` divide la cantidad en partes iguales |
| POST | `/planning/sowings/{id}/sow` | Siembra hecha: `{sown_on?, create_crop_cycle=true, consume_seed_lot=true}` arranca el ciclo (con su plan por etapas) y descuenta el lote |
| GET / POST | `/planning/crop-cycles/{id}/stage-plan` | GET: propuesta de etapas + recordatorios del ciclo según la plantilla del cultivo (germinación, traspaso, etapas clave, posible cosecha, cosecha estimada). POST: la guarda (regenerar reemplaza lo generado; los hechos quedan) |

## Alertas
`GET /alerts?acknowledged=&severity=&field_id=`, `POST /alerts`, `GET /alerts/active`, `GET/DELETE /alerts/{id}`,
`PUT /alerts/{id}/acknowledge`. Las alertas del pronóstico tienen `source: "smn"` y `rule_id`.

## Satélite (Copernicus)
| Método | Ruta | Notas |
|---|---|---|
| GET | `/satellite/fields/{id}/status` | Última pasada sin nubes + `analysis` (cada índice vs lo normal de esa semana y vs el año pasado, tendencia, etapa de la curva, señal de radar, advertencias) + alertas. Actualiza la serie desde Copernicus solo si tiene más de 12 h y hay cupo on-demand |
| GET | `/satellite/fields/{id}/series?metric=ndvi&since=` | Serie guardada (sin llamar a Copernicus): tabla semanal (crudo, suavizado, normal p10/p50/p90, año pasado), pasadas y radar. `metric`: ndvi, ndre, ndmi, evi, ndwi |
| POST | `/satellite/fields/{id}/sync` | Fuerza la actualización de la serie (respeta el cupo mensual) |
| GET / POST | `/satellite/fields/{id}/image`, `/render-map` | Mapa NDVI coloreado (cacheado / regenerar) |
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
