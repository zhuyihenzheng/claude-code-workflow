#!/usr/bin/env python3
"""設計書の表とコードの値が一致しているかを確認する（設計書の更新漏れ・実装漏れを止める）。

    python scripts/spec_sync.py [--only <チェックID>] [--root <プロジェクト>]

対応は config/spec-sync.json に書く。1 件のチェックは、設計書の Markdown の表（Excel の設計書は
xlsx2ai.py が生成した specs-ai/<ブック>/sheets/<シート>.md）の「キーの列」と「値の列」を、
コードから正規表現で取り出したキーと値に突き合わせる：

    {"checks": [{
      "id": "messages",
      "design": {"file": "specs-ai/設計書/sheets/メッセージ一覧.md", "key": "メッセージID", "value": "メッセージ"},
      "code": {"files": ["src/main/resources/messages*.properties"],
               "pattern": "^(?P<key>[A-Za-z0-9_.-]+)\\\\s*[=:]\\\\s*(?P<value>.*)$"},
      "normalize": ["placeholders", "whitespace"],
      "ignore_keys": ["^spring\\\\."]
    }]}

  design.key / design.value  表の見出しの文字列（Markdown の見出し行のとおり。2 段の見出しは「上/下」）。
                             value を省略するとキーの有無だけを比べる。
  code.files                 プロジェクトのルートからの glob。.properties は Java のエスケープ（\\uXXXX、\\n、行の継続）を戻してから読む。
  code.pattern               名前付きグループ key（と value）を持つ正規表現。行ごとに複数行モードで適用する。
  normalize                  placeholders：{0} や {名前} を同じものとみなす。whitespace：連続する空白を 1 つにする。
  ignore_keys                比べないキーの正規表現（フレームワークのメッセージなど）。

報告：設計書にだけあるキー（実装漏れ）、コードにだけあるキー（設計書の更新漏れ）、値の違い。
終了コード：0 = 一致、1 = 不一致、2 = 設定の誤り・ファイルがない（検査未完了）。
標準ライブラリのみを使用する（Python 3.9+）。
"""
import argparse
import json
from pathlib import Path
import re
import sys

CONFIG = 'config/spec-sync.json'
NORMALIZERS = {
    'placeholders': lambda text: re.sub(r'\{[^{}]*\}', '{}', text),
    'whitespace': lambda text: re.sub(r'[\s　]+', ' ', text).strip(),
}
MD_UNESCAPE = ((r'\|', '|'), ('<br>', '\n'), (r'\<', '<'))


class SyncError(Exception):
    pass


def read_text(path):
    data = path.read_bytes()
    for encoding in ('utf-8-sig', 'cp932'):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode('latin-1')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if path.suffix == '.properties':
        # Join continuation lines first (a line ending in an odd number of backslashes), as Java does.
        text = re.sub(r'(?<!\\)((?:\\\\)*)\\\n[ \t\f]*', r'\1', text)
    return text


def properties_unescape(text):
    """Java .properties escapes in one key or value: \\uXXXX, \\n, \\t and \\ before any other character."""
    plain = {'n': '\n', 't': '\t', 'r': '\r', 'f': '\f'}
    return re.sub(r'\\(u[0-9a-fA-F]{4}|.)',
                  lambda m: chr(int(m.group(1)[1:], 16)) if len(m.group(1)) == 5 else plain.get(m.group(1), m.group(1)), text)


def split_row(line):
    cells, current, i = [], '', 0
    body = line.strip()
    body = body[1:] if body.startswith('|') else body
    body = body[:-1] if body.endswith('|') and not body.endswith('\\|') else body
    while i < len(body):
        if body.startswith('\\|', i):
            current += '\\|'
            i += 2
        elif body[i] == '|':
            cells.append(current)
            current, i = '', i + 1
        else:
            current += body[i]
            i += 1
    cells.append(current)
    result = []
    for cell in cells:
        cell = cell.strip()
        for old, new in MD_UNESCAPE:
            cell = cell.replace(old, new)
        result.append(cell)
    return result


def design_values(path, key, value):
    """{key: (value, line)} from every Markdown table in path whose header has the key (and value) column."""
    lines = path.read_text(encoding='utf-8').splitlines()
    found, tables = {}, 0
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith('|') and i + 1 < len(lines) and re.fullmatch(r'\s*\|[\s:|-]+', lines[i + 1]):
            header = split_row(lines[i])
            j = i + 2
            if key in header and (value is None or value in header):
                tables += 1
                k, v = header.index(key), header.index(value) if value else None
                while j < len(lines) and lines[j].lstrip().startswith('|'):
                    cells = split_row(lines[j])
                    name = cells[k] if k < len(cells) else ''
                    if name:
                        if name in found:
                            raise SyncError(f'{path}:{j + 1}：キー「{name}」が {found[name][1]} 行目と重複しています')
                        found[name] = ((cells[v] if v is not None and v < len(cells) else ''), j + 1)
                    j += 1
            i = j
        else:
            i += 1
    if not tables:
        raise SyncError(f'{path}：見出しに「{key}」' + (f'と「{value}」' if value else '') + 'を含む表がありません')
    return found


def code_values(root, files, pattern):
    regex = re.compile(pattern, re.M)
    if 'key' not in regex.groupindex:
        raise SyncError(f'code.pattern に名前付きグループ key がありません：{pattern}')
    paths = sorted({p for glob in files for p in root.glob(glob) if p.is_file()})
    if not paths:
        raise SyncError(f'code.files に一致するファイルがありません：{files}')
    found = {}
    for path in paths:
        text = read_text(path)
        unescape = properties_unescape if path.suffix == '.properties' else (lambda t: t)
        for match in regex.finditer(text):
            name = unescape(match.group('key').strip())
            value = unescape(match.group('value')) if 'value' in regex.groupindex and match.group('value') is not None else ''
            line = text.count('\n', 0, match.start()) + 1
            found.setdefault(name, (value.strip(), f'{path.relative_to(root).as_posix()}:{line}'))
    return found


def run_check(root, check):
    for field in ('id', 'design', 'code'):
        if field not in check:
            raise SyncError(f'チェックに {field} がありません')
    design, code = check['design'], check['code']
    unknown = set(check.get('normalize', [])) - set(NORMALIZERS)
    if unknown:
        raise SyncError(f'{check["id"]}：normalize に不明な値があります：{sorted(unknown)}（{", ".join(NORMALIZERS)}）')
    design_path = root / design['file']
    if not design_path.is_file():
        raise SyncError(f'{check["id"]}：設計書がありません：{design["file"]}（Excel の設計書は python scripts/xlsx2ai.py で生成する）')
    value_column = design.get('value')
    expected = design_values(design_path, design['key'], value_column)
    actual = code_values(root, code['files'], code['pattern'])
    ignored = [re.compile(p) for p in check.get('ignore_keys', [])]

    def kept(names):
        return {n for n in names if not any(p.search(n) for p in ignored)}

    def norm(text):
        for name in check.get('normalize', []):
            text = NORMALIZERS[name](text)
        return text

    problems = []
    rel = design['file']
    for name in sorted(kept(expected) - set(actual)):
        problems.append(f'設計書にだけある（実装漏れ）：{name}（{rel}:{expected[name][1]}）')
    for name in sorted(kept(actual) - set(expected)):
        problems.append(f'コードにだけある（設計書の更新漏れ）：{name}（{actual[name][1]}）')
    if value_column:
        for name in sorted(kept(expected) & set(actual)):
            if norm(expected[name][0]) != norm(actual[name][0]):
                problems.append(f'値が違う：{name}：設計書 {expected[name][0]!r}（{rel}:{expected[name][1]}）、'
                                f'コード {actual[name][0]!r}（{actual[name][1]}）')
    return len(kept(expected) & set(actual)), problems


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--only', help='このチェック ID だけを実行する')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1],
                        help='プロジェクトのルート（省略時は scripts/ の親）')
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        config = root / CONFIG
        if not config.is_file():
            print(f'spec_sync: {CONFIG} がありません（設計書とコードの対応を登録していません）')
            return 0
        try:
            checks = json.loads(config.read_text(encoding='utf-8'))['checks']
            if not isinstance(checks, list):
                raise TypeError('"checks" must be an array')
        except (ValueError, KeyError, TypeError) as error:
            raise SyncError(f'{CONFIG} が不正です：{error}') from None
        selected = [c for c in checks if not args.only or c.get('id') == args.only]
        if args.only and not selected:
            raise SyncError(f'チェック {args.only} がありません')
        total, failed = 0, 0
        for check in selected:
            matched, problems = run_check(root, check)
            total += matched
            for problem in problems:
                print(f'[{check["id"]}] {problem}')
            failed += bool(problems)
    except (SyncError, OSError, re.error, KeyError) as error:
        print(f'spec_sync: 検査未完了：{error}', file=sys.stderr)
        return 2
    if failed:
        print(f'spec_sync: NG：{len(selected)} チェック中 {failed} 件で設計書とコードが一致しません。'
              '設計書が正しければコードを、コードが正しければ設計書（Excel は xlsx_patch.py の変更指示）を直す')
        return 1
    print(f'spec_sync: OK（{len(selected)} チェック、{total} 項目が一致）' if selected
          else f'spec_sync: OK（{CONFIG} にチェックがありません）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
