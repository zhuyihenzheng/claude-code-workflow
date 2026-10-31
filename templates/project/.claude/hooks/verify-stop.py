#!/usr/bin/env python3
"""Bounded Maven compile feedback for Claude Code; CI remains the merge gate."""

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
from typing import NamedTuple


class Verification(NamedTuple):
    status: str  # passed, compilation_failed, or unavailable (never a success claim)
    message: str = ""


def project_root():
    # Preserve the invocation path when hooks/ is symlinked to a shared checkout.
    configured = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(configured).absolute() if configured else Path(__file__).absolute().parents[2]


def kill_build(process):
    if process is not None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def verify(root, timeout=90):
    """Only explicit Java compilation diagnostics may request another model turn."""
    wrapper = root / "mvnw"
    if not (root / "pom.xml").is_file() or not wrapper.is_file():
        return Verification("unavailable", "项目根目录缺少 pom.xml 或 mvnw；请按项目构建方式调整 Stop hook。")
    if not os.access(wrapper, os.X_OK):
        return Verification("unavailable", "mvnw 不可执行；请人工检查 Maven Wrapper 的执行权限。")

    process = None
    interrupted = None
    handlers = {}

    def cancel(signum, _frame):
        nonlocal interrupted
        interrupted = signum
        # If the signal arrives during Popen, remember it and clean up after spawn.
        kill_build(process)

    # Own the child session so timeout/TERM/INT/HUP can terminate all descendants.
    # SIGKILL cannot be handled; the caller must kill the process tree in that case.
    with tempfile.TemporaryFile() as log:
        try:
            for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                handlers[signum] = signal.signal(signum, cancel)
            if interrupted is not None:
                return Verification("unavailable", "编译检查已被中断。")
            try:
                process = subprocess.Popen(
                    [str(wrapper), "-B", "-q", "compile"],
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as exc:
                return Verification("unavailable", f"无法启动 Maven Wrapper：{exc}")

            if interrupted is not None:
                kill_build(process)
            timed_out = False
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                kill_build(process)
                code = process.wait()

            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - 8000))
            tail = log.read().decode("utf-8", errors="replace").strip()
        finally:
            # Also clean up on unexpected errors and wrapper exits with children alive.
            kill_build(process)
            if process is not None:
                process.wait()
            for signum, handler in handlers.items():
                signal.signal(signum, handler)

    if interrupted is not None:
        return Verification("unavailable", f"编译检查被信号 {interrupted} 中断，已清理 Maven 进程组。")
    if timed_out:
        return Verification("unavailable", f"编译在 {timeout} 秒内未完成；请手动验证并按项目耗时调整超时。\n{tail}")
    if code == 0:
        return Verification("passed")
    # Maven uses nonzero exits for dependency/network/JDK/plugin failures too.
    # Be conservative: an unrecognized diagnostic is incomplete validation, not
    # proof of a source error. The real build/CI still must pass before merging.
    compiler_goal = re.search(r"maven-compiler-plugin:[^\s:]+:compile\b", tail)
    if compiler_goal and re.search(r"Compilation failure", tail, re.IGNORECASE):
        return Verification("compilation_failed", f"Java 编译失败（退出码 {code}）。请修复编译诊断，不要修改 hook 绕过检查。\n{tail}")
    return Verification("unavailable", f"Maven 非零退出（{code}），未确认是源码编译错误；请人工检查环境/依赖与日志。\n{tail}")


def main():
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict) or type(event.get("stop_hook_active", False)) is not bool:
            raise ValueError("Stop 输入须为对象，stop_hook_active 须为布尔值")
    except (ValueError, TypeError) as exc:
        print(f"Stop hook 输入无效，未执行验证：{exc}", file=sys.stderr)
        return 1

    result = verify(project_root())
    if result.status == "passed":
        return 0
    if result.status == "unavailable":
        # Warning to the user, without an additional model turn or success claim.
        print(json.dumps({"systemMessage": "编译验证未完成；本次不阻断 Stop。" + result.message}, ensure_ascii=False))
        return 0
    if event.get("stop_hook_active", False):
        print(json.dumps({"continue": False, "stopReason": result.message}, ensure_ascii=False))
        return 0
    print(result.message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
