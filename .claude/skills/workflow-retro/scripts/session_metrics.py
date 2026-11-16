#!/usr/bin/env python3
"""Content-free metrics from Claude Code session transcripts of a project that uses the templates.

    python3 session_metrics.py --project /path/to/adopter-project [--since DAYS] [--json]
    python3 session_metrics.py --transcripts ~/.claude/projects/<dir> [--since DAYS] [--json]

    python3 session_metrics.py ... --timeline SESSION

--project and --transcripts may be repeated (one per git worktree, for example).
--timeline prints the ordered events of the sessions whose id starts with SESSION, each with
its line number in the .jsonl file, so the place to read is found without paging the file.

Reads the session .jsonl files and reports counts only: no prompt text, no file contents,
no command arguments. Sessions are identified by the first 8 characters of their id.

    python3 session_metrics.py ... --excerpt SESSION FROM TO

--excerpt is the exception: it prints truncated assistant text and commands from lines
FROM..TO of one session, for reading on this machine. Its output is transcript content
and must not be copied into a repository, an issue or a report.
The metrics are proxies for "was the task finished the way the templates ask"; read the
flagged sessions before drawing a conclusion.

Exit code: 0 on success, 2 if no transcript directory or session is found.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys

# The wrapper may be called through a path (./mvnw, ./sub/mvnw, ..\\mvnw.cmd); a bare `mvn` is the system Maven.
MAVEN = re.compile(r'(?:^|[\s;&|(])((?:[\w.\\/-]*[\\/])?mvnw(?:\.cmd)?|mvn)\s+([^;&|]*)')
TEST_GOALS = {'test', 'verify', 'package', 'install', 'integration-test'}
BROWSER_TOOLS = ('mcp__playwright__', 'mcp__chrome-devtools__', 'mcp__claude-in-chrome__')
# htmx-check, Playwright Test, and the screen-test runner (run.mjs --engine …, or npm test inside screen-tests/).
# A --build-only run opens no browser, so it is not a check.
BROWSER_COMMANDS = (r'htmx-check\.mjs|\bplaywright\s+test\b'
                    r'|\brun\.mjs\b(?![^\n;&|]*--build-only)[^\n;&|]*--engine\b'
                    r'|screen-tests\b[^\n]*\bnpm\s+(?:run\s+)?test\b')
SKIP_TESTS = ('-DskipTests', '-Dmaven.test.skip')
EDIT_TOOLS = {'Edit', 'Write', 'MultiEdit', 'NotebookEdit'}
SYSTEM_TEXT = ('<', '[Request interrupted', 'Caveat:')
SUBCOMMAND_TOOLS = {'git', 'gh', 'npm', 'npx', 'pnpm', 'yarn', 'docker', 'kubectl', 'pip', 'uv', 'brew'}
MAVEN_GOALS = {'clean', 'compile', 'test', 'verify', 'package', 'install', 'deploy', 'spring-boot:run'}
SHELL_WORDS = {'do', 'done', 'then', 'fi', 'for', 'if', 'while', 'else', 'elif', 'case', 'esac', 'in', 'function'}


def edit_kind(path):
    """Which check a changed file needs: backend/test/migration -> Maven tests, view -> browser."""
    path = '/' + path.replace('\\', '/').lstrip('/')
    name = path.rsplit('/', 1)[-1].lower()
    if '/db/migration/' in path:
        return 'migration'
    if '/src/test/' in path:
        return 'test'
    if '/src/main/' not in path:
        return 'other'
    if name.endswith(('.jsp', '.jspf', '.tag', '.html', '.js', '.css')) or '/src/main/webapp/' in path \
            or '/resources/templates/' in path or '/resources/static/' in path:
        return 'view'
    # Java sources, MyBatis mapper XML, SQL and configuration all change runtime behaviour.
    if name.endswith(('.java', '.xml', '.sql', '.properties', '.yml', '.yaml')):
        return 'backend'
    return 'other'


def command_head(command):
    """Program name plus a plain subcommand, e.g. './mvnw test', 'git commit'. Never arguments or paths."""
    words = command.strip().split()
    while words and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*', words[0]):
        words.pop(0)
    if not words or words[0] in SHELL_WORDS or not re.fullmatch(r'(?:\./|/)?[A-Za-z][\w./-]*', words[0]):
        return ''
    # Only the program's basename is kept: a path, even a relative one, can name a customer or a project.
    head = words[0] if re.fullmatch(r'\./mvnw(\.cmd)?', words[0]) else words[0].rsplit('/', 1)[-1]
    # A second word is kept only where it is a subcommand of a known tool, never free text.
    if len(words) > 1 and (head in SUBCOMMAND_TOOLS and re.fullmatch(r'[a-z][a-z0-9:-]*', words[1])
                           or 'mvn' in head and words[1] in MAVEN_GOALS):
        head += ' ' + words[1]
    return head[:40]


def label(value):
    """Skill and subagent names are identifiers; anything else is reported as 'other'."""
    value = str(value)
    return value if re.fullmatch(r'[\w:.-]{1,40}', value) else 'other'


def is_human_prompt(entry, content):
    if entry.get('isMeta') or entry.get('isCompactSummary') or entry.get('isSidechain'):
        return False
    origin = entry.get('origin')
    if isinstance(origin, dict):
        return origin.get('kind') == 'human'
    if entry.get('turnOrigin'):
        return entry['turnOrigin'] == 'human'
    # Older transcripts carry no origin: fall back to "plain text that is not harness output".
    texts = [content] if isinstance(content, str) else [
        block.get('text', '') for block in content if isinstance(block, dict) and block.get('type') == 'text']
    if isinstance(content, list) and any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in content):
        return False
    return any(text.strip() and not text.lstrip().startswith(SYSTEM_TEXT) for text in texts)


def entries(path):
    """Entries of a session and of its subagents (<session>/subagents/*.jsonl), in time order.

    Yields (source, line_no, entry, is_subagent). Subagent files are merged because a check
    delegated to a subagent is still a check; entries without a timestamp keep their place.
    """
    rows = []
    files = [path] + sorted((path.parent / path.stem / 'subagents').glob('*.jsonl'))
    for order, file in enumerate(files):
        stamp = ''
        with open(file, encoding='utf-8', errors='replace') as handle:
            for line_no, line in enumerate(handle, 1):
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict):
                    continue
                stamp = str(entry.get('timestamp') or stamp)
                rows.append((stamp, order, line_no, entry))
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    for _stamp, order, line_no, entry in rows:
        yield ('' if order == 0 else files[order].stem[:14] + ':'), line_no, entry, order > 0


def analyse(path):
    """Return the metrics of one session file, or None if it holds no activity."""
    m = {'session': path.stem[:8], 'prompts': 0, 'interrupts': 0, 'tool_calls': 0, 'tool_errors': 0,
         'denials': Counter(), 'edits': Counter(), 'maven_tests': 0, 'maven_test_failures': 0, 'maven_compiles': 0,
         'system_mvn': 0, 'browser_checks': 0, 'browser_check_failures': 0, 'commits': 0, 'compactions': 0,
         'skills': Counter(), 'agents': Counter(), 'spec_xlsx_reads': 0, 'commands': Counter(), 'cost_usd': None,
         'file': str(path), 'events': []}
    step = 0
    last = {'code': -1, 'view': -1, 'maven-test': -1, 'browser-check': -1}
    pending = {}  # tool_use id -> check started by that call; it counts once its result is not an error

    def event(source, line_no, name):
        m['events'].append((f'{source}{line_no}', name))

    for source, line_no, entry, subagent in entries(path):
        kind = entry.get('type')
        if kind == 'cost-state' and isinstance(entry.get('totalCostUSD'), (int, float)):
            m['cost_usd'] = round(entry['totalCostUSD'], 2)
        elif kind == 'system' and entry.get('subtype') == 'compact_boundary' and not subagent:
            m['compactions'] += 1
        if kind not in ('user', 'assistant'):
            continue
        content = (entry.get('message') or {}).get('content') or ''
        blocks = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
        if kind == 'user':
            denial = entry.get('toolDenialKind')
            decision = entry.get('permissionDecision')
            if not denial and isinstance(decision, dict) and decision.get('decision') == 'reject':
                denial = decision.get('reasonType') or 'rejected'
            if denial:
                m['denials'][label(denial)] += 1
                event(source, line_no, 'denial:' + label(denial))
            for block in blocks:
                if block.get('type') != 'tool_result':
                    continue
                check = pending.pop(block.get('tool_use_id'), None)
                if block.get('is_error'):
                    m['tool_errors'] += 1
                    event(source, line_no, f'{check[0]}-failed' if check else 'tool-error')
                    if check:
                        m['maven_test_failures' if check[0] == 'maven-test' else 'browser_check_failures'] += 1
                elif check:
                    last[check[0]] = check[1]
            if subagent or entry.get('isSidechain'):
                continue
            texts = [content] if isinstance(content, str) else [b.get('text', '') for b in blocks if b.get('type') == 'text']
            if any(text.startswith('[Request interrupted') for text in texts):
                m['interrupts'] += 1
                event(source, line_no, 'interrupt')
            elif is_human_prompt(entry, content):
                m['prompts'] += 1
                event(source, line_no, 'prompt')
            continue
        for block in blocks:
            if block.get('type') != 'tool_use':
                continue
            step += 1
            m['tool_calls'] += 1
            name, args = block.get('name') or '', block.get('input') or {}
            checks = set()
            if name in EDIT_TOOLS:
                category = edit_kind(str(args.get('file_path') or args.get('notebook_path') or ''))
                m['edits'][category] += 1
                event(source, line_no, 'edit:' + category)
                # Changed tests and persistence files need the same Maven run as changed Java code.
                if category in ('backend', 'test', 'migration'):
                    last['code'] = step
                elif category == 'view':
                    last['view'] = step
            elif name == 'Read' and str(args.get('file_path', '')).lower().endswith(('.xlsx', '.xlsm')):
                m['spec_xlsx_reads'] += 1
                event(source, line_no, 'xlsx-read')
            elif name == 'Skill':
                m['skills'][label(args.get('skill'))] += 1
                event(source, line_no, 'skill:' + label(args.get('skill')))
            elif name in ('Agent', 'Task'):
                agent = label(args.get('subagent_type') or 'general-purpose')
                m['agents'][agent] += 1
                event(source, line_no, 'agent:' + agent)
            elif name.startswith(BROWSER_TOOLS):
                checks.add('browser-check')
            elif name in ('Bash', 'PowerShell'):
                command = str(args.get('command') or '')
                # A heredoc body is data, not commands: count only what precedes it.
                for part in re.split(r'&&|\|\||[;|\n]', command.split('<<', 1)[0]):
                    head = command_head(part)
                    if head:
                        m['commands'][head] += 1
                if re.search(r'(?:^|[\s;&|(])git\s+commit\b', command):
                    m['commits'] += 1
                    event(source, line_no, 'commit')
                if re.search(BROWSER_COMMANDS, command):
                    checks.add('browser-check')
                for wrapper, goals in MAVEN.findall(command):
                    if wrapper == 'mvn':
                        m['system_mvn'] += 1
                    words = goals.split()
                    skipped = any(word.startswith(SKIP_TESTS) for word in words)
                    if TEST_GOALS.intersection(words) and not skipped:
                        checks.add('maven-test')
                    elif TEST_GOALS.intersection(words) or 'compile' in words:
                        m['maven_compiles'] += 1
                        event(source, line_no, 'maven-compile')
            for check in sorted(checks):
                m['maven_tests' if check == 'maven-test' else 'browser_checks'] += 1
                event(source, line_no, check)
                pending[block.get('id')] = (check, step)
    if not m['tool_calls'] and not m['prompts']:
        return None
    # "Unverified": the last change of that kind was not followed by a passing check of the kind the templates require.
    m['backend_unverified'] = last['code'] > last['maven-test']
    m['view_unverified'] = last['view'] > last['browser-check']
    code_edits = sum(count for category, count in m['edits'].items() if category != 'other')
    m['outcome'] = ('no-code-edit' if not code_edits else
                    'unverified' if m['backend_unverified'] or m['view_unverified'] else 'verified')
    return m


def excerpt(directories, session, first, last, width=200):
    """Print what the assistant said and ran on lines first..last of one session, truncated."""
    files = [path for directory in directories for path in directory.glob(f'{session[:8]}*.jsonl')]
    if len(files) != 1 or not (first.isdigit() and last.isdigit()):
        print(f'error: --excerpt needs one matching session and numeric lines (matched {len(files)})', file=sys.stderr)
        return 2
    print('# LOCAL ONLY: transcript content. Do not copy into a repository, an issue or a report.')
    with open(files[0], encoding='utf-8', errors='replace') as handle:
        for line_no, line in enumerate(handle, 1):
            if line_no > int(last):
                break
            if line_no < int(first):
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            content = (entry.get('message') or {}).get('content') if isinstance(entry, dict) else None
            if entry.get('type') not in ('user', 'assistant') or not content:
                continue
            for block in content if isinstance(content, list) else [{'type': 'text', 'text': content}]:
                if not isinstance(block, dict):
                    continue
                if block.get('type') == 'text':
                    shown = ('says', block.get('text') or '')
                elif block.get('type') == 'tool_use':
                    args = block.get('input') or {}
                    shown = (block.get('name'), str(args.get('command') or args.get('file_path') or args.get('skill')
                                                    or args.get('subagent_type') or ''))
                elif block.get('type') == 'tool_result' and block.get('is_error'):
                    result = block.get('content')
                    shown = ('ERROR', result if isinstance(result, str) else json.dumps(result, ensure_ascii=False))
                else:
                    continue
                text = ' '.join(shown[1].split())
                print(f"{line_no:>6} {entry['type'][0]} {shown[0]}: {text[:width]}{'…' if len(text) > width else ''}")
    return 0


def transcript_dir(project, claude_dir):
    encoded = re.sub(r'[^A-Za-z0-9]', '-', str(Path(project).expanduser().resolve()))
    return claude_dir / 'projects' / encoded


def summarise(sessions):
    edited = [s for s in sessions if s['outcome'] != 'no-code-edit']
    total = Counter()
    for key in ('prompts', 'interrupts', 'tool_calls', 'tool_errors', 'system_mvn', 'spec_xlsx_reads', 'commits', 'compactions',
                'maven_test_failures', 'browser_check_failures'):
        total[key] = sum(s[key] for s in sessions)
    merged = {key: sum((s[key] for s in sessions), Counter()) for key in ('denials', 'skills', 'agents', 'commands', 'edits')}

    def rate(part, whole):
        return None if not whole else round(100 * part / whole)

    backend = [s for s in edited if s['edits']['backend'] or s['edits']['test'] or s['edits']['migration']]
    view = [s for s in edited if s['edits']['view']]
    return {
        'sessions': len(sessions),
        'sessions_with_code_edits': len(edited),
        'verified_pct': rate(sum(s['outcome'] == 'verified' for s in edited), len(edited)),
        'backend_verified_pct': rate(sum(not s['backend_unverified'] for s in backend), len(backend)),
        'view_verified_pct': rate(sum(not s['view_unverified'] for s in view), len(view)),
        'prompts_per_code_session': None if not edited else round(sum(s['prompts'] for s in edited) / len(edited), 1),
        'tool_error_pct': rate(total['tool_errors'], total['tool_calls']),
        'totals': dict(total),
        'denials': dict(merged['denials']),
        'skills': dict(merged['skills']),
        'agents': dict(merged['agents']),
        'edits': dict(merged['edits']),
        'top_commands': merged['commands'].most_common(15),
        'cost_usd': round(sum(s['cost_usd'] or 0 for s in sessions), 2),
    }


def render(summary, sessions, out):
    def pct(value):
        return 'n/a' if value is None else f'{value}%'

    print(f"sessions: {summary['sessions']}  (with code edits: {summary['sessions_with_code_edits']})", file=out)
    print(f"verified after the last edit: {pct(summary['verified_pct'])}"
          f"  backend: {pct(summary['backend_verified_pct'])}  view: {pct(summary['view_verified_pct'])}", file=out)
    print(f"prompts per code session: {summary['prompts_per_code_session']}  tool errors: {pct(summary['tool_error_pct'])}"
          f"  interrupts: {summary['totals']['interrupts']}  compactions: {summary['totals']['compactions']}", file=out)
    print(f"denials: {summary['denials'] or 'none'}", file=out)
    print(f"system mvn instead of the wrapper: {summary['totals']['system_mvn']}"
          f"  direct xlsx reads: {summary['totals']['spec_xlsx_reads']}", file=out)
    print(f"skills: {summary['skills'] or 'none'}  subagents: {summary['agents'] or 'none'}", file=out)
    print('top commands: ' + ', '.join(f'{head} ×{count}' for head, count in summary['top_commands']), file=out)
    print('\n| session | outcome | prompts | edits b/v/t | mvn test | browser | errors | denials | interrupts |', file=out)
    print('|---|---|---:|---|---:|---:|---:|---:|---:|', file=out)
    quiet = sum(s['outcome'] == 'no-code-edit' for s in sessions)
    for s in sorted(sessions, key=lambda s: (s['outcome'] != 'unverified', -s['prompts'])):
        if s['outcome'] == 'no-code-edit':
            continue
        edits = f"{s['edits']['backend']}/{s['edits']['view']}/{s['edits']['test']}"
        print(f"| {s['session']} | {s['outcome']} | {s['prompts']} | {edits} | {s['maven_tests']} | {s['browser_checks']} "
              f"| {s['tool_errors']} | {sum(s['denials'].values())} | {s['interrupts']} |", file=out)
    if quiet:
        print(f'\n{quiet} sessions without code edits are not listed (--json includes them).', file=out)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--project', type=Path, action='append', default=[],
                        help='project root; its transcripts are looked up under the Claude directory (repeatable)')
    parser.add_argument('--transcripts', type=Path, action='append', default=[],
                        help='directory that holds the session .jsonl files (repeatable)')
    parser.add_argument('--claude-dir', type=Path, default=Path.home() / '.claude')
    parser.add_argument('--since', type=int, metavar='DAYS', help='only sessions active in the last DAYS days')
    parser.add_argument('--json', action='store_true', help='print the summary and per-session metrics as JSON')
    parser.add_argument('--timeline', metavar='SESSION', help='print the ordered events of sessions whose id starts with SESSION')
    parser.add_argument('--excerpt', nargs=3, metavar=('SESSION', 'FROM', 'TO'),
                        help='print truncated transcript text of lines FROM..TO of one session (local reading only)')
    args = parser.parse_args(argv)

    directories = [d.expanduser() for d in args.transcripts]
    directories += [transcript_dir(project, args.claude_dir.expanduser()) for project in args.project]
    if not directories:
        parser.error('give --project or --transcripts')
    missing = [d for d in directories if not d.is_dir()]
    if missing:
        print('error: no transcript directory: ' + ', '.join(map(str, missing)), file=sys.stderr)
        return 2
    if args.excerpt:
        return excerpt(directories, *args.excerpt)
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.since) if args.since else None
    sessions = []
    for path in sorted(path for directory in directories for path in directory.glob('*.jsonl')):
        if cutoff and datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
            continue
        metrics = analyse(path)
        if metrics:
            sessions.append(metrics)
    if not sessions:
        print('error: no sessions with activity', file=sys.stderr)
        return 2
    if args.timeline:
        chosen = [s for s in sessions if s['session'].startswith(args.timeline[:8])]
        if not chosen:
            print(f'error: no session starts with {args.timeline}', file=sys.stderr)
            return 2
        for s in chosen:
            print(f"{s['session']}  {s['outcome']}  {s['file']}")
            previous, repeat, first = None, 0, None
            for line_no, event in s['events'] + [(None, None)]:
                if event == previous:
                    repeat += 1
                    continue
                if previous is not None:
                    print(f'  line {first:>8}  {previous}' + (f' ×{repeat}' if repeat > 1 else ''))
                previous, repeat, first = event, 1, line_no
        return 0
    for s in sessions:
        del s['events'], s['file']
    summary = summarise(sessions)
    if args.json:
        json.dump({'summary': summary, 'sessions': sessions}, sys.stdout, ensure_ascii=False, indent=1, default=dict)
        print()
    else:
        render(summary, sessions, sys.stdout)
    return 0


if __name__ == '__main__':
    sys.exit(main())
