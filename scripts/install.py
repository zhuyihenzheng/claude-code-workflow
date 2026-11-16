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
* .github/workflows/*      -> optional (only with --with-workflows: they run
  with repository permissions and need secrets)

Exit code: 0 on success, 1 if a file could not be written.

Usage:
    python3 scripts/install.py project /path/to/project [--apply] [--diff] [--with-workflows]
    python3 scripts/install.py user [--claude-dir ~/.claude] [--apply] [--diff]
"""
import argparse
import difflib
import json
import os
import re
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT_TEMPLATES = ROOT / 'templates/project'
USER_SKILLS = ROOT / 'templates/user/skills'
USER_LICENSE = USER_SKILLS / 'LICENSE-mattpocock-skills'
JSON_MERGE = {'.claude/settings.json', '.mcp.json'}
LINE_MERGE = {'.gitignore', '.gitattributes'}
# Workflows act on the repository as soon as they are committed, so they are opt-in.
WORKFLOWS = '.github/workflows/'
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
            have = permissions.get(key, [])
            if not isinstance(have, list):
                raise ValueError(f'"permissions.{key}" is not a list')
            if not all(isinstance(rule, str) for rule in have):
                raise ValueError(f'"permissions.{key}" contains non-string rules')
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


def plan_project(target, with_workflows=False):
    actions = []
    for rel, source in template_files(PROJECT_TEMPLATES):
        dest = target / rel
        if rel.startswith(WORKFLOWS) and not with_workflows and not os.path.lexists(dest):
            actions.append(Action('optional', rel, source, dest, note='not installed; pass --with-workflows'))
            continue
        kind = 'json' if rel in JSON_MERGE else 'lines' if rel in LINE_MERGE else None
        actions.append(plan_file(rel, source, dest, kind))
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='scope', required=True)
    project = sub.add_parser('project', help='merge templates/project into a target project')
    project.add_argument('target', type=Path)
    user = sub.add_parser('user', help='install templates/user/skills into ~/.claude/skills')
    user.add_argument('--claude-dir', type=Path, default=Path.home() / '.claude')
    project.add_argument('--with-workflows', action='store_true',
                         help='also install .github/workflows/ (they need secrets and repository permissions)')
    for p in (project, user):
        p.add_argument('--apply', action='store_true', help='write changes (default: dry run)')
        p.add_argument('--diff', action='store_true', help='print a unified diff for every conflict')
    args = parser.parse_args(argv)

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
        actions = plan_project(target, args.with_workflows)
    else:
        actions = plan_user(args.claude_dir.expanduser().resolve())

    if args.apply:
        apply(actions)
    report(actions, args.apply, show_diff=args.diff)
    return 1 if any(a.kind == 'error' for a in actions) else 0


if __name__ == '__main__':
    sys.exit(main())
