# Repository Guidelines

## Project Structure & Module Organization

This branch provides a Jenkins-based HarmonyOS zip build pipeline. `jenkins/Dockerfile` builds the local Jenkins image from the official Jenkins base image. `jenkins/ref/jobs/harmony-zip-build/config.xml` preloads the Jenkins Freestyle job, and `jenkins/ref/init.groovy.d/basic-security.groovy` configures the local admin user. `scripts/build_harmony_zip.sh` unpacks projects, runs OHPM/Hvigor, and collects `.app`, `.hap`, `.har`, and `.hsp` outputs. `command-line-tools/` is a local mount point for HarmonyOS CLI tools and should only keep `.gitkeep` in git. Runtime data belongs in ignored `jenkins-data/`, `uploads/`, and `jobs/`.

## Build, Test, and Development Commands

- `docker compose up --build`: build and run Jenkins on `http://127.0.0.1:8080`.
- `mkdir -p uploads && cp MultiFinancialManagement-master.zip uploads/`: stage a zip for Jenkins.
- Jenkins job `harmony-zip-build`: run the mounted zip build from the Jenkins UI.
- `scripts/build_harmony_zip.sh MultiFinancialManagement-master.zip jobs/local-script-test`: run a direct build and write logs/status/artifacts under the job directory.
- `bash -n scripts/build_harmony_zip.sh`: quick syntax check for the build script.
- `docker compose config`: validate the Compose file.

Before real builds, ensure `command-line-tools/bin/ohpm` and `command-line-tools/bin/hvigorw` exist and are executable.

## Coding Style & Naming Conventions

Use Bash with `set -uo pipefail`, quoted variables, upper-case environment variables, and lower-case local helper names. Prefer stable output names such as `logs/build.log`, `status.json`, and `artifacts/`. Keep Jenkins job configuration minimal and based on built-in Jenkins Freestyle behavior unless a plugin is explicitly required.

## Testing Guidelines

There is no formal test suite yet. For script changes, run `bash -n scripts/build_harmony_zip.sh` and at least one build against a representative HarmonyOS zip when tools are available. For Jenkins changes, run `docker compose config`, parse the job XML, and start Jenkins with `docker compose up --build` when Docker is available. Do not commit generated `jobs/`, `jenkins-data/`, `uploads/`, `.hvigor/`, `.build-verify/`, archives, or tool binaries.

## Commit & Pull Request Guidelines

The current history uses a short imperative summary, for example `Initial HarmonyOS build service MVP`. Continue with imperative commit subjects such as `Add Jenkins docker build job` or `Document Jenkins workflow`. Pull requests should describe the behavior change, list validation commands, note HarmonyOS tool/version assumptions, and include sample Jenkins console output or log excerpts when build behavior changes.

## Security & Configuration Tips

Keep uploaded archives, build outputs, signing files, Jenkins home data, and HarmonyOS command-line tools out of git. Configure runtime behavior with environment variables documented in `README.md`, especially `JENKINS_ADMIN_ID`, `JENKINS_ADMIN_PASSWORD`, `JOBS_DIR`, `TOOLS_DIR`, and `BUILD_TIMEOUT_SECONDS`. Preserve zip path validation and artifact path checks when editing the build script.
