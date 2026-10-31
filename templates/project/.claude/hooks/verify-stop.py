#!/usr/bin/env python3
"""Bounded Maven compile feedback for Claude Code; CI remains the merge gate."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile


def verify(project_root, timeout=90):
    """Return an error message, or None on success. Never execute input as code."""
    wrapper = project_root / "mvnw"
    if not (project_root / "pom.xml").is_file() or not wrapper.is_file():
        return "项目根目录缺少 pom.xml 或 mvnw；请按项目构建方式调整 Stop hook。"
    if not os.access(wrapper, os.X_OK):
        return "mvnw 不可执行；请检查并恢复 Maven Wrapper 的执行权限。"

    # Bound memory use even if Maven emits a large log. Only return its tail.
    with tempfile.TemporaryFile() as log:
        try:
            process = subprocess.Popen(
                [str(wrapper), "-B", "-q", "compile"],
                cwd=project_root,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            return f"无法启动 Maven Wrapper：{exc}"

        timed_out = False
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Stop descendants too, not just the wrapper shell (macOS/Linux).
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            code = process.wait()

        log.seek(0, os.SEEK_END)
        log.seek(max(0, log.tell() - 8000))
        tail = log.read().decode("utf-8", errors="replace").strip()

    if timed_out:
        return f"编译在 {timeout} 秒内未完成；请手动验证并按项目耗时调整超时。\n{tail}"
    if code != 0:
        return f"Maven 编译失败（退出码 {code}）。请修复或明确报告环境阻碍。\n{tail}"
    return None


def main():
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict) or type(event.get("stop_hook_active", False)) is not bool:
            raise ValueError("Stop 输入须为对象，stop_hook_active 须为布尔值")
    except (ValueError, TypeError) as exc:
        print(f"Stop hook 输入无效，未执行验证：{exc}", file=sys.stderr)
        return 1

    # Anchor to the copied script even when the session cd's into a module.
    error = verify(Path(__file__).resolve().parents[2])
    if error is None:
        return 0
    if event.get("stop_hook_active", False):
        # Report a second failure instead of looping or claiming success.
        print(json.dumps({"continue": False, "stopReason": error}, ensure_ascii=False))
        return 0
    print(error, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
