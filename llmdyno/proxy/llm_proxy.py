"""Logging proxy between an agent sandbox and its model upstream (stdlib only; runs inside a container).

* Streams every response through unchanged.
* Injects the upstream API key (agents only hold a dummy key) and enforces hard spend caps from ledger files.
  Every writer (each proxy, the host) owns one shard file per ledger and readers sum the shards, so parallel runs
  never overwrite each other's spend.
* Writes one metrics line per model request to $PROXY_LOG: tokens, cache reuse, TTFT, speed, tool calls, cost.
* Writes a harness-neutral transcript to $TRANSCRIPT: new conversation messages per request plus streamed deltas,
  so the UI can show thinking, text, tool calls and tool results for any harness.

Understands OpenAI Chat Completions, the OpenAI Responses API and the Anthropic Messages API.
"""
import glob
import hashlib
import http.client
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

UPSTREAM = urlsplit(os.environ.get("UPSTREAM", "http://host.docker.internal:18180"))
API_STYLE = os.environ.get("API_STYLE", "openai-chat")
LOG_PATH = os.environ.get("PROXY_LOG", "/logs/proxy.jsonl")
TRANSCRIPT = os.environ.get("TRANSCRIPT", "/logs/transcript.jsonl")
API_KEY = os.environ.get("UPSTREAM_API_KEY", "")
LEDGERS = json.loads(os.environ.get("LEDGERS", "[]") or "[]")       # [{"name": "provider_x", "budget": usd}]
LEDGER_DIR = os.environ.get("LEDGER_DIR", "/budget")
LEDGER_WRITER = os.environ.get("LEDGER_WRITER", "proxy")
IDLE_TIMEOUT = float(os.environ.get("PROXY_IDLE_TIMEOUT", "900"))    # seconds without a byte from upstream
PRICE = {k: float(os.environ.get(f"PRICE_{k.upper()}", "0") or 0) for k in ("input", "cached", "output", "cache_write")}
INJECT_USAGE = os.environ.get("INJECT_STREAM_USAGE", "1") == "1"
EXTRA_HEADERS = json.loads(os.environ.get("EXTRA_HEADERS", "{}") or "{}")
COMPAT_LOCAL = os.environ.get("COMPAT_LOCAL", "0") == "1"
HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization",
       "proxy-authenticate", "content-length", "host", "accept-encoding"}
MODEL_PATHS = ("/chat/completions", "/responses", "/messages")
_lock = threading.Lock()
_seq = 0
_convs = {}          # conversation key -> list of message fingerprints already written to the transcript


def _append(path, rec):
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def log(rec):
    _append(LOG_PATH, rec)


def tlog(rec):
    _append(TRANSCRIPT, rec)


# ------------------------------------------------------------------ budget ledgers
_last = {}           # path -> last value read; a shard that is briefly locked never counts as $0


def _read(path):
    for attempt in range(20):
        try:
            with open(path) as f:
                v = float(json.load(f).get("spent_usd", 0))
            _last[path] = v
            return v
        except FileNotFoundError:
            return _last.get(path, 0.0)
        except (OSError, ValueError):        # Windows: the writer is mid-rename; JSON never half-written (atomic replace)
            time.sleep(0.01 * (attempt + 1))
    return _last.get(path, 0.0)


def _replace(tmp, dst):
    """os.replace, retried: on Windows it fails while another process has the target open for reading."""
    for attempt in range(50):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            time.sleep(0.01 * (attempt + 1))
    os.replace(tmp, dst)


def ledger_total(name):
    """Spend across all writers: <name>.json (older single-file ledgers) plus every <name>__<writer>.json shard."""
    paths = [os.path.join(LEDGER_DIR, name + ".json")] + glob.glob(os.path.join(LEDGER_DIR, glob.escape(name) + "__*.json"))
    return sum(_read(p) for p in paths)


def over_budget():
    for lg in LEDGERS:
        if lg.get("budget") and ledger_total(lg["name"]) >= float(lg["budget"]):
            return lg
    return None


def ledger_add(cost):
    """Add to this proxy's own shard of every ledger; returns the new total of the first ledger."""
    with _lock:
        out = None
        for lg in LEDGERS:
            shard = os.path.join(LEDGER_DIR, f"{lg['name']}__{LEDGER_WRITER}.json")
            mine = _read(shard) + cost
            tmp = shard + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"spent_usd": round(mine, 6), "budget_usd": lg.get("budget"), "updated": time.time()}, f)
            _replace(tmp, shard)
            out = ledger_total(lg["name"]) if out is None else out
        return out


# ------------------------------------------------------------------ request normalisation
def _text_of(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, dict):
                v = c.get("text")
                if isinstance(v, str):
                    parts.append(v)
                elif c.get("content") is not None:
                    parts.append(_text_of(c.get("content")))
                elif c.get("type") in ("image", "image_url", "input_image"):
                    parts.append("[image]")
        return "\n".join(p for p in parts if p)
    return json.dumps(content)[:20000]


def norm_messages(style, req):
    """Return (system_text, [ {role, blocks:[...]} ]) for any of the three APIs."""
    system, out = "", []
    if style == "anthropic":
        system = _text_of(req.get("system"))
        for m in req.get("messages") or []:
            blocks = []
            content = m.get("content")
            if isinstance(content, str):
                blocks.append({"type": "text", "text": content})
            for c in content if isinstance(content, list) else []:
                t = c.get("type")
                if t == "text":
                    blocks.append({"type": "text", "text": c.get("text", "")})
                elif t == "thinking":
                    blocks.append({"type": "thinking", "text": c.get("thinking", "")})
                elif t == "tool_use":
                    blocks.append({"type": "tool_call", "id": c.get("id"), "name": c.get("name"),
                                   "args": json.dumps(c.get("input"), ensure_ascii=False)})
                elif t == "tool_result":
                    blocks.append({"type": "tool_result", "id": c.get("tool_use_id"), "text": _text_of(c.get("content")),
                                   "is_error": bool(c.get("is_error"))})
            out.append({"role": m.get("role"), "blocks": blocks})
    elif "input" in req and "messages" not in req:           # Responses API
        system = req.get("instructions") or ""
        items = req["input"] if isinstance(req["input"], list) else [{"role": "user", "content": req["input"]}]
        for it in items:
            t = it.get("type")
            if t == "function_call":
                out.append({"role": "assistant", "blocks": [{"type": "tool_call", "id": it.get("call_id"),
                                                              "name": it.get("name"), "args": it.get("arguments", "")}]})
            elif t in ("function_call_output", "custom_tool_call_output"):
                out.append({"role": "tool", "blocks": [{"type": "tool_result", "id": it.get("call_id"),
                                                         "text": _text_of(it.get("output"))}]})
            elif t == "custom_tool_call":
                out.append({"role": "assistant", "blocks": [{"type": "tool_call", "id": it.get("call_id"),
                                                              "name": it.get("name"), "args": it.get("input", "")}]})
            elif t == "reasoning":
                txt = "\n".join(s.get("text", "") for s in it.get("summary") or [] if isinstance(s, dict))
                if txt:
                    out.append({"role": "assistant", "blocks": [{"type": "thinking", "text": txt}]})
            elif it.get("role") in ("system", "developer"):
                system = (system + "\n\n" + _text_of(it.get("content"))).strip()
            elif it.get("role"):
                out.append({"role": it["role"], "blocks": [{"type": "text", "text": _text_of(it.get("content"))}]})
    else:                                                     # Chat Completions
        for m in req.get("messages") or []:
            role = m.get("role")
            if role in ("system", "developer"):
                system = (system + "\n\n" + _text_of(m.get("content"))).strip()
                continue
            blocks = []
            rc = m.get("reasoning_content") or m.get("reasoning")
            if isinstance(rc, str) and rc:
                blocks.append({"type": "thinking", "text": rc})
            if role == "tool":
                blocks.append({"type": "tool_result", "id": m.get("tool_call_id"), "name": m.get("name"),
                               "text": _text_of(m.get("content"))})
            else:
                txt = _text_of(m.get("content"))
                if txt:
                    blocks.append({"type": "text", "text": txt})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                blocks.append({"type": "tool_call", "id": tc.get("id"), "name": fn.get("name"), "args": fn.get("arguments", "")})
            out.append({"role": role, "blocks": blocks})
    return system, out


def _fp(msg):
    return hashlib.sha1(json.dumps(msg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def tools_of(req):
    names = []
    for t in req.get("tools") or []:
        names.append(t.get("name") or (t.get("function") or {}).get("name") or t.get("type"))
    return [n for n in names if n]


def transcript_request(seq, style, req):
    system, msgs = norm_messages(style, req)
    first_user = next((json.dumps(m, sort_keys=True)[:4000] for m in msgs if m["role"] == "user"), "")
    key = hashlib.sha1((system[:4000] + first_user).encode()).hexdigest()[:12]
    fps = [_fp(m) for m in msgs]
    with _lock:
        prev = _convs.get(key)
        _convs[key] = fps
    rec = {"t": time.time(), "seq": seq, "ev": "request", "conv": key, "model": req.get("model"),
           "n_messages": len(msgs)}
    if prev is None:
        rec.update({"new_conv": True, "system": system[:60000], "tools": tools_of(req), "new": msgs})
    elif fps[:len(prev)] == prev:
        rec["new"] = msgs[len(prev):]
    else:
        common = 0
        while common < min(len(prev), len(fps)) and prev[common] == fps[common]:
            common += 1
        rec.update({"reset": True, "kept": common, "new": msgs[common:]})
    for m in rec["new"]:
        for b in m["blocks"]:
            if b.get("type") == "tool_result" and len(b.get("text", "")) > 60000:
                b["text"] = b["text"][:60000] + f"\n… [{len(b['text']) - 60000} more characters]"
    tlog(rec)


def compat_local(style, req):
    """llama-server renders requests through the model's chat template, and many templates (Qwen, Gemma) raise if a
    system message is not first. Harnesses such as Codex interleave developer messages, so merge them up front."""
    if style == "openai-responses" and isinstance(req.get("input"), list):
        sys_parts = [req.get("instructions") or ""]
        keep = []
        for it in req["input"]:
            if isinstance(it, dict) and it.get("role") in ("system", "developer") and it.get("type", "message") == "message":
                sys_parts.append(_text_of(it.get("content")))
            else:
                keep.append(it)
        if len(keep) != len(req["input"]):
            req["input"] = keep
            req["instructions"] = "\n\n".join(p for p in sys_parts if p)
            return True
    elif style == "openai-chat" and isinstance(req.get("messages"), list):
        msgs = req["messages"]
        sys_msgs = [m for m in msgs if m.get("role") in ("system", "developer")]
        if len(sys_msgs) > 1 or (sys_msgs and msgs[0] is not sys_msgs[0]):
            merged = {"role": "system", "content": "\n\n".join(_text_of(m.get("content")) for m in sys_msgs)}
            req["messages"] = [merged] + [m for m in msgs if m.get("role") not in ("system", "developer")]
            return True
    return False


def summarize_request(body):
    try:
        req = json.loads(body)
    except ValueError:
        return {}, None
    msgs = req.get("messages") or req.get("input") or []
    return {"model": req.get("model"), "n_messages": len(msgs) if isinstance(msgs, list) else 1,
            "n_tools": len(req.get("tools") or []),
            "max_tokens": req.get("max_tokens") or req.get("max_completion_tokens") or req.get("max_output_tokens"),
            "reasoning_param": req.get("reasoning_effort") or (req.get("reasoning") or {}).get("effort")
            or ((req.get("thinking") or {}).get("budget_tokens") if isinstance(req.get("thinking"), dict) else None),
            "stream": bool(req.get("stream")), "request_bytes": len(body)}, req


def normalize_usage(u, style):
    """-> {input (total prompt incl. cached), cached, cache_write, output, reasoning}"""
    if not u:
        return None
    if style == "anthropic" or "cache_read_input_tokens" in u or "cache_creation_input_tokens" in u:
        cr, cw = u.get("cache_read_input_tokens") or 0, u.get("cache_creation_input_tokens") or 0
        return {"input": (u.get("input_tokens") or 0) + cr + cw, "cached": cr, "cache_write": cw,
                "output": u.get("output_tokens") or 0, "reasoning": 0}
    inp = u.get("prompt_tokens", u.get("input_tokens"))
    out = u.get("completion_tokens", u.get("output_tokens"))
    di = u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}
    do = u.get("completion_tokens_details") or u.get("output_tokens_details") or {}
    cached = di.get("cached_tokens") or u.get("prompt_cache_hit_tokens") or 0
    return {"input": inp or 0, "cached": cached, "cache_write": 0, "output": out or 0,
            "reasoning": do.get("reasoning_tokens") or 0}


# ------------------------------------------------------------------ streamed response parsing
class StreamState:
    """Accumulates one response's blocks and flushes coalesced deltas to the transcript."""

    def __init__(self, seq):
        self.seq = seq
        self.blocks = {}          # index -> {"type", "text" / "args", "name", "id"}
        self.pending = {}         # index -> text not yet flushed
        self.last_flush = time.time()
        self.first_token = None
        self.usage = None
        self.timings = None
        self.finish = None
        self.tool_names = []
        self.content_chars = 0
        self.reasoning_chars = 0

    def _block(self, idx, btype, **kw):
        b = self.blocks.get(idx)
        if b is None:
            b = self.blocks[idx] = {"type": btype, "text": "", **kw}
            tlog({"t": time.time(), "seq": self.seq, "ev": "block_start", "index": idx, "type": btype,
                  **{k: v for k, v in kw.items() if v is not None}})
            if btype == "tool_call" and kw.get("name"):
                self.tool_names.append(kw["name"])
        else:
            for k, v in kw.items():
                if v and not b.get(k):
                    b[k] = v
                    if k == "name":
                        self.tool_names.append(v)
                        tlog({"t": time.time(), "seq": self.seq, "ev": "block_meta", "index": idx, "name": v})
        return b

    def delta(self, idx, btype, text, **kw):
        if not text and not kw:
            return
        if self.first_token is None:
            self.first_token = time.time()
        b = self._block(idx, btype, **kw)
        if text:
            b["text"] += text
            self.pending[idx] = self.pending.get(idx, "") + text
            if btype == "text":
                self.content_chars += len(text)
            elif btype == "thinking":
                self.reasoning_chars += len(text)
        if time.time() - self.last_flush > 0.08:
            self.flush()

    def flush(self):
        for idx, txt in self.pending.items():
            if txt:
                tlog({"t": time.time(), "seq": self.seq, "ev": "delta", "index": idx, "text": txt})
        self.pending = {}
        self.last_flush = time.time()

    def finish_blocks(self):
        self.flush()
        out = []
        for idx in sorted(self.blocks, key=lambda i: (str(type(i)), i)):
            b = self.blocks[idx]
            if b["type"] == "tool_call":
                out.append({"type": "tool_call", "id": b.get("id"), "name": b.get("name"), "args": b["text"]})
            else:
                out.append({"type": b["type"], "text": b["text"]})
        return out

    # --- per-API event handlers
    def chat(self, ev):
        self.timings = ev.get("timings") or self.timings
        self.usage = ev.get("usage") or self.usage
        for ch in ev.get("choices") or []:
            d = ch.get("delta") or ch.get("message") or {}
            r = d.get("reasoning_content") or d.get("reasoning")
            if isinstance(r, str) and r:
                self.delta("think", "thinking", r)
            if d.get("content"):
                self.delta("text", "text", d["content"] if isinstance(d["content"], str) else _text_of(d["content"]))
            for tc in d.get("tool_calls") or []:
                fn = tc.get("function") or {}
                self.delta(f"tool{tc.get('index', 0)}", "tool_call", fn.get("arguments") or "",
                           name=fn.get("name"), id=tc.get("id"))
            if ch.get("finish_reason"):
                self.finish = ch["finish_reason"]

    def responses(self, ev):
        t = ev.get("type", "")
        if t == "response.output_item.added":
            it = ev.get("item") or {}
            if it.get("type") in ("function_call", "custom_tool_call"):
                self.delta(f"item{ev.get('output_index')}", "tool_call", "", name=it.get("name"), id=it.get("call_id"))
        elif t == "response.output_text.delta":
            self.delta(f"item{ev.get('output_index')}", "text", ev.get("delta") or "")
        elif t.startswith("response.reasoning") and t.endswith(".delta"):
            self.delta(f"item{ev.get('output_index')}", "thinking", ev.get("delta") or "")
        elif t in ("response.function_call_arguments.delta", "response.custom_tool_call_input.delta"):
            self.delta(f"item{ev.get('output_index')}", "tool_call", ev.get("delta") or "")
        elif t in ("response.completed", "response.incomplete", "response.failed"):
            resp = ev.get("response") or {}
            self.usage = resp.get("usage") or self.usage
            self.finish = resp.get("status")

    def anthropic(self, ev):
        t = ev.get("type")
        if t == "message_start":
            self.usage = dict((ev.get("message") or {}).get("usage") or {})
        elif t == "content_block_start":
            cb = ev.get("content_block") or {}
            kind = {"thinking": "thinking", "redacted_thinking": "thinking", "tool_use": "tool_call"}.get(cb.get("type"), "text")
            self.delta(ev.get("index"), kind, cb.get("text") or "", **({"name": cb.get("name"), "id": cb.get("id")}
                                                                        if kind == "tool_call" else {}))
        elif t == "content_block_delta":
            d = ev.get("delta") or {}
            if d.get("type") == "text_delta":
                self.delta(ev.get("index"), "text", d.get("text", ""))
            elif d.get("type") == "thinking_delta":
                self.delta(ev.get("index"), "thinking", d.get("thinking", ""))
            elif d.get("type") == "input_json_delta":
                self.delta(ev.get("index"), "tool_call", d.get("partial_json", ""))
        elif t == "message_delta":
            u = ev.get("usage") or {}
            self.usage = {**(self.usage or {}), **{k: v for k, v in u.items() if v is not None}}
            self.finish = (ev.get("delta") or {}).get("stop_reason") or self.finish

    def whole(self, style, body):
        """Non-streaming response body."""
        try:
            d = json.loads(body)
        except ValueError:
            return
        if style == "anthropic" or d.get("type") == "message":
            for i, c in enumerate(d.get("content") or []):
                if c.get("type") == "text":
                    self.delta(i, "text", c.get("text", ""))
                elif c.get("type") == "thinking":
                    self.delta(i, "thinking", c.get("thinking", ""))
                elif c.get("type") == "tool_use":
                    self.delta(i, "tool_call", json.dumps(c.get("input")), name=c.get("name"), id=c.get("id"))
            self.usage, self.finish = d.get("usage"), d.get("stop_reason")
        elif "output" in d and isinstance(d["output"], list):
            for i, it in enumerate(d["output"]):
                if it.get("type") == "message":
                    self.delta(i, "text", _text_of(it.get("content")))
                elif it.get("type") == "function_call":
                    self.delta(i, "tool_call", it.get("arguments", ""), name=it.get("name"), id=it.get("call_id"))
                elif it.get("type") == "reasoning":
                    self.delta(i, "thinking", "\n".join(s.get("text", "") for s in it.get("summary") or []))
            self.usage, self.finish = d.get("usage"), d.get("status")
        else:
            self.chat(d)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 1800          # an agent connection that sends nothing for 30 min is dropped instead of pinning a thread

    def log_message(self, *args):
        pass

    def _reply_json(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _forward(self):
        global _seq
        with _lock:
            _seq += 1
            seq = _seq
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        is_model = self.command == "POST" and self.path.split("?")[0].rstrip("/").endswith(MODEL_PATHS)
        style = "anthropic" if self.path.split("?")[0].rstrip("/").endswith("/messages") else (
            "openai-responses" if self.path.split("?")[0].rstrip("/").endswith("/responses") else "openai-chat")
        t0 = time.time()
        rec = {"seq": seq, "ts": t0, "path": self.path, "api": style}
        req = None
        if is_model:
            blocked = over_budget()
            if blocked:
                log({**rec, "budget_blocked": True, "ledger": blocked["name"]})
                tlog({"t": t0, "seq": seq, "ev": "error", "text": f"budget of ${blocked['budget']} exhausted"})
                self._reply_json(429, {"error": {"message": f"benchmark budget of ${blocked['budget']} exhausted",
                                                 "type": "budget_exhausted"}})
                return
            info, req = summarize_request(body)
            rec.update(info)
            if req is not None:
                changed = COMPAT_LOCAL and compat_local(style, req)
                if INJECT_USAGE and style == "openai-chat" and req.get("stream") and "stream_options" not in req:
                    req["stream_options"] = {"include_usage": True}
                    changed = True
                if changed:
                    body = json.dumps(req).encode()
                try:
                    transcript_request(seq, style, req)
                except Exception as e:  # noqa: BLE001 - transcript capture must never break the agent
                    tlog({"t": t0, "seq": seq, "ev": "error", "text": f"transcript capture failed: {e}"})
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        if API_KEY:
            headers = {k: v for k, v in headers.items() if k.lower() not in ("authorization", "x-api-key")}
            if style == "anthropic" or API_STYLE == "anthropic":
                headers["x-api-key"] = API_KEY
                headers.setdefault("anthropic-version", "2023-06-01")
            else:
                headers["Authorization"] = f"Bearer {API_KEY}"
        headers.update(EXTRA_HEADERS)
        # OpenAI-style harnesses call <proxy>/v1/...; the upstream base URL replaces that /v1 (it may be /v1,
        # /v1beta/openai, /api/paas/v4 or empty for llama-server). Anthropic SDKs append /v1/messages to the base.
        base = UPSTREAM.path.rstrip("/")
        path = self.path
        if API_STYLE != "anthropic" and path.startswith("/v1/") and base:
            path = path[3:]
        path = base + path
        Conn = http.client.HTTPSConnection if UPSTREAM.scheme == "https" else http.client.HTTPConnection
        conn = Conn(UPSTREAM.hostname, UPSTREAM.port, timeout=IDLE_TIMEOUT)
        try:
            headers["Content-Length"] = str(len(body))
            conn.request(self.command, path, body=body or None, headers=headers)
            resp = conn.getresponse()
        except Exception as e:  # noqa: BLE001
            log({**rec, "error": str(e)})
            self._reply_json(502, {"error": {"message": f"upstream error: {e}"}})
            return
        self.send_response(resp.status)
        ctype = resp.getheader("Content-Type", "")
        for k, v in resp.getheaders():
            if k.lower() not in HOP:
                self.send_header(k, v)
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()
        rec["status"] = resp.status
        st = StreamState(seq)
        buf, raw = b"", b""
        sse = "event-stream" in ctype
        try:
            while True:
                chunk = resp.read1(65536)
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
                if not is_model:
                    continue
                if resp.status >= 400 or not sse:
                    raw = (raw + chunk)[-4_000_000:]
                    if resp.status >= 400:
                        continue
                if not sse:
                    continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        continue
                    try:
                        ev = json.loads(data)
                    except ValueError:
                        continue
                    try:
                        if style == "anthropic":
                            st.anthropic(ev)
                        elif style == "openai-responses":
                            st.responses(ev)
                        else:
                            st.chat(ev)
                    except Exception:  # noqa: BLE001
                        pass
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError) as e:
            rec["client_disconnected"] = str(e)
        except (OSError, http.client.HTTPException) as e:   # upstream stalled (idle timeout) or dropped mid-stream
            rec["upstream_error"] = f"{type(e).__name__}: {e}"[:300]
            tlog({"t": time.time(), "seq": seq, "ev": "error", "text": f"upstream stream broke: {rec['upstream_error']}"})
        finally:
            conn.close()
        if not is_model:
            return
        if resp.status < 400 and not sse:
            st.whole(style, raw)
        t1 = time.time()
        blocks = st.finish_blocks()
        nu = normalize_usage(st.usage, style)
        rec.update({"t_end": t1, "wall_s": round(t1 - t0, 3),
                    "ttft_s": round(st.first_token - t0, 3) if st.first_token else None, "finish_reason": st.finish,
                    "timings": st.timings, "usage_norm": nu, "n_tool_calls": len(st.tool_names),
                    "tool_names": st.tool_names, "content_chars": st.content_chars, "reasoning_chars": st.reasoning_chars})
        if resp.status >= 400:
            rec["error_body"] = raw.decode("utf-8", "replace")[-1500:]
        if not nu and any(PRICE.values()) and resp.status < 400:
            # the stream was cut before the usage event: the provider still bills it, so book a rough estimate
            # (4 characters per token) rather than nothing, which keeps budget caps conservative
            nu = {"input": len(body) // 4, "cached": 0, "cache_write": 0,
                  "output": (st.content_chars + st.reasoning_chars) // 4 + 16, "reasoning": 0, "estimated": True}
            rec["usage_estimated"] = True
        if nu and any(PRICE.values()):
            uncached = max(nu["input"] - nu["cached"] - nu["cache_write"], 0)
            cost = (uncached * PRICE["input"] + nu["cached"] * PRICE["cached"] + nu["output"] * PRICE["output"]
                    + nu["cache_write"] * (PRICE["cache_write"] or PRICE["input"] * 1.25)) / 1e6
            rec["cost_usd"] = round(cost, 6)
            if LEDGERS:
                rec["ledger_spent_usd"] = round(ledger_add(cost) or 0, 6)
        log(rec)
        out = {"t": t1, "seq": seq, "ev": "response", "status": resp.status, "finish": st.finish, "blocks": blocks,
               "usage": nu, "timings": st.timings, "ttft_s": rec["ttft_s"], "wall_s": rec["wall_s"],
               "cost_usd": rec.get("cost_usd")}
        if resp.status >= 400:
            out["error"] = rec["error_body"][-800:]
        tlog(out)

    do_GET = do_POST = do_DELETE = do_PUT = _forward


if __name__ == "__main__":
    for p in (LOG_PATH, TRANSCRIPT):
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    port = int(os.environ.get("PORT", "8081"))
    print(f"proxy :{port} -> {UPSTREAM.geturl()} ({API_STYLE}) key={'yes' if API_KEY else 'no'} "
          f"ledgers={len(LEDGERS)}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
