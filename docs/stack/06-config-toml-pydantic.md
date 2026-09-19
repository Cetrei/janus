# Stack — Configuración: TOML + Pydantic

## 1. Formato: TOML, no YAML

Decisión explícita tras comparar: TOML es más estricto y menos propenso a errores de
parseo silenciosos que YAML (se evita, p. ej., el problema histórico de YAML
interpretando `no` como booleano). TOML además es consistente con el ecosistema que
Janus ya usa (Rust/Cargo, `pyproject.toml` de Python).

## 2. Validación: Pydantic

Equivalente directo, en Python, al patrón "Zod" mencionado durante la discusión:
esquema tipado que valida el TOML cargado, con fallos tempranos y mensajes claros ante
config inválida.

## 3. Filosofía: config es lo que el usuario declara; SQLite es lo que el sistema genera

Distinción explícita: los harnesses base (qué existen, en qué puerto, qué política de
fallo) son **configuración declarada por el usuario** — nunca estado que el sistema
descubre y persiste solo. Mezclar ambos hubiera sido un error. El estado dinámico que
el sistema sí genera (spokes externos registrados en runtime, tokens emitidos) va a
SQLite/Redis, no a `config/janus.toml`.

## 4. Ubicación y consumo

`libs/config/` expone la config validada a cualquier `apps/*` que la necesite, sin que
el consumidor sepa si por debajo es TOML, YAML o cualquier otro formato — cumpliendo
el requisito explícito de "que todas las partes puedan manipularlo sin saber cómo está
guardado".

## 5. Filosofía general: el usuario tiene el control sobre todo

Principio explícito que atraviesa config, puertos, y políticas: nada crítico queda
hardcodeado si el usuario puede querer editarlo. Puertos de harnesses, políticas de
fallo, y (a futuro) políticas de selección son todos editables vía `config/janus.toml`.

---

## Documentos relacionados
- `agents/03-skills-y-config.md` — los schemas de configuración por agente
  (`agent.toml`) que extienden esta base, incluida la validación como barrera
  obligatoria.
- `stack/07-descubrimiento-y-capacidades.md` — la configuración de harnesses base en
  `config/janus.toml`.
- `stack/09-politicas-de-fallo.md` — las políticas de fallo declaradas en la misma
  config.
