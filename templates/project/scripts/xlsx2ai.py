#!/usr/bin/env python3
"""Excel 設計書を AI が少ないトークンで読める形式に変換する（増分変換）。

    python scripts/xlsx2ai.py [SRC_DIR] [OUT_DIR] [--check] [--extract-media]

既定は SRC_DIR=specs、OUT_DIR=specs-ai。ブックごとに次を生成する：

    OUT_DIR/index.md                 全ブックの目次（AI はここから読む）
    OUT_DIR/<book>/index.md          シート一覧（文字数・図形フロー・画像の有無）
    OUT_DIR/<book>/sheets/<sheet>.json   ExStruct light：空セルを除いた値と行列番号
    OUT_DIR/<book>/flows/<sheet>.mmd     図形＋コネクタで描かれたフロー図（excel2md）
    OUT_DIR/<book>/media/*           --extract-media 指定時のみ：貼り付け画像（フロー図の画像など）

変換はローカルで行い、モデルのトークンは消費しない。SHA-256 が変わったブックだけを
再変換し、削除されたブックの出力も削除する。--check は書き込まずに古い出力を報告し、
古いものがあれば終了コード 1 を返す（CI 用）。

依存：pip install "exstruct==0.9.0" "excel2md==2.3.0"
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
FORMAT_VERSION = 1


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
            detail = [f'{name} が未インストールです（pip install "exstruct==0.9.0" "excel2md==2.3.0"）']
        raise ConversionError(f'{name} が失敗しました：{detail[0]}')
    return result


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def book_key(src, path):
    """Stable output directory name: relative path without suffix, '/' kept as folders."""
    return path.relative_to(src).with_suffix('').as_posix()


def find_books(src):
    return sorted(p for p in src.rglob('*')
                  if p.is_file() and p.suffix.lower() in SUFFIXES and not p.name.startswith('~$'))


def _rels(zf, part):
    """Map relationship id -> target part path for an OOXML part."""
    import xml.etree.ElementTree as ET
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
    import xml.etree.ElementTree as ET
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
        rows.append({'sheet': json_file.stem, 'file': f'sheets/{json_file.name}',
                     'chars': len(json_file.read_text(encoding='utf-8'))})
    return {'sheets': rows, 'drawings': drawings, 'flows': sorted(flows), 'media': len(media)}


def md_link(text, target):
    """Markdown link that survives brackets and spaces in Excel book / sheet names."""
    return '[' + re.sub(r'([\\\[\]|])', r'\\\1', text) + '](<' + target + '>)'


def write_book_index(dest, source_rel, summary):
    lines = [f'# {source_rel}', '',
             '生成物：`scripts/xlsx2ai.py`。手で編集しない。原本の Excel を直接読まず、必要なシートだけを開く。', '',
             '| シート | ファイル | 文字数 | 図形フロー | 画像 |', '|---|---|---:|---|---:|']
    for row in summary['sheets']:
        d = summary['drawings'].get(row['sheet'], {})
        mmd = f"flows/{safe_name(row['sheet'])}.mmd"
        flow = md_link(mmd, mmd) if row['sheet'] in summary['flows'] else ''
        sheet = row['sheet'].replace('|', '\\|')
        lines.append(f"| {sheet} | {md_link(row['file'], row['file'])} | {row['chars']:,} | {flow} | {d.get('pictures', 0)} |")
    lines += ['', 'シート JSON は空セルを除いた `{"r": 行, "c": {列: 値}}`（0 始まりの列番号）。結合セルの範囲は含まない。']
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
    books = {book_key(src, p): p for p in find_books(src)}
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
            'sheet_count': len(summary['sheets']), 'chars': sum(r['chars'] for r in summary['sheets']),
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
