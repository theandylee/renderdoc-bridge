---
name: renderdoc-bridge
description: Inspect a live RenderDoc capture (frame structure, draws, textures, pipeline state) via the renderdoc-bridge extension's localhost HTTP API. Use when the user asks about a RenderDoc capture, frame contents, drawcalls, GPU resources, or says the bridge/server is running in RenderDoc.
---

# RenderDoc Bridge

A RenderDoc UI extension an agent can query over localhost HTTP to inspect the open capture.
The human runs RenderDoc and starts the bridge (`Tools -> Agent Bridge -> Start bridge`,
or Run `__init__.py` from the Python panel); the agent does everything below from its own side.

## Connection

- Base: `http://127.0.0.1:38921`, token `renderdoc-bridge`
- Auth: `?token=renderdoc-bridge` query param or `X-Bridge-Token` header. No token -> 403 JSON.
- Binds localhost only. Use `fetch` — it reaches localhost directly, takes JSON bodies inline,
  and parallelizes with `Promise.all`.

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

## Bundled client

`scripts/rdc.js` (node 18+, no dependencies) wraps the endpoints so you don't hand-roll
fetch calls. From a shell:

- `node rdc.js status` — liveness + capture (start here)
- `node rdc.js reports` — available analyses
- `node rdc.js report frame_overview` / `node rdc.js report pass_tree '{"depth":2}'`
- `node rdc.js exec snippet.py` — or pipe code via stdin
- `node rdc.js shutdown` — hand the port back

Prefer `/report/*` over `/exec` for standard questions — one call, no code to write.

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
