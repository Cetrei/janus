# 02 — Arquitectura Estrella y Contrato de Integración

## Estado del documento
Arquitectura pura, sin decisiones de lenguaje/framework. Este documento asume como
leídos `00-vision-y-alcance.md` y `01-conceptos-y-vocabulario.md`, y depende
directamente de los Principios Arquitectónicos #1 (estrella pura) y #2
(no-reinvención) definidos allí.

---

## 1. Forma general del sistema

Janus es una **estrella pura**: el núcleo en el centro, y N spokes conectados
únicamente al núcleo, nunca entre sí.

```
                    Spoke A (p. ej. razonamiento)
                          |
                          |  (solo a través del Core de Traducción)
                          |
Spoke D ------------- NÚCLEO DE JANUS ------------- Spoke B
(p. ej. voz)          (Core de Traducción +               (p. ej. ejecución
                       Registro de Capacidades +            de código)
                       Persistencia Transversal)
                          |
                          |
                    Spoke C (p. ej. gateway multi-canal)
```

No existe, bajo ninguna circunstancia contemplada por esta arquitectura, una línea
directa entre dos spokes. Cualquier necesidad de un spoke de usar algo que provee otro
spoke se resuelve **exclusivamente** por delegación a través del núcleo (ver
`04-modelo-de-capacidades-y-enrutamiento.md`).

## 2. Por qué no un hub-and-spokes con un spoke privilegiado

Una versión anterior de este diseño consideró designar a un spoke concreto (Hermes)
como "hub" — es decir, como intermediario de facto entre los demás spokes, con Janus
como capa fina alrededor. Esa versión queda descartada explícitamente por dos razones:

1. **Viola el Principio Arquitectónico #1 en cuanto ese spoke-hub media entre otros
   dos spokes** — eso es comunicación spoke↔spoke con pasos extra, no una estrella
   pura centrada en Janus.
2. **Ata la arquitectura a la supervivencia de un spoke concreto.** Si mañana ese spoke
   deja de mantenerse, cambia de licencia, o simplemente aparece uno mejor, un diseño
   de hub-privilegiado obliga a una migración de arquitectura. Un diseño de estrella
   pura centrada en Janus solo obliga a reemplazar un adaptador.

Todo spoke, sin excepción — incluyendo aquellos que ya traen de fábrica su propio
gateway multi-canal o su propio orquestador de tareas — se conecta a Janus exactamente
de la misma forma estructural: a través de su adaptador correspondiente en el Core de
Traducción. Ninguno tiene una posición jerárquica distinta a nivel de arquitectura,
aunque a nivel de **capacidad** algunos aporten más superficie que otros (esto se
documenta por spoke en `08-mapa-de-componentes-reales.md`, no aquí).

## 3. Componentes del núcleo

El núcleo de Janus, en esta capa de arquitectura, se compone de tres partes lógicas:

### 3.1. Core de Traducción
Contiene un adaptador por cada spoke conectado, cada uno con sus dos caras (nativa y
semántica, definidas en `01-conceptos-y-vocabulario.md`, sección 4). Es responsable de:
- Recibir toda interacción entrante de un spoke en su protocolo nativo.
- Traducirla al modelo semántico interno.
- Enviar toda instrucción/resultado saliente hacia un spoke en el protocolo que ese
  spoke específico espera.

### 3.2. Registro de Capacidades
Mantiene la tabla de qué capacidades existen en el sistema y qué spoke(s) las sirven.
Es el componente que el motor de enrutamiento consulta para resolver una solicitud de
capacidad por delegación. Desarrollado en detalle en
`04-modelo-de-capacidades-y-enrutamiento.md`.

### 3.3. Persistencia Transversal
Almacena todo lo que pertenece al usuario o al sistema como un todo, y no a un spoke en
particular: sesiones, preferencias, tareas, memoria de largo plazo, correo. Desarrollado
en detalle en `06-modelo-de-persistencia-y-estado.md`.

Estas tres partes son lógicamente distintas pero conviven dentro del mismo núcleo; esta
arquitectura no exige ni prohíbe que se implementen como procesos separados — esa es
una decisión de implementación fuera del alcance de este documento.

## 4. Contrato de integración (extensibilidad)

Janus da soporte "de fábrica" a un conjunto base de spokes (ver
`08-mapa-de-componentes-reales.md`), pero ese conjunto base **no es una lista cerrada**.
El sistema, para ser legítimamente extensible por terceros (requisito de origen: es
software abierto), debe exponer un **contrato de integración** independiente de
cualquier spoke concreto.

### 4.1. Qué exige el contrato de integración

Para que un tercero pueda agregar soporte a un spoke nuevo sin modificar el núcleo de
Janus, alguna de las dos partes (el spoke mismo, o un adaptador nuevo escrito para él)
debe poder comunicarse con el núcleo usando al menos uno de los protocolos de piso que
Janus garantiza soportar de forma nativa en su Core de Traducción. El piso mínimo
identificado en el origen de este proyecto es:

- **MCP** (Model Context Protocol) — como servidor y como cliente, en ambas
  direcciones, ya que distintos spokes esperan distintos roles dentro de ese protocolo.
- **gRPC** — como mecanismo de comunicación bidireccional de propósito general para
  spokes que no hablan MCP nativamente pero exponen (o pueden exponer) una interfaz de
  este tipo.

Este piso es el **mínimo garantizado**, no el techo. Nada en esta arquitectura impide
que el Core de Traducción soporte protocolos adicionales en el futuro; lo que esta
arquitectura exige es que agregar un protocolo nuevo, o un spoke nuevo sobre un
protocolo ya soportado, sea una extensión del Core de Traducción (agregar un adaptador
más) y no una modificación de él ni del resto del núcleo.

### 4.2. Consecuencia de diseño: el núcleo no conoce spokes por nombre

El motor de enrutamiento, el registro de capacidades y la persistencia transversal
operan exclusivamente sobre el modelo semántico interno (capacidades, sesiones, roles,
tareas) y sobre identificadores abstractos de spoke — no contienen lógica
condicionada a "si es Hermes, hacer X; si es OpenClaude, hacer Y". Toda lógica
específica de un spoke concreto vive exclusivamente dentro de su adaptador, en el Core
de Traducción. Esto es lo que permite que el conjunto de spokes soportados crezca sin
tocar el resto del sistema.

## 5. Relación con el Principio de No-reinvención

La combinación de estrella pura + contrato de integración abierto es lo que permite
cumplir el Principio Arquitectónico #2 de forma sostenible: como cualquier spoke que ya
resuelve bien una capacidad puede conectarse sin fricción arquitectónica, nunca hay
presión de diseño para reimplementar esa capacidad dentro del núcleo. El núcleo se
mantiene deliberadamente ligero — traduce, enruta y persiste — y deja que la superficie
de spokes conectados sea donde vive la funcionalidad "pesada" de cada dominio (edición
de código, gateway multi-canal, síntesis de voz, razonamiento, etc.).

## 6. Documentos relacionados
- `03-contrato-de-spoke.md` — desarrolla en detalle qué debe cumplir cada tipo de
  adaptador según el tipo de capacidad que su spoke aporta.
- `04-modelo-de-capacidades-y-enrutamiento.md` — el mecanismo concreto de delegación
  que usa el Registro de Capacidades.
