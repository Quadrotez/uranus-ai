# Uranus-AI test notes

## Local UI verification

- Vite dev server rendered the Uranus-AI interface at `http://127.0.0.1:5173`.
- Visible navigation included Agent, Computer and Settings, plus conversation history, model picker and composer.
- The first visual pass exposed an undesirable bootstrap behavior: the UI tried Ollama before a configured OpenRouter provider and showed a connection notice. The selection logic was changed to prefer a configured-key provider, then OpenCode, then Ollama. A second browser pass displayed the OpenRouter model picker with free models and no Ollama warning.
- The interface is intentionally dark, compact and operator-oriented. The Computer page contains Browser, Terminal and Workspace panels; Settings contains provider cards, behavior controls and Agent Skills.

## Integration checks

- API `/health` and `/api/bootstrap` returned successfully.
- API terminal endpoint executed `printf smoke-ok` inside the local sandbox and returned exit code 0.
- Five deterministic unit tests passed, including path traversal rejection, provider preset coverage, provider-safe tool names and approval policy.
- A free OpenRouter model completed a short text smoke test.
- The same free model successfully called `plan_create` and `terminal_exec`; the terminal result was persisted with exit code 0.
- In normal `ask` mode, `terminal_exec` created a pending approval, the run paused, and continued only after an explicit approved decision.
- The local environment did not provide a Docker daemon, so a real `docker compose build/up` check remains a user-side verification step.

## Computer UI verification

- The Computer page rendered Browser, Terminal and Workspace panels with visible controls.
- The terminal panel exposed a command editor and execute button; browser panel exposed URL, Snapshot, Open, Scroll and Screenshot actions.
- In the no-Docker local environment, Snapshot returned a fetch failure because the separate browser worker was not started. This is expected for the local fallback and should be verified with `docker compose up --build`, where the Playwright container is present.

## Self-improvement verification

- In an isolated demo workspace containing `ARCHITECTURE.md`, `README.md` and `status.txt`, a free OpenRouter model read the architecture, created a three-step plan, wrote `status-self-check.txt` with the requested content, and ran a verification command.
- The write and verification each produced an approval; both were approved explicitly before execution.
- Persisted tool results show `workspace_write` returned `ok=true`, `bytes=29`, and `terminal_exec` returned `exit_code=0` with `stdout=verified`.
- This satisfies the MVP self-improvement criterion for bounded code/workspace changes. It does not yet imply autonomous repository merges, migrations or host-level changes; those remain intentionally gated.

## Browser worker verification

- Local Playwright worker initially failed because the sandbox environment had the Python package but not the Playwright-managed executable. The worker was made configurable via `BROWSER_EXECUTABLE_PATH`; Docker keeps its bundled browser, while local Chromium can be selected explicitly.
- With system Chromium, browser worker health returned `ok`.
- `open` navigated to `https://example.com/`, `snapshot` returned title and visible text, and `screenshot` created a 1440x900 PNG at `workspace/artifacts/browser-smoke.png`.

## Parallel research verification

- A free OpenRouter model called `research_parallel` with two small public documentation queries.
- The tool executed both searches independently and returned direct URLs (`https://fastapi.tiangolo.com/` and `https://playwright.dev/python/docs/library`) with snippets. The result is stored in the run tool trace and no approvals were needed for public search.

## Provider catalog checks

- OpenRouter catalog returned 417 models, including multiple IDs explicitly marked `:free`; the inference checks used `cohere/north-mini-code:free` only.
- Groq catalog returned 14 model IDs using the supplied temporary key; no generation request was made against Groq.
- Gemini OpenAI-compatible catalog returned 54 model IDs; no generation request was made against Gemini.
- The temporary key was used only in the local `/tmp/uranus-data` test database and was never written into the repository files.

## Resilience regression

- When the local browser process exited, the API→browser route initially surfaced an unhandled HTTP 500. The internal proxy now catches transport errors and returns structured `{ok:false,error:...}` JSON; this keeps the UI usable and makes a missing worker diagnosable.

## Release state

- Repository: https://github.com/Quadrotez/uranus-ai
- Visibility: PUBLIC
- Branch: `main`
- Commits: `6d514e4` (initial workspace) and `2c5dc4c` (provider/browser/setup hardening)
- The working tree was clean after push, and the staged secret scan found no provider-key patterns.

## Browser unhealthy fix regression

The user-provided compose log showed that images built successfully but `uranus-browser-1` became unhealthy before API startup. The browser service had been forced to an arbitrary host UID/GID while its image created a different user, and bind-mounted profile/workspace directories could race with service startup. The compose fix adds a root-only one-shot `init-volumes` service, makes sandbox and browser wait for it, keeps API/web ordering intact, sets writable HOME/XDG cache paths for Playwright, and adds a 20-second browser healthcheck start period. A local runtime simulation with the same HOME/XDG/Playwright variables and system Chromium returned health `ok` and opened `https://example.com/` successfully.

## User-reported compose failure

The follow-up log isolated the failure precisely. Compose printed `The "TARGET_UID" variable is not set` and `The "TARGET_GID" variable is not set`, then `init-volumes` exited with code 1. The dollar variables inside the YAML command were being interpolated by Compose on the host before the shell inside Alpine ran, so `chown` received empty values. The command now uses `$$TARGET_UID` and `$$TARGET_GID`, which Compose converts to literal shell variables for the container. No application or Chromium code was involved in this second failure.

## Third compose failure diagnosis

The next user log showed that `init-volumes` was fixed successfully, but both runtime services were still restarting. The browser log explicitly reported `/usr/bin/python: No module named uvicorn`. The sandbox Dockerfile had a separate hidden issue: it executed `python /app/server.py`, while that file only declares `app` and has no `uvicorn.run()` block, so the process exited immediately. Browser and sandbox now each install pinned FastAPI/Uvicorn/Pydantic dependencies; browser keeps its Playwright base, and sandbox starts with `python -m uvicorn server:app --host 0.0.0.0 --port 5001`. A local sandbox entrypoint simulation returned health `ok` and `sandbox-ok` from `/exec`.

## Fourth compose failure diagnosis

The fourth user log showed the init container now succeeds and Uvicorn is installed, but two final runtime issues remained. Browser imported Uvicorn successfully but failed with `ModuleNotFoundError: No module named 'playwright'`; the Playwright base image did not expose the package to the interpreter used by the service, so `playwright==1.51.0` is now explicitly pinned in browser requirements. Sandbox reported `Could not import module "server"` because its working directory was `/workspace` while `server.py` lived in `/app`; its command now passes `--app-dir /app`. A local simulation from a non-app working directory returned sandbox health/exec success and browser health/open success.
