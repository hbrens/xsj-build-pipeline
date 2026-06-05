#!/usr/bin/env python3
"""Deterministic HarmonyOS package/build helper for xsj-build-pipeline."""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


PROJECT_MARKERS = {"hvigorfile.ts", "build-profile.json5", "oh-package.json5"}
EXCLUDE_DIRS = {
    ".git",
    ".hvigor",
    ".build-verify",
    ".preview",
    ".xsj-build",
    "__pycache__",
    "build",
    "node_modules",
    ".idea",
    ".vscode",
}
EXCLUDE_SUFFIXES = {".app", ".hap", ".har", ".hsp", ".zip"}
ARTIFACT_SUFFIXES = {".app", ".hap", ".har", ".hsp"}
DEFAULT_SERVER = "http://127.0.0.1:8080"
DEFAULT_POLL_INTERVAL = 5
DEFAULT_POLL_TIMEOUT = 1800
ARGPARSE_TRANSLATIONS = {
    "usage: ": "用法：",
    "positional arguments": "位置参数",
    "options": "选项",
    "show this help message and exit": "显示帮助信息并退出",
    "the following arguments are required: %s": "缺少必要参数：%s",
    "invalid choice: %(value)r (choose from %(choices)s)": "无效选择：%(value)r（可选：%(choices)s）",
}


def install_argparse_translations() -> None:
    argparse._ = lambda text: ARGPARSE_TRANSLATIONS.get(text, text)


class ChineseArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}：错误：{message}\n")


@dataclass(frozen=True)
class Layout:
    project_root: Path
    run_dir: Path | None = None

    @property
    def xsj_dir(self) -> Path:
        return self.project_root / ".xsj-build"

    @property
    def runs_dir(self) -> Path:
        return self.xsj_dir / "runs"

    @property
    def package_dir(self) -> Path:
        return self.require_run_dir() / "package"

    @property
    def zip_path(self) -> Path:
        return self.package_dir / "project.zip"

    @property
    def manifest_path(self) -> Path:
        return self.package_dir / "manifest.json"

    @property
    def remote_dir(self) -> Path:
        return self.require_run_dir() / "remote"

    @property
    def upload_path(self) -> Path:
        return self.remote_dir / "upload.json"

    @property
    def status_path(self) -> Path:
        return self.remote_dir / "status.json"

    @property
    def log_path(self) -> Path:
        return self.remote_dir / "build.log"

    @property
    def status_history_path(self) -> Path:
        return self.remote_dir / "status_history.jsonl"

    @property
    def artifacts_dir(self) -> Path:
        return self.require_run_dir() / "artifacts"

    def require_run_dir(self) -> Path:
        if self.run_dir is None:
            raise RuntimeError("当前操作需要 run_dir")
        return self.run_dir


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def append_json_line(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def path_payload(path: Path) -> str:
    return str(path.resolve())


def should_skip_dir(path: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in path.parts)


def should_exclude_file(rel: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return True
    return rel.suffix.lower() in EXCLUDE_SUFFIXES


def find_project_roots(search_dir: Path) -> list[Path]:
    roots: list[Path] = []
    for root, dirs, files in os.walk(search_dir):
        root_path = Path(root)
        rel = root_path.relative_to(search_dir)
        dirs[:] = [
            d for d in dirs
            if not should_skip_dir(rel / d)
        ]
        if PROJECT_MARKERS.issubset(set(files)):
            roots.append(root_path)
            dirs[:] = []
    return sorted(roots)


def detect_project(path: Path) -> Path:
    target = path.expanduser().resolve()
    if not target.exists():
        raise SystemExit(f"路径不存在：{target}")
    if not target.is_dir():
        raise SystemExit(f"这不是一个目录：{target}")

    if PROJECT_MARKERS.issubset({p.name for p in target.iterdir() if p.is_file()}):
        return target

    candidates = find_project_roots(target)
    if not candidates:
        missing = ", ".join(sorted(PROJECT_MARKERS))
        raise SystemExit(
            f"这不是鸿蒙项目目录，也没有在其子目录中找到唯一的鸿蒙项目：{target}\n"
            f"需要同一个目录同时包含这些文件：{missing}"
        )
    if len(candidates) > 1:
        lines = "\n".join(f"  - {candidate}" for candidate in candidates)
        raise SystemExit(
            "找到多个鸿蒙项目目录，请重新指定其中一个明确的项目目录：\n"
            f"{lines}"
        )
    return candidates[0]


def create_run_dir(project_root: Path) -> Path:
    runs_dir = project_root / ".xsj-build" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for index in range(1000):
        suffix = "" if index == 0 else f"-{index}"
        candidate = runs_dir / f"{stamp}{suffix}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise SystemExit(f"无法在该目录下创建唯一的运行目录：{runs_dir}")


def resolve_existing_run_dir(project_root: Path, run_dir: Path | None) -> Path:
    if run_dir is None:
        raise SystemExit("当前命令需要提供 --run-dir")
    resolved = run_dir.expanduser().resolve()
    if not resolved.is_dir():
        raise SystemExit(f"运行目录不存在：{resolved}")
    runs_dir = (project_root / ".xsj-build" / "runs").resolve()
    if resolved.parent != runs_dir:
        raise SystemExit(f"运行目录必须是该目录的直接子目录：{runs_dir}\n当前传入：{resolved}")
    return resolved


def relative_name(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def build_manifest(project_root: Path, files: list[Path], zip_size: int) -> dict:
    return {
        "created_at": datetime.now().astimezone().isoformat(),
        "project_root": path_payload(project_root),
        "project_markers": sorted(PROJECT_MARKERS),
        "file_count": len(files),
        "zip_size_bytes": zip_size,
        "excluded_dirs": sorted(EXCLUDE_DIRS),
        "excluded_suffixes": sorted(EXCLUDE_SUFFIXES),
    }


def collect_package_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(project_root)
        if should_exclude_file(rel):
            continue
        files.append(path)
    return files


def create_package(layout: Layout) -> dict:
    run_dir = layout.require_run_dir()
    layout.package_dir.mkdir(parents=True, exist_ok=True)
    layout.remote_dir.mkdir(parents=True, exist_ok=True)
    layout.artifacts_dir.mkdir(parents=True, exist_ok=True)

    files = collect_package_files(layout.project_root)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, relative_name(path, layout.project_root))

    zip_bytes = buffer.getvalue()
    layout.zip_path.write_bytes(zip_bytes)

    manifest = build_manifest(layout.project_root, files, len(zip_bytes))
    manifest["run_dir"] = path_payload(run_dir)
    manifest["zip_path"] = path_payload(layout.zip_path)
    write_json(layout.manifest_path, manifest)
    return manifest


def api_request(
    base_url: str,
    path: str,
    *,
    data: bytes | None = None,
    content_type: str | None = None,
    timeout: int = 60,
) -> tuple[int, bytes]:
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    req = Request(url, data=data, method="POST" if data is not None else "GET")
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except HTTPError as exc:
        return exc.code, exc.read()
    except URLError as exc:
        raise SystemExit(f"无法连接构建服务：{base_url}\n原因：{exc}") from exc


def parse_json_response(status: int, body: bytes, label: str) -> dict:
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        text = body.decode("utf-8", errors="replace")
        raise SystemExit(f"{label} 返回了非 JSON 响应（HTTP {status}）：{text[:1000]}") from exc
    return payload


def upload_package(layout: Layout, server: str) -> dict:
    if not layout.zip_path.is_file():
        raise SystemExit(f"打包文件不存在：{layout.zip_path}")
    if layout.upload_path.exists():
        raise SystemExit(f"上传记录已存在，为避免覆盖数据已停止：{layout.upload_path}")

    zip_bytes = layout.zip_path.read_bytes()
    boundary = "----XsjHarmonyBuildBoundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="project.zip"\r\n'
        "Content-Type: application/zip\r\n\r\n"
    ).encode("utf-8") + zip_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    status, response = api_request(
        server,
        "/builds",
        data=body,
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    payload = parse_json_response(status, response, "Upload")
    payload.update({
        "server": server,
        "http_status": status,
        "uploaded_at": datetime.now().astimezone().isoformat(),
        "zip_path": path_payload(layout.zip_path),
        "zip_size_bytes": len(zip_bytes),
    })
    write_json(layout.upload_path, payload)

    if status != 202:
        raise SystemExit(f"上传失败（HTTP {status}）：{json.dumps(payload, ensure_ascii=False)}")
    if not payload.get("job_id"):
        raise SystemExit(f"上传响应中没有 job_id：{json.dumps(payload, ensure_ascii=False)}")
    return payload


def job_id_from_run(layout: Layout) -> str:
    if layout.upload_path.is_file():
        upload = read_json(layout.upload_path)
        job_id = upload.get("job_id")
        if job_id:
            return str(job_id)
    if layout.status_path.is_file():
        status = read_json(layout.status_path)
        job_id = status.get("job_id")
        if job_id:
            return str(job_id)
    raise SystemExit(f"没有在这些文件中找到 job_id：{layout.upload_path} 或 {layout.status_path}")


def server_from_run(layout: Layout, fallback: str) -> str:
    if layout.upload_path.is_file():
        upload = read_json(layout.upload_path)
        if upload.get("server"):
            return str(upload["server"])
    if layout.status_path.is_file():
        status = read_json(layout.status_path)
        if status.get("server"):
            return str(status["server"])
    return fallback


def fetch_status(server: str, job_id: str) -> dict:
    http_status, response = api_request(server, f"/builds/{job_id}")
    payload = parse_json_response(http_status, response, "Status")
    payload["server"] = server
    payload["http_status"] = http_status
    payload["checked_at"] = datetime.now().astimezone().isoformat()
    return payload


def fetch_log(server: str, job_id: str) -> str:
    status, response = api_request(server, f"/builds/{job_id}/logs")
    if status >= 400:
        return response.decode("utf-8", errors="replace")
    return response.decode("utf-8", errors="replace")


def write_build_log(layout: Layout, content: str) -> Path:
    if not layout.log_path.exists():
        layout.log_path.write_text(content, encoding="utf-8")
        return layout.log_path
    existing = layout.log_path.read_text(encoding="utf-8", errors="replace")
    if existing == content:
        return layout.log_path

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for index in range(1000):
        suffix = "" if index == 0 else f"-{index}"
        candidate = layout.remote_dir / f"build-{stamp}{suffix}.log"
        if candidate.exists():
            continue
        candidate.write_text(content, encoding="utf-8")
        return candidate
    raise SystemExit(f"无法在该目录下创建唯一的构建日志：{layout.remote_dir}")


def poll_build(layout: Layout, server: str, interval: int, timeout: int) -> dict:
    job_id = job_id_from_run(layout)
    deadline = time.monotonic() + timeout
    last_status = None
    final_statuses = {"success", "failed", "error", "timeout"}

    while time.monotonic() <= deadline:
        payload = fetch_status(server, job_id)
        write_json(layout.status_path, payload)
        append_json_line(layout.status_history_path, payload)
        current = str(payload.get("status", ""))
        if current != last_status:
            print(f"状态：{current}")
            last_status = current
        if current in final_statuses:
            log = fetch_log(server, job_id)
            payload["saved_log_path"] = path_payload(write_build_log(layout, log))
            write_json(layout.status_path, payload)
            return payload
        time.sleep(interval)

    payload = {
        "job_id": job_id,
        "server": server,
        "status": "timeout",
        "message": f"轮询超时，已等待 {timeout} 秒",
        "checked_at": datetime.now().astimezone().isoformat(),
    }
    write_json(layout.status_path, payload)
    append_json_line(layout.status_history_path, payload)
    try:
        log = fetch_log(server, job_id)
        payload["saved_log_path"] = path_payload(write_build_log(layout, log))
        write_json(layout.status_path, payload)
    except SystemExit:
        pass
    return payload


def safe_artifact_name(name: str) -> str:
    candidate = Path(name).name
    if not candidate:
        raise SystemExit(f"无效的产物名称：{name!r}")
    if Path(candidate).suffix.lower() not in ARTIFACT_SUFFIXES:
        raise SystemExit(f"产物文件后缀不符合预期：{candidate}")
    return candidate


def artifact_download_path(artifact: dict, job_id: str) -> str:
    url = artifact.get("download_url")
    if not url:
        name = artifact.get("name")
        if not name:
            raise SystemExit(f"产物信息缺少 name 或 download_url：{artifact}")
        return f"/builds/{job_id}/artifacts/{name}"
    return str(url)


def download_artifacts(layout: Layout, server: str) -> list[dict]:
    if not layout.status_path.is_file():
        raise SystemExit(f"状态文件不存在：{layout.status_path}")
    status = read_json(layout.status_path)
    if status.get("status") != "success":
        raise SystemExit(f"当前状态不是 success，不能下载产物：{status.get('status')}")

    artifacts = status.get("artifacts") or []
    if not artifacts:
        print("远端没有列出可下载产物。")
        return []

    layout.artifacts_dir.mkdir(parents=True, exist_ok=True)
    job_id = str(status.get("job_id") or job_id_from_run(layout))
    downloaded: list[dict] = []
    for artifact in artifacts:
        name = safe_artifact_name(str(artifact.get("name", "")))
        path = artifact_download_path(artifact, job_id)
        http_status, data = api_request(server, path)
        if http_status != 200:
            text = data.decode("utf-8", errors="replace")
            raise SystemExit(f"下载失败：{name}（HTTP {http_status}）：{text[:1000]}")
        dest = layout.artifacts_dir / name
        if dest.exists():
            raise SystemExit(f"产物文件已存在，为避免覆盖数据已停止：{dest}")
        dest.write_bytes(data)
        downloaded.append({"name": name, "size": len(data), "path": path_payload(dest)})

    download_record = {
        "downloaded_at": datetime.now().astimezone().isoformat(),
        "server": server,
        "artifacts": downloaded,
    }
    write_json(layout.remote_dir / "download.json", download_record)
    return downloaded


def print_summary(title: str, payload: dict) -> None:
    titles = {
        "detect": "检测结果",
        "package": "打包结果",
        "submit": "提交结果",
        "poll": "轮询结果",
        "download": "下载结果",
        "build": "构建结果",
    }
    print(f"== {titles.get(title, title)} ==")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def run_payload(project_root: Path, run_dir: Path) -> dict:
    return {
        "project_root": path_payload(project_root),
        "run_dir": path_payload(run_dir),
        "data_retention_note": "不会自动删除任何构建数据。本次运行的数据已保留在 run_dir，后续如需清理请用户手动处理。",
    }


def command_detect(args: argparse.Namespace) -> int:
    project_root = detect_project(args.project)
    layout = Layout(project_root)
    print_summary("detect", {
        "project_root": path_payload(project_root),
        "xsj_dir": path_payload(layout.xsj_dir),
        "markers": sorted(PROJECT_MARKERS),
    })
    return 0


def command_package(args: argparse.Namespace) -> int:
    project_root = detect_project(args.project)
    run_dir = create_run_dir(project_root)
    layout = Layout(project_root, run_dir)
    manifest = create_package(layout)
    payload = run_payload(project_root, run_dir)
    payload.update({
        "zip_path": path_payload(layout.zip_path),
        "manifest_path": path_payload(layout.manifest_path),
        "file_count": manifest["file_count"],
        "zip_size_bytes": manifest["zip_size_bytes"],
    })
    print_summary("package", payload)
    return 0


def command_submit(args: argparse.Namespace) -> int:
    project_root = detect_project(args.project)
    run_dir = resolve_existing_run_dir(project_root, args.run_dir)
    layout = Layout(project_root, run_dir)
    upload = upload_package(layout, args.server)
    payload = run_payload(project_root, run_dir)
    payload.update({
        "server": args.server,
        "job_id": upload["job_id"],
        "upload_path": path_payload(layout.upload_path),
    })
    print_summary("submit", payload)
    return 0


def command_poll(args: argparse.Namespace) -> int:
    project_root = detect_project(args.project)
    run_dir = resolve_existing_run_dir(project_root, args.run_dir)
    layout = Layout(project_root, run_dir)
    server = server_from_run(layout, args.server)
    final = poll_build(layout, server, args.interval, args.timeout)
    status = final.get("status")
    payload = run_payload(project_root, run_dir)
    payload.update({
        "server": server,
        "job_id": final.get("job_id"),
        "status": status,
        "status_path": path_payload(layout.status_path),
        "status_history_path": path_payload(layout.status_history_path),
        "log_path": final.get("saved_log_path") or path_payload(layout.log_path),
    })
    print_summary("poll", payload)
    return 0 if status == "success" else 1


def command_download(args: argparse.Namespace) -> int:
    project_root = detect_project(args.project)
    run_dir = resolve_existing_run_dir(project_root, args.run_dir)
    layout = Layout(project_root, run_dir)
    server = server_from_run(layout, args.server)
    artifacts = download_artifacts(layout, server)
    payload = run_payload(project_root, run_dir)
    payload.update({
        "server": server,
        "artifact_count": len(artifacts),
        "artifacts_dir": path_payload(layout.artifacts_dir),
        "artifacts": artifacts,
    })
    print_summary("download", payload)
    return 0


def command_build(args: argparse.Namespace) -> int:
    project_root = detect_project(args.project)
    run_dir = create_run_dir(project_root)
    layout = Layout(project_root, run_dir)

    manifest = create_package(layout)
    upload = upload_package(layout, args.server)
    final = poll_build(layout, args.server, args.interval, args.timeout)
    artifacts: list[dict] = []
    if final.get("status") == "success":
        artifacts = download_artifacts(layout, args.server)

    payload = run_payload(project_root, run_dir)
    payload.update({
        "server": args.server,
        "zip_path": path_payload(layout.zip_path),
        "zip_size_bytes": manifest["zip_size_bytes"],
        "job_id": upload["job_id"],
        "status": final.get("status"),
        "status_path": path_payload(layout.status_path),
        "status_history_path": path_payload(layout.status_history_path),
        "log_path": final.get("saved_log_path") or path_payload(layout.log_path),
        "artifact_count": len(artifacts),
        "artifacts_dir": path_payload(layout.artifacts_dir),
        "artifacts": artifacts,
    })
    print_summary("build", payload)
    return 0 if final.get("status") == "success" else 1


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project", nargs="?", type=Path, default=Path.cwd(),
                        help="鸿蒙项目根目录，或包含唯一鸿蒙项目的父目录")
    parser.add_argument("--server", default=os.environ.get("HARMONY_BUILD_SERVER", DEFAULT_SERVER),
                        help=f"构建服务地址（默认：{DEFAULT_SERVER}，也可用 HARMONY_BUILD_SERVER）")


def add_run_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-dir", type=Path, required=True,
                        help="已有的 .xsj-build/runs/<时间戳> 运行目录")


def add_poll_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--interval", type=int, default=DEFAULT_POLL_INTERVAL,
                        help=f"轮询间隔秒数（默认：{DEFAULT_POLL_INTERVAL}）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_POLL_TIMEOUT,
                        help=f"轮询超时秒数（默认：{DEFAULT_POLL_TIMEOUT}）")


def build_parser() -> argparse.ArgumentParser:
    install_argparse_translations()
    parser = ChineseArgumentParser(
        description="通过 xsj-build-pipeline 打包和构建鸿蒙项目",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=ChineseArgumentParser)

    detect = subparsers.add_parser("detect", help="检测鸿蒙项目根目录")
    detect.add_argument("project", nargs="?", type=Path, default=Path.cwd(),
                        help="鸿蒙项目根目录，或包含唯一鸿蒙项目的父目录")
    detect.set_defaults(func=command_detect)

    package = subparsers.add_parser("package", help="在 .xsj-build 中创建项目 zip")
    package.add_argument("project", nargs="?", type=Path, default=Path.cwd(),
                         help="鸿蒙项目根目录，或包含唯一鸿蒙项目的父目录")
    package.set_defaults(func=command_package)

    submit = subparsers.add_parser("submit", help="上传已有的打包 zip")
    add_common_arguments(submit)
    add_run_argument(submit)
    submit.set_defaults(func=command_submit)

    poll = subparsers.add_parser("poll", help="轮询已提交的构建")
    add_common_arguments(poll)
    add_run_argument(poll)
    add_poll_arguments(poll)
    poll.set_defaults(func=command_poll)

    download = subparsers.add_parser("download", help="下载成功构建的产物")
    add_common_arguments(download)
    add_run_argument(download)
    download.set_defaults(func=command_download)

    build = subparsers.add_parser("build", help="执行打包、提交、轮询和下载完整流程")
    add_common_arguments(build)
    add_poll_arguments(build)
    build.set_defaults(func=command_build)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if getattr(args, "interval", DEFAULT_POLL_INTERVAL) < 1:
            raise SystemExit("--interval 必须至少为 1")
        if getattr(args, "timeout", DEFAULT_POLL_TIMEOUT) < 1:
            raise SystemExit("--timeout 必须至少为 1")
        return int(args.func(args))
    except SystemExit as exc:
        if isinstance(exc.code, str):
            eprint(exc.code)
            return 2
        return int(exc.code or 0)


if __name__ == "__main__":
    raise SystemExit(main())
