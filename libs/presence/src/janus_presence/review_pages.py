"""HTML of the local review page (SPEC.md ampliación, requisito 39).

Server rendered HTML with one stylesheet and one small script. The page works
without the script (every button is a plain form post); the script only makes
the buttons update the page in place instead of reloading it. It is served
from the same origin and the Content-Security-Policy the app sends allows
scripts and requests from `'self'` only, so an injected value still has
nothing to run: there is no inline script or handler anywhere, and every value
that comes from the database goes through `_e` before it reaches the markup.

Everything that comes from the database (names, roles, source ids, error
text) is escaped that way. The pages take plain view objects, never the
service or the store.

The look follows the "Design System Blueprint" tokens: semantic colours, a 4px
spacing scale, a modular type scale, one button family (primary, secondary,
ghost) with every state defined, and short ease-out transitions.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime

__all__ = [
    "APP_SCRIPT",
    "FLASH_MESSAGES",
    "STYLESHEET",
    "EvidenceItem",
    "PersonGroup",
    "SourceRow",
    "login_page",
    "review_page",
]

_MAX_ERROR_CHARS = 200
_SHORT_ID_CHARS = 8

# A person seen for a few minutes can pile up over a hundred pending rows, and
# a wall of buttons hides what matters. Only the newest rows stay open; the
# rest fold into a <details>, which needs no script.
_VISIBLE_EVIDENCE = 5

# Bands for the similarity shown next to a guess. The confidence they read is a
# monotonic placeholder (PresenceService._confidence_from_distance), not a
# calibrated probability, so the page says "parecido" and keeps the number in a
# tooltip instead of presenting "0.00" as if it meant something.
_STRONG_SIMILARITY = 0.6
_WEAK_SIMILARITY = 0.25

# Forms that must leave the page (or start a session) and so are never sent in
# the background by the script.
_PLAIN_ACTIONS = frozenset({"/login", "/logout"})

# The page only ever shows a message from this table, chosen by a short code in
# the query string, so a crafted link cannot put text of its own on the page.
FLASH_MESSAGES = {
    "named": "Nombre guardado.",
    "role": "Rol guardado.",
    "confirmed": "Evidencia confirmada.",
    "rejected": "Evidencia rechazada.",
    "discarded": "Evidencia descartada.",
    "merged": "Personas fusionadas.",
    "bulk_confirm": "Todas las apariciones confirmadas.",
    "bulk_reject": "Todas las apariciones rechazadas.",
    "bulk_discard": "Todas las apariciones descartadas.",
    "settings": "Ajustes guardados. Aplican a las próximas detecciones.",
    "refused": "La acción fue rechazada. Si la persona no tiene nombre, nómbrala primero.",
    "invalid": "Los datos enviados no son válidos.",
}
_FAILURE_FLASHES = frozenset({"refused", "invalid"})

_STATE_LABELS = {
    "unknown": "Desconocida",
    "provisional": "Provisional",
    "established": "Establecida",
}
_STATE_BADGES = {
    "unknown": "badge-neutral",
    "provisional": "badge-warning",
    "established": "badge-success",
}
_SOURCE_STATE_LABELS = {
    "starting": "Iniciando",
    "up": "Activa",
    "down": "Caída",
    "stopped": "Detenida",
}
_SOURCE_STATE_BADGES = {
    "starting": "badge-warning",
    "up": "badge-success",
    "down": "badge-error",
    "stopped": "badge-neutral",
}

_ACTION_LEGEND = (
    '<p class="card legend"><strong>Confirmar</strong> dice que la aparición es de la '
    "persona de la tarjeta y refuerza su reconocimiento. <strong>Rechazar</strong> dice que "
    "no es la persona sugerida y evita que se proponga otra vez. <strong>Descartar</strong> "
    "la ignora sin aprender nada.</p>"
)

# (decision, button label, verb for the confirmation question, variant)
_BULK_ACTIONS = (
    ("confirm", "Confirmar todas", "confirmar", "secondary"),
    ("reject", "Rechazar todas", "rechazar", "secondary"),
    ("discard", "Descartar todas", "descartar", "ghost"),
)

APP_SCRIPT = r"""\
"use strict";
// Sends the page's forms in the background and swaps the result in, so a
// button press no longer reloads the whole page. Without this script every
// form still works as a normal post.
(function () {
  var busy = false;

  function swapPage(markup) {
    var next = new DOMParser().parseFromString(markup, "text/html");
    var incoming = next.querySelector("main");
    var current = document.querySelector("main");
    if (!incoming || !current) {
      return false;
    }
    var top = window.scrollY;
    var replacement = document.adoptNode(incoming);
    keepLiveView(current, replacement);
    current.replaceWith(replacement);
    document.title = next.title;
    window.scrollTo(0, top);
    return true;
  }

  // The live view is one open video stream. Rebuilding its <img> with the rest
  // of the page would cut it and start it again, so the element already on
  // screen is moved into the new page instead.
  function keepLiveView(current, replacement) {
    var kept = current.querySelector("details.live");
    var fresh = replacement.querySelector("details.live");
    if (kept && fresh) {
      fresh.replaceWith(kept);
    }
  }

  function send(form) {
    form.setAttribute("aria-busy", "true");
    return fetch(form.action, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(new FormData(form)).toString()
    }).then(function (response) {
      if (new URL(response.url).pathname === "/login") {
        window.location.assign("/login");
        return null;
      }
      return response.text().then(function (markup) {
        if (!swapPage(markup)) {
          window.location.reload();
        }
      });
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.hasAttribute("data-async")) {
      return;
    }
    event.preventDefault();
    var question = form.getAttribute("data-confirm");
    if (busy || (question && !window.confirm(question))) {
      return;
    }
    busy = true;
    send(form)
      .catch(function () {
        form.submit();
      })
      .then(function () {
        busy = false;
        form.removeAttribute("aria-busy");
      });
  });
})();
"""

STYLESHEET = """\
:root {
  color-scheme: dark light;
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
  --space-6: 24px; --space-8: 32px; --space-12: 48px;
  --radius-sm: 6px; --radius-md: 10px; --radius-pill: 999px;
  --text-xs: 11px; --text-sm: 13px; --text-base: 15px; --text-lg: 18px; --text-2xl: 22px;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1); --duration-fast: 150ms; --duration-small: 200ms;
  --bg-primary: #09090b; --bg-surface: #131316; --bg-raised: #1c1c21;
  --border-default: #27272a; --border-strong: #3f3f46;
  --text-primary: #fafafa; --text-muted: #a1a1aa;
  --brand-primary: #6366f1; --brand-solid: #4f46e5; --brand-hover: #4338ca;
  --brand-active: #3730a3; --brand-fg: #a5b4fc; --brand-soft: rgba(99, 102, 241, 0.18);
  --status-success: #22c55e; --status-error: #ef4444; --status-warning: #f59e0b;
  --success-soft: rgba(34, 197, 94, 0.14); --error-soft: rgba(239, 68, 68, 0.16);
  --warning-soft: rgba(245, 158, 11, 0.16);
}
@media (prefers-color-scheme: light) {
  :root {
    --bg-primary: #fafafa; --bg-surface: #ffffff; --bg-raised: #f4f4f5;
    --border-default: #e4e4e7; --border-strong: #d4d4d8;
    --text-primary: #18181b; --text-muted: #52525b;
    --brand-primary: #4f46e5; --brand-fg: #4338ca; --brand-soft: rgba(79, 70, 229, 0.10);
    --status-success: #15803d; --status-error: #dc2626; --status-warning: #b45309;
    --success-soft: rgba(21, 128, 61, 0.10); --error-soft: rgba(220, 38, 38, 0.10);
    --warning-soft: rgba(180, 83, 9, 0.12);
  }
}
* { box-sizing: border-box; }
body { margin: 0; padding: var(--space-6) var(--space-4) var(--space-12);
  background: var(--bg-primary); color: var(--text-primary);
  font-family: Inter, system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: var(--text-base); line-height: 1.6; }
main { max-width: 960px; margin: 0 auto; }
h1, h2, h3, h4 { margin: 0; line-height: 1.25; }
h1 { font-size: var(--text-2xl); font-weight: 700; }
h2 { font-size: var(--text-lg); font-weight: 600; margin: var(--space-8) 0 var(--space-3); }
h3 { font-size: var(--text-lg); font-weight: 600; }
section > h2 { margin: 0 0 var(--space-3); }
h4 { font-size: var(--text-base); font-weight: 600; margin: var(--space-6) 0 var(--space-1);
  display: flex; align-items: center; gap: var(--space-2); }
p { margin: 0; }
.topbar { display: flex; justify-content: space-between; align-items: flex-start;
  gap: var(--space-4); margin-bottom: var(--space-4); }
section, .card { background: var(--bg-surface); border: 1px solid var(--border-default);
  border-radius: var(--radius-md); padding: var(--space-6); margin: var(--space-4) 0; }
.muted { color: var(--text-muted); font-size: var(--text-sm); line-height: 1.5; }
.hint { color: var(--text-muted); font-size: var(--text-sm); margin-top: var(--space-2); }
.legend { color: var(--text-muted); font-size: var(--text-sm); padding: var(--space-4); }
.legend strong { color: var(--text-primary); font-weight: 600; }
.flash { position: sticky; top: var(--space-3); z-index: 10;
  padding: var(--space-3) var(--space-4); border-left: 4px solid var(--brand-primary);
  animation: rise var(--duration-small) var(--ease-out); }
.flash-bad { border-left-color: var(--status-error); }
.login { max-width: 420px; margin: var(--space-12) auto 0; }
.login .card { margin-top: var(--space-6); display: grid; gap: var(--space-4); }
.field { display: grid; gap: var(--space-1); font-weight: 500; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th { color: var(--text-muted); font-size: var(--text-sm); font-weight: 500; text-align: left; }
th, td { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border-default); }
tbody tr:last-child td { border-bottom: 0; }
.person { display: grid; grid-template-columns: 176px 1fr; gap: var(--space-6);
  scroll-margin-top: 72px; }
.person-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.person img { max-width: 100%; height: auto; border-radius: var(--radius-sm); }
.person > div:first-child img { width: 100%; border: 1px solid var(--border-default); }
.nophoto { display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: var(--space-1); min-height: 120px; padding: var(--space-3); text-align: center;
  color: var(--text-muted); font-size: var(--text-sm); line-height: 1.4;
  border: 1px dashed var(--border-strong); border-radius: var(--radius-sm); }
.nophoto strong { color: var(--text-primary); font-weight: 600; }
.count { background: var(--bg-raised); border: 1px solid var(--border-default);
  border-radius: var(--radius-pill); padding: 0 var(--space-2); font-size: var(--text-sm);
  font-weight: 500; color: var(--text-muted); }
.suggestion { display: flex; flex-wrap: wrap; align-items: center;
  justify-content: space-between; gap: var(--space-3); margin-top: var(--space-4);
  padding: var(--space-3) var(--space-4); background: var(--brand-soft);
  border: 1px solid var(--brand-primary); border-radius: var(--radius-sm); }
.bulk { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2);
  margin-top: var(--space-4); }
.bulk .muted { margin-right: var(--space-2); }
.evidence-list { list-style: none; margin: 0; padding: 0; }
.evidence { display: flex; flex-wrap: wrap; justify-content: space-between;
  align-items: center; gap: var(--space-3) var(--space-4); padding: var(--space-3) 0;
  border-top: 1px solid var(--border-default); }
.evidence-main { display: flex; align-items: center; gap: var(--space-4); }
.thumb { flex: none; width: 96px; height: 96px; object-fit: cover;
  background: var(--bg-raised); border: 1px solid var(--border-default);
  border-radius: var(--radius-sm); }
.evidence-info { display: flex; flex-direction: column; gap: var(--space-1); }
.evidence-when { font-weight: 500; }
.guess { color: var(--text-muted); font-size: var(--text-sm); }
.actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
form.inline { display: inline-flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; }
form[aria-busy=true] { opacity: 0.6; pointer-events: none; }
.name-form { margin-top: var(--space-3); }
details.more { margin-top: var(--space-2); }
details.more summary { cursor: pointer; color: var(--brand-fg); font-weight: 500;
  padding: var(--space-2) 0; }
.settings summary { cursor: pointer; font-weight: 600; }
.live summary { cursor: pointer; font-weight: 600; }
.live-grid { display: flex; flex-wrap: wrap; gap: var(--space-4); margin-top: var(--space-3); }
.live-frame { flex: 1 1 320px; margin: 0; }
.live-frame img { width: 100%; height: auto; background: var(--bg-raised);
  border: 1px solid var(--border-default); border-radius: var(--radius-sm); }
.live-frame figcaption { margin-top: var(--space-1); }
.settings p { margin-top: var(--space-3); }
.settings-form { display: flex; flex-wrap: wrap; align-items: flex-end;
  gap: var(--space-4); margin-top: var(--space-4); }
.badge { display: inline-flex; align-items: center; padding: 2px var(--space-2);
  border-radius: var(--radius-pill); font-size: var(--text-sm); font-weight: 500;
  line-height: 1.2; border: 1px solid transparent; }
.badge-neutral { color: var(--text-muted); border-color: var(--border-strong); }
.badge-brand { color: var(--brand-fg); background: var(--brand-soft); }
.badge-success { color: var(--status-success); background: var(--success-soft); }
.badge-error { color: var(--status-error); background: var(--error-soft); }
.badge-warning { color: var(--status-warning); background: var(--warning-soft); }
.btn, input[type=text], input[type=password], input[type=number] { font-family: inherit;
  font-size: var(--text-base); line-height: 1.2; min-height: 36px;
  border-radius: var(--radius-sm); }
.btn { padding: var(--space-2) var(--space-4); font-weight: 500; cursor: pointer;
  border: 1px solid transparent;
  transition: background var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out); }
.btn-primary { background: var(--brand-solid); color: #fff; }
.btn-primary:hover { background: var(--brand-hover); }
.btn-primary:active { background: var(--brand-active); }
.btn-secondary { background: var(--bg-raised); color: var(--text-primary);
  border-color: var(--border-strong); }
.btn-secondary:hover { border-color: var(--brand-primary); }
.btn-ghost { background: transparent; color: var(--text-muted); }
.btn-ghost:hover { background: var(--bg-raised); color: var(--text-primary); }
.btn[disabled] { cursor: not-allowed; opacity: 0.45; }
.btn-primary[disabled]:hover { background: var(--brand-solid); }
.btn-secondary[disabled]:hover { background: var(--bg-raised);
  border-color: var(--border-strong); }
input[type=text], input[type=password], input[type=number] {
  padding: var(--space-2) var(--space-3);
  background: var(--bg-primary); color: var(--text-primary);
  border: 1px solid var(--border-strong);
  transition: border-color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out); }
input[type=number] { width: 8rem; }
input[type=text]:focus, input[type=password]:focus, input[type=number]:focus {
  outline: none; border-color: var(--brand-primary); box-shadow: 0 0 0 3px var(--brand-soft); }
.btn:focus-visible, summary:focus-visible { outline: 2px solid var(--brand-primary);
  outline-offset: 2px; }
.bad { color: var(--status-error); }
@keyframes rise { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; } }
@media (pointer: coarse) {
  .btn, input[type=text], input[type=password], input[type=number] { min-height: 44px; }
}
@media (max-width: 640px) {
  .person { grid-template-columns: 1fr; }
  .topbar { flex-wrap: wrap; }
}
@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
"""


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    captured_at: datetime
    source_id: str
    # Who the system suspects this is, when it suspects somebody (requisito 27).
    hypothesis_label: str | None = None
    hypothesis_confidence: float | None = None
    hypothesis_person_id: str | None = None
    # Whether a face thumbnail was kept for this appearance.
    has_thumb: bool = False


@dataclass(frozen=True)
class PersonGroup:
    person_id: str
    label: str | None
    state: str
    role: str | None
    has_snapshot: bool
    first_seen_at: datetime
    last_seen_at: datetime
    evidence: tuple[EvidenceItem, ...]
    # The named person most of this group's evidence points at: the page offers
    # to merge this person into them.
    suggested_person_id: str | None = None
    suggested_label: str | None = None


@dataclass(frozen=True)
class SourceRow:
    source_id: str
    state: str
    last_frame_at: datetime | None
    consecutive_failures: int
    processing_errors: int
    last_error: str | None


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _when(moment: datetime | None) -> str:
    if moment is None:
        return "nunca"
    return moment.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _similarity(confidence: float) -> str:
    if confidence >= _STRONG_SIMILARITY:
        return "parecido alto"
    if confidence >= _WEAK_SIMILARITY:
        return "parecido medio"
    return "parecido bajo"


def _layout(title: str, body: str, with_script: bool = False) -> str:
    script = '<script src="/app.js" defer></script>' if with_script else ""
    return (
        '<!doctype html>\n<html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="dark light">'
        '<meta name="robots" content="noindex, nofollow">'
        f'<title>{_e(title)}</title><link rel="stylesheet" href="/style.css">{script}'
        f"</head><body><main>{body}</main></body></html>"
    )


def _post_form(
    action: str,
    csrf: str,
    hidden: dict[str, str],
    button: str,
    *,
    variant: str = "secondary",
    disabled_reason: str | None = None,
    confirm: str | None = None,
) -> str:
    fields = f'<input type="hidden" name="csrf" value="{_e(csrf)}">'
    fields += "".join(
        f'<input type="hidden" name="{_e(name)}" value="{_e(value)}">'
        for name, value in hidden.items()
    )
    disabled = f' disabled title="{_e(disabled_reason)}"' if disabled_reason else ""
    background = "" if action in _PLAIN_ACTIONS else " data-async"
    question = f' data-confirm="{_e(confirm)}"' if confirm else ""
    return (
        f'<form method="post" action="{_e(action)}" class="inline"{background}{question}>'
        f'{fields}<button type="submit" class="btn btn-{variant}"{disabled}>{_e(button)}'
        "</button></form>"
    )


def login_page(error: str | None = None) -> str:
    message = f'<p class="bad" role="alert">{_e(error)}</p>' if error else ""
    body = (
        '<div class="login"><h1>Janus Presence</h1>'
        '<div class="card"><p class="muted">Pega el token del runner para entrar. Está en el '
        "archivo de token que indica la configuración.</p>"
        '<form method="post" action="/login" class="field">'
        '<label class="field">Token <input type="password" name="token" required '
        'autocomplete="off" autofocus></label>'
        '<button type="submit" class="btn btn-primary">Entrar</button></form>'
        f"{message}</div></div>"
    )
    return _layout("Janus Presence: acceso", body)


def _sources_section(sources: list[SourceRow]) -> str:
    if not sources:
        return '<section><h2>Fuentes</h2><p class="muted">Sin cámaras activas.</p></section>'
    rows = "".join(_source_row(source) for source in sources)
    return (
        '<section><h2>Fuentes</h2><div class="table-wrap"><table><thead><tr><th>Fuente</th>'
        "<th>Estado</th><th>Último frame</th><th>Fallos</th><th>Errores</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></section>"
    )


def _source_row(source: SourceRow) -> str:
    css = _SOURCE_STATE_BADGES.get(source.state, "badge-neutral")
    state = _SOURCE_STATE_LABELS.get(source.state, source.state)
    detail = ""
    if source.last_error:
        detail = f'<br><span class="muted">{_e(source.last_error[:_MAX_ERROR_CHARS])}</span>'
    return (
        f"<tr><td>{_e(source.source_id)}</td>"
        f'<td><span class="badge {css}">{_e(state)}</span>{detail}</td>'
        f"<td>{_e(_when(source.last_frame_at))}</td>"
        f"<td>{source.consecutive_failures}</td><td>{source.processing_errors}</td></tr>"
    )


def _photo(group: PersonGroup) -> str:
    if group.has_snapshot:
        return f'<img src="/snapshot/{_e(group.person_id)}" alt="Foto retenida de la persona">'
    # Naming a person deletes the retained photo (requisito 12), so the two
    # cases have different reasons and the page says which one applies.
    if group.label:
        reason = "Se borra al ponerle nombre a la persona, o cuando vence el plazo de retención."
    else:
        reason = (
            "No se guardó: la primera detección no tuvo calidad suficiente, "
            "o venció el plazo de retención."
        )
    return f'<div class="nophoto"><strong>Sin foto</strong><span>{reason}</span></div>'


def _name_form(group: PersonGroup, csrf: str) -> str:
    return (
        '<form method="post" action="/name" class="inline name-form" data-async>'
        f'<input type="hidden" name="csrf" value="{_e(csrf)}">'
        f'<input type="hidden" name="person_id" value="{_e(group.person_id)}">'
        f'<input type="hidden" name="back" value="{_e(group.person_id)}">'
        '<label>Nombre <input type="text" name="label" maxlength="64" required '
        f'autocomplete="off" value="{_e(group.label or "")}"></label>'
        '<button type="submit" class="btn btn-secondary">Guardar nombre</button></form>'
    )


def _role_form(group: PersonGroup, csrf: str) -> str:
    """Only for a named person: the role is what a Home Assistant automation
    matches, and it means nothing for someone nobody has named yet."""
    if not group.label:
        return ""
    return (
        '<form method="post" action="/role" class="inline name-form" data-async>'
        f'<input type="hidden" name="csrf" value="{_e(csrf)}">'
        f'<input type="hidden" name="person_id" value="{_e(group.person_id)}">'
        f'<input type="hidden" name="back" value="{_e(group.person_id)}">'
        '<label>Rol <input type="text" name="role" maxlength="32" required '
        'pattern="[A-Za-z][A-Za-z0-9_\\-]*" placeholder="owner" autocomplete="off" '
        f'value="{_e(group.role or "")}"></label>'
        '<button type="submit" class="btn btn-secondary">Guardar rol</button></form>'
    )


def _merge_prompt(group: PersonGroup, csrf: str) -> str:
    if group.suggested_person_id is None or not group.suggested_label:
        return ""
    name = group.suggested_label
    hidden = {
        "person_id": group.person_id,
        "target_id": group.suggested_person_id,
        "back": group.suggested_person_id,
    }
    question = f"¿Fusionar con {name}? Esta persona desaparece y sus apariciones pasan a {name}."
    form = _post_form("/merge", csrf, hidden, f"Sí, es {name}", variant="primary", confirm=question)
    return (
        f'<div class="suggestion"><p>Parece ser <strong>{_e(name)}</strong>. Si ya la tienes '
        f"registrada, fusiónalas.</p>{form}</div>"
    )


def _bulk_bar(group: PersonGroup, csrf: str) -> str:
    count = len(group.evidence)
    if count < 2:
        return ""
    who = group.label or "esta persona"
    unnamed = "Nombra a la persona antes de confirmar" if group.state == "unknown" else None
    forms = []
    for decision, label, verb, variant in _BULK_ACTIONS:
        hidden = {"person_id": group.person_id, "decision": decision, "back": group.person_id}
        question = f"¿Seguro que quieres {verb} las {count} apariciones de {who}?"
        reason = unnamed if decision == "confirm" else None
        forms.append(
            _post_form(
                "/bulk",
                csrf,
                hidden,
                label,
                variant=variant,
                disabled_reason=reason,
                confirm=question,
            )
        )
    buttons = "".join(forms)
    return f'<div class="bulk"><span class="muted">Las {count} a la vez:</span>{buttons}</div>'


def _guess(item: EvidenceItem) -> str:
    if item.hypothesis_label is None or item.hypothesis_confidence is None:
        return ""
    return (
        f'<span class="guess" title="confianza {item.hypothesis_confidence:.2f}">'
        f"Podría ser {_e(item.hypothesis_label)} "
        f'<span class="badge badge-neutral">{_similarity(item.hypothesis_confidence)}</span>'
        "</span>"
    )


def _thumb(item: EvidenceItem) -> str:
    if not item.has_thumb:
        return ""
    return (
        f'<img class="thumb" src="/evidence/{_e(item.evidence_id)}/thumb" '
        'alt="Cara detectada" width="96" height="96" loading="lazy">'
    )


def _evidence_row(item: EvidenceItem, group: PersonGroup, csrf: str) -> str:
    # `back` lets the redirect land on this person's card, for the case where
    # the script is not running and the whole document reloads.
    hidden = {"evidence_id": item.evidence_id, "back": group.person_id}
    unnamed = "Nombra a la persona antes de confirmar" if group.state == "unknown" else None
    actions = (
        _post_form(
            "/confirm", csrf, hidden, "Confirmar", variant="primary", disabled_reason=unnamed
        )
        + _post_form("/reject", csrf, hidden, "Rechazar")
        + _post_form("/discard", csrf, hidden, "Descartar", variant="ghost")
    )
    return (
        f'<li class="evidence"><div class="evidence-main">{_thumb(item)}'
        '<div class="evidence-info">'
        f'<span class="evidence-when">{_e(_when(item.captured_at))}</span>'
        f'<span class="muted">Cámara {_e(item.source_id)}</span>{_guess(item)}</div></div>'
        f'<div class="actions">{actions}</div></li>'
    )


def _evidence_list(group: PersonGroup, csrf: str) -> str:
    visible = group.evidence[:_VISIBLE_EVIDENCE]
    folded = group.evidence[_VISIBLE_EVIDENCE:]
    shown = "".join(_evidence_row(item, group, csrf) for item in visible)
    listing = f'<ul class="evidence-list">{shown}</ul>'
    if not folded:
        return listing
    rows = "".join(_evidence_row(item, group, csrf) for item in folded)
    return (
        f'{listing}<details class="more"><summary>Ver {len(folded)} más antiguas</summary>'
        f'<ul class="evidence-list">{rows}</ul></details>'
    )


def _live_section(sources: list[SourceRow]) -> str:
    """The live video of every camera that is up: a motion JPEG the browser plays
    by itself, no reload and no script. Each frame is the one the detector would
    see, so what you watch is what it sees. It sits behind the login like
    everything else."""
    frames = "".join(
        '<figure class="live-frame"><img '
        f'src="/camera/{_e(source.source_id)}/stream" '
        f'alt="Cámara {_e(source.source_id)}"><figcaption class="muted">'
        f"{_e(source.source_id)}</figcaption></figure>"
        for source in sources
        if source.state == "up"
    )
    if not frames:
        return ""
    return (
        '<details class="card live" open><summary>Cámara en vivo</summary>'
        f'<div class="live-grid">{frames}</div>'
        '<p class="hint">Video en vivo, unos 8 cuadros por segundo. Cierra la pestaña '
        "para dejar de transmitir.</p></details>"
    )


def _person_badges(group: PersonGroup) -> str:
    state = _STATE_LABELS.get(group.state, group.state)
    css = _STATE_BADGES.get(group.state, "badge-neutral")
    badges = f'<span class="badge {css}">{_e(state)}</span>'
    if group.role:
        badges += f'<span class="badge badge-brand">rol {_e(group.role)}</span>'
    return badges


def _person_section(group: PersonGroup, csrf: str) -> str:
    title = group.label or "Persona sin nombre"
    short_id = group.person_id[:_SHORT_ID_CHARS]
    hint = ""
    if group.state == "unknown":
        hint = '<p class="hint">Ponle un nombre para poder confirmar sus apariciones.</p>'
    return (
        f'<section class="person" id="p-{_e(group.person_id)}"><div>{_photo(group)}</div><div>'
        f'<div class="person-head"><h3>{_e(title)}</h3>{_person_badges(group)}</div>'
        f'<p class="muted">Vista por primera vez {_e(_when(group.first_seen_at))}, '
        f"por última vez {_e(_when(group.last_seen_at))} · id {_e(short_id)}</p>"
        f"{_name_form(group, csrf)}{_role_form(group, csrf)}{hint}{_merge_prompt(group, csrf)}"
        f'<h4>Pendiente de revisión <span class="count">{len(group.evidence)}</span></h4>'
        f"{_evidence_list(group, csrf)}{_bulk_bar(group, csrf)}</div></section>"
    )


def _summary(groups: list[PersonGroup]) -> str:
    total = sum(len(group.evidence) for group in groups)
    return (
        f'<p class="muted">{_plural(len(groups), "persona", "personas")} · '
        f"{_plural(total, 'aparición', 'apariciones')} por revisar</p>"
    )


def _banner(flash_code: str | None) -> str:
    flash = FLASH_MESSAGES.get(flash_code or "")
    if flash is None:
        return ""
    css = "flash flash-bad" if flash_code in _FAILURE_FLASHES else "flash"
    return f'<p class="card {css}" role="status">{_e(flash)}</p>'


def _people_section(groups: list[PersonGroup], csrf: str) -> str:
    if not groups:
        return '<section><p class="muted">No hay nada pendiente de revisión.</p></section>'
    return _ACTION_LEGEND + "".join(_person_section(group, csrf) for group in groups)


def _settings_section(csrf: str, thresholds: tuple[float, float] | None) -> str:
    if thresholds is None:
        return ""
    match, ambiguous = thresholds
    number = 'type="number" step="any" min="0" max="4" required'
    return (
        '<details class="card settings"><summary>Ajustes de coincidencia</summary>'
        '<p class="muted">Distancia máxima entre dos caras para decidir si son la misma '
        "persona. Más bajo es más estricto y crea más personas nuevas; más alto es más "
        "permisivo y puede mezclar personas distintas. Aplica a las próximas detecciones; "
        "para las que ya existen usa fusionar.</p>"
        '<form method="post" action="/settings" class="settings-form" data-async>'
        f'<input type="hidden" name="csrf" value="{_e(csrf)}">'
        f'<label class="field">Misma persona hasta <input {number} '
        f'name="match_threshold" value="{match:g}"></label>'
        f'<label class="field">Zona ambigua hasta <input {number} '
        f'name="match_threshold_ambiguous" value="{ambiguous:g}"></label>'
        '<button type="submit" class="btn btn-primary">Guardar ajustes</button>'
        "</form></details>"
    )


def review_page(
    groups: list[PersonGroup],
    sources: list[SourceRow],
    csrf: str,
    flash_code: str | None = None,
    thresholds: tuple[float, float] | None = None,
) -> str:
    logout = _post_form("/logout", csrf, {}, "Salir", variant="ghost")
    body = (
        f'<header class="topbar"><div><h1>Janus Presence</h1>{_summary(groups)}</div>'
        f"{logout}</header>"
        f"{_banner(flash_code)}{_sources_section(sources)}{_live_section(sources)}"
        f"<h2>Revisión pendiente</h2>{_people_section(groups, csrf)}"
        f"{_settings_section(csrf, thresholds)}"
    )
    return _layout("Janus Presence: revisión", body, with_script=True)
