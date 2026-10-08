# Nombre común — *Nombre científico* (Familia)

<!--
Plantilla de ficha técnica por cultivo. Copiar como `<cultivo>.md` (slug sin tildes, igual que la clave de
`src/application/planning/stage_templates.py::TEMPLATES`, por ejemplo `frutilla.md`) y completar cada tabla.
La primera línea tiene que respetar el formato `# Nombre — *Científico* (Familia)`: de ahí sale la descripción
del skill en `src/agent/prompts/knowledge_skills.py`. Los archivos que empiezan con "_" no se cargan como skill.

Fuentes de datos tabulados usadas en las fichas existentes:
- Composición nutricional: USDA SR Legacy (por 100 g crudo).
- Clima y suelo (temperaturas, pH, textura, profundidad, luz, lluvia, ciclo): FAO ECOCROP.
- Kc inicial / medio / final: FAO-56, Tabla 12.
- Salinidad: Maas & Hoffman (1977) / FAO-29.
Lo específico de Argentina (variedades, zonas, plagas y manejo) sale de INTA, MAGyP, INASE, SENASA,
universidades nacionales (UNLu, UNLP, UNCuyo, FAUBA, UNNE) y otras fuentes técnicas; citarlas al final.
-->

> Ficha técnica de cultivo. Pensada para huerta familiar y producción hortícola en Argentina (zona templada y cinturones verdes, salvo que se indique otra cosa). Los valores son orientativos: hay que ajustarlos a la zona, la variedad y el sistema (a campo o bajo cubierta). Para fitosanitarios, usar solo productos registrados por SENASA para el cultivo y respetar el período de carencia del marbete.

## 1. Identificación

| Campo | Dato |
|---|---|
| Nombre común | |
| Nombre científico | |
| Familia | |
| Hábito y ciclo | (anual, bianual o perenne; determinado o indeterminado; enano o trepador) |
| Parte comestible | |
| Origen | |
| Catálogo de la app | (ciclo en días, época de siembra y de cosecha según `GLOBAL_CROPS`) |

## 2. Variedades y tipos

| Variedad / tipo | Características | Uso / zona en Argentina |
|---|---|---|
| | | |

## 3. Composición nutricional

Por 100 g de parte comestible cruda. Fuente: USDA SR Legacy, NDB ...

| Componente | Valor |
|---|---|
| Agua | g |
| Energía | kcal |
| Proteína | g |
| Grasas totales | g |
| Carbohidratos | g |
| Fibra dietaria | g |
| Azúcares totales | g |
| Calcio | mg |
| Hierro | mg |
| Magnesio | mg |
| Fósforo | mg |
| Potasio | mg |
| Sodio | mg |
| Zinc | mg |
| Vitamina C | mg |
| Folatos | µg DFE |
| Vitamina A | µg RAE |
| β-caroteno | µg |
| Luteína + zeaxantina | µg |
| Vitamina E | mg |
| Vitamina K | µg |

(Una o dos líneas con lo que destaca nutricionalmente.)

## 4. Clima

| Parámetro | Valor |
|---|---|
| Temperatura mínima de crecimiento (ECOCROP) | °C |
| Rango óptimo de crecimiento (ECOCROP) | °C |
| Temperatura máxima de crecimiento (ECOCROP) | °C |
| Temperatura letal (ECOCROP) | °C (solo si ECOCROP la informa) |
| Luz (ECOCROP) | |
| Lluvia anual óptima, en secano (ECOCROP) | mm |
| Duración del ciclo (ECOCROP, rango mundial) | días |
| Germinación | (temperatura mínima y óptima, días a emergencia) |
| Heladas | |
| Fotoperíodo | |
| Calor | (qué pasa por encima del óptimo) |

## 5. Suelo

| Parámetro | Valor |
|---|---|
| pH óptimo (ECOCROP) | |
| pH tolerado (ECOCROP, extremos) | |
| Textura preferida (ECOCROP) | |
| Profundidad efectiva requerida (ECOCROP) | |
| Drenaje | |
| Fertilidad requerida (ECOCROP) | |
| Salinidad: umbral CEe (Maas & Hoffman) | dS/m; % de pérdida por dS/m |
| Preferido | |
| Evitar | |

## 6. Nutrición y fertilización

| Ítem | Dato |
|---|---|
| Extracción orientativa | kg N, P₂O₅ y K₂O por tonelada o por hectárea |
| Momento | |
| Elementos críticos | |
| Exceso de N | |

## 7. Riego

| Ítem | Dato |
|---|---|
| Kc inicial / medio / final (FAO-56, Tabla 12) | / / |
| Método recomendado | |
| Etapas críticas | |

## 8. Siembra y plantación

| Ítem | Dato |
|---|---|
| Método | (siembra directa o almácigo y trasplante) |
| Época (zona templada) | |
| Profundidad | cm |
| Marco | cm entre líneas × cm entre plantas (plantas/m²) |
| Emergencia | días (debe coincidir con `stage_templates.py`) |
| Trasplante | días (debe coincidir con `stage_templates.py`) |
| Semilla | semillas/g; kg/ha |

## 9. Etapas del ciclo (días desde siembra, orientativo)

| Etapa | Días | Qué hacer / vigilar |
|---|---|---|
| | | (alinear con los hitos de `stage_templates.py`) |

## 10. Plagas

| Plaga | Agente | Daño / síntomas | Manejo |
|---|---|---|---|
| | | | |

## 11. Enfermedades

| Enfermedad | Agente | Síntomas | Favorecen | Manejo |
|---|---|---|---|---|
| | | | | |

## 12. Fisiopatías y desórdenes

| Problema | Causa | Prevención |
|---|---|---|
| | | |

## 13. Asociaciones y rotación

| Ítem | Dato |
|---|---|
| Buenas compañeras | |
| Evitar | |
| Rotación | |

## 14. Cosecha y poscosecha

| Ítem | Dato |
|---|---|
| Índice de cosecha | |
| Rendimiento orientativo | |
| Conservación | °C, % HR, duración |
| Usos | |

## 15. Claves para el agente

- (síntoma → diagnóstico probable → qué recomendar; los 4–6 casos más frecuentes)

## Fuentes

- (fuentes específicas del cultivo, con URL)
- FAO-56, FAO ECOCROP, USDA SR Legacy, Maas & Hoffman / FAO-29, SENASA.
