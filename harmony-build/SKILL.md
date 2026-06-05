---
name: harmony-build
description: 用 xsj-build-pipeline 服务检测、打包、提交、轮询和下载鸿蒙项目构建产物。只要用户提到识别鸿蒙项目、打包鸿蒙项目、提交到 Harmony 构建服务、轮询构建、下载产物，或只想跑其中一个阶段，就使用这个 skill。优先调用内置脚本，不要手写零散 API 或路径逻辑，避免项目判断、输出目录和数据保留规则不一致。
---

# Harmony Build

这个 skill 用来打包本地鸿蒙项目，并可选择提交到 xsj-build-pipeline 构建服务。

内置脚本是唯一可信入口。让脚本负责检测项目、创建输出目录、调用 API、保存日志和下载产物，减少 agent 自己猜路径或拼接口导致的错误。

## 核心规则

- 所有构建相关数据都放在鸿蒙项目根目录下的 `.xsj-build/`。
- 绝对不要删除用户数据。不要删除 `.xsj-build`、旧运行目录、压缩包、日志、状态文件或构建产物。
- 不要运行 `rm -rf .xsj-build`、不要清空旧 run、不要覆盖旧产物、不要为了“保持干净”替用户清理数据。清理只能由用户手动决定并执行。
- 打包或构建前，先确认目标目录是鸿蒙项目。
- 默认每次创建新的时间戳运行目录：
  `.xsj-build/runs/YYYYMMDD-HHMMSS[-N]/`
- 本地打包文件和远端构建完成后的产物都放在同一个运行目录里。
- 不要在推理里写死服务地址。使用脚本默认值、`HARMONY_BUILD_SERVER`，或用户传入的 `--server`。

## 项目检测

只有当脚本能找到一个目录同时包含以下文件时，才认为它是鸿蒙项目：

- `hvigorfile.ts`
- `build-profile.json5`
- `oh-package.json5`

用户可以传入项目根目录，也可以传入只包含一个鸿蒙项目的父目录。如果找到多个候选项目，脚本会失败并列出候选目录；不要替用户猜，应该让用户指定其中一个目录。

## 输出目录

每次运行只写入自己的运行目录：

```text
.xsj-build/
  runs/
    20260605-143012/
      package/
        project.zip
        manifest.json
      remote/
        upload.json
        status.json
        status_history.jsonl
        build.log
      artifacts/
        ...
```

脚本会打印 `project_root`、`run_dir` 和相关文件路径。回复用户时要报告这些路径。

构建结束后，只提示用户本次运行目录和产物目录。不要建议自动删除这些目录；最多可以说明“历史数据已保留，后续如需清理请手动处理”。

## 脚本命令

可以从任意目录运行：

```bash
python3 <skill-dir>/scripts/harmony_build.py <command> [project-or-parent-dir] [options]
```

命令：

- `detect`：只检测鸿蒙项目根目录并打印路径。
- `package`：只创建 `.xsj-build/runs/<时间戳>/package/project.zip` 和 `manifest.json`。
- `submit`：上传已有运行目录里的打包 zip。需要 `--run-dir`。
- `poll`：轮询已提交的构建。需要 `--run-dir`。
- `download`：下载成功构建的产物。需要 `--run-dir`。
- `build`：依次执行 `package`、`submit`、`poll`、`download`。

`submit` 会拒绝覆盖已有的 `remote/upload.json`。如果用户想再次创建远端构建任务，应重新运行 `package` 或 `build`，让脚本创建新的时间戳运行目录。

常用参数：

- `--server URL`：本次调用使用的构建服务地址。
- `HARMONY_BUILD_SERVER`：构建服务地址的环境变量默认值。
- `--run-dir DIR`：复用已有运行目录，供 `submit`、`poll` 或 `download` 使用。
- `--timeout SECONDS`：轮询超时时间，默认 1800 秒。
- `--interval SECONDS`：轮询间隔，默认 5 秒。

示例：

```bash
# 只检测项目。
python3 <skill-dir>/scripts/harmony_build.py detect .

# 只打包，适合测试 zip 内容和大小。
python3 <skill-dir>/scripts/harmony_build.py package .

# 完整远端构建。
python3 <skill-dir>/scripts/harmony_build.py build . --server http://127.0.0.1:8080

# 继续之前已经打包的运行目录。
python3 <skill-dir>/scripts/harmony_build.py submit . --run-dir .xsj-build/runs/20260605-143012
python3 <skill-dir>/scripts/harmony_build.py poll . --run-dir .xsj-build/runs/20260605-143012
python3 <skill-dir>/scripts/harmony_build.py download . --run-dir .xsj-build/runs/20260605-143012
```

## 工作流

1. 用户只想判断项目时，运行 `detect`。
2. 用户只想打包或检查压缩包时，运行 `package`。
3. 用户想完整构建时，运行 `build`。
4. 用户想继续之前的运行时，配合 `--run-dir` 使用 `submit`、`poll` 或 `download`。

执行后需要总结：

- 检测到的 `project_root`
- `run_dir`
- 如果生成了压缩包，说明压缩包路径和大小
- 如果提交到远端，说明 `job_id` 和状态
- 如果下载了产物，列出产物路径
- 如果构建失败或超时，说明日志路径
- 如果执行过轮询，说明状态历史文件路径
- 明确说明历史数据没有被删除，本次数据保留在 `run_dir`

## 失败处理

- 如果项目检测失败，直接说明目录不是鸿蒙项目，或列出多个候选目录。
- 如果上传失败，说明 HTTP 状态和错误信息，并提示 `remote/upload.json` 路径。
- 如果轮询结果是 `failed`、`error` 或 `timeout`，说明最终状态，并总结 `remote/build.log` 的关键错误。
- 不要为了重试而删除或覆盖旧数据。重试应创建新的 `package`/`build` 运行目录，或者只用同一个 `--run-dir` 继续远端步骤。
- 即使构建成功，也不要清理打包目录、日志目录或旧产物目录。只报告目录位置，让用户自己决定后续处理。
