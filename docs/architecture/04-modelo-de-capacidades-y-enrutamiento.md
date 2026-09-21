# 04 — Modelo de Capacidades y Enrutamiento

## Estado del documento
Arquitectura pura. Depende de `01-conceptos-y-vocabulario.md` (Principio
Arquitectónico #1, definición de Capacidad) y `02-arquitectura-estrella-y-contrato-de-
integracion.md` (Registro de Capacidades como parte del núcleo).

---

## 1. Qué es una capacidad, en términos operativos

Una capacidad es cualquier función concreta que un spoke puede ejecutar y que el
sistema puede solicitar de forma nombrada: "buscar en internet", "editar un archivo con
conciencia de AST", "enviar un mensaje a Discord", "sintetizar voz a partir de texto",
"ejecutar un comando de shell", "consultar un modelo de lenguaje específico", etc.

Toda capacidad, para ser utilizable por el sistema, debe estar **registrada**: el
Registro de Capacidades mantiene, como mínimo conceptual:
- Un identificador abstracto de la capacidad (independiente del spoke que la sirve).
- Qué spoke(s) la sirven actualmente.
- Qué forma de entrada espera y qué forma de salida produce, en términos del modelo
  semántico interno (no en el protocolo nativo del spoke — eso lo resuelve el
  adaptador correspondiente).

## 2. Regla única de resolución: delegación siempre

Por el Principio Arquitectónico #1 (estrella pura), **no existe más que un mecanismo de
resolución de capacidades: la delegación a través de Janus.** Toda solicitud de
capacidad, sin importar quién la origina (el usuario, un rol, un spoke que necesita
algo de otro spoke) sigue el mismo camino:

1. El solicitante (un rol ejecutándose en un spoke, o el propio núcleo) pide a Janus
   una capacidad por su identificador abstracto.
2. El motor de enrutamiento consulta el Registro de Capacidades para determinar qué
   spoke(s) la sirven.
3. Janus invoca al spoke elegido a través del adaptador correspondiente (cara
   semántica → cara nativa).
4. El resultado se traduce de vuelta al modelo semántico interno y se entrega al
   solicitante en el formato que este último espera (vía su propio adaptador, si el
   solicitante es también un spoke).

No existe una ruta alternativa de "préstamo directo" de una capacidad de un spoke a
otro. Una versión anterior de este diseño distinguía entre "delegar" (pedir cada vez) y
"heredar" (dar acceso directo y persistente a la capacidad de otro spoke) como dos
mecanismos distintos. Esa distinción queda **descartada**: bajo estrella pura, ambas
son, estructuralmente, delegación — la única diferencia posible entre ellas es si Janus
decide cachear el resultado de una invocación previa en lugar de repetirla, lo cual es
un detalle de optimización (sección 4), no un modelo de enrutamiento distinto.

## 3. Resolución cuando existe más de un spoke para la misma capacidad

Es esperable que, con el tiempo, más de un spoke conectado sea capaz de servir la misma
capacidad abstracta (p. ej. dos spokes distintos que ambos pueden hacer búsqueda web, o
dos que ambos pueden conectarse a Discord). El Registro de Capacidades debe soportar
esta situación sin ambigüedad, mediante alguna política de selección explícita y
consultable:

- **Selección por configuración del usuario:** el usuario fija, para una capacidad o
  tipo de capacidad, cuál spoke debe preferirse.
- **Selección por disponibilidad/cuota:** si el spoke preferido no está disponible
  (caído, sin cuota, sin credenciales activas), el motor de enrutamiento recurre a un
  spoke alternativo que sirva la misma capacidad, si existe uno registrado.
- **Selección por rol/contexto:** el rol o la tarea que origina la solicitud puede
  llevar asociada una preferencia (p. ej. el rol Implementer prefiere que la edición de
  código la resuelva un spoke de tipo ejecución con conciencia de AST, no un spoke de
  razonamiento genérico).

Esta arquitectura no fija cuál de estas políticas tiene prioridad sobre cuál — eso es
una decisión de configuración/producto que se deja explícitamente abierta en
`09-preguntas-abiertas.md`. Lo que sí fija esta arquitectura es que **debe existir
siempre una política determinística y consultable**, nunca una selección arbitraria o
silenciosa que el usuario no pueda auditar.

## 4. Caché como optimización, no como modelo alterno

Cuando el resultado de invocar una capacidad es válido para ser reutilizado sin
volver a invocar al spoke (por ejemplo, una configuración que no cambia, o un resultado
reciente dentro de una ventana de validez razonable), Janus puede optar por servir ese
resultado desde una caché en lugar de delegar de nuevo. Esto es puramente una
optimización de latencia/costo:

- No cambia el hecho de que, conceptualmente, la capacidad sigue perteneciendo al spoke
  que la sirve.
- No debe usarse para casos donde el resultado depende del estado actual del spoke o
  del mundo externo (p. ej. no cachear una búsqueda web como si fuera una operación
  idempotente en el tiempo).
- La decisión de qué es cacheable y por cuánto tiempo es una decisión por capacidad,
  registrada junto con la capacidad misma en el Registro de Capacidades — no una
  decisión global del sistema.

## 5. Registro dinámico

Las capacidades no son una lista fija definida en tiempo de diseño. Un spoke puede:
- **Declarar nuevas capacidades al conectarse**, según lo que su adaptador reporte
  (ver `03-contrato-de-spoke.md`, sección 3, punto 4).
- **Dejar de estar disponible**, momento en el cual el Registro de Capacidades debe
  reflejar que esa capacidad (si era servida únicamente por ese spoke) queda sin
  proveedor, sin que esto rompa al resto del sistema — simplemente esa capacidad deja
  de poder resolverse hasta que un spoke vuelva a proveerla.

Esto es lo que permite que el "pool de modelos gratuitos con fallback" (la motivación de
origen del proyecto, ver `00-vision-y-alcance.md` sección 3) sea simplemente una
instancia particular de este modelo: cada modelo/proveedor accesible por API es una
capacidad de tipo razonamiento, registrada con su propia política de selección
(preferencia + fallback por disponibilidad de cuota), sin requerir ningún mecanismo
aparte del ya descrito en este documento.

## 6. Documentos relacionados
- `05-modelo-de-roles-y-tareas.md` — cómo los roles consumen capacidades para ejecutar
  tareas.
- `06-modelo-de-persistencia-y-estado.md` — dónde vive el Registro de Capacidades como
  parte de la persistencia transversal.
- `09-preguntas-abiertas.md` — política de prioridad entre criterios de selección de
  spoke (sección 3 de este documento), aún no decidida.
