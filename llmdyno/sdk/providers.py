"""Cloud providers: vendors, keys, budgets and spend, connection tests and price lookup."""
from __future__ import annotations

from typing import Union

import os
import re

from ..errors import ConflictError, LLMDynoError, NotFoundError
from ._core import Handle, call, covers

__all__ = ["Provider", "list_providers", "provider", "add_provider", "vendors", "lookup_price", "local_servers",
           "ollama_model", "openai_compatible", "litellm_model"]


class Provider(Handle):
    """A cloud provider account: vendor, endpoint, API key (kept encrypted in the data folder, never returned),
    a hard budget and what has been spent against it."""

    @property
    def name(self) -> str:
        return self._data["name"]

    @property
    def vendor(self) -> str:
        return self._data["vendor"]

    @property
    def budget_usd(self) -> float:
        return self._data["budget_usd"]

    @property
    def spent_usd(self) -> float:
        """Spend recorded against the budget (fetched fresh)."""
        return self.refresh()._d["spent_usd"]

    @property
    def has_key(self) -> bool:
        return bool(self._data.get("has_key"))

    def refresh(self) -> "Provider":
        hit = [p for p in call("providers.list_providers") if p["id"] == self.id]
        if not hit:
            raise NotFoundError(f"no provider {self.id}")
        self._d = hit[0]
        return self

    @covers("POST /api/providers/{pid}/test")
    def test(self) -> dict:
        """Check the key and endpoint by listing models: {"ok", "error", "models", "latency_ms"}."""
        out = call("providers.test_provider", pid=self.id)
        self.refresh()
        return out

    def models(self, refresh: bool = False) -> list:
        """Model ids this provider offers (from the last connection test; refresh=True tests again)."""
        cached = self._data.get("models_cache") or []
        if refresh or not cached:
            return self.test()["models"]
        return list(cached)

    @covers("PATCH /api/providers/{pid}")
    def update(self, *, name: str | None = None, budget_usd: float | None = None, api_style: str | None = None,
               base_url: str | None = None) -> "Provider":
        """Rename, change the budget (USD, a hard cap), the API style ("openai-chat", "openai-responses",
        "anthropic", …) or the base URL."""
        body = {k: v for k, v in (("name", name), ("budget_usd", budget_usd), ("api_style", api_style),
                                  ("base_url", base_url)) if v is not None}
        self._d = call("providers.patch_provider", pid=self.id, body=body)
        return self

    @covers("PUT /api/providers/{pid}/key")
    def set_key(self, api_key: str) -> "Provider":
        self._d = call("providers.set_provider_key", pid=self.id, body={"api_key": api_key})
        return self

    @covers("DELETE /api/providers/{pid}/key")
    def remove_key(self) -> "Provider":
        self._d = call("providers.del_provider_key", pid=self.id)
        return self

    @covers("POST /api/providers/{pid}/reset-spend")
    def reset_spend(self) -> "Provider":
        """Start counting spend against the budget from zero again."""
        self._d = call("providers.reset_spend", pid=self.id)
        return self

    @covers("DELETE /api/providers/{pid}")
    def delete(self) -> None:
        """Remove the provider and its key (refused while profiles use it)."""
        call("providers.delete_provider", pid=self.id)

    def __repr__(self):
        d = self._d or {}
        return (f"<llmdyno.Provider {d.get('name', self.id)!r} {d.get('vendor', '')} "
                f"${d.get('spent_usd', 0):.2f} of ${d.get('budget_usd', 0):.2f}>")


@covers("GET /api/providers")
def list_providers(vendor: str | None = None) -> list:
    """Your cloud providers (optionally of one vendor)."""
    return [Provider(p) for p in call("providers.list_providers") if vendor in (None, p["vendor"])]


def provider(name_or_id: Union[str, Provider]) -> Provider:
    """A provider by id, name, or vendor id when you have only one of that vendor."""
    if isinstance(name_or_id, Provider):
        return name_or_id
    key = str(name_or_id)
    rows = call("providers.list_providers")
    hit = ([p for p in rows if p["id"] == key] or [p for p in rows if p["name"].lower() == key.lower()]
           or [p for p in rows if p["vendor"] == key])
    if not hit:
        raise NotFoundError(f"no provider {key!r}")
    if len(hit) > 1:
        raise ConflictError(f"{len(hit)} providers match {key!r}; use the id")
    return Provider(hit[0])


@covers("POST /api/providers")
def add_provider(vendor: str, *, api_key: str | None = None, name: str | None = None, base_url: str | None = None,
                 api_style: str | None = None, budget_usd: float = 5.0) -> Provider:
    """Add a provider account. vendor is one of vendors() ("custom" for any OpenAI-compatible endpoint, which
    needs base_url). cloud_model() does this for you when no provider of that vendor exists yet."""
    body = {"vendor": vendor, "api_key": api_key, "name": name, "base_url": base_url, "api_style": api_style,
            "budget_usd": budget_usd}
    return Provider(call("providers.create_provider", body={k: v for k, v in body.items() if v is not None}))


@covers("GET /api/vendors")
def vendors() -> list:
    """Supported vendors with their API styles, endpoints, where to get a key and notes."""
    return call("providers.list_vendors")


@covers("GET /api/pricing/lookup")
def lookup_price(vendor: str, model: str) -> dict | None:
    """Price per 1M tokens ({"input", "output", "cached"}, plus context length and the matched model) from
    OpenRouter's catalog, or None when the model is not found."""
    return call("providers.pricing_lookup", vendor=vendor, model=model)["match"]


# ------------------------------------------------------------------ servers on your own machine, gateways
@covers("GET /api/providers/local-servers")
def local_servers() -> list:
    """OpenAI-compatible servers running on the machine LLMDyno runs on (Ollama, LM Studio, vLLM, SGLang, a
    llama.cpp server, a LiteLLM proxy), each with its URL, the URL the sandbox uses, and its models."""
    return call("providers.local_servers")


def _docker_url(url: str) -> str:
    """The sandbox proxy reaches this machine's servers through host.docker.internal."""
    return re.sub(r"//(localhost|127\.0\.0\.1|0\.0\.0\.0)(?=[:/])", "//host.docker.internal", url.rstrip("/"))


def ollama_model(model: str, *, name: str | None = None, **params):
    """A model served by Ollama on this machine, as a profile: ollama_model("qwen3-coder:30b", ctx=65536).
    Ollama must be running (it is found on its usual port, 11434)."""
    from .profiles import cloud_model
    server = next((s for s in local_servers() if s["id"] == "ollama"), None)
    if server is None:
        raise LLMDynoError("Ollama is not running on this machine (nothing answers on port 11434); start it first")
    if model not in server["models"]:
        raise NotFoundError(f"Ollama has no {model!r}; it has: {', '.join(server['models']) or 'no models'} "
                            f"(ollama pull {model})")
    return cloud_model("custom", model, base_url=server["docker_url"], name=name or f"{model} · Ollama",
                       pricing=None, **params)


def openai_compatible(base_url: str, model: str | None = None, *, api_key: str | None = None, name: str | None = None,
                      api_style: str | None = None, **params):
    """Any OpenAI-compatible endpoint as a profile: LM Studio, vLLM, SGLang, a llama.cpp server, a gateway.
    localhost URLs are rewritten so the sandbox can reach them. Without model=, the endpoint must serve exactly one
    (it is looked up among local_servers())."""
    from .profiles import cloud_model
    url = _docker_url(base_url)
    if model is None:
        hit = next((s for s in local_servers() if s["docker_url"] == url), None)
        models = hit["models"] if hit else []
        if len(models) != 1:
            raise LLMDynoError(f"pass model=; {base_url} serves {', '.join(models) or 'nothing LLMDyno can see'}")
        model = models[0]
    return cloud_model("custom", model, base_url=url, api_key=api_key, api_style=api_style,
                       name=name or f"{model} · {re.sub(r'^https?://', '', base_url).rstrip('/')}", pricing=None,
                       **params)


def litellm_model(model: str, *, base_url: str | None = None, api_key: str | None = None, name: str | None = None,
                  budget_usd: float | None = None, pricing="auto", **params):
    """A model behind a LiteLLM proxy (Azure OpenAI, Bedrock, Vertex AI, … through one OpenAI-compatible endpoint):
    litellm_model("bedrock/anthropic.claude-sonnet-4-5", reasoning_effort="low"). Start the proxy yourself, e.g.
    `litellm --model bedrock/...` or `litellm --config config.yaml` (pip install "litellm[proxy]"); base_url defaults
    to it on this machine's port 4000. Prices come from LiteLLM's table when the litellm package is installed
    ("llmdyno[litellm]"); budgets cap spend as for any cloud provider."""
    from .profiles import cloud_model
    key = api_key or os.environ.get("LITELLM_API_KEY") or os.environ.get("LITELLM_MASTER_KEY")
    return cloud_model("litellm", model, base_url=_docker_url(base_url) if base_url else None, api_key=key,
                       name=name or f"{model} · LiteLLM", budget_usd=budget_usd, pricing=pricing, **params)

