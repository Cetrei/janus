# 06 — Modelo de Persistencia y Estado

## Estado del documento
Arquitectura pura — sin decisión de motor de almacenamiento, formato de serialización,
ni tecnología concreta. Depende de `01-conceptos-y-vocabulario.md` (Sesión, Tarea) y
`02-arquitectura-estrella-y-contrato-de-integracion.md` (Persistencia Transversal como
parte del núcleo).

---

## 1. Principio: pertenencia al usuario, no al spoke

Todo lo enumerado en este documento pertenece a **Janus como entidad única que
representa al usuario**, no a ningún spoke individual. Esto tiene una consecuencia
directa: si el usuario reemplaza un spoke por otro (p. ej. cambia de spoke de
razonamiento, o de spoke de gateway multi-canal), **la persistencia transversal
sobrevive intacta** — las sesiones, tareas, preferencias y memoria no se pierden ni
quedan fragmentadas por spoke.

Un spoke puede tener su propio estado interno efímero o especializado (p. ej. el
historial de conversación bruto que un spoke de razonamiento mantiene internamente
mientras procesa una solicitud), pero ese estado no es la fuente de verdad del sistema
— es, cuando corresponde, un insumo que se traduce y se refleja en la persistencia
transversal a través del adaptador correspondiente.

## 2. Categorías de persistencia transversal

### 2.1. Sesiones
Registro de unidades de trabajo con estado propio (ver definición en documento 01),
incluyendo qué roles y spokes participaron, en qué orden, y con qué resultados. Una
sesión debe poder reanudarse: el usuario puede retomarla más adelante, potencialmente
con una asignación de rol→spoke distinta a la que tenía originalmente, sin perder el
contexto acumulado que el núcleo haya persistido.

### 2.2. Tareas
Registro de unidades de trabajo discretas (ver definición en documento 05), su estado,
sus dependencias, y sus resultados, independientemente de si la sesión que las originó
sigue activa.

### 2.3. Preferencias del usuario
Configuración explícita del usuario sobre cómo debe comportarse el sistema: políticas
de selección de spoke cuando hay ambigüedad (ver documento 04, sección 3), canales
preferidos, idioma, y cualquier otro ajuste de comportamiento que no deba perderse
entre sesiones ni depender de qué spoke esté activo en un momento dado.

### 2.4. Memoria de largo plazo
Información acumulada a través del tiempo que informa el comportamiento futuro del
sistema (p. ej. contexto recurrente sobre proyectos del usuario, decisiones pasadas
relevantes). Esta arquitectura no fija aquí el mecanismo de captura o consulta de esa
memoria — solo establece que su almacenamiento pertenece a la persistencia transversal
del núcleo, no a un spoke.

### 2.5. Correo y otras integraciones de datos personales
Cuando Janus gestiona correo (u otras fuentes de datos personales equivalentes,
como calendarios o notas), el estado relevante para el sistema (qué se leyó, qué
tareas se derivaron de un correo, qué se respondió) se persiste de forma transversal,
incluso si el acceso de bajo nivel al correo en sí lo provee un spoke o una integración
externa a través del Registro de Capacidades.

### 2.6. Registro de Capacidades
El propio Registro de Capacidades (documento 04) es, en sí mismo, un dato persistente
del núcleo: qué capacidades existen, qué spoke(s) las sirven actualmente, y las
políticas de selección configuradas. Se incluye aquí porque es estado que debe
sobrevivir a reinicios y reconexiones de spokes, igual que el resto de las categorías.

## 3. Relación entre categorías

Estas categorías no son compartimentos aislados: una sesión referencia tareas; una
tarea puede haber consumido una capacidad cuyo registro también es persistente; una
preferencia del usuario puede condicionar cómo se resuelve una tarea futura. Esta
arquitectura no impone aquí un esquema de datos concreto (eso es implementación) — solo
establece que estas relaciones deben ser representables de forma consistente dentro de
una única capa de persistencia transversal, y no dispersarse en almacenamientos
inconexos por spoke.

## 4. Requisito de observabilidad

Toda la persistencia transversal descrita en este documento debe ser, como mínimo,
consultable desde afuera del núcleo (no solo utilizable internamente por el motor de
enrutamiento). Este requisito es lo que conecta este documento con
`07-superficie-para-gui-futura.md`: una GUI futura no podría mostrar sesiones activas,
historial de tareas, o el estado del Registro de Capacidades si esta persistencia no
fuera observable desde el diseño original.

## 5. Documentos relacionados
- `05-modelo-de-roles-y-tareas.md` — el ciclo de vida de tareas que aquí se persiste.
- `04-modelo-de-capacidades-y-enrutamiento.md` — el Registro de Capacidades como dato
  persistente.
- `07-superficie-para-gui-futura.md` — requisitos de observabilidad externa sobre esta
  persistencia.
- `09-preguntas-abiertas.md` — mecanismo concreto de captura/consulta de memoria de
  largo plazo, aún no decidido.
