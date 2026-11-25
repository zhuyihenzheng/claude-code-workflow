#!/usr/bin/env python3
"""AI が作った PR の手戻りが月ごとに減っているかを集計する（「AI がプロジェクトに慣れてきたか」の指標）。

    python scripts/ai_metrics.py [--since YYYY-MM-DD] [--all] [--json]
    python scripts/ai_metrics.py --input prs.json      # gh の出力を保存したファイルから集計する

マージ済みの PR を GitHub CLI（gh）で取得し、月ごと（マージした月）に次を出す：

    PR 数            対象の PR の数
    一発で通った割合   レビュー後の追加コミットも、変更要求（Request changes）もなかった PR の割合
    手戻りコミット     最初のレビューより後に積んだコミットの数（PR あたりの平均）
    変更要求         Request changes のレビューの数（PR あたりの平均）

あわせて、git の履歴から月ごとに次を数える（学習の仕組みが使われているか）：

    追加したルール     config/guard/rules.json に追加された guard のルール（correct skill の成果）
    知識の更新        docs/knowledge/ を変更したコミット（knowledge skill の成果）

対象（--all を付けない場合）：ブランチ名が claude/ または copilot/ で始まる PR、作成者が Copilot の PR、
コミットに Co-Authored-By: Claude / Copilot が付いた PR。少ない件数の月は傾向とみなさない。
指標は代理であり、レビューの厳しさや PR の大きさでも変わる。結論は件数とあわせて判断する。
標準ライブラリのみを使用する（Python 3.9+）。gh がない環境では --input を使う。
"""
import argparse
from collections import defaultdict
import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

FIELDS = 'number,title,author,headRefName,createdAt,mergedAt,reviews,commits'
AI_BRANCH = re.compile(r'^(?:claude|copilot)/', re.I)
AI_TRAILER = re.compile(r'^Co-Authored-By:.*\b(?:Claude|Copilot)\b', re.I | re.M)
AI_AUTHORS = {'copilot', 'copilot-swe-agent', 'app/copilot-swe-agent'}
RULE_ADDED = re.compile(r'^\+\s*"id"\s*:\s*"([a-z0-9-]+)"', re.M)


class MetricsError(Exception):
    pass


def login(user):
    return (user or {}).get('login', '') if isinstance(user, dict) else ''


def is_ai(pr):
    if AI_BRANCH.match(pr.get('headRefName') or '') or login(pr.get('author')).lower() in AI_AUTHORS:
        return True
    return any(AI_TRAILER.search(c.get('messageBody') or '') for c in pr.get('commits') or [])


def parse_time(text):
    return datetime.datetime.fromisoformat(text.replace('Z', '+00:00')) if text else None


def pr_metrics(pr):
    """(rework commits, changes requested, reviewed) for one PR. Reviews by the PR's author do not count."""
    author = login(pr.get('author'))
    reviews = [r for r in pr.get('reviews') or [] if login(r.get('author')) != author and r.get('submittedAt')]
    first = min((parse_time(r['submittedAt']) for r in reviews), default=None)
    rework = 0 if first is None else sum(
        1 for c in pr.get('commits') or [] if (t := parse_time(c.get('committedDate'))) and t > first)
    requested = sum(1 for r in reviews if r.get('state') == 'CHANGES_REQUESTED')
    return rework, requested, bool(reviews)


def fetch_prs(since):
    gh = shutil.which('gh')
    if not gh:
        raise MetricsError('gh（GitHub CLI）が見つかりません。gh pr list の JSON を保存して --input で渡す')
    query = f'merged:>={since}' if since else ''
    cmd = [gh, 'pr', 'list', '--state', 'merged', '--limit', '1000', '--json', FIELDS, '--search', query]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode != 0:
        raise MetricsError(f'gh pr list が失敗しました：{(result.stderr or result.stdout).strip()}')
    return json.loads(result.stdout)


def learning_by_month(root, since):
    """{month: {'rules': n, 'knowledge': n}} from git history; empty without git."""
    git = shutil.which('git')
    months = defaultdict(lambda: {'rules': 0, 'knowledge': 0})
    if not git or not (root / '.git').exists():
        return months

    def log(*args):
        result = subprocess.run([git, '-C', str(root), 'log', '--no-merges', *args],
                                capture_output=True, text=True, encoding='utf-8', errors='replace')
        return result.stdout if result.returncode == 0 else ''

    # Whole history, oldest first: a rule counts once, in the month its id first appeared
    # (later edits of the same rule and rules that existed before --since are not "added").
    seen = set()
    for chunk in log('--reverse', '--format=%x00%cs', '-p', '--', 'config/guard/rules.json').split('\0')[1:]:
        month = chunk[:7]
        for rule_id in RULE_ADDED.findall(chunk):
            if rule_id not in seen:
                seen.add(rule_id)
                if not since or month >= since[:7]:
                    months[month]['rules'] += 1
    for line in log(*([f'--since={since}'] if since else []), '--format=%cs', '--', 'docs/knowledge/').split():
        months[line[:7]]['knowledge'] += 1
    return months


def summarize(prs, include_all, since, learning):
    months = defaultdict(lambda: {'prs': 0, 'first_pass': 0, 'rework': 0, 'requested': 0})
    for pr in prs:
        merged = parse_time(pr.get('mergedAt'))
        if merged is None or (since and merged.date().isoformat() < since) or not (include_all or is_ai(pr)):
            continue
        rework, requested, _ = pr_metrics(pr)
        row = months[merged.strftime('%Y-%m')]
        row['prs'] += 1
        row['rework'] += rework
        row['requested'] += requested
        row['first_pass'] += rework == 0 and requested == 0
    rows = []
    for month in sorted(set(months) | set(learning)):
        m, k = months.get(month, {'prs': 0, 'first_pass': 0, 'rework': 0, 'requested': 0}), learning.get(month, {})
        n = m['prs']
        rows.append({'month': month, 'prs': n,
                     'first_pass_rate': round(m['first_pass'] / n, 2) if n else None,
                     'rework_per_pr': round(m['rework'] / n, 2) if n else None,
                     'changes_requested_per_pr': round(m['requested'] / n, 2) if n else None,
                     'rules_added': k.get('rules', 0), 'knowledge_commits': k.get('knowledge', 0)})
    return rows


def markdown(rows, include_all):
    def cell(value, percent=False):
        return '-' if value is None else f'{value:.0%}' if percent else f'{value:g}'

    lines = [f"# AI の PR の手戻り（{'すべての PR' if include_all else 'AI が作った PR'}）", '',
             '| 月 | PR 数 | 一発で通った割合 | 手戻りコミット/PR | 変更要求/PR | 追加したルール | 知識の更新 |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {r['month']} | {r['prs']} | {cell(r['first_pass_rate'], True)} | {cell(r['rework_per_pr'])} | "
                     f"{cell(r['changes_requested_per_pr'])} | {r['rules_added']} | {r['knowledge_commits']} |")
    if not rows:
        lines.append('| - | 0 | - | - | - | 0 | 0 |')
    lines += ['', '一発で通った割合が上がり、手戻りと変更要求が下がっていれば、AI がプロジェクトに慣れてきたと読める。'
                  'PR 数が少ない月（目安 5 件未満）は傾向とみなさない。']
    return '\n'.join(lines) + '\n'


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--since', help='この日以降にマージされた PR（YYYY-MM-DD）')
    parser.add_argument('--all', action='store_true', help='AI が作った PR に限らず、すべての PR を集計する')
    parser.add_argument('--input', type=Path, help='gh pr list --json ' + FIELDS + ' の出力を保存したファイル')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1], help='git の履歴を読むリポジトリ')
    parser.add_argument('--json', action='store_true', help='JSON で出力する')
    args = parser.parse_args(argv)
    try:
        if args.since:
            datetime.date.fromisoformat(args.since)
        prs = json.loads(args.input.read_text(encoding='utf-8')) if args.input else fetch_prs(args.since)
        if not isinstance(prs, list):
            raise MetricsError('PR の一覧（JSON の配列）ではありません')
    except (MetricsError, OSError, ValueError) as error:
        print(f'ai_metrics: 集計できません：{error}', file=sys.stderr)
        return 2
    rows = summarize(prs, args.all, args.since, learning_by_month(args.root.resolve(), args.since))
    print(json.dumps(rows, ensure_ascii=False, indent=1) if args.json else markdown(rows, args.all), end='' if not args.json else '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
