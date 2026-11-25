#!/usr/bin/env python3
"""Non-destructive installer for the workflow templates.

Default is a dry run that prints the plan; pass --apply to write.
Existing files are never overwritten:

* missing file             -> create (byte-for-byte copy)
* identical file           -> skip
* settings.json / .mcp.json -> merge (union of permission rules, add missing
  MCP servers and hardening switches; existing values win, ``hooks`` is never added)
* .gitignore               -> merge (missing lines go first, so existing rules,
  which git reads later, keep precedence)
* .gitattributes           -> merge (missing lines are appended)
* any other differing file -> conflict (left untouched; --diff shows the difference)
* symlinked destination file -> conflict (never written through; a symlinked
  parent directory such as a shared .claude/ is followed)
* screen-tests/*           -> optional (only with --with-screen-tests: a Node
  project that installs the screen-test framework from GitHub)
* .github/workflows/*      -> optional (only with --with-workflows: they run
  with repository permissions and need secrets)
* .github/workflows/copilot-setup-steps.yml.example -> optional (only with
  --with-copilot-cloud-agent; not part of --with-workflows)
* src/test/java/*          -> optional (only with --with-archunit: the ArchUnit test
  compiles only after the dependency in config/quality/pom-snippet.xml is added)

``doctor`` checks a project that already has the templates: placeholders left in
AGENTS.md, the CLAUDE.md import, permission rules, MCP servers, generated Copilot
instructions, the guard checks and the rules AGENTS.md says guard, ArchUnit and
PMD enforce, the feature map, and tracked secrets. It only reads.

Exit code: 0 on success, 1 if a file could not be written or ``doctor`` found a failure.

Usage:
    python3 scripts/install.py project /path/to/project [--apply] [--diff] [--with-workflows] [--with-screen-tests] [--with-archunit]
                                      [--with-copilot-cloud-agent]
    python3 scripts/install.py user [--claude-dir ~/.claude] [--apply] [--diff]
    python3 scripts/install.py doctor /path/to/project
"""
import argparse
import difflib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT_TEMPLATES = ROOT / 'templates/project'
USER_SKILLS = ROOT / 'templates/user/skills'
USER_LICENSE = USER_SKILLS / 'LICENSE-mattpocock-skills'
JSON_MERGE = {'.claude/settings.json', '.mcp.json'}
LINE_MERGE = {'.gitignore', '.gitattributes'}
# Workflows act on the repository as soon as they are committed, so they are opt-in.
WORKFLOWS = '.github/workflows/'
# A Node project of its own; projects that do not run screen tests should not get it.
SCREEN_TESTS = 'screen-tests/'
# Compiles only once the project's pom.xml has the ArchUnit dependency.
ARCHUNIT = 'src/test/java/'
# Only for teams that use the GitHub Copilot cloud agent; kept apart from the other workflows.
COPILOT_CLOUD_AGENT = '.github/workflows/copilot-setup-steps.yml.example'
POM_SNIPPET = 'config/quality/pom-snippet.xml'
KINDS = ('create', 'merge', 'skip', 'conflict', 'optional', 'error')
PERMISSION_LISTS = ('allow', 'deny', 'ask')
# Top-level switches the company edition turns off; added when absent, never overwritten.
HARDENING_KEYS = ('disableClaudeAiConnectors', 'enableArtifact')
IGNORED_PARTS = {'__pycache__'}


class Action:
    def __init__(self, kind, rel, source, dest, content=None, note=''):
        self.kind, self.rel, self.source, self.dest = kind, rel, source, dest
        self.content, self.note = content, note


def template_files(base):
    for path in sorted(base.rglob('*')):
        rel = path.relative_to(base)
        if path.is_file() and not IGNORED_PARTS.intersection(rel.parts) and path.suffix != '.pyc':
            yield rel.as_posix(), path


def dump_json(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def string_list(obj, key, label):
    values = obj.get(key, [])
    if not isinstance(values, list):
        raise ValueError(f'"{label}" is not a list')
    if not all(isinstance(value, str) for value in values):
        raise ValueError(f'"{label}" contains non-string entries')
    return values


def merge_settings(existing, template):
    merged = dict(existing)
    notes = []
    if '$schema' in template and '$schema' not in merged:
        merged['$schema'] = template['$schema']
    if 'permissions' in template:
        current = merged.get('permissions')
        if current is not None and not isinstance(current, dict):
            raise ValueError('"permissions" is not an object')
        permissions = dict(current or {})
        for key in PERMISSION_LISTS:
            wanted = template['permissions'].get(key, [])
            have = string_list(permissions, key, f'permissions.{key}')
            added = [rule for rule in wanted if rule not in have]
            if added:
                permissions[key] = have + added
        allowed = {rule for rule in permissions.get('allow', []) if isinstance(rule, str)}
        for key in ('deny', 'ask'):
            for rule in template['permissions'].get(key, []):
                if rule in allowed:
                    notes.append(f'existing allow also contains {key} rule {rule!r}; review it')
        broad = [r for r in allowed if re.search(r'mvnw(\.cmd)?(:| )\*\)$', r.strip())]
        notes.extend(f'broad rule {r!r} also allows deploy/arbitrary goals; consider removing' for r in sorted(broad))
        # Scalar permission keys (e.g. disableBypassPermissionsMode): add when absent, existing value wins.
        for key, value in template['permissions'].items():
            if key not in PERMISSION_LISTS and key not in permissions:
                permissions[key] = value
            elif key not in PERMISSION_LISTS and permissions[key] != value:
                notes.append(f'"permissions.{key}" differs from template; kept existing')
        merged['permissions'] = permissions
    for key in HARDENING_KEYS:
        if key in template and key not in merged:
            merged[key] = template[key]
        elif key in template and merged[key] != template[key]:
            notes.append(f'{key!r} differs from template; kept existing')
    if 'mcpServers' in template:
        current = merged.get('mcpServers')
        if current is not None and not isinstance(current, dict):
            raise ValueError('"mcpServers" is not an object')
        servers = dict(current or {})
        for name, config in template['mcpServers'].items():
            if name not in servers:
                servers[name] = config
            elif servers[name] != config:
                notes.append(f'MCP server {name!r} differs from template; kept existing')
        merged['mcpServers'] = servers
    return merged, notes


def merge_lines(existing_text, template_text, prepend=False, by_pattern=False):
    """Return (merged_text or None, notes).

    In both formats the last matching line wins. prepend puts the missing lines
    first so existing rules keep precedence (.gitignore: an appended ``.env.*``
    would re-ignore an existing ``!.env.example``). Appending lets the template's
    specific rules override a generic one such as ``* text=auto`` (.gitattributes);
    by_pattern reports the same-pattern rules this overrides.
    """
    bom = '\ufeff' if existing_text.startswith('\ufeff') else ''
    existing_text = existing_text[len(bom):]
    have = {line.strip() for line in existing_text.splitlines()}
    missing = [line for line in template_text.splitlines() if line.strip() and line.strip() not in have]
    if not missing:
        return None, []
    notes = []
    if by_pattern:
        patterns = {line.split()[0] for line in have if line and not line.startswith('#')}
        notes = [f'existing rule for {line.split()[0]!r} is overridden by appended {line.strip()!r}; review it'
                 for line in missing if line.split()[0] in patterns]
    newline = '\r\n' if '\r\n' in existing_text else '\n'
    block = newline.join(missing) + newline
    if prepend:
        return bom + block + existing_text, notes
    prefix = existing_text if not existing_text or existing_text.endswith(('\n', '\r')) else existing_text + newline
    return bom + prefix + block, notes


def plan_file(rel, source, dest, merge_kind=None):
    # Check the link itself first: exists() follows it, so a dangling link would
    # look like a missing file and be created wherever it points.
    if dest.is_symlink():
        return Action('conflict', rel, source, dest, note='destination is a symlink; merge manually')
    if not dest.exists():
        return Action('create', rel, source, dest)
    if dest.is_dir():
        return Action('conflict', rel, source, dest, note='destination is a directory')
    src_bytes, dst_bytes = source.read_bytes(), dest.read_bytes()
    if src_bytes == dst_bytes:
        return Action('skip', rel, source, dest)
    if merge_kind == 'json':
        try:
            existing = json.loads(dst_bytes.decode('utf-8-sig'))
            if not isinstance(existing, dict):
                raise ValueError('top level is not an object')
            merged, notes = merge_settings(existing, json.loads(src_bytes.decode('utf-8')))
        except (ValueError, TypeError, UnicodeDecodeError) as error:
            return Action('conflict', rel, source, dest, note=f'cannot merge JSON: {error}')
        note = '; '.join(notes)
        if merged == existing:
            return Action('skip', rel, source, dest, note=note)
        return Action('merge', rel, source, dest, content=dump_json(merged), note=note)
    if merge_kind == 'lines':
        try:
            attributes = rel.endswith('.gitattributes')
            merged, notes = merge_lines(dst_bytes.decode('utf-8'), src_bytes.decode('utf-8'),
                                        prepend=not attributes, by_pattern=attributes)
        except UnicodeDecodeError as error:
            return Action('conflict', rel, source, dest, note=f'cannot merge lines: {error}')
        if merged is None:
            return Action('skip', rel, source, dest)
        return Action('merge', rel, source, dest, content=merged, note='; '.join(notes))
    return Action('conflict', rel, source, dest, note='differs from template; compare and merge manually')


def plan_project(target, with_workflows=False, with_screen_tests=False, with_archunit=False,
                 with_copilot_cloud_agent=False):
    actions = []
    for rel, source in template_files(PROJECT_TEMPLATES):
        dest = target / rel
        flag = ('--with-copilot-cloud-agent' if rel == COPILOT_CLOUD_AGENT and not with_copilot_cloud_agent
                else None if rel == COPILOT_CLOUD_AGENT
                else '--with-workflows' if rel.startswith(WORKFLOWS) and not with_workflows
                else '--with-screen-tests' if rel.startswith(SCREEN_TESTS) and not with_screen_tests
                else '--with-archunit' if rel.startswith(ARCHUNIT) and not with_archunit else None)
        if flag and not os.path.lexists(dest):
            actions.append(Action('optional', rel, source, dest, note=f'not installed; pass {flag}'))
            continue
        kind = 'json' if rel in JSON_MERGE else 'lines' if rel in LINE_MERGE else None
        action = plan_file(rel, source, dest, kind)
        if rel.startswith(ARCHUNIT) and action.kind == 'create' and 'archunit' not in all_poms(target):
            action.note = f'add the archunit-junit5 dependency from {POM_SNIPPET} to pom.xml, or test compilation fails'
        actions.append(action)
    claude_md = next(a for a in actions if a.rel == 'CLAUDE.md')
    if claude_md.kind == 'conflict' and claude_md.dest.is_file() and not claude_md.dest.is_symlink() \
            and '@AGENTS.md' not in claude_md.dest.read_text(encoding='utf-8', errors='replace'):
        claude_md.note = 'differs from template and lacks the @AGENTS.md import; add it or Claude Code ignores AGENTS.md'
    return actions


def plan_user(claude_dir):
    actions = []
    for skill in sorted(p for p in USER_SKILLS.iterdir() if p.is_dir()):
        for rel, source in template_files(skill):
            actions.append(plan_file(f'skills/{skill.name}/{rel}', source, claude_dir / 'skills' / skill.name / rel))
        # Keep the upstream MIT notice next to each copied skill.
        actions.append(plan_file(f'skills/{skill.name}/LICENSE', USER_LICENSE, claude_dir / 'skills' / skill.name / 'LICENSE'))
    return actions


def apply(actions):
    """Write create/merge actions. A failed write becomes an ``error`` action and the rest still run."""
    for action in actions:
        if action.kind not in ('create', 'merge'):
            continue
        try:
            action.dest.parent.mkdir(parents=True, exist_ok=True)
            if action.kind == 'create':
                shutil.copyfile(action.source, action.dest)
                if os.access(action.source, os.X_OK):
                    shutil.copymode(action.source, action.dest)
            else:
                with open(action.dest, 'w', encoding='utf-8', newline='') as handle:
                    handle.write(action.content)
        except OSError as error:
            action.kind, action.note = 'error', f'not written: {error}'


def conflict_diff(action):
    """Unified diff from the existing file to the template, or None if either is not UTF-8 text."""
    try:
        existing = action.dest.read_text(encoding='utf-8').splitlines()
        template = action.source.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    return '\n'.join(difflib.unified_diff(existing, template, f'{action.rel} (existing)',
                                          f'{action.rel} (template)', lineterm=''))


def report(actions, applied, out=None, show_diff=False):
    out = out or sys.stdout
    width = max((len(a.kind) for a in actions), default=0)
    for action in actions:
        line = f'{action.kind.ljust(width)}  {action.rel}'
        if action.note:
            line += f'  ({action.note})'
        print(line, file=out)
    counts = {kind: sum(a.kind == kind for a in actions) for kind in KINDS}
    print('\n' + ', '.join(f'{k}: {v}' for k, v in counts.items() if v or k in KINDS[:4]), file=out)
    if not applied and (counts['create'] or counts['merge']):
        print('Dry run only. Re-run with --apply to write create/merge actions.', file=out)
    if counts['conflict']:
        print('Conflicts were not modified; compare them with the template under templates/'
              + ('.' if show_diff else ' (--diff prints the differences).'), file=out)
    if counts['error']:
        print('Some files could not be written; fix the cause and re-run.', file=out)
    if show_diff:
        for action in actions:
            diff = conflict_diff(action) if action.kind == 'conflict' else None
            if diff:
                print('\n' + diff, file=out)


def doctor(target):
    """Read-only health check of an adopted project. Returns [(level, message)], level in ok/warn/fail."""
    findings = []

    def add(level, message):
        findings.append((level, message))

    def text(rel):
        path = target / rel
        return path.read_text(encoding='utf-8', errors='replace') if path.is_file() else None

    agents = text('AGENTS.md')
    if agents is None:
        add('fail', 'AGENTS.md is missing: the agent has no project rules')
    else:
        todo = agents.count('<!-- TODO')
        add('fail' if todo else 'ok', f'AGENTS.md: {todo} TODO placeholder(s) left; the agent reads them as missing project facts'
            if todo else 'AGENTS.md: no TODO placeholders left')
        lines = len(agents.splitlines())
        add('warn' if lines >= 150 else 'ok', f'AGENTS.md: {lines} lines (budget: under 150, it is loaded into every session)')
    claude_md = text('CLAUDE.md')
    if claude_md is None:
        add('fail', 'CLAUDE.md is missing: the @AGENTS.md import is missing')
    else:
        imported = '@AGENTS.md' in claude_md
        add('ok' if imported else 'fail', 'CLAUDE.md imports @AGENTS.md' if imported
            else 'CLAUDE.md exists without @AGENTS.md: Claude Code then ignores AGENTS.md')
    skill = text('.claude/skills/spring-endpoint/SKILL.md')
    if skill is not None and '<!-- TODO' in skill:
        add('warn', '.claude/skills/spring-endpoint/SKILL.md: reference path placeholder not filled in')

    raw = text('.claude/settings.json')
    if raw is None:
        add('warn', '.claude/settings.json is missing: no shared permission rules')
    else:
        try:
            settings = json.loads(raw.lstrip('\ufeff'))
            permissions = settings.get('permissions', {})
            allow, deny, _ask = (string_list(permissions, key, f'permissions.{key}') for key in PERMISSION_LISTS)
        except (ValueError, AttributeError) as error:
            settings = None
            add('fail', f'.claude/settings.json is not a valid settings object: {error}')
        if settings is not None:
            broad = sorted(r for r in allow if isinstance(r, str) and re.search(r'mvnw(\.cmd)?(:| )\*\)$', r.strip()))
            add('warn' if broad else 'ok', f'broad Maven allow rule(s) {broad} also permit deploy and arbitrary goals'
                if broad else 'no broad Maven allow rule')
            env_denied = any(isinstance(r, str) and r.startswith('Read(') and '.env' in r for r in deny)
            add('ok' if env_denied else 'warn', 'reading .env files is denied' if env_denied
                else 'no Read deny rule for .env files')
            if settings.get('hooks'):
                add('warn', 'hooks are registered: review them like CI changes, they run commands as the user')

    raw = text('.mcp.json')
    if raw is not None:
        try:
            servers = json.loads(raw.lstrip('\ufeff')).get('mcpServers', {})
            if not isinstance(servers, dict):
                raise ValueError('mcpServers must be an object')
        except (ValueError, AttributeError) as error:
            servers = {}
            add('fail', f'.mcp.json is not a valid MCP configuration: {error}')
        for name, config in sorted(servers.items()):
            if not isinstance(config, dict):
                add('fail', f'.mcp.json: server {name!r} must be an object')
                continue
            if config.get('url'):
                add('warn', f'MCP server {name!r} is a remote service: what is sent to it leaves the machine')
            try:
                args = string_list(config, 'args', f'mcpServers.{name}.args')
            except ValueError as error:
                add('fail', f'.mcp.json: {error}')
                continue
            if config.get('command') == 'npx' and not any(re.search(r'@\d+\.\d+\.\d+', a) for a in args):
                add('warn', f'MCP server {name!r} is started with npx without a pinned version')

    sync = target / 'scripts/sync_rules.py'
    if sync.is_file() and (target / '.claude/rules').is_dir():
        result = subprocess.run([sys.executable, str(sync), str(target), '--check'], capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
        add('ok' if result.returncode == 0 else 'fail', '.github/instructions/ matches .claude/rules/' if result.returncode == 0
            else '.github/instructions/ is out of sync with .claude/rules/: run scripts/sync_rules.py')

    doctor_guard(target, agents, add)
    doctor_structure(target, agents, add)
    doctor_codeowners(target, add)

    git = shutil.which('git')
    if git and (target / '.git').exists():
        result = subprocess.run([git, '-C', str(target), 'ls-files', '-z', '--', '.claude/settings.local.json', 'CLAUDE.local.md',
                                 ':(glob)**/.env', ':(glob)**/.env.*'], capture_output=True)
        if result.returncode:
            add('fail', 'git ls-files failed: could not check tracked local files')
        else:
            tracked = sorted(os.fsdecode(p) for p in result.stdout.split(b'\0') if p and p.split(b'/')[-1] != b'.env.example')
            add('fail' if tracked else 'ok', f'tracked by git but must stay local: {tracked}' if tracked
                else 'no local settings or .env files are tracked by git')
    return findings


def doctor_guard(target, agents, add):
    guard = target / 'scripts/guard.py'
    rules_path = target / 'config/guard/rules.json'
    if not guard.is_file() or not rules_path.is_file():
        add('warn', 'scripts/guard.py or config/guard/rules.json is missing: corrections stay prose that nothing enforces')
        return
    result = subprocess.run([sys.executable, str(guard), '--root', str(target)], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    last = (result.stdout.strip().splitlines() or result.stderr.strip().splitlines() or [''])[-1]
    if result.returncode == 0:
        add('ok', 'guard passes: ' + last)
    elif result.returncode == 1:
        hint = ('; a person accepts existing violations with scripts/guard.py --init-baseline'
                if not (target / 'config/guard/baseline.json').is_file() else '')
        add('fail', 'guard reports violations (run python3 scripts/guard.py)' + hint)
    else:
        add('fail', 'guard could not run its rules: ' + (result.stderr.strip() or last))
    try:
        ids = {rule.get('id') for rule in json.loads(rules_path.read_text(encoding='utf-8')).get('rules', [])}
    except (ValueError, AttributeError):
        return
    tagged = set()
    for tag in re.findall(r'〔guard:([^〕]*)〕', agents or ''):
        tagged.update(part.strip() for part in tag.split(',') if re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', part.strip()))
    unknown = sorted(tagged - ids)
    add('fail' if unknown else 'ok', f'AGENTS.md tags guard rules that do not exist: {unknown}' if unknown
        else f'AGENTS.md tags {len(tagged)} guard rule(s), all defined')
    feature_map = target / 'docs/feature-map'
    features = [p for p in feature_map.glob('*.md') if p.name != 'README.md'] if feature_map.is_dir() else []
    add('ok' if features else 'warn', f'feature map lists {len(features)} feature(s)' if features
        else 'docs/feature-map/ has no feature files: agents and reviewers have no shared names or recipes for the screens')


def all_poms(target):
    """Text of every pom.xml in the project (multi-module builds configure plugins per module)."""
    texts = []
    for pom in target.rglob('pom.xml'):
        if not {'target', 'node_modules', '.git'}.intersection(pom.relative_to(target).parts):
            texts.append(pom.read_text(encoding='utf-8', errors='replace'))
    return '\n'.join(texts)


def tags(agents, tool):
    names = set()
    for tag in re.findall(r'〔' + tool + r':([^〕]*)〕', agents or ''):
        names.update(part.strip() for part in tag.split(',') if re.fullmatch(r'[A-Za-z0-9_]+', part.strip()))
    return names


def doctor_structure(target, agents, add):
    poms = all_poms(target)
    test = target / ARCHUNIT / 'ArchitectureTest.java'
    archunit_rules = tags(agents, 'ArchUnit')
    if test.is_file() and 'archunit' not in poms:
        add('fail', f'{ARCHUNIT}ArchitectureTest.java exists but no pom.xml has the archunit-junit5 dependency '
                    f'({POM_SNIPPET}): test compilation fails')
    elif archunit_rules and not test.is_file():
        add('warn', 'AGENTS.md says ArchUnit checks the layers, but src/test/java/ArchitectureTest.java is missing: only '
                    f"guard's import check runs (install with --with-archunit and add {POM_SNIPPET})")
    elif archunit_rules:
        source = test.read_text(encoding='utf-8', errors='replace')
        missing = sorted(name for name in archunit_rules if not re.search(r'\bArchRule\s+' + name + r'\b', source))
        add('fail' if missing else 'ok', f'AGENTS.md tags ArchUnit rules missing from ArchitectureTest.java: {missing}'
            if missing else f'ArchitectureTest.java defines the {len(archunit_rules)} ArchUnit rule(s) AGENTS.md tags')
    pmd_rules = tags(agents, 'PMD')
    jsp = next((p for p in target.rglob('*.jsp')
                if not {'target', 'node_modules', '.git'}.intersection(p.relative_to(target).parts)), None)
    if not pmd_rules or jsp is None:
        return
    ruleset = target / 'config/pmd/jsp-ruleset.xml'
    if 'config/pmd/jsp-ruleset.xml' not in poms or not ruleset.is_file():
        add('warn', 'AGENTS.md says PMD checks JSP output escaping, but no pom.xml runs config/pmd/jsp-ruleset.xml: '
                    f'unescaped EL in JSP is not detected (add the maven-pmd-plugin from {POM_SNIPPET})')
        return
    text = ruleset.read_text(encoding='utf-8', errors='replace')
    missing = sorted(name for name in pmd_rules if '/' + name + '"' not in text)
    add('fail' if missing else 'ok', f'AGENTS.md tags PMD rules missing from config/pmd/jsp-ruleset.xml: {missing}'
        if missing else f'PMD runs the {len(pmd_rules)} JSP rule(s) AGENTS.md tags')


def doctor_codeowners(target, add):
    """Changes to guard rules, the baseline and AI rules should need a person's approval (Copilot has no ask rules)."""
    path = next((target / p for p in ('.github/CODEOWNERS', 'CODEOWNERS', 'docs/CODEOWNERS') if (target / p).is_file()), None)
    if path is None:
        add('warn', 'no CODEOWNERS: changes to guard rules, the baseline and AI rules need no human approval '
                    '(see .github/CODEOWNERS.example; Copilot is not bound by .claude/settings.json)')
        return
    rules = [line.split() for line in path.read_text(encoding='utf-8', errors='replace').splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    if any('@OWNER' in parts for parts in rules):
        add('fail', f'{path.relative_to(target).as_posix()} still has the @OWNER placeholder')
        return
    covered = any(parts[0] in ('*', '/config/', '/config/guard/', 'config/guard/', '/config/guard/**') for parts in rules)
    add('ok' if covered else 'warn', f'{path.relative_to(target).as_posix()} covers config/guard/' if covered
        else f'{path.relative_to(target).as_posix()} has no owner for /config/guard/: guard rules and the baseline '
             'can change without a required reviewer')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='scope', required=True)
    project = sub.add_parser('project', help='merge templates/project into a target project')
    project.add_argument('target', type=Path)
    user = sub.add_parser('user', help='install templates/user/skills into ~/.claude/skills')
    user.add_argument('--claude-dir', type=Path, default=Path.home() / '.claude')
    project.add_argument('--with-screen-tests', action='store_true',
                         help='also install screen-tests/ (a Node project that pins the screen-test framework)')
    project.add_argument('--with-copilot-cloud-agent', action='store_true',
                         help='also install .github/workflows/copilot-setup-steps.yml.example (GitHub Copilot cloud agent only)')
    project.add_argument('--with-archunit', action='store_true',
                         help='also install src/test/java/ArchitectureTest.java (needs the dependency in config/quality/pom-snippet.xml)')
    project.add_argument('--with-workflows', action='store_true',
                         help='also install .github/workflows/ (they need secrets and repository permissions)')
    check = sub.add_parser('doctor', help='check a project that already has the templates (read-only)')
    check.add_argument('target', type=Path)
    for p in (project, user):
        p.add_argument('--apply', action='store_true', help='write changes (default: dry run)')
        p.add_argument('--diff', action='store_true', help='print a unified diff for every conflict')
    args = parser.parse_args(argv)

    if args.scope == 'doctor':
        target = args.target.expanduser().resolve()
        if not target.is_dir():
            parser.error(f'target is not a directory: {target}')
        findings = doctor(target)
        for level, message in findings:
            print(f'{level:<4}  {message}')
        counts = {level: sum(found == level for found, _ in findings) for level in ('ok', 'warn', 'fail')}
        print('\n' + ', '.join(f'{level}: {count}' for level, count in counts.items()))
        return 1 if counts['fail'] else 0

    if args.scope == 'project':
        target = args.target.expanduser().resolve()
        if not target.is_dir():
            parser.error(f'target is not a directory: {target}')
        if target == ROOT or ROOT in target.parents:
            parser.error('target must be a project outside this template repository')
        if not (target / 'pom.xml').is_file():
            print('warning: no pom.xml in target; templates assume a Maven project', file=sys.stderr)
        if not ((target / 'mvnw').is_file() or (target / 'mvnw.cmd').is_file()):
            print('warning: no Maven Wrapper (mvnw / mvnw.cmd) in target', file=sys.stderr)
        actions = plan_project(target, args.with_workflows, args.with_screen_tests, args.with_archunit,
                               args.with_copilot_cloud_agent)
    else:
        actions = plan_user(args.claude_dir.expanduser().resolve())

    if args.apply:
        apply(actions)
    report(actions, args.apply, show_diff=args.diff)
    return 1 if any(a.kind == 'error' for a in actions) else 0


if __name__ == '__main__':
    sys.exit(main())
