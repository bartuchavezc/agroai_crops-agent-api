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

## Farm management (acepta rutas con y sin `/` final)
| Método | Ruta | Permisos |
|---|---|---|
| GET | `/farm-management/overview` | Campos + ciclos activos + última actividad |
| GET / POST | `/farm-management/fields` | POST: owner/tecnico |
| GET / PUT / DELETE | `/farm-management/fields/{id}` | PUT/DELETE: owner/tecnico |
| GET / POST | `/farm-management/crop-masters?q=` | Catálogo global + de la cuenta |
| GET / DELETE | `/farm-management/crop-masters/{id}` | Solo se borran los de la cuenta |
| GET / POST | `/farm-management/crop-cycles?field_id=&status=` | POST: owner/tecnico |
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
| POST | `/analyze` | `{report_id, image_identifier?}` → diagnóstico estructurado (Gemini multimodal) |
| GET / POST | `/reports?field_id=` | |
| GET / PUT / DELETE | `/reports/{id}` | `raw_analysis_data.llm_structured_diagnosis` |

## Alertas
`GET /alerts?acknowledged=&severity=&field_id=`, `POST /alerts`, `GET /alerts/active`, `GET/DELETE /alerts/{id}`,
`PUT /alerts/{id}/acknowledge`. Las alertas del pronóstico tienen `source: "smn"` y `rule_id`.

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
