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

変換はローカルで行い、モデルのトークンは消費しない。原本が更新された場合や生成ファイルが欠けた場合は
該当するブックを再変換し、削除されたブックの出力も削除する。--check は書き込まずに古い出力を報告し、
古いものがあれば終了コード 1 を返す（CI 用）。

依存：pip install "exstruct==0.9.1" "excel2md==2.3.0"
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
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
FORMAT_VERSION = 3


class ConversionError(RuntimeError):
    pass


def tool_command(name, *args):
    """Command line for exstruct / excel2md. The package installed for this interpreter comes
    first: it is the pinned version, while PATH may hold another install (pipx, another venv)."""
    try:
        installed = importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        installed = False
    if installed:
        return [sys.executable, '-c', TOOL_CODE[name], *args]
    exe = shutil.which(name)
    if exe:
        return [exe, *args]
    raise ConversionError(f'{name} が未インストールです（{sys.executable} -m pip install "exstruct==0.9.1" "excel2md==2.3.0"）')


def tool(name, *args):
    cmd = tool_command(name, *args)
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
                        counts['shapes'] += len(re.findall(r'<(?:\w+:)?sp[\s/>]', xml))
                        counts['connectors'] += len(re.findall(r'<(?:\w+:)?cxnSp[\s/>]', xml))
                        counts['pictures'] += len(re.findall(r'<(?:\w+:)?pic[\s/>]', xml))
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
        return flows_from_markdown(out.read_text(encoding='utf-8'), sheets)


def flows_from_markdown(text, sheets):
    """excel2md の出力（シートごとの「## シート名」）から Mermaid を取り出す。
    見出しの前後の空白は落ちるため、空白を除いた名前で元のシート名に対応付ける。"""
    names = {name.strip(): name for name in sheets}
    flows = {}
    for section in re.split(r'^## ', text, flags=re.M)[1:]:
        title, _, body = section.partition('\n')
        name = names.get(title.strip())
        if name is not None:
            blocks = re.findall(r'```mermaid\n(.*?)```', body, re.S)
            if blocks:
                flows[name] = '\n'.join(block.strip() + '\n' for block in blocks)
    return flows


# シートの Markdown：ExStruct の行（空セルを除いた値と列番号）から、表と地の文を復元する。
# 表：見出し行と、同じ左端の列から始まり見出し行の列に収まる行の並び。
#     2 段の見出し（下の段が右から始まる、または上の段の各見出しの下に複数の列がある）を「上/下」にまとめる。
#     見出しより右に 1 つだけはみ出した値（備考など）は、見出しが空の列にする。結合で生じた 2 行までの空行は許す。
#     値が 1 つだけの行（番号・記号を除く）は表の終わりとみなす。
# 地の文：字下げ（左端の列）の深さに応じた箇条書き。番号や記号で始まる 1 セルの行は見出しにする。
# 先頭から 1 回だけ走査する（行数に比例する時間で終わる）。
HEADING = re.compile(r'^(?:\d+(?:\.\d+)*[.．]?\s|[■□◆◇●【≪＜〈《\[])')
BULLETS = {'・', '-', '－', '*', '＊', '●', '○'}
MARKER = re.compile(r'^(?:[・※\-－*＊●○]|[①-⑳]|\(?\d+\)|[0-9]+[.．、]?)$')
NUMBER = re.compile(r'[-+]?[\d,]+(?:\.\d+)?%?')
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


def second_header(top, start, cells):
    """cells が見出しの 2 段目なら、まとめた見出しを返す。"""
    if len(cells) < 2:
        return None
    first = cells[0][0]
    cols = {col for col, _ in cells}
    lo, hi = min(top), max(top)
    # 同じ列から始まる 2 段目：上の段のすべての列を含み、上の段の見出しの間にも列があり、数値を含まない。
    grouped = (first == start and len(top) >= 2 and set(top) < cols
               and any(lo < col < hi and col not in top for col in cols)
               and not any(NUMBER.fullmatch(value) for _, value in cells))
    if first <= start and not grouped:
        return None
    sub, parent, merged = dict(cells), '', {}
    for col in sorted(set(top) | cols):
        parent = top.get(col, parent)
        merged[col] = f'{parent}/{sub[col]}' if col in sub and parent else sub.get(col) or top[col]
    return merged


def body_end(rows, j, start, labels):
    """rows[j] から続く表の本体の終わり。"""
    last = max(labels)
    while j < len(rows) and rows[j][0] - rows[j - 1][0] <= MAX_GAP + 1:
        cells = rows[j][1]
        if cells[0][0] != start or (len(cells) == 1 and not MARKER.match(cells[0][1])):
            break
        inside = sum(col in labels for col, _ in cells)
        # 見出しより右の値（備考など）は 1 つまで。表の列に 2 つ以上の値がある行に限る（次の表の見出しを取り込まない）。
        if inside < len(cells) and not (inside >= 2 and len(cells) - inside == 1 and cells[-1][0] > last):
            break
        j += 1
    return j


def table_at(rows, i):
    """rows[i] から始まる表：(終わりの添字, 列ごとの見出し, 見出しの行数)。表でなければ None。"""
    if i >= len(rows) or len((first := rows[i][1])) < 2 or MARKER.match(first[0][1]):
        return None
    start, top, j = first[0][0], dict(first), i + 1
    if j < len(rows) and rows[j][0] - rows[i][0] <= MAX_GAP + 1 and (labels := second_header(top, start, rows[j][1])):
        if (k := body_end(rows, j + 1, start, labels)) > j + 1:
            return k, labels, 2
    if (k := body_end(rows, j, start, top)) > j:
        return k, top, 1
    return None


def is_title(text, marked=False):
    """見出しになる 1 セルの行。文（。で終わる）は見出しにしない。"""
    return not text.endswith('。') and (not marked or bool(HEADING.match(text)))


def md_text(text):
    return HTML_TAG.sub(r'\\<', text)


def table_lines(rows, labels, count):
    body = [dict(cells) for _, cells in rows[count:]]
    cols = sorted(set(labels).union(*body))

    def line(values):
        return '| ' + ' | '.join(md_text(values.get(col, '')).replace('|', '\\|').replace('\n', '<br>') for col in cols) + ' |'

    return [line(labels), '|' + '---|' * len(cols)] + [line(values) for values in body]


def sheet_markdown(name, sheet_rows, flows=''):
    """ExStruct light のシート 1 枚を Markdown にする。"""
    rows = [(row['r'], cells) for row in sorted(sheet_rows, key=lambda row: row['r']) if (cells := row_cells(row))]
    heading_cols = sorted({cells[0][0] for _, cells in rows if len(cells) == 1 and is_title(cells[0][1], True)})
    out, stack, i = [f'# {md_text(name)}', ''], [], 0
    while i < len(rows):
        if (found := table_at(rows, i)):
            k, labels, count = found
            out += ([''] if out[-1] else []) + table_lines(rows[i:k], labels, count) + ['']
            stack, i = [], k
            continue
        cells = rows[i][1]
        if len(cells) > 1 and cells[0][1] in BULLETS:
            cells = cells[1:]
        text = ' '.join(value.replace('\n', ' ') for _, value in cells)
        joined = md_text(text)
        if len(rows[i][1]) == 1 and is_title(text, True):
            level = min(2 + heading_cols.index(cells[0][0]), 6)
            out += ([''] if out[-1] else []) + ['#' * level + ' ' + joined, '']
            stack = []
        elif len(rows[i][1]) == 1 and is_title(text) and table_at(rows, i + 1):
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
    path = out / MANIFEST
    if not path.exists():
        if (out / 'index.md').exists():
            raise ConversionError(f'{path} がありません。既存の index.md を保護するため、別の出力先を指定してください。')
        return {'format': FORMAT_VERSION, 'books': {}}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('books'), dict):
        raise ConversionError(f'{path} の形式が不正です')
    return data


def validate_destinations(out, books, previous):
    # Each book owns an entire directory (including when a deleted book is cleaned up).
    keys = set(books) | set(previous)
    folded = {key.casefold() for key in keys}
    for key in sorted(keys):
        rel = PurePosixPath(key)
        if (not rel.parts or rel.as_posix() != key or '..' in rel.parts or rel.is_absolute()
                or PureWindowsPath(key).anchor or '\\' in key or rel.parts[0].casefold() in ('index.md', MANIFEST)):
            raise ConversionError(f'不正な出力先：{key!r}')
        if any(parent.as_posix().casefold() in folded for parent in rel.parents):
            raise ConversionError(f'ブックの出力先が入れ子になっています：{key}。別の出力先を指定するか原本名を変更してください。')
        dest = out / key
        if any((out / part).is_symlink() for part in (rel, *rel.parents)):
            raise ConversionError(f'出力先にシンボリックリンクがあります：{dest}')
        if dest.exists() and (key not in previous or not dest.is_dir()):
            raise ConversionError(f'管理対象外の出力先があります：{dest}。別の出力先を指定してください。')
    if len(keys) != len(folded):
        raise ConversionError('大文字・小文字だけが異なる出力先があります。別の出力先を指定してください。')


def run(src, out, check=False, extract_media=False, log=print):
    src, out = Path(src).resolve(), Path(out).resolve()
    if not src.is_dir():
        raise ConversionError(f'入力ディレクトリがありません：{src}')
    if src.is_relative_to(out):
        raise ConversionError('出力先に入力ディレクトリ自身やその親は指定できません')
    for name in (MANIFEST, 'index.md'):
        if (out / name).is_symlink():
            raise ConversionError(f'出力先にシンボリックリンクがあります：{out / name}')
    manifest = load_manifest(out)
    books = book_keys(src, [p for p in find_books(src) if not p.is_relative_to(out)])
    validate_destinations(out, books, manifest['books'])
    stale, failures = [], []
    for key, path in books.items():
        digest = sha256(path)
        entry = manifest['books'].get(key)
        if (manifest.get('format') == FORMAT_VERSION and isinstance(entry, dict) and entry.get('sha256') == digest
                and entry.get('files') and all((out / key / file).is_file() for file in entry['files'])
                and (not extract_media or entry.get('media_extracted') or not entry.get('media'))):
            continue
        stale.append(key)
        if check:
            log(f'古い出力：{path}')
            continue
        dest = out / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=dest.parent, ignore_cleanup_errors=True) as staging:
            tmp = Path(staging) / 'book'
            try:
                summary = convert(path, tmp, extract_media)
                write_book_index(tmp, path.relative_to(src).as_posix(), summary)
                files = sorted(p.relative_to(tmp).as_posix() for p in tmp.rglob('*') if p.is_file())
            except Exception as error:  # one broken book must not block the others
                reason = error if isinstance(error, ConversionError) else f'{type(error).__name__}: {error}'
                failures.append(key)
                log(f'失敗：{path}：{reason}')
                continue
            # 前回の出力は、新しい出力に置き換わるまで消さない（Windows で開いているファイルがあると rename が失敗する）。
            backup = Path(staging) / 'previous'
            try:
                if dest.is_dir():
                    dest.rename(backup)
                try:
                    tmp.rename(dest)
                except OSError:
                    if backup.exists():
                        backup.rename(dest)
                    raise
            except OSError as error:
                failures.append(key)
                kept = '前回の出力はそのままです' if dest.is_dir() else '前回の出力を戻せませんでした。再実行してください'
                log(f'失敗：{path}：出力を置き換えられません（{error}）。{kept}')
                continue
        manifest['books'][key] = {
            'source': path.relative_to(src).as_posix(), 'sha256': digest, 'files': files,
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
        if (out / key).is_dir():
            shutil.rmtree(out / key)
        del manifest['books'][key]
        log(f'削除：{out / key}')
    missing_index = not (out / 'index.md').is_file()
    if check:
        if missing_index:
            log(f"目次がありません：{out / 'index.md'}")
        return 1 if stale or missing_index else 0
    if len(stale) > len(failures) or missing_index:
        if not failures:
            manifest['format'] = FORMAT_VERSION
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
    except (ConversionError, OSError, ValueError) as error:
        print(f'エラー：{error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
