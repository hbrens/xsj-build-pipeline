# HarmonyOS Build Pipeline MVP

This repository contains a first working version of a HarmonyOS zip build service.

The current implementation supports:

- Build a HarmonyOS project zip from command line.
- Upload a zip through HTTP.
- Query build status.
- Read build logs.
- Download generated `.app`, `.hap`, `.har`, or `.hsp` artifacts.

## Local Script Usage

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

The script uses:

```text
command-line-tools/bin/ohpm
command-line-tools/bin/hvigorw
```

It runs:

```bash
ohpm install --all
hvigorw assembleApp --info --no-daemon
```

## Local HTTP Service

Start the service:

```bash
PORT=8090 python3 service/server.py
```

Health check:

```bash
curl http://127.0.0.1:8090/health
```

Upload zip:

```bash
curl -X POST -F file=@MultiFinancialManagement-master.zip http://127.0.0.1:8090/builds
```

Query status:

```bash
curl http://127.0.0.1:8090/builds/<job_id>
```

Read logs:

```bash
curl http://127.0.0.1:8090/builds/<job_id>/logs
```

List artifacts:

```bash
curl http://127.0.0.1:8090/builds/<job_id>/artifacts
```

Download artifact:

```bash
curl -o output.app http://127.0.0.1:8090/builds/<job_id>/artifacts/<artifact_name>
```

## Docker Compose

Start:

```bash
docker compose up --build
```

Service URL:

```text
http://127.0.0.1:8080
```

Compose mounts:

```text
./command-line-tools -> /opt/harmony/command-line-tools
./jobs               -> /data/jobs
```

## Environment Variables

```text
PORT                    default: 8080
JOBS_DIR                default: ./jobs
TOOLS_DIR               default: ./command-line-tools
MAX_UPLOAD_MB           default: 500
MAX_CONCURRENT_BUILDS   default: 1
BUILD_TIMEOUT_SECONDS   default: 1200
```

## Current Limitation

The verified sample project does not configure HarmonyOS signing.

The build succeeds, but logs contain warnings similar to:

```text
Will skip sign 'app'. No signingConfigs profile is configured in current project.
```

So the generated artifacts are unsigned. Signing should be added as a later phase.
