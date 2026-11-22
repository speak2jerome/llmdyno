# Troubleshooting

Most problems show up in one of four places: the **Setup** page (or `llmdyno doctor`), the plan's preflight, the
**Activity** page (every background job keeps its log), and a run's **Logs** tab. Start there; the sections below
cover what they most often say.

## Docker

**"Docker is not running: start Docker Desktop (or the docker service) and try again."**
On Windows and macOS, "Start Docker Desktop" on the Setup page (or `llmdyno start-docker`) starts it; it takes about a
minute. On Linux, start the service (`sudo systemctl start docker`).

**Docker Desktop doesn't start on Windows.** A crashed Docker Desktop can leave stale socket folders behind that stop
the next start. When LLMDyno finds them, the Setup page offers "Fix Docker Desktop start-up" (`llmdyno repair-docker`),
which moves those folders aside; images, containers and settings are untouched. Avoid Docker Desktop's "Reset to
factory defaults", which deletes every image.

**"permission denied" talking to Docker on Linux.** Add your user to the `docker` group (`sudo usermod -aG docker
$USER`), then log out and in again.

**Runs fail with out-of-memory errors inside the sandbox.** Give Docker Desktop more memory (at least 8 GB; on Windows
it is the WSL 2 limit). The Setup page shows the current limit and how to raise it.

**SWE-bench is very slow on an ARM machine.** Its task images are x86-64 only and run under emulation (Rosetta in
Docker Desktop on Apple Silicon, QEMU on Linux), two to five times slower. That is expected; the preflight warns about
it.

## Local models and llama.cpp

**"llama.cpp is not installed; install it on the Setup page."** Download and install it there, or point LLMDyno at
your own build with "Use an existing folder" (`llmdyno use-llama-cpp PATH`). `llmdyno setup --llama-cpp cuda-13` (or
`cuda-12`, `vulkan`, `metal`, `cpu`, …) picks a build.

**The CUDA 13 build is marked as not usable.** It needs NVIDIA driver 580 or newer. Update the driver, or use the
CUDA 12 build.

**"llama-server exited during load" or "did not become ready".** Open the run's **Logs** tab (or `Run.server_log()`):
the llama-server log says why. The usual causes are not enough memory (see below), a context size the model doesn't
support, or a GGUF file this llama.cpp build is too old for (reinstall llama.cpp from the Setup page).

**"port 18180 is used by …".** Another program holds llama-server's port. Change the llama-server port in Settings.

**The profile is projected to spill or run out of memory.** In the profile editor, the Memory fit panel offers fixes:
a q8_0 KV cache, a shorter context, or moving MoE experts or layers to the CPU. Close programs that hold VRAM
(browsers and games use a lot); LLMDyno re-measures free VRAM right before every model load, so a run can fail even
though the profile fitted when you made it.

**Benchmarks are much slower than expected on Windows.** Check for a "spilled to RAM" badge on the run or profile.
When VRAM runs out, the NVIDIA driver moves memory into system RAM instead of failing, and the model runs five to
twenty times slower. LLMDyno refuses to load a profile that would spill unless the plan allows it, and flags runs
where spill happened anyway. In the NVIDIA Control Panel, setting "CUDA - Sysmem Fallback Policy" to "Prefer No
Sysmem Fallback" makes the driver fail instead.

**Sandboxes can't reach llama-server (Linux with Colima or another Docker VM).** llama-server listens on Docker's
bridge gateway on Linux, which a Docker running in a VM may not reach. Set `llama_bind_host` in `settings.json` (see
[Configuration](CONFIGURATION.md)) to an address the VM can reach.

## Downloads

**"this repository is gated or private".** Add a Hugging Face token (Settings, or `llmdyno set-hf-token`) and accept
the model's terms on huggingface.co with the same account.

**"checksum mismatch … the partial file was removed, retry the download".** The file arrived damaged. Download it
again; it starts from scratch.

**"not enough disk space".** The message says how much is needed and free. Free space, or move the models folder to
another disk in Settings (files already downloaded are not moved).

**A download stopped.** Downloads resume where they stopped: **Resume** on the Models page (Downloads tab), or
`model.resume()`.

## Cloud providers

**"no API key for …".** Add a key on the Cloud providers page, pass `api_key=`, or set the provider's environment
variable (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …; the full list is in [Configuration](CONFIGURATION.md)).

**Runs stop with a budget error.** The proxy refuses requests once a provider's budget (or the plan's) is used up.
Raise the budget on the provider card, or **Reset spend counter** if the spend was from earlier work; the provider
still bills what was used. Judging and quick tests count toward the provider's spend too.

**Rate limits (429) or upstream errors (502).** The provider refused or failed the request. Lower the plan's "Cloud runs
in parallel", wait, or check the provider's status page. **Test** on the provider card checks the key and the endpoint.

**"… speaks openai-responses; … offers …".** The harness and the provider share no API. The plan builder's
compatibility grid shows which pairs work; pick another harness (Pi and OpenCode speak all three APIs).

## Plans and runs

**The plan won't start.** The preflight lists what blocks it, most with a button to fix it: an image not built,
Docker not running, a model not downloaded, a missing key. From Python, `PreflightError.problems` has the same list.

**"Some profiles carry serious risks".** A profile is projected to spill or run out of memory. Fix the profile, or
tick "I understand" (`acknowledge_risks=True`) to run anyway with the results flagged.

**Runs failed.** Open a failed run: the **Logs** tab has the harness's output per stage, the **Transcript** shows what
the model did, and the error is at the top. Common causes are a timeout (raise the plan's timeout multiplier for slow
models), a model that doesn't call tools, and the memory problems above. **Retry failed** on the plan runs them again.

**"interrupted by a server restart".** LLMDyno was stopped while the plan ran. Its finished runs are kept and the plan
is paused: **Resume** continues it.

**"The untouched workspace already passes …" when validating a benchmark.** The hidden tests don't measure the agent's
work: the starter code already passes them. See [Writing a benchmark](BENCHMARKS.md#validation).

## Results

**The Results page is empty.** It shows finished runs only. The bundled sample is left out once you have plans of your
own; pick it in the Plans filter, or with `results(include_sample=True)`.

**"Not a like-for-like comparison".** The configurations ran different benchmarks, so their scores don't compare.
"Only shared benchmarks" keeps the ones all of them ran.

**Scores differ from another machine's.** Check the weights (Results page or `results()`), the pass threshold and the
efficiency reference: they change the final score. Every run also records the LLMDyno version that scored it.

## Remote access

**401, or "refused the connection".** The request needs the access token. It was printed once when the server first
started with `--host`; if it is lost, `llmdyno token --rotate` on the server makes a new one.

**401 on the server's own machine.** Open it as `http://127.0.0.1:8777` or `http://localhost:8777`. A request that
names the machine any other way (its host name or LAN address) counts as remote and needs the token.

**"LLMDyno refused a request from the web page at …" (403).** A page from another website tried to use LLMDyno through
your browser, and was refused. If it was your own tool, call the API from a program instead of a web page, or serve
the page from `localhost`.

**Requests through a reverse proxy need no token.** The proxy isn't sending `X-Forwarded-For`; see
[Remote mode](REMOTE.md#https-and-reverse-proxies).

**Live updates don't arrive.** Something blocks the WebSocket at `/ws` (a proxy without WebSocket support, for
example). The dashboard shows "Reconnecting…"; the library and the JS client fall back to polling for status changes.

## JavaScript and npx

**`npx llmdyno` says it found no way to run LLMDyno.** Install LLMDyno with pip, or install uv or pipx; or point
`LLMDYNO_PYTHON` at a Python that has LLMDyno. `LLMDYNO_LAUNCHER_DRY_RUN=1 npx llmdyno` shows what it would run.

**"the server runs LLMDyno X and this client is Y".** The npm client and the server differ in their first two version
numbers. Install the matching versions (`npm install llmdyno@X`).

**The client fails in a browser.** The server sends no CORS headers, so the client works in a browser only on pages the
LLMDyno server serves itself. Use it from Node.

## The library

**`TypeError: … unknown … setting`.** A profile setting name is misspelt; the message lists the known ones.

**Plans from a script and the dashboard collide.** Running plans from a script and from the web app at the same time
on one machine is not supported: both would load models onto the same GPU. Start plans from one place, or drive the
running server from the script with `llmdyno.connect("http://127.0.0.1:8777")`.

**Nothing happens until Ctrl+C.** `bench()` waits for the plan; `bench(..., wait=False)` returns the plan at once.

## Getting help

Open an [issue](https://github.com/speak2jerome/llmdyno/issues) with the output of `llmdyno --version` and
`llmdyno doctor`, what you did, and the error. A run's **Logs** tab is usually the most useful thing to include.
Agents never see your API keys, so their logs can't contain them, but read what you paste anyway. Report security problems privately, as described in
[SECURITY.md](https://github.com/speak2jerome/llmdyno/blob/main/SECURITY.md).
