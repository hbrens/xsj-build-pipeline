# HarmonyOS Jenkins Build Pipeline

This branch provides a Jenkins-based HarmonyOS zip build environment.

It uses the official Jenkins Docker image, preloads one Jenkins Freestyle job, and runs the existing shell build script from Jenkins' built-in shell build step. It does not install extra Jenkins plugins.

## What It Supports

- Build a HarmonyOS project zip from command line.
- Run the same zip build through Jenkins.
- Upload a project zip over HTTP and trigger the Jenkins build without Jenkins plugins.
- Save build logs, status, and generated `.app`, `.hap`, `.har`, or `.hsp` artifacts.
- Persist Jenkins data under `jenkins-data/`.
- Persist build outputs under `jobs/`.

## Required Local Tools

Before running real builds, make sure these files exist and are executable:

```text
command-line-tools/bin/ohpm
command-line-tools/bin/hvigorw
```

The `command-line-tools/` directory is mounted into Jenkins as:

```text
/opt/harmony/command-line-tools
```

## Jenkins Docker Compose

Start Jenkins:

```bash
docker compose up --build
```

Jenkins URL:

```text
http://127.0.0.1:8080
```

Upload API URL:

```text
http://127.0.0.1:8090
```

Default local login:

```text
username: admin
password: admin
```

Override these in `docker-compose.yml` or with environment variables before first startup:

```text
JENKINS_ADMIN_ID
JENKINS_ADMIN_PASSWORD
```

The preloaded job is:

```text
harmony-zip-build
```

If `jenkins-data/` already exists from an earlier run, Jenkins will keep the existing home directory and may not copy the preloaded job again. Remove `jenkins-data/` only when you intentionally want a fresh Jenkins home.

## Run A Jenkins Build

Put a project zip in the ignored local upload directory:

```bash
mkdir -p uploads
cp MultiFinancialManagement-master.zip uploads/
```

Open Jenkins, select `harmony-zip-build`, then choose **Build with Parameters**.

Default parameter:

```text
ZIP_PATH=/data/uploads/MultiFinancialManagement-master.zip
```

Optional parameters:

```text
JOB_ID                  output directory name under /data/jobs
BUILD_TIMEOUT_SECONDS   default: 1200
```

Jenkins archives these files for each build when available:

```text
artifacts/**/*
logs/build.log
status.json
```

Persistent output is also written under:

```text
jobs/<job_id>/
  logs/build.log
  artifacts/
  status.json
```

## Upload And Trigger Over HTTP

The `upload-api` service accepts a raw zip request body, writes it to `uploads/`
with a unique filename, then triggers Jenkins through `buildWithParameters`.
It does not require Jenkins plugins.

```bash
curl -X POST "http://127.0.0.1:8090/upload?filename=MultiFinancialManagement-master.zip" \
  -H "Content-Type: application/zip" \
  --data-binary @MultiFinancialManagement-master.zip
```

Optional query parameters:

```text
job_id    output directory name under /data/jobs; defaults to a unique id
timeout   build timeout in seconds; defaults to BUILD_TIMEOUT_SECONDS
```

Example with a fixed job id:

```bash
curl -X POST "http://127.0.0.1:8090/upload?filename=app.zip&job_id=api-test" \
  -H "Content-Type: application/zip" \
  --data-binary @app.zip
```

The response includes the unique uploaded filename, the Jenkins-visible `zip_path`,
the `job_id`, and the Jenkins queue URL.

To require a token on uploads, set `UPLOAD_TOKEN` for the `upload-api` service and
send it as either:

```bash
Authorization: Bearer <token>
```

or:

```bash
X-Upload-Token: <token>
```

## Local Script Usage

You can still run the build script directly:

```bash
scripts/build_harmony_zip.sh MultiFinancialManagement-master.zip jobs/local-script-test
```

Outputs:

```text
jobs/local-script-test/
  logs/build.log
  artifacts/
  status.json
```

The script runs:

```bash
ohpm install --all
hvigorw assembleApp --info --no-daemon
```

## Compose Mounts

```text
./jenkins-data       -> /var/jenkins_home
./command-line-tools -> /opt/harmony/command-line-tools
./jobs               -> /data/jobs
./uploads            -> /data/uploads
```

## Environment Variables

```text
JENKINS_ADMIN_ID          default: admin
JENKINS_ADMIN_PASSWORD    default: admin
JOBS_DIR                  default: /data/jobs
TOOLS_DIR                 default: /opt/harmony/command-line-tools
BUILD_TIMEOUT_SECONDS     default: 1200
UPLOADS_DIR               upload-api path for saved zips; default: /data/uploads
JENKINS_UPLOADS_DIR       Jenkins-visible upload path; default: /data/uploads
JENKINS_URL               upload-api Jenkins endpoint; default: http://jenkins:8080
JENKINS_JOB               upload-api Jenkins job name; default: harmony-zip-build
JENKINS_USER              upload-api Jenkins username; default: admin
JENKINS_PASSWORD          upload-api Jenkins password; default: admin
MAX_UPLOAD_BYTES          upload-api max request size; default: 1073741824
UPLOAD_TOKEN              optional token required by upload-api
```

## Current Limitation

The verified sample project does not configure HarmonyOS signing.

The build succeeds, but logs contain warnings similar to:

```text
Will skip sign 'app'. No signingConfigs profile is configured in current project.
```

So the generated artifacts are unsigned. Signing should be added as a later phase.
