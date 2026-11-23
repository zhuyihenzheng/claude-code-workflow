#!/usr/bin/env python3
"""Excel 設計書を AI と人が少ないトークンで読める形式に変換する（増分変換）。

    python scripts/xlsx2ai.py [SRC_DIR] [OUT_DIR] [--check] [--extract-media]

既定は SRC_DIR=specs、OUT_DIR=specs-ai。ブックごとに次を生成する：

    OUT_DIR/index.md                 全ブックの目次（AI はここから読む）
    OUT_DIR/<book>/index.md          シート一覧（文字数・図形フロー・画像の有無）
    OUT_DIR/<book>/sheets/<sheet>.md     表は Markdown の表、地の文は字下げどおりの箇条書き（まずこれを読む）
    OUT_DIR/<book>/sheets/<sheet>.json   ExStruct light：空セルを除いた値と行列番号（セル位置が必要なとき）
    OUT_DIR/<book>/flows/<sheet>.mmd     図形＋コネクタで描かれたフロー図（excel2md）
    OUT_DIR/<book>/media/*           --extract-media 指定時のみ：貼り付け画像（フロー図の画像など）

同じ名前のブック（a.xlsx と a.xlsm、大文字・小文字だけが異なる名前）は、出力先を
<book>-xlsx / <book>-xlsm として区別する。それでも重複する場合は終了コード 2 を返す。

変換はローカルで行い、モデルのトークンは消費しない。SHA-256 が変わったブックだけを
再変換し、削除されたブックの出力も削除する。--check は書き込まずに古い出力を報告し、
古いものがあれば終了コード 1 を返す（CI 用）。

依存：pip install "exstruct==0.9.1" "excel2md==2.3.0"
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

SUFFIXES = {'.xlsx', '.xlsm'}
MANIFEST = '.manifest.json'
NS_MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
TOOL_CODE = {
    'exstruct': 'import sys; from exstruct.cli.main import main; sys.exit(main())',
    'excel2md': 'import sys; from excel2md.cli import main; sys.exit(main())',
}
# Bump when the output layout changes so every book is regenerated.
FORMAT_VERSION = 2


class ConversionError(RuntimeError):
    pass


def tool(name, *args):
    """Run exstruct / excel2md from PATH or from this interpreter's packages."""
    exe = shutil.which(name)
    cmd = [exe, *args] if exe else [sys.executable, '-c', TOOL_CODE[name], *args]
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
    except OSError as error:
        raise ConversionError(f'{name} を起動できません：{error}') from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ['']
        if 'No module named' in detail[0]:
            detail = [f'{name} が未インストールです（pip install "exstruct==0.9.1" "excel2md==2.3.0"）']
        raise ConversionError(f'{name} が失敗しました：{detail[0]}')
    return result


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def book_keys(src, paths):
    """Map a stable output directory name to each workbook: its relative path without
    the suffix, '/' kept as folders. Books that would share a directory (a.xlsx next to
    a.xlsm, or names differing only in case) get '-xlsx' / '-xlsm' appended instead, so
    none is dropped. The suffix is not kept as '.xlsx': Read(/**/*.xlsx) is denied."""
    def stem(path):
        return path.relative_to(src).with_suffix('').as_posix()
    shared = {}
    for path in paths:
        shared.setdefault(stem(path).casefold(), []).append(path)
    keys = {}
    for path in paths:
        key = stem(path)
        if len(shared[key.casefold()]) > 1:
            key += '-' + path.suffix[1:].lower()
        clash = next((other for other in keys if other.casefold() == key.casefold()), None)
        if clash is not None:
            raise ConversionError(f'出力先が重複します：{keys[clash]} と {path}。どちらかのファイル名を変更してください。')
        keys[key] = path
    return keys


def find_books(src):
    return sorted(p for p in src.rglob('*')
                  if p.is_file() and p.suffix.lower() in SUFFIXES and not p.name.startswith('~$'))


def _rels(zf, part):
    """Map relationship id -> target part path for an OOXML part."""
    pure = PurePosixPath(part)
    rels_path = str(pure.parent / '_rels' / (pure.name + '.rels'))
    if rels_path not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read(rels_path))
    result = {}
    for rel in root:
        target = rel.get('Target', '')
        if rel.get('TargetMode') == 'External':
            continue
        resolved = target.lstrip('/') if target.startswith('/') else os.path.normpath(str(pure.parent / target)).replace('\\', '/')
        result[rel.get('Id')] = resolved
    return result


def inspect_drawings(path):
    """Return {sheet name: {"shapes": n, "connectors": n, "pictures": n}} from DrawingML parts."""
    stats = {}
    with zipfile.ZipFile(path) as zf:
        workbook = ET.fromstring(zf.read('xl/workbook.xml'))
        book_rels = _rels(zf, 'xl/workbook.xml')
        for sheet in workbook.iter(f'{{{NS_MAIN}}}sheet'):
            name = sheet.get('name')
            part = book_rels.get(sheet.get(f'{{{NS_REL}}}id'))
            counts = {'shapes': 0, 'connectors': 0, 'pictures': 0}
            if part and part in zf.namelist():
                sheet_rels = _rels(zf, part)
                root = ET.fromstring(zf.read(part))
                for drawing in root.iter(f'{{{NS_MAIN}}}drawing'):
                    target = sheet_rels.get(drawing.get(f'{{{NS_REL}}}id'))
                    if target and target in zf.namelist():
                        xml = zf.read(target).decode('utf-8', 'replace')
                        counts['shapes'] += len(re.findall(r'<(?:\w+:)?sp[ >]', xml))
                        counts['connectors'] += len(re.findall(r'<(?:\w+:)?cxnSp[ >]', xml))
                        counts['pictures'] += len(re.findall(r'<(?:\w+:)?pic[ >]', xml))
            stats[name] = counts
    return stats


def safe_name(name):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name).strip() or '_'


def extract_flows(path, sheets):
    """Mermaid blocks from excel2md's shape detection, keyed by sheet name."""
    if not sheets:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'flows.md'
        tool('excel2md', str(path), '-o', str(out), '--mermaid-enabled', '--mermaid-detect-mode', 'shapes',
             '--no-csv-markdown-enabled')
        text = out.read_text(encoding='utf-8')
    flows = {}
    for section in re.split(r'^## ', text, flags=re.M)[1:]:
        title, _, body = section.partition('\n')
        title = title.strip()
        if title in sheets:
            blocks = re.findall(r'```mermaid\n(.*?)```', body, re.S)
            if blocks:
                flows[title] = '\n'.join(block.strip() + '\n' for block in blocks)
    return flows


# シートの Markdown：ExStruct の行（空セルを除いた値と列番号）から、表と地の文を復元する。
# 表：見出し行と、同じ左端の列から始まり見出し行の列に収まる行の並び（2 段の見出し、結合で生じた 2 行までの空行を許す）。
#     値が 1 つだけの行（番号・記号を除く）は表の終わりとみなす。
# 地の文：字下げ（左端の列）の深さに応じた箇条書き。番号や記号で始まる 1 セルの行は見出しにする。
HEADING = re.compile(r'^(?:\d+(?:\.\d+)*[.．]?\s|[■□◆◇●【≪＜〈《\[])')
BULLETS = {'・', '-', '－', '*', '＊', '●', '○'}
MARKER = re.compile(r'^(?:[・※\-－*＊●○]|[①-⑳]|\(?\d+\)|[0-9]+[.．、]?)$')
MAX_GAP = 2
HTML_TAG = re.compile(r'<(?=[A-Za-z/!])')


def cell_text(value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text[:-9] if re.fullmatch(r'\d{4}-\d{2}-\d{2} 00:00:00', text) else text


def row_cells(row):
    items = sorted((int(col), cell_text(value)) for col, value in row.get('c', {}).items())
    return [(col, value) for col, value in items if value]


def table_header(rows):
    """(列ごとの見出し, 見出しの行数)。rows が表でなければ None。"""
    first = rows[0][1]
    if len(first) < 2 or MARKER.match(first[0][1]):
        return None
    start = first[0][0]
    labels, body, count = dict(first), rows[1:], 1
    if body and body[0][1][0][0] > start and len(body[0][1]) >= 2:
        sub, parent, merged = dict(body[0][1]), '', {}
        for col in sorted(set(labels) | set(sub)):
            parent = labels.get(col, parent)
            merged[col] = f'{parent}/{sub[col]}' if col in sub and parent else sub.get(col) or labels[col]
        labels, body, count = merged, body[1:], 2
    if not body:
        return None
    for _, cells in body:
        if cells[0][0] != start or not {col for col, _ in cells} <= set(labels):
            return None
        if len(cells) == 1 and not MARKER.match(cells[0][1]):
            return None
    return labels, count


def is_title(text, marked=False):
    """見出しになる 1 セルの行。文（。で終わる）は見出しにしない。"""
    return not text.endswith('。') and (not marked or bool(HEADING.match(text)))


def md_text(text):
    return HTML_TAG.sub(r'\\<', text)


def table_lines(rows, labels, count):
    cols = sorted(labels)

    def line(values):
        return '| ' + ' | '.join(md_text(values.get(col, '')).replace('|', '\\|').replace('\n', '<br>') for col in cols) + ' |'

    return [line(labels), '|' + '---|' * len(cols)] + [line(dict(cells)) for _, cells in rows[count:]]


def run_end(rows, i):
    j = i + 1
    while j < len(rows) and rows[j][0] - rows[j - 1][0] <= MAX_GAP + 1:
        j += 1
    return j


def table_at(rows, i):
    for k in range(run_end(rows, i), i + 1, -1):
        if (header := table_header(rows[i:k])):
            return k, header
    return None


def sheet_markdown(name, sheet_rows, flows=''):
    """ExStruct light のシート 1 枚を Markdown にする。"""
    rows = [(row['r'], cells) for row in sorted(sheet_rows, key=lambda row: row['r']) if (cells := row_cells(row))]
    heading_cols = sorted({cells[0][0] for _, cells in rows if len(cells) == 1 and is_title(cells[0][1], True)})
    out, stack, i = [f'# {md_text(name)}', ''], [], 0
    while i < len(rows):
        if (found := table_at(rows, i)):
            k, (labels, count) = found
            out += ([''] if out[-1] else []) + table_lines(rows[i:k], labels, count) + ['']
            stack, i = [], k
            continue
        cells = rows[i][1]
        if len(cells) > 1 and cells[0][1] in BULLETS:
            cells = cells[1:]
        joined = md_text(' '.join(value.replace('\n', ' ') for _, value in cells))
        if len(rows[i][1]) == 1 and is_title(joined, True):
            level = min(2 + heading_cols.index(cells[0][0]), 6)
            out += ([''] if out[-1] else []) + ['#' * level + ' ' + joined, '']
            stack = []
        elif len(rows[i][1]) == 1 and is_title(joined) and table_at(rows, i + 1):
            out += ([''] if out[-1] else []) + [f'**{joined}**']
            stack = []
        else:
            col = rows[i][1][0][0]
            while stack and stack[-1] > col:
                stack.pop()
            if not stack or stack[-1] < col:
                stack.append(col)
            out.append('  ' * (len(stack) - 1) + '- ' + joined)
        i += 1
    if flows:
        out += ['', '```mermaid', flows.strip(), '```']
    return '\n'.join(out).strip() + '\n'


def convert(path, dest, extract_media):
    """Convert one workbook into dest (a fresh directory). Returns the per-book summary."""
    sheets_dir = dest / 'sheets'
    sheets_dir.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        tool('exstruct', str(path), '-m', 'light', '-f', 'json', '-o', str(Path(tmp) / 'book.json'),
             '--sheets-dir', str(sheets_dir))
    drawings = inspect_drawings(path)
    flow_sheets = {name for name, c in drawings.items() if c['connectors']}
    flows = extract_flows(path, flow_sheets)
    if flows:
        (dest / 'flows').mkdir()
        for name, mermaid in flows.items():
            (dest / 'flows' / f'{safe_name(name)}.mmd').write_text(mermaid, encoding='utf-8', newline='\n')
    media = []
    with zipfile.ZipFile(path) as zf:
        media = sorted(n for n in zf.namelist() if n.startswith('xl/media/'))
        if extract_media and media:
            (dest / 'media').mkdir()
            for name in media:
                (dest / 'media' / PurePosixPath(name).name).write_bytes(zf.read(name))
    rows = []
    for json_file in sorted(sheets_dir.glob('*.json')):
        raw = json_file.read_text(encoding='utf-8')
        data = json.loads(raw)
        name = data.get('sheet_name') or json_file.stem
        markdown = sheet_markdown(name, (data.get('sheet') or {}).get('rows') or [], flows.get(name, ''))
        md_file = json_file.with_suffix('.md')
        md_file.write_text(markdown, encoding='utf-8', newline='\n')
        rows.append({'sheet': name, 'file': f'sheets/{json_file.name}', 'md': f'sheets/{md_file.name}',
                     'chars': len(raw), 'md_chars': len(markdown)})
    return {'sheets': rows, 'drawings': drawings, 'flows': sorted(flows), 'media': len(media)}


def md_link(text, target):
    """Markdown link that survives brackets and spaces in Excel book / sheet names."""
    return '[' + re.sub(r'([\\\[\]|])', r'\\\1', text) + '](<' + target + '>)'


def write_book_index(dest, source_rel, summary):
    lines = [f'# {source_rel}', '',
             '生成物：`scripts/xlsx2ai.py`。手で編集しない。原本の Excel を直接読まず、必要なシートだけを開く。', '',
             '| シート | Markdown | JSON | 文字数 | 図形フロー | 画像 |', '|---|---|---|---:|---|---:|']
    for row in summary['sheets']:
        d = summary['drawings'].get(row['sheet'], {})
        mmd = f"flows/{safe_name(row['sheet'])}.mmd"
        flow = md_link(mmd, mmd) if row['sheet'] in summary['flows'] else ''
        sheet = row['sheet'].replace('|', '\\|')
        lines.append(f"| {sheet} | {md_link(row['md'], row['md'])} | {md_link(row['file'], row['file'])} | "
                     f"{row['md_chars']:,} | {flow} | {d.get('pictures', 0)} |")
    lines += ['', 'まず Markdown を読む。表は Markdown の表、地の文は字下げどおりの箇条書き、図形フローは Mermaid で入っている。',
              'セルの位置が必要なとき（`xlsx_patch.py` の変更指示を書くときなど）だけ JSON を読む。'
              'JSON は空セルを除いた `{"r": 行, "c": {列: 値}}`（0 始まりの列番号）で、結合セルの範囲は含まない。']
    if summary['flows']:
        lines.append('図形フローの分岐ラベル（はい／いいえ等）は独立ノードとして出ることがある。原本と照合して辺に付け直す。')
    if summary['media']:
        lines.append(f"貼り付け画像 {summary['media']} 件。画像のフロー図は `--extract-media` で取り出し、"
                     'Mermaid に起こしてレビューしたうえで別ファイルとして管理する。')
    (dest / 'index.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')


def write_root_index(out, manifest):
    lines = ['# Excel 設計書インデックス', '',
             '`scripts/xlsx2ai.py` の生成物。AI はここから必要なブック → シートだけを読む。', '',
             '| 原本 | 目次 | シート数 | 文字数 |', '|---|---|---:|---:|']
    for key, entry in sorted(manifest['books'].items()):
        source = entry['source'].replace('|', '\\|')
        lines.append(f"| {source} | {md_link(key + '/index.md', key + '/index.md')} | {entry['sheet_count']} | {entry['chars']:,} |")
    (out / 'index.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')


def load_manifest(out):
    try:
        data = json.loads((out / MANIFEST).read_text(encoding='utf-8'))
        if data.get('format') == FORMAT_VERSION and isinstance(data.get('books'), dict):
            return data
    except (OSError, ValueError):
        pass
    return {'format': FORMAT_VERSION, 'books': {}}


def run(src, out, check=False, extract_media=False, log=print):
    src, out = Path(src), Path(out)
    if not src.is_dir():
        raise ConversionError(f'入力ディレクトリがありません：{src}')
    manifest = load_manifest(out)
    books = book_keys(src, find_books(src))
    stale, failures = [], []
    for key, path in books.items():
        digest = sha256(path)
        entry = manifest['books'].get(key)
        if entry and entry['sha256'] == digest and (out / key / 'index.md').is_file() \
                and (not extract_media or entry.get('media_extracted') or not entry.get('media')):
            continue
        stale.append(key)
        if check:
            log(f'古い出力：{path}')
            continue
        dest = out / key
        tmp = out / f'.{PurePosixPath(key).name}.tmp'
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            summary = convert(path, tmp, extract_media)
            write_book_index(tmp, path.relative_to(src).as_posix(), summary)
        except Exception as error:  # one broken book must not block the others
            shutil.rmtree(tmp, ignore_errors=True)
            reason = error if isinstance(error, ConversionError) else f'{type(error).__name__}: {error}'
            failures.append(key)
            log(f'失敗：{path}：{reason}')
            continue
        shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp.rename(dest)
        manifest['books'][key] = {
            'source': path.relative_to(src).as_posix(), 'sha256': digest,
            'sheet_count': len(summary['sheets']), 'chars': sum(r['md_chars'] for r in summary['sheets']),
            'flows': summary['flows'], 'media': summary['media'], 'media_extracted': extract_media,
        }
        log(f"変換：{path} → {dest}（{len(summary['sheets'])} シート、フロー {len(summary['flows'])}）")
    removed = sorted(set(manifest['books']) - set(books))
    for key in removed:
        stale.append(key)
        if check:
            log(f'原本のない出力：{out / key}')
            continue
        shutil.rmtree(out / key, ignore_errors=True)
        del manifest['books'][key]
        log(f'削除：{out / key}')
    if check:
        return 1 if stale else 0
    if len(stale) > len(failures) or not (out / 'index.md').is_file():
        out.mkdir(parents=True, exist_ok=True)
        write_root_index(out, manifest)
        (out / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + '\n',
                                    encoding='utf-8', newline='\n')
    converted = len(stale) - len(removed) - len(failures)
    log(f'完了：{len(books)} ブック中 {converted} 件を変換、{len(removed)} 件を削除、{len(failures)} 件が失敗')
    return 2 if failures else 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('src', nargs='?', default='specs', type=Path, help='Excel 設計書のディレクトリ（既定 specs）')
    parser.add_argument('out', nargs='?', default='specs-ai', type=Path, help='出力ディレクトリ（既定 specs-ai）')
    parser.add_argument('--check', action='store_true', help='書き込まずに古い出力を報告し、あれば終了コード 1')
    parser.add_argument('--extract-media', action='store_true', help='貼り付け画像を <book>/media/ に取り出す')
    args = parser.parse_args(argv)
    try:
        return run(args.src, args.out, check=args.check, extract_media=args.extract_media)
    except ConversionError as error:
        print(f'エラー：{error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
