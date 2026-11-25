#!/usr/bin/env python3
"""プロジェクト知識（docs/knowledge/）が古くなっていないかを確認する。

    python scripts/knowledge_check.py [--root <プロジェクト>]

docs/knowledge/ には、作業のたびにエージェントと人が確かめた事実を書き戻す（knowledge skill）。
書き戻すだけでは、ファイルの移動や機能の廃止で記載が古くなり、次の作業を誤らせる。
このスクリプトは次を検査する：

    - 記載中のパス（/ を含み、拡張子付きのファイル名か末尾が / のフォルダ）が存在する
    - codemap.md の「## <機能ID> …」の機能 ID が docs/feature-map/ にある（機能マップがある場合）
    - glossary.md の用語（表の 1 列目）が重複していない

終了コード：0 = 問題なし（知識ファイルがない場合も 0）、1 = 古い記載や重複がある、2 = 入力が不正。
標準ライブラリのみを使用する（Python 3.9+）。
"""
import argparse
from pathlib import Path
import re
import sys

KNOWLEDGE = 'docs/knowledge'
FEATURE_MAP = 'docs/feature-map'
CODE_SPAN = re.compile(r'`([^`\n]+)`')
# A file (last part has an extension) or a folder (ends with /). View names such as fragments/order-form are not paths.
PATH_LIKE = re.compile(r'[\w.\-]+(?:/[\w.\-]+)*(?:\.\w+|/)')
FEATURE_HEADING = re.compile(r'^##\s+(\S+)', re.M)


def code_paths(text):
    """Repository paths written as code spans: they contain '/', no spaces, no URL scheme or wildcard."""
    for number, line in enumerate(text.splitlines(), 1):
        for span in CODE_SPAN.findall(line):
            candidate = re.sub(r':\d+(?:-\d+)?$', '', span.strip())
            if '/' in candidate and '://' not in candidate and not candidate.startswith(('/', '~', '.')) \
                    and PATH_LIKE.fullmatch(candidate):
                yield number, candidate


def glossary_terms(text):
    """First-column values of Markdown table rows, skipping each table's header and separator rows."""
    in_table = False
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped.startswith('|'):
            in_table = False
            continue
        if not in_table:
            in_table = True
            continue
        if re.fullmatch(r'\|[\s:|-]+', stripped):
            continue
        first = stripped.strip('|').split('|')[0].strip()
        if first:
            yield number, first


def check(root):
    problems = []
    folder = root / KNOWLEDGE
    files = sorted(p for p in folder.glob('*.md') if p.name != 'README.md') if folder.is_dir() else []
    features = None
    if (root / FEATURE_MAP).is_dir():
        features = {p.name.split('-', 1)[0] for p in (root / FEATURE_MAP).glob('*.md') if p.name != 'README.md'}
    for path in files:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding='utf-8')
        for number, target in code_paths(text):
            exists = (root / target).is_dir() if target.endswith('/') else (root / target).exists()
            if not exists:
                problems.append(f'{rel}:{number}: `{target}` がありません。移動先に直すか、記載を削除する')
        if path.name == 'codemap.md' and features is not None:
            for match in FEATURE_HEADING.finditer(text):
                feature = match.group(1)
                if feature not in features:
                    number = text.count('\n', 0, match.start()) + 1
                    problems.append(f'{rel}:{number}: 機能 ID {feature} が {FEATURE_MAP}/ にありません。'
                                    '機能マップに追加するか、見出しを直す')
        if path.name == 'glossary.md':
            seen = {}
            for number, term in glossary_terms(text):
                key = term.casefold()
                if key in seen:
                    problems.append(f'{rel}:{number}: 用語「{term}」が {seen[key]} 行目と重複しています。1 行にまとめる')
                else:
                    seen[key] = number
    return files, problems


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1],
                        help='プロジェクトのルート（省略時は scripts/ の親）')
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f'knowledge: 検査未完了：プロジェクトのルートがありません：{root}', file=sys.stderr)
        return 2
    try:
        files, problems = check(root)
    except (OSError, UnicodeDecodeError) as error:
        print(f'knowledge: 検査未完了：{error}', file=sys.stderr)
        return 2
    for problem in problems:
        print(problem)
    if problems:
        print(f'knowledge: NG：古い記載または重複 {len(problems)} 件（{len(files)} ファイル）')
        return 1
    print(f'knowledge: OK（{len(files)} ファイル）' if files else f'knowledge: OK（{KNOWLEDGE}/ に知識ファイルはまだありません）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
