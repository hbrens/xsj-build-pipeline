#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import uuid
import zipfile
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
JOBS_DIR = Path(os.environ.get("JOBS_DIR", ROOT_DIR / "jobs")).resolve()
BUILD_SCRIPT = Path(os.environ.get("BUILD_SCRIPT", ROOT_DIR / "scripts" / "build_harmony_zip.sh")).resolve()
TOOLS_DIR = Path(os.environ.get("TOOLS_DIR", ROOT_DIR / "command-line-tools")).resolve()
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "500")) * 1024 * 1024
MAX_CONCURRENT_BUILDS = int(os.environ.get("MAX_CONCURRENT_BUILDS", "1"))

build_slots = threading.BoundedSemaphore(MAX_CONCURRENT_BUILDS)


def utc_status_payload(job_id: str, status: str, message: str, exit_code: int | None = None) -> dict:
    from datetime import datetime, timezone

    return {
        "job_id": job_id,
        "status": status,
        "message": message,
        "exit_code": exit_code,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "log_path": "logs/build.log",
        "artifacts": list_artifacts(job_id),
    }


def job_dir(job_id: str) -> Path:
    if not is_valid_job_id(job_id):
        raise ValueError("Invalid job id")
    return JOBS_DIR / job_id


def is_valid_job_id(job_id: str) -> bool:
    try:
        uuid.UUID(job_id)
    except ValueError:
        return False
    return True


def status_file(job_id: str) -> Path:
    return job_dir(job_id) / "status.json"


def write_status(job_id: str, status: str, message: str, exit_code: int | None = None) -> None:
    path = status_file(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = utc_status_payload(job_id, status, message, exit_code)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_status(job_id: str) -> dict | None:
    path = status_file(job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_artifacts(job_id: str) -> list[dict]:
    artifact_dir = job_dir(job_id) / "artifacts"
    if not artifact_dir.is_dir():
        return []
    artifacts = []
    for path in sorted(artifact_dir.iterdir()):
        if path.is_file():
            artifacts.append(
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "download_url": f"/builds/{job_id}/artifacts/{path.name}",
                }
            )
    return artifacts


def parse_upload(content_type: str, body: bytes) -> tuple[str, bytes]:
    if "multipart/form-data" in content_type:
        header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        message = BytesParser(policy=policy.default).parsebytes(header + body)
        for part in message.iter_parts():
            filename = part.get_filename()
            disposition = part.get("Content-Disposition", "")
            if filename or 'name="file"' in disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    return filename or "upload.zip", payload
        raise ValueError("Multipart request must include a non-empty file field")

    if content_type in {"application/zip", "application/octet-stream"} or content_type.startswith(
        "application/zip;"
    ):
        return "upload.zip", body

    raise ValueError("Use multipart/form-data field 'file' or Content-Type: application/zip")


def run_build(job_id: str) -> None:
    current_job = job_dir(job_id)
    zip_path = current_job / "upload.zip"

    with build_slots:
        write_status(job_id, "running", "Build started")
        env = os.environ.copy()
        env.setdefault("BUILD_TIMEOUT_SECONDS", "1200")

        result = subprocess.run(
            [str(BUILD_SCRIPT), str(zip_path), str(current_job), str(TOOLS_DIR)],
            cwd=str(ROOT_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            check=False,
        )

        latest = read_status(job_id)
        if latest is None or latest.get("status") in {"queued", "running"}:
            if result.returncode == 0:
                write_status(job_id, "success", "Build succeeded", 0)
            else:
                write_status(job_id, "failed", f"Build failed with exit code {result.returncode}", result.returncode)


class Handler(BaseHTTPRequestHandler):
    server_version = "HarmonyBuildAPI/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]

        if parsed.path == "/" or parsed.path == "/health":
            self.send_json({"status": "ok"})
            return

        if len(parts) == 2 and parts[0] == "builds":
            self.handle_get_build(parts[1])
            return

        if len(parts) == 3 and parts[0] == "builds" and parts[2] == "logs":
            self.handle_get_logs(parts[1])
            return

        if len(parts) == 3 and parts[0] == "builds" and parts[2] == "artifacts":
            self.handle_list_artifacts(parts[1])
            return

        if len(parts) == 4 and parts[0] == "builds" and parts[2] == "artifacts":
            self.handle_download_artifact(parts[1], parts[3])
            return

        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/builds":
            self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")
            return

        content_length = self.headers.get("Content-Length")
        if not content_length:
            self.send_error_json(HTTPStatus.LENGTH_REQUIRED, "Content-Length is required")
            return

        try:
            length = int(content_length)
        except ValueError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
            return

        if length <= 0:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Upload body is empty")
            return
        if length > MAX_UPLOAD_BYTES:
            self.send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Upload is too large")
            return

        body = self.rfile.read(length)
        try:
            original_name, payload = parse_upload(self.headers.get("Content-Type", ""), body)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return

        job_id = str(uuid.uuid4())
        current_job = job_dir(job_id)
        current_job.mkdir(parents=True, exist_ok=False)
        (current_job / "logs").mkdir()
        (current_job / "artifacts").mkdir()

        zip_path = current_job / "upload.zip"
        zip_path.write_bytes(payload)
        if not zipfile.is_zipfile(zip_path):
            shutil.rmtree(current_job, ignore_errors=True)
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Uploaded file is not a valid zip")
            return

        (current_job / "upload_name.txt").write_text(original_name + "\n", encoding="utf-8")
        write_status(job_id, "queued", "Build is queued")

        worker = threading.Thread(target=run_build, args=(job_id,), daemon=True)
        worker.start()

        self.send_json(read_status(job_id), status=HTTPStatus.ACCEPTED)

    def handle_get_build(self, job_id: str) -> None:
        if not is_valid_job_id(job_id):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid job id")
            return
        status = read_status(job_id)
        if status is None:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Build not found")
            return
        status["artifacts"] = list_artifacts(job_id)
        self.send_json(status)

    def handle_get_logs(self, job_id: str) -> None:
        if not is_valid_job_id(job_id):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid job id")
            return
        path = job_dir(job_id) / "logs" / "build.log"
        if not path.exists():
            self.send_text("", content_type="text/plain; charset=utf-8")
            return
        self.send_text(path.read_text(encoding="utf-8", errors="replace"), content_type="text/plain; charset=utf-8")

    def handle_list_artifacts(self, job_id: str) -> None:
        if not is_valid_job_id(job_id):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid job id")
            return
        if not job_dir(job_id).exists():
            self.send_error_json(HTTPStatus.NOT_FOUND, "Build not found")
            return
        self.send_json({"job_id": job_id, "artifacts": list_artifacts(job_id)})

    def handle_download_artifact(self, job_id: str, artifact_name: str) -> None:
        if not is_valid_job_id(job_id) or artifact_name != os.path.basename(artifact_name):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid artifact path")
            return
        path = job_dir(job_id) / "artifacts" / artifact_name
        if not path.is_file():
            self.send_error_json(HTTPStatus.NOT_FOUND, "Artifact not found")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        with path.open("rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def send_json(self, payload: dict | None, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload or {}, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, text: str, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status=status)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    if not BUILD_SCRIPT.exists():
        raise SystemExit(f"Build script not found: {BUILD_SCRIPT}")
    if not TOOLS_DIR.exists():
        raise SystemExit(f"Command line tools not found: {TOOLS_DIR}")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Listening on http://{HOST}:{PORT}")
    print(f"jobs_dir={JOBS_DIR}")
    print(f"tools_dir={TOOLS_DIR}")
    server.serve_forever()


if __name__ == "__main__":
    main()
