# 01 — Conceptos y Vocabulario

## Estado del documento
Este documento fija el vocabulario que todos los demás documentos deben usar sin
desviación. Si un documento posterior parece contradecir una definición de este
documento, el error está en el documento posterior. Este documento también fija los
dos Principios Arquitectónicos que gobiernan toda decisión de diseño en Janus.

---

## 1. Principio Arquitectónico #1 — Estrella pura

**Ningún spoke se comunica jamás, de forma directa, con otro spoke. Todo pasa por
Janus.**

Esto no es una preferencia de diseño entre varias válidas: es una regla dura.
Consecuencias que se derivan directamente de esta regla y que todo documento posterior
debe respetar:

- No existe llamada directa spoke→spoke bajo ninguna circunstancia, incluyendo llamadas
  a servidores MCP que un spoke exponga. Si el Spoke A tiene una capacidad que el
  Spoke B necesita, el Spoke B se la pide a Janus; Janus resuelve internamente quién la
  sirve (que puede ser el Spoke A) y devuelve el resultado al Spoke B en el idioma que
  el Spoke B espera. El Spoke B nunca se entera de que fue el Spoke A quien
  efectivamente la resolvió, salvo que el modelo de resultado lo incluya
  explícitamente como metadato.
- Janus es, por definición, un **proxy obligatorio de todo protocolo** entre spokes, no
  solamente un directorio de "quién tiene qué". No hay una ruta de "presentación" en la
  que Janus solo facilita el primer contacto y luego los spokes quedan conectados entre
  sí — cada interacción, siempre, pasa por Janus.
- Ningún spoke necesita saber que Janus es un intermediario. Desde la perspectiva de
  cada spoke, Janus se ve y se comporta como su entorno nativo esperado (ver `Core de
  Traducción` más abajo). Un spoke que espera ser cliente MCP de un servidor MCP ve a
  Janus actuando como ese servidor MCP; un spoke que espera recibir webhooks los recibe
  de Janus como si fueran de su gateway habitual.

## 2. Principio Arquitectónico #2 — No-reinvención

**Janus no reimplementa una capacidad que un spoke ya resuelve bien. La conecta.**

- La regla de diseño para decidir si algo se construye dentro del núcleo de Janus o se
  delega a un spoke es: *¿existe ya un spoke soportado (o soportable vía el contrato de
  integración) que resuelva esto correctamente?* Si sí, Janus lo conecta y expone bajo
  su modelo semántico único; no construye una segunda implementación.
- Janus solo contiene código propio de "trabajo pesado" para aquello que,
  genuinamente, ningún spoke resuelve de forma completa: el propio Core de Traducción,
  el registro de capacidades, la persistencia transversal, y (condicionalmente) un
  pipeline de voz si ningún spoke soportado lo cubre satisfactoriamente.
- Este principio es lo que mantiene a Janus como una capa **ligera de orquestación**, no
  como un monolito que duplica el trabajo de sus propios spokes. Es también lo que hace
  viable que sea open source: un tercero que ya tiene una herramienta fuerte en un nicho
  no necesita que Janus reconstruya esa herramienta, solo que la conecte.

## 3. Definiciones

### Janus
El sistema completo descrito en `00-vision-y-alcance.md`: núcleo + Core de Traducción +
registro de capacidades + persistencia transversal + (opcionalmente, en el futuro) GUI.
Cuando este documento dice "Janus" sin calificar, se refiere al sistema completo, no a
un componente interno específico.

### Núcleo (Core)
La parte de Janus que no es un spoke: contiene el Core de Traducción, el registro de
capacidades, el motor de enrutamiento, y la persistencia transversal. El núcleo es
agnóstico a qué spokes concretos están conectados en un momento dado.

### Spoke
Cualquier herramienta externa, existente o futura, que Janus conecta para proveer una o
más capacidades. Un spoke puede ser un motor de razonamiento (Claude Desktop, Gemini
Desktop), un runtime de agente de código (OpenClaude), un runtime de agente
general-purpose con gateway multi-canal (Hermes, OpenClaw), o cualquier otra
herramienta futura que cumpla el contrato de integración. **Un spoke jamás sabe de la
existencia de otro spoke.**

Nota de vocabulario: en el diseño original de este proyecto se consideró brevemente a
Hermes como "el hub" y a los demás como "adaptadores que cuelgan de él". Ese modelo
queda descartado por el Principio Arquitectónico #1: no existe un hub que no sea Janus
mismo. Hermes, OpenClaude, OpenClaw, Claude Desktop y Gemini Desktop son todos spokes,
sin jerarquía entre ellos. Ver `08-mapa-de-componentes-reales.md` para el detalle de
cada uno.

### Core de Traducción
El componente del núcleo responsable de que cada spoke pueda hablar con Janus usando su
propio protocolo nativo, sin necesitar modificarse. Tiene, por cada spoke conectado,
dos caras (ver sección 4).

### Capacidad
Cualquier cosa concreta que un spoke puede hacer y que otro punto del sistema (el
usuario, un rol, otro spoke indirectamente) puede solicitar: búsqueda web, edición de
código consciente de AST, envío de un mensaje a una plataforma, síntesis de voz,
ejecución de un comando, etc. Una capacidad se registra una vez en el núcleo y se
resuelve, cada vez que se solicita, por delegación (ver
`04-modelo-de-capacidades-y-enrutamiento.md`).

### MCP / gRPC (como contrato, no como implementación)
En este conjunto de documentos, "hablar MCP" o "hablar gRPC" se usa como el ejemplo
mínimo de protocolo que un contrato de integración puede exigir para que un tercero
conecte un spoke nuevo sin tocar el núcleo. No se fija aquí que estos sean los únicos
protocolos soportados — son el piso de extensibilidad esperado, detallado en
`02-arquitectura-estrella-y-contrato-de-integracion.md`.

### Sesión
Una unidad de trabajo con estado propio y persistente, iniciada por el usuario o por
Janus en su nombre, que puede involucrar a uno o más spokes y uno o más roles a lo
largo del tiempo, y que puede reanudarse. Ver `06-modelo-de-persistencia-y-estado.md`.

### Rol
Una función abstracta dentro del dominio de desarrollo de software (Architect,
Implementer, Debugger, Documenter, DevOps, u otros que se agreguen) que se asigna a un
spoke concreto en tiempo de ejecución, y que puede reasignarse a un spoke distinto sin
que el resto del sistema lo perciba. Ver `05-modelo-de-roles-y-tareas.md`.

### Tarea
Una unidad de trabajo discreta, asignable a un rol, con un estado de progreso
rastreable por Janus, independientemente de qué spoke la ejecute internamente.

### Canal
Una vía de interacción externa entre el usuario y Janus (chat directo, una plataforma
de mensajería, voz). Un canal no es un spoke — es una superficie de entrada/salida que
Janus expone o conecta, potencialmente reutilizando un spoke que ya resuelve ese canal
(p. ej. un spoke con gateway a Discord ya construido), respetando siempre el Principio
Arquitectónico #1.

### Adaptador de spoke (dentro del Core de Traducción)
La porción del Core de Traducción específica de un spoke concreto: sabe imitar el
protocolo nativo de ese spoke y sabe traducir hacia/desde el modelo semántico interno de
Janus. Cada spoke soportado tiene exactamente un adaptador. Un adaptador nuevo es lo
que un tercero implementa para agregar soporte a un spoke no contemplado originalmente.

## 4. Las dos caras del Core de Traducción

Por cada spoke conectado, el Core de Traducción mantiene dos caras funcionalmente
distintas:

1. **Cara nativa (hacia el spoke):** imita el protocolo/entorno que el spoke espera
   encontrar. Si el spoke espera ser cliente de un servidor MCP, esta cara se comporta
   como ese servidor. Si el spoke espera emitir o recibir webhooks de un gateway, esta
   cara se comporta como ese gateway. El spoke no requiere modificación alguna y no
   necesita saber que está hablando con Janus y no con su contraparte habitual.

2. **Cara semántica (hacia el núcleo):** traduce cada interacción capturada en la cara
   nativa al modelo interno único de Janus (capacidades, sesiones, tareas, roles,
   resultados), y viceversa: traduce las respuestas del núcleo de vuelta al formato que
   la cara nativa de ese spoke específico sabe emitir.

Ninguna de las dos caras existe de forma aislada — un adaptador de spoke sin ambas caras
no es un adaptador completo. Este es el mecanismo concreto que hace posible el
Principio Arquitectónico #1: los spokes nunca se enteran de la mediación porque la cara
nativa se lo oculta por diseño.

## 5. Nota sobre "idioma" y adaptación de salida

Cuando el núcleo de Janus produce un resultado (una respuesta, un estado de tarea, un
resultado de capacidad), ese resultado existe primero en el modelo semántico interno.
La cara semántica del adaptador correspondiente lo traduce al formato de salida que ese
spoke específico espera — no existe un formato de salida único y fijo que todos los
spokes reciban igual. La adaptación de idioma por spoke es parte constitutiva del
contrato de cada adaptador, no un detalle de implementación postergable.
