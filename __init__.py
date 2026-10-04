import io
import json
import sys
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

HOST = "127.0.0.1"
PORT = 38921
TOKEN = "renderdoc-bridge"
MAX_BODY = 1024 * 1024

try:
    import renderdoc as _rd
except ImportError:
    _rd = None

_server = None
_server_thread = None
_server_ctx = None


def _try_import(name):
    try:
        module = __import__(name)
        return module, True
    except Exception:
        return None, False


def _need_rd():
    if _rd is None:
        raise RuntimeError("renderdoc module not available")
    return _rd


def _flag_names(flags):
    AF = _need_rd().ActionFlags
    out = []
    for n in dir(AF):
        if n.startswith("_") or not n[0].isupper():
            continue
        v = int(getattr(AF, n))
        if v and (v & int(flags)):
            out.append(n)
    return out


def _is_draw(action):
    return bool(int(_need_rd().ActionFlags.Drawcall) & int(action.flags))


def _walk(actions):
    for a in actions:
        yield a
        for c in _walk(a.children):
            yield c


def rep_frame_overview(ctx):
    """Totals for the open capture: passes, draws, dispatches, clears, tiny/instanced draws."""
    eb = ctx.GetEventBrowser()
    roots = ctx.CurRootActions()
    counts = {}
    ndraw = 0
    tiny = 0
    instanced1 = 0
    zeroinst = 0
    maxdepth = 0
    stack = [(r, 0) for r in roots]
    while stack:
        a, depth = stack.pop()
        maxdepth = max(maxdepth, depth)
        names = _flag_names(a.flags)
        for n in names:
            counts[n] = counts.get(n, 0) + 1
        if _is_draw(a):
            ndraw += 1
            if a.numIndices < 36:
                tiny += 1
            if a.numInstances == 1 and "Instanced" in names:
                instanced1 += 1
            if a.numInstances == 0:
                zeroinst += 1
        stack.extend((c, depth + 1) for c in a.children)
    return {
        "passes": [
            {"eid": r.eventId, "name": eb.GetEventName(r.eventId), "direct_children": len(r.children)}
            for r in roots
        ],
        "flag_counts": counts,
        "draws": ndraw,
        "tiny_draws_lt36idx": tiny,
        "instanced_with_count_1": instanced1,
        "zero_instance_draws": zeroinst,
        "max_marker_depth": maxdepth,
    }


def _subtree_draws(action):
    n = 1 if _is_draw(action) else 0
    for c in action.children:
        n += _subtree_draws(c)
    return n


def rep_pass_tree(ctx, depth=3, children=25):
    """Nested pass/marker tree with draw counts. depth/children cap the output size."""
    eb = ctx.GetEventBrowser()

    def node(a, d):
        kids = []
        if d < depth:
            kids = [node(c, d + 1) for c in a.children[:children]]
        out = {"eid": a.eventId, "name": eb.GetEventName(a.eventId)[:160], "draws": _subtree_draws(a)}
        if kids:
            out["children"] = kids
            if len(a.children) > children:
                out["more_children"] = len(a.children) - children
        return out

    return [node(r, 0) for r in ctx.CurRootActions()]


def _format_name(fmt):
    for attr in ("name", "Name"):
        v = getattr(fmt, attr, None)
        if isinstance(v, str) and v:
            return v
    return "unknown"


def rep_texture_report(ctx, top=15):
    """Texture memory: total, largest first, MSAA targets."""
    rows = []
    for t in ctx.GetTextures():
        try:
            name = ctx.GetResourceName(t.resourceId)
        except Exception:
            name = "?"
        rows.append({
            "bytes": t.byteSize,
            "name": name,
            "w": t.width,
            "h": t.height,
            "depth": t.depth,
            "array": t.arraysize,
            "mips": t.mips,
            "msaa": t.msSamp,
            "format": _format_name(t.format),
        })
    rows.sort(key=lambda r: r["bytes"], reverse=True)
    total = sum(r["bytes"] for r in rows)
    return {
        "count": len(rows),
        "total_mb": round(total / 1048576.0, 1),
        "top": rows[:top],
        "msaa_targets": [r for r in rows if r["msaa"] > 1],
    }


def rep_draw_report(ctx, max_indices=6, limit=50):
    """Suspicious draws: tiny index counts and zero instance counts, with names."""
    eb = ctx.GetEventBrowser()
    tiny = []
    zeroinst = []
    for a in _walk(ctx.CurRootActions()):
        if not _is_draw(a):
            continue
        if a.numIndices <= max_indices and len(tiny) < limit:
            tiny.append({
                "eid": a.eventId,
                "indices": a.numIndices,
                "instances": a.numInstances,
                "name": eb.GetEventName(a.eventId)[:150],
            })
        if a.numInstances == 0 and len(zeroinst) < limit:
            zeroinst.append({
                "eid": a.eventId,
                "indices": a.numIndices,
                "name": eb.GetEventName(a.eventId)[:150],
            })
    return {"tiny": tiny, "zero_instance": zeroinst}


_REPORTS = {
    "frame_overview": rep_frame_overview,
    "pass_tree": rep_pass_tree,
    "texture_report": rep_texture_report,
    "draw_report": rep_draw_report,
}


def _safe_call(label, func, out):
    try:
        out[label] = func()
    except Exception as exc:
        out[label + "_error"] = repr(exc)


def collect_status():
    info = {
        "ok": True,
        "bridge": "renderdoc-bridge",
        "host": HOST,
        "port": PORT,
        "python": sys.version.split()[0],
    }
    _, info["renderdoc_module"] = _try_import("renderdoc")
    _, info["qrenderdoc_module"] = _try_import("qrenderdoc")
    info["reports"] = sorted(_REPORTS)

    ctx = _server_ctx
    if ctx is None:
        info["capture_loaded"] = False
        info["note"] = "no CaptureContext bound"
        return info

    _safe_call("capture_loaded", lambda: bool(ctx.IsCaptureLoaded()), info)
    if not info.get("capture_loaded"):
        return info

    _safe_call("filename", lambda: str(ctx.GetCaptureFilename()), info)
    _safe_call("cur_event", lambda: int(ctx.CurEvent()), info)

    def _event_name():
        eid = int(ctx.CurEvent())
        return str(ctx.GetEventBrowser().GetEventName(eid))

    _safe_call("cur_event_name", _event_name, info)
    return info


def run_code(code):
    namespace = {}
    ctx = _server_ctx
    if ctx is not None:
        namespace["pyrenderdoc"] = ctx
        namespace["ctx"] = ctx
    module, found = _try_import("renderdoc")
    if found:
        namespace["renderdoc"] = module
    module, found = _try_import("qrenderdoc")
    if found:
        namespace["qrenderdoc"] = module
    namespace["_reports"] = _REPORTS

    buffer = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buffer
    try:
        exec(compile(code, "<bridge>", "exec"), namespace)
    except Exception:
        return {"ok": False, "output": buffer.getvalue(), "error": traceback.format_exc()}
    finally:
        sys.stdout = old_stdout
    return {"ok": True, "output": buffer.getvalue(), "error": ""}


def _jsonable(obj):
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return str(obj)


def _run_report(name, params):
    if name not in _REPORTS:
        return {"ok": False, "error": "unknown report: " + name}
    try:
        result = _REPORTS[name](_server_ctx, **params)
    except Exception:
        return {"ok": False, "error": traceback.format_exc()}
    try:
        return {"ok": True, "result": _jsonable(result)}
    except Exception as exc:
        return {"ok": False, "error": "unserializable result: " + repr(exc)}


class _Handler(BaseHTTPRequestHandler):
    server_version = "RenderDocBridge/1.0"

    def log_message(self, fmt, *args):
        print("bridge: " + fmt % args)

    def _authorized(self):
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            return False
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        if params.get("token", [None])[0] == TOKEN:
            return True
        return self.headers.get("X-Bridge-Token") == TOKEN

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._authorized():
            self._send_json({"ok": False, "error": "unauthorized"}, status=403)
            return
        path = urllib.parse.urlparse(self.path).path
        if path == "/status":
            self._send_json(collect_status())
        elif path == "/reports":
            self._send_json({"ok": True, "reports": sorted(_REPORTS)})
        elif path.startswith("/report/"):
            name = path[len("/report/"):]
            query = urllib.parse.urlparse(self.path).query
            params = {}
            raw = urllib.parse.parse_qs(query).get("params", [""])[0]
            if raw:
                try:
                    params = json.loads(raw)
                except Exception as exc:
                    self._send_json({"ok": False, "error": "bad params json: " + repr(exc)}, status=400)
                    return
            if not isinstance(params, dict):
                self._send_json({"ok": False, "error": "params must be an object"}, status=400)
                return
            self._send_json(_run_report(name, params))
        elif path == "/shutdown":
            self._send_json({"ok": True, "note": "shutting down"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send_json({"ok": False, "error": "unknown endpoint: " + path}, status=404)

    def do_POST(self):
        if not self._authorized():
            self._send_json({"ok": False, "error": "unauthorized"}, status=403)
            return
        path = urllib.parse.urlparse(self.path).path
        if path != "/exec":
            self._send_json({"ok": False, "error": "unknown endpoint: " + path}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._send_json({"ok": False, "error": "bad body length"}, status=400)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            code = payload.get("code", "")
        except Exception as exc:
            self._send_json({"ok": False, "error": "bad json: " + repr(exc)}, status=400)
            return
        if not isinstance(code, str) or not code:
            self._send_json({"ok": False, "error": "missing 'code' string"}, status=400)
            return
        self._send_json(run_code(code))


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start(ctx=None, port=PORT, block=False):
    global _server, _server_thread, _server_ctx
    stop(quiet=True)
    _server_ctx = ctx
    try:
        _server = _Server((HOST, port), _Handler)
    except OSError as exc:
        print("renderdoc bridge: cannot listen on {}:{} ({})".format(HOST, port, exc))
        print("renderdoc bridge: a previous instance is probably still running.")
        print("renderdoc bridge: shut it down via /shutdown (see README) or restart RenderDoc, then Run again.")
        _server = None
        return None
    print("renderdoc bridge serving on http://{}:{}/status?token={}".format(HOST, port, TOKEN))
    print("renderdoc bridge reports: {}".format(", ".join(sorted(_REPORTS))))
    if ctx is None:
        print("renderdoc bridge: no capture context bound (plain python, status only)")
    if block:
        try:
            _server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop(quiet=True)
        return None
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()
    return _server


def stop(quiet=False):
    global _server, _server_thread
    if _server is not None:
        try:
            _server.shutdown()
            _server.server_close()
        except Exception as exc:
            if not quiet:
                print("renderdoc bridge stop error: {!r}".format(exc))
        _server = None
    if _server_thread is not None:
        _server_thread.join(timeout=5)
        _server_thread = None
    if not quiet:
        print("renderdoc bridge stopped")


def register(version, ctx):
    try:
        import qrenderdoc as qrd
        mgr = ctx.Extensions()
        mgr.RegisterWindowMenu(qrd.WindowMenu.Tools, ["Agent Bridge", "Start bridge"], _menu_start)
        mgr.RegisterWindowMenu(qrd.WindowMenu.Tools, ["Agent Bridge", "Stop bridge"], _menu_stop)
        mgr.RegisterWindowMenu(qrd.WindowMenu.Tools, ["Agent Bridge", "Show status"], _menu_status)
        print("renderdoc bridge: Tools > Agent Bridge menu installed")
    except Exception as exc:
        print("renderdoc bridge: menu registration failed: {!r}".format(exc))
    print("renderdoc bridge extension registered (RenderDoc {})".format(version))
    start(ctx)


def _menu_start(ctx, data):
    start(ctx)


def _menu_stop(ctx, data):
    stop()


def _menu_status(ctx, data):
    info = collect_status()
    print("renderdoc bridge: loaded={} event={} ({}) file={}".format(
        info.get("capture_loaded"), info.get("cur_event"),
        info.get("cur_event_name"), info.get("filename")))


def unregister():
    stop()


print("renderdoc bridge script loaded")

_script_ctx = globals().get("pyrenderdoc")
_script_name = globals().get("__name__", "__main__")

if _script_name == "__main__" and _script_ctx is None:
    start(None, block=True)
elif _script_ctx is not None:
    start(_script_ctx)
else:
    print("renderdoc bridge: no pyrenderdoc context found, server not started")
    print("renderdoc bridge: run this from RenderDoc with a capture open, or import it as an extension")
