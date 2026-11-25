import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'templates/project/scripts'))
import junit_report  # noqa: E402
import xlsx_patch  # noqa: E402

SUITE = '''<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="com.example.order.OrderServiceTest" tests="4" failures="1" errors="1" skipped="1">
  <testcase name="createsAnOrder" classname="com.example.order.OrderServiceTest" time="0.120"/>
  <testcase name="rejectsZeroQuantity" classname="com.example.order.OrderServiceTest" time="0.010">
    <failure message="expected: &lt;422&gt; but was: &lt;200&gt;" type="org.opentest4j.AssertionFailedError">stack</failure>
  </testcase>
  <testcase name="connectsToTheDatabase" classname="com.example.order.OrderServiceTest" time="0.5">
    <error type="java.lang.IllegalStateException">java.lang.IllegalStateException: no container
	at x</error>
  </testcase>
  <testcase name="limits(int)[1]" classname="com.example.order.OrderServiceTest" time="0.001">
    <skipped message="Docker がない"/>
  </testcase>
</testsuite>
'''
SOURCE = '''package com.example.order;

@DisplayName("O01 注文サービス")
class OrderServiceTest {
    @Test
    @DisplayName("注文を登録できる")
    void createsAnOrder() {}

    @Test
    @DisplayName("数量 0 は \\"入力エラー\\" にする")
    void rejectsZeroQuantity() {}

    @ParameterizedTest
    @DisplayName("上限の境界値")
    @ValueSource(ints = {1})
    void limits(int n) {}

    void connectsToTheDatabase() {}
}
'''


class JunitReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def run_report(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = junit_report.main(['--root', str(self.root), *args])
        return code, out.getvalue()

    def test_no_reports_is_an_error(self):
        code, out = self.run_report()
        self.assertEqual(code, 2)
        self.assertIn('./mvnw test', out)

    def test_report_from_surefire_results_with_display_names(self):
        self.write('order-core/target/surefire-reports/TEST-com.example.order.OrderServiceTest.xml', SUITE)
        self.write('order-core/src/test/java/com/example/order/OrderServiceTest.java', SOURCE)
        code, out = self.run_report('--title', '注文システム')
        self.assertEqual(code, 1, out)
        md = (self.root / 'target/test-report/単体テスト成績書.md').read_text(encoding='utf-8')
        for line in ('| 対象 | 注文システム |', '| ケース | 4 |', '| OK | 1 |', '| NG | 2 |', '| スキップ | 1 |', '| 判定 | 不合格 |',
                     '| 1 | O01 注文サービス（OrderServiceTest） | 注文を登録できる | createsAnOrder | OK | 0.12 |  |',
                     '| 2 | O01 注文サービス（OrderServiceTest） | 数量 0 は "入力エラー" にする | rejectsZeroQuantity | NG | 0.01 | '
                     'expected: <422> but was: <200> |',
                     '| connectsToTheDatabase | connectsToTheDatabase | NG（エラー） | 0.5 | java.lang.IllegalStateException: no container |',
                     '| 上限の境界値 | limits(int)[1] | スキップ | 0.001 | Docker がない |'):
            self.assertIn(line, md)

        book = self.root / 'target/test-report/単体テスト成績書.xlsx'
        with zipfile.ZipFile(book) as zf:
            parts = xlsx_patch.sheet_parts(zf)
            self.assertEqual(list(parts), ['集計', '結果一覧'])
            cells = xlsx_patch.read_cells(zf.read(parts['結果一覧']).decode('utf-8'), xlsx_patch.shared_strings(zf))
        self.assertEqual((cells['C1'][0], cells['E3'][0], cells['C3'][0]), ('観点', 'NG', '数量 0 は "入力エラー" にする'))
        self.assertNotEqual(cells['E3'][1], cells['E2'][1], 'NG uses its own style')

    @unittest.skipUnless(importlib.util.find_spec('openpyxl'), 'openpyxl not installed')
    def test_the_workbook_opens_in_openpyxl(self):
        import openpyxl
        self.write('target/surefire-reports/TEST-a.xml', SUITE)
        self.run_report()
        wb = openpyxl.load_workbook(self.root / 'target/test-report/単体テスト成績書.xlsx')
        self.assertEqual(wb.sheetnames, ['集計', '結果一覧'])
        ws = wb['結果一覧']
        self.assertEqual([c.value for c in ws[1]], list(junit_report.HEADERS))
        self.assertEqual(ws['F2'].value, 0.12)
        self.assertTrue(ws['A1'].font.b)
        self.assertEqual(ws.freeze_panes, 'A2')
        self.assertEqual(ws.auto_filter.ref, 'A1:G5')


if __name__ == '__main__':
    unittest.main()
