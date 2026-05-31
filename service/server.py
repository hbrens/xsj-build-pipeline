#!/usr/bin/env python3
import base64
import hmac
import json
import os
import re
import tempfile
import uuid
import zipfile
from http.cookiejar import CookieJar
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


CHUNK_SIZE = 1024 * 1024
JENKINS_OPENER = build_opener(HTTPCookieProcessor(CookieJar()))


def env_int(name, default):
    value = os.getenv(name, str(default))
    try:
        return int(value)
    except ValueError:
        return default


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def clean_filename(name):
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", base)
    base = base.strip("._")
    if not base:
        base = "upload.zip"
    if not base.lower().endswith(".zip"):
        raise ValueError("uploaded filename must end with .zip")
    return base


def clean_job_id(value):
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", (value or "").strip())
    return value.strip("._")


def jenkins_job_path(job_name):
    parts = [part for part in job_name.split("/") if part]
    return "/".join("job/" + quote(part, safe="") for part in parts)


class Config:
    host = os.getenv("HOST", "0.0.0.0")
    port = env_int("PORT", 8090)
    uploads_dir = os.getenv("UPLOADS_DIR", "/data/uploads")
    jenkins_uploads_dir = os.getenv("JENKINS_UPLOADS_DIR", "/data/uploads")
    max_upload_bytes = env_int("MAX_UPLOAD_BYTES", 1024 * 1024 * 1024)
    upload_token = os.getenv("UPLOAD_TOKEN", "")
    jenkins_url = os.getenv("JENKINS_URL", "http://jenkins:8080").rstrip("/")
    jenkins_job = os.getenv("JENKINS_JOB", "harmony-zip-build")
    jenkins_user = os.getenv("JENKINS_USER", "admin")
    jenkins_password = os.getenv("JENKINS_PASSWORD", "admin")
    build_timeout_seconds = os.getenv("BUILD_TIMEOUT_SECONDS", "1200")
    request_timeout_seconds = env_int("REQUEST_TIMEOUT_SECONDS", 30)


class UploadHandler(BaseHTTPRequestHandler):
    server_version = "HarmonyUploadService/1.0"

    def do_GET(self):
        path = urlparse(self.path).path
        if path in {"/health", "/healthz"}:
            self.send_json(200, {"status": "ok"})
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/upload":
            self.send_json(404, {"error": "not found"})
            return

        if not self.authorized():
            self.send_json(401, {"error": "unauthorized"})
            return

        try:
            response = self.handle_upload()
            self.send_json(201, response)
        except ClientError as exc:
            self.send_json(exc.status, {"error": exc.message})
        except JenkinsError as exc:
            self.send_json(exc.status, {"error": exc.message, **exc.details})
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})

    def authorized(self):
        if not Config.upload_token:
            return True
        supplied = self.headers.get("X-Upload-Token", "")
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            supplied = auth_header[len("Bearer ") :]
        return hmac.compare_digest(supplied, Config.upload_token)

    def handle_upload(self):
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            raise ClientError(
                415,
                "multipart/form-data is not supported; send the raw zip body with Content-Type: application/zip",
            )

        length_header = self.headers.get("Content-Length")
        if not length_header:
            raise ClientError(411, "Content-Length is required")
        try:
            content_length = int(length_header)
        except ValueError as exc:
            raise ClientError(400, "Content-Length must be an integer") from exc
        if content_length <= 0:
            raise ClientError(400, "upload body is empty")
        if content_length > Config.max_upload_bytes:
            raise ClientError(413, "upload exceeds MAX_UPLOAD_BYTES")

        query = parse_qs(urlparse(self.path).query)
        original_name = query.get("filename", [None])[0] or self.headers.get("X-Filename")
        safe_name = clean_filename(original_name)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        unique_id = uuid.uuid4().hex[:12]
        stored_name = f"{stamp}-{unique_id}-{safe_name}"
        default_job_id = f"{stamp}-{unique_id}"
        job_id = clean_job_id(query.get("job_id", [default_job_id])[0]) or default_job_id
        timeout_seconds = query.get("timeout", [Config.build_timeout_seconds])[0]

        os.makedirs(Config.uploads_dir, exist_ok=True)
        final_path = os.path.abspath(os.path.join(Config.uploads_dir, stored_name))
        uploads_root = os.path.abspath(Config.uploads_dir)
        if not final_path.startswith(uploads_root + os.sep):
            raise ClientError(400, "invalid upload path")

        fd, tmp_path = tempfile.mkstemp(prefix=".uploading-", suffix=".tmp", dir=Config.uploads_dir)
        try:
            with os.fdopen(fd, "wb") as output:
                remaining = content_length
                while remaining:
                    chunk = self.rfile.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ClientError(400, "upload ended before Content-Length bytes were received")
                    output.write(chunk)
                    remaining -= len(chunk)

            if not zipfile.is_zipfile(tmp_path):
                raise ClientError(400, "uploaded file is not a valid zip archive")

            os.chmod(tmp_path, 0o644)
            os.replace(tmp_path, final_path)
            tmp_path = None

            jenkins_zip_path = Config.jenkins_uploads_dir.rstrip("/") + "/" + stored_name
            trigger = trigger_jenkins_build(jenkins_zip_path, job_id, timeout_seconds)
            return {
                "status": "queued",
                "filename": stored_name,
                "job_id": job_id,
                "zip_path": jenkins_zip_path,
                **trigger,
            }
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def send_json(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ClientError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class JenkinsError(Exception):
    def __init__(self, status, message, **details):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details


def jenkins_request(method, url, data=None, headers=None):
    headers = dict(headers or {})
    auth = base64.b64encode(f"{Config.jenkins_user}:{Config.jenkins_password}".encode("utf-8")).decode("ascii")
    headers["Authorization"] = "Basic " + auth
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with JENKINS_OPENER.open(request, timeout=Config.request_timeout_seconds) as response:
            return response.status, response.headers, response.read()
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read()
    except URLError as exc:
        raise JenkinsError(502, "could not connect to Jenkins", detail=str(exc)) from exc


def get_jenkins_crumb():
    status, headers, body = jenkins_request("GET", Config.jenkins_url + "/crumbIssuer/api/json")
    if status == 404:
        return {}
    if status != 200:
        raise JenkinsError(status, "could not fetch Jenkins crumb", response=body.decode("utf-8", "replace"))
    payload = json.loads(body.decode("utf-8"))
    return {payload["crumbRequestField"]: payload["crumb"]}


def trigger_jenkins_build(zip_path, job_id, timeout_seconds):
    crumb_headers = get_jenkins_crumb()
    body = urlencode(
        {
            "ZIP_PATH": zip_path,
            "JOB_ID": job_id,
            "BUILD_TIMEOUT_SECONDS": timeout_seconds,
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded", **crumb_headers}
    job_url = Config.jenkins_url + "/" + jenkins_job_path(Config.jenkins_job)
    build_url = job_url + "/buildWithParameters"
    status, response_headers, response_body = jenkins_request("POST", build_url, data=body, headers=headers)
    if status not in {200, 201, 302}:
        raise JenkinsError(
            status,
            "Jenkins build trigger failed",
            response=response_body.decode("utf-8", "replace"),
        )
    return {
        "jenkins_job_url": job_url + "/",
        "jenkins_queue_url": response_headers.get("Location"),
    }


def main():
    os.makedirs(Config.uploads_dir, exist_ok=True)
    server = ThreadingHTTPServer((Config.host, Config.port), UploadHandler)
    print(f"upload service listening on {Config.host}:{Config.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
