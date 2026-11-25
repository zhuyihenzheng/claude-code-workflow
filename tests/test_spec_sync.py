import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'templates/project/scripts'))
import spec_sync  # noqa: E402
import xlsx2ai  # noqa: E402

DESIGN = '''# メッセージ一覧

| メッセージID | メッセージ | 区分 |
|---|---|---|
| E001 | 名前を入力してください | エラー |
| E002 | {0} は {1} 文字以内で入力してください | エラー |
| I001 | 登録しました：{名前} | 情報 |
| E003 | a\\|b<br>2行目 | エラー |

## 別の表（キーの列がないので対象外）

| 項目 | 規則 |
|---|---|
| 名前 | 必須 |
'''
PROPERTIES = '''# messages
E001=\\u540d\\u524d\\u3092\\u5165\\u529b\\u3057\\u3066\\u304f\\u3060\\u3055\\u3044
E002 = {0} は  {1} 文字以内で入力してください
I001=登録しました：{0}
E003=a|b\\n2行目
spring.custom=ignored
'''
CHECK = {'id': 'messages',
         'design': {'file': 'docs/messages.md', 'key': 'メッセージID', 'value': 'メッセージ'},
         'code': {'files': ['src/main/resources/messages*.properties'],
                  'pattern': r'^(?P<key>[A-Za-z0-9_.-]+)\s*[=:]\s*(?P<value>.*)$'},
         'normalize': ['placeholders', 'whitespace'], 'ignore_keys': [r'^spring\.']}


class SpecSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.write('docs/messages.md', DESIGN)
        self.write('src/main/resources/messages.properties', PROPERTIES)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def config(self, *checks):
        self.write(spec_sync.CONFIG, json.dumps({'checks': list(checks)}, ensure_ascii=False))

    def run_sync(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = spec_sync.main(['--root', str(self.root), *args])
        return code, out.getvalue()

    def test_no_config_or_no_checks_passes(self):
        self.assertEqual(self.run_sync()[0], 0)
        self.config()
        self.assertIn('チェックがありません', self.run_sync()[1])

    def test_matching_design_and_code(self):
        self.write('src/main/resources/messages.properties', PROPERTIES.replace('E003=a|b\\n2行目\n', ''))
        self.write('docs/messages.md', DESIGN.replace('| E003 | a\\|b<br>2行目 | エラー |\n', ''))
        self.config(CHECK)
        code, out = self.run_sync()
        self.assertEqual(code, 0, out)
        self.assertIn('spec_sync: OK（1 チェック、3 項目が一致）', out)

    def test_missing_extra_and_changed_values_are_reported_both_ways(self):
        self.write('src/main/resources/messages.properties',
                   PROPERTIES.replace('I001=登録しました：{0}\n', 'I002=削除しました\n').replace('E002 = {0} は  {1} 文字', 'E002={0} は {1} 桁'))
        self.config(CHECK)
        code, out = self.run_sync()
        self.assertEqual(code, 1, out)
        self.assertIn('[messages] 設計書にだけある（実装漏れ）：I001（docs/messages.md:7）', out)
        self.assertIn('[messages] コードにだけある（設計書の更新漏れ）：I002（src/main/resources/messages.properties:4）', out)
        self.assertIn("[messages] 値が違う：E002：設計書 '{0} は {1} 文字以内で入力してください'", out)
        self.assertNotIn('spring.custom', out)
        self.assertNotIn('E003', out, 'escaped pipes and <br> in the design match the code')

    def test_properties_escapes_and_continuation_lines(self):
        self.assertEqual(spec_sync.properties_unescape('x\\u3042\\ty\\\\z\\n'), 'x\u3042\ty\\z\n')
        self.write('src/main/resources/messages.properties', 'E001=\\u540d\\u524d\\u3092\\\n    \u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\n')
        self.write('docs/messages.md', '| メッセージID | メッセージ |\n|---|---|\n| E001 | 名前を入力してください |\n')
        self.config(CHECK)
        code, out = self.run_sync()
        self.assertEqual(code, 0, out)

    def test_keys_only_and_configuration_errors(self):
        self.config({**CHECK, 'design': {'file': 'docs/messages.md', 'key': 'メッセージID'}})
        self.assertEqual(self.run_sync()[0], 0)
        for broken, message in (({**CHECK, 'design': {**CHECK['design'], 'file': 'specs-ai/none.md'}}, 'xlsx2ai.py'),
                                ({**CHECK, 'design': {**CHECK['design'], 'key': 'ID'}}, '見出しに「ID」'),
                                ({**CHECK, 'code': {**CHECK['code'], 'files': ['nothing/*.properties']}}, '一致するファイルがありません'),
                                ({**CHECK, 'code': {**CHECK['code'], 'pattern': '^(?P<name>.*)$'}}, 'グループ key'),
                                ({**CHECK, 'normalize': ['case']}, 'normalize に不明な値')):
            with self.subTest(message=message):
                self.config(broken)
                code, out = self.run_sync()
                self.assertEqual(code, 2, out)
                self.assertIn(message, out)
        self.config(CHECK)
        self.assertEqual(self.run_sync('--only', 'other')[0], 2)

    def test_a_table_rendered_from_excel_by_xlsx2ai_is_read(self):
        rows = [{'r': 1, 'c': {'1': '■ メッセージ一覧'}},
                {'r': 2, 'c': {'1': 'メッセージID', '3': 'メッセージ'}},
                {'r': 3, 'c': {'1': 'E001', '3': '名前を入力してください'}},
                {'r': 4, 'c': {'1': 'E009', '3': '<b>太字</b> | 区切り'}}]
        self.write('specs-ai/設計書/sheets/メッセージ.md', xlsx2ai.sheet_markdown('メッセージ', rows))
        self.write('src/main/resources/messages.properties', 'E001=名前を入力してください\nE009=<b>太字</b> | 区切り\n')
        self.config({**CHECK, 'design': {**CHECK['design'], 'file': 'specs-ai/設計書/sheets/メッセージ.md'}})
        code, out = self.run_sync()
        self.assertEqual(code, 0, out)


if __name__ == '__main__':
    unittest.main()
