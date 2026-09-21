# 03 — Contrato de Spoke

## Estado del documento
Arquitectura pura. Depende de `01-conceptos-y-vocabulario.md` (definiciones de Spoke,
Core de Traducción, Adaptador) y de `02-arquitectura-estrella-y-contrato-de-
integracion.md` (contrato de integración general). Este documento detalla el contrato
por **tipo** de spoke, no por spoke concreto (eso es `08-mapa-de-componentes-
reales.md`).

---

## 1. Precisión importante: el contrato lo cumple Janus, no el spoke

A diferencia de un modelo de integración convencional (donde cada sistema externo debe
implementar una interfaz que el orquestador central define), en Janus **el contrato lo
cumple el adaptador dentro del Core de Traducción, imitando lo que el spoke ya espera
de su entorno nativo**. El spoke, en el caso general, no se modifica ni sabe que Janus
existe.

Esto significa que "contrato de spoke" en este documento se lee como: *qué debe
garantizar el adaptador de Janus para que un spoke de este tipo funcione correctamente
creyendo que está en su entorno habitual*, no como una lista de requisitos que se le
exige al software del spoke.

Excepción: cuando un spoke es, él mismo, código nuevo escrito específicamente para
integrarse con Janus (p. ej. un spoke construido por un tercero desde cero pensando en
Janus), ese spoke puede optar por hablar directamente el protocolo de piso (MCP/gRPC)
descrito en el documento anterior, sin necesidad de que Janus le construya una cara
nativa de imitación — en ese caso el "contrato de spoke" se cumple del lado del spoke
directamente. Ambas rutas son válidas y coexisten.

## 2. Tipos de spoke

Para evitar tratar todo spoke como si aportara lo mismo, se distinguen tres tipos según
la naturaleza de la capacidad que aportan. Un spoke real puede pertenecer a más de un
tipo simultáneamente (ver `08-mapa-de-componentes-reales.md` para casos concretos).

### 2.1. Spoke de razonamiento
Aporta capacidad de pensar/generar/decidir sin necesariamente ejecutar nada por sí
mismo en el sistema del usuario. Típicamente cerrado, sin API de extensión más allá de
ser cliente de protocolos estándar.

**Contrato que el adaptador debe garantizar:**
- Poder enviarle al spoke un problema/pregunta en el formato que ese spoke espera
  recibir como entrada conversacional o de completado.
- Poder recibir su salida y traducirla al modelo semántico interno (como resultado de
  una tarea, una respuesta de rol, o contenido para otro spoke).
- Si el spoke solo actúa como cliente de MCP (no como servidor), el adaptador debe
  exponerle a este spoke una cara de servidor MCP que en realidad enruta hacia el
  Registro de Capacidades del núcleo — el spoke cree que está hablando con un servidor
  MCP normal.

### 2.2. Spoke de ejecución
Aporta capacidad de actuar sobre código o sistemas reales: editar archivos con
conciencia de estructura (AST/LSP), ejecutar comandos, correr pruebas, hacer despliegue.

**Contrato que el adaptador debe garantizar:**
- Poder asignarle una tarea concreta (en el sentido de `05-modelo-de-roles-y-
  tareas.md`) y recibir de vuelta un resultado con suficiente detalle para que el
  núcleo pueda rastrear el progreso (éxito, fallo, artefactos producidos, siguiente
  paso sugerido).
- Si el spoke expone su propio servidor (p. ej. un servidor gRPC de sesión), el
  adaptador debe poder actuar como cliente de ese servidor sin que el spoke necesite
  saber que quien lo consume es Janus y no un frontend directo.
- Debe preservarse la trazabilidad de qué rol y qué tarea originaron la ejecución, para
  la persistencia transversal.

### 2.3. Spoke de canal / gateway multi-canal
Aporta una vía de entrada/salida hacia el usuario u otros sistemas externos:
mensajería (Discord, Telegram, Slack, WhatsApp), voz, u otro canal.

**Contrato que el adaptador debe garantizar:**
- Poder recibir eventos entrantes desde la plataforma que el spoke ya gestiona
  (mensajes, comandos, notificaciones) y traducirlos a una solicitud dentro del modelo
  semántico interno, atribuida a la sesión/usuario correcto.
- Poder enviar salidas del núcleo hacia esa plataforma en el formato que el spoke ya
  sabe emitir.
- Importante: si dos spokes distintos resuelven el mismo tipo de canal (p. ej. dos
  spokes que ambos pueden hablar con Discord), Janus decide, a nivel de configuración
  del usuario, cuál está activo para cada canal — nunca se conectan ambos a la vez de
  forma que generen ambigüedad de quién responde. Este es un detalle de enrutamiento,
  no de este documento; se referencia en `04-modelo-de-capacidades-y-enrutamiento.md`.

### 2.4. Spoke controlado por automatización de interfaz gráfica
Aporta capacidad de razonamiento (o cualquier otra) a través de una aplicación de
escritorio cerrada que no expone ningún protocolo programático (ni MCP, ni gRPC, ni
API, ni webhooks) — la única superficie disponible es la misma interfaz gráfica que
usaría un humano: ventanas, botones, campos de texto.

Este tipo de spoke es estructuralmente distinto a los tres anteriores: en los tipos
2.1 a 2.3, el adaptador imita un protocolo que el spoke ya espera hablar. Aquí no hay
protocolo que imitar — el adaptador debe operar el sistema operativo y la aplicación
directamente, de la misma forma que lo haría el usuario. El mecanismo detallado de
cómo se logra esto (control de ventanas + mapa de elementos interactuables) se
desarrolla en `10-automatizacion-de-interfaz-grafica.md`; esta sección solo fija el
contrato que ese mecanismo debe satisfacer para calificar como un adaptador válido de
este tipo.

**Contrato que el adaptador debe garantizar:**
- Poder localizar, abrir (si no está abierta) y enfocar la ventana de la aplicación
  objetivo, sin depender de que esa aplicación coopere de ninguna forma especial.
- Poder identificar, dentro de la ventana enfocada, los elementos interactuables
  relevantes para completar una interacción (típicamente: dónde escribir una entrada,
  qué acción dispara el envío, dónde leer la salida producida).
- Poder ejecutar la interacción (escribir, activar el control de envío) y extraer el
  resultado producido por la aplicación, traduciéndolo al modelo semántico interno con
  la misma fidelidad que cualquier otro adaptador.
- Degradar de forma explícita y detectable cuando la interfaz de la aplicación objetivo
  cambia de forma que el mecanismo de identificación de elementos deja de funcionar —
  nunca debe fallar en silencio produciendo una interacción incorrecta sin que el
  núcleo se entere de que algo salió mal.

**Nota:** cualquier aplicación de escritorio arbitraria es, en principio, candidata a
ser un spoke de este tipo — no es un mecanismo exclusivo para Claude Desktop o Gemini
Desktop, aunque esos dos sean, hoy, los casos de uso que lo motivan (ver documento 08).

## 3. Requisitos comunes a todo adaptador, sin importar el tipo

Independientemente del tipo de spoke, todo adaptador dentro del Core de Traducción
debe:

1. **Ocultar la mediación.** El spoke no debe requerir ninguna modificación de su
   comportamiento esperado para funcionar detrás del adaptador (salvo en el caso de
   excepción de la sección 1, donde el spoke se construyó sabiendo que hablaría con
   Janus).
2. **Traducir en ambas direcciones sin pérdida de intención.** La cara semántica debe
   preservar suficiente información al traducir hacia el modelo interno como para que
   el núcleo pueda enrutar, registrar y persistir correctamente; y al traducir de
   vuelta, debe producir una salida que el spoke pueda interpretar sin necesitar
   contexto adicional que no tenga.
3. **No asumir la existencia de otros spokes.** El código del adaptador de un spoke no
   debe referenciar, directa o indirectamente, el protocolo o la existencia de otro
   spoke concreto. Toda necesidad de otra capacidad se expresa hacia el núcleo en
   términos abstractos de capacidad, nunca como "pídele esto a [spoke X]".
4. **Reportar sus capacidades al Registro de Capacidades al conectarse.** Un adaptador
   nuevo, al activarse, declara qué capacidades aporta su spoke, para que puedan ser
   descubiertas y delegadas por el resto del sistema.
5. **Ser reemplazable sin afectar a otros adaptadores.** Retirar o reemplazar el
   adaptador de un spoke no debe requerir cambios en los adaptadores de los demás
   spokes ni en el núcleo, más allá de la actualización correspondiente en el Registro
   de Capacidades.

## 4. Documentos relacionados
- `04-modelo-de-capacidades-y-enrutamiento.md` — cómo se registran y resuelven las
  capacidades que cada adaptador declara.
- `05-modelo-de-roles-y-tareas.md` — cómo se asignan tareas a spokes de tipo ejecución
  y razonamiento a través de roles.
- `08-mapa-de-componentes-reales.md` — clasificación concreta de Hermes, OpenClaude,
  OpenClaw, Relay, Claude Desktop y Gemini Desktop según estos tipos.
- `10-automatizacion-de-interfaz-grafica.md` — desarrollo completo del mecanismo que
  implementa el tipo de spoke 2.4.
