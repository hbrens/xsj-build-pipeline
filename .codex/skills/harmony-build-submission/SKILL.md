---
name: harmony-build-submission
description: Package the current working repository and submit it to the local Harmony Jenkins build service. Use when an AI agent or user wants to build the active repo immediately, even if there are uncommitted or untracked changes, without changing the repo's git state.
---

# Harmony Build Submission

Use this skill when the request is:

- build the current working repository now
- package the current code and send it to the build service
- submit uncommitted work to the Jenkins/Harmony build pipeline

This skill uses the existing upload API from this repository:

- `POST /upload`
- default local base URL `http://127.0.0.1:8090`
- request body is the raw zip payload
- query params support `filename`, `job_id`, and `timeout`

## Required tools

Ensure the executing environment has:

- `curl`
- `zip`
- `git` preferred; `find` used as fallback if not inside a git repo

## Workflow

1. Resolve the target repository path.
   - Default to the current working directory.
   - If the user gives another repo path, use that path instead.
2. Inspect the repository state.
   - Read `git status --porcelain` and `git diff --stat` to summarize dirty files.
   - Continue even if the repo has uncommitted changes.
3. Package the working tree.
   - Use `scripts/package_and_submit_build.sh` from this repo.
   - Default mode includes git-tracked files plus untracked files that are not ignored by `.gitignore`.
   - The script also excludes common large generated archives by default, such as `*.tar`, `*.tar.gz`, and `*.zip`, even if they are not yet ignored.
4. Submit the build.
   - The script posts the packaged zip to `/upload` and prints the service response.
   - If the build service is unavailable, tell the user that `docker compose up --build` needs to run first in this repository.
5. Return a short result summary.
   - Include `uploaded_filename`, `zip_path`, `job_id`, `jenkins_queue_url` if available, and any error returned by the service.

## Script

Primary script:

- `scripts/package_and_submit_build.sh`

Common usage:

```bash
./scripts/package_and_submit_build.sh
./scripts/package_and_submit_build.sh --path /absolute/path/to/target-repo
./scripts/package_and_submit_build.sh --base-url http://127.0.0.1:8090 --job-id manual-test
```

If the user only wants local packaging without submitting, run:

```bash
./scripts/package_and_submit_build.sh --submit no
```

## Important notes

- This workflow intentionally does not require committed code.
- It is intended for the active working repository with uncommitted changes.
- Use it for the active working repository, not this pipeline repo itself, unless the user explicitly asks to build this repo.
- Do not change git history, stash state, or commit automatically unless the user explicitly asks for that.
- Keep output concise and factual: summarize dirty files, the packaged zip path, and the submission response.
