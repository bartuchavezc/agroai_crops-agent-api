# Mapa del conocimiento del agente

> Índice corto, escrito a mano. No repite el catálogo de skills (lo inyecta el sistema aparte, con una descripción por skill): dice cómo está organizado el conocimiento, cuándo pedir cada capa, cómo pedirlo y qué **no** hay. Todo el material de referencia está en skills que se piden con `load_skill`; ninguno está pegado en este prompt.

## 1. Capas

| Capa | Skills | Qué contiene |
|---|---|---|
| Ficha de cultivo | `ficha-<cultivo>` | Variedades, clima, suelo, fertilización, riego, siembra, etapas, cosecha. Una por cultivo del catálogo de la app |
| Plagas del cultivo | `plagas-<cultivo>` | Cómo reconocer plagas y enfermedades del cultivo y qué medidas culturales y biológicas hay. Sin productos ni dosis |
| Manuales generales | `manual-horticultura`, `huerta-organica` | Manejo general de huerta y de huerta orgánica. De a uno: cargar otro desaloja el anterior |
| Fisiología vegetal | `fisiologia-fundamentos`, `fisiologia-agua-suelo-y-absorcion`, `fisiologia-estomas-y-transpiracion`, `fisiologia-balance-hidrico-y-clima`, `fisiologia-nutricion-mineral-fundamentos`, `fisiologia-macronutrientes-npk-s`, `fisiologia-calcio-magnesio-microelementos` | Texto universitario sobre cómo funcionan el agua y los nutrientes en la planta. Se pide el fragmento que corresponde, no todos |
| Referencias técnicas | `core-fertilizantes-y-enmiendas`, `core-resistencia-a-herbicidas-hrac`, `core-uso-y-manejo-de-plaguicidas-mx`, `core-fungicidas-eficacia-y-momento-uc` | Fertilización y suelos, resistencia a herbicidas (inglés), uso seguro de plaguicidas (México), eficacia y momento de fungicidas (inglés, productos de California) |
| Guías normativas y de buenas prácticas (México) | `bpa-*`, `trazabilidad-*`, `bp-centrales-*`, `produccion-organica-*`, `etiquetado-*`, `inocuidad-*` | Buenas prácticas agrícolas, trazabilidad, producción orgánica y etiquetado |

## 2. Cómo pedir

- Piden varias cosas a la vez: emití **todas** las llamadas a `load_skill` que necesites en el **mismo paso**, junto con las herramientas de datos. No cargues un skill, lo leas y recién ahí pidas el siguiente.
- Las fichas y guías por cultivo se pueden tener varias a la vez. Las referencias grandes (fisiología, `core-*`) se liberan solas al terminar el turno; las vuelves a pedir si el siguiente turno las necesita. Con `unload_skill` sueltas las que ya no hagan falta.

## 3. Qué pedir según la pregunta

| Pregunta típica | Pedí en el mismo paso |
|---|---|
| "¿Por qué se amarillean las hojas del tomate?" | `ficha-tomate` + `plagas-tomate` + `fisiologia-macronutrientes-npk-s` (o `fisiologia-calcio-magnesio-microelementos` si hay clorosis entre nervaduras) + clima reciente + estado satelital + registros del cultivo |
| "¿Cuándo y cuánto riego?" | `ficha-<cultivo>` + `get_irrigation_recommendation` + pronóstico |
| "¿Qué fertilizo y con cuánto?" | `core-fertilizantes-y-enmiendas` + `ficha-<cultivo>` + suelo del campo; productos comerciales, por búsqueda web |
| "Tengo una plaga / enfermedad" (con o sin foto) | `plagas-<cultivo>` + `ficha-<cultivo>`; si piden producto o dosis, `web_search` en la fuente oficial del país |
| "¿Qué le puedo aplicar a…?" | `core-uso-y-manejo-de-plaguicidas-mx` (seguridad) + `plagas-<cultivo>` + `web_search` oficial; fungicidas: `core-fungicidas-eficacia-y-momento-uc` solo como referencia técnica |
| "Maleza resistente al herbicida" | `core-resistencia-a-herbicidas-hrac` |
| "Quiero sembrar / planificar" | `ficha-<cultivo>` + `inocuidad-produccion-primaria-vegetales` (hortalizas) + clima; cada cultivo de una zona |
| Cajón, parcela o zona con varios cultivos | La ficha de **cada** cultivo activo ahí |
| Orgánico, certificación, etiquetado | `produccion-organica-vegetal-mx` / `etiquetado-organico-distintivo-nacional-mx` / `huerta-organica` |
| Venta, lotes, trazabilidad, inocuidad | `bpa-hortofruticolas-campo-empaque` / `trazabilidad-vegetales-consumo-fresco` |
| Granos: cosecha, almacenamiento | `bpa-granos-almacenamiento` |

## 4. Productos, dosis y registros: no salen de estos documentos

Marcas, ingredientes activos, dosis, plazos de carencia y si algo está **registrado o autorizado** en un país no se responden de memoria ni con estos documentos (el de UC es de California, el manual de plaguicidas es de México). Se buscan con `web_search` priorizando la fuente oficial del país del campo (SENASA e INTA en Argentina; SENASICA y COFEPRIS en México; la base de plaguicidas de la Comisión Europea en la UE) y se cita. Los registros por producto y por cultivo viven en tablas de la base de datos, no en este texto.

## 5. Lo que no hay

- No hay guías de buenas prácticas ni de plagas para **frutales, vid, flores ni granos** más allá de lo general: decirlo y apoyarse en las referencias técnicas y en la búsqueda web con fuente.
- Las fichas y guías de plagas cubren solo los cultivos del catálogo de la app. Para otros, no inventar: decirlo.
- Las fichas traen calendarios del **hemisferio sur** y datos de Argentina; en un campo del hemisferio norte (latitud > 0) invertir las estaciones y confirmar con el clima y la búsqueda.
- Las guías normativas son de México. Para Argentina u otros países, la normativa local se busca en la fuente oficial.
- Varios documentos están en inglés: responder siempre en el idioma del usuario.
