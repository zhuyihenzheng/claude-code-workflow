import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'templates/project/.claude/hooks/verify-stop.py'
spec = importlib.util.spec_from_file_location('verify_stop', SOURCE)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)
COMPILE_ERROR = '[ERROR] Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin:3.13.0:compile (default-compile) on project demo: Compilation failure'


class StopHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='workflow project ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / '.claude/hooks/verify-stop.py'
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SOURCE, self.script)
        (self.root / 'pom.xml').write_text('<project/>')
        self.wrapper('exit 0')
        self.env = dict(os.environ)
        self.env.pop('CLAUDE_PROJECT_DIR', None)

    def wrapper(self, body):
        p = self.root / 'mvnw'
        p.write_text('#!/bin/sh\n' + body + '\n')
        p.chmod(0o755)

    def compile_failure(self, before=''):
        self.wrapper(before + '\necho "' + COMPILE_ERROR + '" >&2\necho "cannot find symbol" >&2\nexit 1')

    def run_hook(self, payload=None, cwd=None):
        return subprocess.run(
            [sys.executable, str(self.script)],
            input=json.dumps({'stop_hook_active': False} if payload is None else payload),
            text=True, capture_output=True, cwd=cwd or self.root, env=self.env, timeout=5,
        )

    def assert_unavailable(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(set(output), {'systemMessage'})
        self.assertIn('验证未完成', output['systemMessage'])
        return output['systemMessage']

    def test_compile_success(self):
        result = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')

    def test_failure_blocks_and_includes_maven_diagnostics(self):
        self.compile_failure()
        result = self.run_hook()
        self.assertEqual(result.returncode, 2)
        self.assertIn('cannot find symbol', result.stderr)

    def test_repeated_failure_stops_and_reports_failure(self):
        self.compile_failure()
        result = self.run_hook({'stop_hook_active': True})
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertIs(output['continue'], False)
        self.assertIn('cannot find symbol', output['stopReason'])

    def test_repaired_retry_is_verified(self):
        self.wrapper('touch checked\nexit 0')
        result = self.run_hook({'stop_hook_active': True})
        self.assertEqual(result.returncode, 0)
        self.assertTrue((self.root / 'checked').exists())
        self.assertEqual(result.stdout, '')

    def test_subdirectory_and_spaces_use_project_root(self):
        module = self.root / 'module with spaces'
        module.mkdir()
        self.wrapper('pwd > actual-cwd\nprintf "%s\\n" "$@" > actual-args')
        result = self.run_hook({'cwd': str(module)}, cwd=module)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'actual-cwd').read_text().strip(), str(self.root.resolve()))
        self.assertEqual((self.root / 'actual-args').read_text().splitlines(), ['-B', '-q', 'compile'])

    def test_environment_root_takes_priority(self):
        other = self.root / 'actual project'
        other.mkdir()
        (other / 'pom.xml').write_text('<project/>')
        shutil.copyfile(self.root / 'mvnw', other / 'mvnw')
        (other / 'mvnw').write_text('#!/bin/sh\ntouch checked\n')
        (other / 'mvnw').chmod(0o755)
        self.env['CLAUDE_PROJECT_DIR'] = str(other)
        result = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((other / 'checked').exists())
        self.assertFalse((self.root / 'checked').exists())

    def test_symlinked_hook_preserves_invocation_project(self):
        shared = self.root / 'shared hooks'
        self.script.parent.rename(shared)
        self.script.parent.symlink_to(shared, target_is_directory=True)
        self.wrapper('touch checked')
        for configured in (False, True):
            with self.subTest(configured=configured):
                if configured:
                    self.env['CLAUDE_PROJECT_DIR'] = str(self.root)
                result = self.run_hook()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((self.root / 'checked').exists())
                (self.root / 'checked').unlink()

    def test_missing_wrapper(self):
        (self.root / 'mvnw').unlink()
        self.assertIn('mvnw', self.assert_unavailable(self.run_hook()))

    def test_missing_pom_does_not_execute_wrapper(self):
        (self.root / 'pom.xml').unlink()
        self.wrapper('touch unexpected')
        self.assert_unavailable(self.run_hook())
        self.assertFalse((self.root / 'unexpected').exists())

    def test_non_executable_wrapper(self):
        (self.root / 'mvnw').chmod(0o644)
        self.assert_unavailable(self.run_hook())

    def test_environment_and_unrecognized_failures_do_not_request_retry(self):
        for diagnostic in ('JAVA_HOME is not defined correctly', 'Could not resolve dependencies',
                           'maven-compiler-plugin:3.13.0:compile: invalid target release: 99',
                           'unknown build error'):
            with self.subTest(diagnostic=diagnostic):
                self.wrapper('echo "' + diagnostic + '" >&2\nexit 1')
                for active in (False, True):
                    self.assertIn(diagnostic, self.assert_unavailable(self.run_hook({'stop_hook_active': active})))

    def test_invalid_payloads_do_not_run_build(self):
        self.wrapper('touch unexpected')
        for payload in [[], 'bad', {'stop_hook_active': 'false'}]:
            with self.subTest(payload=payload):
                self.assertEqual(self.run_hook(payload).returncode, 1)
        self.assertFalse((self.root / 'unexpected').exists())

    def test_malformed_json(self):
        result = subprocess.run([sys.executable, str(self.script)], input='{',
                                text=True, capture_output=True, env=self.env, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn('输入无效', result.stderr)

    def test_timeout_kills_wrapper_children_and_warns_without_retry(self):
        self.wrapper('(sleep 0.4; touch escaped) &\nwait')
        result = hook.verify(self.root, timeout=0.05)
        self.assertEqual(result.status, 'unavailable')
        self.assertIn('未完成', result.message)
        output = io.StringIO()
        with patch.object(hook, 'verify', return_value=result), patch('sys.stdin', io.StringIO('{}')), contextlib.redirect_stdout(output):
            self.assertEqual(hook.main(), 0)
        self.assertEqual(set(json.loads(output.getvalue())), {'systemMessage'})
        time.sleep(0.5)
        self.assertFalse((self.root / 'escaped').exists())

    def test_signals_clean_up_wrapper_and_children(self):
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            with self.subTest(signal=signum):
                self.wrapper('(touch ready; sleep 0.5; touch escaped) &\nwait')
                proc = subprocess.Popen([sys.executable, str(self.script)], cwd=self.root, env=self.env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    proc.stdin.write('{}')
                    proc.stdin.close()
                    proc.stdin = None
                    deadline = time.monotonic() + 3
                    while not (self.root / 'ready').exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue((self.root / 'ready').exists(), 'wrapper never became ready')
                    proc.send_signal(signum)
                    out, err = proc.communicate(timeout=3)
                    self.assertEqual(proc.returncode, 0, err)
                    self.assertIn('已清理', json.loads(out)['systemMessage'])
                    time.sleep(0.6)
                    self.assertFalse((self.root / 'escaped').exists())
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                        proc.communicate(timeout=3)
                (self.root / 'ready').unlink(missing_ok=True)

    def test_large_log_keeps_useful_tail(self):
        self.compile_failure('i=0; while [ "$i" -lt 2000 ]; do echo long-build-message; i=$((i+1)); done')
        result = self.run_hook()
        self.assertEqual(result.returncode, 2)
        self.assertIn('cannot find symbol', result.stderr)
        self.assertLess(len(result.stderr), 8500)

    def test_wrapper_launch_error_is_reported(self):
        (self.root / 'mvnw').write_text('#!/nonexistent-interpreter\n')
        result = hook.verify(self.root)
        self.assertEqual(result.status, 'unavailable')
        self.assertIn('无法启动', result.message)


if __name__ == '__main__':
    unittest.main()
