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
    # Never signal a group after reaping its leader: that PGID may be reused.
    if process is not None and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # The group may disappear or become inaccessible while exiting.
            pass


def verify(root, timeout=90):
    """Only explicit Java compilation diagnostics may request another model turn."""
    wrapper = root / "mvnw"
    if not (root / "pom.xml").is_file() or not wrapper.is_file():
        return Verification("unavailable", "プロジェクトルートに pom.xml または mvnw がありません。プロジェクトのビルド方式に合わせて Stop hook を調整してください。")
    if not os.access(wrapper, os.X_OK):
        return Verification("unavailable", "mvnw を実行できません。Maven Wrapper の実行権限を確認してください。")

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
                return Verification("unavailable", "コンパイルの確認が中断されました。")
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
                return Verification("unavailable", f"Maven Wrapper を起動できません：{exc}")

            if interrupted is not None:
                kill_build(process)
            timed_out = False
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                kill_build(process)
                code = process.wait()

            # Classify the complete output; only presentation uses a bounded tail.
            compiler_goal = compilation_failure = unsupported_release = False
            log.seek(0)
            for raw_line in log:
                line = raw_line.decode("utf-8", errors="replace")
                compiler_goal |= bool(re.search(r"maven-compiler-plugin:[^\s:]+:compile\b", line))
                compilation_failure |= bool(re.search(r"Compilation failure", line, re.IGNORECASE))
                unsupported_release |= bool(re.search(
                    r"invalid (?:target|source) release|release version \S+ not supported", line, re.IGNORECASE,
                ))
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - 8000))
            tail = log.read().decode("utf-8", errors="replace").strip()
        finally:
            # Clean up on unexpected errors, but never signal a reaped group.
            kill_build(process)
            if process is not None:
                process.wait()
            for signum, handler in handlers.items():
                signal.signal(signum, handler)

    if interrupted is not None:
        return Verification("unavailable", f"コンパイルの確認がシグナル {interrupted} により中断されました。Maven プロセスグループの終了処理を行いました。")
    if timed_out:
        return Verification("unavailable", f"コンパイルが {timeout} 秒以内に完了しませんでした。プロジェクトルートで ./mvnw -B -q compile を実行してログを確認し、所要時間に応じてタイムアウトを調整してください。")
    if code == 0:
        return Verification("passed")
    # Maven uses nonzero exits for dependency/network/JDK/plugin failures too.
    # Be conservative: an unrecognized diagnostic is incomplete validation, not
    # proof of a source error. The real build/CI still must pass before merging.
    if unsupported_release:
        return Verification("unavailable", "JDK がプロジェクトで指定された Java release に対応していません。JDK/JAVA_HOME を確認し、プロジェクトルートで ./mvnw -B -q compile を実行してログを確認してください。")
    if compiler_goal and compilation_failure:
        return Verification("compilation_failed", f"Java のコンパイルに失敗しました（終了コード {code}）。コンパイルエラーを修正してください。検証を回避するために hook を変更しないでください。\n{tail}")
    return Verification("unavailable", f"Maven が非ゼロの終了コード（{code}）で終了しました。ソースコードのコンパイルエラーかどうかは確認できていません。環境／依存関係を確認し、プロジェクトルートで ./mvnw -B -q compile を実行してログを確認してください。")


def main():
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict) or type(event.get("stop_hook_active", False)) is not bool:
            raise ValueError("Stop の入力はオブジェクト、stop_hook_active は真偽値である必要があります")
    except (ValueError, TypeError) as exc:
        print(f"Stop hook の入力が不正なため、検証を実行しませんでした：{exc}", file=sys.stderr)
        return 1

    result = verify(project_root())
    if result.status == "passed":
        return 0
    if result.status == "unavailable":
        # Warning to the user, without an additional model turn or success claim.
        print(json.dumps({"systemMessage": "コンパイルの検証は完了していません。今回は Stop をブロックしません。" + result.message}, ensure_ascii=False))
        return 0
    if event.get("stop_hook_active", False):
        print(json.dumps({"continue": False, "stopReason": result.message}, ensure_ascii=False))
        return 0
    print(result.message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
