"""Errors raised by LLMDyno's services and Python API.

Every error carries the HTTP status the web API answers with, so the same exception means the same thing whether you
call `llmdyno.bench()` from Python or POST /api/plans: one handler in server.py turns it into {"detail": message}.
All of them inherit from LLMDynoError; catch that to handle anything LLMDyno refuses or fails to do."""


class LLMDynoError(Exception):
    """Anything LLMDyno refuses or fails to do; the message says why and usually what to change."""
    status = 400


class InvalidError(LLMDynoError, ValueError):
    """A request that cannot be valid as given (bad setting, missing field, unknown option)."""
    status = 400


class ForbiddenError(LLMDynoError, PermissionError):
    """Not allowed, for example editing a built-in benchmark or suite."""
    status = 403


class NotFoundError(LLMDynoError, LookupError):
    """No such profile, model, plan, run, benchmark, file, …"""
    status = 404


class ConflictError(LLMDynoError):
    """The thing is in use, already exists, ambiguous, or in the wrong state for this action."""
    status = 409


class RiskNotAcknowledgedError(InvalidError):
    """A plan has danger warnings (VRAM spill, out of memory, …) that need acknowledge_risks=True."""
    status = 428


class RateLimitError(LLMDynoError):
    """An upstream rate limit, for example the Artificial Analysis free tier's 100 requests a day."""
    status = 429


class UpstreamError(LLMDynoError):
    """An external service failed (Hugging Face, a provider API, Artificial Analysis, …)."""
    status = 502


class InsufficientStorageError(LLMDynoError):
    """Not enough disk space, for example for a model download."""
    status = 507


class PreflightError(LLMDynoError):
    """A plan cannot start. `problems` are the blocking items, `warnings` the rest of the preflight report."""
    status = 409

    def __init__(self, problems, warnings=None, report=None):
        self.problems, self.warnings, self.report = list(problems), list(warnings or []), report or {}
        super().__init__("the plan cannot start:\n  - " + "\n  - ".join(self.problems))


_BY_STATUS = {400: InvalidError, 403: ForbiddenError, 404: NotFoundError, 409: ConflictError,
              428: RiskNotAcknowledgedError, 429: RateLimitError, 502: UpstreamError, 507: InsufficientStorageError}


def http(status: int, detail) -> LLMDynoError:
    """The error class for an HTTP status, with that message (services use this where the web API used
    HTTPException, so status codes and messages stay exactly as they were)."""
    err = _BY_STATUS.get(int(status), LLMDynoError)(str(detail))
    err.status = int(status)
    return err
