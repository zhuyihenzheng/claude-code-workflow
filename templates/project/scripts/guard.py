#!/usr/bin/env python3
"""決定的チェック（guard）：人の修正指示をルールにし、同じ誤りを機械で止める。

    python3 scripts/guard.py [PATH ...]           # 検査（PATH 省略時はプロジェクト全体）
    python3 scripts/guard.py --list               # ルールの一覧
    python3 scripts/guard.py --update-baseline    # ベースラインを現在の件数まで縮小する（増やさない）
    python3 scripts/guard.py --init-baseline      # ベースライン未登録のルールについて、既存の違反を受け入れる（人が実行する）
    python3 scripts/guard.py --format github      # GitHub Actions で、違反を PR の該当行に注釈として表示する

ルールは config/guard/rules.json、ルール導入時点の既存違反は config/guard/baseline.json、
個別の例外は config/guard/allow.json に置く。3 つとも人が承認する（Claude Code では編集に確認が入り、
CODEOWNERS で承認者を必須にする）。ベースラインは縮小だけができる。新しい違反は件数が増えたファイルとして検出する。

例外（config/guard/allow.json の "allow" の 1 件）：
    {"rule": "<ルールID>", "path": "<ファイル>", "match": "<違反行に含まれる文字列>",
     "until": "YYYY-MM-DD", "by": "<承認者>", "reason": "<理由>"}
期限は 1 年以内。期限切れ・項目不足・未知のルールは違反として扱う。
ソースコードに書いた例外のコメント（guard:allow）は使えない。人の承認を経ずに書けてしまうため、違反として扱う。

各ルールの examples.bad は一致し、examples.good は一致しないことを毎回確認する。
終了コード：0 = 違反なし、1 = 違反あり、2 = 設定またはルールの誤り（検査未完了）。
標準ライブラリのみを使用する（Python 3.9+）。
"""

import argparse
import bisect
from collections import Counter
import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
RULES = 'config/guard/rules.json'
BASELINE = 'config/guard/baseline.json'
ALLOWLIST = 'config/guard/allow.json'
SKIP_DIRS = {'.git', 'target', 'build', 'node_modules', '.idea', '.gradle', '.mvn', '__pycache__'}
RULE_ID = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
INLINE_ALLOW = re.compile(r'guard:allow\b')
ALLOW_FIELDS = ('rule', 'path', 'match', 'until', 'by', 'reason')
MAX_ALLOW_DAYS = 366
ALLOW_RULE = 'guard-allow'


class ConfigError(Exception):
    pass


def glob_regex(pattern):
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith('**/', i):
            out.append('(?:.*/)?')
            i += 3
        elif pattern.startswith('**', i):
            out.append('.*')
            i += 2
        elif pattern[i] == '*':
            out.append('[^/]*')
            i += 1
        elif pattern[i] == '?':
            out.append('[^/]')
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile(''.join(out) + r'\Z')


class Rule:
    def __init__(self, data):
        self.id = data['id']
        self.message = data['message']
        self.origin = data.get('origin', '')
        self.files = [glob_regex(p) for p in data['files']]
        self.exclude = [glob_regex(p) for p in data.get('exclude', [])]
        self.regex = re.compile(data['pattern'], re.MULTILINE)
        self.examples = data['examples']
        self.patterns = data['files']

    def applies(self, rel):
        return any(g.match(rel) for g in self.files) and not any(g.match(rel) for g in self.exclude)


def load_rules(root):
    path = root / RULES
    if not path.is_file():
        raise ConfigError(f'{RULES} がありません')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as error:
        raise ConfigError(f'{RULES} が JSON として不正です：{error}') from None
    entries = data.get('rules') if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ConfigError(f'{RULES} に "rules" の配列がありません')
    rules, problems, seen = [], [], set()
    for index, entry in enumerate(entries):
        where = f'rules[{index}]'
        if not isinstance(entry, dict):
            problems.append(f'{where}：オブジェクトではありません')
            continue
        rule_id = entry.get('id')
        if not isinstance(rule_id, str) or not RULE_ID.fullmatch(rule_id) or rule_id == ALLOW_RULE:
            problems.append(f'{where}：id は小文字英数字とハイフンで書く（{ALLOW_RULE} は予約済み）')
            continue
        where = rule_id
        if rule_id in seen:
            problems.append(f'{where}：id が重複しています')
        seen.add(rule_id)
        if not isinstance(entry.get('message'), str) or not entry['message'].strip():
            problems.append(f'{where}：message（直し方）がありません')
        files = entry.get('files')
        if not isinstance(files, list) or not files or not all(isinstance(f, str) and f for f in files):
            problems.append(f'{where}：files に対象ファイルの glob を 1 つ以上書く')
        if not all(isinstance(f, str) for f in entry.get('exclude', [])):
            problems.append(f'{where}：exclude は文字列の配列にする')
        examples = entry.get('examples')
        bad = examples.get('bad') if isinstance(examples, dict) else None
        good = examples.get('good', []) if isinstance(examples, dict) else []
        if not isinstance(bad, list) or not bad or not isinstance(good, list) \
                or not all(isinstance(x, str) for x in bad + good):
            problems.append(f'{where}：examples.bad に実際の誤りの例を 1 つ以上書く（good は任意の文字列の配列）')
        try:
            re.compile(entry.get('pattern', ''), re.MULTILINE)
            if not entry.get('pattern'):
                raise re.error('empty pattern')
        except (re.error, TypeError) as error:
            problems.append(f'{where}：pattern が正規表現として不正です（{error}）')
            continue
        if any(p.startswith(where + '：') for p in problems):
            continue
        rule = Rule(entry)
        for example in bad:
            if not rule.regex.search(normalize(example)):
                problems.append(f'{where}：examples.bad に一致しません：{example!r}')
        for example in good:
            if rule.regex.search(normalize(example)):
                problems.append(f'{where}：examples.good に一致してしまいます：{example!r}')
        rules.append(rule)
    if problems:
        raise ConfigError('ルールの誤り：\n  ' + '\n  '.join(problems))
    return rules


def load_baseline(root, rule_ids):
    path = root / BASELINE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        rules = data['rules']
        if not isinstance(rules, dict) or not all(
                isinstance(files, dict) and all(isinstance(n, int) and n > 0 for n in files.values())
                for files in rules.values()):
            raise ValueError('rules must map rule id -> {path: positive count}')
    except (ValueError, KeyError, TypeError) as error:
        raise ConfigError(f'{BASELINE} が不正です：{error}') from None
    return {rule_id: dict(files) for rule_id, files in rules.items() if rule_id in rule_ids}


def write_baseline(root, baseline):
    path = root / BASELINE
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {rule_id: dict(sorted(files.items())) for rule_id, files in sorted(baseline.items())}
    payload = {
        '_note': 'guard.py が生成する。手で編集しない。件数は縮小だけができる（--update-baseline）。',
        'rules': ordered,
    }
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + '\n')


def project_files(root):
    git = shutil.which('git')
    if git:
        result = subprocess.run([git, '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                                capture_output=True)
        if result.returncode == 0:
            names = result.stdout.decode('utf-8', 'replace').split('\0')
            return sorted({n for n in names if n and not SKIP_DIRS.intersection(n.split('/')[:-1])
                           and (root / n).is_file()})
    found = []
    for path in root.rglob('*'):
        rel = path.relative_to(root)
        if path.is_file() and not SKIP_DIRS.intersection(rel.parts[:-1]):
            found.append(rel.as_posix())
    return sorted(found)


def select(root, files, paths):
    if not paths:
        return files
    chosen = set()
    for raw in paths:
        target = Path(raw)
        target = (target if target.is_absolute() else Path.cwd() / target).resolve()
        try:
            rel = target.relative_to(root.resolve()).as_posix()
        except ValueError:
            raise ConfigError(f'プロジェクトの外のパスです：{raw}') from None
        if rel == '.':
            return files
        chosen.update(f for f in files if f == rel or f.startswith(rel + '/'))
    return sorted(chosen)


def normalize(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def read_text(path):
    data = path.read_bytes()
    for encoding in ('utf-8-sig', 'cp932'):
        try:
            return normalize(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    return normalize(data.decode('latin-1'))


class Allow:
    def __init__(self, index, data, problem):
        self.index, self.problem, self.used = index, problem, 0
        self.rule_id, self.path, self.match = (data.get(key) if isinstance(data, dict) else None
                                               for key in ('rule', 'path', 'match'))

    @property
    def where(self):
        return f'{ALLOWLIST}（allow[{self.index}]）'

    def covers(self, rule_id, path, source):
        return self.problem is None and self.rule_id == rule_id and self.path == path and self.match in source


def load_allows(root, rule_ids, today):
    """Exceptions from config/guard/allow.json. Entries with a problem cover nothing and are reported."""
    path = root / ALLOWLIST
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        entries = data['allow']
        if not isinstance(entries, list):
            raise TypeError('"allow" must be an array')
    except (ValueError, KeyError, TypeError) as error:
        raise ConfigError(f'{ALLOWLIST} が不正です：{error}') from None
    allows = []
    for index, entry in enumerate(entries):
        problem = None
        missing = [key for key in ALLOW_FIELDS
                   if not isinstance(entry, dict) or not isinstance(entry.get(key), str) or not entry[key].strip()]
        if missing:
            problem = f'例外に {", ".join(missing)} がありません（{", ".join(ALLOW_FIELDS)} がすべて必要）'
        elif entry['rule'] not in rule_ids:
            problem = f'未知のルール {entry["rule"]!r} の例外です'
        else:
            try:
                until = datetime.date.fromisoformat(entry['until'])
            except ValueError:
                until = None
            if until is None:
                problem = f'until={entry["until"]} は日付ではありません'
            elif until < today:
                problem = f'例外の期限が切れています（until={until}）。根本原因を直すか、人が期限を見直す'
            elif (until - today).days > MAX_ALLOW_DAYS:
                problem = f'例外の期限は 1 年以内にする（until={until}）'
        allows.append(Allow(index, entry, problem))
    return allows


def scan(root, rules, files, allows):
    """Return (violations, inline_allows). A violation is (rule_id, path, line, source_line)."""
    violations, inline = [], []
    for rel in files:
        applicable = [r for r in rules if r.applies(rel)]
        if not applicable:
            continue
        text = read_text(root / rel)
        lines = text.split('\n')
        inline += [(rel, number) for number, line in enumerate(lines, 1) if INLINE_ALLOW.search(line)]
        newlines = [m.start() for m in re.finditer('\n', text)]
        for rule in applicable:
            for match in rule.regex.finditer(text):
                number = bisect.bisect_left(newlines, match.start()) + 1
                source = lines[number - 1].strip()
                covering = [a for a in allows if a.covers(rule.id, rel, source)]
                for allow in covering:
                    allow.used += 1
                if not covering:
                    violations.append((rule.id, rel, number, source))
    return violations, inline


def compare(violations, baseline):
    counts = Counter((rule_id, path) for rule_id, path, _, _ in violations)
    failing, accepted = [], 0
    for rule_id, path, number, source in violations:
        allowed = (baseline or {}).get(rule_id, {}).get(path, 0)
        if counts[(rule_id, path)] > allowed:
            failing.append((rule_id, path, number, source, allowed, counts[(rule_id, path)]))
        else:
            accepted += 1
    return failing, accepted, counts


def shrink(baseline, counts, rule_ids):
    shrunk, removed = {}, 0
    for rule_id, files in baseline.items():
        if rule_id not in rule_ids:
            removed += sum(files.values())
            continue
        kept = {}
        for path, allowed in files.items():
            now = min(allowed, counts.get((rule_id, path), 0))
            removed += allowed - now
            if now:
                kept[path] = now
        shrunk[rule_id] = kept
    return shrunk, removed


def annotate(level, path, line, title, message):
    def data(value):
        return value.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')

    def prop(value):
        return data(value).replace(':', '%3A').replace(',', '%2C')

    print(f'::{level} file={prop(path)},line={line},title={prop(title)}::{data(message)}')


def print_rules(rules, baseline, allows):
    for rule in rules:
        state = ('ベースライン未登録' if baseline is None or rule.id not in baseline
                 else f'既存違反 {sum(baseline[rule.id].values())} 件を受け入れ済み')
        exceptions = sum(1 for a in allows if a.rule_id == rule.id and a.problem is None)
        print(f'{rule.id}  [{state}' + (f'、例外 {exceptions} 件' if exceptions else '') + ']')
        print(f'  対象：{", ".join(rule.patterns)}')
        print(f'  直し方：{rule.message}')
        if rule.origin:
            print(f'  由来：{rule.origin}')


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
        sys.stderr.reconfigure(errors='replace')
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('paths', nargs='*', help='検査するファイルまたはディレクトリ（省略時は全体）')
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT, help='プロジェクトのルート（省略時は scripts/ の親）')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--list', action='store_true', help='ルールの一覧を表示する')
    group.add_argument('--update-baseline', action='store_true', help='ベースラインを現在の件数まで縮小する')
    group.add_argument('--init-baseline', action='store_true',
                       help='ベースライン未登録のルールについて既存の違反を受け入れる（人が実行する）')
    parser.add_argument('--format', choices=('text', 'github'), default='text',
                        help='github：GitHub Actions の注釈（::error）も出力する')
    parser.add_argument('--today', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    root = args.root.expanduser().resolve()
    today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
    try:
        if not root.is_dir():
            raise ConfigError(f'プロジェクトのルートがありません：{root}')
        rules = load_rules(root)
        rule_ids = {r.id for r in rules}
        baseline = load_baseline(root, rule_ids)
        allows = load_allows(root, rule_ids, today)
        if args.list:
            print_rules(rules, baseline, allows)
            return 0
        if args.paths and (args.update_baseline or args.init_baseline):
            raise ConfigError('ベースラインの更新はプロジェクト全体を対象にする（PATH を指定しない）')
        files = [f for f in select(root, project_files(root), args.paths) if any(r.applies(f) for r in rules)]
    except ConfigError as error:
        print(f'guard: 検査未完了：{error}', file=sys.stderr)
        return 2

    violations, inline = scan(root, rules, files, allows)
    allow_problems = [(ALLOW_RULE, ALLOWLIST, 1, f'allow[{a.index}]：{a.problem}') for a in allows if a.problem]
    allow_problems += [(ALLOW_RULE, path, number, f'ソースコードの例外コメント（guard:allow）は使えない。例外は人が {ALLOWLIST} に登録する')
                       for path, number in inline]
    counts = Counter((rule_id, path) for rule_id, path, _, _ in violations)

    if args.init_baseline:
        current = dict(baseline or {})
        added = [r.id for r in rules if r.id not in current]
        for rule_id in added:
            current[rule_id] = {path: n for (rid, path), n in sorted(counts.items()) if rid == rule_id}
        current, _ = shrink(current, counts, rule_ids)
        write_baseline(root, current)
        accepted = sum(sum(current[r].values()) for r in added)
        print(f'guard: ベースラインに {len(added)} ルールを登録し、既存の違反 {accepted} 件を受け入れました'
              + (f'（{", ".join(added)}）' if added else '（登録済みのルールは変更しない）'))
        baseline = current
    elif args.update_baseline:
        if baseline is None:
            print('guard: ベースラインがありません。既存の違反を受け入れて始める場合は、人が --init-baseline を実行する',
                  file=sys.stderr)
            return 2
        baseline, removed = shrink(baseline, counts, rule_ids)
        write_baseline(root, baseline)
        print(f'guard: ベースラインを {removed} 件縮小しました' if removed else 'guard: ベースラインは最新です')

    failing, accepted, counts = compare(violations, baseline)
    failing.sort(key=lambda f: (f[1], f[2]))
    for rule_id, path, number, source, allowed, now in failing:
        message = next(r.message for r in rules if r.id == rule_id)
        extra = f'（このファイルのベースライン {allowed} 件に対して {now} 件）' if allowed else ''
        if args.format == 'github':
            annotate('error', path, number, f'guard {rule_id}', message + extra)
        print(f'{path}:{number}: [{rule_id}] {message}{extra}')
        print(f'    {source[:160]}')
    for rule_id, path, number, problem in allow_problems:
        if args.format == 'github':
            annotate('error', path, number, f'guard {rule_id}', problem)
        print(f'{path}:{number}: [{rule_id}] {problem}')
    for allow in allows:
        if allow.problem is None and not allow.used and (not args.paths or allow.path in files):
            if args.format == 'github':
                annotate('warning', ALLOWLIST, 1, 'guard', f'使われていない例外です（allow[{allow.index}] {allow.rule_id} {allow.path}）')
            print(f'{allow.where}: [警告] 使われていない例外です（{allow.rule_id} {allow.path}）。人が削除する')

    if baseline is not None and not args.paths:
        stale = sum(n - min(n, counts.get((rule_id, path), 0))
                    for rule_id, files in baseline.items() for path, n in files.items())
        if stale and not args.update_baseline:
            print(f'guard: 既存の違反が {stale} 件減りました。python3 scripts/guard.py --update-baseline でベースラインを縮小する')

    used = sum(allow.used for allow in allows)
    if failing or allow_problems:
        uninitialized = sorted({f[0] for f in failing} - set(baseline or {}))
        print(f'guard: NG：新しい違反 {len(failing) + len(allow_problems)} 件（{len(rules)} ルール、{len(files)} ファイルを検査）。'
              '各行の直し方に従って直す。ルールを弱めたり、例外やベースラインで通したりしない')
        if uninitialized:
            print(f'guard: ベースライン未登録のルール：{", ".join(uninitialized)}。既存コードの違反を受け入れて'
                  'ルールを導入する場合だけ、人が python3 scripts/guard.py --init-baseline を実行する')
        return 1
    print(f'guard: OK（{len(rules)} ルール、{len(files)} ファイルを検査。ベースラインの既存違反 {accepted} 件、例外 {used} 件）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
