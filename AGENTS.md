# Developing renderdoc-bridge

Single-file RenderDoc UI extension (`__init__.py` + `extension.json`) exposing the open
capture over localhost HTTP. Agent *usage* is documented in
`skills/renderdoc-bridge/SKILL.md` — this file is for changing the bridge itself.

## Hard constraints

- Stdlib only. RenderDoc embeds its own Python (3.8 in current builds); no pip packages.
- No `__file__`, no `os.path` tricks. The scripting panel's Run button execs the source
  without setting `__file__` — everything must work in a bare namespace with only
  `pyrenderdoc` pre-filled.
- Python 3.6-compatible syntax (f-strings OK, nothing newer).
- The HTTP server thread must never block the UI thread: daemon thread, localhost only.

## Adding an analysis

New pre-made tool = new `rep_*` function returning plain dicts/lists/numbers/strings
registered in `_REPORTS`. It becomes a `/report/<name>` endpoint with no other changes.
`_jsonable` stringifies anything non-plain, so keep returns clean instead.

## Verifying

- `python -B -m py_compile __init__.py`
- Logic: stub-harness via `exec(compile(src, ...))` in a dict with **no `__file__`**,
  stub `renderdoc` module in `sys.modules`, fake actions/textures/context. Assert report
  shapes, menu registration, and start/stop callbacks. Throw the harness away after.
- Menu items (`Tools -> Agent Bridge`) register in `register()` only, never on script Run,
  to avoid duplicates. Verify `RegisterWindowMenu` calls against the live API if unsure.
- After edits: reload the extension from RenderDoc's status bar, or re-press Run.

## Commits

Lowercase short messages (`initial-commit`, `add-agent-briefing`). Push `main` when done.
