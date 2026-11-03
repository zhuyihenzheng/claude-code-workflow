import functools
import http.server
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'templates/project/scripts/htmx-check.mjs'
NODE = shutil.which('node')


def playwright_available():
    if not NODE:
        return False
    probe = ("import('node:module').then(m => m.createRequire(process.argv[1]).resolve('playwright'))"
             ".catch(() => process.exit(1))")
    return subprocess.run([NODE, '-e', probe, str(SCRIPT)], capture_output=True, timeout=30).returncode == 0


# Pages emulate what htmx does (swap / dispatch error events) so the checker's
# verdicts can be tested without downloading the htmx library.
PAGE = '''<!doctype html><meta charset="utf-8"><title>t</title>
<script>{htmx}</script>
<input id="name"><button id="go">go</button><div id="target">initial</div>
<script>
document.getElementById('go').addEventListener('click', () => setTimeout(() => {{ {action} }}, 50));
</script>'''
HTMX = 'window.htmx = {};'
SWAP = "document.getElementById('target').innerHTML = '保存しました ' + document.getElementById('name').value;"
PAGES = {
    'ok.html': PAGE.format(htmx=HTMX, action=SWAP),
    'no-swap.html': PAGE.format(htmx=HTMX, action=''),
    'target-error.html': PAGE.format(htmx=HTMX, action=(
        "document.getElementById('go').dispatchEvent(new CustomEvent('htmx:targetError', {bubbles: true}));")),
    'console-error.html': PAGE.format(htmx=HTMX, action=SWAP + " console.error('boom');"),
    'login.html': PAGE.format(htmx=HTMX, action="document.getElementById('target').innerHTML = 'ログイン画面';"),
    'no-htmx.html': PAGE.format(htmx='', action=SWAP),
    'preexisting.html': PAGE.format(htmx=HTMX, action='').replace('>initial<', '>保存しました<'),
    'same-render.html': PAGE.format(htmx=HTMX, action=(
        "document.getElementById('target').dispatchEvent(new CustomEvent('htmx:afterSwap', {bubbles: true}));"
    )).replace('>initial<', '>保存しました<'),
}


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


AVAILABLE = playwright_available()
if not AVAILABLE and os.environ.get('HTMX_CHECK_REQUIRED') == '1':
    raise RuntimeError('HTMX_CHECK_REQUIRED=1 but node + playwright are not available')


@unittest.skipUnless(AVAILABLE, 'node + playwright not available')
class HtmxCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        for name, html in PAGES.items():
            (cls.root / name).write_text(html, encoding='utf-8')
        handler = functools.partial(QuietHandler, directory=str(cls.root))
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}/'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def check(self, page, *extra):
        args = [NODE, str(SCRIPT), '--url', self.base + page, '--click', '#go', '--expect', '#target',
                '--timeout', '2000', *extra]
        return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=60)

    def test_successful_swap_passes_and_saves_screenshot(self):
        shot = self.root / 'shots/ok.png'
        result = self.check('ok.html', '--fill', '#name=太郎', '--contains', '保存しました 太郎',
                            '--absent', 'ログイン', '--screenshot', str(shot))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('OK', result.stdout)
        self.assertTrue(shot.is_file())

    def test_any_change_is_enough_without_contains(self):
        self.assertEqual(self.check('ok.html').returncode, 0)

    def test_missing_swap_fails(self):
        result = self.check('no-swap.html')
        self.assertEqual(result.returncode, 1)
        self.assertIn('置換されなかった', result.stderr)

    def test_htmx_error_event_fails_even_without_wait(self):
        result = self.check('target-error.html', '--timeout', '500')
        self.assertEqual(result.returncode, 1)
        self.assertIn('htmx:targetError on #go', result.stderr)

    def test_console_error_fails_unless_allowed(self):
        self.assertEqual(self.check('console-error.html').returncode, 1)
        self.assertEqual(self.check('console-error.html', '--allow-console-error', 'boom').returncode, 0)

    def test_login_page_in_fragment_fails(self):
        result = self.check('login.html', '--absent', 'ログイン')
        self.assertEqual(result.returncode, 1)
        self.assertIn('ログイン', result.stderr)

    def test_text_already_present_without_swap_fails(self):
        result = self.check('preexisting.html', '--contains', '保存しました')
        self.assertEqual(result.returncode, 1)
        self.assertIn('置換されず', result.stderr)

    def test_identical_rerender_reported_by_after_swap_passes(self):
        self.assertEqual(self.check('same-render.html', '--contains', '保存しました').returncode, 0)

    def test_missing_control_is_ng_not_incomplete(self):
        result = self.check('ok.html', '--fill', '#missing=x')
        self.assertEqual(result.returncode, 1)
        self.assertIn('#missing', result.stderr)

    def test_page_without_htmx_fails(self):
        result = self.check('no-htmx.html')
        self.assertEqual(result.returncode, 1)
        self.assertIn('window.htmx', result.stderr)

    def test_unreachable_server_and_bad_args_are_incomplete_not_failures(self):
        closed = [NODE, str(SCRIPT), '--url', 'http://127.0.0.1:9/', '--click', '#go', '--expect', '#t']
        result = subprocess.run(closed, capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 2)
        self.assertIn('検証未完了', result.stderr)
        result = subprocess.run([NODE, str(SCRIPT), '--url', self.base], capture_output=True, text=True,
                                encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
