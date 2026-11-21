# Remote mode

Run LLMDyno on the machine with the GPU and Docker, and drive it from anywhere: from Python, from the command line,
or in a browser.

## On the server

```bash
llmdyno serve --host 0.0.0.0
```

The first time, this prints an access token. It is shown once, so keep it somewhere safe. `llmdyno token --rotate` makes
a new one, and clients using the old one stop working at once.

Requests from the server's own machine need nothing, as always. Every other request must present the token:
- in an `Authorization: Bearer <token>` header;
- or as `?token=` for downloads and the WebSocket, which cannot send headers.

A request that came through a reverse proxy counts as remote even if the proxy runs on the same machine. So putting
nginx or Caddy in front for HTTPS does not open a hole. Changes made by remote clients are logged to
`<data>/logs/remote-requests.jsonl`, with the time, client address, method, path and status.

LLMDyno speaks plain HTTP. Across a network you do not trust, put it behind HTTPS (a reverse proxy), or reach it
through an SSH tunnel:

```bash
ssh -L 8777:localhost:8777 gpu-box        # then use http://localhost:8777 on your laptop: no token needed
```

## From Python

```python
import llmdyno

llmdyno.connect("http://gpu-box:8777", token="...")       # or set LLMDYNO_URL and LLMDYNO_TOKEN
qwen = llmdyno.profile("Qwen 27B 32k")
plan = llmdyno.bench(qwen, "suite_quick", wait=False)      # runs on the server
for ev in llmdyno.watch(plan, transcript=True):            # live events over the WebSocket
    print(ev.kind, ev.status)
results = plan.results()
results.open()                                             # opens the server's dashboard, already signed in
llmdyno.disconnect()                                       # back to this machine
```

Every call in the library works the same against a server. Tests run each library area both ways to keep that true.
Calls that only make sense on one machine say so: `init()` and `serve()` refuse while connected, and `data_dir()`
reports the server's folder.

API keys you pass, such as `cloud_model(api_key=...)` or `set_hf_token()`, are sent to the server once and stored
there encrypted. No API call ever returns a key, and the access token is never returned either.

## From the command line

Every command takes `--url` and `--api-token`, or reads `LLMDYNO_URL` and `LLMDYNO_TOKEN`:

```bash
export LLMDYNO_URL=http://gpu-box:8777 LLMDYNO_TOKEN=...
llmdyno list-plans
llmdyno bench "Qwen 27B 32k" --benchmarks suite_quick
```

## In a browser

Open `http://gpu-box:8777`. The dashboard asks for the access token once and keeps it in that browser.
