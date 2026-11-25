#!/usr/bin/env python3
"""JUnit の実行結果から単体テスト成績書（Markdown と Excel）を作る。

    ./mvnw test   （または verify）を実行したあとで：
    python scripts/junit_report.py [--out target/test-report] [--title <システム名>]

Maven の target/surefire-reports/ と target/failsafe-reports/（複数モジュールは各モジュールの target/ も）の
TEST-*.xml を読み、次を書き出す：

    <out>/単体テスト成績書.md     集計と結果一覧（AI とレビューはこれを読む）
    <out>/単体テスト成績書.xlsx   同じ内容の Excel（人が提出・保管する）

観点の列は、テストのソースの @DisplayName（クラスとメソッド）から取る。ない場合はメソッド名になる。
成績書の 1 行は 1 回の実行結果であり、手で編集しない。結果を変えたい場合はテストかコードを直して再実行する。
終了コード：0 = 作成した（すべて成功）、1 = 作成した（失敗・エラーがある）、2 = 結果のファイルがない・読めない。
標準ライブラリのみを使用する（Python 3.9+）。
"""
import argparse
import datetime
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import zipfile

REPORT_DIRS = ('surefire-reports', 'failsafe-reports')
NAME = '単体テスト成績書'
RESULTS = {'ok': 'OK', 'failure': 'NG', 'error': 'NG（エラー）', 'skipped': 'スキップ'}
DISPLAY_NAME = re.compile(r'@DisplayName\(\s*"((?:[^"\\]|\\.)*)"\s*\)')


class ReportError(Exception):
    pass


def report_files(root):
    found = []
    for target in [root / 'target', *sorted(p for p in root.glob('*/target') if p.is_dir()),
                   *sorted(p for p in root.glob('*/*/target') if p.is_dir())]:
        for name in REPORT_DIRS:
            found += sorted((target / name).glob('TEST-*.xml'))
    return found


def java_string(literal):
    """The value of a Java string literal's body (\\" \\\\ \\n \\t \\uXXXX)."""
    plain = {'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f'}
    return re.sub(r'\\(u+[0-9a-fA-F]{4}|.)', lambda m: chr(int(m.group(1).lstrip('u'), 16)) if m.group(1)[0] == 'u' and len(m.group(1)) > 1
                  else plain.get(m.group(1), m.group(1)), literal)


def source_names(root, classname):
    """(class display name, {method: display name}) from the test source, if it can be found."""
    rel = Path(*classname.split('$')[0].split('.')).with_suffix('.java')
    candidates = [p for p in [root / 'src/test/java' / rel, *root.glob(f'*/src/test/java/{rel.as_posix()}'),
                              *root.glob(f'*/*/src/test/java/{rel.as_posix()}')] if p.is_file()]
    if not candidates:
        return '', {}
    text = candidates[0].read_text(encoding='utf-8', errors='replace')
    methods = {}
    for match in DISPLAY_NAME.finditer(text):
        after = text[match.end():match.end() + 400]
        method = re.search(r'\bvoid\s+(\w+)\s*\(', after)
        klass = re.search(r'\bclass\s+(\w+)', after)
        if klass and (not method or klass.start() < method.start()):
            if klass.group(1) == classname.split('.')[-1].split('$')[-1]:
                methods.setdefault('', java_string(match.group(1)))
        elif method:
            methods.setdefault(method.group(1), java_string(match.group(1)))
    return methods.pop('', ''), methods


def read_reports(root, files):
    cases = []
    for path in files:
        try:
            suite = ET.parse(path).getroot()
        except ET.ParseError as error:
            raise ReportError(f'{path} を読めません：{error}') from None
        for case in suite.iter('testcase'):
            classname = case.get('classname') or suite.get('name') or ''
            method = re.sub(r'[(\[].*$', '', case.get('name') or '')
            class_label, labels = source_names(root, classname)
            result, detail = 'ok', ''
            for kind in ('failure', 'error', 'skipped'):
                node = case.find(kind)
                if node is not None:
                    lines = (node.text or '').strip().splitlines()
                    result, detail = kind, node.get('message') or (lines[0] if lines else '')
                    break
            cases.append({'class': classname, 'class_label': class_label, 'method': case.get('name') or '',
                          'label': labels.get(method, '') or method, 'result': result,
                          'time': float(case.get('time') or 0), 'detail': ' '.join(detail.split())[:300],
                          'report': path.relative_to(root).as_posix()})
    return cases


def commit(root):
    git = shutil.which('git')
    if not git:
        return ''
    head = subprocess.run([git, '-C', str(root), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True)
    if head.returncode != 0:
        return ''
    dirty = subprocess.run([git, '-C', str(root), 'status', '--porcelain', '--untracked-files=no'],
                           capture_output=True, text=True).stdout.strip()
    return head.stdout.strip() + ('（未コミットの変更あり）' if dirty else '')


def summary(cases, files, root, title):
    count = {kind: sum(1 for c in cases if c['result'] == kind) for kind in RESULTS}
    stamps = [datetime.datetime.fromtimestamp(f.stat().st_mtime) for f in files]
    return [('対象', title or root.name), ('実行日時', max(stamps).strftime('%Y-%m-%d %H:%M') if stamps else ''),
            ('コミット', commit(root)), ('テストクラス', len({c['class'] for c in cases})), ('ケース', len(cases)),
            ('OK', count['ok']), ('NG', count['failure'] + count['error']), ('スキップ', count['skipped']),
            ('実行時間（秒）', round(sum(c['time'] for c in cases), 3)),
            ('判定', '合格' if count['failure'] + count['error'] == 0 and cases else '不合格')]


HEADERS = ('No.', 'テストクラス', '観点', 'メソッド', '結果', '時間（秒）', '失敗の内容')


def rows_of(cases):
    return [(i, (c['class_label'] + '（' + c['class'].split('.')[-1] + '）') if c['class_label'] else c['class'].split('.')[-1],
             c['label'], c['method'], RESULTS[c['result']], round(c['time'], 3), c['detail'])
            for i, c in enumerate(cases, 1)]


def markdown(info, rows):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', '<br>')

    lines = [f'# {NAME}', '', '生成物：`scripts/junit_report.py`。手で編集しない。', '', '| 項目 | 値 |', '|---|---|']
    lines += [f'| {k} | {cell(v)} |' for k, v in info]
    lines += ['', '## 結果一覧', '', '| ' + ' | '.join(HEADERS) + ' |', '|' + '---|' * len(HEADERS)]
    lines += ['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows]
    return '\n'.join(lines) + '\n'


# Minimal SpreadsheetML: inline strings, four styles (default, header, body, NG), widths, frozen header, filter.
STYLES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="3"><font><sz val="10"/><name val="Meiryo UI"/></font><font><b/><sz val="10"/><name val="Meiryo UI"/></font><font><sz val="10"/><color rgb="FFC00000"/><name val="Meiryo UI"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFDDEBF7"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''


def column(index):
    letters = ''
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def sheet_xml(rows, widths, header_style=True, ng_column=None):
    out = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, value in enumerate(row, 1):
            ref = f'{column(c)}{r}'
            style = 1 if r == 1 and header_style else 3 if ng_column and c == ng_column and str(value).startswith('NG') else 2
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}" s="{style}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>')
        out.append(f'<row r="{r}">{"".join(cells)}</row>')
    cols = ''.join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, 1))
    last = f'{column(len(widths))}{max(len(rows), 1)}'
    pane = ('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            '</sheetView></sheetViews>' if header_style else '<sheetViews><sheetView workbookViewId="0"/></sheetViews>')
    auto = f'<autoFilter ref="A1:{last}"/>' if header_style and len(rows) > 1 else ''
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="A1:{last}"/>{pane}<cols>{cols}</cols><sheetData>{"".join(out)}</sheetData>{auto}</worksheet>')


def write_xlsx(path, sheets):
    """sheets: [(name, xml)]."""
    rels = ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                   f'Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml',
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Default Extension="xml" ContentType="application/xml"/>'
                    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                    + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                              'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                              for i in range(1, len(sheets) + 1)) + '</Types>')
        zf.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                    'Target="xl/workbook.xml"/></Relationships>')
        zf.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                    + ''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _x) in enumerate(sheets, 1))
                    + '</sheets></workbook>')
        zf.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + rels
                    + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
                      'Target="styles.xml"/></Relationships>')
        zf.writestr('xl/styles.xml', STYLES)
        for i, (_name, xml) in enumerate(sheets, 1):
            zf.writestr(f'xl/worksheets/sheet{i}.xml', xml)


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1], help='プロジェクトのルート')
    parser.add_argument('--out', type=Path, help='出力先（既定 <root>/target/test-report）')
    parser.add_argument('--title', help='成績書の「対象」に書く名前（既定はディレクトリ名）')
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    files = report_files(root)
    try:
        if not files:
            raise ReportError('TEST-*.xml がありません。先に ./mvnw test（または verify）を実行する')
        cases = read_reports(root, files)
    except (ReportError, OSError) as error:
        print(f'junit_report: 作成できません：{error}', file=sys.stderr)
        return 2
    info, rows = summary(cases, files, root, args.title), rows_of(cases)
    out = (args.out or root / 'target/test-report').resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / f'{NAME}.md').write_text(markdown(info, rows), encoding='utf-8', newline='\n')
    write_xlsx(out / f'{NAME}.xlsx', [
        ('集計', sheet_xml([('項目', '値'), *info], (18, 48))),
        ('結果一覧', sheet_xml([HEADERS, *rows], (6, 36, 48, 32, 12, 10, 60), ng_column=5)),
    ])
    failed = sum(1 for c in cases if c['result'] in ('failure', 'error'))
    print(f'junit_report: {len(cases)} ケース（NG {failed}）の成績書を作成しました：{out / NAME}.md / .xlsx')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
