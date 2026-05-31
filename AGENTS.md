# Repository Guidelines

## Project Structure & Module Organization

This repository provides a HarmonyOS zip build service. `service/server.py` is the Python HTTP API for uploads, status checks, logs, and artifact downloads. `scripts/build_harmony_zip.sh` unpacks projects, runs OHPM/Hvigor, and collects `.app`, `.hap`, `.har`, and `.hsp` outputs. `service/Dockerfile` and `docker-compose.yml` package local container use. `command-line-tools/` is a local mount point for HarmonyOS CLI tools and should only keep `.gitkeep` in git. Runtime build data belongs in ignored `jobs/`.

## Build, Test, and Development Commands

- `PORT=8090 python3 service/server.py`: run the API locally.
- `curl http://127.0.0.1:8090/health`: verify the service is responding.
- `scripts/build_harmony_zip.sh MultiFinancialManagement-master.zip jobs/local-script-test`: run a direct build and write logs/status/artifacts under the job directory.
- `docker compose up --build`: build and run the containerized service on `http://127.0.0.1:8080`.
- `python3 -m py_compile service/server.py`: quick syntax check for the Python service.
- `bash -n scripts/build_harmony_zip.sh`: quick syntax check for the build script.

Before real builds, ensure `command-line-tools/bin/ohpm` and `command-line-tools/bin/hvigorw` exist and are executable.

## Coding Style & Naming Conventions

Use Python 3 style with 4-space indentation, explicit helper functions, `Path` for filesystem paths, and UTF-8 JSON responses. Keep API route behavior in `Handler` methods and shared filesystem/status helpers at module scope. Use Bash with `set -uo pipefail`, quoted variables, upper-case environment variables, and lower-case local helper names. Prefer UUID job IDs and stable output names such as `logs/build.log`, `status.json`, and `artifacts/`.

## Testing Guidelines

There is no formal test suite yet. For Python changes, run `python3 -m py_compile service/server.py` and exercise `/health`, `/builds`, `/builds/<job_id>`, logs, and artifact endpoints with `curl`. For script changes, run `bash -n scripts/build_harmony_zip.sh` and at least one build against a representative HarmonyOS zip when tools are available. Do not commit generated `jobs/`, `.hvigor/`, `.build-verify/`, archives, or tool binaries.

## Commit & Pull Request Guidelines

The current history uses a short imperative summary, for example `Initial HarmonyOS build service MVP`. Continue with imperative commit subjects such as `Add build timeout status handling` or `Document Docker workflow`. Pull requests should describe the behavior change, list validation commands, note HarmonyOS tool/version assumptions, and include sample API output or log excerpts when endpoint behavior changes.

## Security & Configuration Tips

Keep uploaded archives, build outputs, signing files, and HarmonyOS command-line tools out of git. Configure runtime behavior with environment variables documented in `README.md`, especially `JOBS_DIR`, `TOOLS_DIR`, `MAX_UPLOAD_MB`, `MAX_CONCURRENT_BUILDS`, and `BUILD_TIMEOUT_SECONDS`. Preserve zip path validation and artifact path checks when editing upload or download logic.
