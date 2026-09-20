# Agentes — Skills y configuración

## 1. Skills y comandos: catálogo compartido, delegación por especialidad

Los skills y comandos son un **catálogo único, compartido entre todos los agentes** —
no hay un set de skills distinto por agente. La especialización ocurre en el momento
de la delegación: cuando Janus determina que una solicitud requiere un skill/comando
de una categoría dada (p. ej. "esto es una tarea de código"), delega la ejecución al
agente configurado para esa especialidad (p. ej. Implementer), usando el mismo
mecanismo de resolución por capacidad ya definido en
`architecture/04-modelo-de-capacidades-y-enrutamiento.md`, extendido ahora a nivel de
skill/comando y no solo a nivel de "tipo de tarea" genérico.

## 2. Config de agente: legible, editable por humano, IA o interfaz

### 2.1 Topología de carpetas obligatoria: filesystem como harness

Cada agente vive en su propia carpeta, siguiendo una topología **obligatoria**, sin
excepciones — esta estructura es lo que permite que incluso un modelo simple, con solo
acceso a filesystem, alcance capacidades de harness avanzado (el mismo principio que
agent-roles ya demuestra):

```
Implementer/
  Skills/
  Instructions/
  Rules/
  Tools/
  agent.md
  agent.toml
```

`agent.toml` es la config validada por Pydantic (ver sección 3); `agent.md` es la
descripción legible de identidad/propósito del agente; `Skills/`, `Instructions/`,
`Rules/`, `Tools/` contienen los `.md` correspondientes a cada categoría, que el
agente indexa y navega vía el mecanismo de `agents/02-memoria.md`, sección 5. Cada
agente es un folder; no hay excepciones a esta convención para agentes nuevos que el
usuario defina.

Cada agente tiene un archivo de configuración legible por humano (TOML, consistente
con el resto del stack fijado en `stack/06-config-toml-pydantic.md`) donde se declaran:
reglas, voz, skills habilitados, comandos habilitados, proveedor de modelo, y cualquier
otro parámetro de `AgentCore`/`AgentPersona`.

Esta config es editable por tres vías, todas igualmente válidas:
1. El usuario, directamente, editando el archivo.
2. La propia IA (cualquier agente, típicamente Janus), a través de una herramienta ya
   existente en vez de construir un mecanismo de escritura propio (no-reinvención):
   **`crates/filesystem-mcp/`** (fork de `filesystem-mcp-rs`, ver
   `stack/02-monorepo.md` — elegido sobre el MCP de filesystem oficial porque este
   último carece de eliminación de archivos, tiene búsqueda de patrones limitada, y no
   resuelve indexación; el fork aporta `bulk_edits` atómico y `grep_files` con regex,
   y lo que falte tras auditar el upstream, que ya trae `delete_path` recursivo
   según lo verificado en septiembre de 2026, ver `specs/spec-08-filesystem-mcp.md`), acompañado de un **skill obligatorio que documenta cómo
   usarla correctamente** — la mitigación directa al problema observado de que un
   modelo puede confundirse con su propio sistema de edición de archivos si solo cuenta
   con las tools, sin ejemplos concretos de uso (orden típico de llamadas, cuándo usar
   `edit_file` vs `bulk_edits`, ejemplo de dry-run antes de aplicar).
3. Una interfaz futura (`architecture/07-superficie-para-gui-futura.md`).

## 3. Validación como barrera obligatoria, sin excepción por vía de escritura

Independientemente de qué vía escribió el archivo, **ninguna config se aplica a un
agente en ejecución sin pasar antes por validación Pydantic** (ya definida como
mecanismo en `stack/06-config-toml-pydantic.md`, sección 2). El flujo es:

```
Escritura (humano | IA vía MCP filesystem | interfaz) → archivo TOML modificado
    → Janus detecta el cambio o recibe orden de recarga
    → validación Pydantic
    → si es válida: se aplica (con hot-reload o reinicio completo, ver sección 4)
    → si es inválida: se rechaza, el cambio NO se aplica, se informa el error a quien
      lo originó (humano o IA)
```

Esto evita que una edición mal formada —humana o generada por una IA que alucinó un
campo o un valor fuera de rango— tumbe un agente corriendo en producción.

## 4. Hot-reload condicional por campo

No toda modificación de config se trata igual, por riesgo de confusión/alucinación de
la IA si su propia identidad cambia a mitad de una tarea en curso:

- **Campos que requieren reinicio completo del agente** (matar la sesión de
  razonamiento en curso, reinstanciar limpio): el prompt/reglas base, el proveedor de
  modelo, el toolset asignado. Cambiar esto en caliente arriesgaría que el agente
  quede en un estado inconsistente respecto a su propia identidad a mitad de turno.
- **Campos de hot-reload simple** (se aplican sin reiniciar nada): voz, tono,
  parámetros cosméticos de `AgentPersona` en general.

Cada campo del schema de configuración de un agente se marca explícitamente con
`requires_restart: true` o `requires_restart: false` — esta marca es parte del
contrato del schema, no una inferencia en runtime.

---

## Documentos relacionados
- `architecture/04-modelo-de-capacidades-y-enrutamiento.md` — base conceptual de la
  delegación por especialidad de la sección 1.
- `architecture/07-superficie-para-gui-futura.md` — consumidor futuro de la config de
  agentes.
- `stack/06-config-toml-pydantic.md` — el formato TOML y la validación Pydantic que
  esta configuración extiende.
- `stack/02-monorepo.md` — `crates/filesystem-mcp/` y `libs/config/`.
- `agents/02-memoria.md` — indexación de la carpeta de identidad de cada agente
  (sección 5), que se reindexa cuando la config cambia.
- `agents/08-impacto-en-monorepo-y-diferido.md` — ubicación exacta de los folders de
  agente, diferida a `/spec`.
