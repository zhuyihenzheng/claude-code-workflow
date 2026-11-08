import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'templates/project/scripts/xlsx2ai.py'
spec = importlib.util.spec_from_file_location('xlsx2ai', SCRIPT)
xlsx2ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xlsx2ai)


def tools_available():
    return all(importlib.util.find_spec(name) for name in ('exstruct', 'excel2md', 'openpyxl'))


TOOLS = tools_available()
if not TOOLS and os.environ.get('XLSX2AI_REQUIRED') == '1':
    raise RuntimeError('XLSX2AI_REQUIRED=1 but exstruct / excel2md / openpyxl are not installed')

# Flowchart drawn with real DrawingML shapes and connectors (stCxn/endCxn), as Excel stores it.
NODES = [(2, 'flowChartTerminator', '開始', 5), (3, 'flowChartProcess', '入力チェック', 9),
         (4, 'flowChartDecision', 'エラー有?', 13), (5, 'flowChartProcess', 'エラー表示', 13),
         (6, 'flowChartProcess', '登録処理', 17), (7, 'flowChartTerminator', '終了', 21)]
EDGES = [(2, 3), (3, 4), (4, 5), (4, 6), (6, 7), (5, 3)]


def drawing_xml(with_picture=False):
    def anchor(row):
        return (f'<xdr:from><xdr:col>3</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
                f'<xdr:to><xdr:col>5</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row + 2}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>')
    body = ''
    for i, preset, text, row in NODES:
        body += (f'<xdr:twoCellAnchor>{anchor(row)}<xdr:sp macro="" textlink=""><xdr:nvSpPr><xdr:cNvPr id="{i}" name="n{i}"/>'
                 f'<xdr:cNvSpPr/></xdr:nvSpPr><xdr:spPr><a:prstGeom prst="{preset}"><a:avLst/></a:prstGeom></xdr:spPr>'
                 f'<xdr:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{text}</a:t></a:r></a:p></xdr:txBody></xdr:sp>'
                 f'<xdr:clientData/></xdr:twoCellAnchor>')
    for n, (a, b) in enumerate(EDGES):
        body += (f'<xdr:twoCellAnchor>{anchor(7)}<xdr:cxnSp macro=""><xdr:nvCxnSpPr><xdr:cNvPr id="{10 + n}" name="c{n}"/>'
                 f'<xdr:cNvCxnSpPr><a:stCxn id="{a}" idx="2"/><a:endCxn id="{b}" idx="0"/></xdr:cNvCxnSpPr></xdr:nvCxnSpPr>'
                 f'<xdr:spPr><a:prstGeom prst="straightConnector1"><a:avLst/></a:prstGeom><a:ln><a:tailEnd type="triangle"/></a:ln>'
                 f'</xdr:spPr></xdr:cxnSp><xdr:clientData/></xdr:twoCellAnchor>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><xdr:wsDr '
            'xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">' + body + '</xdr:wsDr>')


def make_book(path, flow_on_sheet=None, media=False):
    """Two-sheet design document; optionally a shape flowchart on one sheet and a media file."""
    import openpyxl
    wb = openpyxl.Workbook()
    cover = wb.active
    cover.title = '表紙'
    cover['B2'] = 'テーブル定義書'
    cover['B4'] = '図書貸出管理システム'
    cover.merge_cells('B2:F2')
    table = wb.create_sheet('テーブル一覧')
    for row in (('No', 'テーブル名', '論理名'), (1, 'book', '蔵書'), (2, 'loan', '貸出')):
        table.append(row)
    tmp = str(path) + '.tmp'
    wb.save(tmp)
    sheet_index = {'表紙': 1, 'テーブル一覧': 2}.get(flow_on_sheet)
    with zipfile.ZipFile(tmp) as src, zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if sheet_index and item.filename == f'xl/worksheets/sheet{sheet_index}.xml':
                text = data.decode().replace('</worksheet>', '<drawing r:id="rIdDr1"/></worksheet>')
                if 'xmlns:r=' not in text:
                    text = text.replace('<worksheet ', '<worksheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ', 1)
                data = text.encode()
            if item.filename == '[Content_Types].xml' and sheet_index:
                data = data.decode().replace('</Types>', '<Override PartName="/xl/drawings/drawing1.xml" ContentType='
                                             '"application/vnd.openxmlformats-officedocument.drawing+xml"/></Types>').encode()
            dst.writestr(item, data)
        if sheet_index:
            dst.writestr('xl/drawings/drawing1.xml', drawing_xml())
            dst.writestr(f'xl/worksheets/_rels/sheet{sheet_index}.xml.rels',
                         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships '
                         'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdDr1" '
                         'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" '
                         'Target="../drawings/drawing1.xml"/></Relationships>')
        if media:
            dst.writestr('xl/media/image1.png', b'\x89PNG\r\n\x1a\n')
    os.remove(tmp)


def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = xlsx2ai.main([str(a) for a in args])
    return code, out.getvalue()


@unittest.skipUnless(TOOLS, 'exstruct / excel2md / openpyxl not installed')
class Xlsx2AiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='xlsx2ai ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.src = self.root / 'specs'
        self.out = self.root / 'specs-ai'
        (self.src / 'db').mkdir(parents=True)

    def test_converts_sheets_and_writes_indexes(self):
        make_book(self.src / 'db' / '[テーブル定義書]図書.xlsx')
        code, log = run(self.src, self.out)
        self.assertEqual(code, 0, log)
        book = self.out / 'db' / '[テーブル定義書]図書'
        sheet = json.loads((book / 'sheets' / 'テーブル一覧.json').read_text(encoding='utf-8'))
        self.assertIn('蔵書', json.dumps(sheet, ensure_ascii=False))
        self.assertIn('貸出', json.dumps(sheet, ensure_ascii=False))
        self.assertTrue((book / 'sheets' / '表紙.json').is_file())
        root_index = (self.out / 'index.md').read_text(encoding='utf-8')
        self.assertIn('(<db/[テーブル定義書]図書/index.md>)', root_index)
        self.assertIn(r'\[テーブル定義書\]', root_index)
        self.assertIn('(<sheets/テーブル一覧.json>)', (book / 'index.md').read_text(encoding='utf-8'))
        self.assertFalse((book / 'flows').exists())
        self.assertFalse((book / 'media').exists())

    def test_shape_flowchart_becomes_mermaid_with_all_edges(self):
        make_book(self.src / 'flow.xlsx', flow_on_sheet='テーブル一覧')
        code, log = run(self.src, self.out)
        self.assertEqual(code, 0, log)
        mermaid = (self.out / 'flow' / 'flows' / 'テーブル一覧.mmd').read_text(encoding='utf-8')
        self.assertTrue(mermaid.startswith('flowchart'))
        self.assertEqual(mermaid.count('-->'), len(EDGES))
        for _, _, text, _ in NODES:
            self.assertIn(text, mermaid)
        self.assertIn('{"エラー有?"}', mermaid)
        index = (self.out / 'flow' / 'index.md').read_text(encoding='utf-8')
        self.assertIn('(<flows/テーブル一覧.mmd>)', index)
        self.assertIn('分岐ラベル', index)

    def test_incremental_reconvert_delete_and_check(self):
        first, second = self.src / 'a.xlsx', self.src / 'b.xlsx'
        make_book(first)
        make_book(second)
        self.assertEqual(run(self.src, self.out)[0], 0)
        self.assertEqual(run(self.src, self.out, '--check')[0], 0)
        marker = self.out / 'a' / 'sheets' / '表紙.json'
        before = marker.stat().st_mtime_ns
        code, log = run(self.src, self.out)
        self.assertIn('0 件を変換', log)
        self.assertEqual(marker.stat().st_mtime_ns, before)

        make_book(first, flow_on_sheet='表紙')  # content change
        self.assertEqual(run(self.src, self.out, '--check')[0], 1)
        code, log = run(self.src, self.out)
        self.assertIn('1 件を変換', log)
        self.assertTrue((self.out / 'a' / 'flows' / '表紙.mmd').is_file())

        second.unlink()
        self.assertEqual(run(self.src, self.out, '--check')[0], 1)
        self.assertTrue((self.out / 'b').exists(), '--check must not delete')
        code, log = run(self.src, self.out)
        self.assertFalse((self.out / 'b').exists())
        self.assertNotIn('b/index.md', (self.out / 'index.md').read_text(encoding='utf-8'))
        self.assertEqual(run(self.src, self.out, '--check')[0], 0)

    def test_lock_files_ignored_and_media_only_on_request(self):
        make_book(self.src / 'pics.xlsx', media=True)
        (self.src / '~$pics.xlsx').write_bytes(b'lock')
        code, log = run(self.src, self.out)
        self.assertEqual(code, 0, log)
        self.assertFalse((self.out / '~$pics').exists())
        self.assertFalse((self.out / 'pics' / 'media').exists())
        self.assertIn('貼り付け画像 1 件', (self.out / 'pics' / 'index.md').read_text(encoding='utf-8'))
        self.assertEqual(run(self.src, self.out, '--extract-media')[0], 0)
        self.assertTrue((self.out / 'pics' / 'media' / 'image1.png').is_file())

    def test_broken_workbook_fails_alone_without_partial_output(self):
        (self.src / 'broken.xlsx').write_bytes(b'not a zip')
        make_book(self.src / 'good.xlsx')
        code, log = run(self.src, self.out)
        self.assertEqual(code, 2)
        self.assertIn('失敗：', log)
        self.assertNotIn('Traceback', log)
        self.assertFalse((self.out / 'broken').exists())
        self.assertEqual([p.name for p in self.out.glob('.*.tmp')], [])
        self.assertTrue((self.out / 'good' / 'index.md').is_file())
        self.assertIn('good/index.md', (self.out / 'index.md').read_text(encoding='utf-8'))
        # The good book is recorded, so only the broken one stays stale.
        self.assertEqual(run(self.src, self.out, '--check')[1].count('古い出力'), 1)

    def test_corrupt_drawing_part_is_reported_not_raised(self):
        path = self.src / 'bad-drawing.xlsx'
        make_book(path, flow_on_sheet='表紙')
        with zipfile.ZipFile(path) as zf:
            items = {i.filename: zf.read(i.filename) for i in zf.infolist()}
        items['xl/workbook.xml'] = b'<not-xml'
        with zipfile.ZipFile(path, 'w') as zf:
            for name, data in items.items():
                zf.writestr(name, data)
        code, log = run(self.src, self.out)
        self.assertEqual(code, 2)
        self.assertIn('失敗：', log)
        self.assertNotIn('Traceback', log)


class InspectDrawingsTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('openpyxl'), 'openpyxl not installed')
    def test_counts_shapes_and_connectors_per_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'f.xlsx'
            make_book(path, flow_on_sheet='表紙')
            stats = xlsx2ai.inspect_drawings(path)
        self.assertEqual(stats['表紙'], {'shapes': len(NODES), 'connectors': len(EDGES), 'pictures': 0})
        self.assertEqual(stats['テーブル一覧'], {'shapes': 0, 'connectors': 0, 'pictures': 0})

    def test_missing_source_dir_is_an_error(self):
        code, log = run('/nonexistent-xlsx2ai-src', '/tmp/xlsx2ai-out')
        self.assertEqual(code, 2)
        self.assertIn('入力ディレクトリ', log)


if __name__ == '__main__':
    unittest.main()
