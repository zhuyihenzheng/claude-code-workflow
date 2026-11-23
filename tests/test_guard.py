import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'templates/project'
sys.path.insert(0, str(PROJECT / 'scripts'))
import guard  # noqa: E402

TODAY = '2026-11-23'
CONTROLLER = 'src/main/java/com/example/order/OrderController.java'
CLEAN_CONTROLLER = '''package com.example.order;

import com.example.order.service.OrderService;

public class OrderController {
    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }
}
'''
FIELD_INJECTION = '''package com.example.order;

import com.example.order.mapper.OrderMapper;

public class OrderController {
    @Autowired
    private OrderMapper orderMapper;
}
'''


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'config/guard').mkdir(parents=True)
        shutil.copy(PROJECT / 'config/guard/rules.json', self.root / 'config/guard/rules.json')
        self.write(CONTROLLER, CLEAN_CONTROLLER)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text, encoding='utf-8'):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode(encoding))
        return path

    def run_guard(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = guard.main(['--root', str(self.root), '--today', TODAY, *args])
        return code, out.getvalue() + err.getvalue()

    def baseline(self):
        return json.loads((self.root / guard.BASELINE).read_text(encoding='utf-8'))['rules']

    def test_template_rules_pass_their_own_examples(self):
        rules = guard.load_rules(PROJECT)
        self.assertGreaterEqual(len(rules), 10)
        for rule in rules:
            with self.subTest(rule=rule.id):
                self.assertTrue(rule.message.strip())
                self.assertTrue(rule.origin)
                self.assertTrue(rule.examples['bad'])

    def test_clean_project_passes(self):
        code, out = self.run_guard()
        self.assertEqual(code, 0, out)
        self.assertIn('guard: OK', out)

    def test_violations_name_file_line_rule_and_fix(self):
        self.write(CONTROLLER, FIELD_INJECTION)
        self.write('src/main/webapp/WEB-INF/jsp/orders/new.jsp',
                   '<%@ page contentType="text/html; charset=UTF-8" %>\n<p><%= request.getParameter("name") %></p>\n')
        code, out = self.run_guard()
        self.assertEqual(code, 1, out)
        self.assertIn(f'{CONTROLLER}:3: [controller-no-persistence] ', out)
        self.assertIn(f'{CONTROLLER}:6: [java-no-field-injection] ', out)
        self.assertIn('コンストラクタの引数で受け取る', out)
        self.assertIn('src/main/webapp/WEB-INF/jsp/orders/new.jsp:2: [jsp-no-scriptlet] ', out)
        self.assertIn('ベースライン未登録のルール', out)

    def test_each_rule_fires_only_on_its_files(self):
        self.write('src/test/java/com/example/order/OrderControllerTest.java',
                   'class T {\n    @Autowired\n    private MockMvc mockMvc;\n}\n')
        self.write('docs/notes.md', '<% scriptlet in prose %>\n')
        code, out = self.run_guard()
        self.assertEqual(code, 0, out)

    def test_baseline_accepts_existing_violations_and_only_shrinks(self):
        self.write(CONTROLLER, FIELD_INJECTION)
        code, out = self.run_guard('--init-baseline')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.baseline()['java-no-field-injection'], {CONTROLLER: 1})
        self.assertEqual(self.baseline()['jsp-no-scriptlet'], {})

        grown = FIELD_INJECTION.replace('}\n', '    @Autowired\n    private Clock clock;\n}\n')
        self.write(CONTROLLER, grown)
        code, out = self.run_guard()
        self.assertEqual(code, 1, out)
        self.assertIn('ベースライン 1 件に対して 2 件', out)
        self.assertNotIn('ベースライン未登録', out)

        code, out = self.run_guard('--update-baseline')
        self.assertEqual(code, 1, out)
        self.assertEqual(self.baseline()['java-no-field-injection'], {CONTROLLER: 1}, 'update never grows')

        code, out = self.run_guard('--init-baseline')
        self.assertEqual(code, 1, out)
        self.assertEqual(self.baseline()['java-no-field-injection'], {CONTROLLER: 1}, 'init leaves registered rules')

        self.write(CONTROLLER, CLEAN_CONTROLLER)
        code, out = self.run_guard()
        self.assertEqual(code, 0, out)
        self.assertIn('--update-baseline', out)
        code, out = self.run_guard('--update-baseline')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.baseline()['java-no-field-injection'], {})
        self.write(CONTROLLER, FIELD_INJECTION)
        self.assertEqual(self.run_guard()[0], 1, 'a fixed violation cannot come back')

    def test_new_rule_starts_unregistered_while_old_rules_keep_their_baseline(self):
        self.write(CONTROLLER, FIELD_INJECTION)
        self.run_guard('--init-baseline')
        rules = json.loads((self.root / guard.RULES).read_text(encoding='utf-8'))
        rules['rules'].append({
            'id': 'no-order-mapper', 'files': ['**/*.java'], 'pattern': r'\bOrderMapper\b',
            'message': 'OrderService を使う', 'origin': 'test', 'examples': {'bad': ['OrderMapper m;']}})
        (self.root / guard.RULES).write_text(json.dumps(rules, ensure_ascii=False), encoding='utf-8')
        code, out = self.run_guard()
        self.assertEqual(code, 1, out)
        self.assertIn('[no-order-mapper]', out)
        self.assertNotIn('[java-no-field-injection]', out)
        self.assertIn('ベースライン未登録のルール：no-order-mapper', out)

    def test_update_baseline_requires_an_initialized_baseline(self):
        code, out = self.run_guard('--update-baseline')
        self.assertEqual(code, 2, out)
        self.assertIn('--init-baseline', out)
        self.assertFalse((self.root / guard.BASELINE).exists())

    def test_allow_needs_reason_expiry_and_approver(self):
        cases = {
            'until=2027-03-31 by=yamada -- 外部ライブラリが setter 注入だけを提供する': 0,
            'until=2026-11-22 by=yamada -- 期限切れ': 1,
            'until=2028-01-01 by=yamada -- 期限が遠すぎる': 1,
            'until=2027-03-31 -- 承認者なし': 1,
            'until=2027-03-31 by=yamada': 1,
            'until=next-week by=yamada -- 日付ではない': 1,
        }
        for fields, expected in cases.items():
            with self.subTest(fields=fields):
                self.write(CONTROLLER, FIELD_INJECTION.replace(
                    'import com.example.order.mapper.OrderMapper;\n', '').replace(
                    '    @Autowired\n', f'    // guard:allow java-no-field-injection {fields}\n    @Autowired\n'))
                code, out = self.run_guard()
                self.assertEqual(code, expected, out)
                if expected:
                    self.assertIn('[guard-allow]', out)

    def test_allow_covers_only_its_rule_and_lines(self):
        self.write(CONTROLLER, FIELD_INJECTION.replace(
            'import com.example.order.mapper.OrderMapper;',
            'import com.example.order.mapper.OrderMapper; // guard:allow java-no-field-injection until=2027-01-31 by=sato -- 別ルール'))
        code, out = self.run_guard()
        self.assertEqual(code, 1, out)
        self.assertIn('[controller-no-persistence]', out)
        self.assertIn('[java-no-field-injection]', out)
        self.assertIn('使われていない例外', out)

    def test_allow_with_unknown_rule_fails_and_allow_text_is_not_scanned(self):
        self.write('src/main/java/com/example/A.java',
                   'class A {\n    // guard:allow no-such-rule until=2027-01-31 by=sato -- 暫定対応の説明\n}\n')
        code, out = self.run_guard()
        self.assertEqual(code, 1, out)
        self.assertIn("[guard-allow] 未知のルール 'no-such-rule'", out)
        self.assertNotIn('[comment-workaround]', out)

    def test_allow_in_jsp_comment(self):
        self.write('src/main/webapp/WEB-INF/jsp/a.jsp',
                   '<%-- guard:allow jsp-no-scriptlet until=2027-01-31 by=sato -- ベンダー提供タグの制約 --%>\n<%= x %>\n')
        code, out = self.run_guard()
        self.assertEqual(code, 0, out)
        self.assertIn('例外 1 件', out)

    def test_broken_rule_is_a_configuration_error(self):
        rules = json.loads((self.root / guard.RULES).read_text(encoding='utf-8'))
        rules['rules'][0]['examples']['bad'].append('<c:out value="${x}"/>')
        rules['rules'][1]['pattern'] = '('
        rules['rules'].append(dict(rules['rules'][2]))
        (self.root / guard.RULES).write_text(json.dumps(rules, ensure_ascii=False), encoding='utf-8')
        code, out = self.run_guard()
        self.assertEqual(code, 2, out)
        self.assertIn('検査未完了', out)
        self.assertIn('examples.bad に一致しません', out)
        self.assertIn('正規表現として不正', out)
        self.assertIn('id が重複', out)

    def test_missing_rules_file_is_a_configuration_error(self):
        (self.root / guard.RULES).unlink()
        self.assertEqual(self.run_guard()[0], 2)

    def test_paths_limit_the_scan_and_block_baseline_updates(self):
        self.write(CONTROLLER, FIELD_INJECTION)
        self.write('src/main/java/com/example/Other.java', 'class Other {}\n')
        code, out = self.run_guard(str(self.root / 'src/main/java/com/example/Other.java'))
        self.assertEqual(code, 0, out)
        self.assertIn('1 ファイルを検査', out)
        self.assertEqual(self.run_guard(str(self.root / 'src'))[0], 1)
        self.assertEqual(self.run_guard('--init-baseline', str(self.root / 'src'))[0], 2)

    def test_crlf_and_shift_jis_sources(self):
        self.write('src/main/java/com/example/B.java', 'class B {\r\n\r\n    // 暫定対応\r\n}\r\n')
        self.write('src/main/webapp/WEB-INF/jsp/sjis.jsp', '<p>注文</p>\n<% int i = 0; %>\n', encoding='cp932')
        code, out = self.run_guard()
        self.assertEqual(code, 1, out)
        self.assertIn('src/main/java/com/example/B.java:3: [comment-workaround]', out)
        self.assertIn('src/main/webapp/WEB-INF/jsp/sjis.jsp:2: [jsp-no-scriptlet]', out)

    def test_build_output_is_skipped_and_git_ignored_files_are_skipped(self):
        self.write('target/classes/x.jsp', '<% bad %>\n')
        self.write('node_modules/pkg/x.jsp', '<% bad %>\n')
        self.assertEqual(self.run_guard()[0], 0)
        git = shutil.which('git')
        if not git:
            self.skipTest('git is not installed')
        subprocess.run([git, 'init', '-q', str(self.root)], check=True)
        self.write('.gitignore', 'generated/\n')
        self.write('generated/x.jsp', '<% bad %>\n')
        self.write('src/main/webapp/untracked.jsp', '<% bad %>\n')
        code, out = self.run_guard()
        self.assertEqual(code, 1, out)
        self.assertIn('src/main/webapp/untracked.jsp:1:', out)
        self.assertNotIn('generated/x.jsp', out)

    def test_runs_as_a_script_with_its_project_as_default_root(self):
        (self.root / 'scripts').mkdir()
        shutil.copy(PROJECT / 'scripts/guard.py', self.root / 'scripts/guard.py')
        self.write(CONTROLLER, FIELD_INJECTION)
        result = subprocess.run([sys.executable, str(self.root / 'scripts/guard.py')], capture_output=True,
                                text=True, encoding='utf-8', errors='replace', cwd=self.root,
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        self.assertIn('guard: NG', result.stdout)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('[java-no-field-injection]', result.stdout)

    def test_github_format_annotates_the_failing_lines(self):
        self.write(CONTROLLER, FIELD_INJECTION)
        code, out = self.run_guard('--format', 'github')
        self.assertEqual(code, 1, out)
        self.assertIn(f'::error file={CONTROLLER},line=6,title=guard java-no-field-injection::フィールドインジェクション', out)
        self.assertIn(f'{CONTROLLER}:6: [java-no-field-injection]', out, 'the readable line stays in the log')
        self.write('src/main/java/a,b%c.java', 'class A {\n    // 暫定\n}\n')
        code, out = self.run_guard('--format', 'github')
        self.assertIn('::error file=src/main/java/a%2Cb%25c.java,line=2,title=guard comment-workaround::', out)

    def test_list_shows_fix_and_origin(self):
        code, out = self.run_guard('--list')
        self.assertEqual(code, 0)
        self.assertIn('jsp-no-scriptlet  [ベースライン未登録]', out)
        self.assertIn('直し方：', out)
        self.assertIn('由来：', out)

    def test_glob_semantics(self):
        regex = guard.glob_regex('**/src/main/java/**/*Controller.java')
        self.assertTrue(regex.match('src/main/java/a/OrderController.java'))
        self.assertTrue(regex.match('order-web/src/main/java/a/b/OrderController.java'))
        self.assertFalse(regex.match('src/test/java/a/OrderControllerTest.java'))
        self.assertTrue(guard.glob_regex('**/*.jsp').match('a.jsp'))
        self.assertFalse(guard.glob_regex('screen-tests/*.mjs').match('screen-tests/a/b.mjs'))


if __name__ == '__main__':
    unittest.main()
