"""Cloud providers: vendors, keys, budgets and spend, connection tests and price lookup."""
from __future__ import annotations

from typing import Union

from ..errors import ConflictError, NotFoundError
from ._core import Handle, call, covers

__all__ = ["Provider", "list_providers", "provider", "add_provider", "vendors", "lookup_price"]


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
