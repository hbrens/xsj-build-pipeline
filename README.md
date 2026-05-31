# HarmonyOS Jenkins Build Pipeline

This branch provides a Jenkins-based HarmonyOS zip build environment.

It uses the official Jenkins Docker image, preloads one Jenkins Freestyle job, and runs the existing shell build script from Jenkins' built-in shell build step. It does not install extra Jenkins plugins.

## What It Supports

- Build a HarmonyOS project zip from command line.
- Run the same zip build through Jenkins.
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
```

## Current Limitation

The verified sample project does not configure HarmonyOS signing.

The build succeeds, but logs contain warnings similar to:

```text
Will skip sign 'app'. No signingConfigs profile is configured in current project.
```

So the generated artifacts are unsigned. Signing should be added as a later phase.
