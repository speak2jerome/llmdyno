// Thin fetch wrapper: JSON in/out, readable errors (FastAPI's {detail}) surfaced to the UI.
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// ---------------------------------------------------------------- remote access token
// On the server's own machine nothing is needed. Opened from elsewhere, the API answers 401 until the browser presents
// the server's access token; it is kept in this browser and sent with every request (?token= for links and the
// WebSocket, which cannot carry headers). `results.open()` from a connected Python session passes it as #token=.
const TOKEN_KEY = "llmdyno.token";
let memoryToken: string | null = null;     // when the browser refuses storage

(function tokenFromHash() {
  const m = location.hash.match(/(?:^#|&)token=([^&]+)/);
  if (!m) return;
  try {
    localStorage.setItem(TOKEN_KEY, decodeURIComponent(m[1]));
  } catch {
    /* storage unavailable: the prompt will ask */
  }
  history.replaceState(null, "", location.pathname + location.search);
})();

export function apiToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY) || memoryToken;
  } catch {
    return memoryToken;
  }
}

export function authHeaders(): Record<string, string> {
  const t = apiToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export function withToken(url: string): string {
  const t = apiToken();
  return t ? `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(t)}` : url;
}

let asking: Promise<boolean> | null = null;

function askForToken(reason: string): Promise<boolean> {
  if (!asking) asking = tokenDialog(reason).finally(() => (asking = null));
  return asking;
}

function tokenDialog(reason: string): Promise<boolean> {
  return new Promise((resolve) => {
    const wrap = document.createElement("div");
    wrap.className = "token-gate";
    wrap.innerHTML = `
      <form class="card card-pad token-card" role="dialog" aria-modal="true" aria-labelledby="token-title">
        <h2 id="token-title">Connect to this LLMDyno</h2>
        <p class="token-why">You opened LLMDyno from another machine, so it needs the server's access token. It was
          printed when the server started with <code>--host</code>; <code>llmdyno token --rotate</code> on the server
          makes a new one.</p>
        <div class="field">
          <label for="token-input">Access token</label>
          <input id="token-input" class="input" type="password" autocomplete="off" spellcheck="false" required />
          <div class="error" hidden></div>
        </div>
        <div class="token-actions"><button class="btn primary" type="submit">Connect</button></div>
      </form>`;
    document.body.appendChild(wrap);
    const form = wrap.querySelector("form") as HTMLFormElement;
    const input = wrap.querySelector("input") as HTMLInputElement;
    const err = wrap.querySelector(".error") as HTMLDivElement;
    const button = wrap.querySelector("button") as HTMLButtonElement;
    if (!/needs its access token|does not accept remote/.test(reason)) {
      err.textContent = reason;
      err.hidden = false;
    }
    input.focus();
    form.onsubmit = async (e) => {
      e.preventDefault();
      const t = input.value.trim();
      if (!t) return;
      button.disabled = true;
      const ok = await fetch("/api/health", { headers: { Authorization: `Bearer ${t}` } }).then((r) => r.ok, () => false);
      button.disabled = false;
      if (!ok) {
        err.textContent = "That token was not accepted. Check it on the server with llmdyno token --rotate.";
        err.hidden = false;
        input.select();
        return;
      }
      try {
        localStorage.setItem(TOKEN_KEY, t);
      } catch {
        /* storage unavailable: this page keeps working until it is reloaded */
      }
      memoryToken = t;
      wrap.remove();
      resolve(true);
      window.dispatchEvent(new Event("llmdyno:token"));
    };
  });
}

async function request<T>(method: string, path: string, body?: unknown, raw = false, retried = false): Promise<T> {
  const token = apiToken();
  const res = await fetch(`/api${path}`, {
    method,
    headers: {
      ...(body !== undefined && !(body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
  });
  if (res.status === 401 && !retried) {
    let reason = "";
    try {
      reason = (await res.clone().json()).detail || "";
    } catch {
      /* not JSON */
    }
    if (await askForToken(reason)) return request<T>(method, path, body, raw, true);
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const d = await res.json();
      msg = typeof d.detail === "string" ? d.detail : Array.isArray(d.detail) ? d.detail.map((x: any) => x.msg).join("; ") : msg;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  if (raw) return (await res.text()) as unknown as T;
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("json") ? await res.json() : await res.text()) as T;
}

export const api = {
  get: <T = any>(p: string) => request<T>("GET", p),
  text: (p: string) => request<string>("GET", p, undefined, true),
  post: <T = any>(p: string, b: unknown = {}) => request<T>("POST", p, b),
  put: <T = any>(p: string, b: unknown = {}) => request<T>("PUT", p, b),
  patch: <T = any>(p: string, b: unknown = {}) => request<T>("PATCH", p, b),
  del: <T = any>(p: string) => request<T>("DELETE", p),
  upload: <T = any>(p: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<T>("POST", p, fd);
  },
};

export function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

export function download(path: string) {
  const a = document.createElement("a");
  a.href = withToken(`/api${path}`);
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
