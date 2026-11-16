import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('xlsx_patch', ROOT / 'templates/project/scripts/xlsx_patch.py')
xlsx_patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xlsx_patch)

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill
except ImportError:  # the script itself needs only the standard library
    openpyxl = None

PICTURE = b'\x89PNG\r\n\x1a\n' + bytes(range(256)) * 4


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = xlsx_patch.main([str(a) for a in argv])
    return code, out.getvalue()


@unittest.skipUnless(openpyxl, 'openpyxl is needed to build the fixture workbook')
class XlsxPatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='xlsx patch ')
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.book = self.dir / '試験結果.xlsx'
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '試験結果'
        ws.append(['ケースID', '画面', '判定'])
        for row in (('L-01', 'ログイン', 'OK'), ('C-01', 'クーポン一覧', 'NG'), ('C-02', 'クーポン一覧', 'OK'), ('E-04', '交換', 'NG')):
            ws.append(row)
        ws['C3'].font = Font(bold=True, color='FF0000')
        ws['C3'].fill = PatternFill('solid', fgColor='FFEEEE')
        ws.column_dimensions['B'].width = 30
        ws.freeze_panes = 'A2'
        ws['A8'] = '合計'
        ws['C8'] = '=COUNTA(C2:C5)'
        ws.merge_cells('A10:C10')
        ws['A10'] = '備考欄（結合）'
        design = wb.create_sheet('画面項目定義')
        design.append(['項目', '型', '桁数'])
        design.append(['名前', '文字列', '20 文字以内'])
        staged = self.dir / 'staged.xlsx'
        wb.save(staged)
        # A picture and a part this script knows nothing about must survive untouched.
        with zipfile.ZipFile(staged) as src, zipfile.ZipFile(self.book, 'w', zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                dst.writestr(item, src.read(item.filename))
            dst.writestr('xl/media/image1.png', PICTURE)
            dst.writestr('customXml/item1.xml', '<a b="1"/>')
        staged.unlink()
        self.original = self.book.read_bytes()

    def patch(self, data, name='patch.json'):
        path = self.dir / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return path

    def entries(self, path):
        with zipfile.ZipFile(path) as zf:
            return {name: zf.read(name) for name in zf.namelist()}

    def values(self, sheet='試験結果'):
        ws = openpyxl.load_workbook(self.book)[sheet]
        return {cell.coordinate: cell.value for row in ws.iter_rows() for cell in row if cell.value is not None}

    def test_rows_are_found_by_key_and_only_instructed_cells_change(self):
        patch = self.patch({'sheet': '試験結果', 'table': {'key': 'ケースID', 'add_columns': ['備考'], 'rows': {
            'C-01': {'備考': '既知 NG：#123 画面仕様変更に未追随'}, 'E-04': {'備考': '要確認：E-04', '判定': {'from': 'NG', 'to': '保留'}}}}})
        before = self.entries(self.book)
        code, log = run('apply', self.book, patch)
        self.assertEqual(code, 0, log)
        self.assertIn("試験結果!D3：'' → '既知 NG：#123 画面仕様変更に未追随'", log)
        self.assertIn('4 セルを変更しました', log)
        after = self.entries(self.book)
        self.assertEqual(list(after), list(before), 'same parts in the same order')
        changed = [name for name in before if before[name] != after[name]]
        self.assertEqual(changed, ['xl/worksheets/sheet1.xml'])
        self.assertEqual(after['xl/media/image1.png'], PICTURE)
        values = self.values()
        self.assertEqual((values['D1'], values['D3'], values['D5'], values['C5']), ('備考', '既知 NG：#123 画面仕様変更に未追随', '要確認：E-04', '保留'))
        self.assertEqual((values['A3'], values['C3'], values['C4']), ('C-01', 'NG', 'OK'), 'neighbouring rows are untouched')
        self.assertNotIn('D2', values)
        self.assertNotIn('D4', values)
        ws = openpyxl.load_workbook(self.book)['試験結果']
        self.assertTrue(ws['C3'].font.bold)
        self.assertEqual(ws['C8'].value, '=COUNTA(C2:C5)')
        self.assertEqual((ws.freeze_panes, ws.column_dimensions['B'].width), ('A2', 30))
        self.assertIn('A10:C10', [str(r) for r in ws.merged_cells.ranges])
        # Applying the same instructions again changes nothing.
        saved = self.book.read_bytes()
        code, log = run('apply', self.book, patch)
        self.assertEqual(code, 0, log)
        self.assertIn('変更はありません', log)
        self.assertEqual(self.book.read_bytes(), saved)

    def test_existing_cell_keeps_its_style_when_rewritten(self):
        code, log = run('apply', self.book, self.patch({'sheet': '試験結果', 'cells': {'C3': {'from': 'NG', 'to': '既知NG'}}}))
        self.assertEqual(code, 0, log)
        cell = openpyxl.load_workbook(self.book)['試験結果']['C3']
        self.assertEqual(cell.value, '既知NG')
        self.assertTrue(cell.font.bold)
        self.assertEqual(cell.fill.fgColor.rgb[-6:], 'FFEEEE')

    def test_cells_need_the_current_value_and_special_characters_survive(self):
        text = '40 文字以内 <必須> & "引用"\n2 行目'
        code, log = run('apply', self.book, self.patch({'sheet': '画面項目定義', 'cells': {'C2': {'from': '20 文字以内', 'to': text}}}))
        self.assertEqual(code, 0, log)
        self.assertEqual(self.values('画面項目定義')['C2'], text)
        self.assertEqual(self.values()['C3'], 'NG', 'the other sheet is untouched')

    def test_wrong_instructions_write_nothing(self):
        cases = {
            'from does not match': {'sheet': '画面項目定義', 'cells': {'C2': {'from': '30 文字以内', 'to': 'x'}}},
            'from is required for cells': {'sheet': '画面項目定義', 'cells': {'C2': {'to': 'x'}}},
            'unknown key': {'sheet': '試験結果', 'table': {'key': 'ケースID', 'rows': {'Z-99': {'判定': 'OK'}}}},
            'unknown key column': {'sheet': '試験結果', 'table': {'key': 'ID', 'rows': {'C-01': {'判定': 'OK'}}}},
            'column not declared': {'sheet': '試験結果', 'table': {'key': 'ケースID', 'rows': {'C-01': {'備考': 'x'}}}},
            'ambiguous key': {'sheet': '試験結果', 'table': {'key': '画面', 'rows': {'クーポン一覧': {'判定': 'OK'}}}},
            'formula cell': {'sheet': '試験結果', 'cells': {'C8': {'from': '', 'to': 'x'}}},
            'inside a merged range': {'sheet': '試験結果', 'cells': {'B10': {'from': '', 'to': 'x'}}},
            'missing sheet': {'sheet': 'なし', 'cells': {'A1': {'from': '', 'to': 'x'}}},
            'non-string value': {'sheet': '試験結果', 'table': {'key': 'ケースID', 'rows': {'C-01': {'判定': 1}}}},
            'unknown field': {'sheet': '試験結果', 'rows': {'C-01': {'判定': 'OK'}}},
            # One good instruction next to a bad one: nothing may be written.
            'partial': {'sheet': '試験結果', 'cells': {'C3': {'from': 'NG', 'to': 'OK'}, 'C4': {'from': 'NG', 'to': '保留'}}},
        }
        for label, data in cases.items():
            with self.subTest(label=label):
                code, log = run('apply', self.book, self.patch(data))
                self.assertEqual(code, 2, log)
                self.assertIn('エラー', log)
                self.assertEqual(self.book.read_bytes(), self.original)
        self.assertEqual(run('apply', self.book, self.dir / 'missing.json')[0], 2)
        (self.dir / 'broken.json').write_text('{', encoding='utf-8')
        self.assertEqual(run('apply', self.book, self.dir / 'broken.json')[0], 2)
        self.assertEqual([p.name for p in self.dir.glob('*.xlsx')], [self.book.name], 'no temporary workbook is left behind')

    def test_dry_run_and_out_leave_the_original_alone(self):
        patch = self.patch({'sheet': '試験結果', 'cells': {'C3': {'from': 'NG', 'to': 'OK'}}})
        code, log = run('apply', self.book, patch, '--dry-run')
        self.assertEqual(code, 0, log)
        self.assertIn("試験結果!C3：'NG' → 'OK'", log)
        self.assertIn('--dry-run', log)
        self.assertEqual(self.book.read_bytes(), self.original)
        out = self.dir / 'copy.xlsx'
        self.assertEqual(run('apply', self.book, patch, '--out', out)[0], 0)
        self.assertEqual(self.book.read_bytes(), self.original)
        self.assertEqual(openpyxl.load_workbook(out)['試験結果']['C3'].value, 'OK')

    def test_new_rows_and_cells_are_inserted_in_order(self):
        code, log = run('apply', self.book, self.patch({'sheet': '試験結果', 'cells': {
            'B7': {'from': '', 'to': '行の追加'}, 'A6': {'from': '', 'to': '先頭'}, 'E12': {'from': '', 'to': '末尾'}, 'B8': {'from': '', 'to': '間'}}}))
        self.assertEqual(code, 0, log)
        values = self.values()
        self.assertEqual((values['A6'], values['B7'], values['B8'], values['E12']), ('先頭', '行の追加', '間', '末尾'))
        self.assertEqual((values['A8'], values['C8']), ('合計', '=COUNTA(C2:C5)'))
        with zipfile.ZipFile(self.book) as zf:
            xml = zf.read('xl/worksheets/sheet1.xml').decode('utf-8')
        rows = [int(n) for n in xlsx_patch.re.findall(r'<row r="(\d+)"', xml)]
        self.assertEqual(rows, sorted(rows))
        self.assertIn('ref="A1:E12"', xml)

    def test_diff_reports_changes_and_expect_rejects_anything_else(self):
        patch = self.patch({'sheet': '試験結果', 'table': {'key': 'ケースID', 'rows': {'C-01': {'判定': {'from': 'NG', 'to': '既知NG'}}}}})
        good = self.dir / 'good.xlsx'
        self.assertEqual(run('apply', self.book, patch, '--out', good)[0], 0)
        code, log = run('diff', self.book, good, '--expect', patch)
        self.assertEqual(code, 0, log)
        self.assertIn("試験結果!C3：'NG' → '既知NG'", log)
        self.assertEqual(run('diff', self.book, self.book)[1].strip(), '差分はありません')

        # A person (or a tool) edited the workbook: one instructed cell, one extra cell, one wrong row, one style.
        edited = self.dir / 'edited.xlsx'
        wb = openpyxl.load_workbook(self.book)
        ws = wb['試験結果']
        ws['C3'] = '既知NG'
        ws['C5'] = '既知NG'
        ws['B2'].font = Font(italic=True)
        ws.column_dimensions['A'].width = 50
        wb.save(edited)
        code, log = run('diff', self.book, edited, '--expect', patch)
        self.assertEqual(code, 1, log)
        self.assertIn("指示にない変更：試験結果!C5：'NG' → '既知NG'", log)
        self.assertIn('書式または数式が変わっています：試験結果!B2', log)
        self.assertIn('セル以外の定義', log)
        self.assertNotIn('指示にない変更：試験結果!C3', log)
        self.assertEqual(run('diff', self.book, edited)[0], 0, 'without --expect the diff is only a report')

        untouched = self.dir / 'untouched.xlsx'
        untouched.write_bytes(self.original)
        code, log = run('diff', self.book, untouched, '--expect', patch)
        self.assertEqual(code, 1, log)
        self.assertIn('指示どおりになっていません：試験結果!C3', log)


class RefTests(unittest.TestCase):
    def test_column_letters_round_trip(self):
        for index, letters in ((1, 'A'), (26, 'Z'), (27, 'AA'), (52, 'AZ'), (703, 'AAA')):
            self.assertEqual(xlsx_patch.col_letters(index), letters)
            self.assertEqual(xlsx_patch.col_index(letters), index)
        with self.assertRaises(xlsx_patch.PatchError):
            xlsx_patch.split_ref('a1')


if __name__ == '__main__':
    unittest.main()
