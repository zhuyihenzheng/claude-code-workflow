#!/usr/bin/env python3
"""Excel 設計書・試験書を、変更指示（JSON）どおりに書き換える。指示にないセルは 1 バイトも変えない。

    python scripts/xlsx_patch.py apply <book.xlsx> <patch.json> [--out <new.xlsx>] [--dry-run]
    python scripts/xlsx_patch.py diff  <before.xlsx> <after.xlsx> [--expect <patch.json>]

AI ツールに Excel を直接編集させると、行の取り違えや、画像・書式の消失が起きても気づけない。
このスクリプトでは、AI は「どのセルを何から何へ」だけを JSON に書き、書き込みと検証は機械的に行う。

変更指示（1 シート分のオブジェクト、またはその配列）：

    {"sheet": "画面項目定義",
     "cells": {"D12": {"from": "20 文字以内", "to": "40 文字以内"}},
     "table": {"header_row": 1, "key": "ケースID", "add_columns": ["備考"],
               "rows": {"C-01": {"備考": "既知 NG：#123"}}}}

  cells  セル番地で指定する。from は現在の値（空欄は ""）。一致しなければ何も書かずに終了する。
  table  見出し行の列名と、キー列の値で行を特定する。行番号は書かない。キーが 0 行または複数行に
         一致した場合は何も書かずに終了する。値は文字列、または {"from": …, "to": …}。

apply は、対象シートの XML の該当セルだけを書き換え、他のファイル（画像・書式・他シート）は
そのままコピーする。保存前に「指示したセルだけが、指示した値になった」ことを確認する。
diff は 2 つのブックを比べ、変わったセルと、シート以外で変わったファイルを表示する。
--expect を付けると、変更指示にない差分があれば終了コード 1 を返す（人が Excel で直した結果の確認用）。
保存のたびに変わる情報（docProps の更新日時、計算チェーン、共有文字列の並び）は比較しない。セルの書式は
スタイル番号ではなく、フォント・塗りつぶし・罫線・表示形式の定義そのものを比べる。画像・図形・テーマ・
シート構成が変わった場合は差分として報告する。

制限：数式セル・結合セルの左上以外には書き込まない。書き込む値は文字列。新しく作るセルに書式は付かない。
終了コード：0 = 成功／差分は指示どおり、1 = 指示にない差分がある、2 = 指示が適用できない・入力が不正。
"""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import zipfile

NS_MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
ROW = re.compile(r'<row\b[^>]*?(?:/>|>.*?</row>)', re.S)
CELL = re.compile(r'<c\b[^>]*?(?:/>|>.*?</c>)', re.S)


class PatchError(Exception):
    pass


def attr(tag, name):
    found = re.search(r'\b' + re.escape(name) + r'="([^"]*)"', tag)
    return found.group(1) if found else None


def split_ref(ref):
    found = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]*)', ref)
    if not found or col_index(found.group(1)) > 16384 or int(found.group(2)) > 1048576:
        raise PatchError(f'セル番地が不正です：{ref}')
    return found.group(1), int(found.group(2))


def col_index(letters):
    index = 0
    for char in letters:
        index = index * 26 + ord(char) - 64
    return index


def col_letters(index):
    letters = ''
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def sheet_parts(zf):
    """Map sheet name -> part path."""
    rels = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
    targets = {}
    for rel in rels:
        target = rel.get('Target', '')
        targets[rel.get('Id')] = target.lstrip('/') if target.startswith('/') else str(PurePosixPath('xl') / target)
    book = ET.fromstring(zf.read('xl/workbook.xml'))
    return {sheet.get('name'): targets[sheet.get(f'{{{NS_REL}}}id')] for sheet in book.iter(f'{{{NS_MAIN}}}sheet')}


def shared_strings(zf):
    if 'xl/sharedStrings.xml' not in zf.namelist():
        return []
    root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
    texts = []
    for si in root.iter(f'{{{NS_MAIN}}}si'):
        # Direct <t> or rich-text runs <r><t>. Phonetic runs (<rPh>) hold furigana, not cell text.
        parts = [child.text or '' if child.tag == f'{{{NS_MAIN}}}t'
                 else ''.join(t.text or '' for t in child.iter(f'{{{NS_MAIN}}}t'))
                 for child in si if child.tag in (f'{{{NS_MAIN}}}t', f'{{{NS_MAIN}}}r')]
        texts.append(''.join(parts))
    return texts


def style_table(zf):
    """Resolved definition of every cell style index, so two workbooks can be compared after a re-save."""
    if 'xl/styles.xml' not in zf.namelist():
        return []
    root = ET.fromstring(zf.read('xl/styles.xml'))

    def children(name):
        node = root.find(f'{{{NS_MAIN}}}{name}')
        return [] if node is None else list(node)

    def canon(node):
        return ET.tostring(node, encoding='unicode') if node is not None else ''

    fonts, fills, borders = children('fonts'), children('fills'), children('borders')
    formats = {fmt.get('numFmtId'): fmt.get('formatCode') for fmt in children('numFmts')}
    table = []
    for xf in children('cellXfs'):
        def pick(items, key, xf=xf):
            index = int(xf.get(key, '0'))
            return canon(items[index]) if index < len(items) else ''
        number = xf.get('numFmtId', '0')
        table.append((pick(fonts, 'fontId'), pick(fills, 'fillId'), pick(borders, 'borderId'),
                      formats.get(number, number), ''.join(canon(child) for child in xf)))
    return table


def read_cells(xml, strings):
    """{ref: (text, style, formula)} with the formula expression and its shared/array attributes."""
    cells = {}
    data = re.search(r'<sheetData\b[^>]*?(?:/>|>(.*)</sheetData>)', xml, re.S)
    if data is None:
        raise PatchError('sheetData が見つかりません（対応していない形式のシートです）')
    for row in ROW.finditer(data.group(1) or ''):
        for cell in CELL.finditer(row.group(0)):
            raw = cell.group(0)
            head = raw[:raw.index('>') + 1]
            ref = attr(head, 'r')
            if ref is None:
                raise PatchError('番地（r 属性）のないセルがあります（対応していない形式のシートです）')
            node = ET.fromstring(raw.replace('<c ', f'<c xmlns="{NS_MAIN}" ', 1))
            kind = node.get('t')
            value = node.find(f'{{{NS_MAIN}}}v')
            if kind == 's' and value is not None:
                text = strings[int(value.text)]
            elif kind == 'inlineStr':
                text = ''.join(t.text or '' for t in node.iter(f'{{{NS_MAIN}}}t'))
            else:
                text = value.text or '' if value is not None else ''
            formula = node.find(f'{{{NS_MAIN}}}f')
            cells[ref] = (text, attr(head, 's'), None if formula is None else (formula.text, sorted(formula.attrib.items())))
    return cells


def merged_ranges(xml):
    ranges = []
    for found in re.finditer(r'<mergeCell\b[^>]*\bref="([A-Z]+)([0-9]+):([A-Z]+)([0-9]+)"', xml):
        c1, r1, c2, r2 = col_index(found.group(1)), int(found.group(2)), col_index(found.group(3)), int(found.group(4))
        ranges.append((c1, r1, c2, r2))
    return ranges


def plan_sheet(spec, cells, merges):
    """Resolve one sheet's instructions to {ref: new text}. Raises PatchError without side effects."""
    sheet = spec['sheet']
    planned = {}

    def text_of(ref):
        return planned.get(ref, cells.get(ref, ('', None, None))[0])

    def put(ref, change, label):
        letters, row = split_ref(ref)
        col = col_index(letters)
        new = change['to'] if isinstance(change, dict) else change
        if not isinstance(new, str):
            raise PatchError(f'{sheet}!{ref}（{label}）：書き込む値は文字列で指定してください')
        if text_of(ref) == new:
            return  # already as instructed, so applying the same instructions twice is harmless
        if isinstance(change, dict) and 'from' in change and text_of(ref) != change['from']:
            raise PatchError(f'{sheet}!{ref}（{label}）：現在の値が from と一致しません。'
                             f'from={change["from"]!r}、現在={text_of(ref)!r}')
        if cells.get(ref, ('', None, None))[2]:
            raise PatchError(f'{sheet}!{ref}（{label}）：数式セルには書き込みません')
        if any(c1 <= col <= c2 and r1 <= row <= r2 and (col, row) != (c1, r1) for c1, r1, c2, r2 in merges):
            raise PatchError(f'{sheet}!{ref}（{label}）：結合セルの左上以外には書き込みません')
        planned[ref] = new

    for ref, change in (spec.get('cells') or {}).items():
        if not isinstance(change, dict) or 'from' not in change or 'to' not in change:
            raise PatchError(f'{sheet}!{ref}：cells は {{"from": 現在の値, "to": 新しい値}} で指定してください')
        put(ref, change, 'cells')

    table = spec.get('table')
    if table:
        header_row = int(table.get('header_row', 1))
        headers = {}
        for ref, (text, _style, _formula) in cells.items():
            letters, row = split_ref(ref)
            if row == header_row and text.strip():
                if text.strip() in headers:
                    raise PatchError(f'{sheet}：見出し「{text.strip()}」が {header_row} 行目に複数あります')
                headers[text.strip()] = letters
        key = table.get('key')
        if key not in headers:
            raise PatchError(f'{sheet}：キー列「{key}」が {header_row} 行目の見出しにありません（見出し：{"、".join(headers) or "なし"}）')
        next_col = max((col_index(c) for c in headers.values()), default=0) + 1
        for name in table.get('add_columns') or []:
            if name not in headers:
                headers[name] = col_letters(next_col)
                put(f'{headers[name]}{header_row}', name, '列の追加')
                next_col += 1
        by_key = {}
        for ref, (text, _style, _formula) in cells.items():
            letters, row = split_ref(ref)
            if letters == headers[key] and row > header_row and text.strip():
                by_key.setdefault(text.strip(), []).append(row)
        for row_key, values in (table.get('rows') or {}).items():
            rows = by_key.get(row_key, [])
            if len(rows) != 1:
                raise PatchError(f'{sheet}：{key}「{row_key}」に一致する行が {len(rows)} 件あります（1 件である必要があります）')
            for name, change in values.items():
                if name not in headers:
                    raise PatchError(f'{sheet}：列「{name}」が見出しにありません（追加する場合は add_columns に書く）')
                put(f'{headers[name]}{rows[0]}', change, f'{key}={row_key}')
    return planned


def cell_xml(ref, text, style):
    style_attr = f' s="{style}"' if style is not None else ''
    return f'<c r="{ref}"{style_attr} t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def write_cells(xml, planned, cells):
    """Return the sheet XML with only the planned cells replaced or inserted."""
    by_row = {}
    for ref, text in planned.items():
        by_row.setdefault(split_ref(ref)[1], []).append((ref, text))

    def patch_row(row_xml, changes):
        head_end = row_xml.index('>') + 1
        head = row_xml[:head_end]
        if head.endswith('/>'):
            head, body, tail = head[:-2] + '>', '', '</row>'
        else:
            body, tail = row_xml[head_end:-len('</row>')], '</row>'
        for ref, text in sorted(changes, key=lambda change: col_index(split_ref(change[0])[0])):
            style = cells.get(ref, ('', None, None))[1]
            new, column = cell_xml(ref, text, style), col_index(split_ref(ref)[0])
            existing = next((c for c in CELL.finditer(body) if attr(c.group(0)[:c.group(0).index('>') + 1], 'r') == ref), None)
            if existing:
                body = body[:existing.start()] + new + body[existing.end():]
                continue
            # A new cell: keep column order, and drop the row's span hint, which would now be wrong.
            head = re.sub(r'\s+spans="[^"]*"', '', head)
            after = next((c for c in CELL.finditer(body)
                          if col_index(split_ref(attr(c.group(0)[:c.group(0).index('>') + 1], 'r'))[0]) > column), None)
            position = after.start() if after else len(body)
            body = body[:position] + new + body[position:]
        return head + body + tail

    data = re.search(r'<sheetData\b[^>]*?(/>|>(.*)</sheetData>)', xml, re.S)
    inner = data.group(2) or ''
    pieces, last, seen = [], 0, set()
    for row in ROW.finditer(inner):
        number = int(attr(row.group(0)[:row.group(0).index('>') + 1], 'r'))
        # Rows that do not exist yet go in before the first later row.
        for missing in sorted(n for n in by_row if n < number and n not in seen):
            pieces.append(patch_row(f'<row r="{missing}"/>', by_row[missing]))
            seen.add(missing)
        pieces.append(inner[last:row.start()])
        pieces.append(patch_row(row.group(0), by_row[number]) if number in by_row else row.group(0))
        seen.add(number)
        last = row.end()
    pieces.append(inner[last:])
    pieces.extend(patch_row(f'<row r="{n}"/>', by_row[n]) for n in sorted(by_row) if n not in seen)
    xml = xml[:data.start()] + '<sheetData>' + ''.join(pieces) + '</sheetData>' + xml[data.end():]

    dimension = re.search(r'<dimension\b[^>]*\bref="([A-Z]+)([0-9]+)(?::([A-Z]+)([0-9]+))?"[^>]*/>', xml)
    if dimension:
        first_col, first_row = col_index(dimension.group(1)), int(dimension.group(2))
        last_col = col_index(dimension.group(3)) if dimension.group(3) else first_col
        last_row = int(dimension.group(4)) if dimension.group(4) else first_row
        for ref in planned:
            letters, row = split_ref(ref)
            first_col, last_col = min(first_col, col_index(letters)), max(last_col, col_index(letters))
            first_row, last_row = min(first_row, row), max(last_row, row)
        new_ref = f'{col_letters(first_col)}{first_row}:{col_letters(last_col)}{last_row}'
        xml = xml[:dimension.start()] + re.sub(r'\bref="[^"]*"', f'ref="{new_ref}"', dimension.group(0)) + xml[dimension.end():]
    return xml


def outside_cells(xml):
    """The sheet XML without the parts apply may touch: cell data, the dimension hint and row span hints."""
    xml = re.sub(r'<sheetData\b[^>]*?(?:/>|>.*</sheetData>)', '<sheetData/>', xml, flags=re.S)
    return re.sub(r'<dimension\b[^>]*/>', '', xml)


def load_specs(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        raise PatchError(f'変更指示を読めません：{error}') from error
    specs = data if isinstance(data, list) else [data]
    for spec in specs:
        if not isinstance(spec, dict) or not isinstance(spec.get('sheet'), str):
            raise PatchError('変更指示には "sheet"（シート名）が必要です')
        unknown = set(spec) - {'sheet', 'cells', 'table'}
        if unknown:
            raise PatchError(f'変更指示に不明な項目があります：{sorted(unknown)}')
    names = [spec['sheet'] for spec in specs]
    if len(names) != len(set(names)):
        raise PatchError('同じシートの変更指示は 1 つにまとめてください')
    return specs


def build_plan(book, specs):
    """Return ({part: (sheet, {ref: text}, cells, xml)}) for every sheet that actually changes."""
    plan = {}
    with zipfile.ZipFile(book) as zf:
        parts, strings = sheet_parts(zf), shared_strings(zf)
        for spec in specs:
            if spec['sheet'] not in parts:
                raise PatchError(f'シート「{spec["sheet"]}」がありません（シート：{"、".join(parts)}）')
            xml = zf.read(parts[spec['sheet']]).decode('utf-8')
            cells = read_cells(xml, strings)
            planned = plan_sheet(spec, cells, merged_ranges(xml))
            if planned:
                plan[parts[spec['sheet']]] = (spec['sheet'], planned, cells, xml)
    return plan


def apply(book, specs, out=None, dry_run=False, log=print):
    plan = build_plan(book, specs)
    for sheet, planned, cells, _xml in plan.values():
        for ref in sorted(planned, key=lambda r: (split_ref(r)[1], col_index(split_ref(r)[0]))):
            log(f'{sheet}!{ref}：{cells.get(ref, ("",))[0]!r} → {planned[ref]!r}')
    if not plan:
        log('変更はありません（すべて指示どおりの値になっています）')
        return 0
    if dry_run:
        log(f'{sum(len(p[1]) for p in plan.values())} セルを変更します（--dry-run のため書き込んでいません）')
        return 0
    target = Path(out or book)
    handle, temp = tempfile.mkstemp(suffix='.xlsx', dir=str(target.parent))
    os.close(handle)
    try:
        with zipfile.ZipFile(book) as src, zipfile.ZipFile(temp, 'w') as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename in plan:
                    _sheet, planned, cells, xml = plan[info.filename]
                    data = write_cells(xml, planned, cells).encode('utf-8')
                dst.writestr(info, data, compress_type=info.compress_type)
        problems = compare(book, temp, expected={part: p[1] for part, p in plan.items()})[1]
        if problems:
            raise PatchError('書き込み結果が指示と一致しません（ファイルは変更していません）：' + '；'.join(problems[:5]))
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    log(f'{sum(len(p[1]) for p in plan.values())} セルを変更しました：{target}')
    return 0


def compare(before, after, expected=None):
    """Return (changes, problems). expected maps a sheet part to {ref: text}; None means "report only"."""
    changes, problems = [], []
    with zipfile.ZipFile(before) as a, zipfile.ZipFile(after) as b:
        names_a, names_b = a.namelist(), b.namelist()
        parts_a, parts_b = sheet_parts(a), sheet_parts(b)
        if parts_a != parts_b:
            problems.append('シート構成が変わっています')
        sheet_of = {part: name for name, part in parts_b.items()}
        strings_a, strings_b = shared_strings(a), shared_strings(b)
        styles_a, styles_b = style_table(a), style_table(b)

        def style(table, index):
            index = int(index or 0)
            return table[index] if index < len(table) else index
        for name in sorted(set(names_a) | set(names_b)):
            if name not in names_a or name not in names_b:
                problems.append(f'ファイルの{"追加" if name not in names_a else "削除"}：{name}')
                continue
            if name not in sheet_of:
                # Rewritten on every save, or judged through the cells: metadata, calculation chain,
                # shared strings (cell text) and the style table (resolved per cell below).
                volatile = name.startswith('docProps/') or name in ('xl/sharedStrings.xml', 'xl/calcChain.xml', 'xl/styles.xml')
                if a.read(name) != b.read(name) and not volatile:
                    problems.append(f'シート以外のファイルが変わっています：{name}')
                continue
            xml_a, xml_b = a.read(name).decode('utf-8'), b.read(name).decode('utf-8')
            if xml_a == xml_b and strings_a == strings_b and styles_a == styles_b and name not in (expected or {}):
                continue
            cells_a, cells_b = read_cells(xml_a, strings_a), read_cells(xml_b, strings_b)
            wanted = (expected or {}).get(name, {})
            for ref in sorted(set(cells_a) | set(cells_b), key=lambda r: (split_ref(r)[1], col_index(split_ref(r)[0]))):
                old, new = cells_a.get(ref, ('', None, None)), cells_b.get(ref, ('', None, None))
                label = f'{sheet_of[name]}!{ref}'
                if old[0] != new[0]:
                    changes.append(f'{label}：{old[0]!r} → {new[0]!r}')
                    if expected is not None and wanted.get(ref) != new[0]:
                        problems.append(f'指示にない変更：{label}：{old[0]!r} → {new[0]!r}')
                if old[2] != new[2] or style(styles_a, old[1]) != style(styles_b, new[1]):
                    problems.append(f'書式または数式が変わっています：{label}')
                elif old[0] == new[0] and (ref in cells_a) != (ref in cells_b) and ref not in wanted:
                    problems.append(f'空のセルの{"追加" if ref in cells_b else "削除"}：{label}')
            for ref, text in wanted.items():
                if cells_b.get(ref, ('', None, None))[0] != text:
                    problems.append(f'指示どおりになっていません：{sheet_of[name]}!{ref}（期待 {text!r}、実際 {cells_b.get(ref, ("",))[0]!r}）')
            if outside_cells(xml_a) != outside_cells(xml_b):
                problems.append(f'セル以外の定義（列幅・結合・枠固定など）が変わっています：{sheet_of[name]}')
        for name in expected or {}:
            if name not in names_b:
                problems.append(f'対象のシートがありません：{name}')
    return changes, problems


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    apply_cmd = sub.add_parser('apply', help='変更指示どおりに書き換える')
    apply_cmd.add_argument('book', type=Path)
    apply_cmd.add_argument('patch', type=Path)
    apply_cmd.add_argument('--out', type=Path, help='別のファイルに保存する（既定は上書き）')
    apply_cmd.add_argument('--dry-run', action='store_true', help='変更内容を表示するだけで書き込まない')
    diff_cmd = sub.add_parser('diff', help='2 つのブックの差分を表示する')
    diff_cmd.add_argument('before', type=Path)
    diff_cmd.add_argument('after', type=Path)
    diff_cmd.add_argument('--expect', type=Path, help='変更指示。これにない差分があれば終了コード 1')
    args = parser.parse_args(argv)
    try:
        if args.command == 'apply':
            return apply(args.book, load_specs(args.patch), args.out, args.dry_run)
        expected = None
        if args.expect:
            expected = {part: plan[1] for part, plan in build_plan(args.before, load_specs(args.expect)).items()}
        changes, problems = compare(args.before, args.after, expected)
        for line in changes:
            print(line)
        for line in problems:
            print(f'NG  {line}')
        if not changes and not problems:
            print('差分はありません')
        # Without --expect this is a report; with it, anything outside the instructions fails.
        return 1 if problems and expected is not None else 0
    except (PatchError, OSError, zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        print(f'エラー：{error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
