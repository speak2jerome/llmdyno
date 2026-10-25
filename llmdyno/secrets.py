"""Local secret store for API keys and tokens.

Values live in data/secrets.json, encrypted with Windows DPAPI (bound to the current Windows user) or stored with
0600 permissions on Linux. They are never returned by the API, never written to logs, and never enter an agent
sandbox: only the proxy container receives the key it needs, through a temporary env file deleted after start."""
import base64
import ctypes
import json
import os
import threading

from .config import DATA

_lock = threading.Lock()
IS_WIN = os.name == "nt"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data, protect):
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    inp = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inp), None, None, None, None, 0x01, ctypes.byref(out)):   # CRYPTPROTECT_UI_FORBIDDEN
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _path():
    return DATA / "secrets.json"


def _load():
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(d):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    if not IS_WIN:
        os.chmod(tmp, 0o600)
    os.replace(tmp, _path())


def set(name, value):  # noqa: A001 - mirrors dict-like API
    value = (value or "").strip()
    with _lock:
        d = _load()
        if not value:
            d.pop(name, None)
        elif IS_WIN:
            d[name] = {"dpapi": base64.b64encode(_dpapi(value.encode(), True)).decode()}
        else:
            d[name] = {"plain": value}
        _save(d)


def get(name):
    with _lock:
        v = _load().get(name)
    if not v:
        return None
    if "dpapi" in v:
        try:
            return _dpapi(base64.b64decode(v["dpapi"]), False).decode()
        except OSError:
            return None
    return v.get("plain")


def has(name):
    with _lock:
        return name in _load()


def delete(name):
    set(name, "")


def masked(name):
    v = get(name)
    if not v:
        return None
    return f"{v[:3]}…{v[-4:]}" if len(v) > 10 else "•" * len(v)
