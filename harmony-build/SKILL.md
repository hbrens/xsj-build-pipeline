---
name: harmony-build
description: Package the current HarmonyOS working repository (including uncommitted and untracked code) into a zip, upload it to the xsj-build-pipeline build service, poll until the build finishes, and download the resulting artifacts. Use when the user asks to build or package a HarmonyOS project through the remote build service, or wants to send the current workspace to a CI build endpoint.
---

# Harmony Build

Package any local HarmonyOS project directory into a zip (including uncommitted changes, untracked files, and staged work) and submit it to the xsj-build-pipeline build service for compilation.

## Prerequisites

- The build service must be running (default `http://127.0.0.1:8080`).
- Python 3.10+ available on PATH.

## Workflow

### 1. Run the build script

```bash
python3 <skill-dir>/scripts/harmony_build.py <project-dir> [--server URL] [--out DIR]
```

- `<project-dir>`: the working repository to package (the current cwd is the typical choice).
- `--server`: override the build service URL if it is not on the default `http://127.0.0.1:8080`.
- `--out`: directory to save downloaded artifacts (default: `./build-artifacts`).

The script will:
1. Walk the project directory and create a zip, automatically excluding `.git`, `node_modules`, `.hvigor`, `build`, `__pycache__`, `.idea`, `.vscode`, `.build-verify`, `.preview`, and existing build artifacts (`.zip`, `.har`, `.hap`, `.hsp`, `.app`).
2. Upload the zip via `POST /builds` as `multipart/form-data`.
3. Poll `GET /builds/<job_id>` every 5 seconds (timeout 30 min).
4. On success: download all artifacts to the output directory.
5. On failure: print the build log tail and exit non-zero.

### 2. Interpret results

- **success**: Artifacts are saved to the output directory. List them and report to the user.
- **failed / error**: The script prints the last 4000 characters of the build log. Summarize the key error lines for the user.

### 3. Manual API usage (when the script is not suitable)

For finer control, use `curl` directly:

```bash
# Upload
curl -s -X POST http://127.0.0.1:8080/builds \
  -F "file=@project.zip" | python3 -m json.tool

# Check status
curl -s http://127.0.0.1:8080/builds/<job_id>

# Get logs
curl -s http://127.0.0.1:8080/builds/<job_id>/logs

# List artifacts
curl -s http://127.0.0.1:8080/builds/<job_id>/artifacts

# Download an artifact
curl -s -O http://127.0.0.1:8080/builds/<job_id>/artifacts/<filename>
```

## Notes

- The zip includes all working-tree files regardless of git commit status, so uncommitted edits are always included.
- The build service uses `MAX_UPLOAD_MB` (default 500) to limit upload size. If the project is very large, clean unnecessary files before packaging.
- Artifacts typically include `.app`, `.hap`, `.har`, `.hsp` files depending on the project type.
