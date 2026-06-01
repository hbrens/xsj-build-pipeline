#!/usr/bin/env python3
"""Package a HarmonyOS project (including uncommitted changes) and submit it
to the xsj-build-pipeline build service.

Usage:
    python3 harmony_build.py /path/to/project [--server URL] [--out DIR]
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

# Directories to exclude from the zip
EXCLUDE_DIRS = {
    ".git", ".hvigor", ".build-verify", "node_modules",
    "build", ".preview", "__pycache__", ".idea", ".vscode",
}

EXCLUDE_SUFFIXES = {".zip", ".har", ".hap", ".hsp", ".app"}

POLL_INTERVAL = 5
POLL_TIMEOUT = 1800


def should_exclude(rel: Path) -> bool:
    for part in rel.parts:
        if part in EXCLUDE_DIRS:
            return True
    if rel.suffix in EXCLUDE_SUFFIXES:
        return True
    return False


def create_zip(project_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(project_dir.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(project_dir)
            if should_exclude(rel):
                continue
            zf.write(f, rel)
    return buf.getvalue()


def api_request(base: str, path: str, *, data: bytes | None = None,
                content_type: str | None = None) -> tuple[int, bytes]:
    url = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
    req = Request(url, data=data, method="POST" if data is not None else "GET")
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urlopen(req) as resp:
            return resp.status, resp.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def upload(server: str, zip_bytes: bytes) -> dict:
    boundary = "----HarmonyBuildBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="project.zip"\r\n'
        f"Content-Type: application/zip\r\n\r\n"
    ).encode() + zip_bytes + f"\r\n--{boundary}--\r\n".encode()

    status, resp = api_request(
        server, "/builds", data=body,
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    payload = json.loads(resp)
    if status != 202:
        print(f"Upload failed ({status}): {json.dumps(payload, ensure_ascii=False)}", file=sys.stderr)
        sys.exit(1)
    return payload


def poll(server: str, job_id: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT
    last = ""
    while time.monotonic() < deadline:
        _, resp = api_request(server, f"/builds/{job_id}")
        data = json.loads(resp)
        cur = data.get("status", "")
        if cur != last:
            print(f"  status: {cur}")
            last = cur
        if cur in {"success", "failed", "error"}:
            return data
        time.sleep(POLL_INTERVAL)
    print("Timed out waiting for build.", file=sys.stderr)
    sys.exit(1)


def fetch_log(server: str, job_id: str) -> str:
    _, resp = api_request(server, f"/builds/{job_id}/logs")
    return resp.decode("utf-8", errors="replace")


def download_artifacts(server: str, job_id: str, artifacts: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for art in artifacts:
        name = art["name"]
        print(f"  downloading {name} ...")
        _, data = api_request(server, art["download_url"])
        dest = out_dir / name
        dest.write_bytes(data)
        print(f"    -> {dest} ({len(data)} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Package and build a HarmonyOS project")
    parser.add_argument("project", type=Path, help="Project directory to package")
    parser.add_argument("--server", default="http://127.0.0.1:8080",
                        help="Build service URL (default: http://127.0.0.1:8080)")
    parser.add_argument("--out", type=Path, default=None,
                        help="Directory to save artifacts (default: ./build-artifacts)")
    args = parser.parse_args()

    project = args.project.resolve()
    if not project.is_dir():
        print(f"Not a directory: {project}", file=sys.stderr)
        sys.exit(1)

    out_dir = args.out or Path("build-artifacts")

    print(f"Packaging {project} ...")
    zip_bytes = create_zip(project)
    print(f"  zip size: {len(zip_bytes) / 1024 / 1024:.1f} MB")

    print("Uploading ...")
    result = upload(args.server, zip_bytes)
    job_id = result["job_id"]
    print(f"  job_id: {job_id}")

    print("Waiting for build ...")
    final = poll(args.server, job_id)

    if final["status"] == "success":
        artifacts = final.get("artifacts", [])
        if artifacts:
            print(f"Build succeeded! Downloading {len(artifacts)} artifact(s) ...")
            download_artifacts(args.server, job_id, artifacts, out_dir)
        else:
            print("Build succeeded (no artifacts).")
    else:
        print(f"Build {final['status']}: {final.get('message', '')}")
        log = fetch_log(args.server, job_id)
        if log:
            print("\n--- build log (last 4000 chars) ---")
            print(log[-4000:])
        sys.exit(1)


if __name__ == "__main__":
    main()
