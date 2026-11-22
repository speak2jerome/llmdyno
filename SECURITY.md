# Security policy

## Supported versions

Only the latest 0.x release gets security fixes.

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private vulnerability reporting
(**Security → Report a vulnerability** on the repository), or email jeromeeliezer@zynxtech.in with "LLMDyno security"
in the subject. You should hear back within a week.

## Security model, briefly

- **Network.** LLMDyno listens on `127.0.0.1` by default. Requests from your own machine are not authenticated, so
  any program running as any user on that machine can use its API. A request counts as local only when it comes from
  a loopback address, addresses the server as `localhost`, `127.0.0.1` or `[::1]`, and carries no proxy header; so a
  web page that makes its own domain resolve to 127.0.0.1 (DNS rebinding) still needs the token. Browsers mark their
  requests with the page's origin, and a local request from a page on another website is refused, so sites you visit
  can't drive LLMDyno or read its live events. With `llmdyno serve --host 0.0.0.0`, every request
  from another machine must present the access token (`Authorization: Bearer`, or `?token=`). The server speaks plain
  HTTP: across a network you don't trust, use an SSH tunnel or a reverse proxy with HTTPS, and make sure the proxy sets
  `X-Forwarded-For` (see [docs/REMOTE.md](docs/REMOTE.md)). Changes made from other machines are logged to
  `<data>/logs/remote-requests.jsonl`.
- **Keys.** API keys, the Hugging Face and Artificial Analysis keys and the access token are kept in `secrets.json` in
  the data folder: encrypted with DPAPI on Windows (readable only by your Windows user), and as plain text in a file
  only your user can read (mode 600) on Linux and macOS. No API call returns them. Provider keys are passed only to the
  per-run proxy container, never to agent sandboxes, which get a placeholder.
- **Sandboxes.** Agents run in containers on an internal Docker network whose only route out is their own proxy, which
  enforces spend caps. Graders and code-quality analysis run with no network at all.
- **Third-party code.** Benchmarks, harness manifests, your own agents (`python_harness()`, `node_harness()`) and
  models you import are code and data from other people, and harness images run their install steps with network
  access while they are built. Review them as you would any other download.
