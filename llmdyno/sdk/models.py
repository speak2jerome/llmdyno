# pyright: strict, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""GGUF models: Hugging Face search, fit estimates before download, downloads, imports and the recommended list."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Union

from ..errors import ConflictError, LLMDynoError, NotFoundError
from ._core import Handle, Job, say, call, covers

__all__ = ["Model", "list_models", "model", "search_models", "repo_info", "estimate", "download_model",
           "import_models", "recommended_models"]


class Model(Handle):
    """A GGUF model in the data folder, downloaded from Hugging Face or registered from disk."""

    _get_op, _id_arg = "models.model_detail", "mid"

    @property
    def name(self) -> str:
        return self._data["name"]

    @property
    def repo(self) -> str:
        return self._data.get("repo") or ""

    @property
    def quant(self) -> str:
        return self._data.get("quant") or ""

    @property
    def status(self) -> str:
        """ready, queued, downloading, paused, failed, … (as last fetched; refresh() to update)."""
        return self._data["status"]

    @property
    def size_gb(self) -> float:
        return round((self._data.get("size_bytes") or 0) / 2**30, 2)

    @property
    def paths(self) -> list[Any]:
        """The model's file(s) on disk."""
        return list(self._data.get("paths") or [])

    @covers("GET /api/models/{mid}")
    def refresh(self) -> "Model":
        return super().refresh()

    def contexts(self) -> list[Any]:
        """Projected memory and verdict at each context size with the default settings for this machine (what the
        model page's context table shows). Empty until the model is downloaded."""
        return list(self._fresh().get("contexts") or [])

    def profile(self, name: str | None = None, **params: Any):
        """A local profile for this model with these settings (same keywords as local_model())."""
        from .profiles import local_profile
        return local_profile(self._data, name, params, quiet=True)

    @covers("POST /api/models/{mid}/pause")
    def pause(self) -> None:
        """Pause its download (the partial file is kept; resume() carries on)."""
        call("models.model_pause", mid=self.id)

    @covers("POST /api/models/{mid}/resume")
    def resume(self, wait: bool = True, quiet: bool = False) -> Union["Model", Job]:
        """Carry on with an interrupted or paused download. wait=False returns the download Job."""
        job = Job(call("models.model_resume", mid=self.id)["job_id"])
        if not wait:
            return job
        job.wait(quiet=quiet)
        return self.refresh()

    @covers("DELETE /api/models/{mid}")
    def delete(self, files: bool = False) -> dict[str, Any]:
        """Forget the model. files=True also deletes downloaded files (files you imported are never deleted).
        Profiles using it stay, without a model. Returns what was removed."""
        return call("models.model_delete", mid=self.id, delete_files=files)

    def __repr__(self):
        d = self._d or {}
        return f"<llmdyno.Model {d.get('name', self.id)!r} {d.get('quant', '')} {d.get('status', '')}>"


@covers("GET /api/models")
def list_models(status: str | None = None) -> list[Any]:
    """Models in the data folder, newest first; status="ready" keeps the usable ones."""
    return [Model(m) for m in call("models.list_models") if status in (None, m["status"])]


def model(name_or_id: Union[str, Model]) -> Model:
    """A model by id, by name (the file name without .gguf), or as "repo:quant"."""
    if isinstance(name_or_id, Model):
        return name_or_id
    key = str(name_or_id)
    rows = call("models.list_models")
    repo, _, quant = key.rpartition(":") if ":" in key and "/" in key else ("", "", "")
    hit = ([m for m in rows if m["id"] == key] or [m for m in rows if m["name"].lower() == key.lower()]
           or [m for m in rows if repo and m["repo"] == repo and (m["quant"] or "").lower() == quant.lower()])
    if not hit:
        raise NotFoundError(f"no model {key!r}; list_models() shows what is in the data folder")
    if len(hit) > 1:
        raise ConflictError(f"{len(hit)} models match {key!r}; use the id")
    return Model(hit[0])


# ------------------------------------------------------------------ Hugging Face
@covers("GET /api/hub/search")
def search_models(query: str, sort: str = "downloads", limit: int = 30) -> list[Any]:
    """Search Hugging Face for GGUF repositories (sort: downloads, likes or lastModified)."""
    return call("models.hub_search", q=query, sort=sort, limit=limit)


@covers("GET /api/hub/repo")
def repo_info(repo: str) -> dict[str, Any]:
    """A Hugging Face repository's GGUF variants (quant, size, files, a first fit hint for this GPU) plus its
    license, downloads, likes, tags and whether it is gated."""
    return call("models.hub_repo", repo=repo)


def _variant(repo: str, quant: str, info: dict[str, Any] | None = None) -> dict[str, Any]:
    """The repository variant for a quant name ("UD-Q3_K_XL", "Q4_K_M", …)."""
    info = info or repo_info(repo)
    variants = [v for v in info["variants"] if not v["mmproj"]]
    if not quant:
        raise LLMDynoError(f"pick a quant for {repo}: {', '.join(v['quant'] for v in variants)}")
    hit = [v for v in variants if v["quant"].lower() == quant.lower()] or \
          [v for v in variants if quant.lower() in v["id"].lower()]
    if not hit:
        raise NotFoundError(f"{repo} has no {quant}; available: {', '.join(v['quant'] for v in variants)}")
    return hit[0]


@covers("POST /api/hub/estimate")
def estimate(repo: str, quant: str, **params: Any) -> dict[str, Any]:
    """Will it fit, before downloading anything: reads the GGUF header over HTTP and projects GPU and system memory
    for these settings (same keywords as local_model(): ctx, kv_cache, n_cpu_moe, …). Returns {"check": verdict,
    projected memory and warnings, "contexts": the table for other context sizes, "params", "meta"}."""
    from .profiles import profile_params
    v = _variant(repo, quant)
    return call("models.hub_estimate", body={"repo": repo, "variant_id": v["id"], "params": profile_params("local", params)})


@covers("POST /api/models/download")
def download_model(repo: str, quant: str, *, wait: bool = True, quiet: bool = False) -> Union[Model, Job]:
    """Download one quant of a Hugging Face GGUF repository into the models folder (resumable, checksum-verified).
    Returns the Model when done, or the download Job with wait=False. An interrupted download resumes."""
    v = _variant(repo, quant)
    mine = [m for m in call("models.list_models")
            if m["repo"] == repo and (m["quant"] or "").lower() == v["quant"].lower()]
    if mine and mine[0]["status"] == "ready":
        return Model(mine[0])
    if mine:
        return Model(mine[0]).resume(wait=wait, quiet=quiet)
    say(quiet, f"Downloading {repo} {v['quant']} ({v['size_bytes'] / 2**30:.1f} GB)")
    r = call("models.model_download", body={"repo": repo, "variant_id": v["id"]})
    job = Job(r["job_id"])
    if not wait:
        return job
    job.wait(quiet=quiet)
    return Model(r["model_id"]).refresh()


@covers("POST /api/models/import")
def import_models(folder: Union[str, Path]) -> list[Any]:
    """Register the GGUF files in a folder where they are (nothing is copied); returns the models added."""
    r = call("models.model_import", body={"folder": str(Path(folder).expanduser())})
    return [Model(mid) for mid in r["ids"]]


@covers("GET /api/models/recommended/list")
def recommended_models() -> list[Any]:
    """LLMDyno's suggested local models for coding agents, each with why and whether it is already downloaded."""
    return call("models.recommended")["items"]
