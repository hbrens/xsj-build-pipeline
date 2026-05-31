#!/usr/bin/env bash
set -uo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/build_harmony_zip.sh <zip_path> <job_dir> [command_line_tools_dir]

Environment:
  BUILD_TIMEOUT_SECONDS  Build timeout in seconds. Default: 1200.
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ZIP_PATH="$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$1")"
JOB_DIR="$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$2")"
TOOLS_DIR="$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "${3:-$PROJECT_DIR/command-line-tools}")"
TIMEOUT_SECONDS="${BUILD_TIMEOUT_SECONDS:-1200}"

LOG_DIR="$JOB_DIR/logs"
SOURCE_DIR="$JOB_DIR/source"
ARTIFACT_DIR="$JOB_DIR/artifacts"
STATUS_FILE="$JOB_DIR/status.json"
LOG_FILE="$LOG_DIR/build.log"

mkdir -p "$LOG_DIR" "$SOURCE_DIR" "$ARTIFACT_DIR"

write_status() {
  local status="$1"
  local message="$2"
  local exit_code="${3:-}"
  python3 - "$STATUS_FILE" "$JOB_DIR" "$status" "$message" "$exit_code" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

status_file, job_dir, status, message, exit_code = sys.argv[1:6]
artifact_dir = os.path.join(job_dir, "artifacts")
artifacts = []
if os.path.isdir(artifact_dir):
    for name in sorted(os.listdir(artifact_dir)):
        path = os.path.join(artifact_dir, name)
        if os.path.isfile(path):
            artifacts.append({"name": name, "size": os.path.getsize(path)})

payload = {
    "job_id": os.path.basename(os.path.abspath(job_dir)),
    "status": status,
    "message": message,
    "exit_code": int(exit_code) if exit_code else None,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "log_path": "logs/build.log",
    "artifacts": artifacts,
}

tmp = status_file + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(tmp, status_file)
PY
}

fail() {
  local rc="$1"
  local message="$2"
  echo "ERROR: $message"
  write_status "failed" "$message" "$rc"
  exit "$rc"
}

exec > >(tee -a "$LOG_FILE") 2>&1

echo "== HarmonyOS zip build started =="
echo "zip: $ZIP_PATH"
echo "job_dir: $JOB_DIR"
echo "tools_dir: $TOOLS_DIR"
echo "timeout_seconds: $TIMEOUT_SECONDS"
date '+started_at: %Y-%m-%d %H:%M:%S %z'

write_status "running" "Build started" ""

[ -f "$ZIP_PATH" ] || fail 2 "Zip file not found: $ZIP_PATH"
[ -d "$TOOLS_DIR" ] || fail 2 "Command line tools directory not found: $TOOLS_DIR"
[ -x "$TOOLS_DIR/bin/ohpm" ] || fail 2 "ohpm is not executable: $TOOLS_DIR/bin/ohpm"
[ -x "$TOOLS_DIR/bin/hvigorw" ] || fail 2 "hvigorw is not executable: $TOOLS_DIR/bin/hvigorw"

rm -rf "$SOURCE_DIR/unpacked"
mkdir -p "$SOURCE_DIR/unpacked"

echo
echo "== Extracting zip safely =="
python3 - "$ZIP_PATH" "$SOURCE_DIR/unpacked" <<'PY'
import os
import stat
import sys
import zipfile

zip_path, dest = sys.argv[1:3]
dest_abs = os.path.abspath(dest)

if not zipfile.is_zipfile(zip_path):
    raise SystemExit(f"Not a valid zip file: {zip_path}")

with zipfile.ZipFile(zip_path) as zf:
    for info in zf.infolist():
        normalized = info.filename.replace("\\", "/")
        if not normalized or normalized.startswith("/"):
            raise SystemExit(f"Unsafe zip path: {info.filename}")
        target = os.path.abspath(os.path.join(dest_abs, normalized))
        if target != dest_abs and not target.startswith(dest_abs + os.sep):
            raise SystemExit(f"Unsafe zip path: {info.filename}")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise SystemExit(f"Zip symlinks are not allowed: {info.filename}")
    zf.extractall(dest_abs)
PY
extract_rc=$?
[ "$extract_rc" -eq 0 ] || fail "$extract_rc" "Zip extraction failed"

PROJECT_ROOT="$(
  python3 - "$SOURCE_DIR/unpacked" <<'PY'
import os
import sys

base = os.path.abspath(sys.argv[1])
matches = []
required = {"hvigorfile.ts", "build-profile.json5", "oh-package.json5"}

for root, dirs, files in os.walk(base):
    dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "build", ".hvigor"}]
    if required.issubset(set(files)):
        depth = os.path.relpath(root, base).count(os.sep)
        matches.append((depth, root))

if not matches:
    raise SystemExit("Could not find HarmonyOS project root")

matches.sort(key=lambda item: (item[0], item[1]))
print(matches[0][1])
PY
)"
find_rc=$?
[ "$find_rc" -eq 0 ] || fail "$find_rc" "Could not locate HarmonyOS project root"

echo "project_root: $PROJECT_ROOT"

export PATH="$TOOLS_DIR/bin:$PATH"
export DEVECO_NODE_HOME="$TOOLS_DIR/tool/node"
export DEVECO_SDK_HOME="$TOOLS_DIR/sdk"
export NODE_HOME="$DEVECO_NODE_HOME"
export PATH="$NODE_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$TOOLS_DIR/sdk/default/hms/toolchains/lib:$TOOLS_DIR/sdk/default/openharmony/toolchains/lib:$TOOLS_DIR/sdk/default/openharmony/previewer/common/bin:${LD_LIBRARY_PATH:-}"

echo
echo "== Tool versions =="
ohpm --version || fail 3 "ohpm version check failed"
hvigorw --version || fail 3 "hvigor version check failed"

cd "$PROJECT_ROOT" || fail 3 "Cannot enter project root: $PROJECT_ROOT"

echo
echo "== Installing OHPM dependencies =="
ohpm install --all
install_rc=$?
[ "$install_rc" -eq 0 ] || fail "$install_rc" "ohpm install failed"

echo
echo "== Building app =="
hvigorw --stop-daemon-all >/dev/null 2>&1 || true
if command -v timeout >/dev/null 2>&1; then
  timeout "${TIMEOUT_SECONDS}s" hvigorw assembleApp --info --no-daemon
  build_rc=$?
else
  hvigorw assembleApp --info --no-daemon
  build_rc=$?
fi

if [ "$build_rc" -eq 124 ]; then
  write_status "timeout" "Build timed out after ${TIMEOUT_SECONDS}s" "$build_rc"
  exit "$build_rc"
fi
[ "$build_rc" -eq 0 ] || fail "$build_rc" "hvigor build failed"

echo
echo "== Collecting artifacts =="
find "$PROJECT_ROOT" -type f \( -name '*.app' -o -name '*.hap' -o -name '*.har' -o -name '*.hsp' \) -print0 |
  while IFS= read -r -d '' artifact; do
    rel="${artifact#$PROJECT_ROOT/}"
    safe_name="$(printf '%s' "$rel" | sed 's#[/[:space:]]#_#g')"
    cp -f "$artifact" "$ARTIFACT_DIR/$safe_name"
    size="$(wc -c < "$ARTIFACT_DIR/$safe_name" | tr -d ' ')"
    echo "artifact: $safe_name ($size bytes)"
  done

artifact_count="$(find "$ARTIFACT_DIR" -maxdepth 1 -type f | wc -l | tr -d ' ')"
[ "$artifact_count" -gt 0 ] || fail 4 "Build succeeded but no artifacts were found"

write_status "success" "Build succeeded" 0

echo
echo "== Build completed successfully =="
date '+finished_at: %Y-%m-%d %H:%M:%S %z'
