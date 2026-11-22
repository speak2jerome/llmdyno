/** The errors the client throws: the same family, names and HTTP statuses as the Python library's llmdyno.errors. */

export class LLMDynoError extends Error {
  static readonly defaultStatus: number = 400;
  /** The HTTP status the server answered with (or the status this kind of error stands for). */
  status: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = new.target.name;
    this.status = status ?? (new.target as typeof LLMDynoError).defaultStatus;
  }
}

/** Bad input: a missing or unknown parameter, an invalid setting (400). */
export class InvalidError extends LLMDynoError {}

/** Not allowed: a wrong or missing access token, or an action the server refuses (401, 403). */
export class ForbiddenError extends LLMDynoError {
  static override readonly defaultStatus: number = 403;
}

/** No such plan, run, profile, … (404). */
export class NotFoundError extends LLMDynoError {
  static override readonly defaultStatus: number = 404;
}

/** It clashes with what is there: a name in use, a plan already running (409). */
export class ConflictError extends LLMDynoError {
  static override readonly defaultStatus: number = 409;
}

/** A risk (VRAM spill, out of memory, …) that needs acknowledgeRisks: true (428). */
export class RiskNotAcknowledgedError extends InvalidError {
  static override readonly defaultStatus: number = 428;
}

/** A provider's rate limit (429). */
export class RateLimitError extends LLMDynoError {
  static override readonly defaultStatus: number = 429;
}

/** A provider, Hugging Face or another service LLMDyno talks to failed (502). */
export class UpstreamError extends LLMDynoError {
  static override readonly defaultStatus: number = 502;
}

/** The disk is full (507). */
export class InsufficientStorageError extends LLMDynoError {
  static override readonly defaultStatus: number = 507;
}

/** bench() checked the plan and something blocks it. problems are the reasons; report is the full preflight. */
export class PreflightError extends LLMDynoError {
  static override readonly defaultStatus: number = 409;
  problems: string[];
  warnings: string[];
  report: Record<string, unknown> | undefined;

  constructor(problems: string[], warnings: string[] = [], report?: Record<string, unknown>) {
    super("the plan cannot start: " + problems.join("; "));
    this.problems = problems;
    this.warnings = warnings;
    this.report = report;
  }
}

const BY_STATUS: Record<number, typeof LLMDynoError> = {
  400: InvalidError, 401: ForbiddenError, 403: ForbiddenError, 404: NotFoundError, 409: ConflictError,
  422: InvalidError, 428: RiskNotAcknowledgedError, 429: RateLimitError, 502: UpstreamError,
  507: InsufficientStorageError,
};

/** The error for an HTTP status and the server's detail message. */
export function httpError(status: number, detail: unknown): LLMDynoError {
  const message = typeof detail === "string" ? detail : JSON.stringify(detail);
  const Cls = BY_STATUS[status] ?? LLMDynoError;
  return new Cls(message, status);
}
