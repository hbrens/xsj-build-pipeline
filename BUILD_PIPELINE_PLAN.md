# HarmonyOS Jenkins Build Pipeline Plan

## Current Direction

This branch is the Jenkins variant of the HarmonyOS zip build pipeline.

The service-style Python HTTP API has been removed from this branch. Jenkins is the build entry point, using one preloaded Freestyle job and the built-in shell build step.

## Runtime Layout

```text
jenkins/Dockerfile                         Jenkins-based image
jenkins/ref/jobs/harmony-zip-build/config.xml
jenkins/ref/init.groovy.d/basic-security.groovy
scripts/build_harmony_zip.sh               HarmonyOS build script
docker-compose.yml                         Local Jenkins runtime
```

Persistent runtime data:

```text
jenkins-data/   Jenkins home
uploads/        input zip files mounted read-only into Jenkins
jobs/           build logs, status, and artifacts
```

## Build Flow

1. User copies a HarmonyOS project zip into `uploads/`.
2. User starts `harmony-zip-build` in Jenkins.
3. Jenkins runs `scripts/build_harmony_zip.sh` through its built-in shell builder.
4. The script safely extracts the zip, runs `ohpm install --all`, then runs `hvigorw assembleApp --info --no-daemon`.
5. Artifacts and logs are copied back into the Jenkins workspace and archived by Jenkins.
6. Full persistent output remains under `jobs/<job_id>/`.

## Acceptance Criteria

- `docker compose up --build` starts Jenkins on `http://127.0.0.1:8080`.
- Jenkins has a `harmony-zip-build` job on first startup with an empty `jenkins-data/`.
- The job builds a zip path mounted under `/data/uploads`.
- Build logs are visible in Jenkins and persisted under `jobs/<job_id>/logs/build.log`.
- Generated `.app`, `.hap`, `.har`, or `.hsp` files are archived by Jenkins and persisted under `jobs/<job_id>/artifacts/`.

## Intentional Constraints

- Use the official Jenkins image as the base image.
- Do not install extra Jenkins plugins.
- Do not run the old Python HTTP API in this branch.
- Keep HarmonyOS command-line tools outside git and mount them at runtime.
