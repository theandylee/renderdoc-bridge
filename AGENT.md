# Agent briefing: RenderDoc bridge

This repo is a RenderDoc UI extension that exposes the open capture over localhost HTTP
so a coding agent can inspect frames. The human runs RenderDoc and starts the bridge
(`Tools -> Agent Bridge -> Start bridge`, or Run `__init__.py` from the Python panel);
the agent does everything below from its own side.

## Connection

- Base: `http://127.0.0.1:38921`, token `renderdoc-bridge`
- Auth: `?token=renderdoc-bridge` query param or `X-Bridge-Token` header. No token -> 403 JSON.
- Binds localhost only. If you use curl from a shell, prefer your JS `fetch` — it reaches
  localhost directly, takes JSON bodies inline, and parallelizes with `Promise.all`.

## Endpoints

- `GET /status` — `{capture_loaded, filename, cur_event, cur_event_name, reports[]}`.
  Always call first: confirms the bridge is up and tells you which capture/event the human sees.
- `GET /reports` — names of pre-made analyses.
- `GET /report/<name>?params=<urlencoded JSON>` — run one:
  - `frame_overview` — passes, flag counts, draw totals, tiny/instanced/zero-instance counts
  - `pass_tree` (`{depth, children}`) — nested pass/marker tree with draw counts
  - `texture_report` (`{top}`) — total MB, largest textures, MSAA targets
  - `draw_report` (`{max_indices, limit}`) — suspicious tiny/zero-instance draws with names
- `POST /exec` with `{"code": "..."}` — run Python inside RenderDoc, returns
  `{ok, output, error}`. Namespace: `pyrenderdoc` (= `ctx`, the CaptureContext),
  `renderdoc`, `qrenderdoc`, `_reports` (the report functions, callable directly).
- `GET /shutdown` — stop the server. Only call to hand the port back, never mid-session.

## /exec discipline

- Aggregate server-side, print small summaries. Never dump full action/texture lists.
- Probe APIs with `dir()` / `hasattr` before using unfamiliar members; wrap guesses in try/except.
- SWIG enums: `int(renderdoc.ActionFlags.Drawcall)` is `2`. Key values: Clear=1,
  Drawcall=2, Dispatch=4, Indexed=65536, Instanced=131072, Copy=1024, Present=256.
- `ctx.GetEventBrowser().GetEventName(eid)` gives readable names without moving selection.
- `ActionDescription` fields: `eventId, flags, children, numIndices, numInstances`.
- `TextureDescription` fields: `resourceId, byteSize, width, height, depth, arraysize,
  mips, msSamp, format`. Resolve names via `ctx.GetResourceName(resourceId)`.
- Avoid `SetEventID` unless the task needs per-event pipeline state — it moves the human's
  selection in the UI. Reads (tree walks, names, stats) are side-effect free.
- `/exec` runs on a server thread: fine for introspection, don't issue competing replays.

## Workflow

1. `/status` to confirm liveness + capture.
2. `frame_overview` + `texture_report` for the landscape.
3. `pass_tree` / `draw_report` to localize, then targeted `/exec` snippets.
4. Report findings with event IDs and names so the human can click to them.
