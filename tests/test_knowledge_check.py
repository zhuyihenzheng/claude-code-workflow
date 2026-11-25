import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'templates/project'
sys.path.insert(0, str(PROJECT / 'scripts'))
import knowledge_check  # noqa: E402

CODEMAP = '''# コードマップ

## S01 注文登録

- 画面：`src/main/webapp/WEB-INF/jsp/orders/new.jsp`
- Controller：`src/main/java/com/example/OrderController.java:21`（`create`）
- 設計書のフォルダ：`specs-ai/注文/`
- 参考：`https://example.com/a/b`、`*.jsp`、`/etc/hosts`、`name=foo`、`OrderController`、ビュー名 `fragments/order-form`
'''
GLOSSARY = '''# 用語集

| 用語 | 意味 | 画面・設計書での表記 | コード・DB での名前 |
|---|---|---|---|
| 受注 | 注文を登録した状態 | 注文登録 | `Order` |
| 締め | 月末の確定 | 月次締め | `ClosingService` |
'''


class KnowledgeCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in ('src/main/webapp/WEB-INF/jsp/orders/new.jsp', 'src/main/java/com/example/OrderController.java',
                    'docs/feature-map/S01-order-new.md', 'specs-ai/注文/index.md'):
            self.write(rel, 'x\n')

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def run_check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = knowledge_check.main(['--root', str(self.root)])
        return code, out.getvalue()

    def test_no_knowledge_yet_passes(self):
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn('知識ファイルはまだありません', out)

    def test_current_knowledge_passes_and_only_repository_paths_are_checked(self):
        self.write('docs/knowledge/codemap.md', CODEMAP)
        self.write('docs/knowledge/glossary.md', GLOSSARY)
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn('knowledge: OK（2 ファイル）', out)

    def test_moved_files_unknown_features_and_duplicate_terms_are_reported(self):
        self.write('docs/knowledge/codemap.md', CODEMAP.replace('orders/new.jsp', 'orders/old.jsp') + '\n## S99 廃止画面\n')
        self.write('docs/knowledge/glossary.md', GLOSSARY + '| 受注 | 重複 | - | - |\n')
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn('docs/knowledge/codemap.md:5: `src/main/webapp/WEB-INF/jsp/orders/old.jsp` がありません', out)
        self.assertIn('docs/knowledge/codemap.md:10: 機能 ID S99 が docs/feature-map/ にありません', out)
        self.assertIn('docs/knowledge/glossary.md:7: 用語「受注」が 5 行目と重複しています', out)

    def test_the_readme_examples_are_not_checked(self):
        (self.root / 'docs/knowledge').mkdir(parents=True)
        (self.root / 'docs/knowledge/README.md').write_bytes((PROJECT / 'docs/knowledge/README.md').read_bytes())
        self.assertEqual(self.run_check()[0], 0)


if __name__ == '__main__':
    unittest.main()
