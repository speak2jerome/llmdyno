You are working in /workspace, an empty project. Build a small "text jobs" web application with a FastAPI backend, a separate background worker process, and a TypeScript frontend.

## Backend

Python package `backend/` (with `backend/__init__.py`). The FastAPI instance is `app` in `backend/main.py`.

- Jobs are stored in SQLite. The database path comes from the environment variable `JOBS_DB` (default `./jobs.db`) and must be read at request time, not at import time, because tests set it per test.
- `POST /api/jobs` with JSON `{"text": str, "operation": str}`:
  - `operation` is one of `wordcount`, `uppercase`, `reverse_words`, `summary`.
  - `text` must be 1 to 10000 characters.
  - Invalid input returns 422.
  - Success returns 201 with the job JSON (status `queued`).
- `GET /api/jobs/{id}` returns the job JSON, or 404 if it is unknown.
- `GET /api/jobs` returns a list of jobs, newest first. The optional query parameter `status` filters by status.
- `POST /api/jobs/{id}/cancel`: if the job is `queued`, set its status to `cancelled` and return 200 with the job. Otherwise return 409. An unknown id returns 404.
- Job JSON shape: `{"id": int, "text": str, "operation": str, "status": "queued"|"running"|"done"|"failed"|"cancelled", "result": <any or null>, "error": <str or null>, "created_at": str, "finished_at": <str or null>}`.
- The API must NOT process jobs itself. Jobs stay `queued` until the worker handles them.

## Worker

Python package `worker/` (with `worker/__init__.py`), code in `worker/worker.py`.

- `process_next_job(db_path: str) -> bool`: atomically claim the oldest `queued` job (set it to `running`), compute the result, and store it with status `done`. If an exception occurs, store status `failed` with an error message. Set `finished_at` and return True. Return False if there is no queued job.
- `main()`: loop forever calling `process_next_job(os.environ.get("JOBS_DB", "./jobs.db"))`, sleeping 0.5 s when idle. It must be runnable as `python -m worker.worker`.
- Operation results:
  - `wordcount` → `{"words": <number of whitespace-separated words>, "chars": <len(text)>}`
  - `uppercase` → `text.upper()`
  - `reverse_words` → the words (split on whitespace) in reverse order, joined by single spaces
  - `summary` → the first sentence: the text up to and including the first `.`, `!` or `?`, stripped. If there is no such character, use the stripped text. In both cases, truncate to at most 100 characters.

## Frontend

Directory `frontend/`.

- `frontend/tsconfig.json` with `"strict": true`, compiling `frontend/src/*.ts` to `frontend/dist/`.
- `frontend/src/api.ts` exports:
  - `interface Job`, matching the job JSON
  - the union types `Operation` and `JobStatus`
  - functions `createJob(text: string, operation: Operation): Promise<Job>`, `getJob(id: number): Promise<Job>` and `listJobs(status?: JobStatus): Promise<Job[]>`, all using `fetch`
- `frontend/src/main.ts` wires a form in `frontend/index.html` (a textarea, an operation select and a submit button) to `createJob`. It then polls `getJob` every second until the job is finished, and shows the result.
- `tsc -p frontend` must succeed with zero errors. TypeScript is installed globally as `tsc`.
- Serve the frontend from FastAPI: `GET /` returns `frontend/index.html`, and `/static` serves `frontend/dist`.

## Also

- `requirements.txt`.
- A `README.md` describing how to run the API (uvicorn), the worker and the frontend build.
- pytest tests in `backend/tests/` covering the API and the worker. They must pass with `pytest -q`.

All packages (fastapi, uvicorn, httpx, pytest, typescript) are installed. There is no internet access, so do not install anything. When you are finished, reply with a short summary.
