# RenderDoc agent bridge

Single-file localhost HTTP server that runs **inside RenderDoc** (embedded Python,
stdlib only, no `__file__` dependency so it works from the scripting panel's Run button)
so the agent can inspect the open capture: status, current event, and arbitrary
read-only Python snippets via `/exec`.

Binds `127.0.0.1:38921` only. Token: `renderdoc-bridge` (see `TOKEN` in `__init__.py`).

## Quick run (no restart)

1. RenderDoc: `Window -> Python Scripting`
2. Load `__init__.py`, press `Run`
3. Output panel shows the status URL. Tell the agent, it polls the port from here.

## Persistent (auto-start, recommended)

1. Clone this repo (or copy this folder) to
   `%APPDATA%\qrenderdoc\extensions\renderdoc_bridge\`
2. RenderDoc: `Tools -> Manage Extensions`, tick `Enable` for `RenderDoc Bridge`
3. Restart RenderDoc. The bridge auto-starts, and you get
   `Tools -> Agent Bridge -> Start bridge / Stop bridge / Show status`.
   Update with `git pull`; after editing, reload via the status-bar button.

## Protocol

- `GET /status?token=renderdoc-bridge` — capture loaded, filename, current event id + name
- `GET /reports?token=renderdoc-bridge` — available pre-made analyses
- `GET /report/<name>?token=...&params={...}` — run one, e.g. `frame_overview`,
  `pass_tree`, `texture_report`, `draw_report`. New analyses are new `rep_*`
  functions registered in `_REPORTS`, returning plain dicts/lists
- `POST /exec?token=renderdoc-bridge` with `{"code": "..."}` — runs code with
  `pyrenderdoc`/`ctx`/`_reports` (+ `renderdoc`, `qrenderdoc` if importable), returns
  `{ok, output, error}`
- `GET /shutdown?token=renderdoc-bridge` — stop the server (before restarting it)

Query example (agent side): `curl "http://127.0.0.1:38921/status?token=renderdoc-bridge"`

Agent usage briefing: `skills/renderdoc-bridge/SKILL.md`. Bridge development notes: `AGENTS.md`.

Note: `/exec` runs on a server thread. Reads (event names, action tree,
pipeline state) are fine; avoid issuing replays from two places at once.
