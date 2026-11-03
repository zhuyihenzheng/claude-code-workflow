#!/usr/bin/env python3
"""Non-destructive installer for the workflow templates.

Default is a dry run that prints the plan; pass --apply to write.
Existing files are never overwritten:

* missing file             -> create (byte-for-byte copy)
* identical file           -> skip
* settings.json / .mcp.json -> merge (union of permission rules, add missing
  MCP servers; existing values win, ``hooks`` is never added)
* .gitignore / .gitattributes -> merge (append missing lines)
* any other differing file -> conflict (left untouched, compare manually)

Usage:
    python3 scripts/install.py project /path/to/project [--apply]
    python3 scripts/install.py user [--claude-dir ~/.claude] [--apply]
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT_TEMPLATES = ROOT / 'templates/project'
USER_SKILLS = ROOT / 'templates/user/skills'
USER_LICENSE = USER_SKILLS / 'LICENSE-mattpocock-skills'
JSON_MERGE = {'.claude/settings.json', '.mcp.json'}
LINE_MERGE = {'.gitignore', '.gitattributes'}
PERMISSION_LISTS = ('allow', 'deny', 'ask')
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
            added = [rule for rule in wanted if rule not in have]
            if added:
                permissions[key] = have + added
        allowed = set(permissions.get('allow', []))
        for key in ('deny', 'ask'):
            for rule in template['permissions'].get(key, []):
                if rule in allowed:
                    notes.append(f'existing allow also contains {key} rule {rule!r}; review it')
        broad = [r for r in allowed if r.rstrip().endswith(('mvnw *)', 'mvnw.cmd *)'))]
        notes.extend(f'broad rule {r!r} also allows deploy/arbitrary goals; consider removing' for r in sorted(broad))
        merged['permissions'] = permissions
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


def merge_lines(existing_text, template_text):
    have = {line.strip() for line in existing_text.splitlines()}
    missing = [line for line in template_text.splitlines() if line.strip() and line.strip() not in have]
    if not missing:
        return None
    newline = '\r\n' if '\r\n' in existing_text else '\n'
    prefix = existing_text if not existing_text or existing_text.endswith(('\n', '\r')) else existing_text + newline
    return prefix + newline.join(missing) + newline


def plan_file(rel, source, dest, merge_kind=None):
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
        except (ValueError, UnicodeDecodeError) as error:
            return Action('conflict', rel, source, dest, note=f'cannot merge JSON: {error}')
        note = '; '.join(notes)
        if merged == existing:
            return Action('skip', rel, source, dest, note=note)
        return Action('merge', rel, source, dest, content=dump_json(merged), note=note)
    if merge_kind == 'lines':
        try:
            merged = merge_lines(dst_bytes.decode('utf-8'), src_bytes.decode('utf-8'))
        except UnicodeDecodeError as error:
            return Action('conflict', rel, source, dest, note=f'cannot merge lines: {error}')
        if merged is None:
            return Action('skip', rel, source, dest)
        return Action('merge', rel, source, dest, content=merged)
    return Action('conflict', rel, source, dest, note='differs from template; compare and merge manually')


def plan_project(target):
    actions = []
    for rel, source in template_files(PROJECT_TEMPLATES):
        kind = 'json' if rel in JSON_MERGE else 'lines' if rel in LINE_MERGE else None
        actions.append(plan_file(rel, source, target / rel, kind))
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
    for action in actions:
        if action.kind not in ('create', 'merge'):
            continue
        action.dest.parent.mkdir(parents=True, exist_ok=True)
        if action.kind == 'create':
            shutil.copyfile(action.source, action.dest)
            if os.access(action.source, os.X_OK):
                shutil.copymode(action.source, action.dest)
        else:
            with open(action.dest, 'w', encoding='utf-8', newline='') as handle:
                handle.write(action.content)


def report(actions, applied, out=None):
    out = out or sys.stdout
    width = max((len(a.kind) for a in actions), default=0)
    for action in actions:
        line = f'{action.kind.ljust(width)}  {action.rel}'
        if action.note:
            line += f'  ({action.note})'
        print(line, file=out)
    counts = {kind: sum(a.kind == kind for a in actions) for kind in ('create', 'merge', 'skip', 'conflict')}
    print('\n' + ', '.join(f'{k}: {v}' for k, v in counts.items()), file=out)
    if not applied and (counts['create'] or counts['merge']):
        print('Dry run only. Re-run with --apply to write create/merge actions.', file=out)
    if counts['conflict']:
        print('Conflicts were not modified; compare them with the template under templates/.', file=out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='scope', required=True)
    project = sub.add_parser('project', help='merge templates/project into a target project')
    project.add_argument('target', type=Path)
    user = sub.add_parser('user', help='install templates/user/skills into ~/.claude/skills')
    user.add_argument('--claude-dir', type=Path, default=Path.home() / '.claude')
    for p in (project, user):
        p.add_argument('--apply', action='store_true', help='write changes (default: dry run)')
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
        actions = plan_project(target)
    else:
        actions = plan_user(args.claude_dir.expanduser().resolve())

    if args.apply:
        apply(actions)
    report(actions, args.apply)
    return 0


if __name__ == '__main__':
    sys.exit(main())
