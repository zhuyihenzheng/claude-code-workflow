import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'templates/project/.claude/hooks/verify-stop.py'
spec = importlib.util.spec_from_file_location('verify_stop', SOURCE)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


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

    def wrapper(self, body):
        p = self.root / 'mvnw'
        p.write_text('#!/bin/sh\n' + body + '\n')
        p.chmod(0o755)

    def run_hook(self, payload=None, cwd=None):
        return subprocess.run(
            [sys.executable, str(self.script)],
            input=json.dumps({'stop_hook_active': False} if payload is None else payload),
            text=True, capture_output=True, cwd=cwd or self.root, timeout=5,
        )

    def test_compile_success(self):
        result = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')

    def test_failure_blocks_and_includes_maven_diagnostics(self):
        self.wrapper('echo "cannot find symbol" >&2\nexit 1')
        result = self.run_hook()
        self.assertEqual(result.returncode, 2)
        self.assertIn('cannot find symbol', result.stderr)

    def test_repeated_failure_stops_and_reports_failure(self):
        self.wrapper('echo "compile broken" >&2\nexit 1')
        result = self.run_hook({'stop_hook_active': True})
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertIs(output['continue'], False)
        self.assertIn('compile broken', output['stopReason'])

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

    def test_missing_wrapper(self):
        (self.root / 'mvnw').unlink()
        result = self.run_hook()
        self.assertEqual(result.returncode, 2)
        self.assertIn('mvnw', result.stderr)

    def test_missing_pom_does_not_execute_wrapper(self):
        (self.root / 'pom.xml').unlink()
        self.wrapper('touch unexpected')
        result = self.run_hook()
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / 'unexpected').exists())

    def test_non_executable_wrapper(self):
        (self.root / 'mvnw').chmod(0o644)
        self.assertEqual(self.run_hook().returncode, 2)

    def test_invalid_payloads_do_not_run_build(self):
        self.wrapper('touch unexpected')
        for payload in [[], 'bad', {'stop_hook_active': 'false'}]:
            with self.subTest(payload=payload):
                self.assertEqual(self.run_hook(payload).returncode, 1)
        self.assertFalse((self.root / 'unexpected').exists())

    def test_malformed_json(self):
        result = subprocess.run([sys.executable, str(self.script)], input='{',
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn('输入无效', result.stderr)

    def test_timeout_kills_wrapper_children(self):
        self.wrapper('(sleep 0.4; touch escaped) &\nwait')
        error = hook.verify(self.root, timeout=0.05)
        self.assertIn('未完成', error)
        time.sleep(0.5)
        self.assertFalse((self.root / 'escaped').exists())

    def test_large_log_keeps_useful_tail(self):
        self.wrapper('i=0; while [ "$i" -lt 2000 ]; do echo long-build-message; i=$((i+1)); done\necho FINAL-ERROR\nexit 1')
        result = self.run_hook()
        self.assertEqual(result.returncode, 2)
        self.assertIn('FINAL-ERROR', result.stderr)
        self.assertLess(len(result.stderr), 8500)

    def test_wrapper_launch_error_is_reported(self):
        (self.root / 'mvnw').write_text('#!/nonexistent-interpreter\n')
        self.assertIn('无法启动', hook.verify(self.root))


if __name__ == '__main__':
    unittest.main()
