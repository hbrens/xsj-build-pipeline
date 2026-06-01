#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_BASE_URL="http://127.0.0.1:8090"
DEFAULT_TIMEOUT=1200
DEFAULT_MODE="tracked"
DEFAULT_SUBMIT="yes"

usage() {
  cat <<'EOF'
Usage:
  scripts/package_and_submit_build.sh [options]

Options:
  --path <dir>          Target repository to package. Default: current directory.
  --out <file.zip>      Local zip path to write. Default: <repo-basename>-working-snapshot.zip
  --base-url <url>      Build service base URL. Default: http://127.0.0.1:8090
  --job-id <id>         Optional Jenkins job id.
  --filename <name>     Uploaded filename hint. Default: derived from --out.
  --timeout <seconds>   Build timeout forwarded to the service. Default: 1200.
    --mode <tracked|all>  tracked = git-tracked + untracked files not ignored by .gitignore, excludes common large archives by default.
                        all     = zip almost everything in the directory.
  --submit <yes|no>     Submit the zip to the build service. Default: yes.
  -h, --help            Show help.
EOF
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

BASE_URL="$DEFAULT_BASE_URL"
TARGET_PATH="."
OUT_PATH=""
JOB_ID=""
FILENAME=""
TIMEOUT_SECONDS="$DEFAULT_TIMEOUT"
MODE="$DEFAULT_MODE"
SUBMIT="$DEFAULT_SUBMIT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --path)
      [[ $# -ge 2 ]] || die "--path requires a value"
      TARGET_PATH="$2"
      shift 2
      ;;
    --out)
      [[ $# -ge 2 ]] || die "--out requires a value"
      OUT_PATH="$2"
      shift 2
      ;;
    --base-url)
      [[ $# -ge 2 ]] || die "--base-url requires a value"
      BASE_URL="$2"
      shift 2
      ;;
    --job-id)
      [[ $# -ge 2 ]] || die "--job-id requires a value"
      JOB_ID="$2"
      shift 2
      ;;
    --filename)
      [[ $# -ge 2 ]] || die "--filename requires a value"
      FILENAME="$2"
      shift 2
      ;;
    --timeout)
      [[ $# -ge 2 ]] || die "--timeout requires a value"
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --mode)
      [[ $# -ge 2 ]] || die "--mode requires a value"
      MODE="$2"
      shift 2
      ;;
    --submit)
      [[ $# -ge 2 ]] || die "--submit requires a value"
      SUBMIT="$2"
      shift 2
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

require_cmd curl
require_cmd zip
require_cmd python3

[[ "$MODE" == "tracked" || "$MODE" == "all" ]] || die "--mode must be tracked or all"
[[ "$SUBMIT" == "yes" || "$SUBMIT" == "no" ]] || die "--submit must be yes or no"

TARGET_PATH="$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$TARGET_PATH")"
[[ -d "$TARGET_PATH" ]] || die "Target path is not a directory: $TARGET_PATH"

REPO_BASENAME="$(basename "$TARGET_PATH")"
SAFE_BASENAME="$(printf '%s' "$REPO_BASENAME" | tr -c 'A-Za-z0-9_.-' '_')"
[[ -n "$SAFE_BASENAME" ]] || SAFE_BASENAME="working-repo"

if [[ -z "$OUT_PATH" ]]; then
  OUT_PATH="${SAFE_BASENAME}-working-snapshot.zip"
fi
OUT_PATH="$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$OUT_PATH")"

if [[ -z "$FILENAME" ]]; then
  FILENAME="$(basename "$OUT_PATH")"
fi
[[ "$FILENAME" == *.zip ]] || FILENAME="${FILENAME}.zip"

IN_GIT="no"
if [[ -d "$TARGET_PATH/.git" ]] || git -C "$TARGET_PATH" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  IN_GIT="yes"
fi

echo "== Packaging working repository =="
echo "target_path: $TARGET_PATH"
echo "output_zip: $OUT_PATH"
echo "mode: $MODE"
echo "in_git_repo: $IN_GIT"

if [[ "$IN_GIT" == "yes" ]]; then
  echo "== Git status snapshot =="
  git -C "$TARGET_PATH" status --porcelain || true
  echo "== Changed files =="
  git -C "$TARGET_PATH" diff --stat || true
fi

TMPDIR_PACKAGING="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_PACKAGING"' EXIT
LIST_FILE="$TMPDIR_PACKAGING/files.txt"

pushd "$TARGET_PATH" >/dev/null
if [[ "$MODE" == "tracked" && "$IN_GIT" == "yes" ]]; then
  git -C "$TARGET_PATH" ls-files -z --cached --others --exclude-standard > "$TMPDIR_PACKAGING/all_files.bin"
  python3 - "$TMPDIR_PACKAGING/all_files.bin" "$LIST_FILE" <<'PY'
import sys
from pathlib import Path

all_files_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
exclude_suffixes = {'tar', 'zip'}
lines = []
for raw in all_files_path.read_bytes().split(b"\x00"):
    line = raw.decode('utf-8', 'replace').strip()
    if not line:
        continue
    if line.startswith('.git/') or line == '.git':
        continue
    suffix = line.rsplit('.', 1)[-1].lower() if '.' in line else ''
    if line.endswith('.tar.gz') or line.endswith('.tgz') or suffix in exclude_suffixes:
        continue
    lines.append(line)
out_path.write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')
PY
  if [[ ! -s "$LIST_FILE" ]]; then
    die "No files found after applying gitignore rules. Use --mode all if you want a raw directory snapshot."
  fi
  zip -q -@ -0 "$OUT_PATH" < "$LIST_FILE"
else
  zip -qr "$OUT_PATH" . \
    -x './.git/*' \
    -x './.git' \
    -x './node_modules/*' \
    -x './__pycache__/*' \
    -x './uploads/*' \
    -x './jobs/*' \
    -x './jenkins-data/*'
fi
popd >/dev/null

[[ -f "$OUT_PATH" ]] || die "Failed to create zip archive: $OUT_PATH"
ZIP_SIZE="$(wc -c < "$OUT_PATH" | tr -d ' ')"
echo "zip_bytes: $ZIP_SIZE"

if [[ "$SUBMIT" == "no" ]]; then
  echo "== Packaging completed without submission =="
  exit 0
fi

require_cmd curl
URL="${BASE_URL%/}/upload?filename=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$FILENAME")"
if [[ -n "$JOB_ID" ]]; then
  URL="${URL}&job_id=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$JOB_ID")"
fi
if [[ -n "$TIMEOUT_SECONDS" ]]; then
  URL="${URL}&timeout=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$TIMEOUT_SECONDS")"
fi

AUTH_HEADER=()
if [[ -n "${UPLOAD_TOKEN:-}" ]]; then
  AUTH_HEADER=(-H "Authorization: Bearer $UPLOAD_TOKEN")
fi

echo "== Submitting zip to build service =="
echo "url: $URL"
HTTP_CODE_FILE="$TMPDIR_PACKAGING/http_code.txt"
RESPONSE_FILE="$TMPDIR_PACKAGING/response.json"

HTTP_CODE="$(curl -sS -X POST "$URL" \
  -H "Content-Type: application/zip" \
  "${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"}" \
  --data-binary @"$OUT_PATH" \
  -o "$RESPONSE_FILE" \
  -w '%{http_code}')"

echo "http_status: $HTTP_CODE"

if [[ -s "$RESPONSE_FILE" ]]; then
  echo "== Service response =="
  cat "$RESPONSE_FILE"
  echo ""
fi

if [[ "$HTTP_CODE" -lt 200 || "$HTTP_CODE" -ge 300 ]]; then
  die "Build service returned HTTP $HTTP_CODE"
fi

exit 0
