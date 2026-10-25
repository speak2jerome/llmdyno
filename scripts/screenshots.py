"""Capture the README screenshots from a running LLMDyno (default http://127.0.0.1:8777) with headless Chrome.

    python scripts/screenshots.py [--base URL] [--chrome PATH] [--only results,overview]

Drives Chrome over the DevTools protocol so each page can finish loading live data and charts before the capture.
Writes PNGs to docs/images/. Uses a throwaway Chrome profile; your own browser profile is never touched.
"""
import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
CHROME_PATHS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]

# name, path, viewport height, seconds to wait, optional JavaScript to run before the capture
SHOTS = [
    ("overview", "/", 900, 4, None),
    ("results", "/results?plans=plan_sample_round1", 1900, 6, None),
    ("profile-editor", "/profiles/{local_profile}", 1000, 6, None),
    ("run-transcript", "/runs/{run}", 1000, 5, None),
    ("plan-wizard", "/plans/new", 900, 4, None),
    ("judging", "/judging", 1000, 5, None),
    ("setup", "/setup", 1000, 5, None),
    ("panic-stop", "/", 900, 3, "document.querySelector('[aria-label^=\"Panic stop\"]').click()"),
    ("mascot", "/settings#about", 900, 4, "document.getElementById('about').scrollIntoView()"),
]


class Tab:
    def __init__(self, ws_url):
        self.ws = connect(ws_url, max_size=64 * 2**20)
        self.n = 0

    def call(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})


def fill(path, base):
    """Resolve {local_profile} and {run} placeholders from the running instance."""
    if "{local_profile}" in path:
        profs = [p for p in httpx.get(f"{base}/api/profiles").json() if p["kind"] == "local" and "sample" not in (p.get("tags") or [])]
        path = path.replace("{local_profile}", profs[0]["id"]) if profs else "/profiles"
    if "{run}" in path:
        plans = [p for p in httpx.get(f"{base}/api/plans").json() if not p.get("sample") and (p.get("counts") or {}).get("done")]
        runs = httpx.get(f"{base}/api/plans/{plans[0]['id']}").json()["runs"] if plans else []
        done = [r for r in runs if r["status"] == "done"]
        path = path.replace("{run}", done[0]["id"]) if done else "/plans"
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8777")
    ap.add_argument("--chrome", default=next((p for p in CHROME_PATHS if Path(p).exists()), None))
    ap.add_argument("--only", default="")
    ap.add_argument("--theme", default="dark")
    a = ap.parse_args()
    if not a.chrome:
        sys.exit("Chrome or Edge not found; pass --chrome")
    OUT.mkdir(parents=True, exist_ok=True)
    prof = tempfile.mkdtemp(prefix="llmdyno-shots-")
    port = 9333
    proc = subprocess.Popen([a.chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                             f"--user-data-dir={prof}", f"--remote-debugging-port={port}", "--hide-scrollbars",
                             "--window-size=1440,900", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                pages = [t for t in httpx.get(f"http://127.0.0.1:{port}/json/list").json() if t["type"] == "page"]
                if pages:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        tab = Tab(pages[0]["webSocketDebuggerUrl"])
        tab.call("Page.enable")
        only = set(filter(None, a.only.split(",")))
        for name, path, height, wait, js in SHOTS:
            if only and name not in only:
                continue
            tab.call("Emulation.setDeviceMetricsOverride", width=1440, height=height, deviceScaleFactor=1, mobile=False)
            url = a.base + fill(path, a.base)
            url += ("&" if "?" in url.split("#")[0] else "?") + f"theme={a.theme}" if "#" not in url else ""
            if "#" in path:
                p, h = (a.base + path).split("#")
                url = f"{p}?theme={a.theme}#{h}"
            tab.call("Page.navigate", url=url)
            time.sleep(wait)
            if js:
                tab.call("Runtime.evaluate", expression=js)
                time.sleep(1.2)
            png = base64.b64decode(tab.call("Page.captureScreenshot", format="png")["data"])
            (OUT / f"{name}.png").write_bytes(png)
            print(f"{name}.png  {len(png) // 1024} KB  {url}")
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(prof, ignore_errors=True)


if __name__ == "__main__":
    main()
