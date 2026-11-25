import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock
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


    def test_each_sheet_also_gets_markdown_linked_from_the_index(self):
        make_book(self.src / 'flow.xlsx', flow_on_sheet='テーブル一覧')
        code, log = run(self.src, self.out)
        self.assertEqual(code, 0, log)
        book = self.out / 'flow'
        table = (book / 'sheets' / 'テーブル一覧.md').read_text(encoding='utf-8')
        self.assertTrue(table.startswith('# テーブル一覧\n'))
        self.assertIn('| No | テーブル名 | 論理名 |\n|---|---|---|\n| 1 | book | 蔵書 |\n| 2 | loan | 貸出 |', table)
        self.assertIn('```mermaid\nflowchart', table, 'the shape flowchart is embedded in its sheet')
        self.assertIn('- テーブル定義書', (book / 'sheets' / '表紙.md').read_text(encoding='utf-8'))
        index = (book / 'index.md').read_text(encoding='utf-8')
        self.assertIn('| テーブル一覧 | [sheets/テーブル一覧.md](<sheets/テーブル一覧.md>) | [sheets/テーブル一覧.json](<sheets/テーブル一覧.json>) |', index)
        self.assertIn('まず Markdown を読む', index)
        chars = sum(len(p.read_text(encoding='utf-8')) for p in (book / 'sheets').glob('*.md'))
        self.assertEqual(json.loads((self.out / xlsx2ai.MANIFEST).read_text(encoding='utf-8'))['books']['flow']['chars'], chars)

    def test_check_and_repair_missing_index_and_sheet(self):
        make_book(self.src / 'a.xlsx')
        self.assertEqual(run(self.src, self.out)[0], 0)
        for path in (self.out / 'index.md', self.out / 'a/sheets/表紙.md'):
            path.unlink()
            self.assertEqual(run(self.src, self.out, '--check')[0], 1, path)
            self.assertFalse(path.exists())
            self.assertEqual(run(self.src, self.out)[0], 0)
            self.assertTrue(path.is_file())
            self.assertEqual(run(self.src, self.out, '--check')[0], 0)

    def test_overlapping_book_destinations_and_unmanaged_directories_are_preserved(self):
        make_book(self.src / 'db.xlsx')
        make_book(self.src / 'db/a.xlsx')
        self.assertEqual(run(self.src, self.out)[0], 2)
        self.assertFalse(self.out.exists())
        (self.src / 'db/a.xlsx').unlink()
        existing = self.out / 'db/team-notes.md'
        existing.parent.mkdir(parents=True)
        existing.write_text('notes', encoding='utf-8')
        self.assertEqual(run(self.src, self.out)[0], 2)
        self.assertEqual(existing.read_text(encoding='utf-8'), 'notes')

    def test_output_from_an_older_format_is_regenerated(self):
        make_book(self.src / 'a.xlsx')
        self.assertEqual(run(self.src, self.out)[0], 0)
        manifest = self.out / xlsx2ai.MANIFEST
        data = json.loads(manifest.read_text(encoding='utf-8'))
        data['format'] = xlsx2ai.FORMAT_VERSION - 1
        manifest.write_text(json.dumps(data), encoding='utf-8')
        (self.out / 'a' / 'sheets' / '表紙.md').unlink()
        self.assertEqual(run(self.src, self.out, '--check')[0], 1)
        self.assertEqual(run(self.src, self.out)[0], 0)
        self.assertTrue((self.out / 'a' / 'sheets' / '表紙.md').is_file())

    def test_books_sharing_a_name_are_all_converted(self):
        # a.xlsx and a.xlsm used to map to the same output directory; one was dropped silently.
        make_book(self.src / '設計書.xlsx')
        make_book(self.src / '設計書.xlsm')
        make_book(self.src / 'db' / '単独.xlsx')
        code, log = run(self.src, self.out)
        self.assertEqual(code, 0, log)
        self.assertIn('3 ブック中 3 件を変換', log)
        for name in ('設計書-xlsx', '設計書-xlsm', 'db/単独'):
            self.assertTrue((self.out / name / 'sheets' / '表紙.json').is_file(), name)
        self.assertFalse((self.out / '設計書').exists())
        root_index = (self.out / 'index.md').read_text(encoding='utf-8')
        self.assertIn('| 設計書.xlsx | [設計書-xlsx/index.md]', root_index)
        self.assertIn('| 設計書.xlsm | [設計書-xlsm/index.md]', root_index)
        self.assertEqual(run(self.src, self.out, '--check')[0], 0)
        # No output directory may end in a suffix that the template settings deny reading.
        self.assertFalse([p for p in self.out.rglob('*') if p.is_dir() and p.suffix.lower() in xlsx2ai.SUFFIXES])
        # Removing one of the pair frees the plain name again; the stale directories go away.
        (self.src / '設計書.xlsm').unlink()
        code, log = run(self.src, self.out)
        self.assertEqual(code, 0, log)
        self.assertTrue((self.out / '設計書' / 'index.md').is_file())
        self.assertFalse((self.out / '設計書-xlsx').exists())
        self.assertFalse((self.out / '設計書-xlsm').exists())

    def test_unresolvable_output_name_clash_is_an_error(self):
        src = Path('specs')
        paths = [src / 'a.xlsx', src / 'a.xlsm', src / 'a-xlsx.xlsx']
        with self.assertRaises(xlsx2ai.ConversionError):
            xlsx2ai.book_keys(src, paths)
        self.assertEqual(set(xlsx2ai.book_keys(src, paths[:2])), {'a-xlsx', 'a-xlsm'})
        self.assertEqual(set(xlsx2ai.book_keys(src, [src / 'A.xlsx', src / 'sub/a.xlsx'])), {'A', 'sub/a'})

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

    def test_a_failed_replace_keeps_the_previous_output(self):
        book = self.src / 'a.xlsx'
        make_book(book)
        self.assertEqual(run(self.src, self.out)[0], 0)
        index = self.out / 'a' / 'index.md'
        before = index.read_text(encoding='utf-8')
        make_book(book, flow_on_sheet='表紙')
        real_rename = Path.rename

        def locked(self_path, target):
            if self_path.name == 'book':
                raise PermissionError('locked by another process')
            return real_rename(self_path, target)

        with mock.patch.object(Path, 'rename', locked):
            code, log = run(self.src, self.out)
        self.assertEqual(code, 2, log)
        self.assertIn('失敗：', log)
        self.assertNotIn('Traceback', log)
        self.assertEqual(index.read_text(encoding='utf-8'), before)
        self.assertEqual(run(self.src, self.out, '--check')[0], 1, 'the book stays stale until it converts')
        self.assertEqual(run(self.src, self.out)[0], 0)
        self.assertTrue((self.out / 'a' / 'flows' / '表紙.mmd').is_file())
        self.assertEqual(sorted(p.name for p in self.out.iterdir() if p.name.startswith('.') and p.is_dir()), [])

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


def grid(*rows):
    """ExStruct light rows from (row number, {column: value}) pairs."""
    return [{'r': r, 'c': {str(c): v for c, v in cells.items()}} for r, cells in rows]


class SheetMarkdownTests(unittest.TestCase):
    def test_design_document_grid_becomes_headings_tables_and_outline(self):
        md = xlsx2ai.sheet_markdown('S01 注文登録', grid(
            (1, {0: 'システム名', 7: '受注', 40: '作成者', 44: '山田'}),
            (3, {1: '■ 画面一覧'}),
            (4, {1: '画面ID', 5: '画面名', 12: 'URL'}),
            (5, {1: 'S01', 5: '注文登録', 12: '/orders/new'}),
            (6, {1: 'S02', 5: '注文照会', 12: '/orders'}),
            (8, {1: '5.2 相関チェック'}),
            (9, {1: '項番', 3: 'チェック内容', 20: 'メッセージ'}),
            (10, {1: 1, 3: '名前が未入力', 20: '名前を入力してください'}),
            (11, {1: 2, 3: '数量が 0 以下', 20: '数量は 1 以上を入力してください'}),
            (13, {1: '≪処理概要≫'}),
            (14, {2: '①', 3: '入力内容を検証する'}),
            (15, {3: '・', 4: 'エラーがあればフォームを再表示する'}),
            (16, {4: '入力値は保持する'}),
            (17, {2: '②', 3: '注文を登録する'}),
        ))
        self.assertTrue(md.startswith('# S01 注文登録\n\n- システム名 受注 作成者 山田\n'))
        self.assertIn('## ■ 画面一覧\n\n| 画面ID | 画面名 | URL |\n|---|---|---|\n| S01 | 注文登録 | /orders/new |', md)
        self.assertIn('## 5.2 相関チェック\n\n| 項番 | チェック内容 | メッセージ |\n|---|---|---|\n'
                      '| 1 | 名前が未入力 | 名前を入力してください |', md)
        self.assertIn('## ≪処理概要≫\n\n- ① 入力内容を検証する\n  - エラーがあればフォームを再表示する\n'
                      '    - 入力値は保持する\n- ② 注文を登録する\n', md)

    def test_two_column_table_two_row_header_and_merged_gaps(self):
        md = xlsx2ai.sheet_markdown('s', grid(
            (1, {1: '条件', 6: 'メッセージ'}),
            (2, {1: '名前が未入力', 6: '名前を入力してください'}),
            (3, {1: '登録成功', 6: '登録しました：{名前}'}),
            (6, {1: 'No.', 3: '項目', 8: 'イベント'}),
            (7, {8: '初期表示', 10: '操作時'}),
            (8, {1: 1, 3: '検索入力', 8: '表示', 10: '表示（活性）'}),
            (11, {1: 2, 3: '検索ボタン', 8: '非表示', 10: '表示'}),
        ))
        self.assertIn('| 条件 | メッセージ |\n|---|---|\n| 名前が未入力 | 名前を入力してください |\n| 登録成功 | 登録しました：{名前} |', md)
        self.assertIn('| No. | 項目 | イベント/初期表示 | イベント/操作時 |', md)
        self.assertIn('| 2 | 検索ボタン | 非表示 | 表示 |', md, 'two empty rows left by a merged cell do not end the table')

    def test_title_rows_split_tables_and_prose_is_not_mistaken_for_a_table(self):
        md = xlsx2ai.sheet_markdown('books', grid(
            (1, {1: 'カラム情報'}),
            (2, {1: 'No.', 3: '論理名', 8: '物理名'}),
            (3, {1: 1, 3: '書籍ID', 8: 'id'}),
            (4, {1: 'インデックス情報'}),
            (5, {1: 'No.', 3: 'インデックス名', 8: 'カラム'}),
            (6, {1: 1, 3: 'books_pkey', 8: 'id'}),
            (8, {3: '・', 4: '一行目'}),
            (9, {3: '・', 4: '二行目'}),
            (10, {3: '・', 4: '三行目'}),
        ))
        self.assertIn('**カラム情報**\n\n| No. | 論理名 | 物理名 |\n|---|---|---|\n| 1 | 書籍ID | id |\n\n**インデックス情報**', md)
        self.assertIn('- 一行目\n- 二行目\n- 三行目\n', md)

    def test_lists_never_jump_more_than_one_level_or_turn_into_code_blocks(self):
        md = xlsx2ai.sheet_markdown('s', grid((1, {1: '■ 概要'}), (2, {9: '深い字下げの段落'}), (3, {20: 'さらに深い'}),
                                             (4, {2: '浅く戻る'})))
        self.assertIn('## ■ 概要\n\n- 深い字下げの段落\n  - さらに深い\n- 浅く戻る\n', md)
        for line in md.splitlines():
            self.assertFalse(line.startswith('    ') and not line.lstrip().startswith('- '), line)

    def test_escaping_line_breaks_and_dates(self):
        md = xlsx2ai.sheet_markdown('<sheet>', grid(
            (1, {1: '項目', 3: '値', 5: '備考'}),
            (2, {1: 'a|b', 3: '1行目\n2行目', 5: '<input type="text">'}),
            (3, {1: '日付', 3: '2026-11-23 00:00:00', 5: 'x < y'}),
            (4, {1: '数量', 3: 3.0, 5: 2.5}),
        ))
        self.assertTrue(md.startswith('# \\<sheet>\n'))
        self.assertIn('| a\\|b | 1行目<br>2行目 | \\<input type="text"> |', md)
        self.assertIn('| 日付 | 2026-11-23 | x < y |', md)
        self.assertIn('| 数量 | 3 | 2.5 |', md)

    def test_sentences_are_never_titles_and_prose_ends_a_table(self):
        md = xlsx2ai.sheet_markdown('s', grid(
            (1, {2: '項目', 7: '規則'}),
            (2, {2: '名前', 7: '必須'}),
            (4, {2: '〈登録〉を押すと、フォームの領域だけを置き換える。'}),
            (6, {2: '条件', 8: 'メッセージ'}),
            (7, {2: '名前が未入力', 8: '名前を入力してください'}),
            (8, {2: '入力値は保持する。'}),
        ))
        self.assertIn('| 項目 | 規則 |\n|---|---|\n| 名前 | 必須 |\n\n- 〈登録〉を押すと、フォームの領域だけを置き換える。\n', md)
        self.assertIn('| 名前が未入力 | 名前を入力してください |\n\n- 入力値は保持する。\n', md)

    def test_group_header_row_starting_in_the_same_column(self):
        md = xlsx2ai.sheet_markdown('s', grid(
            (1, {1: '基本情報', 5: '連絡先'}),
            (2, {1: '氏名', 3: '年齢', 5: '電話', 7: 'メール'}),
            (3, {1: '山田', 3: 30, 5: '03-0000-0000', 7: 'a@example.com'}),
            (4, {1: '佐藤', 3: 41, 5: '06-0000-0000', 7: 'b@example.com'}),
        ))
        self.assertIn('| 基本情報/氏名 | 基本情報/年齢 | 連絡先/電話 | 連絡先/メール |\n|---|---|---|---|\n'
                      '| 山田 | 30 | 03-0000-0000 | a@example.com |', md)

    def test_a_remark_right_of_a_table_does_not_split_it(self):
        md = xlsx2ai.sheet_markdown('s', grid(
            (1, {1: 'No.', 3: '項目', 6: '値'}),
            (2, {1: 1, 3: 'a', 6: 'x'}),
            (3, {1: 2, 3: 'b', 6: 'y', 12: '※要確認'}),
            (4, {1: 3, 3: 'c', 6: 'z'}),
        ))
        self.assertIn('| No. | 項目 | 値 |  |\n|---|---|---|---|\n| 1 | a | x |  |\n| 2 | b | y | ※要確認 |\n| 3 | c | z |  |\n', md)

    def test_the_next_table_or_a_milestone_row_is_not_taken_as_a_remark(self):
        md = xlsx2ai.sheet_markdown('s', grid(
            (1, {1: '支払条件', 3: '月末締め翌月末払い'}),
            (2, {1: '部分納品', 3: '受領日から起算する'}),
            (3, {1: '支払対象', 5: '受領', 7: '支払期日'}),
            (4, {1: '外部設計', 5: '1/29', 7: '2/26'}),
            (6, {1: '検収', 9: '◆ 6/14'}),
            (7, {1: 'リリース', 11: '◆ 6/30'}),
        ))
        self.assertIn('| 部分納品 | 受領日から起算する |\n\n| 支払対象 | 受領 | 支払期日 |\n|---|---|---|\n| 外部設計 | 1/29 | 2/26 |\n', md)
        self.assertIn('- 検収 ◆ 6/14\n- リリース ◆ 6/30\n', md)

    def test_long_sheets_convert_in_linear_time(self):
        prose = grid(*[(r, {1: 'a', 2: 'b'} if r % 2 else {1: 'c'}) for r in range(1, 3001)])
        table = grid((1, {1: 'No.', 2: '値'}), *[(r, {1: r, 2: 'x'}) for r in range(2, 3002)])
        started = time.perf_counter()
        md, md_table = xlsx2ai.sheet_markdown('s', prose), xlsx2ai.sheet_markdown('t', table)
        self.assertLess(time.perf_counter() - started, 2.0)
        self.assertEqual(md.count('- a b'), 1500)
        self.assertEqual(md_table.count(' | x |'), 3000)

    def test_titles_are_judged_before_markdown_escaping(self):
        md = xlsx2ai.sheet_markdown('s', grid((1, {1: '■ <input> の扱い'}), (2, {2: '本文'})))
        self.assertIn('## ■ \\<input> の扱い\n', md)

    def test_flow_titles_match_sheet_names_with_surrounding_spaces(self):
        text = '# book\n\n## フロー\n\n```mermaid\nflowchart TD\n  A --> B\n```\n\n## 表紙\n\nx\n'
        self.assertEqual(xlsx2ai.flows_from_markdown(text, {'フロー ', '表紙'}), {'フロー ': 'flowchart TD\n  A --> B\n'})

    def test_empty_sheet_and_shape_flow(self):
        self.assertEqual(xlsx2ai.sheet_markdown('空', []), '# 空\n')
        md = xlsx2ai.sheet_markdown('フロー', grid((1, {1: '処理フロー'})), 'flowchart TD\n  A --> B\n')
        self.assertTrue(md.endswith('```mermaid\nflowchart TD\n  A --> B\n```\n'))


class InspectDrawingsTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('openpyxl'), 'openpyxl not installed')
    def test_counts_shapes_and_connectors_per_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'f.xlsx'
            make_book(path, flow_on_sheet='表紙')
            stats = xlsx2ai.inspect_drawings(path)
        self.assertEqual(stats['表紙'], {'shapes': len(NODES), 'connectors': len(EDGES), 'pictures': 0})
        self.assertEqual(stats['テーブル一覧'], {'shapes': 0, 'connectors': 0, 'pictures': 0})

    def test_drawing_tags_followed_by_a_line_break_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'f.xlsx'
            make_book(path, flow_on_sheet='表紙')
            spaced = Path(tmp) / 'g.xlsx'
            with zipfile.ZipFile(path) as src, zipfile.ZipFile(spaced, 'w') as dst:
                for item in src.infolist():
                    data = src.read(item.filename)
                    if item.filename == 'xl/drawings/drawing1.xml':
                        data = data.replace(b'<xdr:sp ', b'<xdr:sp\n ').replace(b'<xdr:cxnSp ', b'<xdr:cxnSp\n ')
                    dst.writestr(item, data)
            stats = xlsx2ai.inspect_drawings(spaced)
        self.assertEqual(stats['表紙'], {'shapes': len(NODES), 'connectors': len(EDGES), 'pictures': 0})

    def test_tools_come_from_this_interpreter_before_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('exstruct', 'exstruct.bat'):
                fake = Path(tmp) / name
                fake.write_text('#!/bin/sh\nexit 9\n', encoding='utf-8')
                fake.chmod(0o755)
            with mock.patch.dict(os.environ, {'PATH': tmp + os.pathsep + os.environ.get('PATH', '')}):
                with mock.patch.object(xlsx2ai.importlib.util, 'find_spec', return_value=object()):
                    self.assertEqual(xlsx2ai.tool_command('exstruct', '--help')[:2], [sys.executable, '-c'])
                with mock.patch.object(xlsx2ai.importlib.util, 'find_spec', return_value=None):
                    self.assertEqual(Path(xlsx2ai.tool_command('exstruct', '--help')[0]).parent, Path(tmp))

    def test_missing_source_dir_is_an_error(self):
        code, log = run('/nonexistent-xlsx2ai-src', '/tmp/xlsx2ai-out')
        self.assertEqual(code, 2)
        self.assertIn('入力ディレクトリ', log)


if __name__ == '__main__':
    unittest.main()
