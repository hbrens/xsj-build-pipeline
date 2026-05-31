# HarmonyOS Build Pipeline Plan

## 1. Current Status

Current directory contains:

- `command-line-tools/`: HarmonyOS command line build toolchain.
- `MultiFinancialManagement-master.zip`: sample HarmonyOS project package.
- `jenkins-data/`: existing Jenkins data directory, currently not required for command-line verification.

Command-line build has been verified successfully in:

```text
.build-verify/MultiFinancialManagement-master
```

Verified tool versions:

```text
hvigor: 6.24.2
ohpm: 6.1.2.268
node: v18.20.1
HarmonyOS SDK: 6.1.1 / API 24
```

Verified commands:

```bash
export PATH="/home/hbrens/Desktop/Project/coding/xsj-build-pipeline/command-line-tools/bin:$PATH"
ohpm install --all
hvigorw tasks
hvigorw assembleApp --info
```

Build result:

- `ohpm install --all`: success.
- `hvigorw assembleApp --info`: success.
- Build time: about 18 seconds.
- Generated unsigned `.app` and `.hap` artifacts.

Important limitation:

- The project does not configure `signingConfigs`.
- Build skips signing and generates unsigned artifacts.
- If users need installable or releasable packages, signing must be added later.

## 2. Goal

Build a service that allows users to upload a HarmonyOS project zip package through a network request, then the service compiles it and returns:

- Build status.
- Build logs.
- Build errors if failed.
- Generated artifacts if successful.

The first implementation should prioritize a stable command-line build flow before introducing Jenkins or a larger CI system.

## 3. Recommended Direction

Use a lightweight build API service first.

Reason:

- The current requirement is upload zip, build, return result.
- A custom API service maps directly to this workflow.
- Jenkins can be added later if pipeline UI, permission management, build history, manual approval, or multi-branch jobs become necessary.

Recommended MVP stack:

- `docker-compose`
- One build API service container
- HarmonyOS command-line tools inside the container or mounted into it
- Persistent job workspace volume
- Optional queue worker if builds may run concurrently

## 4. Milestone Plan

### Phase 1: Build Script

Create a standalone build script, for example:

```text
scripts/build_harmony_zip.sh
```

Responsibilities:

- Accept a zip path as input.
- Create an isolated job workspace.
- Safely unzip the package.
- Locate the HarmonyOS project root.
- Export toolchain environment variables.
- Run:

```bash
ohpm install --all
hvigorw assembleApp --info
```

- Save full build log.
- Collect `.app`, `.hap`, `.har`, `.hsp` artifacts.
- Return a reliable exit code.

Expected output structure:

```text
jobs/{job_id}/
  source/
  logs/
    build.log
  artifacts/
    *.app
    *.hap
  status.json
```

Acceptance criteria:

- The current `MultiFinancialManagement-master.zip` can be built through the script.
- Build logs are saved.
- Artifacts are copied to the job artifacts directory.
- Failed builds produce a clear failure status and error log.

### Phase 2: Docker Build Environment

Create Docker and Compose files:

```text
Dockerfile
docker-compose.yml
```

Container requirements:

- Include or mount `command-line-tools`.
- Set `PATH`, `DEVECO_NODE_HOME`, and `DEVECO_SDK_HOME`.
- Provide `unzip`, `bash`, and common Linux build utilities.
- Mount persistent directories for jobs and artifacts.

Suggested environment:

```bash
PATH=/opt/harmony/command-line-tools/bin:$PATH
DEVECO_NODE_HOME=/opt/harmony/command-line-tools/tool/node
DEVECO_SDK_HOME=/opt/harmony/command-line-tools/sdk
```

Acceptance criteria:

- The same zip builds successfully inside Docker.
- The output artifact path is accessible from the host.
- Container rebuild does not destroy previous job results unless explicitly cleaned.

### Phase 3: HTTP Build API

Create a simple API service.

Suggested endpoints:

```text
POST /builds
GET  /builds/{job_id}
GET  /builds/{job_id}/logs
GET  /builds/{job_id}/artifacts
```

Initial behavior:

- `POST /builds` accepts one zip file.
- Server stores the zip under a new job id.
- Server starts build synchronously or asynchronously.
- Server returns job id and initial status.

Recommended status values:

```text
queued
running
success
failed
timeout
cancelled
```

Acceptance criteria:

- User can upload the verified sample zip through HTTP.
- User can query build status.
- User can read build logs.
- User can download successful artifacts.

### Phase 4: Queue, Isolation, and Cleanup

Add production controls:

- Limit max upload size.
- Validate uploaded file is a zip.
- Prevent zip path traversal.
- Run each build in a separate workspace.
- Limit build timeout.
- Limit concurrent builds.
- Clean old jobs by age or disk usage.

Suggested defaults:

```text
max upload size: 500 MB
build timeout: 20 minutes
max concurrent builds: 1 or 2 initially
job retention: 7 days
```

Acceptance criteria:

- Bad zip packages fail safely.
- One user's build cannot overwrite another user's workspace.
- Long-running builds are stopped and marked as timeout.

### Phase 5: Signing Strategy

Decide how signing should work.

Options:

1. Return unsigned artifacts only.
2. Server owns one signing profile and signs all builds.
3. User uploads signing materials per build.

Recommended initial choice:

- Return unsigned artifacts first.
- Add signing only after the upload/build/download workflow is stable.

Required later if signing is enabled:

- Secure storage for signing files.
- No signing secrets in logs.
- Per-job cleanup of temporary signing material.
- Clear distinction between debug, test, and release signing.

### Phase 6: Jenkins Option

Only add Jenkins if needed.

Jenkins is useful when the system needs:

- Visual pipeline management.
- Build history UI.
- User permissions.
- Manual approval steps.
- Scheduled builds.
- Integration with Git repositories.

If Jenkins is introduced later:

- Keep the same build script as the single source of truth.
- Jenkins should call the script instead of duplicating build commands.
- API service can trigger Jenkins jobs through Jenkins REST API.

## 5. Proposed Repository Layout

```text
xsj-build-pipeline/
  command-line-tools/
  scripts/
    build_harmony_zip.sh
  service/
    src/
    Dockerfile
  jobs/
    .gitkeep
  docker-compose.yml
  BUILD_PIPELINE_PLAN.md
```

`jobs/` should be runtime data and should not be committed except for `.gitkeep`.

## 6. Risks

- Some HarmonyOS projects may depend on remote OHPM packages.
- Some projects may require a specific SDK/API version.
- Release builds may fail without signing configuration.
- Large projects may require more memory and longer timeout.
- Build logs may contain sensitive project paths or signing information.

## 7. Next Action

Recommended next step:

Create `scripts/build_harmony_zip.sh` and verify that it can build `MultiFinancialManagement-master.zip` end to end using only one command.

After that, wrap the same script in Docker and then expose it through HTTP.
