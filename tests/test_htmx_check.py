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
    'xhr-422.html': PAGE.format(htmx=HTMX, action=(
        "fetch('/invalid', {method: 'POST'}).then(() => { document.getElementById('target').textContent = '入力エラー'; });")),
    'preexisting.html': PAGE.format(htmx=HTMX, action='').replace('>initial<', '>保存しました<'),
    'same-render.html': PAGE.format(htmx=HTMX, action=(
        "document.getElementById('target').dispatchEvent(new CustomEvent('htmx:afterSwap', {bubbles: true}));"
    )).replace('>initial<', '>保存しました<'),
}


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.send_response(422)
        self.send_header('Content-Length', '0')
        self.end_headers()


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

    def test_http_status_console_log_is_not_an_error(self):
        result = self.check('xhr-422.html', '--contains', '入力エラー')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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


def find_htmx():
    candidates = [os.environ.get('HTMX_JS', ''), str(ROOT / 'node_modules/htmx.org/dist/htmx.min.js')]
    return next((Path(c) for c in candidates if c and Path(c).is_file()), None)


HTMX_JS = find_htmx()
if HTMX_JS is None and os.environ.get('HTMX_CHECK_REQUIRED') == '1':
    raise RuntimeError('HTMX_CHECK_REQUIRED=1 but node_modules/htmx.org (or HTMX_JS) is missing')

# 422 config copied from docs/04 so the documented snippet is exercised against real htmx.
CONFIG_422 = ('<meta name="htmx-config" content=\'{"responseHandling":['
              '{"code":"204","swap":false},{"code":"[23]..","swap":true},'
              '{"code":"422","swap":true,"error":false},'
              '{"code":"[45]..","swap":false,"error":true},{"code":"...","swap":false}]}\'>')
REAL_PAGE = ('<!doctype html><html><head><meta charset="utf-8">{config}<script src="/htmx.js"></script></head>'
             '<body><form hx-post="{endpoint}" hx-target="{target}"><input id="name" name="name">'
             '<button id="go">go</button></form><div id="target">initial</div></body></html>')
REAL_PAGES = {
    'ok.html': REAL_PAGE.format(config='', endpoint='/ok', target='#target'),
    'missing-target.html': REAL_PAGE.format(config='', endpoint='/ok', target='#nope'),
    'invalid-default.html': REAL_PAGE.format(config='', endpoint='/invalid', target='#target'),
    'invalid-configured.html': REAL_PAGE.format(config=CONFIG_422, endpoint='/invalid', target='#target'),
    'login.html': REAL_PAGE.format(config='', endpoint='/login', target='#target'),
}
POST_RESPONSES = {
    '/ok': (200, '<p>登録しました</p>'),
    '/invalid': (422, '<p class="error">入力エラー</p>'),
    '/login': (200, '<html><body><h1>ログイン</h1></body></html>'),
}


class FakeAppHandler(QuietHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length') or 0))
        status, body = POST_RESPONSES.get(self.path, (404, 'not found'))
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@unittest.skipUnless(AVAILABLE and HTMX_JS, 'node + playwright + htmx.org not available')
class RealHtmxTests(unittest.TestCase):
    """Run the checker against the real htmx library and a fake server-rendered app."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        shutil.copyfile(HTMX_JS, root / 'htmx.js')
        for name, html in REAL_PAGES.items():
            (root / name).write_text(html, encoding='utf-8')
        handler = functools.partial(FakeAppHandler, directory=str(root))
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}/'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def check(self, page, *extra):
        args = [NODE, str(SCRIPT), '--url', self.base + page, '--fill', '#name=太郎', '--click', '#go',
                '--expect', '#target', '--timeout', '3000', *extra]
        return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=60)

    def test_real_swap_passes(self):
        result = self.check('ok.html', '--contains', '登録しました', '--absent', 'ログイン')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_hx_target_is_caught(self):
        result = self.check('missing-target.html')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('htmx:targetError', result.stderr)

    def test_422_is_not_swapped_by_default(self):
        result = self.check('invalid-default.html', '--contains', '入力エラー')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('htmx:responseError', result.stderr)

    def test_documented_422_config_swaps_error_fragment(self):
        result = self.check('invalid-configured.html', '--contains', '入力エラー')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_login_page_swapped_into_fragment_is_caught(self):
        result = self.check('login.html', '--absent', 'ログイン')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
