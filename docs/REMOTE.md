# Remote mode

Run LLMDyno on the machine with the GPU and Docker, and drive it from anywhere: from Python, from the command line,
from JavaScript or in a browser.

## On the server

```bash
llmdyno serve --host 0.0.0.0
```

The first time LLMDyno listens on anything other than 127.0.0.1 or localhost, it makes an access token and prints it.
It is shown once, so keep it somewhere safe; later starts only remind you that one exists. `llmdyno token --rotate`
makes a new one, and clients using the old one stop working at once. `llmdyno token` on its own makes a token if there
is none yet.

Requests from the server's own machine need nothing, as always, as long as they address it as `localhost`,
`127.0.0.1` or `[::1]`; opening `http://my-pc:8777` on the same machine counts as remote. Every other request to the
API must present the token:

- in an `Authorization: Bearer <token>` header;
- or as `?token=<token>` in the URL, which is how downloads and the WebSocket send it, since they can't set headers.

Without it the API answers 401. A browser request from a web page on another site is refused (403) even on the
server's own machine, so the sites you visit can't use LLMDyno through your browser. The dashboard's own files (HTML, scripts, images) are served to anyone, because they
hold no data. Changes made by remote clients (POST, PUT, PATCH and DELETE requests that were accepted) are logged to
`<data>/logs/remote-requests.jsonl`, with the time, client address, method, path and status.

### HTTPS and reverse proxies

LLMDyno speaks plain HTTP. Across a network you do not trust, reach it through an SSH tunnel, or put it behind a reverse
proxy that adds HTTPS:

```bash
ssh -L 8777:localhost:8777 gpu-box        # then use http://localhost:8777 on your laptop: no token needed
```

LLMDyno decides that a request is local when it comes from a loopback address, names a loopback host in its `Host`
header (`localhost`, `127.0.0.1`, `[::1]`), and carries none of the headers `X-Forwarded-For`, `Forwarded` or
`X-Real-IP`. A reverse proxy on the same machine connects from 127.0.0.1, so it
**must** add one of those headers, or every request it forwards looks local and needs no token. Caddy adds
`X-Forwarded-For` by default. nginx does not; add it yourself:

```nginx
location / {
    proxy_pass http://127.0.0.1:8777;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_http_version 1.1;                          # the WebSocket at /ws needs these three lines
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

Then check from another machine that `curl https://your-host/api/health` without a token answers 401.

## From Python

```python
import llmdyno

llmdyno.connect("http://gpu-box:8777", token="...")       # or llmdyno.connect() with LLMDYNO_URL and LLMDYNO_TOKEN set
qwen = llmdyno.profile("Qwen 27B 32k")
plan = llmdyno.bench(qwen, "suite_quick", wait=False)      # runs on the server
for ev in llmdyno.watch(plan, transcript=True):            # live events over the WebSocket
    print(ev.kind, ev.status)
results = plan.results()
results.open()                                             # opens the server's dashboard, already signed in
llmdyno.disconnect()                                       # back to this machine
```

`connect(url=None, token=None, *, timeout=120.0, verify=True, client=None)` checks the server's health and fails if
nothing answers, the token is refused, or the answer isn't from LLMDyno. It warns when the server's version differs
from the library's in the first two numbers. `verify=False` accepts a self-signed HTTPS certificate, and `client=`
takes your own `httpx.Client`. The environment variables are read by `connect()`; setting them alone does not connect
the library (the command line, below, does read them on every command). `llmdyno.connection()` says where calls go now.

Every call in the library works the same against a server; tests run each library area both ways to keep that true.
Live events come over the server's WebSocket; if a proxy blocks it, `watch()` falls back to polling for status changes.
A few calls behave differently:

- **`init()` and `serve()`** refuse while connected. `data_dir()` reports the server's folder.
- **Paths that the server uses** are paths on the server: `use_llama_cpp(path)`, `import_models(folder)`,
  `Settings.update(models_dir=...)`. `local_model(path=...)` needs the same path to exist on both machines, so register
  files from the server's own machine instead.
- **Files you send or receive** are on your machine: `import_profile()`, `add_harness()` with a manifest file,
  `import_benchmark()`, `python_harness()` and `node_harness()` read local files and send them; exports,
  `Run.download()` and `Plan.swebench_predictions()` write local files.
- **`Plan.open()` and `Results.open()`** open the server's dashboard with the token in the address, so you are signed in.

API keys you pass, such as `cloud_model(api_key=...)` or `set_hf_token()`, are sent to the server and saved there
(encrypted with DPAPI on a Windows server, in a file only its user can read on Linux and macOS). Note that
`cloud_model()` also sends a key it finds in your local environment (`OPENAI_API_KEY`, …) each time it is called. No
API call ever returns a key, and the access token is never returned either.

## From the command line

Every command that talks to LLMDyno takes `--url` and `--api-token`, or reads `LLMDYNO_URL` and `LLMDYNO_TOKEN`
(`serve` and `token` always act on this machine):

```bash
export LLMDYNO_URL=http://gpu-box:8777 LLMDYNO_TOKEN=...
llmdyno list-plans
llmdyno bench "Qwen 27B 32k" --benchmarks suite_quick
```

## From JavaScript

```ts
import { connect } from "llmdyno";
const dyno = await connect("http://gpu-box:8777", { token: process.env.LLMDYNO_TOKEN });
```

See [JavaScript and TypeScript](JAVASCRIPT.md).

## In a browser

Open `http://gpu-box:8777`. The dashboard asks for the access token the first time ("Connect to this LLMDyno") and keeps
it in that browser's local storage. A link with `#token=<token>` at the end signs in and removes the token from the
address bar; that is what `results.open()` uses.
